"""Report actual controlled admission changes alongside their known-arrival replays."""
import argparse
import json
import math
from pathlib import Path
from statistics import mean

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt

from opendc_report_observed import _covered_series

SCHEMA = "opendc-controlled-report-v1"
TITLES = {
    "busy": "Cordon an occupied worker",
    "empty": "Cordon an empty worker",
    "up": "Uncordon a worker",
}


def validate_comparisons(comparisons):
    """Reject predictions labeled as a different physical action.

    Args:
        comparisons (list[dict]): Saved controlled action evidence.

    Raises:
        ValueError: The predicted and observed action identities disagree.
    """
    for saved in comparisons:
        kind = saved["physical"]["kind"]
        expected = "scale-up" if kind == "up" else "scale-down"
        if saved["context"]["candidate"] != expected or kind not in TITLES:
            raise ValueError("prediction does not match the observed action")
        action_reference(saved)


def action_reference(saved):
    """Locate display zero at the midpoint of the clock-bounded physical API interval.

    Args:
        saved (dict): Comparison with an action interval relative to the model cutoff.

    Returns:
        float or None: Seconds after cutoff, or absent action timing evidence.

    Raises:
        ValueError: The interval is malformed, nonfinite or reversed.
    """
    interval = saved["context"].get("observed_action_interval_seconds")
    if interval is None:
        return None
    if (
        len(interval) != 2
        or not all(math.isfinite(v) for v in interval)
        or interval[0] > interval[1]
    ):
        raise ValueError("invalid observed action interval")
    return mean(interval)


def timing_summary(saved):
    """Separate start-time and execution-duration errors for matched completed future Jobs.

    Restricting to new Jobs avoids mixing full execution with running remainders.
    These means explain timing discrepancy; they do not identify its causal mechanism.

    Args:
        saved (dict): Controlled comparison with matched pairs and task diagnostics.

    Returns:
        dict: Cohort size, available component counts and mean absolute errors in seconds.
    """
    comparison = saved.get("comparison") or {}
    matched = {pair["uid"] for pair in comparison.get("matched_completed_pairs", [])}
    rows = [
        row
        for row in comparison.get("tasks", [])
        if row["uid"] in matched and row["cohort"] == "future"
    ]
    result = {"matched_future_jobs": len(rows)}
    for name, key in (
        ("start", "start_or_resume_error_seconds"),
        ("runtime", "runtime_or_remainder_error_seconds"),
    ):
        values = [abs(row[key]) for row in rows if row.get(key) is not None]
        result[name + "_error_jobs"] = len(values)
        result[name + "_mae_seconds"] = mean(values) if values else None
    waits = [
        (row["observed"]["start_ms"] - row["original_creation_ms"]) / 1000
        for row in rows
        if (row.get("observed") or {}).get("start_ms") is not None
        and row.get("original_creation_ms") is not None
    ]
    result["observed_wait_jobs"] = len(waits)
    result["observed_wait_range_seconds"] = [min(waits), max(waits)] if waits else None
    return result


def _title(saved):
    """Build a reader-facing action and target label.

    Args:
        saved (dict): Physical kind and selected worker.

    Returns:
        str: Two-line panel title.
    """
    return TITLES[saved["physical"]["kind"]] + "\nTarget: " + saved["context"]["selected_worker"]


def _action_axis(axis, saved):
    """Label action-relative time and retain the physical timing uncertainty.

    Args:
        axis (Axes): Time-series panel.
        saved (dict): Physical action and clock-bounded timing evidence.

    Returns:
        float: Display shift in seconds; zero only for explicitly unavailable action timing.
    """
    reference = action_reference(saved)
    if reference is None:
        axis.set_xlabel("Seconds from model start (action time unavailable)", fontsize=8)
        return 0
    lower, upper = saved["context"]["observed_action_interval_seconds"]
    axis.axvspan(
        lower - reference,
        upper - reference,
        color="grey",
        alpha=0.3,
        label="Action timing interval",
    )
    action = "uncordon" if saved["physical"]["kind"] == "up" else "cordon"
    axis.set_xlabel(f"Seconds from {action} action")
    return reference


def render_pages(pdf, comparisons):
    """Append physical validation, completion/error explanation and individual responses.

    Args:
        pdf (PdfPages): Open PDF writer.
        comparisons (list[dict]): Saved controlled evidence, including unavailable results.
    """
    validate_comparisons(comparisons)
    for offset in range(0, len(comparisons), 3):
        page = comparisons[offset : offset + 3]
        _assignment_page(pdf, page, comparisons)
        _timing_page(pdf, page, comparisons)
        _response_page(pdf, page, comparisons)


def _assignment_page(pdf, page, all_comparisons):
    """Show the physical admission/drain check with a shared worker occupancy scale.

    Args:
        pdf (PdfPages): Open report writer.
        page (list[dict]): Comparisons on this page.
        all_comparisons (list[dict]): Evidence defining common colors and scales.
    """
    names = sorted(
        {
            name
            for saved in all_comparisons
            for point in saved.get("observed_occupancy", [])
            for name in point["workers"]
        }
    )
    maximum = max(
        [1]
        + [
            max(point["workers"].values(), default=0)
            for saved in all_comparisons
            for point in saved.get("observed_occupancy", [])
        ]
    )
    figure, axes = plt.subplots(
        1, len(page), figsize=(11.69, 8.27), squeeze=False, sharex=True, sharey=True
    )
    figure.subplots_adjust(top=0.77, bottom=0.31, left=0.07, right=0.97, wspace=0.22)
    figure.suptitle("Validation | Cordon and uncordon behave as expected", fontsize=16, y=0.96)
    # The page title describes the check; per-panel verdicts retain failures/inconclusive evidence.
    if any(saved["physical"]["status"] != "supported" for saved in page):
        figure.suptitle("Validation | Check cordon and uncordon behavior", fontsize=16, y=0.96)
    for axis, saved in zip(axes.flat, page):
        physical = saved["physical"]
        reference = _action_axis(axis, saved)
        for index, name in enumerate(names):
            values = [
                {
                    "time_seconds": point["time_seconds"] - reference,
                    "count": point["workers"].get(name),
                }
                for point in saved.get("observed_occupancy", [])
            ]
            if values:
                axis.step(
                    *_covered_series(values, "count"),
                    where="post",
                    color=plt.get_cmap("tab10")(index),
                    label=name,
                )
        axis.set(
            title=_title(saved), xlim=(-60, 120), ylim=(0, maximum + 0.4), ylabel="Assigned pods"
        )
        if not saved.get("observed_occupancy"):
            axis.text(
                0.5, 0.5, "Occupancy samples unavailable", ha="center", transform=axis.transAxes
            )
        axis.grid(alpha=0.2)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=7)
        detail = (
            f"Observed behavior: {physical['status']}\n"
            f"Initial target pods finished: {len(physical['drained_initial_pod_uids'])}/"
            f"{len(physical['initial_active_pod_uids'])}; "
            f"later admissions: {len(physical['new_assignments_after_ack'])}\n"
            f"Ambiguous boundary assignments: {len(physical['boundary_assignment_uids'])}"
        )
        axis.text(0, -0.26, detail, transform=axis.transAxes, fontsize=8, va="top", linespacing=1.6)
    figure.text(
        0.07,
        0.075,
        "Cordon lets assigned work finish and blocks new admissions. Uncordon permits new work.\n"
        "Pods shown are starting or running; completed pods are excluded. VMs stay powered on.\n"
        "Zero is the midpoint of the recorded action interval; shading includes clock uncertainty.",
        fontsize=8,
        linespacing=1.6,
    )
    pdf.savefig(figure)
    plt.close(figure)


def _timing_page(pdf, page, all_comparisons):
    """Contrast aggregate completion agreement with individual start/runtime errors.

    Args:
        pdf (PdfPages): Open report writer.
        page (list[dict]): Comparisons on this page.
        all_comparisons (list[dict]): Evidence defining shared count and timing scales.
    """
    count_max = max(
        [1]
        + [
            max(saved["comparison"][key])
            for saved in all_comparisons
            if saved.get("comparison")
            for key in ("observed_curve", "predicted_curve")
        ]
    )
    summaries = [timing_summary(saved) for saved in all_comparisons]
    error_max = (
        max(
            [1]
            + [
                summary[key]
                for summary in summaries
                for key in ("start_mae_seconds", "runtime_mae_seconds")
                if summary[key] is not None
            ]
        )
        * 1.2
    )
    figure, axes = plt.subplots(
        2,
        len(page),
        figsize=(11.69, 8.27),
        squeeze=False,
        sharey="row",
        gridspec_kw={"height_ratios": [1.4, 1]},
    )
    figure.subplots_adjust(top=0.79, bottom=0.23, left=0.07, right=0.97, wspace=0.22, hspace=0.95)
    figure.suptitle(
        "Validation | Completion counts can hide individual timing errors", fontsize=16, y=0.96
    )
    for column, saved in enumerate(page):
        top, bottom = axes[:, column]
        reference = _action_axis(top, saved)
        comparison = saved.get("comparison")
        top.set(
            title=_title(saved), xlim=(-5, 120), ylim=(0, count_max * 1.05), ylabel="Completed jobs"
        )
        summary = timing_summary(saved)
        if comparison:
            grid = [seconds - reference for seconds in comparison["grid_seconds"]]
            for key, color, style, label in (
                ("observed_curve", "black", "-", "Observed"),
                ("predicted_curve", "#2864b4", "--", "OpenDC replay"),
            ):
                top.step(
                    grid,
                    comparison[key],
                    where="post",
                    color=color,
                    linestyle=style,
                    linewidth=2,
                    label=label,
                )
            count_error = comparison["completion_curve_mae"]
            count_label = f"{count_error:.2f} jobs" if count_error is not None else "unavailable"
            detail = (
                f"Count MAE: {count_label}\n"
                f"Exhausted: {len(comparison['model_exhausted'])}; "
                f"unmatched: {len(comparison['unmatched_observed_backlog'])}; "
                f"censored: {len(comparison['observed_censored_uids'])}"
            )
            if not comparison["coverage_complete"] or not (
                comparison.get("initial_membership") or {}
            ).get("complete"):
                detail += "\nIncomplete coverage or initial membership"
        else:
            detail = saved.get("native_unavailable_reason", "Native comparison unavailable")
            top.text(
                0.5, 0.5, "Native comparison unavailable", ha="center", transform=top.transAxes
            )
        for index, (key, color) in enumerate(
            (("start_mae_seconds", "#c56a16"), ("runtime_mae_seconds", "#2864b4"))
        ):
            value = summary[key]
            if value is not None:
                bottom.bar(index, value, color=color, width=0.55)
                bottom.text(
                    index,
                    value + error_max * 0.035,
                    "<0.1" if 0 < value < 0.1 else f"{value:.2f}",
                    ha="center",
                    fontsize=9,
                )
            else:
                bottom.text(index, error_max * 0.2, "Unavailable", ha="center", fontsize=8)
        bottom.set(
            xticks=[0, 1],
            xticklabels=["Start time", "Runtime"],
            ylabel="Mean absolute error (s)",
            ylim=(0, error_max),
            xlim=(-0.6, 1.6),
        )
        bottom.set_title(
            f"{summary['matched_future_jobs']} matched completed future jobs", fontsize=10
        )
        bottom.text(
            0, -0.36, detail, transform=bottom.transAxes, fontsize=8, va="top", linespacing=1.5
        )
        for axis in (top, bottom):
            axis.grid(axis="y", alpha=0.2)
        if top.get_legend_handles_labels()[0]:
            top.legend(fontsize=7)
    figure.text(
        0.07,
        0.05,
        "Start-time error includes waiting and startup; "
        "runtime error measures classifier execution.\n"
        "Replay uses actual arrivals; the model starts shortly before the physical action. "
        "API timestamps have one-second resolution.\n"
        "Scored cohort: initial backlog plus 60 s of arrivals, "
        "followed for 120 s from model start. "
        "Different workloads across actions.",
        fontsize=8,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)


def _response_page(pdf, page, all_comparisons):
    """Expose per-Job timing differences that can cancel in aggregate completion curves.

    Args:
        pdf (PdfPages): Open report writer.
        page (list[dict]): Controlled actions shown on this page.
        all_comparisons (list[dict]): All report evidence defining the shared response scale.
    """
    maximum = (
        max(
            [1]
            + [
                pair[key]
                for saved in all_comparisons
                for pair in (saved.get("comparison") or {}).get("matched_completed_pairs", [])
                for key in ("observed_response_seconds", "predicted_response_seconds")
            ]
        )
        * 1.05
    )
    figure, axes = plt.subplots(
        1, len(page), figsize=(11.69, 8.27), squeeze=False, sharex=True, sharey=True
    )
    figure.subplots_adjust(top=0.77, bottom=0.35, left=0.08, right=0.97, wspace=0.22)
    figure.suptitle(
        "Validation | Where do individual response predictions differ?", fontsize=16, y=0.96
    )
    for axis, saved in zip(axes.flat, page):
        comparison = saved.get("comparison") or {}
        pairs = comparison.get("matched_completed_pairs", [])
        for cohort, color in (("backlog", "#2864b4"), ("future", "#c56a16")):
            selected = [pair for pair in pairs if pair["cohort"] == cohort]
            if selected:
                axis.scatter(
                    [p["observed_response_seconds"] for p in selected],
                    [p["predicted_response_seconds"] for p in selected],
                    label=cohort.capitalize(),
                    color=color,
                    alpha=0.75,
                    s=24,
                )
        axis.plot([0, maximum], [0, maximum], color="grey", linestyle=":", label="Equal response")
        axis.set(
            title=_title(saved),
            xlabel="Observed response (s)",
            ylabel="Predicted response (s)",
            xlim=(0, maximum),
            ylim=(0, maximum),
        )
        axis.set_aspect("equal", adjustable="box")
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8)
        error = comparison.get("matched_response_mae_seconds")
        annotation = (
            f"{len(pairs)} matched completed Jobs\nResponse MAE {error:.2f} s"
            if error is not None
            else "No matched completed response estimate"
        )
        timing = timing_summary(saved)
        if timing["observed_wait_range_seconds"] is not None:
            lower, upper = timing["observed_wait_range_seconds"]
            annotation += f"\nFuture observed wait: {lower:g}–{upper:g} s"
        axis.text(
            0, -0.27, annotation, transform=axis.transAxes, fontsize=9, va="top", linespacing=1.6
        )
    figure.text(
        0.08,
        0.10,
        "Response = waiting + classifier execution. "
        "Backlog includes running, starting and queued jobs; "
        "their observed history is retained.\n"
        "Backlog/future are defined at model start, shortly before the action. "
        "Start/runtime errors are separated on the previous page.\n"
        "Only matched completions are plotted. Different workloads and queue pressure "
        "prevent a general scale-up/down accuracy ranking.",
        fontsize=8,
        linespacing=1.6,
    )
    pdf.savefig(figure)
    plt.close(figure)


def write_report(comparison_files, output_dir):
    """Write an exclusive offline report while preserving unsuccessful comparisons.

    Args:
        comparison_files (iterable[Path]): Individual comparisons or a saved combined metrics file.
        output_dir (str or Path): New output directory.

    Returns:
        dict: Full numerical payload retained for offline regeneration.

    Raises:
        ValueError: No results or predicted/observed actions disagree.
        FileExistsError: Destination already exists.
    """
    comparisons = []
    for source in comparison_files:
        saved = json.loads(Path(source).read_text(encoding="utf-8"))
        comparisons.extend(saved.get("comparisons", [saved]))
    if not comparisons:
        raise ValueError("no controlled comparisons")
    validate_comparisons(comparisons)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    payload = {"schema_version": SCHEMA, "comparisons": comparisons}
    (output / "metrics.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    with PdfPages(output / "report.pdf") as pdf:
        render_pages(pdf, comparisons)
    return payload


def main():
    """Render preserved physical intervention comparisons without a live cluster."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    write_report(args.comparison, args.output_dir)


if __name__ == "__main__":
    main()
