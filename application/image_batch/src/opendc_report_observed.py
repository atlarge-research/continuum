"""Reusable measured-run evidence for the combined demo report."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
import numpy as np

from analyze_run import STREAMS, analyze, read_jsonl, compact_alignment, compact_figures, seconds


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
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("analyze_run.py", "opendc_report_observed.py")
            },
        },
        "interpretation": (
            "captured workload execution and workload CPU, not whole-node utilization or power; "
            "matching arrival plans are execution repetitions, not independent workload seeds"
        ),
    }


def _run_pages(pdf, report, context):
    """Render one run without requiring a matched plan or a small Job count.

    Args:
        pdf (PdfPages): Open combined-report writer.
        report (dict): Complete analyzed numerical payload.
        context (dict): Explicit workload/infrastructure metadata.
    """
    summary = report["summary"]
    arrivals, jobs, pressure = report["arrivals"], report["jobs"], report["pressure"]
    origin = report["origin"]
    end = report["end_seconds"]
    figure, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), sharex=True)
    figure.subplots_adjust(top=0.80, bottom=0.16, left=0.08, right=0.97, hspace=0.38, wspace=0.27)
    figure.suptitle("Measured workload and cluster pressure", fontsize=17, y=0.97)
    figure.text(0.08, 0.91, summary["run_id"], fontsize=9)
    figure.text(0.08, 0.865, textwrap.fill(context.get("description", ""), 125), fontsize=8)
    for field, label, color in (
        ("planned_seconds", "Planned sends", "#888888"),
        ("actual_seconds", "Actual HTTP starts", "#2864b4"),
    ):
        values = sorted(row[field] for row in arrivals if row.get(field) is not None)
        axes[0, 0].step(
            [0] + values + [end],
            [0] + list(range(1, len(values) + 1)) + [len(values)],
            where="post",
            label=label,
            color=color,
        )
    for field, label, color in (
        ("finish", "Classifier finished", "#2864b4"),
        ("completed", "Kubernetes Job complete", "#555555"),
    ):
        values = sorted(job[field] - origin for job in jobs if job.get(field) is not None)
        axes[0, 1].step(
            [0] + values + [end],
            [0] + list(range(1, len(values) + 1)) + [len(values)],
            where="post",
            label=label,
            color=color,
        )
    maximum = max(len(arrivals), len(jobs), 1)
    for axis in axes[0]:
        axis.set_ylim(0, maximum * 1.05)
        axis.set_ylabel("Cumulative Jobs / requests")
    occupancy_fields = (
        ("queued_jobs", "Queued", "#df8434"),
        ("active_jobs", "Active Pods (includes startup)", "#2864b4"),
        ("executing_jobs", "Classifier executing", "#39753b"),
    )
    if pressure and "snapshot_running_jobs" in pressure[0]:
        occupancy_fields = (
            ("unassigned_jobs", "Unassigned", "#df8434"),
            ("snapshot_running_jobs", "Observed running", "#39753b"),
            ("startup_jobs", "Assigned startup", "#2864b4"),
            ("unclassified_assigned_jobs", "Assigned, state unknown", "#888888"),
        )
    for key, label, color in occupancy_fields:
        axes[1, 0].step(*_covered_series(pressure, key), where="post", label=label, color=color)
    for key, label, style in (
        ("active_requested_cpu", "Active requested CPU", "--"),
        ("allocatable_worker_cpu", "Observed allocatable CPU", ":"),
    ):
        axes[1, 1].step(*_covered_series(pressure, key), where="post", label=label, linestyle=style)
    axes[1, 1].plot(
        *_covered_series(pressure, "observed_workload_cpu", True),
        label="Observed workload CPU",
        color="#2864b4",
    )
    partial = [
        p
        for p in pressure
        if not p["cpu_coverage_complete"] and p["observed_workload_cpu"] is not None
    ]
    axes[1, 1].scatter(
        [p["time_seconds"] for p in partial],
        [p["observed_workload_cpu"] for p in partial],
        marker="x",
        s=10,
        color="#2864b4",
        label="Partial CPU sample sum",
    )
    if pressure and "modeled_admission_cpu" in pressure[0]:
        axes[1, 1].step(
            *_covered_series(pressure, "modeled_admission_cpu"),
            where="post",
            color="#333333",
            linestyle="-.",
            label="Modeled admission CPU (ready, schedulable C−1)",
        )
    axes[1, 0].set_ylabel("Jobs")
    axes[1, 1].set_ylabel("CPU cores")
    for axis in axes[1]:
        for start, finish in report["gaps"]:
            axis.axvspan(start, finish, color="#dddddd", alpha=0.7)
    for axis in axes.flat:
        axis.set_xlim(0, end)
        axis.set_ylim(bottom=0)
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8, loc="upper left")
        axis.set_xlabel("Seconds from schedule start")
    figure.text(
        0.08,
        0.075,
        f"Completed {summary['completed_jobs']}; "
        f"unresolved accepted Jobs {summary['unresolved_accepted_jobs']}; "
        f"state gaps {len(report['gaps'])}; evidence warnings {len(summary['warnings'])}.\n"
        "CPU describes the measured workload, not total VM utilization or power. "
        "Gray spans mark state gaps.",
        fontsize=9,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)

    figure, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
    figure.subplots_adjust(top=0.84, bottom=0.14, left=0.09, right=0.97, hspace=0.42)
    figure.suptitle("Measured Job lifecycle and waiting", fontsize=17, y=0.97)
    figure.text(0.09, 0.91, summary["run_id"], fontsize=9)
    names = sorted({job["worker"] or "Unobserved worker" for job in jobs})
    colors = {name: plt.get_cmap("tab10")(index % 10) for index, name in enumerate(names)}
    seen = set()
    for job in jobs:
        name = job["worker"] or "Unobserved worker"
        row = job["batch_index"]
        axes[0].plot(
            [job["submitted"] - origin, job["start"] - origin],
            [row, row],
            color="#bfbfbf",
            linewidth=1,
        )
        axes[0].plot(
            [job["start"] - origin, job["finish"] - origin],
            [row, row],
            color=colors[name],
            linewidth=1.7,
            label=name if name not in seen else None,
        )
        seen.add(name)
    axes[0].set(xlabel="Seconds from schedule start", ylabel="Endpoint batch index", xlim=(0, end))
    for key, label, color in (
        ("queue_seconds", "Creation → container start", "#df8434"),
        ("execution_seconds", "Classifier execution", "#2864b4"),
    ):
        axes[1].scatter(
            [job["batch_index"] for job in jobs],
            [job[key] for job in jobs],
            s=10,
            label=label,
            color=color,
        )
    axes[1].set(xlabel="Batch index within this run", ylabel="Seconds", ylim=(0, None))
    for axis in axes:
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8, loc="upper left", ncol=3)
    figure.text(
        0.09,
        0.065,
        "Gray segments include scheduling and startup; colored segments are classifier execution.\n"
        "Original creation timestamps are retained. "
        "Unfinished Jobs are counted without invented completion times.",
        fontsize=9,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)


def render_measured_pages(pdf, payload, output):
    """Compose measured pages, retaining matching-plan ranges only where valid.

    Args:
        pdf (PdfPages): Open report writer.
        payload (dict): Complete saved measured evidence.
        output (Path): Existing new report directory for auxiliary numerical CSVs.

    Returns:
        dict: Run/group identities and warnings included in this measured section.

    Raises:
        ValueError: Payload schema or run inventory is missing.
    """
    if payload.get("schema_version") != SCHEMA or not payload.get("runs"):
        raise ValueError("expected complete saved measured evidence")
    audit = {"runs": [r["summary"] for r in payload["runs"]], "groups": []}
    for indices in measured_groups(payload):
        reports = [payload["runs"][index] for index in indices]
        matched = len(reports) > 1 and all(len(report["jobs"]) <= 40 for report in reports)
        alignment = None
        if matched:
            try:
                alignment = compact_alignment(reports)
            except ValueError:
                matched = False
        if matched:
            directory = output / ("measured-" + str(len(audit["groups"])))
            directory.mkdir(exist_ok=False)

            def save(figure, _directory, _name, title, layout=True):
                """Adapt the existing measured renderer to the combined PDF writer.

                Args:
                    figure (Figure): Existing measured figure.
                    _directory (Path): Standalone renderer output directory.
                    _name (str): Standalone artifact basename.
                    title (str): Page title from the measured renderer.
                    layout (bool): Whether to apply automatic layout.
                """
                figure.suptitle(title, fontsize=17)
                if layout:
                    figure.tight_layout(rect=(0, 0.055, 1, 0.94))
                pdf.savefig(figure)
                plt.close(figure)

            compact_figures(reports, directory, save, payload["max_sample_age_seconds"], alignment)
        else:
            for report in reports:
                _run_pages(pdf, report, payload.get("context", {}))
        audit["groups"].append({"run_indices": indices, "matching_plan_ranges": matched})
    return audit


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
