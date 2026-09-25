"""Reusable measured-run evidence for the combined demo report."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from analyze_run_core import STREAMS, analyze, read_jsonl, seconds


SCHEMA = "opendc-measured-evidence-v1"


def _snapshot_occupancy(report, states, context=None):
    """Add causal occupancy without inferring running state from later task profiles.

    Args:
        report (dict): Analyzed run, updated with explicit snapshot categories.
        states (list[dict]): Original captured cluster-state records.
        context (dict or None): Explicit configured worker cores, if known.

    Raises:
        ValueError: Configured worker identities or core counts are invalid.
    """
    workers = (context or {}).get("workers", [])
    configured = {worker["node_name"]: worker["configured_cores"] for worker in workers}
    if len(configured) != len(workers) or any(
        isinstance(core, bool) or not isinstance(core, int) or core <= 1
        for core in configured.values()
    ):
        raise ValueError("report workers require unique names and integer configured_cores > 1")
    snapshots = {seconds(state["timestamp"]): state for state in states}
    for point in report["pressure"]:
        state = snapshots[point["time_seconds"] + report["origin"]]
        jobs = [
            job
            for group in ("queued", "active")
            for job in state["jobs"][group]
            if job.get("workload_run_id") == report["summary"]["run_id"]
            and job.get("pod_phase") not in ("Succeeded", "Failed")
            and job.get("execution_state") != "terminated"
            and job.get("job_terminal_status") not in ("Complete", "Failed")
        ]
        assigned = [job for job in jobs if job.get("node_name")]
        running = sum(job.get("execution_state") == "running" for job in assigned)
        startup = sum(job.get("execution_state") == "waiting" for job in assigned)
        point.update(
            snapshot_running_jobs=running,
            startup_jobs=startup,
            unclassified_assigned_jobs=len(assigned) - running - startup,
            unassigned_jobs=len(jobs) - len(assigned),
        )
        if configured:
            observed = {worker["node_name"]: worker for worker in state["workers"]}
            point["modeled_admission_cpu"] = (
                sum(
                    core - 1
                    for name, core in configured.items()
                    if observed[name]["ready"] and observed[name]["schedulable"]
                )
                if configured.keys() <= observed.keys()
                else None
            )


def _covered_series(points, key, complete_only=False):
    """Break plotted lines at missing samples and state gaps exceeding three seconds.

    Args:
        points (list[dict]): Ordered analyzed pressure snapshots.
        key (str): Numeric snapshot field to plot.
        complete_only (bool): Require complete workload CPU sampling for each value.

    Returns:
        tuple[list[float], list[float]]: Times and values with explicit NaN gaps.
    """
    times, values = [], []
    for point in points:
        now = point["time_seconds"]
        if times and now - times[-1] > 3:
            times.append(times[-1] + 0.001)
            values.append(np.nan)
        value = point.get(key)
        if complete_only and not point["cpu_coverage_complete"]:
            value = None
        times.append(now)
        values.append(np.nan if value is None else value)
    return times, values


def measured_groups(payload):
    """Group matching arrival plans without aligning batch indices across different seeds.

    Args:
        payload (dict): Saved measured evidence with ordered analyzed runs.

    Returns:
        list[list[int]]: Run indices sharing exact batch indices and planned offsets.
    """
    groups = {}
    for index, report in enumerate(payload["runs"]):
        key = tuple((row["batch_index"], row["planned_seconds"]) for row in report["arrivals"])
        groups.setdefault(key, []).append(index)
    return list(groups.values())


def prepare_measured(endpoint_logs, observer_dir, run_ids=None, max_sample_age=10, context=None):
    """Reuse captured-run calculations and freeze every plotted numerical series.

    Unlike the historical summary alone, this payload retains arrivals, original
    Job timing and worker assignments, pressure, CPU coverage and collection gaps.
    Rendering it requires no cluster or original input files. Context is explicit
    operator metadata; it must not be mistaken for independently measured power.

    Args:
        endpoint_logs (list[str or Path]): Captured endpoint JSONL files.
        observer_dir (str or Path): Matching frozen four-stream observation directory.
        run_ids (list[str] or None): Explicit run selection, defaulting to all endpoint runs.
        max_sample_age (float): Positive maximum sample hold time in seconds.
        context (dict or None): Saved image, workload, infrastructure and intervention metadata.

    Returns:
        dict: Serializable complete measured evidence and source SHA-256 provenance.

    Raises:
        ValueError: Selection, measurement contract or sample-age limit is invalid.
    """
    if not math.isfinite(max_sample_age) or max_sample_age <= 0:
        raise ValueError("sample age must be finite and positive")
    endpoint_logs = [Path(path).resolve() for path in endpoint_logs]
    directory = Path(observer_dir).resolve()
    paths = endpoint_logs + [directory / (name + ".jsonl") for name in STREAMS]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    records = [row for path in endpoint_logs for row in read_jsonl(path)]
    evidence = {name: read_jsonl(directory / (name + ".jsonl")) for name in STREAMS}
    available = sorted({row["run_id"] for row in records if row.get("component") == "endpoint"})
    selected = available if run_ids is None else run_ids
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(available):
        raise ValueError("select unique run IDs present in endpoint evidence")
    reports = [analyze(records, evidence, run_id, max_sample_age) for run_id in selected]
    for report in reports:
        _snapshot_occupancy(report, evidence["cluster-state"], context)
    if before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise ValueError("input evidence changed while preparing report")
    return {
        "schema_version": SCHEMA,
        "runs": reports,
        "max_sample_age_seconds": max_sample_age,
        "context": context or {},
        "provenance": {
            "inputs": [{"path": path, "sha256": digest} for path, digest in before.items()],
            "implementation": {
                name: hashlib.sha256(
                    (Path(__file__).resolve().parent.parent / name).read_bytes()
                ).hexdigest()
                for name in (
                    "analyze_run_core.py",
                    "reporting/analyzer.py",
                    "reporting/measured.py",
                )
            },
        },
        "interpretation": (
            "captured workload execution and workload CPU, not whole-node utilization or power; "
            "matching arrival plans are execution repetitions, not independent workload seeds"
        ),
    }


def main():
    """Save a new measured payload suitable for offline combined-report rendering."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-log", type=Path, action="append", required=True)
    parser.add_argument("--observer-dir", type=Path, required=True)
    parser.add_argument("--run-id", action="append")
    parser.add_argument("--max-sample-age-seconds", type=float, default=10)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context = json.loads(args.context.read_text()) if args.context else None
    payload = prepare_measured(
        args.endpoint_log, args.observer_dir, args.run_id, args.max_sample_age_seconds, context
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
