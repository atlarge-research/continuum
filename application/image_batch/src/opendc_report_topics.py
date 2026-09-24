"""Topic-oriented report summaries, preserving independent runs and frozen selection."""
import statistics

from opendc_report_topic_physical import render_physical
from opendc_report_topic_forecast import render_arrivals
from opendc_report_topic_study import render_selection, render_completion

from opendc_report_study import study_panels


def arrival_summary(reports, roles):
    """Average errors within each run before giving independent runs equal weight.

    Args:
        reports (list[dict]): Saved arrival evaluations with individual horizon scores.
        roles (dict): Run IDs mapped to explicit study split and workload seed.

    Returns:
        list[dict]: Split/horizon means, run ranges, counts and original run summaries.

    Raises:
        ValueError: Duplicate runs, unknown roles or incompatible forecast settings.
    """
    seen, groups, contracts = set(), {}, set()
    for report in reports:
        settings = report["evaluation"]["settings"]
        run = settings["run_id"]
        if run in seen:
            raise ValueError("duplicate arrival run")
        if run not in roles:
            raise ValueError("arrival run has no explicit study role")
        seen.add(run)
        contracts.add(
            tuple(
                settings.get(key)
                for key in (
                    "bin_seconds",
                    "period_seconds",
                    "horizon_seconds",
                    "warmup_periods",
                    "max_gap_seconds",
                    "image_count",
                    "inference_repetitions",
                )
            )
        )
        for summary in report["horizon_summary"]:
            horizon = summary["horizon_seconds"]
            scores = [row for row in report["horizon_scores"] if row["horizon_seconds"] == horizon]
            if len(scores) != summary["eligible_forecasts"]:
                raise ValueError("arrival score count disagrees with eligible forecasts")
            row = {
                "run_id": run,
                **roles[run],
                "eligible_forecasts": len(scores),
                "excluded_forecasts": summary["excluded_forecasts"],
                "mean_observed_count": statistics.mean(s["observed_count"] for s in scores)
                if scores
                else None,
            }
            for model in ("cyclic", "constant"):
                row[model] = (
                    statistics.mean(s[model]["absolute_error"] for s in scores) if scores else None
                )
            groups.setdefault((roles[run]["split"], horizon), []).append(row)
    if len(contracts) > 1:
        raise ValueError("incompatible arrival forecast settings")
    result = []
    for (split, horizon), runs in sorted(groups.items()):
        scored = [run for run in runs if run["eligible_forecasts"]]
        row = {
            "split": split,
            "horizon_seconds": horizon,
            "independent_runs": len(runs),
            "scored_runs": len(scored),
            "per_run": runs,
            "mean_observed_count": statistics.mean(r["mean_observed_count"] for r in scored)
            if scored
            else None,
        }
        for key in ("eligible_forecasts", "excluded_forecasts"):
            row[key] = sum(r[key] for r in runs)
        for model in ("cyclic", "constant"):
            values = [r[model] for r in scored]
            row[model + "_mean"] = statistics.mean(values) if values else None
            row[model + "_range"] = [min(values), max(values)] if values else None
        result.append(row)
    return result


def render_topics(pdf, measured, forecasts, studies, supplement):
    """Render topic pages without changing original study data or selection.

    Args:
        pdf (PdfPages): Open report writer.
        measured (list[dict]): Original complete physical measurement payloads.
        forecasts (list[dict]): Original forecast evaluations used by the study.
        studies (list[dict]): One frozen selection/held-out study.
        supplement (dict): Optional saved causal illustrations and scenario sensitivity.

    Returns:
        dict: Numerical summaries, study panels and provenance used on the topic pages.

    Raises:
        ValueError: Evidence lacks one study, matching run identities or a held-out run.
    """
    if len(studies) != 1:
        raise ValueError("topic report requires exactly one frozen study")
    study = studies[0]
    roles = {
        r["run_id"]: {"split": r["split"], "workload_seed": r["workload_seed"]}
        for r in study["results"]
    }
    if len(roles) != len(study["results"]):
        raise ValueError("duplicate study run")
    runs = [r for saved in measured for r in saved["runs"]]
    identities = [r["summary"]["run_id"] for r in runs]
    if len(set(identities)) != len(identities) or set(identities) != set(roles):
        raise ValueError("physical and study run identities must match uniquely")
    summaries = arrival_summary(forecasts, roles)
    if {f["evaluation"]["settings"]["run_id"] for f in forecasts} != set(roles):
        raise ValueError("forecast and study run identities must match")
    held = sorted(run for run, role in roles.items() if role["split"] == "held-out")
    if len(held) != 1:
        raise ValueError("topic illustrations require one identified held-out run")
    panels = study_panels(study)
    render_physical(pdf, measured, roles, supplement)
    example = next(f for f in forecasts if f["evaluation"]["settings"]["run_id"] == held[0])
    render_arrivals(pdf, example, summaries, roles, supplement)
    render_selection(pdf, study, panels, supplement)
    render_completion(pdf, [p for p in panels if p["run_id"] == held[0]], roles)
    return {
        "arrival_summary": summaries,
        "study_panels": panels,
        "selection": study["selection"],
        "supplement": supplement,
    }
