"""Frozen per-cycle forecasts adjacent to later physical observations, with control caveats."""

import json

import numpy as np

from forecast_trace import milliseconds


def cycle_diagnostic(directory, cycle, observations, arrival_end_ms, followup_end_ms):
    """Compare one saved forecast with its later actual arrival and original-creation cohort.

    This is a closed-loop diagnostic, not validation of an isolated counterfactual:
    subsequent controller actions can alter the physical completion times.

    Args:
        directory (Path): Immutable cycle directory containing forecast and native scores.
        cycle (dict): Journal-derived cycle and confirmed physical action identity.
        observations (list[dict]): Full observed application Job UID inventory.
        arrival_end_ms (int): End of planned physical arrivals; exclude truncated forecast windows.
        followup_end_ms (int): Last allowed actual terminal time for physical completion scoring.

    Returns:
        dict or None: Self-contained prediction/observation pair, or no ready forecast.
    """
    forecast_path = directory / "forecast/forecast.json"
    if not forecast_path.exists():
        return None
    forecast = json.loads(forecast_path.read_text())
    if forecast["status"] != "ready":
        return None
    cutoff = milliseconds(forecast["cutoff"])
    end = cutoff + forecast["settings"]["horizon_seconds"] * 1000
    future = [row for row in observations if cutoff <= row["creation_ms"] < end]
    candidate = None
    if cycle.get("outcome") in ("held", "shadow"):
        candidate = "unchanged"
    elif cycle.get("outcome") == "acknowledged" and cycle.get("action_observed") is True:
        candidate = cycle["proposal"]["action"]
    result = dict(
        tick=cycle["tick"],
        cutoff_ms=cutoff,
        horizon_end_ms=end,
        complete_arrival_window=end <= arrival_end_ms,
        predicted_mean_future_jobs=sum(row["mean_count"] for row in forecast["predictions"]),
        sampled_future_job_counts=forecast["scenario_job_counts"],
        observed_future_jobs=len(future),
        actual_candidate=candidate,
        predicted_response_p95_seconds=[],
        observed_cohort_response_p95_seconds=None,
        interpretation=(
            "Later controller actions may change these physical outcomes; "
            "not isolated counterfactual validation."
        ),
    )
    scores_path = directory / "scores.json"
    case_path = directory / "suite/experiments/unchanged/0000/case.json"
    if candidate is None or not scores_path.exists() or not case_path.exists():
        return result
    scores = json.loads(scores_path.read_text())
    selected = next((row for row in scores if row["candidate"] == candidate), {})
    scenarios = selected.get("scenarios", [])
    age = cycle.get("decision_age_seconds")
    if not scenarios or not all(row["complete"] for row in scenarios) or age is None:
        return result
    result["predicted_response_p95_seconds"] = [
        float(np.percentile([value + age for value in row["responses_seconds"]], 95))
        for row in scenarios
        if row["responses_seconds"]
    ]
    case = json.loads(case_path.read_text())
    backlog = {
        task["metadata"]["kubernetes_job_uid"]
        for task in case["tasks"]
        if task["metadata"]["cohort"] == "backlog"
    }
    uids = backlog | {row["uid"] for row in future}
    cohort = [row for row in observations if row["uid"] in uids]
    completed = [
        row
        for row in cohort
        if row["status"] == "Complete"
        and row.get("job_finish_ms") is not None
        and row["job_finish_ms"] <= followup_end_ms
    ]
    values = [(row["job_finish_ms"] - row["creation_ms"]) / 1000 for row in completed]
    result.update(
        observed_cohort_uids=sorted(uids),
        observed_cohort_jobs=len(uids),
        observed_cohort_unmatched_uids=sorted(uids - {row["uid"] for row in cohort}),
        observed_cohort_completed=len(completed),
        observed_cohort_response_p95_seconds=float(np.percentile(values, 95)) if values else None,
        observed_cohort_deadline_fraction=sum(value <= 120 for value in values) / len(uids)
        if uids
        else None,
        decision_age_seconds=age,
    )
    return result
