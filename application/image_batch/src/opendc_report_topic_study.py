"""Frozen configuration choice and held-out completion/response interpretation."""
import statistics

from matplotlib.ticker import MaxNLocator

from opendc_report_layout import BLUE, ORANGE, COLORS, page, panel, finish


def render_selection(pdf, study, panels, supplement):
    """Explain candidate differences, sampling sensitivity and held-out error units.

    Args:
        pdf (PdfPages): Open report writer.
        study (dict): Frozen choice and unchanged original study evidence.
        panels (list[dict]): Paired forecast/known-arrival comparisons.
        supplement (dict): Matched-phase scenario-seed sensitivity, if supplied.

    Raises:
        ValueError: No covered held-out comparison is available.
    """
    selection = study["selection"]
    chosen = selection["selected"]
    held = [
        p
        for p in panels
        if p["split"] == "held-out"
        and p["forecast"]["coverage_complete"]
        and p["known_arrival"]["coverage_complete"]
    ]
    if not held:
        raise ValueError("held-out evaluation has no covered paired cutoffs")
    figure, axes = page(
        "Configuration selection | small differences, limited evidence",
        f"H{chosen['horizon_seconds']}/N{chosen['scenarios']} was selected before "
        f"held-out seed {held[0]['workload_seed']}; the held-out run never changes the choice.",
    )
    candidates = selection["candidates"]
    for index, candidate in enumerate(candidates):
        mean = candidate["completion_curve_mae"]
        low, high = candidate["between_run_completion_mae_range"]
        axes[0, 0].errorbar(
            index, mean, yerr=[[mean - low], [high - mean]], fmt="o", capsize=5, color=BLUE
        )
        for offset, (run, values) in enumerate(candidate["per_run"].items()):
            axes[0, 0].plot(
                index + (offset - 0.5) * 0.12,
                values["completion_error"],
                "x",
                color=COLORS[offset % 3],
                label=f"Seed {selection['workload_seeds'][run]}" if index == 0 else None,
            )
    axes[0, 0].set(
        xticks=range(len(candidates)),
        xticklabels=[f"N{c['scenarios']}" for c in candidates],
        ylim=(0, None),
    )
    panel(
        axes[0, 0],
        "Similar errors across tested sample counts",
        "Sampled futures (H60 fixed)",
        "Completion-count MAE (Jobs)",
    )
    sensitivity = supplement.get("sensitivity", {})
    for key, color, label in (
        ("primary", BLUE, "Original scenario seed"),
        ("secondary", ORANGE, "Second scenario seed"),
    ):
        rows = sensitivity.get("rows", [])
        axes[0, 1].plot(range(len(rows)), [r[key] for r in rows], "o-", color=color, label=label)
    axes[0, 1].set(
        xticks=range(len(rows)), xticklabels=[f"N{r['scenarios']}" for r in rows], ylim=(0, None)
    )
    panel(
        axes[0, 1],
        "Changing sampled futures can change the ranking"
        if rows
        else "Scenario-seed sensitivity not supplied",
        "Same rising/busy phases; sampled futures",
        "Completion-count MAE (Jobs)",
    )
    for axis, position in zip(axes[0], (0.28, 0.76)):
        handles, labels = axis.get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="center",
            bbox_to_anchor=(position, 0.855),
            ncol=2,
            frameon=False,
            fontsize=8,
        )
    means = [
        statistics.mean(p[key]["completion_curve_mae"] for p in held)
        for key in ("forecast", "known_arrival")
    ]
    axes[1, 0].bar([0, 1], means, color=[BLUE, ORANGE], width=0.6)
    for index, value in enumerate(means):
        axes[1, 0].text(index, value + 0.04, f"{value:.2f} Jobs", ha="center", fontsize=10)
    axes[1, 0].set(
        xticks=[0, 1],
        xticklabels=[f"Selected H60/N{chosen['scenarios']}", "Known arrivals"],
        ylim=(0, max(means) * 1.3),
    )
    panel(
        axes[1, 0],
        "Held-out: lower error with known arrivals",
        "Same observed cohort and 120-s follow-up",
        "Mean absolute count gap (Jobs)",
    )
    response_deltas = []
    for index, item in enumerate(held):
        response = item["forecast"]["responses"]["future"]
        observed = response["observed"]["median"]
        predicted = response["median"]
        if observed is not None and predicted["median"] is not None:
            response_deltas.append(observed - predicted["median"])
        if observed is not None:
            axes[1, 1].plot(
                index, observed, "o", color="black", label="Observed" if index == 0 else None
            )
        if predicted["median"] is not None:
            axes[1, 1].errorbar(
                index + 0.12,
                predicted["median"],
                yerr=[
                    [predicted["median"] - predicted["min"]],
                    [predicted["max"] - predicted["median"]],
                ],
                fmt="o",
                capsize=4,
                color=BLUE,
                label="Forecast median + range" if index == 0 else None,
            )
    axes[1, 1].set(
        xticks=range(len(held)),
        xticklabels=[str(p["cutoff_index"] + 1) for p in held],
        ylim=(0, None),
    )
    panel(
        axes[1, 1],
        "Forecasts underestimate median response here"
        if response_deltas and min(response_deltas) > 0
        else "Response errors vary across cutoffs",
        "Held-out cutoff (chronological)",
        "Future-Job median response (s)",
    )
    axes[1, 1].set_ylim(0, axes[1, 1].get_ylim()[1] * 1.1)
    handles, labels = axes[1, 1].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="center",
        bbox_to_anchor=(0.76, 0.12),
        ncol=1,
        frameon=False,
        fontsize=8,
    )
    figure.text(
        0.08,
        0.108,
        "H = future-arrival seconds; N = sampled futures.\nFollow-up = 120 s; count grid = 5 s.",
        fontsize=9,
    )
    diagnostics = [p["diagnostics"] for p in panels if p["split"] != "held-out"]
    incomplete = sum(d["membership_complete"] is not True for d in diagnostics)
    exhausted = sum(d["model_exhausted"] for d in diagnostics)
    unmatched = sum(d["unmatched_observed_backlog"] for d in diagnostics)
    censored = sum(d["observed_censored_uids"] for d in diagnostics)
    unknown = sum(d["unknown_outcome_uids"] for d in diagnostics)
    figure.text(
        0.08,
        0.085,
        f"Selection Job-cutoff diagnostics: {incomplete} incomplete memberships; "
        f"{exhausted} exhausted; {unmatched} unmatched; {censored} censored; {unknown} unknown.",
        fontsize=8,
    )
    finish(
        pdf,
        figure,
        "Count MAE is the average vertical gap in cumulative completions, not a percentage "
        "or a per-Job timing error.\nResponse: creation → finish, completed future Jobs only; "
        "sample ranges are not confidence intervals. "
        "Cutoffs overlap; no general optimum is established.",
    )


def render_completion(pdf, panels, roles):
    """Show all held-out phases with directly paired predictions and outcome completeness.

    Args:
        pdf (PdfPages): Open report writer.
        panels (list[dict]): Chronological cutoffs for the identified held-out workload.
        roles (dict): Explicit run metadata retained by the report (for identity context).
    """
    maximum = max(
        [1]
        + [max(p["forecast"][key]) for p in panels for key in ("observed_curve", "completion_max")]
        + [max(p["known_arrival"]["completion_median"]) for p in panels]
    )
    for offset in range(0, len(panels), 4):
        subset = panels[offset : offset + 4]
        seed = roles[subset[0]["run_id"]]["workload_seed"]
        figure, axes = page(
            "Completion diagnosis | predictions directly against observations",
            f"Held-out seed {seed}: known-arrival replay isolates simulator discrepancy; "
            "forecast curves also include uncertain arrivals.",
        )
        for axis, item in zip(axes.flat, subset):
            view, known = item["forecast"], item["known_arrival"]
            grid = view["grid_seconds"]
            axis.fill_between(
                grid,
                view["completion_min"],
                view["completion_max"],
                step="post",
                color=BLUE,
                alpha=0.15,
            )
            for values, label, color, style in (
                (view["completion_median"], "Forecast median + sample min–max", BLUE, "-"),
                (known["completion_median"], "Known-arrival replay", ORANGE, "--"),
                (view["observed_curve"], "Observed", "black", "-"),
            ):
                axis.step(
                    grid,
                    values,
                    where="post",
                    color=color,
                    linestyle=style,
                    linewidth=1.6,
                    label=label,
                )
            forecast_error, replay_error = (
                view["completion_curve_mae"],
                known["completion_curve_mae"],
            )
            delta = view["completion_median"][-1] - view["observed_curve"][-1]
            conclusion = (
                "forecasts too many completions"
                if delta > 0
                else "forecasts too few completions"
                if delta < 0
                else "final completion count agrees"
            )
            if not view["coverage_complete"] or not known["coverage_complete"]:
                conclusion = "Incomplete coverage — error unavailable"
            errors = (
                f"MAE forecast/replay {forecast_error:.2f}/{replay_error:.2f} Jobs"
                if forecast_error is not None and replay_error is not None
                else "MAE unavailable"
            )
            panel(
                axis,
                f"Cutoff {item['cutoff_index'] + 1}: {conclusion}\n"
                f"{errors}; "
                f"{item['diagnostics']['observed_censored_uids']} censored",
                "Seconds after forecast / model start",
                "Completed cohort Jobs",
            )
            axis.set(xlim=(0, 120), ylim=(0, max(1, maximum * 1.08)), xticks=[0, 30, 60, 90, 120])
            axis.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
        for axis in list(axes.flat)[len(subset) :]:
            axis.set_visible(False)
        handles, labels = axes[0, 0].get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="center",
            bbox_to_anchor=(0.53, 0.12),
            ncol=3,
            frameon=False,
            fontsize=9,
        )
        diagnostics = [p["diagnostics"] for p in subset]
        incomplete = sum(d["membership_complete"] is not True for d in diagnostics)
        counts = "/".join(str(p["forecast"]["observed_curve"][-1]) for p in subset)
        finish(
            pdf,
            figure,
            f"Observed completions: {counts}. Incomplete membership: {incomplete} cutoffs; "
            f"exhausted/unmatched/unknown: "
            f"{sum(d['model_exhausted'] for d in diagnostics)}/"
            f"{sum(d['unmatched_observed_backlog'] for d in diagnostics)}/"
            f"{sum(d['unknown_outcome_uids'] for d in diagnostics)}. "
            "\n"
            "Cohort = backlog + next 60 s of arrivals; follow-up = 120 s. "
            f"Ranges describe {subset[0]['scenarios']} sampled futures, not confidence intervals.",
        )
