"""Scheduling alignment and arrival-knowledge diagnostics beside physical loop outcomes."""

import numpy as np
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator

from reporting.layout import BLUE, GREEN, ORANGE, finish, page, panel
from reporting.closed_loop import _table_page

VARIANTS = ("original", "backoff1", "fifo-profile", "fifo-occupancy")
LABELS = ("Original", "Backoff 1 s", "FIFO", "FIFO +\noccupancy")


def ranking_coverage(run):
    """Retain missing prescribed cutoffs when diagnostic execution stopped partway through.

    Args:
        run (dict): Saved diagnostic rows and optional explicit prescribed tick inventory.

    Returns:
        dict: Missing identities and total unavailable prescribed cutoffs.

    Raises:
        ValueError: Duplicate or unplanned cutoffs would change the declared study.
    """
    expected = set(run.get("expected_ticks", [1, 4, 7, 10]))
    actual = [row["tick"] for row in run["comparisons"]]
    if len(set(actual)) != len(actual) or not set(actual) <= expected:
        raise ValueError("ranking rows contain duplicate or unplanned cutoffs")
    missing = sorted(expected - set(actual))
    return dict(
        missing_ticks=missing,
        unavailable=len(missing) + sum(bool(row.get("excluded")) for row in run["comparisons"]),
    )


def ranking_agreement(runs, variant):
    """Average agreement within each independent run before averaging across runs.

    Args:
        runs (list[dict]): Independent workload runs with their chronological diagnostics.
        variant (str): Alternate sampled future or retrospective known-arrival ranking key.

    Returns:
        dict: Per-run agreement fractions, scored cutoff counts and equal-run mean.
    """
    fractions, counts, seeds = [], [], []
    for run in runs:
        rows = [
            row
            for row in run["comparisons"]
            if not row.get("excluded")
            and row.get("primary", {}).get("preferred") is not None
            and row.get(variant, {}).get("preferred") is not None
        ]
        if rows:
            fractions.append(
                sum(row["primary"]["preferred"] == row[variant]["preferred"] for row in rows)
                / len(rows)
            )
            counts.append(len(rows))
            seeds.append(run["seed"])
    return dict(
        seeds=seeds,
        run_fractions=fractions,
        scored_cutoffs=counts,
        mean_run_fraction=float(np.mean(fractions)) if fractions else None,
    )


def timeline_segments(row, cutoff):
    """Recover matched classifier and resource-release intervals from saved replay metrics.

    Args:
        row (dict): One matched future Job with original creation and native completion metrics.
        cutoff (int): Causal replay cutoff in epoch milliseconds.

    Returns:
        dict: Creation/start/classifier-finish/release seconds relative to the cutoff.
    """
    observed = row["observed"]
    predicted_finish = row["predicted_finish_ms"]
    predicted_start = predicted_finish - row["modeled_duration_seconds"] * 1000
    return dict(
        uid=row["uid"],
        observed=[
            (value - cutoff) / 1000
            for value in (
                row["original_creation_ms"],
                observed["start_ms"],
                observed["finish_ms"],
                observed["job_finish_ms"],
            )
        ],
        predicted=[
            (value - cutoff) / 1000
            for value in (
                row["original_creation_ms"],
                predicted_start,
                predicted_finish,
                row.get("predicted_resource_release_ms", predicted_finish),
            )
        ],
    )


def _scheduling_summary(pdf, study):
    """Compare each seed's scheduling errors and common-window physical completion counts.

    Args:
        pdf (PdfPages): Open report destination.
        study (dict): Saved scheduler-arm summaries and common physical end counts.
    """
    figure, axes = page(
        "Scheduling alignment: matched workload seeds",
        "FIFO plus causal occupancy improves per-Job timing; "
        "ordering alone explains only part of the gain.",
    )
    rows = study["runs"]
    for index, seed in enumerate(sorted({row["seed"] for row in rows})):
        selected = {row["variant"]: row for row in rows if row["seed"] == seed}
        for axis, metric in zip(axes[0], ("start_mae_seconds", "start_absolute_p95_seconds")):
            axis.plot(
                range(4),
                [selected[key][metric] for key in VARIANTS],
                marker="o",
                label=f"Seed {seed}",
                color=(BLUE, ORANGE)[index % 2],
            )
            axis.set_xticks(range(4), LABELS)
        axes[1, 0].plot(
            range(3),
            [selected[key]["completed_at_arrival_end"] for key in VARIANTS[:3]],
            marker="o",
            label=f"Seed {seed}",
            color=(BLUE, ORANGE)[index % 2],
        )
        axes[1, 1].plot(
            range(4),
            [selected[key]["jobs_waiting_at_least_5_seconds"] for key in VARIANTS],
            marker="o",
            label=f"Seed {seed}",
            color=(BLUE, ORANGE)[index % 2],
        )
    axes[0, 0].axhline(5, color="black", linestyle="--", linewidth=1)
    axes[0, 1].axhline(15, color="black", linestyle="--", linewidth=1)
    for axis in axes[0]:
        axis.set_ylim(bottom=0)
    axes[1, 1].axhline(20, color="black", linestyle="--", linewidth=1)
    axes[1, 0].set_xticks(range(3), LABELS[:3])
    axes[1, 1].set_xticks(range(4), LABELS)
    for axis in axes[1]:
        axis.set_ylim(bottom=0)
        axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    panel(
        axes[0, 0],
        "Both final runs meet the 5 s mean-error target",
        "",
        "Absolute start error: mean (s)",
    )
    panel(
        axes[0, 1],
        "Both final runs meet the 15 s tail-error target",
        "",
        "Absolute start error: p95 (s)",
    )
    panel(
        axes[1, 0],
        "Common-end throughput stays within the 5% tolerance",
        "",
        "Jobs completed by arrival end",
    )
    panel(
        axes[1, 1],
        "Each run supplies substantial queue contention",
        "",
        "Jobs waiting at least 5 s",
    )
    figure.legend(
        *axes[0, 0].get_legend_handles_labels(),
        loc="center",
        bbox_to_anchor=(0.53, 0.85),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    finish(
        pdf,
        figure,
        "Selection seeds 52/53; four cutoffs per run, H120 competing arrivals, "
        "first 60 s future cohort scored through E120.\n"
        "FIFO and FIFO + occupancy reuse the same physical capture; "
        "only their modeled lifecycle differs.\n"
        "Two accepting workers, six modeled slots. "
        "Common-end counts include the complete arrival period.",
    )


def _timeline(axis, example):
    """Draw paired actual/predicted lifecycle bars for identical within-arm Job UIDs.

    Args:
        axis (Axes): Timeline destination.
        example (dict): Explicit chronological subset and cutoff-relative lifecycle segments.
    """
    for index, row in enumerate(example["rows"]):
        for key, offset, hatch in (("observed", -0.2, None), ("predicted", 0.2, "///")):
            boundaries = row[key]
            for start, end, color in zip(boundaries, boundaries[1:], ("0.72", BLUE, ORANGE)):
                axis.barh(
                    index + offset,
                    max(0, end - start),
                    left=start,
                    height=0.35,
                    color=color,
                    hatch=hatch,
                    edgecolor="white",
                    linewidth=0.3,
                )
    axis.set_ylim(len(example["rows"]) - 0.5, -0.5)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    panel(axis, example["label"], "Seconds after replay cutoff", "Jobs in creation order")


def _lifecycle_page(pdf, study):
    """Separate runtime/startup/release diagnostics and retain detailed matched Job timelines.

    Args:
        pdf (PdfPages): Open report destination.
        study (dict): Frozen scheduling summaries and representative paired timelines.
    """
    figure, axes = page(
        "Lifecycle fidelity: where prediction differs",
        "Runtime, startup and release are separate quantities; "
        "matched timelines expose Job-level error.",
    )
    for seed_index, seed in enumerate(sorted({row["seed"] for row in study["runs"]})):
        selected = {row["variant"]: row for row in study["runs"] if row["seed"] == seed}
        axes[0, 0].plot(
            range(4),
            [selected[key]["future_runtime_mae_seconds"] for key in VARIANTS],
            marker="o",
            color=(BLUE, ORANGE)[seed_index % 2],
            label=f"Seed {seed}",
        )
        axes[0, 1].plot(
            range(4),
            [selected[key]["observed_release_median_seconds"] for key in VARIANTS],
            marker="o",
            color=(BLUE, ORANGE)[seed_index % 2],
            label=f"Seed {seed}",
        )
    for axis in axes[0]:
        axis.set_xticks(range(4), LABELS)
        axis.set_ylim(bottom=0)
    panel(
        axes[0, 0],
        "Classifier-duration error is distinct from waiting",
        "",
        "Future runtime absolute error: mean (s)",
    )
    panel(
        axes[0, 1],
        "Successful Job status follows classifier finish",
        "",
        "Observed release proxy: median (s)",
    )
    examples = study["timeline_examples"]
    xmax = max(
        (
            value
            for item in examples
            for row in item["rows"]
            for key in ("observed", "predicted")
            for value in row[key]
        ),
        default=120,
    )
    for axis, example in zip(axes[1], examples):
        _timeline(axis, example)
        axis.set_xlim(0, xmax * 1.02)
    figure.legend(
        *axes[0, 0].get_legend_handles_labels(),
        loc="center",
        bbox_to_anchor=(0.53, 0.85),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    figure.legend(
        handles=[
            Patch(facecolor="0.72", label="Waiting"),
            Patch(facecolor=BLUE, label="Classifier"),
            Patch(facecolor=ORANGE, label="Release"),
            Patch(facecolor="white", edgecolor="0.3", hatch="///", label="Predicted"),
        ],
        loc="center",
        bbox_to_anchor=(0.53, 0.115),
        ncol=4,
        frameon=False,
        fontsize=8,
    )
    startup = "; ".join(
        f"seed {row['seed']}: {row['occupancy_calibration']['startup_ms']/1000:.3f} s"
        for row in study["runs"]
        if row["variant"] == "fifo-occupancy" and row.get("occupancy_calibration")
    )
    finish(
        pdf,
        figure,
        "Timelines: seed 52, second chronological cutoff, up to 12 matched future Jobs. "
        "Each solid/hatched pair is the same Job UID.\n"
        f"Frozen startup estimate, a first-observed-assignment lower bound: {startup}.\n"
        "Observed release is a status proxy, not an exact kernel timestamp; "
        "original replay omits explicit release occupancy.",
    )


def _ranking_page(pdf, runs):
    """Show independent-run agreement without treating oracle preference as a live policy action.

    Args:
        pdf (PdfPages): Open report destination.
        runs (list[dict]): Predeclared chronological cutoff comparisons for held-out seeds.
    """
    figure, axes = page(
        "Forecast usefulness: sensitivity of objective rankings",
        "Changing sampled futures or supplying later-known arrivals tests ranking stability, "
        "not physical benefit.",
    )
    summaries = [ranking_agreement(runs, key) for key in ("alternate", "known_arrival")]
    for index, summary in enumerate(summaries):
        values = [100 * value for value in summary["run_fractions"]]
        axes[0, 0].scatter([index] * len(values), values, color=(BLUE, ORANGE)[index], s=35)
        if values:
            axes[0, 0].scatter(
                index, 100 * summary["mean_run_fraction"], marker="_", s=250, color="black"
            )
    axes[0, 0].set_xticks([0, 1], ["Alternate seed", "Known arrivals"])
    axes[0, 0].set_ylim(0, 105)
    panel(
        axes[0, 0],
        "Agreement is averaged within run, then across runs",
        "",
        "Same preferred candidate (%)",
    )
    names = ("unchanged", "scale-up", "scale-down")
    points = [
        (run["seed"], row) for run in runs for row in run["comparisons"] if not row.get("excluded")
    ]
    for offset, variant, color in (
        (-0.2, "primary", BLUE),
        (0, "alternate", ORANGE),
        (0.2, "known_arrival", GREEN),
    ):
        axes[0, 1].scatter(
            [i + offset for i, (_, row) in enumerate(points) if row[variant]["preferred"] in names],
            [
                names.index(row[variant]["preferred"])
                for _, row in points
                if row[variant]["preferred"] in names
            ],
            color=color,
            label=variant.replace("_", " "),
            s=24,
        )
    axes[0, 1].set_xticks(
        range(len(points)), [f"{seed}/{row['tick']}" for seed, row in points], rotation=45
    )
    axes[0, 1].set_yticks(range(3), ["Hold", "Up", "Down"])
    panel(
        axes[0, 1],
        "Original action eligibility is preserved in every variant",
        "Seed / cycle",
        "Objective preference",
    )
    for axis, key in zip(axes[1], ("alternate", "known_arrival")):
        changes = []
        for _, row in points:
            primary = {
                value["candidate"]: value for value in row["primary"]["scores"] if value["valid"]
            }
            variant = {value["candidate"]: value for value in row[key]["scores"] if value["valid"]}
            changes.append(
                max(
                    (
                        abs(variant[name]["worst_late_fraction"] - value["worst_late_fraction"])
                        for name, value in primary.items()
                        if name in variant
                    ),
                    default=0,
                )
            )
        axis.bar(
            range(len(points)),
            [100 * value for value in changes],
            color=ORANGE if key == "alternate" else GREEN,
        )
        axis.set_xticks(
            range(len(points)), [f"{seed}/{row['tick']}" for seed, row in points], rotation=45
        )
        panel(
            axis,
            key.replace("_", " ").capitalize() + ": response-feasibility sensitivity",
            "Seed / cycle",
            "Largest change in late fraction (pp)",
        )
    figure.legend(
        *axes[0, 1].get_legend_handles_labels(),
        loc="center",
        bbox_to_anchor=(0.53, 0.85),
        ncol=3,
        frameon=False,
        fontsize=9,
    )
    excluded = sum(ranking_coverage(run)["unavailable"] for run in runs)
    finish(
        pdf,
        figure,
        f"Predeclared cycles 1/4/7/10; {excluded} excluded cutoffs, never replaced. "
        "Dots are independent runs; black marks are equal-run means.\n"
        "Rankings precede hysteresis, minimum savings, cooldown and physical guards. "
        "They are not policy actions or policy regret.\n"
        "Known arrivals retain causal profiles/backlog and finite H60; "
        "only matched physical arms can establish benefit.",
    )


def render_pages(pdf, supplement):
    """Append available scheduling and ranking topics without importing historical study results.

    Args:
        pdf (PdfPages): Open combined report destination.
        supplement (dict): Self-contained supplementary numerical evidence.

    Returns:
        list[str]: Topic names actually rendered.
    """
    sections = []
    scheduling = supplement.get("closed_loop_scheduling")
    if scheduling:
        _scheduling_summary(pdf, scheduling)
        _lifecycle_page(pdf, scheduling)
        sections.append("closed-loop-scheduling-alignment")
    rankings = supplement.get("closed_loop_rankings", [])
    if rankings:
        _ranking_page(pdf, rankings)
        sections.append("closed-loop-ranking-diagnostics")
    return sections


def render_safety(pdf, supplement):
    """Keep safety findings and incomplete coverage in the validation section.

    Args:
        pdf (PdfPages): Open combined report destination.
        supplement (dict): Frozen per-capture audit payloads.

    Returns:
        bool: Whether a safety page was rendered.
    """
    audits = supplement.get("closed_loop_safety", [])
    if not audits:
        return False
    rows = []
    for audit in audits:
        journal, inventory, states = (audit[key] for key in ("journal", "inventory", "states"))
        missing = set(inventory["missing_final_pod_job_uids"])
        missing.update(inventory["unmatched_application_pods"])
        missing.update(audit["observed_pods_missing_from_final_inventory"])
        rows.append(
            [
                f"{audit['seed']} / {audit['arm']}",
                str(inventory["jobs"]),
                str(journal["request_count"]),
                "found" if audit["observed_violations"] else "none found",
                str(len(missing)),
                str(len(states["uncertain_binding_job_uids"])),
                f"{states['invalid_snapshots']} / {states['snapshots']}",
                str(
                    len(
                        set(journal["uncertain_action_ids"])
                        | set(journal["unresolved_action_ids"])
                        | set(journal["missing_proposal_action_ids"])
                    )
                ),
            ]
        )
    for offset in range(0, len(rows), 14):
        _table_page(
            pdf,
            "Observed safety and evidence coverage",
            "No observed violation is weaker than proof of no unseen event; "
            "incomplete intervals remain explicit.",
            [
                "Seed / arm",
                "Jobs",
                "Intents",
                "Observed issues",
                "Missing inventory",
                "Uncertain bindings",
                "Invalid snapshots",
                "API / intent unclear",
            ],
            rows[offset : offset + 14],
            "Audits cover the whole capture, including warm-up; "
            "pilot seeds 60/61 remain selection evidence.\n"
            "Intents include requests later vetoed before dispatch. "
            "Missing inventories and binding gaps are inconclusive.\n"
            "No Kubernetes Events/API audit log; "
            "host/observer mutation timing has no measured clock-offset bound.",
        )
    return True
