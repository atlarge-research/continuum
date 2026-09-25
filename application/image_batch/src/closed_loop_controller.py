"""Repeated causal forecast, native evaluation and guarded warm-reserve admission."""

import copy
import json
import resource
import subprocess
import time
import uuid

from closed_loop_guards import guard_action, reactive_action, reconcile_pending, snapshot_view
from closed_loop_journal import Journal
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


def shadow_progress(completed, valid):
    """Require two consecutive verified cycles before the first physical proposal.

    Args:
        completed (int): Consecutive valid shadow cycles, capped at two.
        valid (bool): Whether the current forecast and native evaluation are complete.

    Returns:
        tuple[int, bool]: Updated progress and whether this cycle remains shadow-only.
    """
    if completed >= 2:
        return 2, False
    return (min(2, completed + 1) if valid else 0), True


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
        dict: Acknowledged action identity and cooldown timestamp.

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
    """Own one sequential controller with durable evidence and two shadow cycles.

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
        self.history.update(down_worker=None, down_wins=0)
        self.shadow = 0
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
            # Both outcomes receive a conservative cooldown after uncertain mutation.
            now = time.time()
            self.journal.append(
                "action.result",
                action_id=pending["action_id"],
                status=status,
                attribution="uncertain_after_reconciliation",
                last_action_at=now,
            )
            self.history.update(last_action_at=now, down_worker=None, down_wins=0)
            self.shadow = 0

    def maybe_tick(self):
        """Run at most one due cycle, skipping missed ticks rather than overlapping work."""
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
        if self.origin is None or time.time() < self.next_tick:
            return
        # Evaluation includes drain follow-up; arrivals themselves remain independent.
        self.cycle()
        self.next_tick += 60
        if self.next_tick <= time.time():
            skipped = int((time.time() - self.next_tick) // 60) + 1
            self.next_tick += skipped * 60
            self.history.update(down_worker=None, down_wins=0)
            self.journal.append("cycle.skipped", count=skipped, reason="nonoverlapping_cadence")

    def predict(self, directory):
        """Freeze a causal prefix and evaluate all complete shared-future capacity choices.

        Args:
            directory (Path): New cycle evidence directory.

        Returns:
            tuple: Proposal state, scores and effective cutoff in epoch seconds.

        Raises:
            ValueError: The forecast, membership or native results are incomplete.
        """
        prefix = directory / "observer"
        self.session.archive_observer(prefix)
        captured_at = time.time()
        settings = Settings(
            run_id=self.session.namespace,
            origin_ms=round(self.origin * 1000),
            period_seconds=self.args.period_seconds,
            warmup_periods=self.args.warmup_cycles,
            horizon_seconds=60,
            scenarios=3,
            seed=20261008 + self.tick_number,
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
        if self.template is None:
            self.template = selected
            write_json(self.output / "frozen-template.json", selected)
        state = json.loads((forecast_dir / "state.json").read_text())
        # Initial freshness belongs to collection; computation ages the separately guarded decision.
        before = snapshot_view(state, self.config, now_seconds=captured_at)
        config = {
            **copy.deepcopy(self.config),
            "active_workers": before["active_workers"],
            "draining_workers": before["draining_workers"],
        }
        wins = self.history.get("down_wins", 0)
        if isinstance(wins, int) and not isinstance(wins, bool) and wins > 0:
            config["preferred_down_worker"] = self.history.get("down_worker")
        write_json(
            directory / "collection-timing.json",
            {
                "collected_at_seconds": captured_at,
                "state_seconds": before["timestamp_seconds"],
                "prepared_at_seconds": time.time(),
            },
        )
        prepare_suite(forecast_dir, prefix, config, directory / "suite", "pinned-trace")
        batch = run_control_plane_suite(
            directory / "suite",
            directory / "native",
            self.args.native_image,
            self.cluster,
            f"native-{self.tick_number:04d}",
        )
        scores, _ = load_scores(batch)
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
            if self.args.control_arm == "forecast":
                try:
                    before, scores, cutoff = self.predict(directory)
                    age = time.time() - cutoff
                    proposal = select_action(
                        scores, self.history, now_seconds=time.time(), decision_age=age
                    )
                    valid = age <= 30 and any(
                        item["candidate"] == "unchanged" and item["valid"]
                        for item in proposal.get("scores", [])
                    )
                    if not valid:
                        raise ValueError("native decision invalid or older than 30 seconds")
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    self.journal.append("forecast.invalid", tick=self.tick_number, error=str(exc))
                    before = self.fresh()
                    cutoff = before["timestamp_seconds"]
                    proposal = reactive_action(
                        before, self.history, now_seconds=time.time(), fallback=True
                    )
            elif self.args.control_arm == "reactive":
                proposal = reactive_action(
                    before, self.history, now_seconds=time.time(), fallback=False
                )
                valid = True
            else:
                proposal = {
                    "action": "unchanged",
                    "selected_worker": None,
                    "reason": "fixed_full_capacity",
                    "state": self.history,
                }
                valid = True
            shadow_only = False
            if self.args.control_arm == "forecast":
                self.shadow, shadow_only = shadow_progress(self.shadow, valid)
            self.history = proposal["state"]
            self.journal.append(
                "cycle.proposal",
                tick=self.tick_number,
                proposal=proposal,
                before=before,
                cutoff_seconds=cutoff,
                shadow=shadow_only,
                forecast_valid=valid,
            )
            if proposal["action"] != "unchanged" and not shadow_only:
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
                self.history.update(
                    last_action_at=result["last_action_at"], down_worker=None, down_wins=0
                )
                outcome = "acknowledged"
            elif shadow_only:
                outcome = "shadow"
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
            if self.shadow < 2:
                self.shadow = 0
            self.history.update(down_worker=None, down_wins=0)
            self.journal.append("cycle.error", tick=self.tick_number, error=str(exc))
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
