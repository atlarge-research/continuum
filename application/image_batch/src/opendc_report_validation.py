"""Render self-contained forecast comparisons from saved observation-validation metrics."""
import numpy as np

from opendc_evaluate import _finish_axes
from opendc_report_layout import finish, page

COLORS = ("#2864b4", "#218358", "#8855a3", "#c56a16")


def render_configuration_pages(pdf, result, selection=None, seed=None):
    """Append a measured configuration comparison and one chronological example.

    Args:
        pdf (PdfPages): Open report shared with the other evidence sections.
        result (dict): One saved observation-validation run.
        selection (dict or None): Previously selected settings; never fitted by this renderer.
        seed (int or None): Forecast scenario seed, or the smallest available seed.

    Returns:
        dict: Run identity, plotted settings, shared windows and configuration summaries.

    Raises:
        ValueError: A requested scenario seed is absent.
    """
    forecasts = forecast_groups(result, seed)
    if seed is not None and not forecasts:
        raise ValueError(f"No forecast groups for scenario seed {seed}")
    audit = {"run_id": result["run_id"], "split": result["split"], "configurations": []}
    try:
        rows, cutoffs = comparison_rows(result, seed)
    except ValueError as error:
        figure, axes = page("Configuration comparison unavailable", str(error), rows=1, columns=1)
        axes[0, 0].set_axis_off()
        finish(
            pdf,
            figure,
            "Saved evidence is retained in JSON; no common observable windows were found.",
        )
        audit["unavailable_reason"] = str(error)
        return audit
    chosen = selection["selected"] if selection else rows[0]
    detail = next(
        (
            g
            for g in forecasts
            if g["cutoff_index"] == cutoffs[0]
            and (g["horizon_seconds"], g["scenarios"])
            == (chosen["horizon_seconds"], chosen["scenarios"])
        ),
        None,
    )
    used_selection = selection is not None and detail is not None
    if detail is None:
        detail = next(g for g in forecasts if g["cutoff_index"] == cutoffs[0])
    target = next(
        c["comparisons"]["120"]["target_seconds"]
        for c in result["cases"]
        if c["arrival_source"] == "forecast"
        and c["seed"] == detail["seed"]
        and c["cutoff_index"] == cutoffs[0]
    )
    note = (
        f"Saved choice: {detail['horizon_seconds']} seconds / {detail['scenarios']} futures. "
        "The detailed example uses these settings."
        if used_selection
        else "The detailed example uses an available configuration; "
        "no matching saved choice was supplied."
    )
    context = {
        "period_seconds": result["period_seconds"],
        "total_windows": len({g["cutoff_index"] for g in forecasts}),
        "usable_windows": len(cutoffs),
        "target_seconds": target,
        "selection_note": note,
    }
    configuration_page(pdf, rows, context)
    detail_page(pdf, result, detail)
    audit.update(
        configurations=rows,
        cutoff_indices=cutoffs,
        forecast_seed=detail["seed"],
        detail_configuration={
            "horizon_seconds": detail["horizon_seconds"],
            "scenarios": detail["scenarios"],
        },
    )
    return audit


def forecast_groups(result, seed=None):
    """Keep one scenario seed so repeated starting points are never silently mixed.

    Args:
        result (dict): Saved observation-validation result.
        seed (int or None): Requested scenario seed, or the smallest available seed.

    Returns:
        list[dict]: Forecast groups for the requested seed; empty when none are available.
    """
    groups = [g for g in result["groups"] if g["arrival_source"] == "forecast"]
    if seed is None and groups:
        seed = min(g["seed"] for g in groups)
    return [g for g in groups if g["seed"] == seed]


def comparison_rows(result, seed=None):
    """Use identical, observable windows for every configuration and every metric.

    Args:
        result (dict): Saved measurements, including individual forecast scenarios.
        seed (int or None): Scenario seed, or the smallest available seed.

    Returns:
        tuple[list[dict], list[int]]: Per-configuration values and common cutoff indices.

    Raises:
        ValueError: There are no common usable windows.
    """
    forecasts = forecast_groups(result, seed)
    configurations = sorted({(g["horizon_seconds"], g["scenarios"]) for g in forecasts})
    groups = {
        config: {
            group["cutoff_index"]: group
            for group in forecasts
            if (group["horizon_seconds"], group["scenarios"]) == config
            and group["windows"]["120"]["coverage_complete"]
        }
        for config in configurations
    }
    cutoffs = sorted(set.intersection(*(set(group) for group in groups.values()))) if groups else []
    if not cutoffs:
        raise ValueError("No shared usable windows for the supplied configurations")
    rows = []
    for config, by_cutoff in groups.items():
        samples = [by_cutoff[index] for index in cutoffs]
        values = {
            "completion_error": [g["windows"]["120"]["completion_curve_mae"] for g in samples],
            "response_error": [
                g["windows"]["120"]["responses"]["overall"]["median"]["absolute_error"]
                for g in samples
            ],
            "execution_seconds": [g["execution_seconds"] for g in samples],
        }
        rows.append(
            {
                "horizon_seconds": config[0],
                "scenarios": config[1],
                "samples": values,
                "means": {
                    key: float(np.mean(sample)) if all(v is not None for v in sample) else None
                    for key, sample in values.items()
                },
            }
        )
    return rows, cutoffs


def configuration_page(pdf, rows, context):
    """Compare all configurations in one panel per headline metric.

    Args:
        pdf (PdfPages): Open report destination.
        rows (list[dict]): Matched per-window samples and their arithmetic means.
        context (dict): Measured period, window counts, target horizon and detail settings.
    """
    figure, axes = page(
        "Forecast settings | errors and execution cost",
        f"Same {context['usable_windows']} observable windows for every setting; "
        f"{context['total_windows'] - context['usable_windows']} starting points excluded.",
        rows=1,
        columns=3,
    )
    axes = axes[0]
    figure.subplots_adjust(left=0.17, bottom=0.32, wspace=0.40)
    metrics = (
        ("completion_error", "Completion-count error", "Mean absolute error (Jobs)"),
        ("response_error", "Typical response-time error", "Mean absolute error (seconds)"),
        ("execution_seconds", "Simulation cost", "Mean execution time (seconds)"),
    )
    labels = [f"{r['horizon_seconds']} s forecast\n{r['scenarios']} futures" for r in rows]
    for axis, (key, title, xlabel) in zip(axes, metrics):
        maximum = max((v for row in rows for v in row["samples"][key] if v is not None), default=1)
        for index, row in enumerate(rows):
            color = COLORS[index % len(COLORS)]
            samples, mean = row["samples"][key], row["means"][key]
            if mean is None:
                axis.text(0.03, index, "Unavailable", transform=axis.get_yaxis_transform())
                continue
            axis.scatter(
                samples,
                index + np.linspace(-0.13, 0.13, len(samples)),
                s=24,
                color=color,
                alpha=0.32,
                edgecolors="none",
            )
            axis.plot([0, mean], [index, index], color=color, alpha=0.25, linewidth=2)
            axis.scatter([mean], [index], s=85, marker="D", color=color, zorder=3)
            axis.annotate(
                f"{mean:.2f}" if key != "execution_seconds" else f"{mean:.1f}",
                (mean, index),
                xytext=(0, 11),
                textcoords="offset points",
                ha="center",
                fontsize=10,
                fontweight="bold",
                color=color,
            )
        axis.set(
            title=title,
            xlabel=xlabel,
            xlim=(0, max(maximum * 1.17, 1)),
            ylim=(len(rows) - 0.4, -0.6),
        )
        axis.set_yticks(range(len(rows)), labels)
        axis.tick_params(labelleft=axis is axes[0])
        axis.grid(axis="x", alpha=0.2)
        axis.spines[["top", "right"]].set_visible(False)
    finish(
        pdf,
        figure,
        "Diamonds: means; dots: windows. Overlapping windows are dependent. Missing "
        "measurements remain unavailable.\n"
        f"{context['period_seconds']} s workload cycles; existing Jobs + arrivals within "
        f"{context['target_seconds']} s, evaluated for 120 s.\n"
        "Completion error uses 5 s counts; response error uses medians of Jobs "
        "finishing in-window (unfinished excluded).\n"
        "Cost sums simulator execution across futures; forecast fitting and "
        "Kubernetes overhead are excluded.\n" + context["selection_note"],
    )


def detail_page(pdf, result, group):
    """Show the first usable window, chosen by chronology rather than prediction quality.

    Args:
        pdf (PdfPages): Open report destination.
        result (dict): Saved measurements and individual scenario cases.
        group (dict): Detail settings at the first shared usable starting point.
    """
    horizon, count = group["horizon_seconds"], group["scenarios"]
    window = group["windows"]["120"]
    figure, axes = page(
        "Forecast example | arrivals and completions",
        f"{horizon} s forecast, {count} futures; starting point {group['cutoff_index'] + 1}. "
        "First shared usable window, chosen chronologically.",
        rows=1,
        columns=2,
    )
    axes = axes[0]
    arrivals = group["arrivals"]
    arrival_samples = np.column_stack(
        (np.zeros(count), np.cumsum(arrivals["scenario_bins"], axis=1))
    )
    completions = [
        c["comparisons"]["120"]["predicted_curve"]
        for c in result["cases"]
        if c["arrival_source"] == "forecast"
        and c["seed"] == group["seed"]
        and c["horizon_seconds"] == horizon
        and c["scenario"] < count
        and c["cutoff_index"] == group["cutoff_index"]
    ]
    for axis, times, matrix, observed, title, ylabel in (
        (
            axes[0],
            np.arange(arrival_samples.shape[1]) * 5,
            arrival_samples,
            np.r_[0, np.cumsum(arrivals["observed_bins"])],
            "New arrivals",
            "Cumulative arriving Jobs",
        ),
        (
            axes[1],
            window["grid_seconds"],
            completions,
            window["observed_curve"],
            "Completions: existing + new Jobs",
            "Cumulative completed Jobs",
        ),
    ):
        _draw_prediction(axis, times, matrix, "Forecast median + min–max", "#2864b4")
        axis.plot(times, observed, color="black", linewidth=1.8, label="Observed")
        axis.set(title=title, ylabel=ylabel, xlabel="Seconds after the prediction starts")
        _finish_axes(axis, integer_y=True)
        axis.set_xlim(0, max(times))
        axis.set_xticks(np.arange(0, max(times) + 1, 20))
        axis.grid(alpha=0.2)

    figure.legend(
        *axes[0].get_legend_handles_labels(),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.105),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    finish(
        pdf,
        figure,
        f"Bands span {count} futures, not confidence intervals. "
        "One configuration; arrival and completion time domains are labeled separately.\n"
        "Completion means classifier finish; the Kubernetes Job-completion signal arrives later.\n"
        "Initialization and represented-work limitations remain in the saved "
        "evidence; missing work is not zero work.",
    )


def _draw_prediction(axis, times, matrix, label, color, linestyle="-"):
    """Draw the accepted median/outline/fill styling for a scenario matrix.

    Args:
        axis (Axes): Destination plot.
        times (array-like): Common horizontal coordinates.
        matrix (array-like): One row per scenario.
        label (str): Legend label.
        color (str): Stable configuration color.
        linestyle (str): Median and outline line style.
    """
    values = np.asarray(matrix)
    low, high = values.min(axis=0), values.max(axis=0)
    axis.fill_between(times, low, high, color=color, alpha=0.045)
    axis.plot(times, low, color=color, linewidth=0.8, linestyle=linestyle, alpha=0.75)
    axis.plot(times, high, color=color, linewidth=0.8, linestyle=linestyle, alpha=0.75)
    axis.plot(
        times,
        np.median(values, axis=0),
        color=color,
        linewidth=2.4,
        linestyle=linestyle,
        label=label,
    )
