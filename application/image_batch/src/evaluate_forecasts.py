"""Score saved forecasts against subsequent covered Job arrivals."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from scipy.stats import poisson

from forecast_trace import (
    bounded_read,
    milliseconds,
    observed_milliseconds,
    read_trace,
    training_bins,
    write_json,
)
from forecast_workload import Settings


def evaluation_trace(rows, run_id, window_end):
    """Use all frozen evidence, but generate bins only inside the arrival window.

    A later observation can reveal an earlier arrival or bracket the final bin.
    This retrospective reader is separate from causal forecast/template reads.
    """
    return replace(read_trace(rows, run_id, float("inf")), cutoff=window_end)


def evaluate(observer_dir, forecast_dir, gap_thresholds=(1.5, 3.0, 5.0), until=None):
    paths = sorted(Path(forecast_dir).glob("*/forecast.json"))
    if (Path(forecast_dir) / "forecast.json").exists():
        paths = [Path(forecast_dir) / "forecast.json"]
    forecasts = [json.loads(path.read_text()) for path in paths]
    if not forecasts:
        raise ValueError("no forecast.json files found")
    settings = Settings(**forecasts[0]["settings"])
    if any(row["settings"] != forecasts[0]["settings"] for row in forecasts):
        raise ValueError("evaluation requires identical forecast settings")
    rows, boundaries = bounded_read(observer_dir)
    if not rows["cluster-state.jsonl"]:
        raise ValueError("no subsequent state observations")
    cutoff = max(observed_milliseconds(row["timestamp"]) for row in rows["cluster-state.jsonl"])
    if until is not None:
        cutoff = min(cutoff, milliseconds(until))
    trace = evaluation_trace(rows, settings.run_id, cutoff)
    scores = []
    skipped = 0
    for forecast in forecasts:
        if forecast["status"] != "ready":
            continue
        origin = milliseconds(forecast["cutoff"])
        bins = training_bins(
            trace,
            origin,
            settings.bin_seconds * 1000,
            round(settings.max_gap_seconds * 1000),
        )
        lookup = {b["start_ms"]: b for b in bins if b["eligible"]}
        for prediction in forecast["predictions"]:
            observed = lookup.get(prediction["start_ms"])
            if observed is None:
                skipped += 1
                continue
            row = {
                "forecast_cutoff": forecast["cutoff"],
                "bin_start_ms": prediction["start_ms"],
                "observed_count": observed["count"],
            }
            for model, field in (
                ("cyclic", "mean_count"),
                ("constant", "reference_mean_count"),
            ):
                mean = prediction[field]
                low, high = poisson.interval(0.9, mean)
                row[model] = {
                    "mean_count": mean,
                    "absolute_error": abs(observed["count"] - mean),
                    "covered_90": bool(low <= observed["count"] <= high),
                }
            scores.append(row)
    aggregate = {}
    for model in ("cyclic", "constant"):
        aggregate[model] = {
            "mean_absolute_count_error": float(
                np.mean([s[model]["absolute_error"] for s in scores])
            )
            if scores
            else None,
            "predictive_coverage_90": float(np.mean([s[model]["covered_90"] for s in scores]))
            if scores
            else None,
        }
    sensitivity = []
    for gap in gap_thresholds:
        if gap <= 0 or not np.isfinite(gap):
            raise ValueError("gap thresholds must be finite and positive")
        bins = training_bins(
            trace, settings.origin_ms, settings.bin_seconds * 1000, round(gap * 1000)
        )
        sensitivity.append(
            {
                "max_gap_seconds": gap,
                "eligible_bins": sum(b["eligible"] for b in bins),
                "excluded_bins": sum(not b["eligible"] for b in bins),
            }
        )
    cycles = []
    period_ms = settings.period_seconds * 1000
    for cycle in range(max(0, (cutoff - settings.origin_ms) // period_ms)):
        start = settings.origin_ms + cycle * period_ms
        captured = [(t, s) for t, s in trace.states if start <= t < start + period_ms]
        tail = [(t, s) for t, s in captured if t >= start + period_ms * 0.75]
        cycles.append(
            {
                "cycle": cycle + 1,
                "peak_queued": max((s["counts"]["queued_jobs"] for _, s in captured), default=None),
                "low_tail_min_queued": min(
                    (s["counts"]["queued_jobs"] for _, s in tail), default=None
                ),
                "low_tail_zero_snapshots": sum(s["counts"]["queued_jobs"] == 0 for _, s in tail),
                "all_three_workers_available": bool(captured)
                and all(
                    sum(w["ready"] and w["schedulable"] for w in s["workers"]) == 3
                    for _, s in captured
                ),
            }
        )
    return {
        "settings": forecasts[0]["settings"],
        "evaluation_cutoff_ms": cutoff,
        "inputs": boundaries,
        "forecast_count": len(forecasts),
        "ready_count": sum(f["status"] == "ready" for f in forecasts),
        "scored_bins": len(scores),
        "uncovered_or_future_bins": skipped,
        "aggregate": aggregate,
        "gap_sensitivity": sensitivity,
        "cycles": cycles,
        "scores": scores,
        "interpretation": (
            "90% central Poisson predictive intervals conditional on each fitted mean; "
            "overlapping horizons are not independent repetitions"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-dir", type=Path, required=True)
    parser.add_argument("--forecast-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--until", help="UTC end of the arrival experiment; exclude shutdown/drain time"
    )
    parser.add_argument("--gap-thresholds", nargs="+", type=float, default=[1.5, 3.0, 5.0])
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    result = evaluate(args.observer_dir, args.forecast_dir, args.gap_thresholds, args.until)
    write_json(args.output, result)
    print(
        json.dumps(
            {key: result[key] for key in ("scored_bins", "aggregate", "gap_sensitivity", "cycles")}
        )
    )


if __name__ == "__main__":
    main()
