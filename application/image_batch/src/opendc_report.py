"""Assemble available OpenDC action and forecast evidence into one offline PDF."""
import argparse
import json
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt

from opendc_evaluate import render_action_pages
from opendc_report_validation import render_configuration_pages
from opendc_report_observed import SCHEMA as MEASURED_SCHEMA, render_measured_pages
from forecast_report import render_forecasts
from opendc_report_replay import render_replay_pages


def render_report(
    results,
    output,
    selection=None,
    action_reports=(),
    seed=None,
    measured_reports=(),
    forecast_reports=(),
    replay_reports=(),
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

    Returns:
        dict: Section inventory and the exact configuration summaries plotted.

    Raises:
        ValueError: No evidence sections were supplied or their measurements are incompatible.
    """
    action_reports = list(action_reports)
    measured_reports, forecast_reports = list(measured_reports), list(forecast_reports)
    replay_reports = list(replay_reports)
    if (
        not results
        and not action_reports
        and not measured_reports
        and not forecast_reports
        and not replay_reports
    ):
        raise ValueError("Supply action results or observation-validation results")
    audit = {
        "action_reports": len(action_reports),
        "validation": [],
        "measured": [],
        "arrival_forecasts": [],
        "replay": [],
        "section_order": [],
    }
    output = Path(output)
    with PdfPages(output) as pdf:
        for index, measured in enumerate(measured_reports):
            directory = output.parent / f"measured-{index:02d}"
            directory.mkdir(exist_ok=False)
            audit["measured"].append(render_measured_pages(pdf, measured, directory))
            audit["section_order"].append("measured")
        for index, forecast in enumerate(forecast_reports):
            directory = output.parent / f"arrival-forecast-{index:02d}"
            directory.mkdir(exist_ok=False)

            def save(figure, _directory, _name, title, layout=True):
                """Save a reused forecast page into the combined report.

                Args:
                    figure (Figure): Existing forecast figure.
                    _directory (Path): Standalone renderer output directory.
                    _name (str): Standalone artifact basename.
                    title (str): Page title from the forecast renderer.
                    layout (bool): Whether to apply automatic layout.
                """
                figure.suptitle(title, fontsize=17)
                if layout:
                    figure.tight_layout(rect=(0, 0.055, 1, 0.94))
                pdf.savefig(figure)
                plt.close(figure)

            render_forecasts(forecast, directory, save)
            audit["arrival_forecasts"].append(
                {
                    "settings": forecast["evaluation"]["settings"],
                    "horizon_summary": forecast["horizon_summary"],
                }
            )
            audit["section_order"].append("arrival-forecast")
        if replay_reports:
            audit["replay"] = render_replay_pages(pdf, replay_reports)
            audit["section_order"].append("unchanged-replay")
        for actions in action_reports:
            render_action_pages(pdf, actions)
            audit["section_order"].append("actions")
        for result in results:
            audit["validation"].append(render_configuration_pages(pdf, result, selection, seed))
            audit["section_order"].append("configuration")
    return audit


def write_report(metrics_files, output_dir, split=None, seed=None):
    """Load saved evidence and create a new report without loading original run directories.

    Args:
        metrics_files (iterable[str or Path]): Saved measured, forecast, replay, action
            or combined numerical evidence.
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
    saved_seeds = set()
    for source in sources:
        saved = json.loads(source.read_text(encoding="utf-8"))
        saved_seed = saved.get("render_options", {}).get("forecast_seed")
        if saved_seed is not None:
            saved_seeds.add(saved_seed)
        if "results" in saved:
            results.extend(r for r in saved["results"] if split is None or r["split"] == split)
            if saved.get("action_report") is not None:
                actions.append(saved["action_report"])
            actions.extend(saved.get("action_reports", []))
            measured.extend(saved.get("measured_reports", []))
            forecasts.extend(saved.get("forecast_reports", []))
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
    if not results and not actions and not measured and not forecasts and not replays:
        raise ValueError("No evidence matches the requested report sections")
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
        "selection": selection,
        "render_options": {"forecast_seed": seed},
    }
    (output / "metrics.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    audit = render_report(
        results, output / "report.pdf", selection, actions, seed, measured, forecasts, replays
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
