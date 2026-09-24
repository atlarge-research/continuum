"""Select forecast configuration across matched independent validation workload seeds."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from opendc_report_validation import comparison_rows


def select_across_runs(results, seed=20261008):
    """Apply the existing completion-error rule with equal workload-run weighting.

    Within each run, every candidate uses the same observable cutoffs. The mean
    of run means gives independent workload seeds equal weight; overlapping
    cutoffs and nested sampled futures are never counted as new repetitions.
    Shared native process cost is unavailable per configuration unless separately
    measured. Missing cost therefore cannot be replaced by proportional allocation.

    Args:
        results (list[dict]): Validation results with distinct run IDs and workload_seed values.
        seed (int): One scenario seed, distinct from each run's workload-generation seed.

    Returns:
        dict: Timestamped selection, equal-weight candidate metrics and per-run denominators.

    Raises:
        ValueError: Runs are not independent validation inputs or candidate sets differ.
    """
    if len(results) < 2 or any(result["split"] != "validation" for result in results):
        raise ValueError("selection requires at least two validation runs")
    run_ids = [result["run_id"] for result in results]
    workload_seeds = [result.get("workload_seed") for result in results]
    if (
        len(set(run_ids)) != len(run_ids)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in workload_seeds)
        or len(set(workload_seeds)) != len(workload_seeds)
    ):
        raise ValueError("selection requires distinct run identities and explicit workload seeds")
    rows_by_run, cutoffs_by_run, configurations = {}, {}, None
    for result in results:
        rows, cutoffs = comparison_rows(result, seed)
        keyed = {(row["horizon_seconds"], row["scenarios"]): row for row in rows}
        if configurations is not None and set(keyed) != configurations:
            raise ValueError("validation runs must share the same candidate configurations")
        configurations = set(keyed)
        rows_by_run[result["run_id"]] = keyed
        cutoffs_by_run[result["run_id"]] = cutoffs
    candidates = []
    for horizon, count in sorted(configurations):
        per_run = {run: rows[(horizon, count)]["means"] for run, rows in rows_by_run.items()}
        errors = [row["completion_error"] for row in per_run.values()]
        costs = [row["execution_seconds"] for row in per_run.values()]
        candidates.append(
            {
                "horizon_seconds": horizon,
                "scenarios": count,
                "completion_curve_mae": statistics.mean(errors),
                "between_run_completion_mae_range": [min(errors), max(errors)],
                "mean_execution_seconds": statistics.mean(costs)
                if all(c is not None for c in costs)
                else None,
                "per_run": per_run,
            }
        )
    selected = min(
        candidates,
        key=lambda row: (
            round(row["completion_curve_mae"], 6),
            row["mean_execution_seconds"]
            if row["mean_execution_seconds"] is not None
            else float("inf"),
            row["horizon_seconds"],
            row["scenarios"],
        ),
    )
    return {
        "selected": selected,
        "candidates": candidates,
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
        "rule": "validation-only E120 completion-curve MAE, same eligible cutoffs per run, "
        "equal workload-run weights; ties at 1e-6 by available measured cost, then H/N",
        "reference": {"horizon_seconds": 60, "scenarios": 10},
        "scenario_seed": seed,
        "workload_seeds": dict(zip(run_ids, workload_seeds)),
        "run_cutoffs": cutoffs_by_run,
        "interpretation": "between-run ranges are descriptive, not confidence intervals; "
        "sampled futures and overlapping cutoffs are dependent within each run",
    }


def main():
    """Write a new immutable selection file from completed validation metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, action="append", required=True)
    parser.add_argument("--scenario-seed", type=int, default=20261008)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for path in args.metrics:
        saved = json.loads(path.read_text())
        results.extend(saved.get("results", [saved]))
    selection = select_across_runs(results, args.scenario_seed)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(selection, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
