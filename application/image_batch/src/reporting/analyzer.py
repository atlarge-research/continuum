"""Offline topic PDF and numerical exports from captured image-batch evidence.

Requires Python 3.10+ and requirements-analysis.txt; no cluster access.
Each supplied run retains its own arrival schedule and measured coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import matplotlib

# Preserve the standalone analyzer's public numerical API without coupling the core to graphics.
from analyze_run_core import (  # pylint: disable=unused-import
    STREAMS,
    analyze,
    compact_alignment,
    describe,
    endpoint_run,
    export_matched_comparisons,
    number,
    range_series,
    read_jsonl,
    require,
    seconds,
    unique,
    write_csv,
)
from reporting.forecast_evidence import export_forecasts, prepare_forecasts
from reporting.assembly import render_report
from reporting.measured import SCHEMA, prepare_measured


def format_value(value):
    """Format a summary statistic while retaining missingness.

    Args:
        value (float or None): Available statistic or missing value.

    Returns:
        str: Two-decimal display value, or n/a.
    """
    return "n/a" if value is None else f"{value:.2f}"


def summary_text(report):
    """Describe one captured run for the console and Markdown export.

    Args:
        report (dict): Analyzed run containing the summary and coverage statistics.

    Returns:
        str: Human-readable timing, delivery and sampling summary.
    """
    s = report["summary"]
    f, c = s["fidelity"], s["coverage"]
    return (
        f"{s['run_id']} | {s['schedule_start_utc']}\n"
        f"Requests: {f['planned_count']} planned / {f['attempted_count']} started / "
        f"{f['successful_count']} accepted / {s['completed_jobs']} completed Jobs\n"
        f"Scheduling lag median / max: {format_value(f['lag_ms']['median'])} / "
        f"{format_value(f['lag_ms']['max'])} ms; "
        f"fidelity: {f['fidelity_passed']}\n"
        f"Queue wait median / p95: {format_value(s['queue_seconds']['median'])} / "
        f"{format_value(s['queue_seconds']['p95'])} s; "
        f"execution median / p95: {format_value(s['execution_seconds']['median'])} / "
        f"{format_value(s['execution_seconds']['p95'])} s\n"
        f"Samples per completed Job min / median: {format_value(c['min'])} / "
        f"{format_value(c['median'])}; "
        f">=2: {format_value(c['at_least_2_percent'])}%; >=3: "
        f"{format_value(c['at_least_3_percent'])}%\n"
    )


def render(reports, output, provenance, max_sample_age, forecast_report=None):
    """Write shared topic graphics and preserve standalone numerical exports.

    Runs need not share arrival schedules or contain a complete lifecycle. The
    combined metrics payload retains all plotted evidence for offline rendering.

    Args:
        reports (list[dict]): Analyzed runs with arrivals, Jobs, pressure and coverage.
        output (Path): New destination directory; existing output is never overwritten.
        provenance (dict): Source paths, hashes and implementation identity.
        max_sample_age (float): Maximum CPU sample forward-hold duration in seconds.
        forecast_report (dict or None): Optional separately captured forecast evidence.

    Raises:
        FileExistsError: The output directory already exists.
        ValueError: No runs are supplied or report evidence is invalid.
    """
    require(reports, "at least one measured run is required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    measured = {
        "schema_version": SCHEMA,
        "runs": reports,
        "max_sample_age_seconds": max_sample_age,
        "context": {},
        "provenance": provenance,
        "interpretation": (
            "captured workload execution and workload CPU, not whole-node utilization or power; "
            "matching arrival plans are execution repetitions, not independent workload seeds"
        ),
    }
    forecasts = [] if forecast_report is None else [forecast_report]
    payload = {
        "schema_version": "opendc-combined-evidence-v1",
        "results": [],
        "measured_reports": [measured],
        "forecast_reports": forecasts,
        "render_options": {"forecast_seed": None},
    }
    (output / "metrics.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    audit = render_report(
        results=[],
        output=output / "report.pdf",
        measured_reports=[measured],
        forecast_reports=forecasts,
    )
    (output / "comparison.json").write_text(
        json.dumps(audit, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    notes = [
        "# Image-batch captured-run report",
        "",
        "Each run retains its own planned arrivals and captured runtime evidence. "
        "Per-run distributions and coverage are reported without requiring matching schedules.",
        "",
    ]
    for index, report in enumerate(reports, 1):
        s = report["summary"]
        directory = output / f"{index:02d}-{re.sub(r'[^A-Za-z0-9_.-]', '_', s['run_id'])[:80]}"
        directory.mkdir()
        notes += ["```text", summary_text(report).rstrip(), "```", ""]
        correction = s["pressure_corrections"]
        notes += [
            "Pressure correction: excluded "
            f"{correction['excluded_terminal_pod_observations']} terminal-Pod appearances "
            f"across {correction['affected_jobs']} Jobs using captured Succeeded/Failed "
            f"phases. "
            "Original input files are unchanged.",
            "",
        ]
        notes += [f"- {warning}" for warning in s["warnings"]] or ["No input warnings."]
        notes.append("")
        arrivals, jobs, pressure = report["arrivals"], report["jobs"], report["pressure"]
        write_csv(
            directory / "requests.csv",
            arrivals,
            [
                "batch_index",
                "endpoint_batch_id",
                "request_id",
                "job_name",
                "planned_seconds",
                "actual_seconds",
                "lag_ms",
                "outcome",
            ],
        )
        write_csv(
            directory / "jobs.csv",
            jobs,
            [
                "batch_index",
                "job_uid",
                "job_name",
                "request_id",
                "worker",
                "submitted",
                "start",
                "finish",
                "completed",
                "queue_seconds",
                "execution_seconds",
                "sample_count",
            ],
        )
        write_csv(directory / "pressure.csv", pressure, list(pressure[0]))
    export_matched_comparisons(reports, output)
    if forecast_report is not None:
        export_forecasts(forecast_report, output)
        notes += [
            "Forecast pages describe separately captured evidence; see forecast-evaluation.json, "
            "forecast-report.json and forecast-scores.csv for numerical values.",
            "",
        ]
    notes += [
        "## Interpretation",
        "",
        "Queue wait includes scheduling and container startup. Distributions include completed "
        "Jobs only. "
        "CPU is selected-run image-batch workload CPU, not total node utilization. "
        f"Raw source samples are held forward for at most {max_sample_age:g} seconds within "
        f"execution. "
        "Partial sums are marked separately; gaps do not mean zero. CPU rates are not clamped "
        "to requests. "
        "Pressure is sampled; peaks between snapshots can be missed. Cross-host alignment "
        "assumes synchronized VM clocks. "
        "Quantile p95 uses the nearest rank. Synthetic repeated inference is a demo load "
        "multiplier.",
        "Pressure excludes captured Succeeded/Failed Pods, correcting older observer "
        "classifications. "
        "Per-run pressure_corrections in summary.json record the exclusions; input logs remain "
        "unchanged.",
        "Kubernetes lifecycle timestamps have one-second resolution and sample counts are "
        "integers. "
        "Two decimal places are a consistent display convention for statistics, not additional "
        "measurement precision. "
        "The sampling-coverage gap includes startup delay and stale/missing samples; it is not "
        "a direct latency measurement.",
        "",
        "See summary.json for input SHA-256 hashes, paths, plotting version, and analysis "
        "settings. "
        "metrics.json retains every plotted series for offline reproduction. Per-run CSV files "
        "contain the measured values; Job timestamp columns use Unix seconds.",
    ]
    (output / "summary.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(
        json.dumps(
            {
                "provenance": provenance,
                "matplotlib_version": matplotlib.__version__,
                "report_variant": "topics",
                "max_sample_age_seconds": max_sample_age,
                "state_gap_threshold_seconds": 3,
                "runs": [report["summary"] for report in reports],
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    """Analyze captured evidence and produce a new shared topic report.

    Args:
        argv (list[str] or None): Explicit command arguments, defaulting to process arguments.

    Returns:
        int: Zero on success, or two for invalid evidence or an operational failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint-log",
        action="append",
        type=Path,
        required=True,
        help="captured endpoint JSONL; repeat for a combined multi-run report",
    )
    parser.add_argument(
        "--observer-dir",
        type=Path,
        required=True,
        help="directory with the four observer JSONL streams",
    )
    parser.add_argument(
        "--run-id", help="select one workload-run ID (default: all runs in endpoint logs)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory for PDF, Markdown, JSON, and CSV files",
    )
    parser.add_argument(
        "--max-sample-age-seconds",
        type=float,
        default=10,
        help="maximum forward hold of CPU source samples (default: 10 seconds)",
    )
    parser.add_argument("--forecast-dir", type=Path, help="append saved forecast accuracy pages")
    parser.add_argument(
        "--forecast-observer-dir",
        type=Path,
        help="observer capture for the forecast run",
    )
    parser.add_argument(
        "--forecast-until", help="UTC arrival-experiment end; exclude shutdown/drain"
    )
    parser.add_argument(
        "--forecast-rate-bin-seconds",
        type=int,
        default=10,
        choices=(10, 20, 30),
        help="average observed and predicted rates over matching bins (display only)",
    )
    args = parser.parse_args(argv)
    try:
        forecast_args = (
            args.forecast_dir,
            args.forecast_observer_dir,
            args.forecast_until,
        )
        require(
            not any(forecast_args) or all(forecast_args),
            "supply --forecast-dir, --forecast-observer-dir and --forecast-until together",
        )
        require(
            math.isfinite(args.max_sample_age_seconds) and args.max_sample_age_seconds > 0,
            "max sample age must be finite and positive",
        )
        require(
            not args.output_dir.exists(),
            f"output directory already exists: {args.output_dir}; choose a new directory",
        )
        measured = prepare_measured(
            args.endpoint_log,
            args.observer_dir,
            run_ids=[args.run_id] if args.run_id else None,
            max_sample_age=args.max_sample_age_seconds,
        )
        reports = measured["runs"]
        provenance = {
            **measured["provenance"],
            "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "python_version": sys.version.split()[0],
        }
        forecast_report = None
        if args.forecast_dir:
            forecast_report = prepare_forecasts(
                *forecast_args, rate_bin_seconds=args.forecast_rate_bin_seconds
            )
        render(
            reports,
            args.output_dir,
            provenance,
            args.max_sample_age_seconds,
            forecast_report,
        )
        for report in reports:
            print(summary_text(report))
            for warning in report["summary"]["warnings"]:
                print(f"WARNING [{report['summary']['run_id']}]: {warning}", file=sys.stderr)
        print(f"Report: {(args.output_dir / 'report.pdf').resolve()}")
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        ImportError,
    ) as exc:
        print(
            f"Analysis failed: {exc}. Check captured input fields and Python/Matplotlib "
            f"dependencies.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
