"""Arrival illustrations and equal-run accuracy without repeating seed-specific pages."""
import matplotlib.pyplot as plt
import numpy as np

from forecast_report import MODELS, rebin_predictions
from forecast_trace import milliseconds
from opendc_report_layout import page, panel, finish


def render_arrivals(pdf, example, summaries, roles, supplement):
    """Illustrate one held-out workload, then summarize the original evaluation cutoffs.

    Args:
        pdf (PdfPages): Open report writer.
        example (dict): Saved arrival report for the held-out run.
        summaries (list[dict]): Equal-run summaries separated by study split.
        roles (dict): Explicit workload identities and roles.
        supplement (dict): Additional causal forecasts for illustration only.

    Raises:
        ValueError: Supplementary forecasts belong to a different run or settings.
    """
    settings = example["evaluation"]["settings"]
    origin, width = settings["origin_ms"], example["rate_bin_seconds"]
    run = settings["run_id"]
    seed = roles[run]["workload_seed"]
    supplement = supplement.get("arrival_illustration", {})
    extra = supplement.get("forecasts", [])
    if extra and (supplement["run_id"] != run or any(f["settings"] != settings for f in extra)):
        raise ValueError("supplementary forecast settings do not match held-out run")
    forecasts = sorted(example["forecasts"] + extra, key=lambda f: milliseconds(f["cutoff"]))
    end = supplement.get("schedule_seconds", 6 * settings["period_seconds"])
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
        f"Held-out seed {seed}: each forecast is issued before its arrivals; "
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
    first = (milliseconds(forecasts[0]["cutoff"]) - origin) / 1000
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
        "Seconds from schedule start",
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
        max(v for v in series[key] if v is not None)
        for series in example["cumulative_examples"].values()
        for key in ("observed_count", "cyclic", "constant")
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
            xticks=[0, 20, 40, 60],
        )
        axis.grid(alpha=0.18)
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
    finish(
        pdf,
        figure,
        "Bottom: first, middle and last fully covered original study forecasts; "
        "the vertical difference is count error.\n"
        f"Top adds {len(extra)} offline causal illustrations, without changing study scores. "
        "The axis ends with scheduled arrivals, not the observer tail.",
    )
    _accuracy_page(pdf, summaries)


def _accuracy_page(pdf, summaries):
    """Show all workload seeds compactly, with selection and held-out means separated.

    Args:
        pdf (PdfPages): Open report writer.
        summaries (list[dict]): Per-run values and equal-run aggregated count errors.
    """
    figure, axes = page(
        "Forecast accuracy | count errors across independent workloads",
        "Periodic forecasting helps on some runs; compare it against "
        "the constant-rate baseline, including the held-out run.",
        rows=1,
    )
    figure.subplots_adjust(top=0.79, bottom=0.56)
    for axis, split, label in zip(
        axes[0], ("validation", "held-out"), ("Selection runs", "Held-out run")
    ):
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
        seeds = "/".join(str(r["workload_seed"]) for r in row["per_run"])
        cells.append(
            [
                f"{'Held out' if row['split'] == 'held-out' else 'Selection'} {seeds}",
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
            "Workload seeds",
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
    last = [r for r in summaries if r["horizon_seconds"] == 60]
    exceptions = [
        str(run["workload_seed"])
        for row in last
        for run in row["per_run"]
        if run["cyclic"] is not None and run["cyclic"] > run["constant"]
    ]
    figure.text(
        0.08,
        0.125,
        "At 60 s, constant rate beats periodic on workload seed(s): "
        + (", ".join(exceptions) or "none")
        + ".",
        fontsize=10,
    )
    finish(
        pdf,
        figure,
        "Lines: means of scored runs; crosses/ranges: individual runs, not confidence intervals. "
        "Issues within a run are dependent.\n"
        "These scores use only the original study cutoffs. This campaign uses H60; "
        "H120 was tested in the earlier campaign, not this selection.",
    )


def _number(value):
    """Format unavailable errors distinctly from zero.

    Args:
        value (float or None): Measured mean or unavailable value.

    Returns:
        str: Two decimal places or an explicit missing-value dash.
    """
    return "—" if value is None else f"{value:.2f}"
