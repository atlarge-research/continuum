"""Numerical arrival forecast summaries and exported evaluation evidence."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from evaluate_forecasts import evaluate, evaluation_trace
from forecast_trace import (
    bounded_read,
    milliseconds,
    training_bins,
    write_json,
)


MODELS = (
    ("cyclic", "Periodic Poisson", "#2166ac"),
    ("constant", "Constant rate", "#c56b25"),
)


def lead_summary(evaluation):
    """Keep each scored forecast/bin pair; never imply independent repetitions."""
    width = evaluation["settings"]["bin_seconds"]
    groups = {}
    for score in evaluation["scores"]:
        delta = score["bin_start_ms"] - milliseconds(score["forecast_cutoff"])
        if delta < 0 or delta % (width * 1000):
            raise ValueError("score is not on its forecast-relative bin grid")
        end = delta // 1000 + width
        groups.setdefault(end, []).append(score)
    result = []
    for end, scores in sorted(groups.items()):
        row = {
            "lead_start_seconds": end - width,
            "lead_end_seconds": end,
            "scored_bins": len(scores),
        }
        for model, _, _ in MODELS:
            row[model] = {
                "mean_absolute_count_error": sum(s[model]["absolute_error"] for s in scores)
                / len(scores),
                "predictive_coverage_90": sum(s[model]["covered_90"] for s in scores) / len(scores),
            }
        result.append(row)
    return result


def cumulative_counts(forecast, scores, bin_seconds):
    """A missing bin invalidates every later cumulative observed total."""
    lookup = {s["bin_start_ms"]: s for s in scores if s["forecast_cutoff"] == forecast["cutoff"]}
    observed = [0]
    cyclic, constant = [0.0], [0.0]
    for prediction in forecast["predictions"]:
        score = lookup.get(prediction["start_ms"])
        observed.append(
            None
            if score is None or observed[-1] is None
            else observed[-1] + score["observed_count"]
        )
        cyclic.append(cyclic[-1] + prediction["mean_count"])
        constant.append(constant[-1] + prediction["reference_mean_count"])
    return {
        "seconds_ahead": [i * bin_seconds for i in range(len(observed))],
        "observed_count": observed,
        "cyclic": cyclic,
        "constant": constant,
    }


def horizon_summary(forecasts, scores, bin_seconds, horizons=(10, 20, 60)):
    """Score total arrivals from issue to horizon, only with complete coverage."""
    summaries, totals = [], []
    maximum = max((len(f["predictions"]) * bin_seconds for f in forecasts), default=0)
    if maximum and not any(h <= maximum and h % bin_seconds == 0 for h in horizons):
        horizons = (maximum,)
    for horizon in horizons:
        if horizon % bin_seconds:
            continue
        index = horizon // bin_seconds
        available = [f for f in forecasts if len(f["predictions"]) >= index]
        if not available:
            continue
        group = []
        for forecast in available:
            cumulative = cumulative_counts(forecast, scores, bin_seconds)
            actual = cumulative["observed_count"][index]
            if actual is None:
                continue
            row = {
                "forecast_cutoff": forecast["cutoff"],
                "horizon_seconds": horizon,
                "observed_count": actual,
            }
            for model, _, _ in MODELS:
                mean = cumulative[model][index]
                row[model] = {"mean_count": mean, "absolute_error": abs(actual - mean)}
            group.append(row)
        totals.extend(group)
        summary = {
            "horizon_seconds": horizon,
            "eligible_forecasts": len(group),
            "excluded_forecasts": len(available) - len(group),
            "mean_observed_count": sum(g["observed_count"] for g in group) / len(group)
            if group
            else None,
        }
        for model, _, _ in MODELS:
            summary[model] = {
                "mean_absolute_count_error": sum(g[model]["absolute_error"] for g in group)
                / len(group)
                if group
                else None
            }
        summaries.append(summary)
    return summaries, totals


def rebin_predictions(predictions, source_seconds, starts, target_seconds):
    """Integrate saved piecewise-constant means into the exact observed windows.

    Skip any target window not wholly inside this forecast. Fractional overlap
    uses the same uniform within-bin arrival assumption as scenario generation.
    """
    result = []
    source_ms, target_ms = source_seconds * 1000, target_seconds * 1000
    for start in starts:
        overlaps = [
            (
                max(
                    0,
                    min(start + target_ms, p["start_ms"] + source_ms) - max(start, p["start_ms"]),
                ),
                p,
            )
            for p in predictions
        ]
        if sum(length for length, _ in overlaps) != target_ms:
            continue
        count = sum(length / source_ms * p["mean_count"] for length, p in overlaps)
        result.append({"start_ms": start, "mean_count": count, "rate": count / target_seconds})
    return result


def prepare_forecasts(forecast_dir, observer_dir, until, rate_bin_seconds=10):
    if rate_bin_seconds <= 0:
        raise ValueError("rate bin seconds must be positive")
    evaluation = evaluate(observer_dir, forecast_dir, until=until)
    if not evaluation["scores"]:
        raise ValueError("no covered subsequent forecast bins to plot")
    paths = sorted(Path(forecast_dir).glob("*/forecast.json"))
    if (Path(forecast_dir) / "forecast.json").exists():
        paths = [Path(forecast_dir) / "forecast.json"]
    forecasts = [json.loads(p.read_text()) for p in paths]
    ready = sorted(
        (f for f in forecasts if f["status"] == "ready"),
        key=lambda f: milliseconds(f["cutoff"]),
    )
    settings = evaluation["settings"]
    # Reuse the evaluator's frozen prefixes even if the live files have grown.
    rows, _ = bounded_read(observer_dir, evaluation["inputs"])
    trace = evaluation_trace(rows, settings["run_id"], evaluation["evaluation_cutoff_ms"])
    actual = training_bins(
        trace,
        settings["origin_ms"],
        settings["bin_seconds"] * 1000,
        round(settings["max_gap_seconds"] * 1000),
    )
    rate_bins = training_bins(
        trace,
        settings["origin_ms"],
        rate_bin_seconds * 1000,
        round(settings["max_gap_seconds"] * 1000),
    )
    cumulative = {
        f["cutoff"]: cumulative_counts(f, evaluation["scores"], settings["bin_seconds"])
        for f in ready
    }
    # Coverage determines eligibility, never forecast error. Do not resume a
    # cumulative observed curve after a missing interval.
    complete = [f for f in ready if cumulative[f["cutoff"]]["observed_count"][-1] is not None]
    candidates = complete or ready
    examples = [
        candidates[i]["cutoff"] for i in sorted({0, len(candidates) // 2, len(candidates) - 1})
    ]
    horizons, totals = horizon_summary(ready, evaluation["scores"], settings["bin_seconds"])
    return {
        "evaluation": evaluation,
        "forecasts": ready,
        "actual_bins": actual,
        "lead_summary": lead_summary(evaluation),
        "example_cutoffs": examples,
        "examples_have_full_coverage": bool(complete),
        "cumulative_examples": {cutoff: cumulative[cutoff] for cutoff in examples},
        "rate_bin_seconds": rate_bin_seconds,
        "rate_bins": rate_bins,
        "rebinned_predictions": {
            f["cutoff"]: rebin_predictions(
                f["predictions"],
                settings["bin_seconds"],
                [b["start_ms"] for b in rate_bins],
                rate_bin_seconds,
            )
            for f in ready
        },
        "horizon_summary": horizons,
        "horizon_scores": totals,
        "provenance": {
            "forecast_inputs": [
                {
                    "path": str(p.resolve()),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in paths
            ],
            "observer_directory": str(Path(observer_dir).resolve()),
            "implementation": {
                name: hashlib.sha256(
                    (Path(__file__).resolve().parent.parent / name).read_bytes()
                ).hexdigest()
                for name in (
                    "reporting/forecast_evidence.py",
                    "evaluate_forecasts.py",
                    "forecast_trace.py",
                )
            },
        },
    }


def export_forecasts(report, output):
    """Write the saved arrival evaluation and its per-model CSV scores.

    Args:
        report (dict): Prepared forecast report containing evaluation and horizon scores.
        output (str or Path): Existing directory for the JSON and CSV evidence.
    """
    output = Path(output)
    evaluation = report["evaluation"]
    width = evaluation["settings"]["bin_seconds"]
    write_json(output / "forecast-evaluation.json", evaluation)
    write_json(output / "forecast-report.json", report)
    write_json(output / "forecast-horizon-scores.json", report["horizon_scores"])
    with (output / "forecast-scores.csv").open("w", newline="") as handle:
        columns = [
            "forecast_cutoff",
            "bin_start_ms",
            "lead_end_seconds",
            "observed_count",
            "model",
            "mean_count",
            "absolute_error",
            "covered_90",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for score in evaluation["scores"]:
            for model, _, _ in MODELS:
                writer.writerow(
                    {
                        "forecast_cutoff": score["forecast_cutoff"],
                        "bin_start_ms": score["bin_start_ms"],
                        "lead_end_seconds": (
                            score["bin_start_ms"] - milliseconds(score["forecast_cutoff"])
                        )
                        / 1000
                        + width,
                        "observed_count": score["observed_count"],
                        "model": model,
                        **score[model],
                    }
                )
