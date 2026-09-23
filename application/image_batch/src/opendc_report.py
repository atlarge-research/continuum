"""Assemble available OpenDC action and forecast evidence into one offline PDF."""
import argparse
import json
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages

from opendc_evaluate import render_action_pages
from opendc_report_validation import render_configuration_pages


def render_report(results, output, selection=None, action_reports=(), seed=None):
    """Write optional action pages first, followed by supplied forecast experiments.

    Args:
        results (list[dict]): Saved observation-validation results; may be empty.
        output (str or Path): PDF destination whose parent already exists.
        selection (dict or None): Previously selected forecast settings, when available.
        action_reports (iterable[dict]): Saved action evaluations; may be empty.
        seed (int or None): Forecast scenario seed; defaults to the first seed in each run.

    Returns:
        dict: Section inventory and the exact configuration summaries plotted.

    Raises:
        ValueError: No evidence sections were supplied or their measurements are incompatible.
    """
    action_reports = list(action_reports)
    if not results and not action_reports:
        raise ValueError("Supply action results or observation-validation results")
    audit = {"action_reports": len(action_reports), "validation": []}
    with PdfPages(output) as pdf:
        for actions in action_reports:
            render_action_pages(pdf, actions)
        for result in results:
            audit["validation"].append(render_configuration_pages(pdf, result, selection, seed))
    return audit


def write_report(metrics_files, output_dir, split=None, seed=None):
    """Load saved evidence and create a new report without loading original run directories.

    Args:
        metrics_files (iterable[str or Path]): Saved action, validation or combined metrics files.
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
    for source in sources:
        saved = json.loads(source.read_text(encoding="utf-8"))
        if "results" in saved:
            results.extend(r for r in saved["results"] if split is None or r["split"] == split)
            if saved.get("action_report") is not None:
                actions.append(saved["action_report"])
            if saved.get("selection") is not None:
                if selection is not None and selection != saved["selection"]:
                    raise ValueError("Supplied reports contain different configuration selections")
                selection = saved["selection"]
        elif "batches" in saved and "cases" in saved:
            actions.append(saved)
        else:
            raise ValueError(f"Unrecognized report metrics: {source}")
    if not results and not actions:
        raise ValueError("No evidence matches the requested report sections")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    audit = render_report(results, output / "report.pdf", selection, actions, seed)
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
