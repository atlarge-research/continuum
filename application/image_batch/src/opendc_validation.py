"""Retrospective unchanged replay and observation comparison for the manual demo."""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

from opendc_evaluate import (
    _resources,
    load_batch,
    evaluate_batches,
)

from opendc_report import render_report
from forecast_trace import bounded_read, milliseconds, read_trace
from opendc_inputs import file_hashes, write_json
from opendc_scenarios import (
    SUITE_CONTRACT,
    _enrich_backlog,
    _future_metadata,
    _load_evidence,
    _worker_records,
    _write_case,
)


def prepare_validation_suite(
    forecast_dir,
    observer_dir,
    worker_config,
    output_dir,
    *,
    horizon_seconds=60,
    scenarios=10,
    arrival_source="forecast",
):
    """Derive unchanged cases from a verified causal parent without resampling.

    Known arrivals deliberately use later evidence for identities/timestamps only.
    Runtime profiles and backlog always come from the causal parent. Forecast
    subsets preserve the legacy sampler and exact shared parent futures.

    Args:
        forecast_dir (str or Path): Ready parent forecast and simulation bundle.
        observer_dir (str or Path): Original observer capture.
        worker_config (dict): Configured worker cores and memory.
        output_dir (str or Path): New suite destination.
        horizon_seconds (int): Positive horizon no longer than the parent horizon.
        scenarios (int): Positive prefix length, or one for known-arrival replay.
        arrival_source (str): ``forecast`` or retrospective ``known-arrival``.

    Returns:
        dict: Ready suite manifest compatible with the existing batch runner.

    Raises:
        ValueError: Parent evidence or requested derivation is invalid.
        FileExistsError: The destination already exists.
    """
    output = Path(output_dir).resolve()
    forecast_dir, observer_dir = Path(forecast_dir).resolve(), Path(observer_dir).resolve()
    for source in (forecast_dir, observer_dir):
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("output and source evidence directories must be separate")
    if output.exists():
        raise FileExistsError(output)
    forecast, simulation, initial, template, trace, parent, boundaries = _load_evidence(
        forecast_dir, observer_dir
    )
    # Counts must be exact integers: bool is an int subclass but is not a scenario count.
    # pylint: disable=unidiomatic-typecheck
    if (
        type(horizon_seconds) is not int
        or horizon_seconds <= 0
        or horizon_seconds * 1000 > simulation["horizon_ms"]
        or type(scenarios) is not int
        or scenarios <= 0
        or scenarios > len(parent)
        or arrival_source not in ("forecast", "known-arrival")
        or (arrival_source == "known-arrival" and scenarios != 1)
    ):
        raise ValueError("invalid horizon, scenario prefix or arrival source")
    # pylint: enable=unidiomatic-typecheck
    backlog, exhausted = _enrich_backlog(initial, trace)
    configured, active = _worker_records(worker_config, trace, template, backlog, exhausted)
    cutoff, horizon = simulation["cutoff_ms"], horizon_seconds * 1000
    futures = []
    observation_boundaries = None
    if arrival_source == "known-arrival":
        rows, observation_boundaries = bounded_read(observer_dir)
        observed, _ = read_observations(rows, forecast["settings"]["run_id"])
        arrivals = sorted(
            (
                (uid, row)
                for uid, row in observed.arrivals.items()
                if cutoff <= row["creation_ms"] < cutoff + horizon and uid not in trace.arrivals
            ),
            key=lambda item: (item[1]["creation_ms"], item[0]),
        )
        next_id = (
            max(
                [r["task"]["id"] for r in backlog]
                + [r["task_id"] for r in exhausted]
                + [len(trace.arrivals)],
                default=0,
            )
            + 1
        )
        records = []
        source = template["record"]["source"]
        for task_id, (uid, arrival) in enumerate(arrivals, next_id):
            task = copy.deepcopy(template["record"]["task"])
            task.update(id=task_id, submission_time=arrival["creation_ms"] - cutoff)
            for fragment in task["fragments"]:
                fragment["id"] = task_id
            metadata = _future_metadata(
                {
                    "task_id": task_id,
                    "original_submission_ms": arrival["creation_ms"],
                    "template_job_uid": source["kubernetes_job_uid"],
                }
            )
            metadata["identity"]["kubernetes_job_uid"] = uid
            records.append({"task": task, "metadata": metadata})
        futures.append(records)
    else:
        for index, tasks in enumerate(parent[:scenarios]):
            lineage = {r["task_id"]: r for r in simulation["scenarios"][index]["future_tasks"]}
            futures.append(
                [
                    {"task": copy.deepcopy(task), "metadata": _future_metadata(lineage[task["id"]])}
                    for task in tasks
                    if task["id"] in lineage and task["submission_time"] < horizon
                ]
            )
    source_hashes = file_hashes(forecast_dir)
    output.mkdir(parents=True)
    evidence = output / "source-evidence"
    evidence.mkdir()
    shutil.copytree(forecast_dir, evidence / "forecast")
    if file_hashes(evidence / "forecast") != source_hashes:
        raise ValueError("parent changed during evidence copy")
    derived = {**simulation, "horizon_ms": horizon}
    experiments = []
    for index, future in enumerate(futures):
        records = copy.deepcopy(backlog) + future
        relative = Path("experiments") / "unchanged" / f"{index:04d}"
        _write_case(
            output / relative,
            "unchanged",
            index,
            [configured[name] for name in active],
            [r["task"] for r in records],
            records,
            [],
            exhausted,
            derived,
            "provisional-trace",
            None,
            arrival_source,
        )
        experiments.append(
            {"candidate": "unchanged", "scenario": index, "input_dir": relative.as_posix()}
        )
    manifest = {
        "contract": SUITE_CONTRACT,
        "status": "ready",
        "initialization_mode": "provisional-trace",
        "experiment_kind": arrival_source,
        "cutoff_ms": cutoff,
        "horizon_ms": horizon,
        "active_workers": active,
        "template_sha256": template["sha256"],
        "source_prefixes": boundaries,
        "observation_prefixes": observation_boundaries,
        "initial_membership": copy.deepcopy(simulation["membership"]),
        "derivation": {
            "method": "verified_parent_prefix_and_timestamp_truncation",
            "parent_horizon_ms": simulation["horizon_ms"],
            "parent_scenarios": len(parent),
            "scenarios": scenarios,
            "parent_sha256": source_hashes,
        },
        "placement": {
            "kubernetes_profile": "fns-packing",
            "score": "cpu MostAllocated",
            "opendc": "ordered fitting used hosts before empty hosts; no weighers",
            "initial_placement_restored": False,
        },
        "experiments": experiments,
        "unavailable_candidates": [],
        "sha256": file_hashes(output, exclude=("manifest.json",)),
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def observed_jobs(trace):
    """Extract retrospective Job outcomes while preserving missing compute timing.

    Args:
        trace (Trace): Full frozen capture read for one workload run.

    Returns:
        list[dict]: Observed arrivals, terminal outcomes and classifier timing by UID.
    """
    records = {
        uid: {
            "uid": uid,
            "creation_ms": arrival["creation_ms"],
            "start_ms": None,
            "finish_ms": None,
            "job_finish_ms": None,
            "node_name": None,
            "status": "unknown",
            "censored_through_ms": None,
        }
        for uid, arrival in trace.arrivals.items()
    }
    for _, state in trace.states:
        for group in state.get("jobs", {}).values():
            for job in group:
                uid = job.get("kubernetes_job_uid")
                if uid in records and job.get("node_name"):
                    records[uid]["node_name"] = job["node_name"]
    if trace.states:
        last_time, last_state = trace.states[-1]
        for jobs in last_state.get("jobs", {}).values():
            for job in jobs:
                uid = job.get("kubernetes_job_uid")
                if uid in records and job.get("execution_state") != "terminated":
                    records[uid]["censored_through_ms"] = last_time
                    records[uid]["status"] = "unfinished"
    for item in trace.completed:
        source = item["source"]
        uid = source["kubernetes_job_uid"]
        if uid not in records:
            continue
        record = records[uid]
        record["status"] = source.get("terminal_status", "unknown")
        for source_key, target in (
            ("execution_start_time", "start_ms"),
            ("execution_completion_time", "finish_ms"),
            ("completion_time", "job_finish_ms"),
        ):
            if source.get(source_key):
                record[target] = milliseconds(source[source_key])
    return sorted(records.values(), key=lambda r: (r["creation_ms"], r["uid"]))


def read_observations(rows, run_id):
    """Read outcomes, retaining failed Jobs outside the successful runtime-profile reader.

    Args:
        rows (dict): Frozen observer streams.
        run_id (str): Workload identity to evaluate.

    Returns:
        tuple: Trace and complete observed arrival inventory with terminal status.
    """
    successful = {
        **rows,
        "workload.jsonl": [
            r for r in rows["workload.jsonl"] if r["source"]["terminal_status"] == "Complete"
        ],
    }
    trace = read_trace(successful, run_id, float("inf"))
    records = {r["uid"]: r for r in observed_jobs(trace)}
    for event in rows["observer-events.jsonl"]:
        if event["event_type"] == "job.failed":
            uid = event["details"]["kubernetes_job_uid"]
            if uid in records:
                records[uid]["status"] = "Failed"
                records[uid]["failure_observed_ms"] = milliseconds(event["timestamp"])
    for row in rows["workload.jsonl"]:
        source = row["source"]
        if source["workload_run_id"] != run_id or source["terminal_status"] == "Complete":
            continue
        uid = source["kubernetes_job_uid"]
        records[uid] = {
            "uid": uid,
            "creation_ms": milliseconds(row["task"]["submission_time"]),
            "start_ms": None,
            "finish_ms": None,
            "job_finish_ms": milliseconds(source["completion_time"]),
            "node_name": source.get("node_name"),
            "status": source["terminal_status"],
        }
        trace.arrivals.setdefault(uid, {"creation_ms": records[uid]["creation_ms"]})
    return trace, sorted(records.values(), key=lambda r: (r["creation_ms"], r["uid"]))


def compare_tasks(
    case,
    completions,
    observations,
    coverage_end_ms,
    *,
    window_seconds=120,
    target_seconds=60,
    state_coverage=None,
):
    """Compare a common target cohort with explicit completed-only response statistics.

    Forecast future identities are synthetic and are never matched to real Jobs.
    Known-arrival and backlog identities are matched exactly. Contextual arrivals
    outside the target window affect simulation but are excluded from scoring.

    Args:
        case (dict): Prepared unchanged experiment with original Job metadata.
        completions (list[dict]): Validated cutoff-relative native task completions.
        observations (list[dict]): Full retrospective outcomes from ``observed_jobs``.
        coverage_end_ms (int): Last captured state timestamp, bounding observation.
        window_seconds (int): Common completion evaluation window.
        target_seconds (int): Arrival window defining the scored future cohort.
        state_coverage (dict or None): Optional snapshot-gap eligibility from
            ``observation_coverage``.

    Returns:
        dict: Per-Job matches, curves, counts, errors, censored work and diagnostics.

    Raises:
        ValueError: Evaluation windows are nonpositive or native identities differ.
    """
    if window_seconds <= 0 or target_seconds <= 0:
        raise ValueError("evaluation windows must be positive")
    cutoff = case["cutoff_ms"]
    end = cutoff + window_seconds * 1000
    complete = {row["task_id"]: row for row in completions}
    if len(complete) != len(completions) or set(complete) != {
        r["task"]["id"] for r in case["tasks"]
    }:
        raise ValueError("native completion identities differ from prepared inputs")
    observed = {r["uid"]: r for r in observations}
    backlog_uids = {
        r["metadata"]["identity"].get("kubernetes_job_uid")
        for r in case["tasks"]
        if r["metadata"]["cohort"] == "backlog"
    }
    exhausted_uids = {
        r["metadata"]["identity"]["kubernetes_job_uid"]
        for r in case.get("model_exhausted_jobs", [])
    }
    target_observed = [
        r
        for r in observations
        if r["uid"] in backlog_uids or cutoff <= r["creation_ms"] < cutoff + target_seconds * 1000
    ]
    # Exhausted work remains a separate observed inventory, never an invented completion.
    target_observed = [r for r in target_observed if r["uid"] not in exhausted_uids]
    target_observed = [
        {**r, "cohort": "backlog" if r["uid"] in backlog_uids else "future"}
        for r in target_observed
    ]
    unknown = [
        r["uid"]
        for r in target_observed
        if r["finish_ms"] is None
        and r["status"] != "Failed"
        and (r.get("censored_through_ms") or 0) < end
    ]
    matched = []
    for item in case["tasks"]:
        metadata, task = item["metadata"], item["task"]
        if metadata["cohort"] == "future" and task["submission_time"] >= target_seconds * 1000:
            continue
        native = complete[task["id"]]
        uid = metadata["identity"].get("kubernetes_job_uid")
        truth = observed.get(uid)
        predicted_finish = cutoff + native["finish_time"]
        record = {
            "task_id": task["id"],
            "uid": uid,
            "cohort": metadata["cohort"],
            "phase": metadata.get("phase"),
            "original_creation_ms": metadata["original_creation_ms"],
            "predicted_finish_ms": predicted_finish,
            "predicted_response_seconds": (predicted_finish - metadata["original_creation_ms"])
            / 1000,
            "predicted_completed": predicted_finish <= end,
            "observed": truth,
            "match_status": "matched"
            if truth
            else ("synthetic_future" if uid is None else "unmatched"),
            "modeled_duration_seconds": task["duration"] / 1000,
            "rescheduled_wait_seconds": native["schedule_time"] / 1000
            if metadata.get("phase") == "running"
            else None,
            "placement_changed": (native.get("host_name") != metadata.get("preserved_assignment"))
            if metadata.get("preserved_assignment") and native.get("host_name")
            else None,
        }
        if truth and truth["finish_ms"] is not None:
            record["finish_error_seconds"] = (predicted_finish - truth["finish_ms"]) / 1000
            record["observed_response_seconds"] = (truth["finish_ms"] - truth["creation_ms"]) / 1000
            if truth["start_ms"] is not None:
                actual_work = max(
                    0,
                    truth["finish_ms"]
                    - (
                        max(cutoff, truth["start_ms"])
                        if metadata.get("phase") == "running"
                        else truth["start_ms"]
                    ),
                )
                record["runtime_or_remainder_error_seconds"] = (
                    task["duration"] - actual_work
                ) / 1000
                resume = (
                    max(cutoff, truth["start_ms"])
                    if metadata.get("phase") == "running"
                    else truth["start_ms"]
                )
                record["start_or_resume_error_seconds"] = (
                    cutoff + native["schedule_time"] - resume
                ) / 1000
                record["unmodeled_startup_seconds"] = (
                    max(0, truth["start_ms"] - cutoff) / 1000
                    if metadata.get("phase") == "startup"
                    else None
                )
            if truth["job_finish_ms"] is not None:
                record["job_completion_delay_seconds"] = (
                    truth["job_finish_ms"] - truth["finish_ms"]
                ) / 1000
        matched.append(record)
    unknown = sorted(set(unknown) | {r["uid"] for r in matched if r["match_status"] == "unmatched"})
    eligible = (
        coverage_end_ms >= end
        and not unknown
        and (state_coverage is None or state_coverage["complete"])
    )
    observed_complete = [
        r
        for r in target_observed
        if r["finish_ms"] is not None and r["finish_ms"] <= min(end, coverage_end_ms)
    ]
    grid = list(range(0, window_seconds + 1, 5))
    if grid[-1] != window_seconds:
        grid.append(window_seconds)
    predicted_curve = [
        sum(r["predicted_finish_ms"] <= cutoff + t * 1000 for r in matched) for t in grid
    ]
    observed_curve = [
        sum(r["finish_ms"] <= cutoff + t * 1000 for r in observed_complete) for t in grid
    ]
    paired = [
        r
        for r in matched
        if r["predicted_completed"]
        and r["observed"]
        and r["observed"]["finish_ms"] is not None
        and r["observed"]["finish_ms"] <= min(end, coverage_end_ms)
    ]
    return {
        "cutoff_ms": cutoff,
        "window_seconds": window_seconds,
        "target_seconds": target_seconds,
        "coverage_complete": eligible,
        "state_coverage": state_coverage,
        "initial_membership": copy.deepcopy(case.get("initial_membership")),
        "unknown_outcome_uids": unknown,
        "tasks": matched,
        "observations": target_observed,
        "grid_seconds": grid,
        "predicted_curve": predicted_curve,
        "observed_curve": observed_curve,
        "completion_curve_mae": float(np.mean(np.abs(np.asarray(predicted_curve) - observed_curve)))
        if eligible
        else None,
        "predicted_completed": sum(r["predicted_completed"] for r in matched),
        "observed_completed": len(observed_complete),
        "observed_already_complete_at_cutoff": sum(
            r["finish_ms"] <= cutoff for r in observed_complete
        ),
        "matched_completed_pairs": [
            {
                "uid": r["uid"],
                "cohort": r["cohort"],
                "predicted_response_seconds": r["predicted_response_seconds"],
                "observed_response_seconds": r["observed_response_seconds"],
            }
            for r in paired
        ],
        "matched_response_mae_seconds": float(
            np.mean([abs(r["finish_error_seconds"]) for r in paired])
        )
        if paired and eligible
        else None,
        "observed_unfinished": sum(
            r["uid"] not in unknown
            and r["status"] != "Failed"
            and (r["finish_ms"] is None or r["finish_ms"] > end)
            for r in target_observed
        ),
        "observed_censored_uids": [
            r["uid"]
            for r in target_observed
            if r["uid"] not in unknown
            and r["status"] != "Failed"
            and (r["finish_ms"] is None or r["finish_ms"] > min(end, coverage_end_ms))
        ],
        "observed_failed_uids": [r["uid"] for r in target_observed if r["status"] == "Failed"],
        "unmatched_observed_backlog": [
            r["uid"]
            for r in observations
            if r["creation_ms"] < cutoff
            and (r["finish_ms"] is None or r["finish_ms"] > cutoff)
            and (r["job_finish_ms"] is None or r["job_finish_ms"] > cutoff)
            and r.get("failure_observed_ms", float("inf")) > cutoff
            and r["uid"] not in backlog_uids | exhausted_uids
        ],
        "unmatched_predicted": [r["uid"] for r in matched if r["match_status"] == "unmatched"],
        "model_exhausted": [
            observed.get(uid, {"uid": uid, "status": "unmatched"}) for uid in sorted(exhausted_uids)
        ],
    }


def observation_coverage(timestamps, failures, start, end, max_gap_ms=3000):
    """Check bracketing state coverage and capture failures without filling gaps.

    Args:
        timestamps (list[int]): State observation times in epoch milliseconds.
        failures (list[int]): Capture-failure timestamps.
        start (int): Inclusive evaluation start.
        end (int): Inclusive evaluation end.
        max_gap_ms (int): Maximum acceptable spacing between state observations.

    Returns:
        dict: Coverage eligibility, missing edges, internal gaps and failures.
    """
    times = sorted(set(timestamps))
    gaps = [
        [a, b] for a, b in zip(times, times[1:]) if b > start and a < end and b - a > max_gap_ms
    ]
    errors = [t for t in failures if start <= t <= end]
    bracketed = bool(times) and times[0] <= start and times[-1] >= end
    return {
        "complete": bracketed and not gaps and not errors,
        "bracketed": bracketed,
        "gaps": gaps,
        "failures": errors,
    }


def summarize_scenarios(rows):
    """Summarize scenario medians and descriptive envelopes on a common grid.

    Args:
        rows (list[dict]): Nonempty matched comparisons for one configuration/cutoff.

    Returns:
        dict: Median/min/max completion curves, error and empirical range coverage.

    Raises:
        ValueError: No scenarios are supplied or observation curves differ.
    """
    if not rows or any(r["observed_curve"] != rows[0]["observed_curve"] for r in rows):
        raise ValueError("scenarios require identical observed curves")
    values = np.asarray([r["predicted_curve"] for r in rows])
    median, low, high = np.median(values, axis=0), values.min(axis=0), values.max(axis=0)
    observed = np.asarray(rows[0]["observed_curve"])
    eligible = all(r["coverage_complete"] for r in rows)
    return {
        "scenarios": len(rows),
        "completion_median": median.tolist(),
        "completion_min": low.tolist(),
        "completion_max": high.tolist(),
        "observed_curve": observed.tolist(),
        "completion_curve_mae": float(np.mean(np.abs(median - observed))) if eligible else None,
        "completion_envelope_coverage": float(np.mean((low <= observed) & (observed <= high)))
        if eligible
        else None,
        "completion_envelope_width": float(np.mean(high - low)),
        "coverage_complete": eligible,
    }


def _quantiles(values):
    """Return response median/p90, keeping empty cohorts explicitly unavailable.

    Args:
        values (list[float]): Completed response times in seconds.

    Returns:
        dict: Count and nullable median/p90.
    """
    return {
        "count": len(values),
        "median": float(np.median(values)) if values else None,
        "p90": float(np.percentile(values, 90)) if values else None,
    }


def execution_cost(cases):
    """Sum measured native runner elapsed time without replacing missing values by zero.

    Args:
        cases (list[dict]): Evaluated cases with runner resource measurements.

    Returns:
        float or None: Total native elapsed seconds, unavailable if any value is missing.
    """
    values = [c["resources"].get("actual_elapsed_seconds") for c in cases]
    return sum(values) if values and all(v is not None for v in values) else None


def initialization_diagnostics(cases):
    """Summarize known-arrival errors as Job-cutoff pairs, not independent unique Jobs.

    Args:
        cases (list[dict]): Evaluated cases from one chronological capture.

    Returns:
        dict: Phase-specific errors, assignment changes and omitted backlog inventory.
    """
    baseline = [
        c["comparisons"]["120"]
        for c in cases
        if c["arrival_source"] == "known-arrival" and c["horizon_seconds"] == 60
    ]
    tasks = [r for c in baseline for r in c["tasks"]]
    phases = {}
    for phase in ("queued", "startup", "running", "future"):
        selected = [r for r in tasks if r["phase"] == phase]
        metrics = {}
        for key in (
            "finish_error_seconds",
            "runtime_or_remainder_error_seconds",
            "rescheduled_wait_seconds",
            "unmodeled_startup_seconds",
            "job_completion_delay_seconds",
        ):
            values = [r[key] for r in selected if r.get(key) is not None]
            metrics[key] = {
                **_quantiles(values),
                "mean_absolute": float(np.mean(np.abs(values))) if values else None,
            }
        phases[phase] = {
            "job_cutoff_pairs": len(selected),
            "errors": metrics,
            "placement_changed": sum(r["placement_changed"] is True for r in selected),
            "placement_comparable": sum(r["placement_changed"] is not None for r in selected),
        }
    return {
        "basis": "H60 known arrivals; repeated Job-cutoff pairs are dependent",
        "phases": phases,
        "cutoffs": len(baseline),
        "model_exhausted_pairs": sum(len(c["model_exhausted"]) for c in baseline),
        "unmatched_pairs": sum(len(c["unmatched_predicted"]) for c in baseline),
    }


def evaluate_matrix(index_file, batch_dir):
    """Evaluate a saved chronological experiment matrix without fitting any model.

    Args:
        index_file (str or Path): Frozen matrix preparation index.
        batch_dir (str or Path): Successful, hash-verified sequential batch output.

    Returns:
        dict: Cutoff/configuration comparisons, per-Job records, coverage and costs.

    Raises:
        ValueError: Batch or matrix identities disagree.
    """
    index = json.loads(Path(index_file).read_text(encoding="utf-8"))
    directory, batch = load_batch(batch_dir)
    rows, boundaries = bounded_read(index["observer_dir"])
    trace, observations = read_observations(rows, index["run_id"])
    times = [t for t, _ in trace.states]
    expected = {r["global_scenario"]: r for r in index["experiments"]}
    if set(expected) != {r["scenario"] for r in batch["experiments"]}:
        raise ValueError("matrix and batch identities disagree")
    cases = []
    for item in batch["experiments"]:
        meta = expected[item["scenario"]]
        run_dir = directory / item["output_dir"] / item["runner_dir"]
        execution = json.loads((run_dir / "execution.json").read_text())
        case = json.loads((run_dir / "inputs/case.json").read_text())
        if (
            case["cutoff_ms"] != meta["cutoff_ms"]
            or case["horizon_ms"] != meta["horizon_seconds"] * 1000
        ):
            raise ValueError("matrix timing differs from executed inputs")
        coverage = observation_coverage(
            times, trace.capture_failures, case["cutoff_ms"], case["cutoff_ms"] + 120000
        )
        costs, missing_costs = _resources(run_dir, execution)
        comparisons = {}
        for window in (60, 120):
            window_coverage = observation_coverage(
                times, trace.capture_failures, case["cutoff_ms"], case["cutoff_ms"] + window * 1000
            )
            comparison = compare_tasks(
                case,
                execution["validation"]["tasks"],
                observations,
                times[-1],
                window_seconds=window,
                state_coverage=window_coverage,
            )
            comparisons[str(window)] = comparison
        cases.append(
            {
                **meta,
                "scope": case["scope"],
                "coverage": coverage,
                "resources": costs,
                "missing_resources": missing_costs,
                "case_wall_seconds": item.get("wall_seconds", item.get("terminal_seconds")),
                "comparisons": comparisons,
            }
        )
    groups = []
    keys = sorted(
        {(c["cutoff_index"], c["seed"], c["horizon_seconds"], c["arrival_source"]) for c in cases}
    )
    for cutoff_index, seed, horizon, source in keys:
        available = sorted(
            [
                c
                for c in cases
                if (c["cutoff_index"], c["seed"], c["horizon_seconds"], c["arrival_source"])
                == (cutoff_index, seed, horizon, source)
            ],
            key=lambda c: c["scenario"],
        )
        counts = (3, 10, 20) if source == "forecast" and horizon == 60 else (len(available),)
        for count in counts:
            if len(available) < count:
                continue
            selected = available[:count]
            group = {
                "cutoff_index": cutoff_index,
                "cutoff_ms": selected[0]["cutoff_ms"],
                "seed": seed,
                "horizon_seconds": horizon,
                "arrival_source": source,
                "scenarios": count,
                "windows": {},
            }
            for window in (60, 120):
                comparison_rows = [c["comparisons"][str(window)] for c in selected]
                summary = summarize_scenarios(comparison_rows)
                summary["grid_seconds"] = comparison_rows[0]["grid_seconds"]
                summary["matched_response_pairs"] = [
                    len(r["matched_completed_pairs"]) for r in comparison_rows
                ]
                summary["matched_response_mae_seconds"] = [
                    r["matched_response_mae_seconds"] for r in comparison_rows
                ]
                end = group["cutoff_ms"] + window * 1000
                response = {}
                for cohort in ("overall", "backlog", "future"):
                    predicted = [
                        [
                            r["predicted_response_seconds"]
                            for r in row["tasks"]
                            if r["predicted_completed"] and cohort in ("overall", r["cohort"])
                        ]
                        for row in comparison_rows
                    ]
                    truth = [
                        r
                        for r in comparison_rows[0]["observations"]
                        if r["finish_ms"] is not None
                        and r["finish_ms"] <= end
                        and cohort in ("overall", r["cohort"])
                    ]
                    actual = [(r["finish_ms"] - r["creation_ms"]) / 1000 for r in truth]
                    statistics = [_quantiles(v) for v in predicted]
                    response[cohort] = {
                        "observed": _quantiles(actual),
                        "predicted": statistics,
                        "observed_values": actual,
                        "predicted_values": predicted,
                    }
                    for quantile in ("median", "p90"):
                        values = [r[quantile] for r in statistics if r[quantile] is not None]
                        truth_value = response[cohort]["observed"][quantile]
                        response[cohort][quantile] = {
                            "nonempty_scenarios": len(values),
                            "median": float(np.median(values)) if values else None,
                            "min": min(values) if values else None,
                            "max": max(values) if values else None,
                            "absolute_error": abs(float(np.median(values)) - truth_value)
                            if values and truth_value is not None and summary["coverage_complete"]
                            else None,
                            "covered": min(values) <= truth_value <= max(values)
                            if values and truth_value is not None and summary["coverage_complete"]
                            else None,
                        }
                summary["responses"] = response
                group["windows"][str(window)] = summary
            arrival_counts = [
                sum(r["cohort"] == "future" for r in c["comparisons"]["60"]["tasks"])
                for c in selected
            ]
            actual_arrivals = sum(
                group["cutoff_ms"] <= r["creation_ms"] < group["cutoff_ms"] + 60000
                for r in observations
            )
            group["arrivals"] = {
                "scenario_counts": arrival_counts,
                "observed": actual_arrivals,
                "median": float(np.median(arrival_counts)),
                "min": min(arrival_counts),
                "max": max(arrival_counts),
                "absolute_error": abs(float(np.median(arrival_counts)) - actual_arrivals),
                "covered": min(arrival_counts) <= actual_arrivals <= max(arrival_counts),
            }
            group["arrivals"]["coverage_complete"] = group["windows"]["60"]["coverage_complete"]
            if not group["arrivals"]["coverage_complete"]:
                group["arrivals"].update(absolute_error=None, covered=None)
            group["execution_seconds"] = execution_cost(selected)
            bins = np.arange(0, 65000, 5000) + group["cutoff_ms"]
            group["arrivals"]["observed_bins"] = np.histogram(
                [
                    r["creation_ms"]
                    for r in observations
                    if group["cutoff_ms"] <= r["creation_ms"] < group["cutoff_ms"] + 60000
                ],
                bins=bins,
            )[0].tolist()
            group["arrivals"]["scenario_bins"] = [
                np.histogram(
                    [
                        r["original_creation_ms"]
                        for r in c["comparisons"]["60"]["tasks"]
                        if r["cohort"] == "future"
                    ],
                    bins=bins,
                )[0].tolist()
                for c in selected
            ]
            groups.append(group)
    return {
        "split": index["split"],
        "index_file": str(Path(index_file).resolve()),
        "batch_dir": str(directory),
        "period_seconds": index["period_seconds"],
        "run_id": index["run_id"],
        "observation_prefixes": boundaries,
        "skipped": index["skipped"],
        "cases": cases,
        "groups": groups,
        "observed_jobs": observations,
        "initialization_diagnostics": initialization_diagnostics(cases),
    }


def configuration_summary(result):
    """Aggregate primary-seed results by configuration for validation-only selection.

    Args:
        result (dict): One chronological split returned by ``evaluate_matrix``.

    Returns:
        list[dict]: Error, descriptive coverage and execution cost per configuration.
    """
    output = []
    keys = sorted(
        {
            (g["horizon_seconds"], g["scenarios"])
            for g in result["groups"]
            if g["arrival_source"] == "forecast" and g["seed"] == 20261008
        }
    )
    for horizon, count in keys:
        groups = [
            g
            for g in result["groups"]
            if g["arrival_source"] == "forecast"
            and g["seed"] == 20261008
            and (g["horizon_seconds"], g["scenarios"]) == (horizon, count)
        ]
        usable = [g for g in groups if g["windows"]["120"]["coverage_complete"]]
        output.append(
            {
                "horizon_seconds": horizon,
                "scenarios": count,
                "eligible_cutoffs": len(usable),
                "total_cutoffs": len(groups),
                "completion_curve_mae": float(
                    np.mean([g["windows"]["120"]["completion_curve_mae"] for g in usable])
                )
                if usable
                else None,
                "envelope_coverage": float(
                    np.mean([g["windows"]["120"]["completion_envelope_coverage"] for g in usable])
                )
                if usable
                else None,
                "envelope_width": float(
                    np.mean([g["windows"]["120"]["completion_envelope_width"] for g in usable])
                )
                if usable
                else None,
                "arrival_mae": float(np.mean([g["arrivals"]["absolute_error"] for g in usable]))
                if usable
                else None,
                "mean_execution_seconds": float(np.mean([g["execution_seconds"] for g in groups]))
                if all(g["execution_seconds"] is not None for g in groups)
                else None,
            }
        )
        for label, field in (
            ("response_p90_mae", "absolute_error"),
            ("response_p90_envelope_coverage", "covered"),
        ):
            values = [
                g["windows"]["120"]["responses"]["overall"]["p90"][field]
                for g in usable
                if g["windows"]["120"]["responses"]["overall"]["p90"][field] is not None
            ]
            output[-1][label] = float(np.mean(values)) if values else None
        output[-1]["arrival_envelope_coverage"] = (
            float(np.mean([g["arrivals"]["covered"] for g in usable])) if usable else None
        )
    return output


def select_configuration(result):
    """Select experimental parameters on validation evidence only, never actions.

    Args:
        result (dict): Chronological validation split.

    Returns:
        dict: Locked horizon/count choice and its predeclared selection rule.

    Raises:
        ValueError: Evidence is not validation data or no complete cutoffs exist.
    """
    if result["split"] != "validation":
        raise ValueError("parameter selection requires validation evidence")
    candidates = [r for r in configuration_summary(result) if r["completion_curve_mae"] is not None]
    if not candidates:
        raise ValueError("no eligible validation cutoffs")
    selected = min(
        candidates,
        key=lambda r: (
            round(r["completion_curve_mae"], 6),
            r["mean_execution_seconds"]
            if r["mean_execution_seconds"] is not None
            else float("inf"),
            r["horizon_seconds"],
            r["scenarios"],
        ),
    )
    return {
        "selected": selected,
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "rule": "validation-only 120-second target-cohort completion-curve MAE; "
        "ties at 1e-6 by measured execution cost",
        "reference": {"horizon_seconds": 60, "scenarios": 10},
        "source_index": result.get("index_file"),
        "source_batch": result.get("batch_dir"),
    }


def write_validation_report(results, output_dir, selection=None, action_report=None):
    """Save reproducible numerical results, a compact CSV and the evaluation PDF.

    Args:
        results (list[dict]): Evaluated chronological splits.
        output_dir (str or Path): New destination, never an existing report directory.
        selection (dict or None): Locked validation-only parameter choice.
        action_report (dict or None): Explicitly illustrative three-action results.

    Returns:
        dict: Complete machine-readable report.

    Raises:
        FileExistsError: The requested output directory already exists.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": "opendc-observation-validation-v1",
        "results": results,
        "selection": selection,
        "action_report": action_report,
        "range_interpretation": "descriptive min–max, not calibrated confidence intervals",
    }
    write_json(output / "metrics.json", report)
    summaries = [
        {"split": result["split"], **row}
        for result in results
        for row in configuration_summary(result)
    ]
    if summaries:
        with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
    cutoffs = []
    for result in results:
        for group in result["groups"]:
            for window_seconds, window in group["windows"].items():
                cutoffs.append(
                    {
                        "split": result["split"],
                        "cutoff_index": group["cutoff_index"],
                        "cutoff_ms": group["cutoff_ms"],
                        "arrival_source": group["arrival_source"],
                        "seed": group["seed"],
                        "horizon_seconds": group["horizon_seconds"],
                        "scenarios": group["scenarios"],
                        "window_seconds": window_seconds,
                        "coverage_complete": window["coverage_complete"],
                        "completion_curve_mae": window["completion_curve_mae"],
                        "envelope_coverage": window["completion_envelope_coverage"],
                        "envelope_width": window["completion_envelope_width"],
                        "arrival_error": group["arrivals"]["absolute_error"],
                        "arrival_covered": group["arrivals"]["covered"],
                        "response_median_error": window["responses"]["overall"]["median"][
                            "absolute_error"
                        ],
                        "response_p90_error": window["responses"]["overall"]["p90"][
                            "absolute_error"
                        ],
                        "native_execution_seconds": group["execution_seconds"],
                    }
                )
    if cutoffs:
        with (output / "cutoffs.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(cutoffs[0]))
            writer.writeheader()
            writer.writerows(cutoffs)
    render_report(
        results,
        output / "report.pdf",
        selection,
        [action_report] if action_report is not None else [],
    )
    return report


def main():
    """Prepare cases, evaluate a matrix, or redraw a saved report through the CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="derive shared forecast or known-arrival cases")
    prepare.add_argument("--forecast-dir", type=Path, required=True)
    prepare.add_argument("--observer-dir", type=Path, required=True)
    prepare.add_argument("--worker-config", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--horizon-seconds", type=int, default=60)
    prepare.add_argument("--scenarios", type=int, default=10)
    prepare.add_argument(
        "--arrival-source", choices=("forecast", "known-arrival"), default="forecast"
    )
    evaluate = commands.add_parser(
        "evaluate", help="evaluate and optionally lock validation parameters"
    )
    evaluate.add_argument("--index-file", type=Path, required=True)
    evaluate.add_argument("--batch-dir", type=Path, required=True)
    evaluate.add_argument("--output-dir", type=Path, required=True)
    evaluate.add_argument("--select", action="store_true")
    evaluate.add_argument("--selection-file", type=Path)
    report = commands.add_parser(
        "report", help="combine frozen metrics and optional illustrative actions"
    )
    report.add_argument("--metrics", type=Path, action="append", required=True)
    report.add_argument("--output-dir", type=Path, required=True)
    report.add_argument("--selection-file", type=Path)
    report.add_argument("--action-batch-dir", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_validation_suite(
            args.forecast_dir,
            args.observer_dir,
            json.loads(args.worker_config.read_text()),
            args.output_dir,
            horizon_seconds=args.horizon_seconds,
            scenarios=args.scenarios,
            arrival_source=args.arrival_source,
        )
        return
    selection = json.loads(args.selection_file.read_text()) if args.selection_file else None
    if args.command == "evaluate":
        if args.select and selection is not None:
            parser.error("select on validation OR supply an already locked selection")
        if (
            json.loads(args.index_file.read_text(encoding="utf-8"))["split"] == "held-out"
            and selection is None
        ):
            parser.error("held-out evaluation requires an already locked --selection-file")
        result = evaluate_matrix(args.index_file, args.batch_dir)
        if args.select:
            selection = select_configuration(result)
        write_validation_report([result], args.output_dir, selection)
        if selection is not None:
            write_json(args.output_dir / "selection.json", selection)
    else:
        results = [
            result for path in args.metrics for result in json.loads(path.read_text())["results"]
        ]
        actions = evaluate_batches([args.action_batch_dir], 120) if args.action_batch_dir else None
        write_validation_report(results, args.output_dir, selection, actions)


if __name__ == "__main__":
    main()
