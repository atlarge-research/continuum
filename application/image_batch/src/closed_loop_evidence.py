"""Cohort-complete physical outcomes and allocation for matched closed-loop captures."""

import argparse
from collections import Counter

import hashlib
import json
import math
from pathlib import Path

from acquisition_evidence import acquisition_history, charge_acquisitions

import numpy as np

from closed_loop_diagnostics import cycle_diagnostic
from closed_loop_guards import snapshot_view
from forecast_trace import bounded_read, milliseconds
from opendc_inputs import write_json
from opendc_validation import read_observations


SCHEMA = "opendc-closed-loop-evidence-v1"


def allocation(states, config, start, end, *, activation_records=None):
    """Integrate accepting plus draining application cores over a common physical window.

    Each observed state holds until the next snapshot only when the gap is at
    most three seconds. Missing Jobs cannot hide accepting capacity: unknown
    assignment may only add draining cost on otherwise empty cordoned workers.
    Unknown intervals are never filled with zero or used to
    establish a cheaper total. Powered worker time is reported separately.

    Args:
        states (list[dict]): Chronological observer cluster-state snapshots.
        config (dict): Explicit worker resources and accepting-worker bounds.
        start (float): Inclusive evaluation boundary in UTC epoch seconds.
        end (float): Exclusive common arrival-window boundary in epoch seconds.
        activation_records (list[dict] or None): Optional durable acquisition journal.

    Returns:
        dict: Complete or explicitly unavailable allocation, coverage and plotted state series.

    Raises:
        ValueError: Evaluation bounds or observation timestamps are invalid.
    """
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("allocation requires finite increasing evaluation bounds")
    points = []
    maximum = sum(worker["configured_cores"] - 1 for worker in config["workers"])
    for state in states:
        at = milliseconds(state["timestamp"]) / 1000
        if points and at <= points[-1]["time"]:
            raise ValueError("allocation observations must have strictly increasing timestamps")
        try:
            membership = state.get("collection", {}).get("missing_job_uids") == []
            inventory = {
                **state,
                "collection": {**state.get("collection", {}), "missing_job_uids": []},
            }
            view = snapshot_view(inventory, config, now_seconds=at)
            lower = view["allocated_application_cores"]
            upper = lower if membership else maximum
            points.append(
                dict(
                    time=at,
                    allocated=lower if lower == upper else None,
                    lower=lower,
                    upper=upper,
                    membership_complete=membership,
                    allocated_workers=view["active_workers"] + view["draining_workers"],
                    accepting=len(view["active_workers"]),
                    draining=len(view["draining_workers"]),
                    powered=view["powered_worker_count"],
                    queue=len(view["queue"]),
                    valid=True,
                )
            )
        except ValueError as exc:
            points.append(dict(time=at, valid=False, error=str(exc)))
    covered, cost, upper_cost, powered = 0.0, 0.0, 0.0, 0.0
    gaps = []
    cursor = start
    for left, right in zip(points, points[1:]):
        lower, upper = max(start, left["time"]), min(end, right["time"])
        if upper <= lower:
            continue
        if lower > cursor:
            gaps.append(dict(start=cursor, end=lower, reason="missing_initial_state"))
            upper_cost += (lower - cursor) * maximum
        if right["time"] - left["time"] <= 3 and left["valid"] and right["valid"]:
            duration = upper - lower
            cost += duration * left["lower"]
            upper_cost += duration * left["upper"]
            powered += duration * left["powered"]
            if left["lower"] == left["upper"]:
                covered += duration
            else:
                gaps.append(
                    dict(start=lower, end=upper, reason="incomplete_membership_allocation_range")
                )
        else:
            gaps.append(dict(start=lower, end=upper, reason="gap_or_invalid_state"))
            upper_cost += (upper - lower) * maximum
        cursor = upper
    if cursor < end:
        gaps.append(dict(start=cursor, end=end, reason="missing_final_state"))
        upper_cost += (end - cursor) * maximum
    complete = not gaps and math.isclose(covered, end - start, abs_tol=1e-6)
    result = dict(
        start_seconds=start,
        end_seconds=end,
        covered_seconds=covered,
        gaps=gaps,
        allocated_application_core_seconds=cost if complete else None,
        powered_worker_seconds=powered if complete else None,
        known_allocated_core_seconds_lower_bound=cost,
        declared_powered_worker_seconds=(end - start) * len(config["workers"]),
        allocated_core_seconds_bounds=[cost, upper_cost],
        incomplete_membership_snapshots=sum(
            row.get("membership_complete") is False for row in points if start <= row["time"] <= end
        ),
        series=[row for row in points if start - 3 <= row["time"] <= end + 3],
        interpretation=(
            "Accepting or draining allocation; warm reserves remain powered. "
            "No physical energy estimate."
        ),
    )
    return charge_acquisitions(result, activation_records or [], maximum)


def responses(observations, start_ms, end_ms, *, deadline_seconds=120, followup_end_ms=None):
    """Score original-creation Job response with failed and unfinished outcomes retained.

    Args:
        observations (list[dict]): Complete physical UID inventory from observer evidence.
        start_ms (int): Inclusive evaluation arrival boundary.
        end_ms (int): Exclusive evaluation arrival boundary.
        deadline_seconds (float): Approved Job-completion target from original creation.
        followup_end_ms (int or None): Last allowed terminal time; default end plus ten minutes.

    Returns:
        dict: Exact cohort, completion/deadline/censoring counts and descriptive response metrics.

    Raises:
        ValueError: A purported successful Job completes before its original creation.
    """
    followup_end_ms = end_ms + 600000 if followup_end_ms is None else followup_end_ms
    cohort = []
    for observed in observations:
        if not start_ms <= observed["creation_ms"] < end_ms:
            continue
        row = dict(observed)
        terminal = row.get("job_finish_ms") or row.get("failure_observed_ms")
        if terminal is not None and terminal > followup_end_ms:
            row.update(status="unfinished", terminal_after_followup_ms=terminal, job_finish_ms=None)
        cohort.append(row)
    completed, failed, censored = [], [], []
    for row in cohort:
        if row["status"] == "Complete" and row.get("job_finish_ms") is not None:
            value = (row["job_finish_ms"] - row["creation_ms"]) / 1000
            if value < 0 or not math.isfinite(value):
                raise ValueError("successful Job has an invalid original-creation response")
            completed.append(value)
        elif row["status"] == "Failed":
            failed.append(row["uid"])
        else:
            censored.append(row["uid"])
    met = sum(value <= deadline_seconds for value in completed)
    warmup = [
        row["uid"]
        for row in observations
        if row["creation_ms"] < start_ms
        and (
            (row.get("job_finish_ms") or row.get("failure_observed_ms")) is None
            or (row.get("job_finish_ms") or row.get("failure_observed_ms")) > start_ms
        )
    ]
    return dict(
        followup_end_ms=followup_end_ms,
        jobs=len(cohort),
        completed=len(completed),
        failed_uids=failed,
        censored_uids=censored,
        deadline_met=met,
        deadline_fraction=met / len(cohort) if cohort else None,
        completed_responses_seconds=completed,
        completed_response_median_seconds=float(np.median(completed)) if completed else None,
        completed_response_p95_seconds=float(np.percentile(completed, 95)) if completed else None,
        warmup_backlog_uids=warmup,
        cohort=cohort,
        interpretation=(
            "Job completion from original creation; quantiles describe completed Jobs only; "
            "failures/censoring remain in the deadline denominator."
        ),
    )


# Cohesive journal reduction retains separate evidence for each failure and action stage.
def controller_outcomes(  # pylint: disable=too-many-locals
    directory, start, end, *, cadence_seconds=60, age_budget_seconds=30, arm=None
):
    """Summarize actual cycle latency, acknowledged intents and observed action identities.

    Successful streaks require valid forecasts and completed feedback. An
    acknowledged action without observer confirmation breaks the streak; later
    reconciliation does not retroactively make that cycle successful.

    Args:
        directory (Path): Controller journal and immutable per-cycle native evidence.
        start (float): Inclusive common evaluation boundary in epoch seconds.
        end (float): Exclusive scoring boundary, including controlled follow-up when requested.
        cadence_seconds (float): Configured interval between scheduled controller checks.
        age_budget_seconds (float): Configured maximum causal decision age.
        arm (str or None): Explicit policy arm, for action-source attribution.

    Returns:
        dict: Complete cycle rows and descriptive latency, CPU and physical-action counts.
    """
    path = directory / "journal.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    acquisitions = acquisition_history(records)
    acquired = {row.get("api_action_id"): row for row in acquisitions if row.get("api_action_id")}
    cycles = {}
    requests = {}
    current = None
    for record in records:
        if record["event"] == "cycle.begin":
            current = record["tick"]
            cycles[current] = dict(tick=current, started_at=record["started_at"], actions=[])
        if current is None:
            continue
        row = cycles[current]
        if record["event"] == "cycle.end":
            if "recorded_at_ns" in record:
                row["outcome_recorded_seconds"] = record["recorded_at_ns"] / 1e9
            row.update(
                {
                    key: value
                    for key, value in record.items()
                    if key not in ("event", "sequence", "recorded_at_ns", "history")
                }
            )
        elif record["event"] == "cycle.proposal":
            row.update(
                proposal=record["proposal"],
                proposal_seconds=record["recorded_at_ns"] / 1e9,
                decision_age_seconds=record["recorded_at_ns"] / 1e9 - record["cutoff_seconds"],
                shadow=record["shadow"],
            )
        elif record["event"] == "observation.retry":
            row.setdefault("observation_retries", []).append(record)
        elif record["event"] == "fallback.invoked":
            row["fallback_invoked"] = True
            row["failure_category"] = record.get("category", "unclassified")
        elif record["event"] == "forecast.invalid":
            row["forecast_error"] = record["error"]
            row["failure_category"] = record.get("category", "unclassified")
        elif record["event"] == "action.timing":
            row["guard_and_api_seconds"] = record["guard_and_api_seconds"]
        elif record["event"] == "action.request":
            action = dict(record)
            row["actions"].append(action)
            requests[record["action_id"]] = action
        elif record["event"] == "action.result":
            if record["action_id"] in requests:
                requests[record["action_id"]]["result"] = record
        elif record["event"] == "cycle.observed":
            row["action_observed"] = record.get("action_observed")
            row["observation_seconds"] = record.get("state", {}).get("timestamp_seconds")
        elif record["event"] == "cycle.error":
            row["error"] = record["error"]
            row["error_category"] = record.get("category", "unclassified")
        elif record["event"] == "cycle.skipped":
            row["skipped_after"] = row.get("skipped_after", 0) + record["count"]
    rows = [row for row in cycles.values() if start <= row["started_at"] < end]
    consecutive, longest = 0, 0
    previous = {}
    for row in rows:
        if previous and (
            previous.get("skipped_after", 0)
            or row["tick"] != previous["tick"] + 1
            or not 0 <= row["started_at"] - previous["started_at"] <= 1.5 * cadence_seconds
        ):
            consecutive = 0
        previous = row
        valid = row.get("forecast_valid") is True and row.get("outcome") in (
            "held",
            "shadow",
            "acknowledged",
        )
        if row.get("outcome") == "acknowledged" and row.get("action_observed") is not True:
            valid = False
        consecutive = consecutive + 1 if valid else 0
        longest = max(longest, consecutive)
        row["fallback_invoked"] = (
            row.get("fallback_invoked", False) or row.get("proposal", {}).get("fallback") is True
        )
        cycle = directory / f'cycle-{row["tick"]:04d}'
        timing_path = cycle / "stage-timing.json"
        if timing_path.exists():
            row["stage_timing"] = json.loads(timing_path.read_text())
        forecast_path, collection_path = (
            cycle / "forecast/forecast.json",
            cycle / "native/collection.json",
        )
        row["complete_native_eligible"] = False
        if forecast_path.exists() and collection_path.exists():
            forecast = json.loads(forecast_path.read_text())
            collection = json.loads(collection_path.read_text())
            row["complete_native_eligible"] = (
                forecast["status"] == "ready"
                and collection["status"] == "verified"
                and (cycle / "scores.json").exists()
            )
            # A stale native result may be replaced by a reactive proposal; recover its actual age.
            native_cutoff = milliseconds(forecast["cutoff"]) / 1000
            invalid = [
                record
                for record in records
                if record["event"] == "forecast.invalid" and record.get("tick") == row["tick"]
            ]
            if invalid:
                row["decision_age_seconds"] = invalid[0]["recorded_at_ns"] / 1e9 - native_cutoff
            row["native_collection_seconds"] = collection["elapsed_seconds"]
            row["native_stage_timing"] = {
                key: collection[key]
                for key in (
                    "stage_inputs_seconds",
                    "job_launch_and_execution_seconds",
                    "artifact_collection_seconds",
                )
                if key in collection
            }
            resource_path = cycle / "native/artifacts/results/batch/shared-resources.json"
            if resource_path.exists():
                usage = json.loads(resource_path.read_text())
                row["native_process_cpu_seconds"] = usage.get("user_cpu_seconds", 0) + usage.get(
                    "system_cpu_seconds", 0
                )
                row["native_process_peak_rss_bytes"] = usage.get("max_rss_bytes")
                row["native_container_cpu_seconds"] = usage.get("cgroup_cpu_seconds")
                row["native_container_peak_bytes"] = usage.get("cgroup_after", {}).get(
                    "memory_peak_bytes"
                )
    eligible = [row for row in rows if row["complete_native_eligible"]]
    on_time = sum(
        0 <= row.get("decision_age_seconds", float("inf")) <= age_budget_seconds for row in eligible
    )
    legacy_on_time = sum(
        0 <= row.get("decision_age_seconds", float("inf")) <= 30 for row in eligible
    )
    actions = [
        {
            **action,
            "tick": row["tick"],
            "observed": row.get("action_observed"),
            "observation_seconds": row.get("observation_seconds"),
            "decision_source": "reactive_fallback" if row.get("fallback_invoked") else arm,
        }
        for row in rows
        for action in row["actions"]
    ]
    for action in actions:
        acquisition = acquired.get(action["action_id"])
        if acquisition:
            action["activation_id"] = acquisition["activation_id"]
            action["acquisition_requested_seconds"] = acquisition["requested_at_seconds"]
            action["observed"] = acquisition["status"] == "observed"
            action["observation_seconds"] = acquisition.get("observed_at_seconds")
            cycle = cycles.get(acquisition["tick"])
            if cycle:
                cycle["activation_observed"] = action["observed"]
                cycle["activation_requested_seconds"] = acquisition["requested_at_seconds"]
    latencies = [row["elapsed_seconds"] for row in rows if "elapsed_seconds" in row]
    identity_path = directory / "identity.json"
    identity = json.loads(identity_path.read_text()) if identity_path.exists() else {}
    down_observations = (
        identity.get("settings", {}).get("config", {}).get("reactive_down_observations", 2)
    )
    return dict(
        acquisitions=[row for row in acquisitions if start <= row["requested_at_seconds"] < end],
        reactive_down_observations=down_observations,
        cycles=rows,
        actions=actions,
        complete_native_cycles=len(eligible),
        age_budget_seconds=age_budget_seconds,
        cadence_seconds=cadence_seconds,
        within_budget_native_cycles=on_time,
        within_budget_native_fraction=on_time / len(eligible) if eligible else None,
        within30_native_cycles=legacy_on_time,
        within30_native_fraction=legacy_on_time / len(eligible) if eligible else None,
        observation_retries=sum(len(row.get("observation_retries", [])) for row in rows),
        fallback_invocations=sum(row.get("fallback_invoked", False) for row in rows),
        fallback_categories=dict(
            Counter(
                row.get("failure_category", "unclassified")
                for row in rows
                if row.get("fallback_invoked")
            )
        ),
        error_categories=dict(
            Counter(row.get("error_category", "unclassified") for row in rows if row.get("error"))
        ),
        longest_consecutive_valid_cycles=longest,
        observed_down=sum(
            row["action"] == "scale-down" and row["observed"] is True for row in actions
        ),
        observed_up=sum(row["action"] == "scale-up" and row["observed"] is True for row in actions),
        cycle_wall_median_seconds=float(np.median(latencies)) if latencies else None,
        cycle_wall_p95_seconds=float(np.percentile(latencies, 95)) if latencies else None,
        controller_cpu_seconds=sum(row.get("controller_cpu_seconds", 0) for row in rows)
        if rows and all("controller_cpu_seconds" in row for row in rows)
        else None,
        controller_peak_rss_kib=max(
            (row.get("controller_process_peak_rss_kib", 0) for row in rows), default=0
        )
        or None,
    )


def sender_window_fidelity(events, *, start_offset_seconds, end_offset_seconds):
    """Measure dispatch fidelity by exact identities in a planned half-open arrival window.

    Args:
        events (list[dict]): Preserved endpoint event stream.
        start_offset_seconds (float): Inclusive planned offset from the sender origin.
        end_offset_seconds (float): Exclusive planned offset from the sender origin.

    Returns:
        dict: Counts, measured lag quantiles and explicit consistency failures. The planned
        count is the denominator; missing receipts or malformed identities prevent acceptance.

    Raises:
        ValueError: Bounds are not finite nonnegative numbers with an increasing interval.
    """
    bounds = (start_offset_seconds, end_offset_seconds)
    if (
        any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in bounds
        )
        or bounds[1] <= bounds[0]
    ):
        raise ValueError("sender evaluation bounds must be finite, nonnegative and increasing")
    kinds = (
        "schedule.planned",
        "batch.send_started",
        "batch.receipt_received",
        "batch.send_failed",
    )
    groups = {kind: {} for kind in kinds}
    issues = []
    for row in events:
        kind = row.get("event_type")
        if kind not in groups:
            continue
        details = row.get("details", {})
        identity = details.get("endpoint_batch_id")
        if not isinstance(identity, str) or not identity:
            issues.append("malformed_sender_identity")
            continue
        groups[kind].setdefault(identity, []).append(details)
    selected = []
    for identity, rows in groups["schedule.planned"].items():
        for details in rows:
            offset = details.get("planned_offset_ns")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                issues.append("malformed_planned_offset")
                continue
            if bounds[0] * 1e9 <= offset < bounds[1] * 1e9:
                selected.append((identity, details))
    lags, on_time, successful = [], 0, 0
    for identity, plan in selected:
        started, received, failed = (groups[kind].get(identity, []) for kind in kinds[1:])
        if (
            len(groups[kinds[0]][identity]) != 1
            or len(started) != 1
            or len(received) != 1
            or failed
        ):
            issues.append("incomplete_or_duplicate_sender_identity")
        if len(received) == 1 and not failed:
            successful += 1
        if len(started) != 1:
            continue
        dispatch = started[0]
        if any(
            row.get(key) != plan.get(key)
            for row in started + received
            for key in ("batch_index", "planned_offset_ns")
        ):
            issues.append("sender_plan_mismatch")
        actual, reported = dispatch.get("actual_send_offset_ns"), dispatch.get("schedule_lag_ns")
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in (actual, reported)
        ):
            issues.append("malformed_dispatch_clock")
            continue
        lag = actual - plan["planned_offset_ns"]
        if lag < 0 or lag != reported:
            issues.append("inconsistent_dispatch_clock")
            continue
        lags.append(lag / 1e9)
        on_time += lag <= 250_000_000
    count = len(selected)
    if not count:
        issues.append("no_planned_evaluation_arrivals")
    fraction = on_time / count if count else 0
    if fraction < 0.95:
        issues.append("evaluated_sender_fidelity_below_threshold")
    return dict(
        start_offset_seconds=bounds[0],
        end_offset_seconds=bounds[1],
        tolerance_seconds=0.25,
        required_fraction=0.95,
        planned_count=count,
        successful_count=successful,
        on_time_count=on_time,
        on_time_fraction=fraction,
        schedule_lag_p50_seconds=float(np.percentile(lags, 50)) if lags else None,
        schedule_lag_p95_seconds=float(np.percentile(lags, 95)) if lags else None,
        schedule_lag_max_seconds=max(lags) if lags else None,
        fidelity_passed=not issues,
        issues=sorted(set(issues)),
    )


def sender_inventory(events, jobs, summary, run_id):
    """Validate preserved dispatch and receipt identities against the physical Job inventory.

    Args:
        events (list[dict]): Entire endpoint event stream.
        jobs (list[dict]): Final application Job objects.
        summary (dict): Endpoint summary to cross-check against individual events.
        run_id (str): Expected unique capture namespace and sender identity.

    Returns:
        list[str]: Explicit inventory or dispatch-fidelity failures; empty when consistent.
    """
    kinds = ("schedule.planned", "batch.send_started", "batch.receipt_received")
    groups = [[row for row in events if row["event_type"] == kind] for kind in kinds]
    issues = []
    counts = ("planned_count", "attempted_count", "successful_count")
    identities = []
    for rows, count in zip(groups, counts):
        ids = [row["details"].get("endpoint_batch_id") for row in rows]
        identities.append(set(ids))
        if (
            len(rows) != summary.get(count)
            or len(ids) != len(set(ids))
            or None in ids
            or any(row["run_id"] != run_id for row in rows)
        ):
            issues.append("sender_" + count + "_inventory")
    if not identities[0] or any(ids != identities[0] for ids in identities[1:]):
        issues.append("sender_request_identity_mismatch")
    planned = {row["details"].get("endpoint_batch_id"): row["details"] for row in groups[0]}
    fields = ("batch_index", "planned_offset_ns", "image_count", "payload_bytes")
    for row in groups[1] + groups[2]:
        expected = planned.get(row["details"].get("endpoint_batch_id"), {})
        if any(row["details"].get(key) != expected.get(key) for key in fields):
            issues.append("sender_request_plan_mismatch")
            break
    indices = [row["details"].get("batch_index") for row in groups[0]]
    if sorted(indices) != list(range(len(indices))):
        issues.append("sender_plan_indices")
    receipt_ids = [
        (
            row["details"].get("job_name"),
            row.get("request_id"),
            row["details"].get("endpoint_batch_id"),
        )
        for row in groups[2]
    ]
    job_ids = [
        (
            job["metadata"]["name"],
            job["metadata"].get("labels", {}).get("continuum.atlarge.nl/request-id"),
            job["metadata"].get("annotations", {}).get("continuum.atlarge.nl/endpoint-batch-id"),
        )
        for job in jobs
    ]
    if (
        len(set(receipt_ids)) != len(receipt_ids)
        or set(receipt_ids) != set(job_ids)
        or any(None in identity for identity in receipt_ids)
    ):
        issues.append("receipt_job_identity_mismatch")
    on_time = sum(0 <= row["details"].get("schedule_lag_ns", -1) <= 250000000 for row in groups[1])
    fraction = on_time / len(groups[1]) if groups[1] else 0
    if (
        fraction < 0.95
        or on_time != summary.get("on_time_count")
        or not math.isclose(fraction, summary.get("on_time_fraction", -1))
    ):
        issues.append("sender_measured_fidelity")
    return issues


def action_lifecycles(actions, states, config):
    """Attach first-observed release and acknowledged reuse without inferring hidden timing.

    Args:
        actions (list[dict]): Ordered requests with source, identity and confirmed outcomes.
        states (list[dict]): Complete capture snapshots, including controlled follow-up.
        config (dict): Configured worker resources and bounds.

    Returns:
        dict: Action lifecycle records and conservative same-worker forecast down/up pairs.
    """
    views = []
    for state in states:
        try:
            at = milliseconds(state["timestamp"]) / 1000
            views.append(snapshot_view(state, config, now_seconds=at))
        except ValueError:
            continue
    views.sort(key=lambda view: view["timestamp_seconds"])
    result, pending, pairs = [], {}, 0
    for action in actions:
        row = dict(action)
        row["first_observed_empty_seconds"] = None
        row["reused_at_seconds"] = None
        result.append(row)
        acknowledged = row.get("result", {}).get("last_action_at")
        if (
            row.get("result", {}).get("status") != "acknowledged"
            or row.get("observed") is not True
            or acknowledged is None
        ):
            continue
        worker, uid = row["selected_worker"], row["node_uid"]
        if row["action"] == "scale-down":
            empty = next(
                (
                    view["timestamp_seconds"]
                    for view in views
                    if view["timestamp_seconds"] >= acknowledged
                    and worker in view["reserve_workers"]
                    and view["nodes"][worker]["uid"] == uid
                ),
                None,
            )
            row["first_observed_empty_seconds"] = empty
            pending[worker] = row
        elif row["action"] == "scale-up":
            down = pending.pop(worker, None)
            if down and down["node_uid"] == uid:
                down["reused_at_seconds"] = acknowledged
                empty = down["first_observed_empty_seconds"]
                if empty is not None and empty > acknowledged:
                    # An empty observation after reuse belongs to a later drain interval.
                    down["first_observed_empty_seconds"] = None
                    empty = None
                if (
                    empty is not None
                    and empty <= acknowledged
                    and down.get("decision_source") == "forecast"
                    and row.get("decision_source") == "forecast"
                ):
                    pairs += 1
    return dict(
        actions=result,
        forecast_down_up_pairs=pairs,
        interpretation=(
            "Release is first observed empty after acknowledgment, not an exact physical "
            "completion instant; pairs require confirmed forecast-selected reuse "
            "of the same worker."
        ),
    )


# One capture joins sender, observer, native and physical windows without hidden denominators.
def capture_evidence(capture, role):  # pylint: disable=too-many-locals
    """Read one preserved capture with explicit study role and immutable provenance.

    Args:
        capture (Path): Collected experiment directory, including failed attempts if requested.
        role (str): Explicit pilot, heldout or scheduling role; never inferred from outcomes.

    Returns:
        dict: Self-contained physical run outcomes, coverage and control timeline.

    Raises:
        ValueError: The role, sender identity or capture settings are inconsistent.
    """
    if role not in ("pilot", "heldout", "scheduling"):
        raise ValueError("explicit pilot, heldout or scheduling role required")
    capture = Path(capture).resolve()
    invocation = json.loads((capture / "invocation.json").read_text())
    events = [json.loads(line) for line in (capture / "endpoint.jsonl").read_text().splitlines()]
    ready = [row for row in events if row["event_type"] == "schedule.ready"]
    summaries = [row["details"] for row in events if row["event_type"] == "schedule.summary"]
    if len(ready) != 1 or ready[0]["run_id"] != invocation["namespace"]:
        raise ValueError("sender identity or schedule origin is ambiguous")
    origin = milliseconds(ready[0]["details"]["schedule_start_timestamp"]) / 1000
    warmup = (
        invocation.get("warmup_cycles", 1) if invocation.get("control_arm", "none") != "none" else 0
    )
    start = origin + warmup * invocation["period_seconds"]
    end = origin + invocation["cycles"] * invocation["period_seconds"]
    config = dict(
        workers=[
            dict(
                node_name=name,
                configured_cores=invocation.get("worker_cores", 4),
                memory_mib=invocation.get("worker_memory_mib", 16384),
            )
            for name in invocation["workers"]
        ],
        minimum_workers=invocation.get("minimum_workers", 1),
        maximum_workers=invocation.get("maximum_workers", 3),
    )
    rows, boundaries = bounded_read(capture / "observer")
    trace, observations = read_observations(rows, invocation["namespace"])
    journal_path = capture / "controller/journal.jsonl"
    activation_records = (
        [json.loads(line) for line in journal_path.read_text().splitlines()]
        if journal_path.exists()
        else []
    )
    allocation_result = allocation(
        [state for _, state in trace.states],
        config,
        start,
        end,
        activation_records=activation_records,
    )
    followup_end = end + invocation.get("followup_seconds", 600)
    deadline = invocation.get("deadline_seconds", 120)
    response_result = responses(
        observations,
        round(start * 1000),
        round(end * 1000),
        deadline_seconds=deadline,
        followup_end_ms=round(followup_end * 1000),
    )
    inventory = json.loads((capture / "jobs.json").read_text())["items"]
    app_jobs = [
        job
        for job in inventory
        if job["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "image-batch-worker"
    ]
    pods = json.loads((capture / "pods-final.json").read_text())["items"]
    restarts = {
        container["name"]: container.get("restartCount", 0)
        for pod in pods
        if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "image-batch-adapter"
        for container in pod["status"].get("containerStatuses", [])
    }
    summary = summaries[0] if len(summaries) == 1 else {}
    evaluated_sender = sender_window_fidelity(
        events,
        start_offset_seconds=warmup * invocation["period_seconds"],
        end_offset_seconds=invocation["cycles"] * invocation["period_seconds"],
    )
    issues = sender_inventory(events, app_jobs, summary, invocation["namespace"])
    if (
        invocation.get("require_evaluated_sender_fidelity", False)
        and not evaluated_sender["fidelity_passed"]
    ):
        issues.append("evaluated_sender_fidelity")
    if not summary.get("fidelity_passed") or summary.get("on_time_fraction", 0) < 0.95:
        issues.append("sender_fidelity")
    if summary.get("attempted_count") != summary.get("planned_count") or summary.get(
        "failed_count", 1
    ):
        issues.append("unattempted_or_failed_requests")
    if len(app_jobs) != summary.get("successful_count") or {
        job["metadata"]["uid"] for job in app_jobs
    } != {row["uid"] for row in observations}:
        issues.append("unmatched_request_job_observer_inventory")
    if not {"adapter", "opendt-observer"} <= set(restarts) or any(restarts.values()):
        issues.append("capture_restart_or_missing_status")
    if (capture / "failure.json").exists():
        issues.append("recorded_capture_failure")
    plan = [
        {
            key: row["details"][key]
            for key in ("batch_index", "planned_offset_ns", "image_count", "payload_bytes")
        }
        for row in events
        if row["event_type"] == "schedule.planned"
    ]
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    control_settings = dict(
        cadence_seconds=invocation.get("cadence_seconds", 60),
        age_budget_seconds=invocation.get("decision_age_seconds", 30),
        arm=invocation.get("control_arm", "none"),
    )
    controller = controller_outcomes(capture / "controller", start, end, **control_settings)
    operation = controller_outcomes(capture / "controller", start, followup_end, **control_settings)
    state_rows = [state for _, state in trace.states]
    controller["lifecycles"] = action_lifecycles(controller["actions"], state_rows, config)
    operation["lifecycles"] = action_lifecycles(operation["actions"], state_rows, config)
    diagnostics = [
        cycle_diagnostic(
            capture / "controller" / f'cycle-{cycle["tick"]:04d}',
            cycle,
            observations,
            round(end * 1000),
            round(followup_end * 1000),
            deadline_seconds=deadline,
        )
        for cycle in controller["cycles"]
    ]
    return dict(
        capture=str(capture),
        role=role,
        seed=invocation["seed"],
        arm=invocation.get("control_arm", "none"),
        admission=invocation.get("admission_mode", "scheduler"),
        run_id=invocation["namespace"],
        origin_seconds=origin,
        evaluation_start_seconds=start,
        arrival_end_seconds=end,
        config=config,
        comparison_settings={
            key: (
                invocation.get("arm_active_workers")
                if key == "active_workers" and invocation.get("arm_active_workers") is not None
                else invocation.get(key)
            )
            for key in (
                "deployment_sources",
                "network_preset",
                "replay_command",
                "endpoint_image",
                "worker_cores",
                "worker_memory_mib",
                "active_workers",
                "minimum_workers",
                "maximum_workers",
                "acquisition_seconds",
                "modeled_request_delay_seconds",
                "modeled_admission_margin_seconds",
                "require_evaluated_sender_fidelity",
                "template_namespace",
                "template_deployment",
                "period_seconds",
                "cycles",
                "warmup_cycles",
                "minimum_rate",
                "peak_rate",
                "deadline_seconds",
                "deadline_fraction",
                "followup_seconds",
            )
        },
        arrival_plan_sha256=digest,
        arrival_plan=plan,
        invocation=invocation,
        sender=summary,
        sender_evaluated_window=evaluated_sender,
        accepted_capture=not issues,
        acceptance_issues=issues,
        restarts=restarts,
        allocation=allocation_result,
        responses=response_result,
        controller=controller,
        controller_full_operation=operation,
        followup_end_seconds=followup_end,
        forecast_diagnostics=[row for row in diagnostics if row is not None],
        observation_boundaries=boundaries,
        source_hashes=json.loads((capture / "source-hashes.json").read_text()),
    )


def main():
    """Freeze one or more capture summaries for offline combined reporting."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="append", type=Path, required=True)
    parser.add_argument("--role", choices=("pilot", "heldout", "scheduling"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    payload = dict(
        schema_version=SCHEMA, runs=[capture_evidence(path, args.role) for path in args.capture]
    )
    write_json(args.output, payload)


if __name__ == "__main__":
    main()
