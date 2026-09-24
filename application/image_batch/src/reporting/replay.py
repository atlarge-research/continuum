"""Direct, cohort-checked comparisons of unchanged known-arrival replay."""
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from reporting.layout import finish, page as report_page


def replay_panels(entries, window="120"):
    """Pair explicit engine labels on identical physical runs, cutoffs and cohorts.

    Args:
        entries (list[dict]): Labeled saved observation-validation results.
        window (str): Evaluation-window key, normally 60 or 120 seconds.

    Returns:
        list[dict]: Chronological panels with explicit unavailable engine members.

    Raises:
        ValueError: Labels, case identities, observed cohorts or curves disagree.
    """
    panels, labels = {}, {}
    for entry in entries:
        result, label = entry["result"], entry["label"]
        run = result["run_id"]
        if label in labels.setdefault(run, []):
            raise ValueError("duplicate replay engine label for one run")
        labels[run].append(label)
        for group in result["groups"]:
            if group["arrival_source"] != "known-arrival":
                continue
            key = (run, group["cutoff_ms"], group["horizon_seconds"], group["seed"])
            cases = [
                case
                for case in result["cases"]
                if case["arrival_source"] == "known-arrival"
                and (case["cutoff_index"], case["horizon_seconds"], case["seed"])
                == (group["cutoff_index"], group["horizon_seconds"], group["seed"])
            ]
            if len(cases) != 1 or group["scenarios"] != 1:
                raise ValueError("known-arrival replay requires exactly one case per engine/cutoff")
            comparison = cases[0]["comparisons"][window]
            observed = {row["uid"]: row for row in comparison["observations"]}
            if len(observed) != len(comparison["observations"]):
                raise ValueError("duplicate observed cohort identity")
            view = group["windows"][window]
            panel = panels.setdefault(
                key,
                {
                    "run_id": run,
                    "cutoff_ms": group["cutoff_ms"],
                    "cutoff_index": group["cutoff_index"],
                    "horizon_seconds": group["horizon_seconds"],
                    "seed": group["seed"],
                    "window_seconds": int(window),
                    "members": [],
                    "observations": observed,
                    "grid_seconds": view["grid_seconds"],
                    "observed_curve": view["observed_curve"],
                },
            )
            if (
                panel["observations"] != observed
                or panel["grid_seconds"] != view["grid_seconds"]
                or panel["observed_curve"] != view["observed_curve"]
            ):
                raise ValueError("replay engine members have different observed cohort or curve")
            if any(member["label"] == label for member in panel["members"]):
                raise ValueError("duplicate replay case for engine and cutoff")
            panel["members"].append({"label": label, "group": group, "comparison": comparison})
    output = []
    run_order = {run: index for index, run in enumerate(labels)}
    for key in sorted(panels, key=lambda value: (run_order[value[0]], *value[1:])):
        panel = panels[key]
        present = {member["label"] for member in panel["members"]}
        panel["unavailable_labels"] = [
            label for label in labels[panel["run_id"]] if label not in present
        ]
        output.append(panel)
    return output


def render_replay_pages(pdf, entries, window="120"):
    """Render shared-scale completion panels and explicit initialization diagnostics.

    Args:
        pdf (PdfPages): Open combined-report writer.
        entries (list[dict]): Explicitly labeled replay results with full numerical evidence.
        window (str): Scored follow-up window, without enlarging the arrival cohort.

    Returns:
        list[dict]: Exact matched panels and diagnostics used for rendering.
    """
    panels = replay_panels(entries, window)
    names = list(dict.fromkeys(entry["label"] for entry in entries))
    colors = {name: plt.get_cmap("tab10")(index % 10) for index, name in enumerate(names)}
    for run in dict.fromkeys(panel["run_id"] for panel in panels):
        selected = [panel for panel in panels if panel["run_id"] == run]
        maximum = max(
            [1]
            + [
                max(series)
                for panel in selected
                for series in [panel["observed_curve"]]
                + [m["group"]["windows"][window]["completion_median"] for m in panel["members"]]
            ]
        )
        for start in range(0, len(selected), 4):
            page = selected[start : start + 4]
            figure, axes = report_page(
                "Unchanged replay | completions",
                "Engine predictions share the same observed cohort; all cutoffs use "
                "common count and time scales.",
            )
            figure.text(0.08, 0.865, run, fontsize=8)
            revisions = [
                f"{entry['label']}: {entry['engine_revision'][:12]}"
                for entry in entries
                if entry["result"]["run_id"] == run and entry.get("engine_revision")
            ]
            if revisions:
                figure.text(0.08, 0.84, "; ".join(revisions), fontsize=8)
            for axis, panel in zip(axes.flat, page):
                axis.step(
                    panel["grid_seconds"],
                    panel["observed_curve"],
                    where="post",
                    color="black",
                    linewidth=2.5,
                    label="Observed classifier completions",
                )
                for member in panel["members"]:
                    view = member["group"]["windows"][window]
                    axis.step(
                        panel["grid_seconds"],
                        view["completion_median"],
                        where="post",
                        color=colors[member["label"]],
                        linestyle=("--", ":", "-.")[names.index(member["label"]) % 3],
                        label=member["label"],
                    )
                covered = all(
                    m["group"]["windows"][window]["coverage_complete"] for m in panel["members"]
                )
                axis.set(
                    title=f"Cutoff {panel['cutoff_index']} | H{panel['horizon_seconds']}, E{window}"
                    + ("" if covered else " | incomplete coverage")
                    + (
                        "\nUnavailable: " + ", ".join(panel["unavailable_labels"])
                        if panel["unavailable_labels"]
                        else ""
                    ),
                    xlabel="Seconds after cutoff",
                    ylabel="Completed cohort Jobs",
                    xlim=(0, int(window)),
                    ylim=(0, maximum * 1.05),
                )
                axis.yaxis.set_major_locator(MaxNLocator(integer=True))
                axis.grid(alpha=0.2)
            for axis in list(axes.flat)[len(page) :]:
                axis.set_visible(False)
            legend = {}
            for axis in axes.flat:
                handles, labels = axis.get_legend_handles_labels()
                legend.update(zip(labels, handles))
            figure.legend(
                legend.values(),
                legend.keys(),
                loc="lower center",
                bbox_to_anchor=(0.5, 0.105),
                ncol=4,
                frameon=False,
                fontsize=8,
            )
            finish(
                pdf,
                figure,
                "Same represented backlog and arrival cohort; original creation times retained.\n"
                "Placement restoration does not imply improved completion accuracy "
                "or validate scaling.",
            )
        _diagnostic_page(pdf, run, selected, names, colors)
    return panels


def _diagnostic_page(pdf, run, panels, names, colors):
    """Show placement and timing evidence alongside missing-state counts.

    Args:
        pdf (PdfPages): Open report writer.
        run (str): Physical capture identity.
        panels (list[dict]): Matched cutoff evidence for this run.
        names (list[str]): Engine labels in stable display order.
        colors (dict): Shared label-to-color mapping.
    """
    figure, axes = report_page(
        "Replay diagnostics | placement and completion",
        "Placement and matched response times describe different aspects of initialization.",
        rows=1,
        columns=2,
    )
    axes = axes[0]
    figure.subplots_adjust(bottom=0.35)
    figure.text(0.08, 0.865, run, fontsize=8)
    annotations, maximum, placement_maximum = [], 1, 1
    for index, label in enumerate(names):
        members = [m for p in panels for m in p["members"] if m["label"] == label]
        if not members:
            continue
        rows = [row for m in members for row in m["comparison"].get("tasks", [])]
        assigned = [
            row
            for row in rows
            if row.get("phase") in ("running", "startup")
            and row.get("placement_changed") is not None
        ]
        changed = sum(row["placement_changed"] for row in assigned)
        placement_maximum = max(placement_maximum, changed + 1)
        axes[0].bar(index, changed, color=colors[label])
        axes[0].text(index, changed + 0.2, f"{changed}/{len(assigned)}", ha="center", fontsize=9)
        matched = [
            row
            for row in rows
            if row.get("observed_response_seconds") is not None
            and row.get("predicted_response_seconds") is not None
        ]
        actual = [row["observed_response_seconds"] for row in matched]
        predicted = [row["predicted_response_seconds"] for row in matched]
        maximum = max([maximum] + actual + predicted)
        axes[1].scatter(actual, predicted, s=14, alpha=0.7, color=colors[label], label=label)
        comparisons = [m["comparison"] for m in members]
        missing = sum(
            not (c.get("initial_membership") or {}).get("complete", False) for c in comparisons
        )
        exhausted = sum(len(c.get("model_exhausted", [])) for c in comparisons)
        unmatched = sum(len(c.get("unmatched_observed_backlog", [])) for c in comparisons)
        censored = sum(len(c.get("observed_censored_uids", [])) for c in comparisons)
        unknown = sum(len(c.get("unknown_outcome_uids", [])) for c in comparisons)
        annotations.append(
            f"{label}: membership incomplete {missing}/{len(comparisons)} cutoffs; "
            f"exhausted {exhausted}, unmatched backlog {unmatched}, "
            f"censored {censored}, unknown {unknown}."
        )
    axes[0].set(
        xticks=range(len(names)),
        xticklabels=names,
        ylabel="Changed initial placements",
        title="Assigned Job–cutoff pairs",
        ylim=(0, placement_maximum),
    )
    axes[0].tick_params(axis="x", labelrotation=15, labelsize=8)
    axes[0].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[1].plot([0, maximum], [0, maximum], color="black", linestyle=":", label="Exact agreement")
    axes[1].set(
        xlim=(0, maximum * 1.05),
        ylim=(0, maximum * 1.05),
        xlabel="Observed creation → classifier finish (s)",
        ylabel="Predicted response (s)",
        title="Matched Job responses",
    )
    figure.legend(
        *axes[1].get_legend_handles_labels(),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.24),
        ncol=4,
        frameon=False,
        fontsize=8,
    )
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.text(0.08, 0.18, "\n".join(annotations), fontsize=8, linespacing=1.5)
    finish(
        pdf,
        figure,
        "Counts are dependent Job–cutoff pairs. Missing and exhausted work is not zero work.\n"
        "Response points require observed and predicted finish times; JSON retains "
        "all other outcomes.",
    )
