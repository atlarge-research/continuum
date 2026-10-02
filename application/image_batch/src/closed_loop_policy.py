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
    if candidate.get("candidate") != "unchanged" and (
        not isinstance(candidate.get("selected_worker"), str)
        or not candidate["selected_worker"].strip()
    ):
        return {**result, "reason": "missing_action_target"}
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


def _least_cost(scores, fields):
    """Rank measurements lexicographically, preferring hold on numerical ties.

    Args:
        scores (list[dict]): Nonempty valid candidate summaries.
        fields (tuple[str]): Ordered objective fields, most important first.

    Returns:
        dict: Deterministic winning candidate.
    """
    remaining = scores
    for field in fields:
        best = min(item[field] for item in remaining)
        remaining = [
            item
            for item in remaining
            if math.isclose(item[field], best, rel_tol=1e-9, abs_tol=1e-9)
        ]
    return min(remaining, key=lambda item: (item["candidate"] != "unchanged", item["candidate"]))


def select_action(
    candidates,
    state,
    *,
    now_seconds,
    decision_age,
    scenarios=3,
    age_budget_seconds=30,
    deadline_seconds=120,
    deadline_fraction=0.95,
):
    """Select the least allocated capacity satisfying every sampled future.

    All-infeasible choices minimize worst late fraction, mean tardiness, then
    allocation and are explicitly labeled infeasible. Numerical ties prefer hold.
    Complete current evidence suffices; no forecast-win streak or cooldown is
    imposed. Physical guards and unresolved-intent reconciliation remain the
    caller's responsibility. The adapter verifies shared cohorts across actions.

    Args:
        candidates (list[dict]): Shared-future unchanged/up/down score inputs.
        state (dict): Persisted history, passed through without policy mutation.
        now_seconds (float): Current UTC epoch seconds.
        decision_age (float): Cutoff-to-decision duration in seconds.
        scenarios (int): Required sampled-future count.
        age_budget_seconds (float): Maximum causal decision age.
        deadline_seconds (float): Original-creation response deadline.
        deadline_fraction (float): Required within-deadline fraction in every future.

    Returns:
        dict: Chosen action, feasibility, explanation, alternatives and copied history.

    Raises:
        ValueError: Candidate actions, policy settings or clocks are invalid.
    """
    # One boundary validates the complete policy contract; keep related checks together.
    # pylint: disable=too-many-boolean-expressions
    actions = [item.get("candidate") for item in candidates]
    if (
        len(set(actions)) != len(actions)
        or not set(actions) <= {"unchanged", "scale-up", "scale-down"}
        or not _finite_nonnegative(now_seconds)
        or not _finite_nonnegative(decision_age)
        or isinstance(scenarios, bool)
        or not isinstance(scenarios, int)
        or scenarios < 1
        or not _finite_nonnegative(age_budget_seconds)
        or age_budget_seconds <= 0
        or not _finite_nonnegative(deadline_seconds)
        or deadline_seconds <= 0
        or not _finite_nonnegative(deadline_fraction)
        or not 0 < deadline_fraction <= 1
    ):
        raise ValueError("invalid policy candidates, clocks or settings")
    result = {
        "action": "unchanged",
        "selected_worker": None,
        "state": copy.deepcopy(state),
        "guardrail_feasible": False,
        "reason": "no_valid_unchanged",
        "scores": [],
    }
    if decision_age > age_budget_seconds:
        return {**result, "reason": "decision_stale"}
    scores = [
        summarize_candidate(
            item, decision_age, scenarios=scenarios, deadline_seconds=deadline_seconds
        )
        for item in candidates
    ]
    result["scores"] = scores
    valid = [item for item in scores if item["valid"]]
    if not any(item["candidate"] == "unchanged" for item in valid):
        return result
    qualifying = [
        item for item in valid if item["worst_late_fraction"] <= 1 - deadline_fraction + 1e-12
    ]
    result["guardrail_feasible"] = bool(qualifying)
    if qualifying:
        selected = _least_cost(qualifying, ("allocated_core_seconds",))
        reason = "least_allocation_with_response_guardrail"
    else:
        selected = _least_cost(
            valid, ("worst_late_fraction", "mean_tardiness_seconds", "allocated_core_seconds")
        )
        reason = "guardrail_infeasible_least_violation_then_allocation"
    return {
        **result,
        "action": selected["candidate"],
        "selected_worker": selected["selected_worker"],
        "reason": reason,
    }
