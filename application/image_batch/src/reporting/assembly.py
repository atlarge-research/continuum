"""Assemble available OpenDC action and forecast evidence into one offline PDF."""
import argparse
import json
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages

from analyze_run_core import export_matched_comparisons
from opendc_evaluate import render_action_pages
from reporting.forecast_evidence import export_forecasts
from reporting.configuration import render_configuration_pages
from reporting.measured import SCHEMA as MEASURED_SCHEMA, measured_groups
from reporting.replay import render_replay_pages
from reporting.study_evidence import SCHEMA as STUDY_SCHEMA
from reporting.topics import render_topics
from reporting.layout import SUPPLEMENT_SCHEMA
from reporting.controlled import (
    SCHEMA as CONTROLLED_SCHEMA,
    render_pages as render_controlled_pages,
    timing_summary,
    validate_comparisons,
)


def render_report(
    results,
    output,
    selection=None,
    action_reports=(),
    seed=None,
    measured_reports=(),
    forecast_reports=(),
    replay_reports=(),
    study_reports=(),
    controlled_reports=(),
    supplement=None,
):
    """Lead with supplied physical execution and arrival forecasts, then simulations.

    Args:
        results (list[dict]): Saved observation-validation results; may be empty.
        output (str or Path): PDF destination whose parent already exists.
        selection (dict or None): Previously selected forecast settings, when available.
        action_reports (iterable[dict]): Saved action evaluations; may be empty.
        seed (int or None): Forecast scenario seed; defaults to the first seed in each run.
        measured_reports (iterable[dict]): Complete saved measured-run numerical payloads.
        forecast_reports (iterable[dict]): Saved arrival-forecast accuracy payloads.
        replay_reports (iterable[dict]): Explicitly labeled unchanged known-arrival results.
        study_reports (iterable[dict]): Frozen independent-run study and held-out outcomes.
        controlled_reports (iterable[dict]): Physical action comparisons appended as validation.
        supplement (dict or None): Saved supplementary illustrations and sensitivity evidence.

    Returns:
        dict: Section inventory and the exact configuration summaries plotted.

    Raises:
        ValueError: No evidence sections were supplied or their measurements are incompatible.
    """
    action_reports = list(action_reports)
    measured_reports, forecast_reports = list(measured_reports), list(forecast_reports)
    replay_reports = list(replay_reports)
    study_reports = list(study_reports)
    controlled_reports = list(controlled_reports)
    if (
        not results
        and not action_reports
        and not measured_reports
        and not forecast_reports
        and not replay_reports
        and not study_reports
        and not controlled_reports
    ):
        raise ValueError("Supply action results or observation-validation results")
    audit = {
        "action_reports": len(action_reports),
        "validation": [],
        "measured": [],
        "arrival_forecasts": [],
        "replay": [],
        "studies": [],
        "controlled": [],
        "section_order": [],
    }
    output = Path(output)
    with PdfPages(output) as pdf:
        if measured_reports or forecast_reports or study_reports:
            audit["topics"] = render_topics(
                pdf, measured_reports, forecast_reports, study_reports, supplement or {}
            )
            audit["section_order"].extend(audit["topics"]["sections"])
            audit["measured"] = audit["topics"]["physical_runs"]
            audit["arrival_forecasts"] = audit["topics"]["arrival_summary"]
            audit["studies"] = audit["topics"]["studies"]
            for index, measured in enumerate(measured_reports):
                for group_index, indices in enumerate(measured_groups(measured)):
                    if len(indices) > 1:
                        directory = (
                            output.parent / f"measured-{index:02d}" / f"measured-{group_index}"
                        )
                        directory.mkdir(parents=True, exist_ok=False)
                        export_matched_comparisons(
                            [measured["runs"][i] for i in indices], directory
                        )
            for index, forecast in enumerate(forecast_reports):
                directory = output.parent / f"arrival-forecast-{index:02d}"
                directory.mkdir(exist_ok=False)
                export_forecasts(forecast, directory)
        if replay_reports:
            audit["replay"] = render_replay_pages(pdf, replay_reports)
            audit["section_order"].append("unchanged-replay")
        for actions in action_reports:
            render_action_pages(pdf, actions)
            audit["section_order"].append("actions")
        for result in results:
            audit["validation"].append(render_configuration_pages(pdf, result, selection, seed))
            audit["section_order"].append("configuration")
        if controlled_reports:
            render_controlled_pages(pdf, controlled_reports)
            audit["controlled"] = [
                {"context": saved["context"], "timing": timing_summary(saved)}
                for saved in controlled_reports
            ]
            audit["section_order"].append("controlled-validation")
    return audit


def write_report(metrics_files, output_dir, split=None, seed=None):
    """Load saved evidence and create a new report without loading original run directories.

    Args:
        metrics_files (iterable[str or Path]): Saved measured, forecast, replay, action
            controlled physical comparisons or combined numerical evidence.
        output_dir (str or Path): New output directory; existing reports are never overwritten.
        split (str or None): Optional validation split to include, such as ``validation``.
        seed (int or None): Forecast scenario seed to use within each supplied run.

    Returns:
        dict: Report provenance and configuration values also saved as comparison.json.

    Raises:
        FileExistsError: The destination already exists.
        ValueError: A metrics file is unrecognized or the requested evidence is absent.
    """
    sources = [Path(path).resolve() for path in metrics_files]
    results, actions, selection = [], [], None
    measured, forecasts, replays = [], [], []
    studies = []
    controlled = []
    saved_seeds = set()
    supplement = {}
    for source in sources:
        saved = json.loads(source.read_text(encoding="utf-8"))
        extra = (
            saved if saved.get("schema_version") == SUPPLEMENT_SCHEMA else saved.get("supplement")
        )
        if extra:
            if supplement and supplement != extra:
                raise ValueError("Supplied reports contain different supplementary evidence")
            supplement = extra
        saved_seed = saved.get("render_options", {}).get("forecast_seed")
        if saved_seed is not None:
            saved_seeds.add(saved_seed)
        if saved.get("schema_version") == SUPPLEMENT_SCHEMA:
            continue
        if saved.get("schema_version") == CONTROLLED_SCHEMA:
            controlled.extend(saved["comparisons"])
        elif saved.get("schema_version") == "opendc-controlled-comparison-v1":
            controlled.append(saved)
        elif saved.get("schema_version") == STUDY_SCHEMA:
            studies.append(saved)
        elif "results" in saved:
            results.extend(r for r in saved["results"] if split is None or r["split"] == split)
            if saved.get("action_report") is not None:
                actions.append(saved["action_report"])
            actions.extend(saved.get("action_reports", []))
            measured.extend(saved.get("measured_reports", []))
            forecasts.extend(saved.get("forecast_reports", []))
            studies.extend(saved.get("study_reports", []))
            controlled.extend(saved.get("controlled_reports", []))
            replays.extend(
                r
                for r in saved.get("replay_reports", [])
                if split is None or r["result"]["split"] == split
            )
            if saved.get("selection") is not None:
                if selection is not None and selection != saved["selection"]:
                    raise ValueError("Supplied reports contain different configuration selections")
                selection = saved["selection"]
        elif saved.get("schema_version") == MEASURED_SCHEMA:
            measured.append(saved)
        elif all(
            key in saved for key in ("evaluation", "forecasts", "rate_bins", "horizon_summary")
        ):
            forecasts.append(saved)
        elif "batches" in saved and "cases" in saved:
            actions.append(saved)
        else:
            raise ValueError(f"Unrecognized report metrics: {source}")
    if split is not None:
        excluded = {
            result["run_id"]
            for study in studies
            for result in study["results"]
            if result["split"] != split
        }
        measured = [
            {
                **saved,
                "runs": [run for run in saved["runs"] if run["summary"]["run_id"] not in excluded],
            }
            for saved in measured
        ]
        measured = [saved for saved in measured if saved["runs"]]
        forecasts = [
            saved
            for saved in forecasts
            if saved["evaluation"]["settings"]["run_id"] not in excluded
        ]
        supplement = {
            key: value
            for key, value in supplement.items()
            if key not in ("arrival_illustration", "scheduling")
            or value.get("run_id") not in excluded
        }
    studies = [
        {**study, "results": [r for r in study["results"] if split is None or r["split"] == split]}
        for study in studies
    ]
    studies = [study for study in studies if study["results"]]
    if (
        not results
        and not actions
        and not measured
        and not forecasts
        and not replays
        and not studies
        and not controlled
    ):
        raise ValueError("No evidence matches the requested report sections")
    validate_comparisons(controlled)
    if seed is None:
        if len(saved_seeds) > 1:
            raise ValueError(
                "Saved reports selected different forecast seeds; choose one explicitly"
            )
        seed = next(iter(saved_seeds), None)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": "opendc-combined-evidence-v1",
        "results": results,
        "action_reports": actions,
        "measured_reports": measured,
        "forecast_reports": forecasts,
        "replay_reports": replays,
        "study_reports": studies,
        "controlled_reports": controlled,
        "selection": selection,
        "render_options": {"forecast_seed": seed},
        "supplement": supplement,
    }
    (output / "metrics.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    audit = render_report(
        results,
        output / "report.pdf",
        selection,
        actions,
        seed,
        measured,
        forecasts,
        replays,
        studies,
        controlled,
        supplement,
    )
    audit["sources"] = [str(source) for source in sources]
    (output / "comparison.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit


def main():
    """Generate a report from one or more saved metrics files, with optional split selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--split", help="include only this validation split; action pages are retained"
    )
    parser.add_argument("--forecast-seed", type=int)
    args = parser.parse_args()
    write_report(args.metrics, args.output_dir, args.split, args.forecast_seed)


if __name__ == "__main__":
    main()
