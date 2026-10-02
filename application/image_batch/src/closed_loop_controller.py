"""Repeated causal forecast, native evaluation and guarded warm-reserve admission."""

import copy
import json
import resource
import subprocess
import time
import uuid

from closed_loop_guards import (
    IncompleteMembership,
    guard_action,
    reactive_action,
    reconcile_pending,
    snapshot_view,
)
from closed_loop_journal import Journal
from demo_configuration import EXPERIMENT_DEFAULTS
from closed_loop_policy import select_action
from closed_loop_runner import load_scores, prepare_runner, run_control_plane_suite
from forecast_trace import milliseconds
from forecast_workload import Settings, run_once
from opendc_inputs import write_json
from opendc_scenarios import prepare_suite


LATEST_STATE = """import json,pathlib,sys
p=pathlib.Path('/var/lib/opendt/cluster-state.jsonl')
with p.open('rb') as f:
 f.seek(0,2);end=f.tell();size=min(end,1048576)
 while True:
  f.seek(end-size);lines=f.read(size).split(b'\\n')
  complete=lines[:-1]
  if len(complete)>1 or size==end:break
  size=min(end,size*2)
 for line in reversed(complete):
  try:value=json.loads(line)
  except (ValueError,UnicodeDecodeError):continue
  print(json.dumps(value));break
 else:sys.exit('no complete observer state')
"""


def failure_category(error):
    """Classify a recorded failure without converting it into a valid hold.

    Args:
        error (Exception): Forecast, transport, native or observation failure.

    Returns:
        str: Stable diagnostic group; the original exception text is also retained.
    """
    message = str(error).lower()
    if isinstance(error, subprocess.TimeoutExpired) or any(
        word in message for word in ("timeout", "timed out", "outer deadline")
    ):
        return "timeout"
    if any(word in message for word in ("stale", "decision age", "future timestamp")):
        return "stale_input_or_decision"
    if any(
        word in message
        for word in ("membership", "incomplete", "forecast not ready", "unreconciled")
    ):
        return "incomplete_input"
    return "native_or_transport_failure"


def last_tick(journal, directory):
    """Recover the last reserved cycle without overwriting orphaned crash evidence.

    Args:
        journal (Journal): Durable controller records.
        directory (Path): Controller evidence containing any already-created cycle folders.

    Returns:
        int: Highest journaled or physically reserved cycle identity.
    """
    recorded = [row["tick"] for row in journal.records if row["event"] == "cycle.begin"]
    reserved = [int(path.name[6:]) for path in directory.glob("cycle-*") if path.name[6:].isdigit()]
    return max([0, *recorded, *reserved])


def actuate(session, journal, before, fresh, proposal, config, *, cutoff_seconds):
    """Journal then atomically guard one cordon/uncordon against node replacement.

    The Kubernetes resourceVersion test detects changes between the final node
    read and the patch. A lost acknowledgement leaves the intent unresolved;
    callers must observe its result before any subsequent physical action.

    Args:
        session (CaptureSession): Explicit cluster connection and isolated namespace.
        journal (Journal): Exclusively owned durable action history.
        before (dict): State used to prepare the proposal.
        fresh (dict): Validated fresh pre-action state.
        proposal (dict): Capacity action and explicit worker target.
        config (dict): Worker inventory and approved capacity bounds.
        cutoff_seconds (float): Original proposal cutoff in UTC epoch seconds.

    Returns:
        dict: Acknowledged action identity and timestamp.

    Raises:
        ValueError: State, action age, worker identity or pending journal intent is unsafe.
        RuntimeError: The API call failed or its acknowledgement was lost.
    """
    if journal.pending_action():
        raise ValueError("an unresolved action must be reconciled before another request")
    guard_action(before, fresh, proposal, config, decision_age=time.time() - cutoff_seconds)
    worker = proposal["selected_worker"]
    node = session.get("node", worker)
    if (
        node["metadata"]["uid"] != fresh["nodes"][worker]["uid"]
        or bool(node["spec"].get("unschedulable")) == fresh["nodes"][worker]["accepting"]
    ):
        raise ValueError("target node identity or admission state changed before patch")
    if not any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in node.get("status", {}).get("conditions", [])
    ):
        raise ValueError("target node is no longer Ready")
    # Recheck after the potentially slow API read; stale proposals never reach mutation.
    guard_action(before, fresh, proposal, config, decision_age=time.time() - cutoff_seconds)
    if time.time() - fresh["collection_started_seconds"] > 3:
        raise ValueError("pre-action observation became stale during the node read")
    action_id = uuid.uuid4().hex
    request = journal.append(
        "action.request",
        action_id=action_id,
        action=proposal["action"],
        selected_worker=worker,
        node_uid=node["metadata"]["uid"],
        resource_version=node["metadata"]["resourceVersion"],
        cutoff_seconds=cutoff_seconds,
    )
    try:
        guard_action(before, fresh, proposal, config, decision_age=time.time() - cutoff_seconds)
        if time.time() - fresh["collection_started_seconds"] > 3:
            raise ValueError("pre-action observation became stale while persisting intent")
    except ValueError:
        journal.append("action.result", action_id=action_id, status="not_dispatched_stale")
        raise
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": request["node_uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": request["resource_version"]},
        {"op": "add", "path": "/spec/unschedulable", "value": proposal["action"] == "scale-down"},
    ]
    try:
        reply = session.kubectl("patch", "node", worker, "--type=json", "-p", json.dumps(patch))
    except Exception as exc:
        journal.append("action.uncertain", action_id=action_id, error=str(exc))
        raise
    return journal.append(
        "action.result",
        action_id=action_id,
        status="acknowledged",
        last_action_at=time.time(),
        reply=reply.decode(),
    )


class Controller:
    """Own one sequential controller with durable evidence and causal workload warmup.

    Args:
        session (CaptureSession): Prepared isolated capture and its command-line settings.

    Raises:
        ValueError: Configuration conflicts with a previously recorded controller identity.
    """

    def __init__(self, session):
        self.session = session
        self.args = session.args
        self.output = session.output / "controller"
        self.output.mkdir(exist_ok=True)
        self.config = {
            **{
                name: getattr(self.args, name, default)
                for name, default in EXPERIMENT_DEFAULTS.items()
            },
            "modeled_reserve_acquisition_seconds": 0,
            "workers": [
                dict(
                    node_name=name,
                    configured_cores=self.args.worker_cores,
                    memory_mib=self.args.worker_memory_mib,
                )
                for name in self.args.workers
            ],
            "minimum_workers": self.args.minimum_workers,
            "maximum_workers": self.args.maximum_workers,
            "occupancy_model": "causal-occupancy-v1",
            "residual_margin_seconds": self.args.residual_margin_seconds,
            "reactive_up_threshold": self.args.reactive_up_threshold,
            "reactive_down_threshold": self.args.reactive_down_threshold,
        }
        self.cluster = dict(
            controller=self.args.controller,
            runner_host=self.args.controller,
            key=self.args.ssh_key,
            node=self.args.control_node,
            namespace=session.namespace,
        )
        self.journal = Journal(self.output / "journal.jsonl")
        identity = dict(
            namespace=session.namespace,
            arm=self.args.control_arm,
            config=self.config,
            image=self.args.native_image,
        )
        identity_path = self.output / "identity.json"
        if identity_path.exists():
            previous = json.loads(identity_path.read_text())
            if previous["settings"] != identity:
                self.journal.close()
                raise ValueError("controller settings differ from durable identity")
            self.owner = previous["owner"]
        else:
            self.owner = uuid.uuid4().hex
            write_json(identity_path, dict(owner=self.owner, settings=identity))
        self.history = self.journal.history()
        self.history.pop("reactive_observation", None)
        self.tick_number = last_tick(self.journal, self.output)
        self.next_tick = None
        self.origin = None
        self.template = None
        template_path = self.output / "frozen-template.json"
        if template_path.exists():
            self.template = json.loads(template_path.read_text())
        self.journal.append("controller.start", owner=self.owner, arm=self.args.control_arm)

    def prepare(self, *, stage_runner=True):
        """Claim namespace ownership and stage native dependencies before measured arrivals.

        Args:
            stage_runner (bool): Stage the native image only before initial measured arrivals.

        Raises:
            ValueError: Another controller owns this namespace.
        """
        found = json.loads(
            self.session.kubectl(
                "get",
                "configmap",
                "closed-loop-owner",
                "-n",
                self.session.namespace,
                "--ignore-not-found",
                "-o",
                "json",
            )
            or b"null"
        )
        if found:
            if found.get("data", {}).get("owner") != self.owner:
                raise ValueError("another controller owns this namespace")
        else:
            self.session.kubectl(
                "create",
                "configmap",
                "closed-loop-owner",
                "-n",
                self.session.namespace,
                "--from-literal=owner=" + self.owner,
            )
        if self.args.control_arm == "forecast" and stage_runner:
            prepare_runner(
                self.args.native_image,
                self.cluster,
                self.output / ("runner-preflight-" + uuid.uuid4().hex),
            )

    def fresh(self):
        """Read and validate the latest complete observer state through one bounded call.

        Returns:
            dict: Fresh complete allocation, queue and node inventory.
        """
        snapshot = json.loads(
            self.session.kubectl(
                "exec",
                "-n",
                self.session.namespace,
                self.session.pod_name,
                "-c",
                "opendt-observer",
                "--",
                "python",
                "-c",
                LATEST_STATE,
            )
        )
        return snapshot_view(snapshot, self.config, now_seconds=time.time())

    def recover(self, view):
        """Resolve uncertain prior intent from current state without repeating its API call.

        Args:
            view (dict): Fresh validated physical state.
        """
        pending = self.journal.pending_action()
        if pending:
            status = reconcile_pending(pending, view)
            # Reconciliation resolves intent; current guards decide subsequent eligibility.
            now = time.time()
            self.journal.append(
                "action.result",
                action_id=pending["action_id"],
                status=status,
                attribution="uncertain_after_reconciliation",
                last_action_at=now,
            )
            self.history.update(last_action_at=now)
            self.history.pop("reactive_observation", None)

    def discover_origin(self):
        """Read the sender's preserved schedule without taking a controller action."""
        if self.origin is None:
            for line in (self.session.output / "endpoint.jsonl").read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event_type") == "schedule.ready":
                    self.origin = milliseconds(event["details"]["schedule_start_timestamp"]) / 1000
                    self.next_tick = (
                        self.origin + self.args.period_seconds * self.args.warmup_cycles + 5
                    )
                    break

    def maybe_tick(self):
        """Run at most one due cycle, skipping missed ticks rather than overlapping work."""
        self.discover_origin()
        if self.origin is None or time.time() < self.next_tick:
            return
        # Evaluation includes drain follow-up; arrivals themselves remain independent.
        self.cycle()
        cadence = self.config.get("cadence_seconds", 60)
        self.next_tick += cadence
        if self.next_tick <= time.time():
            skipped = int((time.time() - self.next_tick) // cadence) + 1
            self.next_tick += skipped * cadence
            self.history.pop("reactive_observation", None)
            self.journal.append("cycle.skipped", count=skipped, reason="nonoverlapping_cadence")

    def predict(self, directory):
        """Retry one incomplete preparation with a new prefix, retaining the rejected evidence.

        This bounded two-second wait addresses a non-atomic Job-list race only.
        It never retries native computation or accepts an incomplete snapshot.
        The selected prefix's cutoff governs decision age; cycle wall time includes
        both attempts, and rejected preparation remains available for diagnostics.

        Args:
            directory (Path): New cycle evidence directory.

        Returns:
            tuple: Complete proposal state, scores and the selected prefix's cutoff.

        Raises:
            ValueError: Preparation remains invalid after the single allowed recollection.
            RuntimeError: Native or collection operations fail.
        """
        started = time.monotonic()
        try:
            return self._predict_once(directory)
        except IncompleteMembership as exc:
            self.history.pop("reactive_observation", None)
            rejected = directory / "rejected-preparation"
            rejected.mkdir()
            for name in ("observer", "observer.tar", "forecast"):
                source = directory / name
                if source.exists():
                    source.rename(rejected / name)
            self.journal.append(
                "observation.retry",
                tick=self.tick_number,
                phase="forecast_preparation",
                reason=str(exc),
                wait_seconds=2,
                rejected_directory=str(rejected),
            )
            time.sleep(2)
        recollection = time.monotonic() - started
        result = self._predict_once(directory)
        timing_path = directory / "stage-timing.json"
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        timing["rejected_preparation_and_wait_seconds"] = recollection
        write_json(timing_path, timing)
        return result

    def _predict_once(self, directory):
        """Freeze a causal prefix and evaluate all complete shared-future capacity choices.

        Args:
            directory (Path): New cycle evidence directory.

        Returns:
            tuple: Proposal state, scores and effective cutoff in epoch seconds.

        Raises:
            ValueError: The forecast, membership or native results are incomplete.
        """
        started = time.monotonic()
        prefix = directory / "observer"
        self.session.archive_observer(prefix)
        collected = time.monotonic()
        captured_at = time.time()
        settings = Settings(
            run_id=self.session.namespace,
            origin_ms=round(self.origin * 1000),
            period_seconds=self.args.period_seconds,
            warmup_periods=self.args.warmup_cycles,
            horizon_seconds=self.config.get("horizon_seconds", 60),
            scenarios=self.config.get("scenarios", 3),
            seed=self.config.get("scenario_seed", 20261008) + self.tick_number,
        )
        forecast_dir = directory / "forecast"
        status, selected = run_once(
            prefix,
            forecast_dir,
            round(captured_at * 1000),
            settings,
            self.template,
            simulation_inputs=True,
        )
        if status["status"] != "ready" or status["simulation_inputs"]["status"] != "ready":
            raise ValueError("forecast not ready: " + json.dumps(status.get("simulation_inputs")))
        state = json.loads((forecast_dir / "state.json").read_text())
        # Initial freshness belongs to collection; computation ages the separately guarded decision.
        before = snapshot_view(state, self.config, now_seconds=captured_at)
        if self.template is None:
            self.template = selected
            write_json(self.output / "frozen-template.json", selected)
        config = {
            **copy.deepcopy(self.config),
            "active_workers": before["active_workers"],
            "draining_workers": before["draining_workers"],
        }
        write_json(
            directory / "collection-timing.json",
            {
                "collected_at_seconds": captured_at,
                "state_seconds": before["timestamp_seconds"],
                "prepared_at_seconds": time.time(),
            },
        )
        prepare_suite(forecast_dir, prefix, config, directory / "suite", "pinned-trace")
        prepared = time.monotonic()
        batch = run_control_plane_suite(
            directory / "suite",
            directory / "native",
            self.args.native_image,
            self.cluster,
            f"native-{self.tick_number:04d}",
            timeout_seconds=self.config.get("native_timeout_seconds", 20),
        )
        returned = time.monotonic()
        scores, _ = load_scores(
            batch,
            scenarios=self.config.get("scenarios", 3),
            allocation_seconds=self.config.get("allocation_seconds", 120),
        )
        write_json(
            directory / "stage-timing.json",
            dict(
                observer_collection_seconds=collected - started,
                forecast_preparation_seconds=prepared - collected,
                native_and_collection_seconds=returned - prepared,
                score_validation_seconds=time.monotonic() - returned,
            ),
        )
        write_json(directory / "scores.json", scores)
        return before, scores, milliseconds(status["cutoff"]) / 1000

    def cycle(self):
        """Observe, evaluate, select, guard, actuate and record one nonoverlapping cycle."""
        usage_before = resource.getrusage(resource.RUSAGE_SELF)
        self.tick_number += 1
        directory = self.output / f"cycle-{self.tick_number:04d}"
        directory.mkdir()
        started = time.time()
        self.journal.append("cycle.begin", tick=self.tick_number, started_at=started)
        valid = False
        proposal = {"action": "unchanged", "selected_worker": None, "reason": "unavailable_state"}
        outcome = "held"
        try:
            before = self.fresh()
            self.recover(before)
            cutoff = before["timestamp_seconds"]
            reactive = reactive_action(
                before,
                self.history,
                now_seconds=time.time(),
                fallback=False,
                tick_id=self.tick_number,
            )
            self.history = reactive["state"]
            if self.args.control_arm == "forecast":
                try:
                    before, scores, cutoff = self.predict(directory)
                    age = time.time() - cutoff
                    proposal = select_action(
                        scores,
                        self.history,
                        now_seconds=time.time(),
                        decision_age=age,
                        scenarios=self.config.get("scenarios", 3),
                        age_budget_seconds=self.config.get("decision_age_seconds", 30),
                        deadline_seconds=self.config.get("deadline_seconds", 120),
                        deadline_fraction=self.config.get("deadline_fraction", 0.95),
                    )
                    valid = age <= self.config.get("decision_age_seconds", 30) and any(
                        item["candidate"] == "unchanged" and item["valid"]
                        for item in proposal.get("scores", [])
                    )
                    if not valid:
                        raise ValueError("native decision invalid or exceeds decision age budget")
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    self.journal.append(
                        "forecast.invalid",
                        tick=self.tick_number,
                        error=str(exc),
                        category=failure_category(exc),
                    )
                    self.journal.append(
                        "fallback.invoked",
                        tick=self.tick_number,
                        reason=str(exc),
                        category=failure_category(exc),
                    )
                    before = self.fresh()
                    cutoff = before["timestamp_seconds"]
                    proposal = reactive_action(
                        before,
                        self.history,
                        now_seconds=time.time(),
                        fallback=True,
                        tick_id=self.tick_number,
                    )
            elif self.args.control_arm == "reactive":
                proposal = reactive
                valid = True
            else:
                proposal = {
                    "action": "unchanged",
                    "selected_worker": None,
                    "reason": "fixed_full_capacity",
                    "state": self.history,
                }
                valid = True
            self.history = proposal["state"]
            self.journal.append(
                "cycle.proposal",
                tick=self.tick_number,
                proposal=proposal,
                before=before,
                cutoff_seconds=cutoff,
                shadow=False,
                forecast_valid=valid,
            )
            if proposal["action"] != "unchanged":
                action_started = time.monotonic()
                fresh = self.fresh()
                result = actuate(
                    self.session,
                    self.journal,
                    before,
                    fresh,
                    proposal,
                    self.config,
                    cutoff_seconds=cutoff,
                )
                self.journal.append(
                    "action.timing",
                    tick=self.tick_number,
                    action_id=result.get("action_id"),
                    guard_and_api_seconds=time.monotonic() - action_started,
                )
                self.history.update(last_action_at=result["last_action_at"])

                self.history.pop("reactive_observation", None)
                outcome = "acknowledged"
            observed = self.fresh()
            confirmed = None
            if outcome == "acknowledged":
                deadline = time.monotonic() + 3
                while True:
                    target = proposal["selected_worker"]
                    confirmed = (
                        observed["timestamp_seconds"] >= self.history["last_action_at"]
                        and observed["nodes"][target]["uid"] == before["nodes"][target]["uid"]
                        and observed["nodes"][target]["accepting"]
                        == (proposal["action"] == "scale-up")
                    )
                    if confirmed or time.monotonic() >= deadline:
                        break
                    time.sleep(0.2)
                    observed = self.fresh()
            self.journal.append(
                "cycle.observed", tick=self.tick_number, state=observed, action_observed=confirmed
            )
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            outcome = "vetoed_or_failed"
            self.history.pop("reactive_observation", None)
            self.journal.append(
                "cycle.error",
                tick=self.tick_number,
                error=str(exc),
                category="action_cancelled"
                if proposal["action"] != "unchanged" and isinstance(exc, ValueError)
                else failure_category(exc),
            )
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        self.journal.append(
            "cycle.end",
            tick=self.tick_number,
            outcome=outcome,
            forecast_valid=valid,
            history=self.history,
            elapsed_seconds=time.time() - started,
            controller_cpu_seconds=(
                usage_after.ru_utime
                + usage_after.ru_stime
                - usage_before.ru_utime
                - usage_before.ru_stime
            ),
            controller_process_peak_rss_kib=usage_after.ru_maxrss,
        )

    def close(self):
        """Close durable ownership when the enclosing measured capture stops."""
        self.journal.close()
