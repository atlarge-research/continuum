"""Pure, auditable capacity choices under the approved demo response guardrail."""

from __future__ import annotations

import copy
import math
from statistics import mean


def _finite_nonnegative(value):
    """Check numeric measurements without accepting booleans or nonfinite values.

    Args:
        value (object): Measurement supplied by the validated-result adapter.

    Returns:
        bool: Whether the value is a finite nonnegative real measurement.
    """
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def summarize_candidate(candidate, decision_age, *, scenarios=3, deadline_seconds=120):
    """Score complete scenario cohorts with an explicit decision-latency margin.

    Args:
        candidate (dict): Action, target worker and per-scenario response/allocation data.
        decision_age (float): Elapsed seconds since the causal state cutoff.
        scenarios (int): Required number of shared sampled futures.
        deadline_seconds (float): Response target measured from original Job creation.

    Returns:
        dict: Validity and worst-future late fraction, mean tardiness and mean allocation.
    """
    result = {
        "candidate": candidate.get("candidate"),
        "selected_worker": candidate.get("selected_worker"),
        "valid": False,
    }
    rows = candidate.get("scenarios", [])
    if candidate.get("unavailable_reason"):
        return {**result, "reason": candidate["unavailable_reason"]}
    if len(rows) != scenarios:
        return {**result, "reason": "missing_scenarios"}
    fractions, tardiness, allocation = [], [], []
    for row in rows:
        responses = row.get("responses_seconds")
        count = row.get("cohort_size")
        cost = row.get("allocated_core_seconds")
        if (
            row.get("complete") is not True
            or type(count) is not int
            or count < 0
            or not isinstance(responses, list)
            or len(responses) != count
            or not all(_finite_nonnegative(value) for value in responses)
            or not _finite_nonnegative(cost)
        ):
            return {**result, "reason": "incomplete_or_invalid_cohort"}
        adjusted = [value + decision_age for value in responses]
        fractions.append(
            sum(value > deadline_seconds for value in adjusted) / count if count else 0
        )
        tardiness.append(
            mean(max(0, value - deadline_seconds) for value in adjusted) if count else 0
        )
        allocation.append(cost)
    return {
        **result,
        "valid": True,
        "worst_late_fraction": max(fractions),
        "mean_tardiness_seconds": mean(tardiness),
        "allocated_core_seconds": mean(allocation),
        "scenario_late_fractions": fractions,
    }


def select_action(candidates, state, *, now_seconds, decision_age, scenarios=3):
    """Choose an action without performing I/O or modifying controller history.

    Candidate comparison requires all scenarios and complete represented work.
    Empty cohorts are explicitly valid; incomplete results cannot appear cheap.
    Only acknowledged physical actions update ``last_action_at`` in the caller.

    Args:
        candidates (list[dict]): Shared-future unchanged/up/down score inputs.
        state (dict): Persisted last action time and consecutive down-proposal history.
        now_seconds (float): Current UTC epoch seconds, allowing restart reconciliation.
        decision_age (float): Cutoff-to-decision duration in seconds.
        scenarios (int): Required sampled-future count, initially three.

    Returns:
        dict: Chosen action, reason, target, scored alternatives and next history.

    Raises:
        ValueError: Candidate actions, scenario count or supplied clock values are invalid.
    """
    actions = [item.get("candidate") for item in candidates]
    if (
        len(set(actions)) != len(actions)
        or not set(actions) <= {"unchanged", "scale-up", "scale-down"}
        or not _finite_nonnegative(now_seconds)
        or not _finite_nonnegative(decision_age)
        or type(scenarios) is not int
        or scenarios < 1
    ):
        raise ValueError("invalid policy candidates, clocks or scenario count")
    history = copy.deepcopy(state)
    history.update(down_worker=None, down_wins=0)
    result = {
        "action": "unchanged",
        "selected_worker": None,
        "state": history,
        "guardrail_feasible": False,
        "reason": "no_valid_unchanged",
        "scores": [],
    }
    if decision_age > 30:
        return {**result, "reason": "decision_stale"}
    scores = [summarize_candidate(item, decision_age, scenarios=scenarios) for item in candidates]
    result["scores"] = scores
    valid = {item["candidate"]: item for item in scores if item["valid"]}
    if "unchanged" not in valid:
        return result
    hold = valid["unchanged"]
    qualifying = [item for item in valid.values() if item["worst_late_fraction"] <= 0.05]
    result["guardrail_feasible"] = bool(qualifying)
    previous_action = state.get("last_action_at")
    if previous_action is not None:
        if not _finite_nonnegative(previous_action) or now_seconds < previous_action:
            return {**result, "reason": "clock_or_action_history_invalid"}
        if now_seconds - previous_action < 120:
            return {**result, "reason": "action_cooldown"}
    if qualifying:
        selected = min(
            qualifying,
            key=lambda item: (
                item["allocated_core_seconds"],
                item["candidate"] != "unchanged",
                item["candidate"],
            ),
        )
        reason = "least_allocation_with_response_guardrail"
    else:
        up = valid.get("scale-up")
        if up is None or (up["worst_late_fraction"], up["mean_tardiness_seconds"]) >= (
            hold["worst_late_fraction"],
            hold["mean_tardiness_seconds"],
        ):
            return {**result, "reason": "guardrail_infeasible_no_improving_action"}
        selected, reason = up, "guardrail_infeasible_scale_up_improves"
    action = selected["candidate"]
    if action == "scale-down":
        cost = hold["allocated_core_seconds"]
        saving = (cost - selected["allocated_core_seconds"]) / cost if cost else 0
        if saving < 0.10 or not selected["selected_worker"]:
            return {**result, "reason": "insufficient_savings_or_target"}
        wins = (
            state.get("down_wins", 0)
            if state.get("down_worker") == selected["selected_worker"]
            else 0
        )
        history.update(down_worker=selected["selected_worker"], down_wins=wins + 1)
        if history["down_wins"] < 2:
            return {**result, "reason": "awaiting_second_down_win"}
    return {
        **result,
        "action": action,
        "selected_worker": selected["selected_worker"],
        "reason": reason,
    }
