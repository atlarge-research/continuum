"""Numerical analysis of captured endpoint and observer evidence, without report rendering."""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime
import csv
from pathlib import Path
import json
import math
import statistics

STREAMS = ("workload", "resource-snapshots", "cluster-state", "observer-events")


def require(condition, message):
    """Validate one captured-evidence invariant.

    Args:
        condition (bool): Whether the invariant holds.
        message (str): Diagnostic identifying the invalid evidence.

    Raises:
        ValueError: The condition is false.
    """
    if not condition:
        raise ValueError(message)


def seconds(value):
    """Convert a timezone-aware ISO timestamp to Unix seconds.

    Args:
        value (str): Captured ISO timestamp, including an explicit timezone.

    Returns:
        float: Timestamp in Unix seconds.

    Raises:
        ValueError: The timestamp is invalid or has no timezone.
    """
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, f"timestamp has no timezone: {value}")
    return stamp.timestamp()


def number(value):
    """Validate a finite, nonnegative captured number.

    Args:
        value (int or float): Evidence value; booleans are not accepted.

    Returns:
        int or float: The validated value without coercion.

    Raises:
        ValueError: The value is not a finite nonnegative number.
    """
    require(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0,
        f"invalid nonnegative number: {value}",
    )
    return value


def read_jsonl(path):
    """Reject partial captures, unsupported schemas, and non-JSON log noise.

    Args:
        path (Path): Captured JSONL file, optionally carrying kubectl log timestamps.

    Returns:
        list[dict]: Validated schema-version-one records in source order.

    Raises:
        ValueError: A line is truncated, malformed or uses an unsupported schema.
        OSError: The capture cannot be read.
    """
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                require(line.endswith("\n"), "unterminated final line; recapture the file")
                # Also accept `kubectl logs --timestamps` output, without rewriting evidence.
                if not line.lstrip().startswith("{"):
                    prefix, line = line.split(" ", 1)
                    seconds(prefix)
                record = json.loads(line)
                require(isinstance(record, dict), "expected a JSON object")
                require(record.get("schema_version") == 1, "expected schema_version 1")
                records.append(record)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return records


def unique(records, key, label):
    """Index records while rejecting duplicate evidence identities.

    Args:
        records (iterable[dict]): Captured records to index.
        key (callable): Extracts a hashable identity from each record.
        label (str): Identity description used in validation errors.

    Returns:
        dict: Records indexed by their unique identity.

    Raises:
        ValueError: An identity occurs more than once.
    """
    result = {}
    for record in records:
        identity = key(record)
        require(identity not in result, f"duplicate {label}: {identity}")
        result[identity] = record
    return result


def describe(values):
    """Summarize measured values using a nearest-rank p95.

    Args:
        values (iterable[float]): Available measurements, excluding missing values.

    Returns:
        dict: Count, extrema, median and p95; empty statistics are None.
    """
    values = sorted(values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": values[0],
        "median": statistics.median(values),
        "p95": values[math.ceil(0.95 * len(values)) - 1],
        "max": values[-1],
    }


def endpoint_run(records, run_id, warnings):
    """Validate endpoint lineage and calculate actual-versus-planned arrivals.

    Args:
        records (list[dict]): Captured endpoint records for one or more runs.
        run_id (str): Run identity to analyze.
        warnings (list[str]): Diagnostics updated when endpoint evidence is incomplete.

    Returns:
        tuple: Arrival rows, schedule-ready details, Unix origin and fidelity statistics.

    Raises:
        ValueError: Scheduling, outcome or identity evidence is inconsistent.
    """
    events = defaultdict(list)
    for record in records:
        if record["run_id"] == run_id:
            events[record["event_type"]].append(record)
    require(len(events["schedule.ready"]) == 1, f"{run_id}: need exactly one schedule.ready")
    ready = events["schedule.ready"][0]["details"]
    origin_ns = number(ready["schedule_start_timestamp_unix_ns"])
    indexed = {
        name: unique(events[name], lambda r: r["details"]["endpoint_batch_id"], name)
        for name in (
            "schedule.planned",
            "batch.send_started",
            "batch.receipt_received",
            "batch.send_failed",
        )
    }
    plans, starts, receipts, failures = indexed.values()
    require(len(plans) == ready["planned_count"], "planned_count does not match schedule.planned")
    require(not (receipts.keys() & failures.keys()), "batch has both receipt and failure")
    require(starts.keys() <= plans.keys(), "HTTP start without a planned batch")
    require((receipts.keys() | failures.keys()) <= starts.keys(), "outcome without an HTTP start")
    rows = []
    for batch_id, record in plans.items():
        plan = record["details"]
        planned = number(plan["planned_offset_ns"])
        require(
            plan["planned_timestamp_unix_ns"] == origin_ns + planned,
            f"{batch_id}: planned UTC and offset disagree",
        )
        row = {
            "batch_index": plan["batch_index"],
            "endpoint_batch_id": batch_id,
            "planned_seconds": planned / 1e9,
            "actual_seconds": None,
            "lag_ms": None,
            "request_id": None,
            "job_name": None,
            "outcome": "not_attempted",
        }
        if batch_id in starts:
            send = starts[batch_id]["details"]
            actual = number(send["actual_send_offset_ns"])
            require(
                send["planned_offset_ns"] == planned
                and send["actual_send_timestamp_unix_ns"] == origin_ns + actual
                and send["schedule_lag_ns"] == actual - planned,
                f"{batch_id}: inconsistent HTTP start/lag timestamps",
            )
            require(actual >= planned, f"{batch_id}: HTTP start precedes its plan")
            row.update(
                actual_seconds=actual / 1e9,
                lag_ms=(actual - planned) / 1e6,
                outcome="missing_outcome",
            )
        outcome = receipts.get(batch_id) or failures.get(batch_id)
        if outcome:
            require(
                outcome["details"]["actual_send_offset_ns"]
                == starts[batch_id]["details"]["actual_send_offset_ns"],
                f"{batch_id}: outcome disagrees with HTTP start",
            )
            row["outcome"] = "accepted" if batch_id in receipts else "failed"
            if batch_id in receipts:
                row.update(
                    request_id=outcome["request_id"], job_name=outcome["details"]["job_name"]
                )
        rows.append(row)
    unique(rows, lambda r: r["batch_index"], "batch index")
    unique([r for r in rows if r["request_id"]], lambda r: r["request_id"], "receipt request ID")
    rows.sort(key=lambda r: r["batch_index"])
    counts = {
        "planned_count": len(plans),
        "attempted_count": len(starts),
        "successful_count": len(receipts),
        "failed_count": len(failures),
    }
    summaries = events["schedule.summary"]
    require(len(summaries) <= 1, "duplicate schedule.summary")
    if summaries:
        summary = summaries[0]["details"]
        require(
            all(summary[k] == v for k, v in counts.items()),
            "schedule.summary counts disagree with events",
        )
        tolerance = number(summary["fidelity_tolerance_ns"]) / 1e6
        on_time = sum(r["lag_ms"] is not None and r["lag_ms"] <= tolerance for r in rows)
        require(summary["on_time_count"] == on_time, "schedule.summary on-time count disagrees")
        fraction = on_time / len(rows) if rows else 1.0
        passed = len(starts) == len(plans) and fraction >= summary["fidelity_required_fraction"]
        require(summary["fidelity_passed"] == passed, "schedule.summary fidelity disagrees")
    else:
        warnings.append("Missing schedule.summary: endpoint capture may be incomplete.")
        tolerance, passed = 250.0, None
    missing = len(plans) - len(receipts) - len(failures)
    if missing:
        warnings.append(f"{missing} planned request(s) lack a final HTTP outcome.")
    if failures:
        warnings.append(f"{len(failures)} HTTP submission(s) failed; acceptance may be uncertain.")
    return (
        rows,
        ready,
        origin_ns / 1e9,
        {
            **counts,
            "fidelity_passed": passed,
            "tolerance_ms": tolerance,
            "lag_ms": describe([r["lag_ms"] for r in rows if r["lag_ms"] is not None]),
        },
    )


def analyze(records, evidence, run_id, max_sample_age):
    """Derive run timing, pressure and coverage from captured runtime evidence.

    Args:
        records (list[dict]): Endpoint scheduling and request records.
        evidence (dict): Observer records keyed by STREAMS names.
        run_id (str): Workload-run identity to select across evidence streams.
        max_sample_age (float): Maximum CPU sample forward hold within execution, in seconds.

    Returns:
        dict: Per-run summary, arrivals, Jobs, sampled pressure, gaps and time bounds.

    Raises:
        ValueError: Captured identity, timing, sample or state evidence is inconsistent.
        KeyError: Required evidence fields are absent.
    """
    warnings = []
    arrivals, ready, origin, fidelity = endpoint_run(records, run_id, warnings)
    receipts = {r["request_id"]: r for r in arrivals if r["request_id"]}
    for record in evidence["workload"]:
        if record["source"]["request_id"] in receipts:
            require(
                record["source"].get("workload_run_id") == run_id,
                "workload_run_id missing or inconsistent for a matching receipt; older "
                "evidence is unsupported",
            )
    tasks = unique(
        [r for r in evidence["workload"] if r["source"].get("workload_run_id") == run_id],
        lambda r: r["source"]["kubernetes_job_uid"],
        "Job UID in workload",
    )
    states = sorted(evidence["cluster-state"], key=lambda r: seconds(r["timestamp"]))
    require(states, "cluster-state.jsonl is empty")
    unique(states, lambda r: r["timestamp"], "cluster snapshot timestamp")
    jobs = {}
    for uid, record in tasks.items():
        source, task = record["source"], record["task"]
        require(
            "execution_start_time" in source and "execution_completion_time" in source,
            f"{uid}: missing worker execution timestamps; older observer evidence is unsupported",
        )
        submitted = seconds(task["submission_time"])
        start, finish = seconds(source["execution_start_time"]), seconds(
            source["execution_completion_time"]
        )
        completed = seconds(source["completion_time"])
        require(
            submitted <= start <= finish <= completed,
            f"{uid}: inconsistent Job lifecycle timestamps",
        )
        require(
            abs(task["duration"] - (finish - start) * 1000) <= 1,
            f"{uid}: Task duration disagrees with worker interval",
        )
        require(source["terminal_status"] == "Complete", f"{uid}: workload Task is not Complete")
        receipt = receipts.get(source["request_id"])
        require(receipt is not None, f"{uid}: completed Job has no matching endpoint receipt")
        require(
            source["endpoint_batch_id"] == receipt["endpoint_batch_id"]
            and source["job_name"] == receipt["job_name"],
            f"{uid}: Job/endpoint lineage disagrees",
        )
        # Kubernetes timestamps have one-second precision, so allow that rounding.
        require(
            submitted >= origin + receipt["actual_seconds"] - 1,
            f"{uid}: Job creation precedes HTTP start by over one second; check VM clocks",
        )
        jobs[uid] = {
            "job_uid": uid,
            "job_name": source["job_name"],
            "request_id": source["request_id"],
            "batch_index": receipt["batch_index"],
            "submitted": submitted,
            "start": start,
            "finish": finish,
            "completed": completed,
            "queue_seconds": start - submitted,
            "execution_seconds": finish - start,
            "worker": None,
            "samples": [],
            "reported_samples": number(source["resource_sample_count"]),
        }
    unique(list(jobs.values()), lambda j: j["request_id"], "completed request ID")
    unfinished = receipts.keys() - {j["request_id"] for j in jobs.values()}
    if unfinished:
        warnings.append(
            f"{len(unfinished)} accepted Job(s) have no completed workload record; "
            f"lifecycle/distributions exclude them."
        )
    if not jobs:
        warnings.append(
            "No completed Jobs for this run; execution and sample distributions are unavailable."
        )
    duration = ready.get("profile", {}).get("duration_seconds", 0)
    end = max(
        [origin + duration]
        + [origin + (r["actual_seconds"] or r["planned_seconds"]) for r in arrivals]
        + [j["completed"] for j in jobs.values()]
    )
    if unfinished:
        end = max(end, seconds(states[-1]["timestamp"]))
    times = [seconds(s["timestamp"]) for s in states]
    begin_index = max(0, bisect_right(times, origin) - 1)
    end_index = min(len(states), bisect_right(times, end) + 1)
    if not unfinished:
        # Include the observed drain, which can lag the terminal timestamp.
        for i in range(bisect_right(times, end), len(states)):
            if not any(
                j.get("workload_run_id") == run_id
                for group in states[i]["jobs"].values()
                for j in group
            ):
                end_index = min(len(states), i + 2)
                end = times[end_index - 1]
                break
    states = states[begin_index:end_index]
    if times[0] > origin or times[-1] < end:
        warnings.append(
            "Cluster-state capture does not bracket the full run; pressure plots have "
            "incomplete boundaries."
        )
    selected = []
    overlap = 0
    finalizing = set()
    excluded_terminal_jobs = set()
    excluded_terminal_observations = 0
    for state in states:
        groups = state["jobs"]
        require(state["message_type"] == "cluster_state", "unexpected cluster-state message_type")
        require(
            state["counts"]["queued_jobs"] == len(groups["queued"])
            and state["counts"]["active_jobs"] == len(groups["active"]),
            "cluster-state counts disagree with Job lists",
        )
        entries = groups["queued"] + groups["active"]
        for entry in entries:
            if entry["request_id"] in receipts:
                require(
                    entry.get("workload_run_id") == run_id,
                    "cluster-state workload_run_id missing or inconsistent for a matching receipt",
                )
        unique(entries, lambda j: j["kubernetes_job_uid"], "Job UID within cluster snapshot")
        workers = state["workers"]
        unique(workers, lambda w: w["node_name"], "worker within cluster snapshot")
        require(state["counts"]["workers"] == len(workers), "cluster-state worker count disagrees")
        for worker in workers:
            number(worker["allocatable_cpu_count"])
            require(
                type(worker["ready"]) is bool and type(worker["schedulable"]) is bool,
                "invalid worker availability",
            )
        run_groups = {
            key: [j for j in groups[key] if j.get("workload_run_id") == run_id]
            for key in ("queued", "active")
        }
        current = run_groups["queued"] + run_groups["active"]
        overlap = max(overlap, len(entries) - len(current))
        for entry in current:
            uid = entry["kubernetes_job_uid"]
            number(entry["requested_cpu_count"])
            receipt = receipts.get(entry["request_id"])
            require(
                receipt is not None
                and receipt["endpoint_batch_id"] == entry["endpoint_batch_id"]
                and receipt["job_name"] == entry["job_name"],
                f"{uid}: cluster-state/endpoint lineage disagrees",
            )
            if uid in jobs:
                job = jobs[uid]
                if (
                    entry in run_groups["queued"]
                    and entry.get("pod_phase") not in ("Succeeded", "Failed")
                    and job["finish"] <= seconds(state["timestamp"])
                ):
                    finalizing.add(uid)
                require(
                    job["request_id"] == entry["request_id"]
                    and seconds(entry["creation_time"]) == job["submitted"],
                    f"{uid}: state/workload identity or creation time disagrees",
                )
                if entry["node_name"]:
                    require(
                        job["worker"] in (None, entry["node_name"]),
                        f"{uid}: multiple worker assignments; retries are unsupported",
                    )
                    job["worker"] = entry["node_name"]
        # Older captures classified terminal Pods as queued. Apply the corrected
        # pressure semantics using captured Pod phases, without changing inputs
        # or inferring completion from future workload records.
        for key in run_groups:
            terminal = [j for j in run_groups[key] if j.get("pod_phase") in ("Succeeded", "Failed")]
            excluded_terminal_observations += len(terminal)
            excluded_terminal_jobs.update(j["kubernetes_job_uid"] for j in terminal)
            run_groups[key] = [
                j for j in run_groups[key] if j.get("pod_phase") not in ("Succeeded", "Failed")
            ]
        selected.append(
            {
                "time_seconds": seconds(state["timestamp"]) - origin,
                "queued_jobs": len(run_groups["queued"]),
                "active_jobs": len(run_groups["active"]),
                "active_requested_cpu": sum(j["requested_cpu_count"] for j in run_groups["active"]),
                "allocatable_worker_cpu": sum(w["allocatable_cpu_count"] for w in workers),
                "ready_schedulable_cpu": sum(
                    w["allocatable_cpu_count"] for w in workers if w["ready"] and w["schedulable"]
                ),
                "unresolved_active_jobs": sum(
                    j["kubernetes_job_uid"] not in jobs for j in run_groups["active"]
                ),
            }
        )
    if overlap:
        warnings.append(
            f"Up to {overlap} other-run Job(s) overlap the report window; Job/CPU curves show "
            f"only the selected run."
        )
    if finalizing:
        warnings.append(
            f"{len(finalizing)} distinct Job(s) appeared queued after recorded worker finish "
            f"without a terminal Pod phase. These ambiguous observations remain in pressure "
            f"counts; inspect the captured state."
        )
    if any(j["worker"] is None for j in jobs.values()):
        warnings.append(
            "Worker assignment is unavailable for some completed Jobs in cluster snapshots."
        )
    gaps = [
        (a["time_seconds"], b["time_seconds"])
        for a, b in zip(selected, selected[1:])
        if b["time_seconds"] - a["time_seconds"] > 3
    ]
    if gaps:
        warnings.append(
            f"{len(gaps)} cluster-state gap(s) exceed 3 seconds; shaded on pressure plots."
        )
    snapshots = [r for r in evidence["resource-snapshots"] if r["job_uid"] in jobs]
    unique(snapshots, lambda r: (r["job_uid"], r["capture_time"]), "Job resource sample")
    for sample in snapshots:
        job = jobs[sample["job_uid"]]
        stamp = seconds(sample["capture_time"])
        number(sample["cpu_usage_cores"])
        number(sample["memory_usage_mb"])
        require(sample["job_name"] == job["job_name"], "sample Job name disagrees with workload")
        require(
            "observation_time" in sample,
            "resource sample missing observation_time; older evidence is unsupported",
        )
        require(
            stamp <= seconds(sample["observation_time"]),
            "resource sample source time exceeds observation time",
        )
        if job["start"] <= stamp <= job["finish"]:
            job["samples"].append((stamp, sample["cpu_usage_cores"]))
    for job in jobs.values():
        job["samples"].sort()
        job["sample_count"] = len(job["samples"])
        require(
            job["sample_count"] == job["reported_samples"],
            f"{job['job_uid']}: raw in-execution samples ({job['sample_count']}) disagree with "
            f"workload ({job['reported_samples']})",
        )
    # A causal bounded hold makes samples comparable on the state time axis.
    # Partial sums are kept separate from a fully covered workload CPU estimate.
    for point in selected:
        now = origin + point["time_seconds"]
        running = [j for j in jobs.values() if j["start"] <= now < j["finish"]]
        measured = []
        for job in running:
            index = bisect_right(job["samples"], (now, math.inf)) - 1
            if index >= 0 and now - job["samples"][index][0] <= max_sample_age:
                measured.append(job["samples"][index][1])
        expected = len(running) + point["unresolved_active_jobs"]
        point.update(
            executing_jobs=expected,
            sampled_jobs=len(measured),
            observed_workload_cpu=sum(measured) if measured or expected == 0 else None,
            cpu_coverage_complete=len(measured) == expected,
        )
    diagnostics = Counter()
    job_names = {r["job_name"] for r in arrivals if r["job_name"]}
    for event in evidence["observer-events"]:
        stamp, details = seconds(event["timestamp"]), event["details"]
        if origin <= stamp <= end:
            if details.get("job_name") and details["job_name"] not in job_names:
                continue
            if (
                details.get("kubernetes_job_uid")
                and details["kubernetes_job_uid"] not in jobs
                and not details.get("job_name")
            ):
                continue
            diagnostics[event["event_type"]] += 1
    for kind, count in sorted(diagnostics.items()):
        if kind == "prometheus.sample_incomplete":
            warnings.append(
                f"Incomplete resource observations ({kind}): {count} per-Job collection attempts "
                "were skipped because CPU, memory, or source time was missing. This is not a "
                "count of failed Jobs."
            )
        elif kind != "task.emitted":
            warnings.append(f"Observer diagnostic {kind}: {count} in run window.")
    coverage = describe([j["sample_count"] for j in jobs.values()])
    coverage["histogram"] = dict(sorted(Counter(j["sample_count"] for j in jobs.values()).items()))
    for threshold in (2, 3):
        coverage[f"at_least_{threshold}_percent"] = (
            (100 * sum(j["sample_count"] >= threshold for j in jobs.values()) / len(jobs))
            if jobs
            else None
        )
    if any(j["sample_count"] < 2 for j in jobs.values()):
        warnings.append("Some completed Jobs have fewer than two accepted Prometheus samples.")
    summary = {
        "run_id": run_id,
        "schedule_start_utc": ready["schedule_start_timestamp"],
        "schedule": ready,
        "fidelity": fidelity,
        "completed_jobs": len(jobs),
        "unresolved_accepted_jobs": len(unfinished),
        "queue_seconds": describe([j["queue_seconds"] for j in jobs.values()]),
        "execution_seconds": describe([j["execution_seconds"] for j in jobs.values()]),
        "coverage": coverage,
        "diagnostics": dict(diagnostics),
        "pressure_corrections": {
            "excluded_terminal_pod_observations": excluded_terminal_observations,
            "affected_jobs": len(excluded_terminal_jobs),
        },
        "warnings": warnings,
        "pressure_peaks": {
            key: max(p[key] for p in selected)
            for key in ("queued_jobs", "active_jobs", "active_requested_cpu")
        },
    }
    return {
        "summary": summary,
        "arrivals": arrivals,
        "jobs": sorted(jobs.values(), key=lambda j: j["batch_index"]),
        "pressure": selected,
        "gaps": gaps,
        "origin": origin,
        "end_seconds": end - origin,
    }


def compact_alignment(reports):
    """Compare matching plans on a common elapsed-time grid, without bridging gaps.

    Args:
        reports (list[dict]): Nonempty analyzed repetitions with identical planned arrivals.

    Returns:
        tuple: Common one-second grid, aligned pressure points and first complete run index.

    Raises:
        ValueError: Plans differ, there is no complete run of at most 40 Jobs, or captures
            have no common interval. This numerical helper does not constrain topic reporting.
    """
    plans = [
        [(r["batch_index"], r["planned_seconds"]) for r in report["arrivals"]] for report in reports
    ]
    require(
        all(plan == plans[0] for plan in plans),
        "compact comparison requires matching batch indices and planned offsets; analyze "
        "different schedules individually with --run-id",
    )
    complete = [
        i
        for i, r in enumerate(reports)
        if r["summary"]["completed_jobs"] > 0
        and r["summary"]["completed_jobs"] == r["summary"]["fidelity"]["planned_count"]
        and r["summary"]["unresolved_accepted_jobs"] == 0
    ]
    require(complete, "compact lifecycle requires at least one complete run")
    representative = complete[0]
    require(
        len(reports[representative]["jobs"]) <= 40,
        "lifecycle comparison supports up to 40 Jobs per run",
    )
    # Use the common captured interval; never extend a shorter capture as zero load.
    start = math.ceil(max(r["pressure"][0]["time_seconds"] for r in reports))
    end = math.floor(min(r["pressure"][-1]["time_seconds"] for r in reports))
    grid = list(range(max(0, start), end + 1))
    require(grid, "no common pressure capture interval")
    aligned = []
    for report in reports:
        points = report["pressure"]
        times = [p["time_seconds"] for p in points]
        values = []
        for t in grid:
            index = bisect_right(times, t) - 1
            point = points[index] if index >= 0 else None
            values.append(point if point and t - point["time_seconds"] <= 3 else None)
        aligned.append(values)
    return grid, aligned, representative


def range_series(aligned, key):
    """Require every repetition at a grid point so the range has a fixed denominator.

    Args:
        aligned (list[list[dict or None]]): Pressure points aligned on a shared time grid.
        key (str): Numeric pressure field to summarize.

    Returns:
        tuple[list, list, list]: Medians, minima and maxima; missing repetitions yield NaN.
    """
    medians, lows, highs = [], [], []
    for points in zip(*aligned):
        values = [p[key] for p in points if p is not None]
        if len(values) != len(aligned):
            medians.append(math.nan)
            lows.append(math.nan)
            highs.append(math.nan)
        else:
            medians.append(statistics.median(values))
            lows.append(min(values))
            highs.append(max(values))
    return medians, lows, highs


def write_csv(path, rows, fields):
    """Write ordered evidence columns without changing the source records.

    Args:
        path (Path): Destination CSV path.
        rows (iterable[dict]): Numerical records to export.
        fields (list[str]): Ordered column names; extra record keys are ignored.
    """
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_matched_comparisons(reports, output):
    """Preserve historical comparison CSVs when the captured runs can be aligned.

    This numerical export has no lifecycle figure's 40-Job limit. Matching batch
    indices and planned offsets, one complete representative, and a common
    captured interval are required; other evidence still supports per-run reports.

    Args:
        reports (list[dict]): Analyzed runs in report order.
        output (str or Path): Existing directory for the two comparison CSVs.

    Returns:
        bool: Whether matching evidence supported and produced both CSVs.
    """
    if not reports:
        return False
    plans = [
        [(row["batch_index"], row["planned_seconds"]) for row in report["arrivals"]]
        for report in reports
    ]
    complete = [
        report
        for report in reports
        if report["summary"]["completed_jobs"] > 0
        and report["summary"]["completed_jobs"] == report["summary"]["fidelity"]["planned_count"]
        and report["summary"]["unresolved_accepted_jobs"] == 0
    ]
    if not all(plan == plans[0] for plan in plans) or not complete:
        return False
    if any(not report["pressure"] for report in reports):
        return False
    start = math.ceil(max(report["pressure"][0]["time_seconds"] for report in reports))
    end = math.floor(min(report["pressure"][-1]["time_seconds"] for report in reports))
    grid = list(range(max(0, start), end + 1))
    if not grid:
        return False
    aligned = []
    for report in reports:
        points = report["pressure"]
        times = [point["time_seconds"] for point in points]
        values = []
        for instant in grid:
            index = bisect_right(times, instant) - 1
            point = points[index] if index >= 0 else None
            values.append(point if point and instant - point["time_seconds"] <= 3 else None)
        aligned.append(values)
    pressure_rows = [{"time_seconds": instant} for instant in grid]
    for key in (
        "queued_jobs",
        "active_jobs",
        "active_requested_cpu",
        "allocatable_worker_cpu",
        "executing_jobs",
        "sampled_jobs",
    ):
        median, low, high = range_series(aligned, key)
        for row, middle, minimum, maximum in zip(pressure_rows, median, low, high):
            row.update({key + "_median": middle, key + "_min": minimum, key + "_max": maximum})
    by_batch = [{job["batch_index"]: job for job in report["jobs"]} for report in reports]
    queue_rows = []
    for job in complete[0]["jobs"]:
        waits = [
            lookup[job["batch_index"]]["queue_seconds"]
            for lookup in by_batch
            if job["batch_index"] in lookup
        ]
        queue_rows.append(
            {
                "batch_index": job["batch_index"],
                "runs_with_completion": len(waits),
                "queue_min": min(waits),
                "queue_median": statistics.median(waits),
                "queue_max": max(waits),
            }
        )
    output = Path(output)
    write_csv(output / "pressure-ranges.csv", pressure_rows, list(pressure_rows[0]))
    write_csv(output / "queue-wait-comparison.csv", queue_rows, list(queue_rows[0]))
    return True
