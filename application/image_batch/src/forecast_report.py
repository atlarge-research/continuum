"""Optional postmortem pages for saved forecasts; baseline figures stay separate."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator

from evaluate_forecasts import evaluate
from forecast_trace import (
    bounded_read,
    milliseconds,
    read_trace,
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
                "mean_absolute_count_error": sum(
                    s[model]["absolute_error"] for s in scores
                )
                / len(scores),
                "predictive_coverage_90": sum(s[model]["covered_90"] for s in scores)
                / len(scores),
            }
        result.append(row)
    return result


def cumulative_counts(forecast, scores, bin_seconds):
    """A missing bin invalidates every later cumulative observed total."""
    lookup = {
        s["bin_start_ms"]: s
        for s in scores
        if s["forecast_cutoff"] == forecast["cutoff"]
    }
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
                "mean_absolute_count_error": sum(
                    g[model]["absolute_error"] for g in group
                )
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
                    min(start + target_ms, p["start_ms"] + source_ms)
                    - max(start, p["start_ms"]),
                ),
                p,
            )
            for p in predictions
        ]
        if sum(length for length, _ in overlaps) != target_ms:
            continue
        count = sum(length / source_ms * p["mean_count"] for length, p in overlaps)
        result.append(
            {"start_ms": start, "mean_count": count, "rate": count / target_seconds}
        )
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
    trace = read_trace(rows, settings["run_id"], evaluation["evaluation_cutoff_ms"])
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
    complete = [
        f for f in ready if cumulative[f["cutoff"]]["observed_count"][-1] is not None
    ]
    candidates = complete or ready
    examples = [
        candidates[i]["cutoff"]
        for i in sorted({0, len(candidates) // 2, len(candidates) - 1})
    ]
    horizons, totals = horizon_summary(
        ready, evaluation["scores"], settings["bin_seconds"]
    )
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
                    Path(__file__).with_name(name).read_bytes()
                ).hexdigest()
                for name in (
                    "forecast_report.py",
                    "evaluate_forecasts.py",
                    "forecast_trace.py",
                )
            },
        },
    }


def render_forecasts(report, output, save):
    evaluation = report["evaluation"]
    settings = evaluation["settings"]
    forecasts = report["forecasts"]
    origin = settings["origin_ms"]
    width = settings["bin_seconds"]
    rate_width = report["rate_bin_seconds"]
    end = (evaluation["evaluation_cutoff_ms"] - origin) / 1000
    first = (milliseconds(forecasts[0]["cutoff"]) - origin) / 1000

    def relative(ms):
        return (ms - origin) / 1000

    def save_page(fig, name, title):
        save(fig, output, name, title, layout=False)

    fig = plt.figure(figsize=(11.7, 8.3))
    grid = fig.add_gridspec(
        2,
        3,
        height_ratios=[1.15, 1],
        left=0.075,
        right=0.97,
        top=0.85,
        bottom=0.22,
        hspace=0.62,
        wspace=0.3,
    )
    ax = fig.add_subplot(grid[0, :])
    ax.axvspan(0, first, color="#eeeeee", zorder=0)
    actual = report["rate_bins"]
    x = [relative(b["start_ms"]) + rate_width / 2 for b in actual]
    ax.plot(
        x,
        [b["count"] / rate_width if b["eligible"] else np.nan for b in actual],
        color="0.2",
        linewidth=1.6,
        marker="o",
        markersize=2.5,
        label="Observed rate",
    )
    # Both series average over identical clock-aligned windows. Each dashed
    # segment remains a single saved forecast; never splice a synthetic run.
    shown = []
    for forecast in forecasts:
        if (
            not shown
            or milliseconds(forecast["cutoff"]) - milliseconds(shown[-1]["cutoff"])
            >= 30000
        ):
            shown.append(forecast)
    for index, forecast in enumerate(shown):
        predictions = report["rebinned_predictions"][forecast["cutoff"]]
        if not predictions:
            continue
        color = plt.get_cmap("viridis")(0.85 * index / max(1, len(shown) - 1))
        ax.plot(
            [relative(p["start_ms"]) + rate_width / 2 for p in predictions],
            [p["rate"] for p in predictions],
            linestyle="--",
            color=color,
            linewidth=1.7,
            marker=".",
            markersize=4,
            label="Saved periodic forecasts (selected)" if index == 0 else None,
        )
    ax.set(
        xlim=(0, end),
        ylim=(0, None),
        ylabel="Average arrival rate (Jobs/s)",
        xlabel="Seconds since arrival-run start",
        title=f"Observed and predicted rates, both averaged over the same {rate_width}-second bins",
    )
    ax.text(
        first / 2,
        0.96,
        "History collection",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="top",
        fontsize=9,
    )
    ax.legend(loc="upper right", fontsize=8)

    examples = report["example_cutoffs"]
    maximum = max(
        max(value for value in series[key] if value is not None)
        for series in report["cumulative_examples"].values()
        for key in ("observed_count", "cyclic", "constant")
    )
    for index, cutoff in enumerate(examples):
        series = report["cumulative_examples"][cutoff]
        ax = fig.add_subplot(grid[1, index])
        x = series["seconds_ahead"]
        ax.plot(
            x,
            [v if v is not None else np.nan for v in series["observed_count"]],
            "o-",
            color="0.15",
            markersize=3,
            linewidth=1.6,
            label="Observed total",
        )
        for model, label, color in MODELS:
            ax.plot(
                x,
                series[model],
                linestyle="--" if model == "cyclic" else ":",
                color=color,
                linewidth=1.7,
                label=label,
            )
        ax.set(
            xlim=(0, settings["horizon_seconds"]),
            ylim=(0, max(1, maximum * 1.08)),
            xlabel="Seconds after forecast",
            ylabel="Cumulative arrivals (Jobs)" if index == 0 else "",
            title=f"Forecast issued at t = {relative(milliseconds(cutoff)):.1f} s",
        )
        ax.set_xticks(range(0, settings["horizon_seconds"] + 1, 20))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        if index == 0:
            handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.12),
        ncol=3,
        frameon=False,
        fontsize=10,
    )
    fig.text(
        0.075,
        0.905,
        f"Separate {forecasts[0]['cutoff'][:10]} run | {settings['run_id']} | {len(forecasts)} ready forecasts",
        fontsize=9,
    )
    example_note = (
        "Examples: first, middle and last fully observed horizons (selected by coverage)."
        if report["examples_have_full_coverage"]
        else "First, middle and last issued forecasts; observed totals stop at the first missing interval."
    )
    fig.text(
        0.075,
        0.035,
        f"Top: each point is a {rate_width}-second count divided by {rate_width}, plotted at the bin centre; lines join points. Gaps mean missing coverage.\n"
        "Bottom: each curve starts at zero. At 20 s, read the total arrivals in the next 20 seconds; the vertical difference is count error.\n"
        f"{example_note} Points show totals every {width} s; lines join them.",
        fontsize=9,
        linespacing=1.5,
    )
    save_page(
        fig,
        "forecast-arrivals",
        "Arrival forecasting | comparing the trend and the arriving workload",
    )

    fig, ax = plt.subplots(figsize=(11.7, 8.3))
    fig.subplots_adjust(left=0.075, right=0.97, top=0.86, bottom=0.08)
    ax.axis("off")
    intervals = [str(row["horizon_seconds"]) for row in report["horizon_summary"]]
    horizon_label = (
        ", ".join(intervals[:-1]) + " and " + intervals[-1]
        if len(intervals) > 1
        else intervals[0]
    )
    rows = []
    for row in report["horizon_summary"]:

        def formatted(value):
            return "—" if value is None else f"{value:.2f}"

        rows.append(
            [
                f"Next {row['horizon_seconds']} seconds",
                str(row["eligible_forecasts"]),
                formatted(row["mean_observed_count"]),
                formatted(row["cyclic"]["mean_absolute_count_error"]),
                formatted(row["constant"]["mean_absolute_count_error"]),
            ]
        )
    table = ax.table(
        cellText=rows,
        colLabels=[
            "Future interval\nfrom forecast issue",
            "Fully observed\nforecasts",
            "Mean actual\nJobs arriving",
            "Periodic Poisson\nMAE (Jobs)",
            "Constant rate\nMAE (Jobs)",
        ],
        cellLoc="center",
        bbox=[0, 0.58, 1, 0.36],
        colWidths=[0.22, 0.18, 0.2, 0.2, 0.2],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    for (row_index, _), cell in table.get_celld().items():
        cell.set_edgecolor("0.8")
        if row_index == 0:
            cell.set_facecolor("#eef2f6")
            cell.set_text_props(weight="bold")
    explanations = [
        (
            0.51,
            "What is being predicted?",
            "The total number of Jobs arriving between forecast issue and the end of each listed future interval.\nThe observed and predicted totals cover exactly the same interval; lower error is better.",
        ),
        (
            0.35,
            "What does the error mean?",
            "MAE means mean absolute error: take the size of each predicted-versus-actual count difference, then average.\nAn MAE of 1.9 Jobs means the forecast total was off by about 1.9 Jobs on average. Zero is perfect; there is no fixed maximum.\nThis is a count, not a percentage. Random arrivals still produce errors even when their expected rate is known.",
        ),
        (
            0.14,
            "How to read this comparison",
            "Both models use the same historical observations and are scored on the same forecasts within each row.\nOnly fully observed future intervals count. Longer intervals can have fewer eligible forecasts.\nThe horizons overlap and reuse arrivals: this is descriptive evidence from one run, not independent repetitions.",
        ),
    ]
    for y, title, text in explanations:
        ax.text(
            0,
            y,
            title,
            fontsize=12,
            fontweight="bold",
            va="top",
            transform=ax.transAxes,
        )
        ax.text(
            0,
            y - 0.05,
            text,
            fontsize=10,
            va="top",
            linespacing=1.65,
            transform=ax.transAxes,
        )
    excluded = "; ".join(
        f"next {r['horizon_seconds']} s: {r['excluded_forecasts']}"
        for r in report["horizon_summary"]
    )
    fig.text(
        0.075,
        0.9,
        "How accurately did each forecast predict the amount of arriving work?",
        fontsize=12,
    )
    fig.text(
        0.075,
        0.025,
        f"Excluded forecasts for missing coverage or experiment end — {excluded}.\n"
        f"Observation-gap limit: {settings['max_gap_seconds']:g} s. Original {width}-second scores and interval-coverage diagnostics remain in the JSON/CSV files.",
        fontsize=9,
    )
    save_page(
        fig,
        "forecast-accuracy",
        f"Arrival forecasting | error in the next {horizon_label} seconds",
    )

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
                            score["bin_start_ms"]
                            - milliseconds(score["forecast_cutoff"])
                        )
                        / 1000
                        + width,
                        "observed_count": score["observed_count"],
                        "model": model,
                        **score[model],
                    }
                )
