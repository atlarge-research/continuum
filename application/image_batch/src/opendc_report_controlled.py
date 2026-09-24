"""Report actual controlled admission changes alongside their known-arrival replays."""
import argparse
import json
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt

from opendc_report_observed import _covered_series

TITLES = {
    "busy": "Occupied-worker cordon",
    "empty": "Empty-worker cordon",
    "up": "Reserve admission",
}


def render_pages(pdf, comparisons):
    """Show measured assignments first, then prediction against the executed intervention.

    Args:
        pdf (PdfPages): Open PDF writer.
        comparisons (list[dict]): Saved controlled comparison payloads, including failures.
    """
    maximum = max(
        [1]
        + [
            max(saved["comparison"][key])
            for saved in comparisons
            if saved.get("comparison")
            for key in ("observed_curve", "predicted_curve")
        ]
    )
    worker_names = sorted(
        {
            name
            for saved in comparisons
            for point in saved.get("observed_occupancy", [])
            for name in point["workers"]
        }
    )
    colors = {name: plt.get_cmap("tab10")(index) for index, name in enumerate(worker_names)}
    occupancy_maximum = max(
        [1]
        + [
            max(point["workers"].values(), default=0)
            for saved in comparisons
            for point in saved.get("observed_occupancy", [])
        ]
    )
    for offset in range(0, len(comparisons), 3):
        page = comparisons[offset : offset + 3]
        for measured in (True, False):
            figure, axes = plt.subplots(
                1, len(page), figsize=(11.69, 8.27), squeeze=False, sharex=True, sharey=True
            )
            figure.subplots_adjust(top=0.77, bottom=0.31, left=0.07, right=0.97, wspace=0.22)
            figure.suptitle(
                "Controlled changes | measured worker assignments"
                if measured
                else "Controlled changes | prediction against the action actually observed",
                fontsize=16,
                y=0.96,
            )
            for axis, saved in zip(axes.flat, page):
                physical, context = saved["physical"], saved["context"]
                axis.set_title(
                    TITLES[physical["kind"]]
                    + "\n"
                    + context["selected_worker"]
                    + f" | seed {context.get('workload_seed', 'unavailable')}",
                    fontsize=11,
                )
                if measured:
                    points = saved.get("observed_occupancy", [])
                    for name in worker_names:
                        values = [
                            {
                                "time_seconds": point["time_seconds"],
                                "count": point["workers"].get(name),
                            }
                            for point in points
                        ]
                        if values:
                            axis.step(
                                *_covered_series(values, "count"),
                                where="post",
                                color=colors[name],
                                label=name,
                            )
                    interval = context.get("observed_action_interval_seconds")
                    if interval:
                        axis.axvspan(
                            *interval, color="grey", alpha=0.3, label="Observed API interval"
                        )
                    axis.set(
                        xlim=(-60, 120),
                        ylim=(0, occupancy_maximum + 0.4),
                        ylabel="Assigned unfinished Pods",
                    )
                    if not points:
                        axis.text(
                            0.5,
                            0.5,
                            "Occupancy samples unavailable",
                            ha="center",
                            transform=axis.transAxes,
                        )
                    detail = f"Observed behavior: {physical['status']}\n" + (
                        f"Selected-worker drain {len(physical['drained_initial_pod_uids'])}/"
                        f"{len(physical['initial_active_pod_uids'])}; "
                        f"new admissions {len(physical['new_assignments_after_ack'])}\n"
                        f"API-boundary assignments {len(physical['boundary_assignment_uids'])}"
                    )
                else:
                    comparison = saved.get("comparison")
                    if comparison:
                        grid = comparison["grid_seconds"]
                        axis.step(
                            grid,
                            comparison["observed_curve"],
                            where="post",
                            color="black",
                            linewidth=2,
                            label="Observed completions",
                        )
                        axis.step(
                            grid,
                            comparison["predicted_curve"],
                            where="post",
                            color="#2864b4",
                            linewidth=2,
                            linestyle="--",
                            label="Known-arrival action replay",
                        )
                        detail = f"Completion MAE {comparison['completion_curve_mae']} Jobs\n" + (
                            f"Exhausted {len(comparison['model_exhausted'])}; "
                            f"unmatched {len(comparison['unmatched_observed_backlog'])}; "
                            f"censored {len(comparison['observed_censored_uids'])}\n"
                            "Membership complete: "
                            f"{(comparison.get('initial_membership') or {}).get('complete')}"
                        )
                        if not comparison["coverage_complete"]:
                            detail += "\nIncomplete observation coverage"
                    else:
                        detail = saved.get(
                            "native_unavailable_reason", "Native comparison unavailable"
                        )
                        axis.text(
                            0.5,
                            0.5,
                            "Native comparison unavailable",
                            ha="center",
                            transform=axis.transAxes,
                        )
                    axis.set(
                        xlim=(0, 120), ylim=(0, maximum * 1.05), ylabel="Completed cohort Jobs"
                    )
                axis.set_xlabel("Seconds from pre-action snapshot")
                axis.grid(alpha=0.2)
                if axis.get_legend_handles_labels()[0]:
                    axis.legend(fontsize=7)
                axis.text(
                    0,
                    -0.26,
                    detail,
                    transform=axis.transAxes,
                    fontsize=8,
                    va="top",
                    linespacing=1.6,
                )
            footer = (
                "Assigned unfinished Pods include startup. Gaps break curves. "
                "Shading bounds the observed API action, including clock uncertainty.\n"
                "Cordon stops admission without evicting assigned work; "
                "the VMs remain powered on.\n"
                "Workload seeds differ across actions; these are separate prediction checks."
                if measured
                else "One known-arrival replay per actual action; H60 arrival cohort plus backlog, "
                "H120 competing arrivals, E120 follow-up.\n"
                "Simulation acts at zero; the physical request follows the saved snapshot. "
                "Unchanged predictions are unobserved counterfactuals.\n"
                "Startup/exhausted occupancy and scheduling differences remain; "
                "no physical energy accuracy or winning action is inferred. "
                "Workload seeds differ across actions."
            )
            figure.text(0.07, 0.075, footer, fontsize=8, linespacing=1.6)
            pdf.savefig(figure)
            plt.close(figure)
        _response_page(pdf, page, comparisons)


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
    figure.suptitle("Controlled changes | matched per-Job response times", fontsize=16, y=0.96)
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
            title=TITLES[saved["physical"]["kind"]]
            + f"\nWorkload seed {saved['context'].get('workload_seed', 'unavailable')}",
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
        axis.text(
            0, -0.27, annotation, transform=axis.transAxes, fontsize=9, va="top", linespacing=1.6
        )
    figure.text(
        0.08,
        0.10,
        "Response retains original Job creation time and ends at classifier finish. "
        "Only matched completions within E120 appear here.\n"
        "Unfinished, exhausted and unmatched Jobs remain explicit "
        "in the completion panels and saved metrics.\n"
        "Workload seeds differ across actions; these prediction checks "
        "do not estimate a paired action-performance benefit.",
        fontsize=9,
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
    for saved in comparisons:
        expected = "scale-up" if saved["physical"]["kind"] == "up" else "scale-down"
        if saved["context"]["candidate"] != expected or saved["physical"]["kind"] not in TITLES:
            raise ValueError("prediction does not match the observed action")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    payload = {"schema_version": "opendc-controlled-report-v1", "comparisons": comparisons}
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
