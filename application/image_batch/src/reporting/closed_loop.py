"""Real-cluster closed-loop outcomes from frozen, independently repeated evidence."""

import numpy as np

from reporting.layout import COLORS, finish, page, panel

SCHEMA = "opendc-closed-loop-evidence-v1"

ARMS = ("fixed", "reactive", "forecast")
LABELS = ("Fixed capacity", "Reactive", "Forecast loop")


def paired_savings(runs):
    """Pair accepted held-out arms only when their workload and resource windows match.

    Args:
        runs (list[dict]): Frozen physical run evidence, including explicit study roles.

    Returns:
        list[dict]: Per-seed conservative saving bounds relative to fixed capacity.

    Raises:
        ValueError: More than one accepted run claims the same held-out arm and seed.
    """
    accepted = {}
    for run in runs:
        if run["role"] != "heldout" or not run["accepted_capture"]:
            continue
        key = (run["seed"], run["arm"])
        if key in accepted:
            raise ValueError("Duplicate accepted held-out seed/arm; select attempts explicitly")
        accepted[key] = run
    pairs = []
    for (seed, arm), run in accepted.items():
        fixed = accepted.get((seed, "fixed"))
        if arm == "fixed" or fixed is None:
            continue
        boundaries = ("evaluation_start_seconds", "arrival_end_seconds")
        window = [run[key] - run["origin_seconds"] for key in boundaries]
        fixed_window = [fixed[key] - fixed["origin_seconds"] for key in boundaries]
        if (
            run["arrival_plan_sha256"] != fixed["arrival_plan_sha256"]
            or not np.allclose(window, fixed_window, rtol=0, atol=0.001)
            or run["admission"] != fixed["admission"]
            or run["config"] != fixed["config"]
            or run.get("comparison_settings") != fixed.get("comparison_settings")
        ):
            continue
        lower, upper = run["allocation"]["allocated_core_seconds_bounds"]
        fixed_lower, fixed_upper = fixed["allocation"]["allocated_core_seconds_bounds"]
        if fixed_lower <= 0 or fixed_upper <= 0:
            continue
        pairs.append(
            dict(
                seed=seed, arm=arm, saving_bounds=[1 - upper / fixed_lower, 1 - lower / fixed_upper]
            )
        )
    return pairs


def _independent_points(axis, values):
    """Draw individual run values and median/min-max without a confidence interpretation.

    Args:
        axis (Axes): Target panel.
        values (list[list[float]]): One list of independent run metrics per arm.
    """
    for index, group in enumerate(values):
        if not group:
            continue
        axis.scatter(np.full(len(group), index), group, color=COLORS[index], alpha=0.65, s=28)
        median = float(np.median(group))
        axis.errorbar(
            index,
            median,
            yerr=[[median - min(group)], [max(group) - median]],
            fmt="_",
            markersize=18,
            capsize=6,
            color="black",
            linewidth=1.3,
        )
    axis.set_xticks(range(3), LABELS)
    axis.set_xlim(-0.5, 2.5)


def _outcomes(pdf, runs, pairs):
    """Lead the PDF with per-run physical response and resource outcomes.

    Args:
        pdf (PdfPages): Open report destination.
        runs (list[dict]): Accepted held-out captures only.
        pairs (list[dict]): Verified matched-plan allocation comparisons.
    """
    title = "Closed loop: physical outcomes"
    takeaway = (
        "Independent runs measure response and allocated capacity; warm reserves remain powered."
        if runs
        else "Held-out comparisons are not yet available; pilot results appear in validation."
    )
    figure, axes = page(title, takeaway)
    groups = [[run for run in runs if run["arm"] == arm] for arm in ARMS]
    _independent_points(
        axes[0, 0],
        [
            [
                100 * r["responses"]["deadline_fraction"]
                for r in group
                if r["responses"]["deadline_fraction"] is not None
            ]
            for group in groups
        ],
    )
    for fraction in {r.get("invocation", {}).get("deadline_fraction", 0.95) for r in runs}:
        axes[0, 0].axhline(100 * fraction, color="black", linestyle="--", linewidth=1)
    axes[0, 0].set_ylim(0, 103)
    panel(
        axes[0, 0],
        "Failures and unfinished Jobs remain in the denominator",
        "",
        "Jobs within configured deadline (%)",
    )
    _independent_points(
        axes[0, 1],
        [
            [
                r["responses"]["completed_response_p95_seconds"]
                for r in group
                if r["responses"]["completed_response_p95_seconds"] is not None
            ]
            for group in groups
        ],
    )
    for deadline in {r.get("invocation", {}).get("deadline_seconds", 120) for r in runs}:
        axes[0, 1].axhline(deadline, color="black", linestyle="--", linewidth=1)
    axes[0, 1].set_ylim(bottom=0)
    panel(
        axes[0, 1],
        "Each point is one run's response-time quantile",
        "",
        "Completed Job response p95 (s)",
    )
    for index, arm in enumerate(ARMS):
        for pair in [item for item in pairs if item["arm"] == arm]:
            lower, upper = [100 * v for v in pair["saving_bounds"]]
            axes[1, 0].plot([index, index], [lower, upper], color=COLORS[index], linewidth=4)
            axes[1, 0].scatter(index, lower, color=COLORS[index], s=25)
    _independent_points(
        axes[1, 0],
        [[0] * len(groups[0])]
        + [[100 * p["saving_bounds"][0] for p in pairs if p["arm"] == arm] for arm in ARMS[1:]],
    )
    axes[1, 0].axhline(10, color="black", linestyle="--", linewidth=1)
    panel(
        axes[1, 0],
        "Paired savings retain uncertainty from observation gaps",
        "",
        "Allocated core-time saving vs fixed (%)",
    )
    counts = [sum(r["responses"]["completed"] for r in group) for group in groups]
    incomplete = [
        sum(
            len(r["responses"]["censored_uids"]) + len(r["responses"]["failed_uids"]) for r in group
        )
        for group in groups
    ]
    axes[1, 1].bar(range(3), counts, color=COLORS)
    axes[1, 1].bar(range(3), incomplete, bottom=counts, color="#999999", hatch="///")
    axes[1, 1].set_ylim(0, max(1, 1.1 * max(sum(pair) for pair in zip(counts, incomplete))))
    axes[1, 1].set_xticks(range(3), LABELS)
    panel(
        axes[1, 1],
        "Gray counts are failed or unfinished; totals are descriptive",
        "",
        "Evaluation Jobs across supplied runs",
    )
    finish(
        pdf,
        figure,
        "Dots: independent workload runs. Black bars: median and descriptive min–max, "
        "not confidence intervals.\n"
        "Savings use accepting + draining application core-time; bounded intervals "
        "never identify a cheaper partial total.\n"
        "Configured powered worker VMs remain available throughout. No physical energy "
        "saving is inferred.",
    )


def _timelines(pdf, runs):
    """Compare run-aligned capacity, queues, response distributions and cycle latency.

    Args:
        pdf (PdfPages): Open report destination.
        runs (list[dict]): Accepted held-out captures only.
    """
    if not runs:
        return
    figure, axes = page(
        "How capacity and response change during evaluation",
        "Shared axes align independent runs at the end of warm-up; shaded ranges are descriptive.",
    )
    horizon = min(r["arrival_end_seconds"] - r["evaluation_start_seconds"] for r in runs)
    grid = np.arange(0, horizon, 5)
    for index, arm in enumerate(ARMS):
        group = [r for r in runs if r["arm"] == arm]
        for column, field in enumerate(("allocated", "queue")):
            arrays = []
            for run in group:
                series = run["allocation"]["series"]
                times = np.array([p["time"] - run["evaluation_start_seconds"] for p in series])
                values = []
                for at in grid:
                    position = np.searchsorted(times, at, side="right") - 1
                    point = series[position] if position >= 0 else {}
                    known = point.get("valid") and at - times[position] <= 3
                    if field == "queue":
                        known = known and point.get("membership_complete", False)
                    value = point.get(field) if known else None
                    values.append(np.nan if value is None else value)
                arrays.append(values)
            if arrays:
                values = np.array(arrays)
                # Require all supplied runs at each plotted time to keep the denominator fixed.
                complete = np.all(np.isfinite(values), axis=0)
                center = np.where(complete, np.median(values, axis=0), np.nan)
                axes[0, column].plot(grid / 60, center, color=COLORS[index], label=LABELS[index])
                axes[0, column].fill_between(
                    grid / 60,
                    np.where(complete, np.min(values, axis=0), np.nan),
                    np.where(complete, np.max(values, axis=0), np.nan),
                    color=COLORS[index],
                    alpha=0.13,
                )
        quantiles = np.linspace(0, 1, 101)
        distributions = [
            np.quantile(r["responses"]["completed_responses_seconds"], quantiles)
            for r in group
            if r["responses"]["completed_responses_seconds"]
        ]
        if distributions:
            values = np.array(distributions)
            axes[1, 0].plot(np.median(values, axis=0), quantiles, color=COLORS[index])
            axes[1, 0].fill_betweenx(
                quantiles,
                np.min(values, axis=0),
                np.max(values, axis=0),
                color=COLORS[index],
                alpha=0.13,
            )
        for run in group:
            cycles = [c for c in run["controller"]["cycles"] if c.get("complete_native_eligible")]
            axes[1, 1].scatter(
                [(c["started_at"] - run["evaluation_start_seconds"]) / 60 for c in cycles],
                [c.get("decision_age_seconds", np.nan) for c in cycles],
                color=COLORS[index],
                s=14,
                alpha=0.65,
            )
    for deadline in {r.get("invocation", {}).get("deadline_seconds", 120) for r in runs}:
        axes[1, 0].axvline(deadline, color="black", linestyle="--", linewidth=1)
    for budget in {
        r.get("invocation", {}).get("decision_age_seconds", 30)
        for r in runs
        if r["arm"] == "forecast"
    }:
        axes[1, 1].axhline(budget, color="black", linestyle="--", linewidth=1)
    for axis in axes.flat:
        axis.set_ylim(bottom=0)
    axes[0, 0].legend(fontsize=8, loc="lower left")
    panel(
        axes[0, 0],
        "Allocation includes a cordoned worker until it drains",
        "Minutes after warm-up",
        "Allocated application cores",
    )
    panel(
        axes[0, 1],
        "Unassigned Jobs retain their original creation times",
        "Minutes after warm-up",
        "Queued Jobs",
    )
    panel(
        axes[1, 0],
        "Completed-response quantiles are summarized within each run",
        "Original-creation response (s)",
        "Completed Job quantile",
    )
    panel(
        axes[1, 1],
        "Dashed lines show the configured decision-age budgets",
        "Minutes after warm-up",
        "Decision age from forecast cutoff (s)",
    )
    finish(
        pdf,
        figure,
        "Capacity/queue lines: independent-run median; shading: min–max. Gaps are "
        "retained when any run lacks fresh data.\n"
        "Response curves exclude unfinished Jobs; the preceding page keeps them in "
        "the deadline denominator.\n"
        "Decision-age dots are repeated cycles within runs, not independent workload repetitions.",
    )


def render_pages(pdf, reports):
    """Render physical outcomes before validation while retaining pilot/held-out separation.

    Args:
        pdf (PdfPages): Open combined-report writer.
        reports (list[dict]): Frozen closed-loop evidence payloads.

    Returns:
        dict: Exact accepted-run, pairing and section inventory for offline redraw verification.
    """
    runs = [run for report in reports for run in report["runs"]]
    heldout = [run for run in runs if run["role"] == "heldout" and run["accepted_capture"]]
    pairs = paired_savings(runs)
    _outcomes(pdf, heldout, pairs)
    action_runs = [run for run in heldout if run["controller"].get("actions")]
    for run in action_runs:
        _action_evidence_page(pdf, run)
        _lifecycle_page(pdf, run)
    _timelines(pdf, heldout)
    diagnostic_runs = sorted(
        (run for run in heldout if run["arm"] == "forecast"), key=lambda run: run["seed"]
    )
    for run in diagnostic_runs:
        _forecast_observation_page(pdf, run)
    return dict(
        heldout_runs=len(heldout),
        pilot_runs=sum(r["role"] == "pilot" for r in runs),
        rejected_runs=[r["run_id"] for r in runs if not r["accepted_capture"]],
        action_runs=[run["run_id"] for run in action_runs],
        diagnostic_runs=[run["run_id"] for run in diagnostic_runs],
        pairs=pairs,
    )


def render_validation(pdf, reports):
    """Show actuation, cadence, capture acceptance and pilot scope after primary outcomes.

    Args:
        pdf (PdfPages): Open combined-report writer.
        reports (list[dict]): Frozen closed-loop evidence payloads.
    """
    runs = [run for report in reports for run in report["runs"]]
    figure, axes = page(
        "Closed-loop validation and study coverage",
        "Observed actions establish functionality; matched held-out outcomes establish benefit.",
        rows=1,
        columns=1,
    )
    axis = axes[0, 0]
    axis.axis("off")
    rows = []
    for run in runs:
        control = run["controller"]
        fraction = control.get(
            "within_budget_native_fraction", control.get("within30_native_fraction")
        )
        operation = run.get("controller_full_operation", control)
        rows.append(
            [
                f'{run["role"]} {run["seed"]}',
                run["arm"],
                "accepted" if run["accepted_capture"] else "REJECTED",
                str(control["observed_down"]),
                str(control["observed_up"]),
                str(control.get("lifecycles", {}).get("forecast_down_up_pairs", "—"))
                if run["arm"] == "forecast"
                else "n/a",
                str(control["longest_consecutive_valid_cycles"]),
                str(operation.get("observation_retries", 0)),
                str(operation.get("fallback_invocations", "—"))
                if run["arm"] == "forecast"
                else "n/a",
                (
                    f'{control.get("complete_native_cycles", 0)}/{len(control.get("cycles", []))}\n'
                    + ("—" if fraction is None else f"{100*fraction:.0f}%")
                )
                if run["arm"] == "forecast"
                else "n/a",
            ]
        )
    table = axis.table(
        cellText=rows,
        colLabels=[
            "Role / seed",
            "Arm",
            "Capture",
            "Down",
            "Up",
            "Forecast\npairs",
            "Valid\nstreak",
            "Retries*",
            "Fallbacks*",
            "Native done* /\nin budget",
        ],
        loc="upper center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2.2)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#dddddd")
        if row == 0:
            cell.set_facecolor("#eeeeee")
    finish(
        pdf,
        figure,
        "Down/up require acknowledged actions confirmed by a later observer snapshot. "
        "Unconfirmed actions or skipped/invalid cycles break a streak.\n"
        "Pilots provide implementation/functional evidence, separate from held-out "
        "benefit summaries. Rejected attempts remain archived.\n"
        "*Retries and fallback include controlled follow-up. One rejected incomplete prefix "
        "may be recollected; both attempts remain archived.\n"
        "*Native done: complete/evaluated cycles; timing percentage uses complete cases only. "
        "Warm reserves stay powered; C−1 is applied once.",
    )

    _configuration_page(pdf, runs)


def _metric(value, digits=1):
    """Format a measured scalar while leaving absent evidence explicit.

    Args:
        value (float or None): Saved metric.
        digits (int): Decimal precision appropriate to the displayed unit.

    Returns:
        str: Compact measured value or an unavailable marker.
    """
    return "—" if value is None else f"{value:.{digits}f}"


def _table_page(pdf, title, takeaway, columns, rows, note):
    """Render a compact evidence table with the shared landscape layout.

    Args:
        pdf (PdfPages): Open report destination.
        title (str): Page heading.
        takeaway (str): Interpretation sentence.
        columns (list[str]): Column labels with units.
        rows (list[list[str]]): One explicitly identified run per row.
        note (str): Scope and missing-evidence explanation.
    """
    figure, axes = page(title, takeaway, rows=1, columns=1)
    axis = axes[0, 0]
    axis.axis("off")
    table = axis.table(
        cellText=rows,
        colLabels=columns,
        loc="upper center",
        cellLoc="center",
        colWidths=[0.22] + [0.78 / (len(columns) - 1)] * (len(columns) - 1),
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.8)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#dddddd")
        if row == 0:
            cell.set_facecolor("#eeeeee")
    finish(pdf, figure, note)


def render_run_details(pdf, reports):
    """Retain each pilot and rejected run's physical outcomes and controller overhead.

    Args:
        pdf (PdfPages): Open combined-report writer.
        reports (list[dict]): Frozen payloads including pilot and rejected observations.
    """
    runs = [run for report in reports for run in report["runs"]]
    physical, overhead = [], []
    for run in runs:
        response, control = run["responses"], run["controller"]
        identity = f'{run["role"]} {run["seed"]} {run["arm"]}'
        if not run["accepted_capture"]:
            identity += " REJECTED"
        lower, upper = run["allocation"]["allocated_core_seconds_bounds"]
        allocation = f"{lower/3600:.3f}–{upper/3600:.3f}"
        physical.append(
            [
                identity,
                str(response["jobs"]),
                str(response["completed"]),
                str(len(response["failed_uids"])),
                str(len(response["censored_uids"])),
                _metric(response.get("completed_response_median_seconds")),
                _metric(response["completed_response_p95_seconds"]),
                allocation,
                _metric(
                    100 * response["deadline_fraction"]
                    if response["deadline_fraction"] is not None
                    else None
                ),
            ]
        )
        cycles = control["cycles"]
        native_cpu = [
            c["native_process_cpu_seconds"]
            for c in cycles
            if c.get("native_process_cpu_seconds") is not None
        ]
        native_rss = [
            c["native_process_peak_rss_bytes"] / 2**20
            for c in cycles
            if c.get("native_process_peak_rss_bytes") is not None
        ]
        host_rss = control.get("controller_peak_rss_kib")
        overhead.append(
            [
                identity,
                str(len(cycles)),
                _metric(control.get("cycle_wall_median_seconds")),
                _metric(control.get("cycle_wall_p95_seconds")),
                _metric(control.get("controller_cpu_seconds")),
                _metric(host_rss / 1024 if host_rss is not None else None),
                _metric(float(np.median(native_cpu)) if native_cpu else None),
                _metric(max(native_rss) if native_rss else None),
            ]
        )
    for pilot in sorted(
        (run for run in runs if run["role"] == "pilot" and run["arm"] == "forecast"),
        key=lambda run: run["seed"],
    ):
        _forecast_observation_page(pdf, pilot)
    # Keep tables readable when failed attempts are explicitly supplied alongside the study matrix.
    for offset in range(0, len(runs), 14):
        _table_page(
            pdf,
            "Per-run physical evidence, including pilots",
            "Every row retains its role; rejected and pilot attempts do not enter "
            "benefit summaries.",
            [
                "Role / seed / arm",
                "Jobs",
                "Done",
                "Failed",
                "Censored",
                "Median (s)",
                "p95 (s)",
                "Core-hours",
                "Within target (%)",
            ],
            physical[offset : offset + 14],
            "Responses start at original Job creation. Quantiles describe completed Jobs only.\n"
            "Core-hours include accepting and draining workers; bounds preserve "
            "missing observations.\n"
            "Configured follow-up ends after the arrival window; completions beyond "
            "that boundary remain censored. See configuration settings.",
        )
        _table_page(
            pdf,
            "Per-run controller cost and latency",
            "Host preparation and isolated native execution are measured separately.",
            [
                "Role / seed / arm",
                "Cycles",
                "Wall med (s)",
                "Wall p95 (s)",
                "Host CPU (s)",
                "Host peak MiB",
                "Native CPU med (s)",
                "Native peak MiB",
            ],
            overhead[offset : offset + 14],
            "Host CPU is summed over evaluation cycles; its RSS is the "
            "process-lifetime peak recorded there.\n"
            "Native CPU is per completed process; peak RSS is the maximum supplied "
            "native process value.\n"
            "Missing metrics are shown as —. These are computation costs, not "
            "physical energy measurements.",
        )


def observed_series(series, origin, field):
    """Extract a physical timeline with explicit breaks across unknown observation intervals.

    Args:
        series (list[dict]): Timestamped allocation snapshots with validity and membership flags.
        origin (float): Evaluation origin in UTC epoch seconds.
        field (str): Allocated cores, accepting workers or queue length to display.

    Returns:
        tuple[list[float], list[float]]: Minutes and values, including NaNs for unknown intervals.
    """
    times, values = [], []
    previous = None
    for point in series:
        at = (point["time"] - origin) / 60
        if previous is not None and point["time"] - previous > 3:
            times.append((previous - origin + 0.001) / 60)
            values.append(np.nan)
        valid = point.get("valid") and (field != "queue" or point.get("membership_complete"))
        value = point.get(field) if valid else None
        times.append(at)
        values.append(np.nan if value is None else value)
        previous = point["time"]
    return times, values


def action_evidence(run):
    """Keep decision origin separate from API acknowledgment and observer confirmation.

    Args:
        run (dict): Frozen run with per-cycle proposals and recorded action requests.

    Returns:
        list[dict]: All requests, their decision source and strict confirmation status.
    """
    cycles = {cycle["tick"]: cycle for cycle in run["controller"]["cycles"]}
    rows = []
    for action in run["controller"].get("actions", []):
        cycle = cycles.get(action.get("tick"), {})
        if cycle.get("proposal", {}).get("fallback") is True:
            source = "Reactive fallback"
        elif run["arm"] == "forecast" and cycle.get("forecast_valid") is True:
            source = "Forecast"
        elif run["arm"] == "reactive":
            source = "Reactive baseline"
        else:
            source = "Unknown"
        rows.append(
            dict(
                action=action["action"],
                source=source,
                request_seconds=action["recorded_at_ns"] / 1e9,
                confirmed=action.get("observed") is True
                and action.get("result", {}).get("status") == "acknowledged",
            )
        )
    return rows


def _action_summary_rows(actions):
    """Count every request by source without expanding the overview beyond its panel.

    Args:
        actions (list[dict]): Normalized requests and confirmation flags from action_evidence.

    Returns:
        list[list[str]]: Source and down/up confirmed/requested counts for the overview table.
    """
    rows = []
    for source in dict.fromkeys(action["source"] for action in actions):
        row = [source]
        for kind in ("scale-down", "scale-up"):
            requests = [
                action
                for action in actions
                if action["source"] == source and action["action"] == kind
            ]
            row.append(f'{sum(action["confirmed"] for action in requests)}/{len(requests)}')
        rows.append(row)
    return rows


def _action_evidence_page(pdf, run):
    """Show actual actuation, including fallback and rejected native decisions.

    Args:
        pdf (PdfPages): Open report destination.
        run (dict): Accepted held-out run selected because it recorded action requests.
    """
    figure, axes = page(
        f'Physical action evidence: heldout {run["arm"]}, seed {run["seed"]}',
        "Observed capacity changes establish actuation; the decision source and latency "
        "remain explicit.",
    )
    origin = run["evaluation_start_seconds"]
    actions = action_evidence(run)
    for axis, field, title, ylabel in (
        (
            axes[0, 0],
            "allocated",
            "Capacity counts accepting and draining workers",
            "Application cores",
        ),
        (
            axes[0, 1],
            "queue",
            "Observed queue alongside action requests",
            "Queued Jobs",
        ),
    ):
        times, values = observed_series(run["allocation"]["series"], origin, field)
        axis.step(times, values, where="post", color="black")
        for index, action in enumerate(actions):
            axis.axvline(
                (action["request_seconds"] - origin) / 60,
                color=COLORS[index % len(COLORS)],
                linestyle="--",
                linewidth=1,
            )
        axis.set_xlim(0, (run["arrival_end_seconds"] - origin) / 60)
        axis.set_ylim(bottom=0)
        panel(axis, title, "Minutes after warm-up", ylabel)
    axes[1, 0].axis("off")
    axes[1, 0].set_title("Confirmed actions / all requests", fontsize=10, pad=10)
    table = axes[1, 0].table(
        cellText=_action_summary_rows(actions),
        colLabels=["Decision source", "Down\nconfirmed / requested", "Up\nconfirmed / requested"],
        colWidths=[0.44, 0.28, 0.28],
        cellLoc="center",
        loc="upper center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.6)
    if run["arm"] == "reactive":
        axes[1, 1].axis("off")
        axes[1, 1].text(
            0.5,
            0.5,
            "Not applicable: reactive baseline\nuses no native forecasts",
            ha="center",
            va="center",
            transform=axes[1, 1].transAxes,
            fontsize=10,
        )
    else:
        for valid, label, color in (
            (True, "Valid forecast", COLORS[0]),
            (False, "Rejected native decision", COLORS[1]),
        ):
            cycles = [
                cycle
                for cycle in run["controller"]["cycles"]
                if cycle.get("complete_native_eligible")
                and cycle.get("forecast_valid") is valid
                and cycle.get("decision_age_seconds") is not None
            ]
            axes[1, 1].scatter(
                [(cycle["started_at"] - origin) / 60 for cycle in cycles],
                [cycle["decision_age_seconds"] for cycle in cycles],
                color=color,
                label=label,
                s=22,
            )
        axes[1, 1].axhline(
            run.get("invocation", {}).get("decision_age_seconds", 30),
            color="black",
            linestyle="--",
            linewidth=1,
        )
        axes[1, 1].set_ylim(bottom=0)
        axes[1, 1].set_xlim(0, (run["arrival_end_seconds"] - origin) / 60)
        axes[1, 1].legend(fontsize=7, loc="lower left")
        panel(
            axes[1, 1],
            "Rejected completed native decisions retain their measured age",
            "Minutes after warm-up",
            "Native decision age from cutoff (s)",
        )
    finish(
        pdf,
        figure,
        "Dashed markers show API request times; confirmation requires acknowledgment "
        "and observation. Counts retain every request.\n"
        "Per-action timing remains on lifecycle pages when available and in the saved metrics.\n"
        "Observation gaps remain blank. Actions belong to cycles started in the "
        "evaluation window; requests may finish during follow-up.\n"
        "This run is shown because actions occurred, not as a representative "
        "forecast-quality sample. Warm reserves remain powered.",
    )


def _forecast_observation_page(pdf, run):
    """Place a supplied run's predictions directly beside its physical outcomes.

    Args:
        pdf (PdfPages): Open report writer.
        run (dict): Explicitly labeled held-out run or development pilot.
    """
    rows = [row for row in run.get("forecast_diagnostics", []) if row["complete_arrival_window"]]
    if not rows:
        return
    origin = run["evaluation_start_seconds"]
    horizon = run.get("invocation", {}).get("horizon_seconds", rows[0].get("horizon_seconds", 60))
    times = [(row["cutoff_ms"] / 1000 - origin) / 60 for row in rows]
    figure, axes = page(
        f'Predictions and observations: {run["role"]} seed {run["seed"]}',
        "Each forecast uses only its prefix; observed outcomes include any later "
        "controller actions.",
    )
    mean = [row["predicted_mean_future_jobs"] for row in rows]
    observed = [row["observed_future_jobs"] for row in rows]
    axes[0, 0].plot(times, mean, color=COLORS[0], label="Forecast mean")
    axes[0, 0].plot(times, observed, color="black", marker=".", label="Observed")
    lower = [min(row["sampled_future_job_counts"]) for row in rows]
    upper = [max(row["sampled_future_job_counts"]) for row in rows]
    axes[0, 0].fill_between(
        times, lower, upper, color=COLORS[0], alpha=0.15, label="Sampled-future min–max"
    )
    predicted = [row["predicted_response_p95_seconds"] for row in rows]
    axes[0, 1].plot(
        times,
        [np.median(values) if values else np.nan for values in predicted],
        color=COLORS[0],
        label="Predicted + decision age",
    )
    axes[0, 1].fill_between(
        times,
        [min(values) if values else np.nan for values in predicted],
        [max(values) if values else np.nan for values in predicted],
        color=COLORS[0],
        alpha=0.15,
    )
    axes[0, 1].plot(
        times,
        [row["observed_cohort_response_p95_seconds"] for row in rows],
        color="black",
        marker=".",
        label="Observed completed cohort",
    )
    axes[0, 1].axhline(
        run.get("invocation", {}).get("deadline_seconds", 120),
        color="black",
        linestyle="--",
        linewidth=1,
    )
    series = run["allocation"]["series"]
    for field, color, label in (
        ("allocated", COLORS[0], "Accepting + draining cores"),
        ("accepting", COLORS[2], "Accepting workers"),
    ):
        state_times, state_values = observed_series(series, origin, field)
        axes[1, 0].step(
            state_times,
            state_values,
            where="post",
            color=color,
            label=label,
        )
    observed_actions = [
        action for action in run["controller"].get("actions", []) if action["observed"] is True
    ]
    for action in observed_actions:
        at = (action["recorded_at_ns"] / 1e9 - origin) / 60
        axes[1, 0].axvline(at, color=COLORS[1], linestyle=":", linewidth=1)
        axes[1, 0].annotate(
            "↓" if action["action"] == "scale-down" else "↑",
            (at, 0),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            color=COLORS[1],
        )
    queue_times, queue_values = observed_series(series, origin, "queue")
    axes[1, 1].step(queue_times, queue_values, where="post", color="black")
    for axis in axes.flat:
        axis.set_ylim(bottom=0)
        axis.set_xlim(0, (run["arrival_end_seconds"] - origin) / 60)
    axes[0, 0].legend(
        fontsize=7,
        loc="upper left",
        bbox_to_anchor=(0, -0.32),
        ncol=3,
        borderaxespad=0,
        frameon=False,
    )
    axes[0, 1].legend(fontsize=7, loc="lower left")
    axes[1, 0].legend(fontsize=7, loc="upper left")
    panel(
        axes[0, 0],
        f"Forecast count versus arrivals in the next {horizon:g} s",
        "Minutes after warm-up",
        "Future Jobs",
    )
    panel(
        axes[0, 1],
        "Backlog + future cohort; only the actual initial action is compared",
        "Minutes after warm-up",
        "Original-creation response p95 (s)",
    )
    panel(
        axes[1, 0],
        (
            "Dotted lines mark physically observed down/up actions"
            if observed_actions
            else "No confirmed capacity change in this run"
        ),
        "Minutes after warm-up",
        "Application cores / accepting workers",
    )
    panel(
        axes[1, 1],
        "Observed queue through the evaluation window",
        "Minutes after warm-up",
        "Queued Jobs",
    )
    finish(
        pdf,
        figure,
        "Shading spans sampled futures, not a confidence interval. Response "
        "predictions add measured decision age.\n"
        "Observed response quantiles cover completed cohort Jobs; failed/censored "
        "counts remain in the per-run evidence.\n"
        "Later control can change completion times. This is a loop diagnostic, not "
        "isolated scaling-counterfactual validation.",
    )


def _configuration_page(pdf, runs):
    """Show the numerical protocol beside its measured outcomes, including pilot choices.

    Args:
        pdf (PdfPages): Open combined report writer.
        runs (list[dict]): All supplied physical runs with frozen invocation settings.
    """
    if not runs:
        return
    rows = []
    for run in runs:
        settings = run.get("invocation", {})
        rows.append(
            [
                f'{run["role"]} {run["seed"]} {run["arm"]}',
                str(settings.get("period_seconds", "—")),
                str(settings.get("cadence_seconds", 60)),
                str(settings.get("horizon_seconds", 60)),
                str(settings.get("scenarios", 3)),
                str(settings.get("decision_age_seconds", 30)),
                (
                    f'{settings.get("deadline_fraction", .95)*100:g}% / '
                    f'{settings.get("deadline_seconds", 120):g}s'
                ),
                f'{settings.get("warmup_cycles", "—")} / {settings.get("cycles", "—")}',
                str(settings.get("followup_seconds", 600)),
            ]
        )
    for offset in range(0, len(rows), 12):
        _table_page(
            pdf,
            "Configuration choices and scope",
            "Development trials and frozen evaluation retain separate roles; "
            "units are seconds unless stated.",
            [
                "Role / seed / arm",
                "Period",
                "Cadence",
                "Lookahead",
                "Futures",
                "Age budget",
                "Service target",
                "Warm/total cycles",
                "Follow-up",
            ],
            rows[offset : offset + 12],
            "Each run retains its archived policy and exact invocation; legacy settings "
            "are labeled where this table cannot recover them.\n"
            "Forecast-only settings do not run in fixed/reactive arms. Warm-up and follow-up "
            "are distinct from the allocation window.\n"
            "Finite lookahead, frozen lifecycle estimates and few independent runs limit "
            "generalization; warm reserves stay powered.",
        )
    choices = []
    for run in runs:
        settings = run.get("invocation", {})
        choices.append(
            [
                f'{run["role"]} {run["seed"]} {run["arm"]}',
                f'{settings.get("minimum_rate", "—")}–{settings.get("peak_rate", "—")}',
                (
                    f'{settings.get("reactive_up_threshold", "legacy")} / '
                    f'{settings.get("reactive_down_threshold", "legacy")}'
                ),
                str(settings.get("residual_margin_seconds", 0)),
                str(settings.get("allocation_seconds", 120)),
                str(settings.get("native_timeout_seconds", 20)),
            ]
        )
    for offset in range(0, len(choices), 12):
        _table_page(
            pdf,
            "Demand, occupancy and computation settings",
            "Thresholds and timing are development choices, not universal workload constants.",
            [
                "Role / seed / arm",
                "Rate range (jobs/s)",
                "Reactive up / down",
                "Residual margin (s)",
                "Allocation window (s)",
                "Native timeout (s)",
            ],
            choices[offset : offset + 12],
            "Four images and 128 inference repetitions retain the calibrated workload; "
            "resource sampling remains five seconds.\n"
            "Reactive demand counts requested CPU of unfinished assigned/queued Jobs; "
            "up compares with accepting capacity.\n"
            "Down compares with capacity after removal and requires a worker empty at "
            "two consecutive scheduled checks.\n"
            "Current overruns use the median residual of longer completed profiles, or a "
            "five-second fallback, plus the declared margin.\n"
            "Ready reserve acquisition is immediate in the model; measured decision, API "
            "and observation delay remains explicit.",
        )


def _lifecycle_page(pdf, run):
    """Expose measured release and reuse separately from the request and acknowledgement.

    Args:
        pdf (PdfPages): Open report writer.
        run (dict): Physical run with lifecycle evidence, when available.
    """
    lifecycle = run["controller"].get("lifecycles", {})
    actions = lifecycle.get("actions", [])
    if not actions:
        return
    origin = run["evaluation_start_seconds"]
    rows = []
    for action in actions:
        values = [
            action["recorded_at_ns"] / 1e9,
            action.get("result", {}).get("last_action_at"),
            action.get("observation_seconds"),
            action.get("first_observed_empty_seconds"),
            action.get("reused_at_seconds"),
        ]
        rows.append(
            [
                f'{action["action"].replace("scale-", "")} {action["selected_worker"]}',
                action.get("decision_source", "unknown"),
                *[
                    _metric((value - origin) / 60, 2) if value is not None else "—"
                    for value in values
                ],
            ]
        )
    for offset in range(0, len(rows), 12):
        _table_page(
            pdf,
            f'Capacity release and reuse: {run["arm"]} seed {run["seed"]}',
            (
                "Confirmed forecast pairs from cycles started during evaluation: "
                f'{lifecycle.get("forecast_down_up_pairs", 0)}.'
            )
            if run["arm"] == "forecast"
            else (
                "Reactive release and reuse are reported separately "
                "from the forecast-only target."
            ),
            [
                "Action / worker",
                "Source",
                "Request min",
                "Ack min",
                "Observed min",
                "Empty min",
                "Reused min",
            ],
            rows[offset : offset + 12],
            "Minutes are relative to evaluation start. Empty is the first valid observed "
            "reserve after acknowledgment, not an exact resource-release instant.\n"
            "A worker remains allocated while draining. Missing or unconfirmed outcomes "
            "remain —; reserves remain powered.\n"
            "Pairs require confirmed forecast-selected release and reuse of the same worker; "
            "fallback actions cannot satisfy that count.",
        )
