"""Offline PNG/PDF reports from captured image-batch endpoint and observer JSONL.

Compact comparison of captured runs; no cluster access.
Requires Python 3.10+ and requirements-analysis.txt; matching planned arrivals.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import textwrap

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from forecast_report import prepare_forecasts, render_forecasts

matplotlib.use("Agg")

STREAMS = ("workload", "resource-snapshots", "cluster-state", "observer-events")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def seconds(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, f"timestamp has no timezone: {value}")
    return stamp.timestamp()


def number(value):
    require(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0,
        f"invalid nonnegative number: {value}",
    )
    return value


def read_jsonl(path):
    """Reject partial captures, unsupported schemas, and non-JSON log noise."""
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
    result = {}
    for record in records:
        identity = key(record)
        require(identity not in result, f"duplicate {label}: {identity}")
        result[identity] = record
    return result


def describe(values):
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
    warnings = []
    arrivals, ready, origin, fidelity = endpoint_run(records, run_id, warnings)
    receipts = {r["request_id"]: r for r in arrivals if r["request_id"]}
    for record in evidence["workload"]:
        if record["source"]["request_id"] in receipts:
            require(
                record["source"].get("workload_run_id") == run_id,
                "workload_run_id missing or inconsistent for a matching receipt; older evidence is unsupported",
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
            f"{len(unfinished)} accepted Job(s) have no completed workload record; lifecycle/distributions exclude them."
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
            "Cluster-state capture does not bracket the full run; pressure plots have incomplete boundaries."
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
            f"Up to {overlap} other-run Job(s) overlap the report window; Job/CPU curves show only the selected run."
        )
    if finalizing:
        warnings.append(
            f"{len(finalizing)} distinct Job(s) appeared queued after recorded worker finish without a terminal Pod phase. These ambiguous observations remain in pressure counts; inspect the captured state."
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
            f"{job['job_uid']}: raw in-execution samples ({job['sample_count']}) disagree with workload ({job['reported_samples']})",
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
                "were skipped because CPU, memory, or source time was missing. This is not a count of failed Jobs."
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


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def format_value(value):
    return "n/a" if value is None else f"{value:.2f}"


def summary_text(report):
    s = report["summary"]
    f, c = s["fidelity"], s["coverage"]
    return (
        f"{s['run_id']} | {s['schedule_start_utc']}\n"
        f"Requests: {f['planned_count']} planned / {f['attempted_count']} started / "
        f"{f['successful_count']} accepted / {s['completed_jobs']} completed Jobs\n"
        f"Scheduling lag median / max: {format_value(f['lag_ms']['median'])} / {format_value(f['lag_ms']['max'])} ms; "
        f"fidelity: {f['fidelity_passed']}\n"
        f"Queue wait median / p95: {format_value(s['queue_seconds']['median'])} / {format_value(s['queue_seconds']['p95'])} s; "
        f"execution median / p95: {format_value(s['execution_seconds']['median'])} / {format_value(s['execution_seconds']['p95'])} s\n"
        f"Samples per completed Job min / median: {format_value(c['min'])} / {format_value(c['median'])}; "
        f">=2: {format_value(c['at_least_2_percent'])}%; >=3: {format_value(c['at_least_3_percent'])}%\n"
    )


def compact_alignment(reports):
    """Compare matching plans on a common elapsed-time grid, without bridging gaps."""
    plans = [
        [(r["batch_index"], r["planned_seconds"]) for r in report["arrivals"]] for report in reports
    ]
    require(
        all(plan == plans[0] for plan in plans),
        "compact comparison requires matching batch indices and planned offsets; analyze different schedules individually with --run-id",
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
    """Require every repetition at a grid point so the range has a fixed denominator."""
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


def compact_figures(reports, output, save, max_sample_age, alignment):
    grid, aligned, representative = alignment
    colors = [plt.get_cmap("tab10")(i % 10) for i in range(len(reports))]
    labels = [f"Run {i+1}" for i in range(len(reports))]
    n = len(reports)

    def footer(fig, first, second=""):
        fig.text(0.04, 0.032, first, fontsize=8.5)
        fig.text(0.04, 0.012, second, fontsize=8.5)

    def band(ax, key, label, color):
        median, low, high = range_series(aligned, key)
        ax.step(grid, median, where="post", color=color, label=label)
        ax.fill_between(grid, low, high, step="post", color=color, alpha=0.18)
        return median, low, high

    fig, axes = plt.subplots(2, 1, figsize=(11.7, 8.3))
    plan = reports[0]["arrivals"]
    arrival_end = max(
        [r["summary"]["schedule"].get("profile", {}).get("duration_seconds", 0) for r in reports]
        + [a["actual_seconds"] or a["planned_seconds"] for r in reports for a in r["arrivals"]]
    )
    values = sorted(a["planned_seconds"] for a in plan)
    axes[0].step(
        [0] + values + [arrival_end],
        list(range(len(values) + 1)) + [len(values)],
        where="post",
        color="#333333",
        linewidth=2.5,
        label="Common planned HTTP starts",
    )
    for report, color, label in zip(reports, colors, labels):
        actual = sorted(
            a["actual_seconds"] for a in report["arrivals"] if a["actual_seconds"] is not None
        )
        axes[0].step(
            [0] + actual + [arrival_end],
            list(range(len(actual) + 1)) + [len(actual)],
            where="post",
            color=color,
            linestyle="--",
            label=label + " actual starts",
        )
        sent = [a for a in report["arrivals"] if a["lag_ms"] is not None]
        axes[1].scatter(
            [a["batch_index"] for a in sent],
            [a["lag_ms"] for a in sent],
            color=color,
            s=19,
            label=label,
            zorder=3,
        )
    for i, a in enumerate(plan):
        lags = [
            r["arrivals"][i]["lag_ms"] for r in reports if r["arrivals"][i]["lag_ms"] is not None
        ]
        if len(lags) == n:
            axes[1].vlines(a["batch_index"], min(lags), max(lags), color="#999999", linewidth=2)
            axes[1].scatter(
                a["batch_index"],
                statistics.median(lags),
                marker="_",
                s=70,
                color="#333333",
                zorder=4,
            )
    axes[0].set(xlabel="Seconds from schedule start", ylabel="Cumulative HTTP starts")
    axes[1].set(
        xlabel="Endpoint batch index (matching plans)",
        ylabel="Endpoint HTTP-start lag (ms)",
        ylim=(0, None),
    )
    tolerances = sorted({r["summary"]["fidelity"]["tolerance_ms"] for r in reports})
    if any(
        (r["summary"]["fidelity"]["lag_ms"]["max"] or 0) >= min(tolerances) / 2 for r in reports
    ):
        for tolerance in tolerances:
            axes[1].axhline(
                tolerance, color="#b73a3a", linestyle=":", label=f"{tolerance:g} ms tolerance"
            )
    for ax in axes:
        ax.legend(loc="upper left", fontsize=8, ncol=2)
    footer(
        fig,
        f"{n} independent runs with matching planned offsets. Gray bars: observed min–max; black ticks: median; colored points: actual runs.",
        "Ranges describe these repetitions, not confidence intervals. Lag comes from monotonic offsets, not event log time.",
    )
    save(fig, output, "arrivals", f"Arrival fidelity | all {n} repetitions")

    fig, axes = plt.subplots(3, 1, figsize=(11.7, 8.3), sharex=True)
    aggregate_rows = [{"time_seconds": t} for t in grid]
    for axis, key, label, color in [
        (axes[0], "queued_jobs", "Queued Jobs (terminal Pods excluded)", "#e07a36"),
        (axes[0], "active_jobs", "Active Jobs (Pod Running)", "#16697a"),
        (axes[1], "active_requested_cpu", "Active requested CPU", "#777777"),
        (axes[1], "allocatable_worker_cpu", "Allocatable worker CPU", "#222222"),
        (axes[2], "executing_jobs", "Executing Jobs", "#777777"),
        (axes[2], "sampled_jobs", "Executing Jobs with a recent CPU sample", "#56954c"),
    ]:
        median, low, high = band(axis, key, label, color)
        for row, m, l, h in zip(aggregate_rows, median, low, high):
            row.update({key + "_median": m, key + "_min": l, key + "_max": h})
    if any(
        p["ready_schedulable_cpu"] != p["allocatable_worker_cpu"]
        for r in reports
        for p in r["pressure"]
    ):
        band(axes[1], "ready_schedulable_cpu", "Ready + schedulable worker CPU", "#7d4e9b")
    # Keep observed CPU on each run's original time axis: no mixing partial sums or filling gaps.
    for report, color, label in zip(reports, colors, labels):
        x, y, partial_x, partial_y = [], [], [], []
        for i, p in enumerate(report["pressure"]):
            if i and p["time_seconds"] - report["pressure"][i - 1]["time_seconds"] > 3:
                x.append(report["pressure"][i - 1]["time_seconds"] + 0.001)
                y.append(math.nan)
            x.append(p["time_seconds"])
            y.append(p["observed_workload_cpu"] if p["cpu_coverage_complete"] else math.nan)
            if not p["cpu_coverage_complete"] and p["observed_workload_cpu"] is not None:
                partial_x.append(p["time_seconds"])
                partial_y.append(p["observed_workload_cpu"])
        axes[1].step(
            x, y, where="post", color=color, linewidth=1.1, label=label + " observed workload CPU"
        )
        axes[1].scatter(partial_x, partial_y, color=color, marker="x", s=11, alpha=0.55)
    axes[1].add_line(
        Line2D(
            [],
            [],
            color="#777777",
            marker="x",
            linestyle="None",
            label="Crosses: sampled subset only",
        )
    )
    axes[0].set_ylabel("Jobs")
    axes[1].set_ylabel("CPU cores")
    axes[2].set(ylabel="Jobs with CPU coverage", xlabel="Seconds from schedule start")
    for ax in axes:
        ax.set_ylim(bottom=0)
        ax.set_xlim(grid[0], grid[-1] if len(grid) > 1 else grid[0] + 1)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), fontsize=7.5, ncol=3, frameon=False)
    footer(
        fig,
        f"Terminal Pods excluded. Counts/requested CPU: median + min–max across {n} runs; 1 s grid; common capture interval; state holds <=3 s.",
        f"Workload CPU, not node utilization: per-run lines = all executing Jobs sampled; crosses = subset sum; samples held <={max_sample_age:g} s.",
    )
    save(fig, output, "pressure", f"Cluster pressure | repetition ranges and individual CPU traces")
    write_csv(output / "pressure-ranges.csv", aggregate_rows, list(aggregate_rows[0]))

    example = reports[representative]
    jobs = example["jobs"]
    fig, (left, right) = plt.subplots(
        1, 2, sharey=True, figsize=(11.7, 8.3), gridspec_kw={"width_ratios": [2.15, 1]}
    )
    workers = sorted({j["worker"] or "unknown" for j in jobs})
    worker_colors = {worker: plt.get_cmap("tab10")(i % 10) for i, worker in enumerate(workers)}
    by_batch = [{j["batch_index"]: j for j in r["jobs"]} for r in reports]
    queue_rows = []
    for y, j in enumerate(jobs):
        left.barh(
            y,
            j["queue_seconds"],
            left=j["submitted"] - example["origin"],
            height=0.65,
            color="#d3d6da",
        )
        left.barh(
            y,
            j["execution_seconds"],
            left=j["start"] - example["origin"],
            height=0.65,
            color=worker_colors[j["worker"] or "unknown"],
        )
        waits = [
            lookup[j["batch_index"]]["queue_seconds"]
            for lookup in by_batch
            if j["batch_index"] in lookup
        ]
        if len(waits) == n:
            right.hlines(y, min(waits), max(waits), color="#aaaaaa", linewidth=2)
            right.plot(statistics.median(waits), y, "|", color="#222222", markersize=8)
        for lookup, color in zip(by_batch, colors):
            if j["batch_index"] in lookup:
                right.scatter(
                    lookup[j["batch_index"]]["queue_seconds"], y, color=color, s=16, zorder=3
                )
        queue_rows.append(
            {
                "batch_index": j["batch_index"],
                "runs_with_completion": len(waits),
                "queue_min": min(waits),
                "queue_median": statistics.median(waits),
                "queue_max": max(waits),
            }
        )
    left.set_yticks(range(len(jobs)), [f"{j['batch_index']:02d}" for j in jobs], fontsize=8)
    left.invert_yaxis()
    left.set(
        xlabel="Seconds from schedule start",
        ylabel="Endpoint batch index",
        xlim=(0, example["end_seconds"]),
    )
    right.set(xlabel="Queue wait incl. startup (s)", xlim=(0, None))
    left.set_title(f"Actual timeline: {labels[representative]}", fontsize=10, pad=34)
    right.set_title("Same batch across repetitions", fontsize=10, pad=34)
    left.legend(
        handles=[Patch(color="#d3d6da", label="Queue wait")]
        + [Patch(color=c, label=w) for w, c in worker_colors.items()],
        loc="lower left",
        bbox_to_anchor=(0, 1.005),
        ncol=2,
        fontsize=7,
        frameon=False,
    )
    right.legend(
        handles=[
            Line2D([], [], color=c, marker="o", linestyle="None", label=l)
            for c, l in zip(colors, labels)
        ],
        loc="lower left",
        bbox_to_anchor=(0, 1.005),
        ncol=2,
        fontsize=7,
        frameon=False,
    )
    footer(
        fig,
        f"Timeline: {labels[representative]}, the first complete run. Later Jobs can overtake earlier Jobs under Kubernetes scheduling policy.",
        "Right: individual queue waits with min–max and median where every run completed the batch. Gray timeline bars include container startup.",
    )
    save(
        fig,
        output,
        "lifecycle",
        "Job lifecycle | one actual timeline and per-batch queue-wait comparison",
    )
    write_csv(output / "queue-wait-comparison.csv", queue_rows, list(queue_rows[0]))

    fig = plt.figure(figsize=(11.7, 8.3))
    layout = fig.add_gridspec(2, 3, height_ratios=[3.2, 1])
    axes = [fig.add_subplot(layout[0, i]) for i in range(3)]
    for ax, key, label in [
        (axes[0], "queue_seconds", "Queue wait incl. startup (s)"),
        (axes[1], "execution_seconds", "Worker execution time (s)"),
    ]:
        all_values = [j[key] for r in reports for j in r["jobs"]]
        edges = np.histogram_bin_edges(
            all_values,
            bins=min(12, max(1, math.ceil(math.sqrt(max(len(r["jobs"]) for r in reports))))),
        )
        for i, (r, c, l) in enumerate(zip(reports, colors, labels)):
            ax.hist(
                [j[key] for j in r["jobs"]],
                bins=edges,
                histtype="step",
                linewidth=1.7,
                linestyle=["-", "--", ":"][i % 3],
                color=c,
                label=l,
            )
        ax.set(xlabel=label, ylabel="Completed Jobs")
        ax.legend(fontsize=8)
    all_counts = [j["sample_count"] for r in reports for j in r["jobs"]]
    counts = list(range(min(all_counts), max(all_counts) + 1))
    for i, (r, c, l) in enumerate(zip(reports, colors, labels)):
        histogram = Counter(j["sample_count"] for j in r["jobs"])
        axes[2].bar(
            [v + (i - (n - 1) / 2) * 0.8 / n for v in counts],
            [histogram[v] for v in counts],
            width=0.8 / n,
            color=c,
            label=l,
        )
    axes[2].set(xlabel="Accepted CPU samples per Job", ylabel="Completed Jobs")
    axes[2].set_xticks(counts)
    axes[2].legend(fontsize=8)
    coverage_rows = []
    for r, l in zip(reports, labels):
        c = r["summary"]["coverage"]
        coverage_rows.append(
            [
                l,
                r["summary"]["completed_jobs"],
                format_value(c["min"]),
                format_value(c["median"]),
                format_value(c["at_least_2_percent"]),
                format_value(c["at_least_3_percent"]),
            ]
        )
    table_ax = fig.add_subplot(layout[1, :])
    table_ax.axis("off")
    table = table_ax.table(
        cellText=coverage_rows,
        colLabels=[
            "Run",
            "Completed Jobs",
            "Minimum samples",
            "Median samples",
            ">=2 samples (%)",
            ">=3 samples (%)",
        ],
        cellLoc="center",
        bbox=[0.04, 0.05, 0.92, 0.85],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    footer(
        fig,
        "Timing histograms use identical bins across repetitions. Coverage includes zero-sample completed Jobs; incomplete Jobs are excluded.",
        "Statistics retain two decimal places for consistency; individual lifecycle durations have one-second resolution and sample counts are integers.",
    )
    save(
        fig,
        output,
        "distributions",
        "Execution, queue delay, and CPU sampling | all repetitions",
    )


def render(reports, output, provenance, max_sample_age, forecast_report=None):
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "savefig.dpi": 160,
        }
    )
    alignment = compact_alignment(reports)
    output.mkdir(parents=True, exist_ok=False)
    notes = [
        "# Image-batch compact comparison",
        "Matched plans; ranges describe repetitions, not confidence intervals. CPU traces retain individual-run coverage. "
        "Pressure ranges use the common capture interval and a one-second grid without bridging state gaps over three seconds. "
        "Lifecycle shows the first complete run in report order, with per-batch queue waits across repetitions.",
        "",
        "Captured runtime evidence; no simulation or synthetic report data.",
        "",
    ]
    pdf_meta = {"Title": "FNS image-batch run analysis", "CreationDate": None, "ModDate": None}
    with PdfPages(output / "report.pdf", metadata=pdf_meta) as pdf:

        def save(fig, directory, name, title, layout=True):
            fig.suptitle(title, fontsize=14, fontweight="bold")
            if layout:
                fig.tight_layout(rect=(0, 0.055, 1, 0.94))
            fig.savefig(directory / f"{name}.png")
            pdf.savefig(fig)
            plt.close(fig)

        # The PDF starts with a direct comparison, even for one run.
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        columns = [
            "Run",
            "Completed\nJobs",
            "Maximum endpoint\nHTTP-start lag\n(ms)",
            "Median Job\nqueue wait\n(s)",
            "Median worker\nexecution time\n(s)",
            "Accepted CPU\nsamples per Job\nminimum / median",
            "Jobs with CPU samples\n>=2 / >=3\n(%)",
        ]
        rows = []
        for index, report in enumerate(reports, 1):
            s, c = report["summary"], report["summary"]["coverage"]
            rows.append(
                [
                    f"Run {index}",
                    s["completed_jobs"],
                    format_value(s["fidelity"]["lag_ms"]["max"]),
                    format_value(s["queue_seconds"]["median"]),
                    format_value(s["execution_seconds"]["median"]),
                    f"{format_value(c['min'])} / {format_value(c['median'])}",
                    f"{format_value(c['at_least_2_percent'])} / {format_value(c['at_least_3_percent'])}",
                ]
            )
        table = ax.table(
            cellText=rows,
            colLabels=columns,
            cellLoc="center",
            bbox=[0, 0.60, 1, 0.34],
            colWidths=[0.07, 0.09, 0.18, 0.14, 0.15, 0.18, 0.19],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        ax.text(
            0,
            0.56,
            "\n".join(f"Run {i}: {r['summary']['run_id']}" for i, r in enumerate(reports, 1)),
            transform=ax.transAxes,
            va="top",
            fontsize=9,
        )
        interpretation = (
            "Each row is an independently executed run. Matching seeds reproduce planned arrivals; "
            "runtime timing and CPU remain measured.\n\n"
            "Queue wait = Job creation to worker-container start (includes scheduling and startup). "
            "Execution = worker-container start to finish. Completed Jobs only in distributions.\n\n"
            "Precision: captured Kubernetes lifecycle timestamps have one-second resolution; sample counts "
            "are integers. Statistics use two decimal places consistently, including fractional medians; "
            "trailing zeros do not imply finer measurement resolution. HTTP-start lag uses finer-resolution "
            "monotonic timestamps.\n\n"
            "CPU is observed image-batch workload CPU, not total node utilization. "
            f"Raw CPU rates are held forward at most {max_sample_age:g} s within execution; "
            "partial sums are marked separately and missing samples are not zero.\n\n"
            "Synthetic repeated inference lengthens this demo workload. These runs do not establish "
            "Digital Twin policy performance. Warnings and provenance follow in summary.md / summary.json."
        )
        ax.text(
            0,
            0.44,
            "\n\n".join(textwrap.fill(p, 112) for p in interpretation.split("\n\n")),
            transform=ax.transAxes,
            va="top",
            fontsize=9,
        )
        save(fig, output, "comparison", "FNS image-batch | captured run comparison")
        for index, report in enumerate(reports, 1):
            s = report["summary"]
            directory = output / f"{index:02d}-{re.sub(r'[^A-Za-z0-9_.-]', '_', s['run_id'])[:80]}"
            directory.mkdir()
            notes += ["```text", summary_text(report).rstrip(), "```", ""]
            correction = s["pressure_corrections"]
            notes += [
                "Pressure correction: excluded "
                f"{correction['excluded_terminal_pod_observations']} terminal-Pod appearances "
                f"across {correction['affected_jobs']} Jobs using captured Succeeded/Failed phases. "
                "Original input files are unchanged.",
                "",
            ]
            notes += [f"- {warning}" for warning in s["warnings"]] or ["No input warnings."]
            notes.append("")
            arrivals, jobs, pressure = report["arrivals"], report["jobs"], report["pressure"]
            write_csv(
                directory / "requests.csv",
                arrivals,
                [
                    "batch_index",
                    "endpoint_batch_id",
                    "request_id",
                    "job_name",
                    "planned_seconds",
                    "actual_seconds",
                    "lag_ms",
                    "outcome",
                ],
            )
            write_csv(
                directory / "jobs.csv",
                jobs,
                [
                    "batch_index",
                    "job_uid",
                    "job_name",
                    "request_id",
                    "worker",
                    "submitted",
                    "start",
                    "finish",
                    "completed",
                    "queue_seconds",
                    "execution_seconds",
                    "sample_count",
                ],
            )
            write_csv(directory / "pressure.csv", pressure, list(pressure[0]))
        compact_figures(reports, output, save, max_sample_age, alignment)

        # Carry evidence caveats into the PDF itself, not only a sidecar file.
        warning_lines = []
        for report in reports:
            warning_lines += [report["summary"]["run_id"]]
            for warning in report["summary"]["warnings"] or ["No input warnings."]:
                warning_lines += textwrap.wrap("  " + warning, 108)
            warning_lines.append("")
        for page in range(0, len(warning_lines), 32):
            fig, ax = plt.subplots(figsize=(11.7, 8.3))
            ax.axis("off")
            ax.text(
                0,
                0.98,
                "\n".join(warning_lines[page : page + 32]),
                va="top",
                transform=ax.transAxes,
                fontsize=10,
                linespacing=1.5,
            )
            save(
                fig,
                output,
                f"diagnostics-{page // 32 + 1:02d}",
                "Evidence warnings and collection diagnostics",
            )
        if forecast_report is not None:
            render_forecasts(forecast_report, output, save)
            notes += [
                "Forecast pages describe a separate run; see forecast-evaluation.json, "
                "forecast-report.json and forecast-scores.csv for evidence and plotted values.",
                "",
            ]
    notes += [
        "## Interpretation",
        "",
        "Queue wait includes scheduling and container startup. Distributions include completed Jobs only. "
        "CPU is selected-run image-batch workload CPU, not total node utilization. "
        f"Raw source samples are held forward for at most {max_sample_age:g} seconds within execution. "
        "Partial sums are marked separately; gaps do not mean zero. CPU rates are not clamped to requests. "
        "Pressure is sampled; peaks between snapshots can be missed. Cross-host alignment assumes synchronized VM clocks. "
        "Quantile p95 uses the nearest rank. Synthetic repeated inference is a demo load multiplier.",
        "Pressure excludes captured Succeeded/Failed Pods, correcting older observer classifications. "
        "Per-run pressure_corrections in summary.json record the exclusions; input logs remain unchanged.",
        "Kubernetes lifecycle timestamps have one-second resolution and sample counts are integers. "
        "Two decimal places are a consistent display convention for statistics, not additional measurement precision. "
        "The sampling-coverage gap includes startup delay and stale/missing samples; it is not a direct latency measurement.",
        "",
        "See summary.json for input SHA-256 hashes, paths, plotting version, and analysis settings. "
        "Per-run CSV files contain the plotted values; Job timestamp columns use Unix seconds.",
    ]
    (output / "summary.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(
        json.dumps(
            {
                "provenance": provenance,
                "matplotlib_version": matplotlib.__version__,
                "report_variant": "compact",
                "representative_run_id": reports[alignment[2]]["summary"]["run_id"],
                "pressure_grid_seconds": 1,
                "pressure_common_interval": [alignment[0][0], alignment[0][-1]],
                "max_sample_age_seconds": max_sample_age,
                "state_gap_threshold_seconds": 3,
                "runs": [r["summary"] for r in reports],
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint-log",
        action="append",
        type=Path,
        required=True,
        help="captured endpoint JSONL; repeat for a combined multi-run report",
    )
    parser.add_argument(
        "--observer-dir",
        type=Path,
        required=True,
        help="directory with the four observer JSONL streams",
    )
    parser.add_argument(
        "--run-id", help="select one workload-run ID (default: all runs in endpoint logs)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory for PNG, PDF, Markdown, JSON, and CSV files",
    )
    parser.add_argument(
        "--max-sample-age-seconds",
        type=float,
        default=10,
        help="maximum forward hold of CPU source samples (default: 10 seconds)",
    )
    parser.add_argument(
        "--forecast-dir", type=Path, help="append saved forecast accuracy pages"
    )
    parser.add_argument(
        "--forecast-observer-dir",
        type=Path,
        help="observer capture for the forecast run",
    )
    parser.add_argument(
        "--forecast-until", help="UTC arrival-experiment end; exclude shutdown/drain"
    )
    parser.add_argument(
        "--forecast-rate-bin-seconds", type=int, default=10, choices=(10, 20, 30),
        help="average observed and predicted rates over matching bins (display only)",
    )
    args = parser.parse_args(argv)
    try:
        forecast_args = (
            args.forecast_dir,
            args.forecast_observer_dir,
            args.forecast_until,
        )
        require(
            not any(forecast_args) or all(forecast_args),
            "supply --forecast-dir, --forecast-observer-dir and --forecast-until together",
        )
        require(
            math.isfinite(args.max_sample_age_seconds) and args.max_sample_age_seconds > 0,
            "max sample age must be finite and positive",
        )
        require(
            not args.output_dir.exists(),
            f"output directory already exists: {args.output_dir}; choose a new directory",
        )
        paths = args.endpoint_log + [args.observer_dir / f"{name}.jsonl" for name in STREAMS]
        records = [r for p in args.endpoint_log for r in read_jsonl(p)]
        evidence = {name: read_jsonl(args.observer_dir / f"{name}.jsonl") for name in STREAMS}
        run_ids = sorted({r["run_id"] for r in records if r.get("component") == "endpoint"})
        require(run_ids, "no endpoint runs found")
        if args.run_id:
            require(args.run_id in run_ids, f"run ID not found in endpoint logs: {args.run_id}")
            run_ids = [args.run_id]
        reports = []
        for run_id in run_ids:
            try:
                reports.append(analyze(records, evidence, run_id, args.max_sample_age_seconds))
            except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                raise ValueError(f"run {run_id}: {exc}") from exc
        provenance = {
            "inputs": [
                {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in paths
            ],
            "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "python_version": sys.version.split()[0],
        }
        forecast_report = None
        if args.forecast_dir:
            forecast_report = prepare_forecasts(
                *forecast_args, rate_bin_seconds=args.forecast_rate_bin_seconds
            )
        render(
            reports,
            args.output_dir,
            provenance,
            args.max_sample_age_seconds,
            forecast_report,
        )
        for report in reports:
            print(summary_text(report))
            for warning in report["summary"]["warnings"]:
                print(f"WARNING [{report['summary']['run_id']}]: {warning}", file=sys.stderr)
        print(f"Report: {(args.output_dir / 'report.pdf').resolve()}")
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        ImportError,
    ) as exc:
        print(
            f"Analysis failed: {exc}. Check captured input fields and Python/Matplotlib dependencies.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
