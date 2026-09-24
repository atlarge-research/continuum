"""Create an offline, non-ranking PDF and JSON evaluation of successful OpenDC batches.

The report presents exactly two interpretations: a fixed observation window and the same
backlog-plus-pre-horizon cohort followed through completion. Response-time summaries use only
observed completions and preserve each task's original creation time. Energy is cumulative host
energy in joules, or the complete datacenter accumulator for native cordon cases, interpolated
between samples and extended after native output at the idle power of workers remaining on.
Partial scale-down scopes exclude omitted worker
completion and energy; shared comparison axes label their totals as partial.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import textwrap

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import MaxNLocator
import numpy as np
import pyarrow.parquet as pq
from scipy.ndimage import gaussian_filter1d

from opendc_inputs import file_hashes, write_json
from opendc_pinning import PINNED_MODE
from opendc_energy import datacenter_series

plt.switch_backend("Agg")

SCHEMA_VERSION = "opendc-evaluation-v1"
RAW_ROOT = Path("simulator/controlled/raw-output/0/seed=0")


def _percentile(values, fraction):
    """Compute a linearly interpolated percentile from observed samples.

    Args:
        values (list[float]): Finite response-time samples.
        fraction (float): Quantile in the closed interval from zero to one.

    Returns:
        float or None: Interpolated percentile, or null for an empty sample.
    """
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _response_statistics(values):
    """Summarize actual response-time samples without inventing censored values.

    Args:
        values (list[float]): Response times in seconds.

    Returns:
        dict: Sample count and common descriptive statistics.
    """
    if not values:
        return {"samples": 0, "mean": None, "p50": None, "p95": None, "maximum": None}
    return {
        "samples": len(values),
        "mean": sum(values) / len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "maximum": max(values),
    }


def _energy_series(case, rows, native_time_origin_ms=0, analytical_empty=False):
    """Validate and group cumulative energy samples for every included worker.

    Args:
        case (dict): Prepared case containing included worker identities and idle power.
        rows (list[dict]): Native host table rows.
        native_time_origin_ms (float): Offset from scenario cutoff to OpenDC's virtual time zero.
        analytical_empty (bool): Use direct idle-only energy without native simulator evidence.

    Returns:
        dict[str, dict]: Worker names mapped to samples and idle power.

    Raises:
        ValueError: Host coverage, identity, timestamp or cumulative energy is invalid.
    """
    workers = {}
    for worker in case["workers"]:
        name = worker["node_name"]
        if name in workers:
            raise ValueError(f"duplicate worker identity in case: {name}")
        idle = float(worker["idle_power_w"])
        if not math.isfinite(idle) or idle < 0:
            raise ValueError(f"idle power for {name} must be nonnegative")
        workers[name] = {
            "idle_power_w": idle,
            "by_time": {0.0: 0.0},
            "native_samples": 0,
            "native_last_timestamp_ms": None,
        }
    if not workers:
        raise ValueError("case has no included workers for energy evaluation")

    origin = float(native_time_origin_ms)
    if origin < 0:
        raise ValueError("native time origin must be nonnegative")
    if analytical_empty:
        if rows:
            raise ValueError("analytical empty execution must not contain native host rows")
        return {
            name: {"idle_power_w": worker["idle_power_w"], "samples": [(0.0, 0.0)]}
            for name, worker in workers.items()
        }
    for worker in workers.values():
        worker["by_time"][origin] = worker["idle_power_w"] * origin / 1000

    for row in rows:
        name = row.get("host_name")
        if name not in workers:
            raise ValueError(f"host energy references inconsistent identity: {name}")
        native_timestamp = float(row.get("timestamp"))
        native_energy = float(row.get("energy_usage"))
        if (
            not (math.isfinite(native_timestamp) and math.isfinite(native_energy))
            or min(native_timestamp, native_energy) < 0
        ):
            raise ValueError("host timestamps and cumulative energy must be nonnegative")
        timestamp = origin + native_timestamp
        energy = workers[name]["idle_power_w"] * origin / 1000 + native_energy
        previous = workers[name]["by_time"].get(timestamp)
        if previous is not None and not math.isclose(previous, energy, abs_tol=1e-9):
            raise ValueError(f"conflicting duplicate energy samples for {name} at {timestamp} ms")
        workers[name]["by_time"][timestamp] = energy
        workers[name]["native_samples"] += 1
        last_timestamp = workers[name]["native_last_timestamp_ms"]
        workers[name]["native_last_timestamp_ms"] = (
            timestamp if last_timestamp is None else max(last_timestamp, timestamp)
        )

    result = {}
    for name, worker in workers.items():
        if not worker["native_samples"]:
            raise ValueError(f"missing host energy coverage for included worker {name}")
        samples = sorted(worker["by_time"].items())
        if not math.isclose(samples[0][1], 0.0, abs_tol=1e-9):
            raise ValueError(f"host {name} has nonzero cumulative energy at time zero")
        for (_, before), (_, after) in zip(samples, samples[1:]):
            if after + 1e-9 < before:
                raise ValueError(f"host {name} cumulative energy is not monotonic")
        result[name] = {
            "idle_power_w": worker["idle_power_w"],
            "samples": samples,
            "native_last_timestamp_ms": worker["native_last_timestamp_ms"],
        }
    return result


def _host_energy_at(series, end_seconds):
    """Interpolate or idle-extend one host's cumulative joules to an endpoint.

    Args:
        series (dict): Validated samples and configured idle power.
        end_seconds (float): Simulator-relative endpoint in seconds.

    Returns:
        float: Cumulative joules at the requested endpoint.
    """
    target = end_seconds * 1000
    samples = series["samples"]
    for index, (timestamp, energy) in enumerate(samples):
        if math.isclose(target, timestamp, abs_tol=1e-9):
            return energy
        if target < timestamp:
            left_time, left_energy = samples[index - 1]
            fraction = (target - left_time) / (timestamp - left_time)
            return left_energy + fraction * (energy - left_energy)
    last_time, last_energy = samples[-1]
    return last_energy + series["idle_power_w"] * (target - last_time) / 1000


def _total_energy_at(series_by_host, end_seconds):
    """Sum validated worker series or the one complete worker-pool accumulator.

    Args:
        series_by_host (dict): Validated per-host or aggregate datacenter series.
        end_seconds (float): Simulator-relative endpoint in seconds.

    Returns:
        float: Included-host cumulative joules.
    """
    return sum(_host_energy_at(series, end_seconds) for series in series_by_host.values())


def _cohort_metrics(tasks, selected, end_seconds, include_not_arrived):
    """Build separate backlog and future response/count summaries.

    Args:
        tasks (list[dict]): Normalized task and completion records.
        selected (set[int]): Task identities completed by this interpretation endpoint.
        end_seconds (float): Observation endpoint in seconds.
        include_not_arrived (bool): Classify releases after the endpoint separately.

    Returns:
        dict: Per-cohort counts, actual response samples and statistics.
    """
    result = {}
    for cohort in ("backlog", "future"):
        members = [task for task in tasks if task["cohort"] == cohort]
        arrived = [task for task in members if task["submission_seconds"] <= end_seconds]
        completed = [task for task in members if task["task_id"] in selected]
        responses = [task["response_seconds"] for task in completed]
        result[cohort] = {
            "included": len(members),
            "completed": len(completed),
            "unfinished": len(arrived) - len(completed),
            "not_yet_arrived": len(members) - len(arrived) if include_not_arrived else 0,
            "response_samples_seconds": responses,
            "response_seconds": _response_statistics(responses),
        }
    return result


def analyze_case(
    case,
    completions,
    host_rows,
    evaluation_seconds=None,
    native_time_origin_ms=0,
    analytical_empty=False,
    datacenter_rows=None,
):  # pylint: disable=too-many-locals
    """Compute the two approved interpretations for one validated case.

    Args:
        case (dict): Prepared provisional case.json object.
        completions (list[dict]): Independently validated native terminal task records.
        host_rows (list[dict]): Native host table cumulative energy records.
        evaluation_seconds (float or None): Positive fixed endpoint, defaulting to horizon H.
        native_time_origin_ms (float): Offset from cutoff to native OpenDC time zero.
        analytical_empty (bool): Compute idle-only energy for an explicit no-process empty case.
        datacenter_rows (list[dict] or None): Required complete native worker-pool
            accumulator for pinned cases, including workers that drain and close.

    Returns:
        dict: Boundaries, inventory, both windows and shared plot curves.

    Raises:
        ValueError: Task timing, identities, horizon, endpoint or energy evidence is invalid.
    """
    horizon = float(case.get("horizon_ms")) / 1000
    if not math.isfinite(horizon) or horizon <= 0:
        raise ValueError("arrival horizon must be positive")
    evaluation = horizon if evaluation_seconds is None else float(evaluation_seconds)
    if not math.isfinite(evaluation) or evaluation <= 0:
        raise ValueError("evaluation seconds must be positive")
    cutoff = float(case.get("cutoff_ms"))
    native_origin = float(native_time_origin_ms)
    if native_origin < 0:
        raise ValueError("native time origin must be nonnegative")
    if analytical_empty and (case["tasks"] or completions):
        raise ValueError("analytical empty execution cannot contain simulated tasks")

    by_id = {}
    for record in completions:
        task_id = record.get("task_id")
        if task_id in by_id:
            raise ValueError(f"duplicate completion for task {task_id}")
        by_id[task_id] = record
    expected_ids = {item["task"]["id"] for item in case["tasks"]}
    if set(by_id) != expected_ids:
        raise ValueError("completion identities differ from simulated case tasks")

    normalized = []
    for item in case["tasks"]:
        task_id = item["task"]["id"]
        cohort = item["metadata"].get("cohort")
        if cohort not in ("backlog", "future"):
            raise ValueError(f"task {task_id} has invalid cohort")
        submission = float(item["task"].get("submission_time"))
        finish = float(by_id[task_id].get("finish_time"))
        original = float(item["metadata"]["original_creation_ms"])
        if submission < 0 or finish < submission:
            raise ValueError(f"task {task_id} has invalid lifecycle timing")
        if cohort == "future" and submission >= horizon * 1000:
            raise ValueError(f"future task {task_id} is outside arrival horizon")
        response = (cutoff + finish - original) / 1000
        if response < 0 or not math.isfinite(response):
            raise ValueError(f"task {task_id} has invalid original response time")
        normalized.append(
            {
                "task_id": task_id,
                "cohort": cohort,
                "submission_seconds": submission / 1000,
                "finish_seconds": finish / 1000,
                "response_seconds": response,
            }
        )

    pinned = case.get("initialization_mode") == PINNED_MODE
    if pinned and not analytical_empty:
        series = datacenter_series(case, datacenter_rows, native_origin)
    else:
        energy_case = case
        if pinned and case["candidate"] == "scale-down":
            energy_case = {
                **case,
                "workers": [
                    w for w in case["workers"] if w["node_name"] != case["selected_worker"]
                ],
            }
        series = _energy_series(energy_case, host_rows, native_origin, analytical_empty)
    energy_kind = (
        "analytical_idle_only_no_opendc_process"
        if analytical_empty
        else "native_cumulative_plus_analytical_pre_arrival_idle"
    )
    energy_method = (
        "included-host analytical idle before native origin; per-host cumulative joules; "
        "piecewise-linear interpolation; configured-idle extension"
        if not analytical_empty
        else "included-host configured idle power; no OpenDC process"
    )
    if pinned and not analytical_empty:
        energy_kind = "native_datacenter_including_drained_hosts_plus_pre_arrival_idle"
        energy_method = (
            "complete worker-pool native datacenter joules, including drain intervals; "
            "piecewise-linear interpolation; analytical pre-arrival idle "
            "and remaining-worker idle extension"
        )
    elif pinned and analytical_empty:
        energy_method = (
            "remaining-worker configured idle; empty cordoned worker off at zero; no OpenDC process"
        )
    last_completion = max((task["finish_seconds"] for task in normalized), default=0.0)
    if not analytical_empty:
        for name, host_series in series.items():
            if host_series["native_last_timestamp_ms"] + 1e-9 < last_completion * 1000:
                raise ValueError(
                    f"host {name} native energy ends before latest included completion"
                )
    cohort_end = max(horizon, last_completion)
    fixed_completed = {
        task["task_id"]
        for task in normalized
        if task["submission_seconds"] <= evaluation and task["finish_seconds"] <= evaluation
    }
    fixed_arrived = [task for task in normalized if task["submission_seconds"] <= evaluation]
    fixed_cohorts = _cohort_metrics(normalized, fixed_completed, evaluation, True)
    all_completed = {task["task_id"] for task in normalized}
    follow_cohorts = _cohort_metrics(normalized, all_completed, cohort_end, False)

    curve_times = {0.0, evaluation, horizon, cohort_end}
    curve_times.update(task["submission_seconds"] for task in normalized)
    curve_times.update(task["finish_seconds"] for task in normalized)
    for host in series.values():
        curve_times.update(timestamp / 1000 for timestamp, _ in host["samples"])
    maximum = max(evaluation, cohort_end)
    curve_times = sorted(time for time in curve_times if 0 <= time <= maximum)
    energy_curve = [_total_energy_at(series, time) for time in curve_times]
    arrived_curve = [
        sum(task["submission_seconds"] <= min(time, horizon) for task in normalized)
        for time in curve_times
    ]
    future_arrived_curve = [
        sum(
            task["cohort"] == "future" and task["submission_seconds"] <= min(time, horizon)
            for task in normalized
        )
        for time in curve_times
    ]
    completed_curve = [
        sum(task["finish_seconds"] <= time for task in normalized) for time in curve_times
    ]

    return {
        "initialization_mode": case.get("initialization_mode", "provisional-trace"),
        "boundaries": {
            "cutoff_ms": cutoff,
            "arrival_horizon_seconds": horizon,
            "evaluation_seconds": evaluation,
            "cohort_end_seconds": cohort_end,
            "last_included_completion_seconds": last_completion,
            "native_time_origin_seconds": native_origin / 1000,
        },
        "inventory": {
            "simulated_tasks": len(normalized),
            "omitted_tasks": len(case.get("omitted_tasks", [])),
            "model_exhausted_jobs": len(case.get("model_exhausted_jobs", [])),
        },
        "windows": {
            "fixed_window": {
                "label": "fixed evaluation window [0, E]",
                "end_seconds": evaluation,
                "energy_joules": _total_energy_at(series, evaluation),
                "energy_method": energy_method,
                "tasks": {
                    "completed": len(fixed_completed),
                    "unfinished": len(fixed_arrived) - len(fixed_completed),
                    "not_yet_arrived": len(normalized) - len(fixed_arrived),
                },
                "cohorts": fixed_cohorts,
                "response_statistics_censored": len(fixed_arrived) > len(fixed_completed),
            },
            "cohort_through_completion": {
                "label": "same included cohort through completion",
                "end_seconds": cohort_end,
                "energy_joules": _total_energy_at(series, cohort_end),
                "energy_method": energy_method,
                "tasks": {"completed": len(normalized), "unfinished": 0},
                "cohorts": follow_cohorts,
                "response_statistics_censored": False,
            },
        },
        "curves": {
            "time_seconds": curve_times,
            "energy_joules": energy_curve,
            "arrived_tasks": arrived_curve,
            "future_arrived_tasks": future_arrived_curve,
            "completed_tasks": completed_curve,
            "unfinished_tasks": [
                arrived - completed for arrived, completed in zip(arrived_curve, completed_curve)
            ],
        },
        "energy_evidence_kind": energy_kind,
        "included_idle_power_w": sum(host["idle_power_w"] for host in series.values()),
    }


def load_batch(batch_dir):
    """Verify a completed batch once, including all nested execution evidence.

    The runner owns input and native-output validation. Its saved results are trusted
    after this inventory/hash check; individual experiment trees need not be rehashed.

    Args:
        batch_dir (str or Path): Finalized batch directory from opendc_batch.

    Returns:
        tuple[Path, dict]: Resolved directory and batch manifest.

    Raises:
        ValueError: The batch failed, is incomplete, or its saved evidence changed.
    """
    directory = Path(batch_dir).resolve()
    record = json.loads((directory / "batch.json").read_text())
    if record.get("contract") != "opendc-batch-v1" or record.get("status") != "succeeded":
        raise ValueError(f"evaluation requires a succeeded opendc-batch-v1 batch: {directory}")
    if file_hashes(directory, exclude=("batch.json",)) != record["sha256"]:
        raise ValueError(f"batch artifact hash mismatch: {directory}")
    if record["remaining_experiments"] != 0:
        raise ValueError("successful batch must have zero remaining experiments")
    experiments = record["experiments"]
    identities = [(item["candidate"], item["scenario"], item["input_dir"]) for item in experiments]
    expected = {
        (item["candidate"], item["scenario"], item["input_dir"])
        for item in record["suite_manifest"]["experiments"]
    }
    if (
        not identities
        or len(identities) != len(set(identities))
        or set(identities) != expected
        or len(expected) != len(record["suite_manifest"]["experiments"])
    ):
        raise ValueError("batch experiment inventory differs from suite inventory")
    if any(item["status"] != "succeeded" or not item["validated"] for item in experiments):
        raise ValueError("batch contains a failed or unvalidated experiment")
    return directory, record


def _validate_analytical_empty(run_dir, execution, case):
    """Keep empty execution distinct from missing native output.

    Args:
        run_dir (Path): Verified run directory.
        execution (dict): Saved execution manifest.
        case (dict): Prepared case, which must contain no modeled tasks.

    Raises:
        ValueError: Tasks, process state or native output contradict empty execution.
    """
    process = execution["process"]
    if (
        case["tasks"]
        or process["execution_kind"] != "analytical_empty"
        or process["launched"] is not False
        or process["exit_code"] != 0
    ):
        raise ValueError("analytical empty execution disagrees with process or task inventory")
    if (run_dir / "simulator").exists():
        raise ValueError("analytical empty execution must not contain native simulator artifacts")


def _safe_child(root, relative, label):
    """Resolve a manifest-relative child while preventing path escape.

    Args:
        root (Path): Trusted containing directory.
        relative (object): Manifest-provided relative path.
        label (str): Field name used in diagnostics.

    Returns:
        Path: Resolved strict child path.

    Raises:
        ValueError: The value is not a nonempty safe relative path.
    """
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"missing {label}")
    child = (root / relative).resolve()
    if child == root or not child.is_relative_to(root):
        raise ValueError(f"{label} escapes batch directory")
    return child


def _file_sha256(path):
    """Hash a provenance artifact.

    Args:
        path (Path): Existing file.

    Returns:
        str: Lowercase SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resources(run_dir, execution):
    """Read actual runner cost separately from modeled worker energy.

    Args:
        run_dir (Path): Verified run directory.
        execution (dict): Saved manifest, providing empty-run process measurements.

    Returns:
        tuple[dict, list]: Measurements and explicitly unavailable components.
    """
    path = run_dir / "resources.json"
    record = json.loads(path.read_text()) if path.exists() else execution.get("process", {})
    shared = record.get("execution_kind") == "shared_native_batch"
    if shared:
        record = {}
    empty = record.get("execution_kind") == "analytical_empty"
    result, missing = {}, []
    for source, target in (
        ("wall_seconds", "actual_elapsed_seconds"),
        ("user_cpu_seconds", "actual_user_cpu_seconds"),
        ("system_cpu_seconds", "actual_system_cpu_seconds"),
        ("cgroup_cpu_seconds", "actual_cgroup_cpu_seconds"),
        ("max_rss_bytes", "actual_max_rss_bytes"),
    ):
        value = record.get(
            source, 0 if empty and source in ("cgroup_cpu_seconds", "max_rss_bytes") else None
        )
        result[target] = None if value is None else float(value)
        if value is None and not empty:
            missing.append(
                {
                    "component": target,
                    "value": None,
                    "reason": "shared process measured once for the full batch"
                    if shared
                    else "not recorded",
                }
            )
    if empty:
        missing.append(
            {
                "component": "actual_user_system_cpu_split",
                "value": None,
                "reason": "no OpenDC process launched for analytical empty execution",
            }
        )
    return result, missing


def evaluate_batches(batch_dirs, evaluation_seconds=None):
    """Build metrics from finalized runner results and native cumulative host energy.

    Batch hashes cover the saved validation and native tables. The runner already
    validates input contracts, task completion/admission and OpenDC clock offsets;
    this step consumes those results without repeating that validation.

    Args:
        batch_dirs (list[str or Path]): One or more separately prepared batch directories.
        evaluation_seconds (float or None): Positive common E, defaulting per case to H.

    Returns:
        dict: JSON-serializable report metrics and provenance.

    Raises:
        ValueError: A batch, runner artifact, validation result or native table is invalid.
    """
    report = {
        "schema_version": SCHEMA_VERSION,
        "interpretation": {
            "fixed_window": (
                "[0,E]: completed requires finish<=E; unfinished includes only releases by E; "
                "later pre-H arrivals are not_yet_arrived; response statistics use "
                "completions only."
            ),
            "cohort_through_completion": (
                "All backlog plus arrivals in [0,H) followed through completion; energy ends at "
                "max(H,last included completion), including configured idle power until H."
            ),
            "comparison": (
                "Descriptive only: no ranking, score, policy preference or SLO threshold. "
                "Partial remaining-worker scopes are not comparable as full-system totals."
            ),
        },
        "batches": [],
        "cases": [],
    }
    for batch_index, batch_dir in enumerate(batch_dirs, 1):
        directory, batch = load_batch(batch_dir)
        name = directory.parent.name if directory.name == "local" else directory.name
        label = f"batch-{batch_index:02d}:{name}"
        batch_entry = {
            "label": label,
            "path": str(directory),
            "manifest_sha256": _file_sha256(directory / "batch.json"),
            "cases": len(batch["experiments"]),
            "input_contract": batch.get("suite_manifest", {}).get("contract"),
        }
        if batch.get("shared_process") is not None:
            batch_entry["shared_process"] = batch["shared_process"]
            batch_entry["cost_scope"] = batch["cost_scope"]
        report["batches"].append(batch_entry)
        suite_experiments = {
            (item.get("candidate"), item.get("scenario")): item
            for item in batch.get("suite_manifest", {}).get("experiments", [])
        }
        for item in batch["experiments"]:
            case_root = _safe_child(directory, item.get("output_dir"), "output_dir")
            run_dir = _safe_child(case_root, item.get("runner_dir"), "runner_dir")
            execution_path = run_dir / "execution.json"
            execution = json.loads(execution_path.read_text())
            if (
                execution.get("status") != "succeeded"
                or execution.get("validation", {}).get("status") != "passed"
            ):
                raise ValueError(f"execution did not succeed validation: {run_dir}")
            case_path = run_dir / "inputs/case.json"
            case = json.loads(case_path.read_text())
            if case.get("candidate") != item.get("candidate") or case.get("scenario") != item.get(
                "scenario"
            ):
                raise ValueError("batch experiment labels differ from case input")
            host_path = run_dir / RAW_ROOT / "host.parquet"
            task_path = run_dir / RAW_ROOT / "task.parquet"
            validation = execution["validation"]
            analytical_empty = validation.get("kind") == "analytical_empty"
            if analytical_empty:
                _validate_analytical_empty(run_dir, execution, case)
                host_rows = []
            else:
                host_rows = pq.read_table(host_path).to_pylist()
            computed = analyze_case(
                case,
                validation["tasks"],
                host_rows,
                evaluation_seconds,
                native_time_origin_ms=validation.get("native_time_origin_ms", 0),
                analytical_empty=analytical_empty,
                datacenter_rows=(
                    pq.read_table(run_dir / RAW_ROOT / "dataCenter.parquet").to_pylist()
                    if case.get("initialization_mode") == PINNED_MODE and not analytical_empty
                    else None
                ),
            )
            resources, missing = _resources(run_dir, execution)
            if analytical_empty:
                missing.extend(
                    [
                        {
                            "component": "native_task_table",
                            "value": None,
                            "reason": "no OpenDC process launched for analytical empty execution",
                        },
                        {
                            "component": "native_host_table",
                            "value": None,
                            "reason": "idle-only energy is analytical for empty execution",
                        },
                    ]
                )
            if case.get("scope") == "remaining_workers_only":
                missing.extend(
                    [
                        {
                            "component": "omitted_worker_completion",
                            "value": None,
                            "reason": "excluded by partial remaining-workers-only scope",
                        },
                        {
                            "component": "omitted_worker_energy",
                            "value": None,
                            "reason": "excluded by partial remaining-workers-only scope",
                        },
                    ]
                )
            suite_item = suite_experiments.get((item.get("candidate"), item.get("scenario")), {})
            legacy_kind = (
                "observed-replay"
                if batch.get("suite_manifest", {}).get("source_prefixes")
                else "legacy-unspecified-input"
            )
            paths = {
                "batch_manifest": directory / "batch.json",
                "execution_manifest": execution_path,
                "case_input": case_path,
                "native_task_table": None if analytical_empty else task_path,
                "native_host_table": None if analytical_empty else host_path,
            }
            if case.get("initialization_mode") == PINNED_MODE and not analytical_empty:
                paths["native_datacenter_table"] = run_dir / RAW_ROOT / "dataCenter.parquet"
            report["cases"].append(
                {
                    "batch_label": label,
                    "candidate": case["candidate"],
                    "scenario": case["scenario"],
                    "experiment_kind": item.get(
                        "experiment_kind",
                        suite_item.get("experiment_kind", case.get("experiment_kind", legacy_kind)),
                    ),
                    "scope": case.get("scope"),
                    **computed,
                    "resources": resources,
                    "missing_components": missing,
                    "lineage": {
                        "runner_directory": str(run_dir),
                        **{
                            name: {
                                "path": str(path) if path else None,
                                "sha256": _file_sha256(path) if path else None,
                            }
                            for name, path in paths.items()
                        },
                    },
                }
            )
    return report


def _figure_text_page(pdf, title, paragraphs):
    """Write one text page with explicit wrapping inside the page margins.

    Args:
        pdf (PdfPages): Open report writer.
        title (str): Page heading.
        paragraphs (list[str]): Unwrapped prose blocks; the caller must limit total page text.
    """
    figure = plt.figure(figsize=(11.69, 8.27))
    figure.suptitle(title, fontsize=18, fontweight="bold", y=0.94)
    y = 0.84
    for paragraph in paragraphs:
        wrapped = textwrap.fill(paragraph, width=118)
        figure.text(0.08, y, wrapped, fontsize=10.5, va="top", linespacing=1.45)
        y -= 0.025 + len(wrapped.splitlines()) * 10.5 * 1.45 / (8.27 * 72)
    pdf.savefig(figure)
    plt.close(figure)


ACTIONS = ("unchanged", "scale-up", "scale-down")
ACTION_COLORS = {"unchanged": "#2864b4", "scale-up": "#218358", "scale-down": "#c56a16"}
CURVE_METRICS = ("energy_joules", "completed_tasks", "unfinished_tasks")
PLOT_METRICS = ("energy_joules", "completed_tasks")


def _scenario_band(rows):
    """Summarize equally weighted scenarios at corresponding coordinates.

    Args:
        rows (list[list[float]]): Nonempty, equally sized scenario series.

    Returns:
        dict: Pointwise median and observed minimum/maximum, not confidence limits.
    """
    columns = list(zip(*rows))
    return {
        "minimum": [min(values) for values in columns],
        "median": [_percentile(values, 0.5) for values in columns],
        "maximum": [max(values) for values in columns],
    }


def _aligned_curve(case, metric, times):
    """Align one case without interpolating discrete counts or freezing idle energy.

    Args:
        case (dict): Evaluated case including worker idle power and validated curves.
        metric (str): Energy or task-count curve key.
        times (list[float]): Shared cutoff-relative seconds, including all event times.

    Returns:
        list[float]: Linear energy or right-continuous count samples. After a case
            ends, counts stay fixed and included workers consume configured idle power.
    """
    source = case["curves"]["time_seconds"]
    values = case["curves"][metric]
    aligned = []
    for timestamp in times:
        index = bisect_right(source, timestamp) - 1
        value = values[index]
        if metric == "energy_joules":
            if index == len(source) - 1:
                value += (timestamp - source[-1]) * case["included_idle_power_w"]
            else:
                fraction = (timestamp - source[index]) / (source[index + 1] - source[index])
                value += fraction * (values[index + 1] - value)
        aligned.append(value)
    return aligned


def aggregate_actions(cases):
    """Build action distributions from matched futures for one starting input.

    Each scenario has equal weight. Response curves first compute each scenario's
    Job-response percentiles, then summarize those values across scenarios; Jobs
    from different futures are never pooled. The overall curve combines backlog and
    future Jobs within each scenario before computing percentiles. Empty response
    cohorts stay unavailable; omitted scale-down Jobs remain outside every curve.

    Args:
        cases (list[dict]): Evaluated cases for exactly three actions at one cutoff.

    Returns:
        dict: Shared times, boundaries, action curves and response quantile bands.

    Raises:
        ValueError: Actions, scenario identities, scopes or evaluation boundaries disagree.
    """
    grouped = {action: [] for action in ACTIONS}
    identities = set()
    for case in cases:
        identity = (case["candidate"], case["scenario"])
        if identity in identities or case["candidate"] not in grouped:
            raise ValueError("duplicate or unknown action/scenario")
        identities.add(identity)
        grouped[case["candidate"]].append(case)
    scenario_sets = [{case["scenario"] for case in group} for group in grouped.values()]
    if not scenario_sets[0] or any(group != scenario_sets[0] for group in scenario_sets):
        raise ValueError("three actions must have the same nonempty scenario inventory")
    boundaries = cases[0]["boundaries"]
    if any(
        any(
            case["boundaries"][key] != boundaries[key]
            for key in ("cutoff_ms", "arrival_horizon_seconds", "evaluation_seconds")
        )
        or case["batch_label"] != cases[0]["batch_label"]
        for case in cases
    ):
        raise ValueError("action comparison requires shared input and evaluation boundaries")
    times = sorted({time for case in cases for time in case["curves"]["time_seconds"]})
    actions = {}
    for action, group in grouped.items():
        scopes = {case["scope"] for case in group}
        if len(scopes) != 1:
            raise ValueError("action scenarios disagree on accounting scope")
        responses = {}
        for cohort in ("backlog", "future", "all"):
            components = ("backlog", "future") if cohort == "all" else (cohort,)
            samples = [
                [
                    value
                    for name in components
                    for value in case["windows"]["cohort_through_completion"]["cohorts"][name][
                        "response_samples_seconds"
                    ]
                ]
                for case in group
            ]
            responses[cohort] = (
                _scenario_band(
                    [[_percentile(values, q / 100) for q in range(101)] for values in samples]
                )
                if all(samples)
                else None
            )
        actions[action] = {
            "scope": next(iter(scopes)),
            "curves": {
                metric: _scenario_band([_aligned_curve(case, metric, times) for case in group])
                for metric in CURVE_METRICS
            },
            "responses": responses,
        }
    return {
        "scenario_count": len(scenario_sets[0]),
        "time_seconds": times,
        "response_percentiles": list(range(101)),
        "boundaries": {
            key: boundaries[key]
            for key in ("cutoff_ms", "arrival_horizon_seconds", "evaluation_seconds")
        },
        "actions": actions,
    }


def display_comparison(cases, comparison, *, smoothing_seconds=2.0):
    """Smooth individual count trajectories before recomputing their display bands.

    A positive Gaussian filter avoids negative counts and preserves monotonic completed
    counts. Nearest-value padding extends the first/last sample at the display boundary.
    Event times and endpoint counts become approximate; exact metrics are never mutated.

    Args:
        cases (list[dict]): The cases used to build comparison.
        comparison (dict): Exact action aggregates from aggregate_actions.
        smoothing_seconds (float): Positive Gaussian standard deviation in seconds.

    Returns:
        dict: Separate display aggregates; responses retain their exact values.

    Raises:
        ValueError: Smoothing width or the final comparison time is not finite and positive.
    """
    width = float(smoothing_seconds)
    end = float(comparison["time_seconds"][-1])
    if not math.isfinite(width + end) or width <= 0 or end <= 0:
        raise ValueError("positive finite smoothing width and final comparison time are required")
    times = np.linspace(0, end, math.ceil(end / min(0.25, width / 4)) + 1).tolist()
    display = deepcopy(comparison)
    display["time_seconds"] = times
    display["count_smoothing"] = {
        "method": "Gaussian",
        "sigma_seconds": width,
        "boundary_mode": "nearest",
    }
    for action, data in display["actions"].items():
        group = [case for case in cases if case["candidate"] == action]
        for metric in CURVE_METRICS:
            rows = [_aligned_curve(case, metric, times) for case in group]
            if metric != "energy_joules":
                rows = [
                    gaussian_filter1d(
                        np.asarray(row, dtype=float), width / times[1], mode="nearest"
                    ).tolist()
                    for row in rows
                ]
            data["curves"][metric] = _scenario_band(rows)
    return display


def _action_label(action, scope):
    """Label the action and expose incomplete accounting in every legend.

    Args:
        action (str): Candidate identifier.
        scope (str): Complete or remaining-workers-only accounting.

    Returns:
        str: Human-readable legend label.
    """
    label = {"unchanged": "Unchanged", "scale-up": "Scale up", "scale-down": "Scale down"}[action]
    return label + (" (partial)" if scope == "remaining_workers_only" else "")


def _draw_band(axis, coordinates, band, action, scope, *, factor=1):
    """Draw outlined scenario ranges without adding horizontal padding.

    Args:
        axis (matplotlib.axes.Axes): Target metric axis.
        coordinates (list[float]): Common times or response percentiles.
        band (dict): Median, minimum and maximum scenario values.
        action (str): Action identity controlling colour.
        scope (str): Accounting scope shown in the legend.
        factor (float): Display-unit conversion, such as joules to kilojoules.
    """
    color = ACTION_COLORS[action]
    axis.fill_between(
        coordinates,
        [value * factor for value in band["minimum"]],
        [value * factor for value in band["maximum"]],
        color=color,
        alpha=0.045,
    )
    for statistic in ("minimum", "maximum", "median"):
        median = statistic == "median"
        axis.plot(
            coordinates,
            [value * factor for value in band[statistic]],
            color=color,
            linewidth=2.4 if median else 0.8,
            alpha=1 if median else 0.75,
            linestyle={"unchanged": "-", "scale-up": "-.", "scale-down": "--"}[action],
            label=_action_label(action, scope) if median else None,
        )
    axis.set_xlim(coordinates[0], coordinates[-1])
    axis.grid(alpha=0.2)


def _input_title(cases):
    """Name the initial unfinished inventory using the unchanged action.

    Args:
        cases (list[dict]): Matched cases including unchanged.

    Returns:
        str: Initial backlog label, or an explicit range for varying inventories.
    """
    counts = sorted(
        {
            case["windows"]["cohort_through_completion"]["cohorts"]["backlog"]["included"]
            for case in cases
            if case["candidate"] == "unchanged"
        }
    )
    if counts == [0]:
        return "No initial backlog"
    label = str(counts[0]) if len(counts) == 1 else f"{counts[0]}–{counts[-1]}"
    return f"Initial backlog: {label} Jobs"


def _finish_axes(axis, *, integer_y=False, x_maximum=None):
    """End nonnegative axes on evenly spaced, rounded ticks covering all shared data.

    Round the axes only: never extrapolate curves to the rounded endpoint. Call after
    all panels sharing an axis are populated so larger alternatives cannot be clipped.

    Args:
        axis (matplotlib.axes.Axes): Populated linear metric plot.
        integer_y (bool): Require whole-Job ticks for count plots.
        x_maximum (float or None): Known domain endpoint, including empty percentile plots.
    """
    for dimension, integer in (("x", False), ("y", integer_y)):
        siblings = (
            axis.get_shared_x_axes() if dimension == "x" else axis.get_shared_y_axes()
        ).get_siblings(axis)
        maxima = [getattr(sibling.dataLim, f"{dimension}max") for sibling in siblings]
        maximum = max((value for value in maxima if math.isfinite(value)), default=0)
        if dimension == "x" and x_maximum is not None:
            maximum = max(maximum, x_maximum)
        ticks = MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10], integer=integer).tick_values(
            0, maximum if maximum > 0 else 1
        )
        ticks = ticks[ticks >= 0]
        if dimension == "x":
            axis.set_xticks(ticks)
            axis.set_xlim(ticks[0], ticks[-1])
        else:
            axis.set_yticks(ticks)
            axis.set_ylim(ticks[0], ticks[-1])
    axis.tick_params(labelbottom=True, labelleft=True)


def _plot_batch_page(pdf, cases, comparison):
    """Render energy and completed-Job curves for the selected workload.

    Args:
        pdf (PdfPages): Open report writer.
        cases (list[dict]): Matching evaluated cases.
        comparison (dict): Display distributions on a common time grid.
    """
    count = comparison["scenario_count"]
    horizon = comparison["boundaries"]["arrival_horizon_seconds"]
    evaluation = comparison["boundaries"]["evaluation_seconds"]
    figure, axes = plt.subplots(2, 1, figsize=(11.69, 8.27), sharex=True)
    figure.subplots_adjust(top=0.80, bottom=0.15, left=0.09, right=0.97, hspace=0.38)
    figure.suptitle("The demo: compare three capacity choices", fontsize=17, y=0.96)
    figure.text(
        0.09,
        0.89,
        f"{_input_title(cases)} + arrivals over {horizon:g} seconds; "
        f"{count} possible futures.\n"
        "These simulated alternatives illustrate capacity choices; "
        "they do not validate actual scaling.",
        fontsize=10,
        linespacing=1.5,
    )
    for axis, metric, title in zip(
        axes, ("energy_joules", "completed_tasks"), ("Cluster energy use", "Completed Jobs")
    ):
        _metric_axis(axis, comparison, cases, metric)
        axis.set_title(title, fontsize=12)
        for label in axis.texts:
            label.set_text(f"Arrivals: first {horizon:g} s | measurement window: {evaluation:g} s")
        if metric == "completed_tasks":
            axis.get_legend().remove()
            axis.set_xlabel("Seconds from the start of the simulation")
        else:
            axis.set_xlabel("")
        _finish_axes(axis, integer_y=metric == "completed_tasks")
    figure.text(
        0.09,
        0.055,
        "Bold lines: medians. Faint bands: smallest to largest result "
        "across the possible futures.\n"
        "Scale-down omits removed work; energy assumptions are uncalibrated. "
        "No best action is established.",
        fontsize=9,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)


def _plot_response_page(pdf, cases, comparison):
    """Show all modeled responses first, with separate cohort diagnostics below.

    Args:
        pdf (PdfPages): Open report writer.
        cases (list[dict]): Cases with matched sampled futures.
        comparison (dict): Per-action response percentile bands and scopes.
    """
    count = comparison["scenario_count"]
    figure = plt.figure(figsize=(11.69, 8.27))
    grid = figure.add_gridspec(
        2, 2, top=0.81, bottom=0.17, left=0.09, right=0.97, hspace=0.50, wspace=0.27
    )
    figure.suptitle("The same capacity choices: Job response times", fontsize=17, y=0.96)
    figure.text(
        0.09,
        0.89,
        f"Same workload and {count} futures as the preceding action page. "
        "Jobs are followed through completion.\n"
        "At 90% on the horizontal axis, read the response time "
        "within which 90% of the Jobs finish.",
        fontsize=10,
        linespacing=1.5,
    )
    shared_axis = None
    for cohort, position, title in (
        ("all", grid[0, :], "All modeled Jobs"),
        ("future", grid[1, 0], "Jobs arriving after the start"),
        ("backlog", grid[1, 1], "Jobs already present at the start"),
    ):
        axis = figure.add_subplot(position, sharey=shared_axis)
        shared_axis = axis
        _metric_axis(axis, comparison, cases, cohort)
        _finish_axes(axis, x_maximum=100)
        axis.set_title(title, fontsize=12)
        if cohort != "all" and axis.get_legend() is not None:
            axis.get_legend().remove()
    figure.text(
        0.09,
        0.06,
        "Response time starts at original Job creation, "
        "including time spent waiting before this simulation.\n"
        + (
            "Scale-down remains partial. "
            if any(c.get("scope") == "remaining_workers_only" for c in cases)
            else "Cordon retains assigned executable work until completion. "
        )
        + "These are simulated action scenarios, separate from measured application execution.",
        fontsize=9,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)


def _prepare_comparisons(report, reference_batch=None):
    """Collect complete comparisons and put the requested input first.

    Args:
        report (dict): Verified batches and evaluated cases.
        reference_batch (str or Path or None): Input path selected for presentation;
            defaults to the first batch containing all three actions.

    Returns:
        tuple[list, list[str]]: Ordered (batch, cases, aggregates) entries and exclusions.

    Raises:
        ValueError: The requested reference is absent or lacks all three actions.
    """
    comparisons, omitted = [], []
    for batch in report["batches"]:
        cases = [case for case in report["cases"] if case["batch_label"] == batch["label"]]
        missing = sorted(set(ACTIONS) - {case["candidate"] for case in cases})
        if missing:
            omitted.append(f"{batch['label']}: {', '.join(missing)} unavailable")
        else:
            comparisons.append((batch, cases, aggregate_actions(cases)))
    if reference_batch is not None:
        selected = [
            entry
            for entry in comparisons
            if Path(entry[0]["path"]).resolve() == Path(reference_batch).resolve()
        ]
        if not selected:
            raise ValueError("reference batch must be an input containing all three actions")
        comparisons.remove(selected[0])
        comparisons.insert(0, selected[0])
    return comparisons, omitted


def _metric_axis(axis, comparison, cases, metric):
    """Draw the same action comparison in either page layout.

    Args:
        axis (matplotlib.axes.Axes): Target plot; shared limits are finalized by the caller.
        comparison (dict): Matched action distributions.
        cases (list[dict]): Cases supplying cohort inventory for empty-response labels.
        metric (str): Energy/count curve or all/future/backlog response distribution.
    """
    response = metric not in PLOT_METRICS
    key = "responses" if response else "curves"
    coordinates = comparison["response_percentiles" if response else "time_seconds"]
    if all(data[key][metric] is not None for data in comparison["actions"].values()):
        for action, data in comparison["actions"].items():
            _draw_band(
                axis,
                coordinates,
                data[key][metric],
                action,
                data["scope"],
                factor=0.001 if metric == "energy_joules" else 1,
            )
        axis.legend(loc="upper left", fontsize=8, ncol=3)
    else:
        components = ("backlog", "future") if metric == "all" else (metric,)
        empty = all(
            case["windows"]["cohort_through_completion"]["cohorts"][name]["included"] == 0
            for case in cases
            for name in components
        )
        message = (
            {
                "backlog": "No Jobs at the cutoff",
                "future": "No sampled arrivals",
                "all": "No modeled Jobs",
            }[metric]
            if empty
            else "Comparison unavailable: at least one action / future has no response samples"
        )
        axis.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            transform=axis.transAxes,
            fontsize=10,
            wrap=True,
        )
    axis.set_xlabel("Job response percentile (%)" if response else "Seconds since forecast cutoff")
    axis.set_ylabel(
        "Response time (seconds)"
        if response
        else "Energy (kJ)"
        if metric == "energy_joules"
        else "Jobs"
    )
    if not response:
        bounds = comparison["boundaries"]
        horizon, evaluation = bounds["arrival_horizon_seconds"], bounds["evaluation_seconds"]
        axis.axvline(horizon, color="#666666", linestyle=":", alpha=0.6)
        if evaluation != horizon:
            axis.axvline(evaluation, color="#666666", linestyle="-.", alpha=0.6)
        label = (
            f"H = E = {horizon:g}s"
            if horizon == evaluation
            else f"H = {horizon:g}s; E = {evaluation:g}s"
        )
        axis.text(0.99, 0.94, label, transform=axis.transAxes, ha="right", va="top", fontsize=8)


def render_pdf(report, path, reference_batch=None):
    """Show the selected workload using the shared action-page renderers.

    Batches missing an action remain in metrics. Exact aggregates are retained under
    action_comparisons; display settings and the selected reference are separate metadata.
    Reference selection affects presentation only and never ranks scaling actions.

    Args:
        report (dict): Evaluated metrics; presentation metadata is added in place.
        path (str or Path): New PDF artifact path in an existing directory.
        reference_batch (str or Path or None): Explicit reference input, else first eligible batch.

    Raises:
        ValueError: Comparisons are unmatched or the requested reference is ineligible.
    """
    comparisons, omitted = _prepare_comparisons(report, reference_batch)
    report["action_comparisons"] = [
        {"batch_label": batch["label"], **comparison} for batch, _, comparison in comparisons
    ]
    report.pop("reference_summary", None)
    report["presentation"] = {
        "reference_batch": comparisons[0][0]["label"] if comparisons else None,
        "count_smoothing": {
            "method": "Gaussian per scenario before aggregation",
            "sigma_seconds": 2.0,
            "boundary_mode": "nearest",
            "maximum_grid_step_seconds": 0.25,
        },
        "range": "observed minimum and maximum, not confidence limits",
        "exact_metrics_unchanged": True,
        "axis_bounds": "outward-rounded, evenly spaced endpoint ticks",
    }
    reference = (
        _input_title(comparisons[0][1]) if comparisons else "No complete comparison available"
    )
    sources = "; ".join(
        f"{batch['label']} = {_input_title(cases)}" for batch, cases, _ in comparisons
    )
    partial = any(c.get("scope") == "remaining_workers_only" for c in report["cases"])
    pinned = any(c.get("initialization_mode") == PINNED_MODE for c in report["cases"])
    with PdfPages(path) as pdf:
        _figure_text_page(
            pdf,
            "OpenDC provisional evaluation — action comparison",
            [
                f"Selected workload: {reference}. All three actions use the same initial state "
                "and sampled futures. This is a presentation choice, not a preferred scaling "
                "action. Other starting inputs remain in metrics.json. "
                "Batch numbers identify input evidence, not model versions. "
                "Starting inputs: " + (sources or "none."),
                "Read each graph across actions: blue = unchanged, green = scale up, orange "
                "dashed "
                + ("= scale down (partial). " if partial else "= scale down with native cordon. ")
                + "Bold lines are medians; thin outlines and faint shading "
                "show the observed min–max across equally weighted sampled futures, "
                "not confidence "
                "intervals. Job counts use 2-second Gaussian display smoothing per scenario; "
                "event timing and endpoint counts are approximate. Exact numerical metrics "
                "remain available in metrics.json.",
                "Backlog means all unfinished Jobs at the cutoff (queued, starting or running). "
                "Future means sampled arrivals during [0, H). Future response describes new "
                "demand; "
                "backlog response describes recovery and retains pre-cutoff waiting. An empty "
                "backlog has no response curve. All modeled Jobs combines both cohorts within "
                "each future, then aggregates equally across futures. These response curves "
                "follow modeled Jobs through completion, not only finishes by E; omitted Jobs "
                "remain outside them.",
                "H is the arrival horizon; E is the fixed evaluation cutoff (default E = H). "
                "The other window ends at max(H, last included completion). Energy interpolates "
                "native cumulative joules and extends at configured idle power, including "
                "alignment to shared endpoints. Response summaries by E include completions "
                "only and may be censored. Completed Jobs counts finishes by each plotted time. "
                "Axes round outward to evenly spaced ticks; curves are not extrapolated to "
                "these rounded bounds.",
                (
                    "Scale down omits the selected worker and its assigned Jobs: energy and work "
                    "totals are partial, and omitted completion/energy are unknown. "
                    if partial
                    else "Native cordon finishes assigned executable work "
                    "and closes the selected host; "
                    "no queued or future task is admitted there. "
                )
                + "Lower totals or "
                "shorter responses alone cannot identify the best action. No scoring or automatic "
                "decision is introduced. "
                + (
                    "Represented assigned work is pinned at zero; "
                    "startup delay and exhausted occupancy remain unmodeled. "
                    if pinned
                    else "Running remainders restart at zero without restoring placement "
                    "or startup occupancy. "
                )
                + "Each worker has C−1 modeled cores. Default "
                "100 W idle / 200 W maximum power is uncalibrated. Cluster energy here means "
                "modeled worker energy. Control-plane, runner and "
                "separate daemon overhead are excluded.",
                "Supporting batches without all three actions remain in metrics.json but have no "
                "comparison graphs: " + ("; ".join(omitted) if omitted else "none."),
            ],
        )
        if comparisons:
            _, cases, exact = comparisons[0]
            _plot_batch_page(pdf, cases, display_comparison(cases, exact))
            _plot_response_page(pdf, cases, exact)


def create_report(
    batch_dirs,
    output_dir,
    evaluation_seconds=None,
    reference_batch=None,
    *,
    metrics_file=None,
):
    """Analyze saved batches or rerender saved metrics into a new report directory.

    Args:
        batch_dirs (list[str or Path] or None): Batch directories, absent when using metrics_file.
        output_dir (str or Path): New nonoverlapping report directory.
        evaluation_seconds (float or None): Positive common E, defaulting per case to H.
        reference_batch (str or Path or None): Reference input for the first results pages.
        metrics_file (str or Path or None): Saved metrics, without requiring original experiments.

    Returns:
        dict: Written report metrics.

    Raises:
        FileExistsError: Output already exists.
        ValueError: Input/output paths overlap or evidence is invalid.
    """
    if bool(batch_dirs) == bool(metrics_file):
        raise ValueError("provide batch directories or a saved metrics file")
    if metrics_file and evaluation_seconds is not None:
        raise ValueError("changing the evaluation window requires batch evidence")
    output = Path(output_dir).resolve()
    inputs = [Path(directory).resolve() for directory in (batch_dirs or [metrics_file])]
    for directory in inputs:
        if (
            output == directory
            or output.is_relative_to(directory)
            or directory.is_relative_to(output)
        ):
            raise ValueError("output directory must not overlap batch input evidence")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    if metrics_file:
        report = json.loads(Path(metrics_file).read_text(encoding="utf-8"))
        if report["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported saved evaluation metrics")
        if reference_batch is None:
            selected = report.get("presentation", {}).get("reference_batch")
            reference_batch = next(
                (batch["path"] for batch in report["batches"] if batch["label"] == selected), None
            )
    else:
        report = evaluate_batches(inputs, evaluation_seconds)
    output.mkdir(parents=True, exist_ok=False)
    render_pdf(
        report,
        output / "report.pdf",
        reference_batch,
    )
    write_json(output / "metrics.json", report)
    return report


def main(argv=None):
    """Run offline evaluation from command-line arguments.

    Args:
        argv (list[str] or None): Arguments excluding program name, or process arguments.

    Returns:
        int: Zero for success and two for rejected input or report failure.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Limitations: provisional replay is descriptive; fixed-window response statistics are "
            "completion-only and censored; partial scopes exclude omitted-worker work and energy; "
            "the report makes no ranking, SLO, or policy recommendation."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--metrics-file", type=Path, help="rerender saved metrics without raw experiments"
    )
    source.add_argument(
        "--batch-dir",
        type=Path,
        action="append",
        help="successful opendc-batch-v1 directory; repeat for separately prepared inputs",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="new report directory")
    parser.add_argument(
        "--evaluation-seconds",
        type=float,
        help="positive fixed endpoint E in seconds; defaults independently to each case horizon H",
    )
    parser.add_argument(
        "--reference-batch",
        type=Path,
        help="batch input to show first; defaults to first complete comparison",
    )
    args = parser.parse_args(argv)
    try:
        create_report(
            args.batch_dir,
            args.output_dir,
            args.evaluation_seconds,
            args.reference_batch,
            metrics_file=args.metrics_file,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    return 0


def render_action_pages(pdf, report):
    """Append two self-contained pages for each saved three-action comparison.

    Args:
        pdf (PdfPages): Open report destination.
        report (dict): Saved action metrics, requiring no original experiment directories.

    Raises:
        ValueError: No complete three-action comparison is available.
    """
    comparisons, omitted = _prepare_comparisons(report)
    if not comparisons:
        raise ValueError("No complete action comparison: " + "; ".join(omitted))
    for _, cases, exact in comparisons:
        _plot_batch_page(pdf, cases, display_comparison(cases, exact))
        _plot_response_page(pdf, cases, exact)


if __name__ == "__main__":
    raise SystemExit(main())
