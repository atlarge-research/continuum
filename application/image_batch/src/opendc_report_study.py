"""Plot a frozen forecast study directly against observed and known-arrival outcomes."""
import statistics

import matplotlib.pyplot as plt

SCHEMA = "opendc-study-evidence-v1"


def study_panels(saved):
    """Pair selected forecasts with unchanged known-arrival replay on identical grids.

    Args:
        saved (dict): Frozen selection and separately identified validation/held-out results.

    Returns:
        list[dict]: Chronological full numerical panels, without fitting or reselection.

    Raises:
        ValueError: Frozen settings, paired identities or observed cohort curves disagree.
    """
    choice = saved["selection"]
    horizon, count = choice["selected"]["horizon_seconds"], choice["selected"]["scenarios"]
    seed = choice["scenario_seed"]
    panels = []
    for result in saved["results"]:
        all_forecasts = [g for g in result["groups"] if g["arrival_source"] == "forecast"]
        forecasts = [
            g
            for g in all_forecasts
            if (g["horizon_seconds"], g["scenarios"], g["seed"]) == (horizon, count, seed)
        ]
        if not forecasts or (
            result["split"] == "held-out" and len(forecasts) != len(all_forecasts)
        ):
            raise ValueError("study does not use only the frozen held-out configuration")
        keys = [(g["cutoff_index"], g["cutoff_ms"]) for g in forecasts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate selected cutoff")
        for forecast in sorted(forecasts, key=lambda g: g["cutoff_ms"]):
            known = [
                g
                for g in result["groups"]
                if g["arrival_source"] == "known-arrival"
                and (
                    g["cutoff_index"],
                    g["cutoff_ms"],
                    g["horizon_seconds"],
                    g["seed"],
                    g["scenarios"],
                )
                == (forecast["cutoff_index"], forecast["cutoff_ms"], horizon, seed, 1)
            ]
            if len(known) != 1:
                raise ValueError("selected cutoff requires exactly one paired known-arrival replay")
            prediction, replay = forecast["windows"]["120"], known[0]["windows"]["120"]
            if any(prediction[key] != replay[key] for key in ("grid_seconds", "observed_curve")):
                raise ValueError("forecast and known-arrival observed cohort curves disagree")
            cases = [
                case
                for case in result.get("cases", [])
                if case["cutoff_index"] == forecast["cutoff_index"]
                and case["horizon_seconds"] == horizon
                and case["seed"] == seed
                and case["arrival_source"] == "known-arrival"
            ]
            comparison = cases[0]["comparisons"]["120"] if len(cases) == 1 else {}
            if comparison:
                actual = sorted(comparison["observations"], key=lambda row: row["uid"])
                forecasts_cases = [
                    case
                    for case in result.get("cases", [])
                    if case["cutoff_index"] == forecast["cutoff_index"]
                    and case["horizon_seconds"] == horizon
                    and case["seed"] == seed
                    and case["arrival_source"] == "forecast"
                    and case["scenario"] < count
                ]
                if len(forecasts_cases) != count or any(
                    sorted(case["comparisons"]["120"]["observations"], key=lambda row: row["uid"])
                    != actual
                    for case in forecasts_cases
                ):
                    raise ValueError(
                        "forecast and known-arrival observed cohort identities disagree"
                    )
            panels.append(
                {
                    "run_id": result["run_id"],
                    "split": result["split"],
                    "workload_seed": result["workload_seed"],
                    "cutoff_index": forecast["cutoff_index"],
                    "cutoff_ms": forecast["cutoff_ms"],
                    "horizon_seconds": horizon,
                    "scenarios": count,
                    "scenario_seed": seed,
                    "forecast": prediction,
                    "known_arrival": replay,
                    "diagnostics": {
                        "membership_complete": (comparison.get("initial_membership") or {}).get(
                            "complete"
                        ),
                        **{
                            key: len(comparison.get(key, []))
                            for key in (
                                "model_exhausted",
                                "unmatched_observed_backlog",
                                "observed_censored_uids",
                                "unknown_outcome_uids",
                            )
                        },
                    },
                }
            )
    return panels


def render_study_pages(pdf, saved):
    """Render frozen selection and adjacent observed/forecast/replay completion panels.

    Args:
        pdf (PdfPages): Open combined report writer.
        saved (dict): Complete saved study evidence.

    Returns:
        dict: Exact selection and numerical panels used for the figures.
    """
    panels = study_panels(saved)
    selection = saved["selection"]
    if selection.get("candidates"):
        _selection_page(pdf, selection, panels)
    maximum = max(
        [1]
        + [
            max(panel["forecast"][key])
            for panel in panels
            for key in ("observed_curve", "completion_max")
        ]
        + [max(panel["known_arrival"]["completion_median"]) for panel in panels]
    )
    for run in dict.fromkeys(panel["run_id"] for panel in panels):
        run_panels = [panel for panel in panels if panel["run_id"] == run]
        for offset in range(0, len(run_panels), 4):
            page = run_panels[offset : offset + 4]
            figure, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), sharex=True, sharey=True)
            figure.subplots_adjust(
                top=0.82, bottom=0.17, left=0.08, right=0.97, hspace=0.5, wspace=0.25
            )
            figure.suptitle(
                "Frozen forecast | observed completions and known-arrival replay",
                fontsize=16,
                y=0.97,
            )
            figure.text(
                0.08,
                0.91,
                f"{run} | {page[0]['split']} | workload seed {page[0]['workload_seed']}",
                fontsize=9,
            )
            figure.text(
                0.08,
                0.87,
                f"H{page[0]['horizon_seconds']} / N{page[0]['scenarios']} | "
                f"scenario seed {page[0]['scenario_seed']} | E120",
                fontsize=9,
            )
            for axis, panel in zip(axes.flat, page):
                view, known = panel["forecast"], panel["known_arrival"]
                grid = view["grid_seconds"]
                axis.fill_between(
                    grid,
                    view["completion_min"],
                    view["completion_max"],
                    step="post",
                    color="#2864b4",
                    alpha=0.10,
                )
                for key in ("completion_min", "completion_max"):
                    axis.step(
                        grid, view[key], where="post", color="#2864b4", linewidth=0.8, alpha=0.7
                    )
                axis.step(
                    grid,
                    view["completion_median"],
                    where="post",
                    color="#2864b4",
                    linewidth=2,
                    label="Forecast median + min–max",
                )
                axis.step(
                    grid,
                    known["completion_median"],
                    where="post",
                    color="#c56a16",
                    linestyle="--",
                    label="Known-arrival replay",
                )
                axis.step(
                    grid,
                    view["observed_curve"],
                    where="post",
                    color="black",
                    linewidth=2,
                    label="Observed",
                )
                diagnostic = panel["diagnostics"]
                membership = {True: "complete", False: "incomplete", None: "unknown"}[
                    diagnostic["membership_complete"]
                ]
                axis.set(
                    title=f"Cutoff {panel['cutoff_index']} | "
                    f"membership {membership}\n"
                    f"exhausted {diagnostic['model_exhausted']}, "
                    f"unmatched {diagnostic['unmatched_observed_backlog']}, "
                    f"censored {diagnostic['observed_censored_uids']}, "
                    f"unknown {diagnostic['unknown_outcome_uids']}",
                    xlabel="Seconds after cutoff",
                    ylabel="Completed cohort Jobs",
                    xlim=(0, 120),
                    ylim=(0, maximum * 1.05),
                )
                axis.grid(alpha=0.2)
                axis.legend(fontsize=7)
                if not view["coverage_complete"] or not known["coverage_complete"]:
                    axis.text(
                        0.02,
                        0.55,
                        "Incomplete observation coverage",
                        transform=axis.transAxes,
                        fontsize=8,
                    )
            for axis in list(axes.flat)[len(page) :]:
                axis.set_visible(False)
            figure.text(
                0.08,
                0.055,
                "Same physical run and arrival cohort; backlog included. "
                "Bands are sampled ranges, not confidence intervals.\n"
                "Unmodeled startup/exhausted occupancy and scheduling differences remain; "
                "these are unchanged-action comparisons.",
                fontsize=9,
                linespacing=1.5,
            )
            pdf.savefig(figure)
            plt.close(figure)
    return {"selection": selection, "panels": panels}


def _selection_page(pdf, selection, panels):
    """Display equal-run selection separately from the untouched held-out outcome.

    Args:
        pdf (PdfPages): Open report writer.
        selection (dict): Previously frozen selection record.
        panels (list[dict]): Selected-setting observation comparisons.
    """
    candidates = selection["candidates"]
    figure, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
    figure.subplots_adjust(top=0.78, bottom=0.26, left=0.08, right=0.97, wspace=0.3)
    figure.suptitle(
        "Configuration selection | independent workload runs, then held-out evaluation",
        fontsize=16,
        y=0.96,
    )
    chosen = selection["selected"]
    figure.text(
        0.08,
        0.88,
        f"Frozen H{chosen['horizon_seconds']} / N{chosen['scenarios']} | "
        f"{selection['selected_at_utc']}",
        fontsize=10,
    )
    for index, row in enumerate(candidates):
        low, high = row["between_run_completion_mae_range"]
        mean = row["completion_curve_mae"]
        axes[0].errorbar(
            index, mean, yerr=[[mean - low], [high - mean]], fmt="o", capsize=6, color="#2864b4"
        )
    axes[0].set(
        xticks=range(len(candidates)),
        xticklabels=[f"H{r['horizon_seconds']} / N{r['scenarios']}" for r in candidates],
        ylabel="Completion-curve MAE (Jobs)",
        title="Validation: equal run means and between-run range",
        ylim=(0, None),
    )
    held = [panel for panel in panels if panel["split"] == "held-out"]
    if not held:
        axes[1].text(
            0.5, 0.5, "Held-out results not supplied", ha="center", transform=axes[1].transAxes
        )
        axes[1].set_xticks([])
    for index, run in enumerate(dict.fromkeys(panel["run_id"] for panel in held)):
        selected = [
            p
            for p in held
            if p["run_id"] == run
            and p["forecast"]["coverage_complete"]
            and p["known_arrival"]["coverage_complete"]
        ]
        if selected:
            values = [
                statistics.mean(p[key]["completion_curve_mae"] for p in selected)
                for key in ("forecast", "known_arrival")
            ]
            axes[1].bar([index * 3, index * 3 + 1], values, color=["#2864b4", "#c56a16"])
            axes[1].set_xticks([index * 3, index * 3 + 1], ["Frozen forecast", "Known arrivals"])
            axes[1].set_title(
                f"Held-out seed {selected[0]['workload_seed']} | {len(selected)} covered cutoffs"
            )
    axes[1].set(ylabel="Completion-curve MAE (Jobs)", ylim=(0, None))
    maximum = max(axis.get_ylim()[1] for axis in axes)
    for axis in axes:
        axis.set_ylim(0, maximum)
        axis.grid(axis="y", alpha=0.2)
    figure.text(
        0.08,
        0.12,
        "Small validation differences are descriptive; "
        "held-out outcomes never change the frozen choice.\n"
        "Cutoffs overlap and futures are nested within each run. "
        "Ranges are not confidence intervals.\n"
        "Shared batch cost is measured once; per-configuration runtime is unavailable.",
        fontsize=10,
        linespacing=1.5,
    )
    pdf.savefig(figure)
    plt.close(figure)
