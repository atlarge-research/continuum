"""Plot a frozen forecast study directly against observed and known-arrival outcomes."""
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
