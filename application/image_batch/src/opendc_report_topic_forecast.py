"""Arrival illustrations and equal-run accuracy without repeating seed-specific pages."""
import matplotlib.pyplot as plt
import numpy as np

from forecast_report import MODELS, rebin_predictions
from forecast_trace import milliseconds
from opendc_report_layout import page, panel, finish


def render_arrivals(pdf, example, summaries, roles, supplement):
    """Illustrate a captured workload, then summarize its original evaluation cutoffs.

    Args:
        pdf (PdfPages): Open report writer.
        example (dict): Saved arrival report with a captured evaluation end.
        summaries (list[dict]): Equal-run summaries separated by study split.
        roles (dict): Explicit identities; standalone runs can have no seed or study split.
        supplement (dict): Additional causal forecasts for illustration only.

    Raises:
        ValueError: Supplementary forecasts belong to a different run or settings.
    """
    settings = example["evaluation"]["settings"]
    origin, width = settings["origin_ms"], example["rate_bin_seconds"]
    run = settings["run_id"]
    role = roles[run]
    seed = role["workload_seed"]
    study = {row["split"] for row in summaries} == {"validation", "held-out"}
    identity = (
        f"Held-out seed {seed}"
        if role["split"] == "held-out" and seed is not None
        else f"Run {run}"
        if seed is None
        else f"Workload seed {seed}"
    )
    supplement = supplement.get("arrival_illustration", {})
    extra = supplement.get("forecasts", [])
    if extra and (supplement["run_id"] != run or any(f["settings"] != settings for f in extra)):
        raise ValueError("supplementary forecast settings do not match example run")
    forecasts = sorted(example["forecasts"] + extra, key=lambda f: milliseconds(f["cutoff"]))
    end = supplement.get("schedule_seconds")
    if end is None:
        end = (example["evaluation"]["evaluation_cutoff_ms"] - origin) / 1000
    figure = plt.figure(figsize=(11.69, 8.27))
    grid = figure.add_gridspec(
        2, 3, left=0.08, right=0.97, top=0.78, bottom=0.24, hspace=0.95, wspace=0.35
    )
    figure.suptitle(
        "Arrival forecasts | anticipating the next workload burst", fontsize=17, y=0.965
    )
    figure.text(
        0.08,
        0.905,
        f"{identity}: each forecast is issued before its arrivals; "
        "periodic predictions follow the changing workload rate.",
        fontsize=10,
    )
    axis = figure.add_subplot(grid[0, :])
    actual = example["rate_bins"]
    axis.plot(
        [(b["start_ms"] - origin) / 1000 + width / 2 for b in actual],
        [b["count"] / width if b["eligible"] else np.nan for b in actual],
        color="0.25",
        linewidth=1.3,
        label="Observed rate",
    )
    for index, forecast in enumerate(forecasts):
        predictions = rebin_predictions(
            forecast["predictions"], settings["bin_seconds"], [b["start_ms"] for b in actual], width
        )
        color = plt.get_cmap("viridis")(0.15 + 0.70 * (index % 4) / 3)
        axis.plot(
            [(p["start_ms"] - origin) / 1000 + width / 2 for p in predictions],
            [p["rate"] for p in predictions],
            color=color,
            linestyle="--",
            linewidth=1.8,
            label="Periodic forecast (separate issues)" if index == 0 else None,
        )
        issue = (milliseconds(forecast["cutoff"]) - origin) / 1000
        axis.plot(issue, 0, marker="^", color=color, markersize=5, clip_on=False)
    axis.set_xlim(0, end)
    axis.set_ylim(bottom=0)
    axis.set_xticks(np.arange(0, end + 1, settings["period_seconds"]))
    first = (milliseconds(forecasts[0]["cutoff"]) - origin) / 1000 if forecasts else 0
    axis.axvspan(0, first, color="0.94", zorder=-1)
    axis.text(
        first / 2,
        0.90,
        "Initial history",
        ha="center",
        fontsize=9,
        transform=axis.get_xaxis_transform(),
    )
    panel(
        axis,
        f"{len(forecasts)} forecast issues; triangles mark issue times | common {width}-s bins",
        "Seconds from schedule start" if study else "Seconds from forecast origin",
        "Arrivals per second",
    )
    axis.grid(alpha=0.18)
    handles, labels = axis.get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="center",
        bbox_to_anchor=(0.55, 0.845),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    examples = example["example_cutoffs"]
    maximum = max(
        (
            v
            for series in example["cumulative_examples"].values()
            for key in ("observed_count", "cyclic", "constant")
            for v in series[key]
            if v is not None
        ),
        default=0,
    )
    for index, cutoff in enumerate(examples):
        series = example["cumulative_examples"][cutoff]
        axis = figure.add_subplot(grid[1, index])
        axis.plot(
            series["seconds_ahead"],
            series["observed_count"],
            "o-",
            color="0.15",
            markersize=3,
            label="Observed",
        )
        for model, label, color in MODELS:
            axis.plot(
                series["seconds_ahead"],
                series[model],
                color=color,
                linestyle="--" if model == "cyclic" else ":",
                label=label,
            )
        actual_total = series["observed_count"][-1]
        conclusion = (
            "Outcome incomplete"
            if actual_total is None
            else f"At {settings['horizon_seconds']} s: observed {actual_total:.0f}, "
            f"periodic {series['cyclic'][-1]:.1f}"
        )
        issue = (milliseconds(cutoff) - origin) / 1000
        panel(
            axis,
            f"{conclusion}\nIssued at t = {issue:.1f} s",
            "Seconds after forecast",
            "Cumulative arrivals (Jobs)",
        )
        axis.set(
            xlim=(0, settings["horizon_seconds"]),
            ylim=(0, max(1, maximum * 1.08)),
            xticks=np.linspace(0, settings["horizon_seconds"], 4),
        )
        axis.grid(alpha=0.18)
    if examples:
        handles, labels = axis.get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="center",
            bbox_to_anchor=(0.53, 0.15),
            ncol=3,
            frameon=False,
            fontsize=9,
        )
    else:
        figure.text(
            0.08, 0.35, "No eligible cumulative forecast examples are available.", fontsize=11
        )
    if study:
        note = (
            "Bottom: first, middle and last fully covered original study forecasts; "
            "the vertical difference is count error.\n"
            f"Top adds {len(extra)} offline causal illustrations, without changing study scores. "
            "The axis ends with scheduled arrivals, not the observer tail."
        )
    else:
        note = (
            "Bottom: original forecast examples; the vertical difference is count error. "
            "Missing coverage leaves observed totals unavailable.\n"
            "Scores use the original forecast issues. "
            "The top axis ends at the captured evaluation end."
        )
    finish(pdf, figure, note)
    _accuracy_page(pdf, summaries)


def _accuracy_page(pdf, summaries):
    """Show equal-run errors with only the explicitly assigned workload roles.

    Args:
        pdf (PdfPages): Open report writer.
        summaries (list[dict]): Per-run values and equal-run aggregated count errors.
    """
    splits = sorted({row["split"] for row in summaries})
    study = set(splits) == {"validation", "held-out"}
    groups = (
        [("validation", "Selection runs"), ("held-out", "Held-out run")]
        if study
        else [
            (
                split,
                {"validation": "Selection runs", "held-out": "Held-out run"}.get(
                    split, "Captured runs" if split == "unassigned" else split
                ),
            )
            for split in splits
        ]
    )
    figure, axes = page(
        "Forecast accuracy | count errors across independent workloads"
        if study
        else "Forecast accuracy | count errors across captured runs",
        "Periodic forecasting helps on some runs; compare it against "
        "the constant-rate baseline, including the held-out run."
        if study
        else "Compare periodic forecasting against the constant-rate baseline "
        "on captured arrivals.",
        rows=1,
        columns=max(1, len(groups)),
    )
    figure.subplots_adjust(top=0.79, bottom=0.56)
    for axis, (split, label) in zip(axes[0], groups):
        rows = sorted(
            (r for r in summaries if r["split"] == split), key=lambda r: r["horizon_seconds"]
        )
        for model, name, color in MODELS:
            means = [
                row[model + "_mean"] if row[model + "_mean"] is not None else np.nan for row in rows
            ]
            axis.plot([r["horizon_seconds"] for r in rows], means, "o-", color=color, label=name)
            for row in rows:
                if row[model + "_range"] is None:
                    continue
                low, high = row[model + "_range"]
                axis.vlines(row["horizon_seconds"], low, high, color=color, linewidth=2)
                for i, run in enumerate(row["per_run"]):
                    if run[model] is None:
                        continue
                    axis.plot(
                        row["horizon_seconds"] + (i - (len(row["per_run"]) - 1) / 2) * 1.5,
                        run[model],
                        marker="x",
                        color=color,
                    )
        final = rows[-1] if rows else None
        conclusion = "No eligible forecasts"
        if final and final["cyclic_mean"] is not None:
            conclusion = (
                "Periodic has lower mean error"
                if final["cyclic_mean"] < final["constant_mean"]
                else "Constant rate has lower mean error"
            ) + f" at {final['horizon_seconds']} s"
        panel(
            axis,
            f"{label}: {conclusion.lower()}",
            "Forecast horizon (s)",
            "Arrival-count MAE (Jobs)",
        )
        axis.set(xticks=[r["horizon_seconds"] for r in rows], ylim=(0, None))
    maximum = max(axis.get_ylim()[1] for axis in axes[0])
    for axis in axes[0]:
        axis.set_ylim(0, maximum)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="center",
        bbox_to_anchor=(0.53, 0.845),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    table_axis = figure.add_axes((0.08, 0.19, 0.89, 0.25))
    table_axis.axis("off")
    cells = []
    for row in sorted(summaries, key=lambda r: (r["split"] == "held-out", r["horizon_seconds"])):
        seeds = "/".join(_run_identity(run) for run in row["per_run"])
        label = {"held-out": "Held out", "validation": "Selection"}.get(row["split"], "Run")
        cells.append(
            [
                f"{label} {seeds}",
                str(row["horizon_seconds"]),
                str(row["eligible_forecasts"]),
                str(row["excluded_forecasts"]),
                _number(row["mean_observed_count"]),
                _number(row["cyclic_mean"]),
                _number(row["constant_mean"]),
            ]
        )
    table = table_axis.table(
        cellText=cells,
        colLabels=[
            "Workload seeds" if study else "Workloads",
            "Horizon\n(s)",
            "Eligible\nissues",
            "Excluded\nissues",
            "Actual\nJobs (mean)",
            "Periodic\nMAE (Jobs)",
            "Constant\nMAE (Jobs)",
        ],
        cellLoc="center",
        colWidths=[0.24, 0.11, 0.12, 0.12, 0.13, 0.14, 0.14],
        bbox=[0, 0, 1, 1],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("0.85")
        if row == 0:
            cell.set_facecolor("#eef2f6")
    horizon = 60 if study else max((row["horizon_seconds"] for row in summaries), default=0)
    last = [r for r in summaries if r["horizon_seconds"] == horizon]
    exceptions = [
        _run_identity(run)
        for row in last
        for run in row["per_run"]
        if run["cyclic"] is not None and run["cyclic"] > run["constant"]
    ]
    figure.text(
        0.08,
        0.125,
        (
            f"At {horizon} s, constant rate beats periodic on workload seed(s): "
            if study
            else f"At {horizon} s, constant rate beats periodic on run(s): "
        )
        + (", ".join(exceptions) or "none")
        + ".",
        fontsize=10,
    )
    finish(
        pdf,
        figure,
        "Lines: means of scored runs; crosses/ranges: individual runs, not confidence intervals. "
        "Issues within a run are dependent.\n"
        + (
            "These scores use only the original study cutoffs. This campaign uses H60; "
            "H120 was tested in the earlier campaign, not this selection."
            if study
            else "Scores use original captured forecast issues and fully covered future intervals."
        ),
    )


def _run_identity(run):
    """Identify a workload without inventing a seed for a standalone capture.

    Args:
        run (dict): Per-run summary with a run ID and optional workload seed.

    Returns:
        str: Assigned seed, or the actual run ID when a seed is unavailable.
    """
    return str(run["workload_seed"]) if run["workload_seed"] is not None else run["run_id"]


def _number(value):
    """Format unavailable errors distinctly from zero.

    Args:
        value (float or None): Measured mean or unavailable value.

    Returns:
        str: Two decimal places or an explicit missing-value dash.
    """
    return "—" if value is None else f"{value:.2f}"
