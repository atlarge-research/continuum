"""Topic-oriented report summaries, preserving independent runs and frozen selection."""
import statistics

from reporting.physical import render_physical
from reporting.arrivals import render_arrivals
from reporting.study import render_selection, render_completion

from reporting.study_evidence import study_panels


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
    """Render supplied evidence using one layout, without inventing study membership.

    Args:
        pdf (PdfPages): Open report writer.
        measured (list[dict]): Saved physical measurements, possibly empty.
        forecasts (list[dict]): Saved arrival evaluations, possibly empty.
        studies (list[dict]): Frozen studies with explicit selection and evaluation roles.
        supplement (dict): Optional causal illustrations and scenario sensitivity.

    Returns:
        dict: Section inventory, numerical summaries and original selection provenance.

    Raises:
        ValueError: Run identities or study roles conflict, or forecast contracts differ.
    """
    roles = {}
    for study in studies:
        for result in study["results"]:
            run = result["run_id"]
            if run in roles:
                raise ValueError("duplicate study run")
            roles[run] = {"split": result["split"], "workload_seed": result["workload_seed"]}
    runs = [run for saved in measured for run in saved["runs"]]
    identities = [run["summary"]["run_id"] for run in runs]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate physical run")
    for run in runs:
        roles.setdefault(
            run["summary"]["run_id"],
            {"split": "unassigned", "workload_seed": run["summary"]["schedule"].get("random_seed")},
        )
    for report in forecasts:
        roles.setdefault(
            report["evaluation"]["settings"]["run_id"],
            {"split": "unassigned", "workload_seed": None},
        )
    sections, summaries, study_audits = [], [], []
    if runs:
        render_physical(pdf, measured, roles, supplement)
        sections.append("measured")
    if forecasts:
        summaries = arrival_summary(forecasts, roles)
        examples = sorted(
            forecasts,
            key=lambda report: (
                roles[report["evaluation"]["settings"]["run_id"]]["split"] != "held-out",
                report["evaluation"]["settings"]["origin_ms"],
                report["evaluation"]["settings"]["run_id"],
            ),
        )
        render_arrivals(pdf, examples[0], summaries, roles, supplement)
        sections.append("arrival-forecast")
    for study in studies:
        panels = study_panels(study)
        if study["selection"].get("candidates"):
            render_selection(pdf, study, panels, supplement)
        held = {p["run_id"] for p in panels if p["split"] == "held-out"}
        selected_runs = held or {p["run_id"] for p in panels}
        for run in sorted(selected_runs):
            render_completion(pdf, [p for p in panels if p["run_id"] == run], roles)
        study_audits.append({"selection": study["selection"], "panels": panels})
        sections.append("study")
    return {
        "sections": sections,
        "physical_runs": [run["summary"] for run in runs],
        "arrival_summary": summaries,
        "studies": study_audits,
        "supplement": supplement,
    }
