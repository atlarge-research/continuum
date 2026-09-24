"""Physical workload fidelity and scheduling delays across independent runs."""
import statistics

from matplotlib.ticker import MaxNLocator

from reporting.layout import BLUE, ORANGE, GREEN, COLORS, page, panel, finish
from reporting.measured import _covered_series


def _ecdf(axis, values, label, color):
    """Draw a within-run empirical distribution without pooling independent runs.

    Args:
        axis (Axes): Destination panel.
        values (list[float]): Available measured durations.
        label (str): Run or interval identity.
        color (str): Plot color.
    """
    values = sorted(value for value in values if value is not None)
    if values:
        axis.step(
            [values[0]] + values,
            [0] + [100 * (i + 1) / len(values) for i in range(len(values))],
            where="post",
            label=label,
            color=color,
        )
    axis.set_ylim(0, 102)
    axis.set_xlim(0, max(axis.get_xlim()[1], max(values, default=0) * 1.05))


def _run_label(run, roles):
    """Name a physical workload without inventing a random seed.

    Args:
        run (dict): Saved analyzed measurement.
        roles (dict): Explicit workload identities.

    Returns:
        str: Seed label when known, otherwise the run identity.
    """
    identity = run["summary"]["run_id"]
    seed = roles[identity]["workload_seed"]
    return f"seed {seed}" if seed is not None else f"run {identity}"


def render_physical(pdf, measured, roles, supplement):
    """Show per-run fidelity and distributions, retaining one actual cluster timeline.

    Args:
        pdf (PdfPages): Open report writer.
        measured (list[dict]): Full saved physical measurements.
        roles (dict): Explicit workload seeds and study roles.
        supplement (dict): Optional per-Job scheduling timestamp decomposition.
    """
    runs = sorted(
        (run for saved in measured for run in saved["runs"]), key=lambda run: run["origin"]
    )
    example = runs[0]
    example_label = _run_label(example, roles)
    lags = [r["summary"]["fidelity"]["lag_ms"]["max"] for r in runs]
    maximum_lag = max((value for value in lags if value is not None), default=None)
    lag_text = f"{maximum_lag:.1f} ms" if maximum_lag is not None else "unavailable"
    study_context = all(roles[r["summary"]["run_id"]]["split"] != "unassigned" for r in runs)
    total = sum(r["summary"]["completed_jobs"] for r in runs)
    figure, axes = page(
        "Physical execution | workload delivery and cluster pressure",
        f"{total} Jobs completed across {len(runs)} runs; maximum HTTP start lag "
        f"{lag_text}. Cluster pressure varies with arrivals.",
    )
    for index, run in enumerate(runs):
        label = _run_label(run, roles).capitalize()
        _ecdf(axes[0, 0], [r["lag_ms"] for r in run["arrivals"]], label, COLORS[index % 3])
        _ecdf(
            axes[0, 1],
            [
                j["completed"] - j["finish"]
                for j in run["jobs"]
                if j.get("completed") is not None and j.get("finish") is not None
            ],
            label,
            COLORS[index % 3],
        )
    panel(
        axes[0, 0],
        "HTTP starts closely follow planned times"
        if all(r["summary"]["fidelity"].get("fidelity_passed") is True for r in runs)
        else "Compare HTTP starts with planned times",
        "HTTP start − planned start (ms)",
        "Requests at or below delay (%)",
    )
    panel(
        axes[0, 1],
        "Job completion status follows execution",
        "Job Complete − classifier finish (s)",
        "Jobs at or below delay (%)",
    )
    pressure = example["pressure"]
    categories = (
        ("unassigned_jobs", "Waiting for assignment", ORANGE),
        ("snapshot_running_jobs", "Running", GREEN),
        ("startup_jobs", "Assigned, starting", BLUE),
    )
    if not any("unassigned_jobs" in point for point in pressure):
        categories = (
            ("queued_jobs", "Queued", ORANGE),
            ("active_jobs", "Active incl. startup", GREEN),
        )
    for key, label, color in categories:
        axes[1, 0].step(*_covered_series(pressure, key), where="post", label=label, color=color)
    for key, label, color, style in (
        ("active_requested_cpu", "Requested", BLUE, "--"),
        ("modeled_admission_cpu", "Application capacity", "0.3", ":"),
    ):
        axes[1, 1].step(
            *_covered_series(pressure, key), where="post", label=label, color=color, linestyle=style
        )
    axes[1, 1].plot(
        *_covered_series(pressure, "observed_workload_cpu", True),
        color=GREEN,
        label="Measured (complete samples)",
        linewidth=1,
    )
    partial = [
        p
        for p in pressure
        if not p["cpu_coverage_complete"] and p.get("observed_workload_cpu") is not None
    ]
    axes[1, 1].scatter(
        [p["time_seconds"] for p in partial],
        [p["observed_workload_cpu"] for p in partial],
        s=5,
        color="0.5",
        marker="x",
        label="Partial sample sum",
    )
    for axis in axes[1]:
        axis.set_xlim(0, example["end_seconds"])
        axis.set_ylim(bottom=0)
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
        duration = (
            example["summary"]["schedule"]
            .get("profile", {})
            .get("duration_seconds", example["end_seconds"])
        )
        axis.set_xticks([duration * part / 4 for part in range(5)])
    panel(
        axes[1, 0],
        f"Arrival bursts create queues | example {example_label}"
        if study_context
        else f"Captured Job pressure | {example_label}",
        "Seconds from schedule start",
        "Jobs",
    )
    panel(
        axes[1, 1],
        "Requested capacity and measured CPU differ",
        "Seconds from schedule start",
        "Application CPU cores",
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="center",
        bbox_to_anchor=(0.53, 0.855),
        ncol=len(runs),
        frameon=False,
        fontsize=9,
    )
    for axis, location in zip(axes[1], (0.28, 0.77)):
        handles, labels = axis.get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="center",
            bbox_to_anchor=(location, 0.115),
            ncol=2,
            frameon=False,
            fontsize=8,
        )
    counts = "; ".join(
        f"{_run_label(r, roles)}: "
        f"{r['summary']['completed_jobs']} complete, "
        f"{r['summary']['unresolved_accepted_jobs']} unresolved, {len(r['gaps'])} state gaps"
        for r in runs
    )
    finish(
        pdf,
        figure,
        counts
        + (
            "\nSame workload settings, independent arrival seeds. "
            if study_context
            else "\nDistributions are per run; arrival plans are not aligned. "
        )
        + "CPU is workload CPU, not whole-machine utilization or power; gaps remain missing.",
    )
    _waiting_page(pdf, runs, roles, supplement)


def _waiting_page(pdf, runs, roles, supplement):
    """Separate scheduling, startup and execution; illustrate one unaveraged burst.

    Args:
        pdf (PdfPages): Open report writer.
        runs (list[dict]): Physical runs in chronological order.
        roles (dict): Explicit workload seeds.
        supplement (dict): Saved scheduling decomposition, when available.
    """
    study_context = all(roles[r["summary"]["run_id"]]["split"] != "unassigned" for r in runs)
    figure, axes = page(
        "Where time goes | waiting dominates the long delays"
        if study_context
        else "Where time goes | waiting and execution",
        "Compare each run's delay distribution; inspect an actual burst "
        "instead of averaging Job timelines.",
    )
    for index, run in enumerate(runs):
        label = _run_label(run, roles).capitalize()
        for axis, field in zip(axes[0], ("queue_seconds", "execution_seconds")):
            _ecdf(axis, [j.get(field) for j in run["jobs"]], label, COLORS[index % 3])
    panel(
        axes[0, 0],
        "A minority of Jobs wait much longer" if study_context else "Job waiting distribution",
        "Job creation → classifier start (s)",
        "Jobs at or below duration (%)",
    )
    panel(
        axes[0, 1],
        "Classifier execution is comparatively stable"
        if study_context
        else "Classifier execution distribution",
        "Classifier execution (s)",
        "Jobs at or below duration (%)",
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="center",
        bbox_to_anchor=(0.53, 0.855),
        ncol=len(runs),
        frameon=False,
        fontsize=9,
    )
    saved = supplement.get("scheduling", {})
    example = next(
        (run for run in runs if run["summary"]["run_id"] == saved.get("run_id")), runs[0]
    )
    example_label = _run_label(example, roles)
    for key, label, color in (
        ("pod_to_scheduled", "Pod → scheduled", ORANGE),
        ("scheduled_to_start", "Scheduled → execution", BLUE),
    ):
        _ecdf(axes[1, 0], [r["seconds"][key] for r in saved.get("rows", [])], label, color)
    if not saved:
        axes[1, 0].text(
            0.5,
            0.5,
            "Scheduling decomposition not supplied",
            ha="center",
            transform=axes[1, 0].transAxes,
        )
    panel(
        axes[1, 0],
        f"Long waits precede scheduling | {example_label}"
        if saved
        else "Scheduling timestamps unavailable",
        "Measured interval (s)",
        "Jobs at or below duration (%)",
    )
    period = (
        example["summary"]["schedule"]
        .get("profile", {})
        .get("period_seconds", example["end_seconds"])
    )
    origin = example["origin"]
    jobs = sorted(
        (
            j
            for j in example["jobs"]
            if j.get("submitted") is not None and 0 <= j["submitted"] - origin < period
        ),
        key=lambda j: j["submitted"],
    )
    for index, job in enumerate(jobs):
        created = job["submitted"] - origin
        start, end = job.get("start"), job.get("finish")
        wait_end = start - origin if start is not None else example["end_seconds"]
        axes[1, 1].barh(
            index, wait_end - created, left=created, height=1, color="0.7", edgecolor="none"
        )
        if start is not None:
            finish_at = end - origin if end is not None else example["end_seconds"]
            axes[1, 1].barh(
                index,
                finish_at - (start - origin),
                left=start - origin,
                height=1,
                color=BLUE,
                edgecolor="none",
            )
    axes[1, 1].set_ylim(len(jobs) - 0.5, -0.5)
    axes[1, 1].set_xlim(left=0)
    axes[1, 1].yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    panel(
        axes[1, 1],
        f"Waiting varies by Job | {example_label}, first window"
        if "period_seconds" not in example["summary"]["schedule"].get("profile", {})
        else f"Waiting varies by Job | {example_label}, first cycle",
        "Seconds from schedule start",
        "Jobs in creation order",
    )
    handles, labels = axes[1, 0].get_legend_handles_labels()
    figure.legend(
        handles, labels, loc="center", bbox_to_anchor=(0.3, 0.12), ncol=1, frameon=False, fontsize=8
    )
    figure.text(0.58, 0.12, "Gray: waiting + startup     Blue: execution", fontsize=9)
    delay_note = "Timestamp decomposition unavailable."
    if saved:
        startup = statistics.median(r["seconds"]["scheduled_to_start"] for r in saved["rows"])
        delay_note = (
            f"{example_label.capitalize()}: scheduling wait max "
            f"{max(r['seconds']['pod_to_scheduled'] for r in saved['rows']):.0f} s; "
            "scheduled → execution median "
            f"{startup:.0f} s. "
            "Timestamps have second-level resolution."
        )
    finish(
        pdf,
        figure,
        delay_note + "\nThe intervals locate the delay; they do not prove "
        "a scheduler backoff mechanism. "
        "First-cycle Jobs are shown through their captured outcomes.",
    )
