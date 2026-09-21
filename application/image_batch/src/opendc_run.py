"""Prepare or execute one auditable, controlled OpenDC experiment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import pyarrow as pa

from opendc_inputs import (
    COMMIT,
    CONTRACT,
    PROVISIONAL_CONTRACT,
    SOURCE_ARCHIVE_SHA256,
    VERSION,
    file_hashes,
    prepare,
    verify_inputs,
    write_json,
)
from opendc_process import run_process
from opendc_results import validate_results, validate_provisional_results


def utc_now():
    """Return the current UTC time as an ISO 8601 string for execution records.

    Returns:
        str: Current UTC timestamp including its timezone offset.
    """
    return datetime.now(timezone.utc).isoformat()


def runtime_provenance():
    """Return source identity, runtime versions, source hashes and JVM settings.

    Include Java's release metadata when available; local tests need no JRE.

    Returns:
        dict: OpenDC/source identity, runtime versions, JVM options and available Java metadata.
    """
    root = Path(__file__).resolve().parent
    sources = list(root.glob("opendc_*.py")) + [root / "forecast_trace.py"]
    result = {
        "opendc_version": VERSION,
        "opendc_commit": COMMIT,
        "opendc_source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "python_version": platform.python_version(),
        "pyarrow_version": pa.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "java_opts": os.environ.get("JAVA_OPTS", ""),
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        },
    }
    java_release = Path(os.environ.get("JAVA_HOME", "/opt/java/openjdk")) / "release"
    if java_release.is_file():
        result["java_release"] = java_release.read_text()
    return result


def _run_prepared(inputs, output, timeout_seconds, runner, manifest):
    """Copy verified inputs, invoke the SDK CLI and update the execution record.

    Resolve experiment paths into the copied inputs, supervise one process,
    and validate native output only after a successful process exit. Mutate
    manifest in place and return the runner exit code; execute finalizes it.

    Args:
        inputs (Path): Prepared input directory to verify and copy.
        output (Path): New execution directory already created by execute.
        timeout_seconds (float): Wall-clock process deadline in seconds.
        runner (str): OpenDC executable path.
        manifest (dict): Started execution record, updated in place.

    Returns:
        int: 0 for validated success, 1 for process/output failure, 124 for timeout,
            or 128 plus the received signal. Input errors propagate to execute.
    """
    input_manifest = verify_inputs(inputs)
    manifest["contract"] = input_manifest["contract"]
    shutil.copytree(inputs, output / "inputs")
    verify_inputs(output / "inputs")
    manifest["input_manifest"] = input_manifest
    config = json.loads((output / "inputs/experiment.json").read_text())
    config["topologies"][0]["importFrom"] = str(output / "inputs/topology.json")
    config["workloads"][0]["source"] = {"type": "uri", "uri": (output / "inputs/trace").as_uri()}
    write_json(output / "experiment.json", config)
    write_json(output / "execution.json", manifest)
    if input_manifest["contract"] == PROVISIONAL_CONTRACT:
        case = json.loads((output / "inputs/case.json").read_text())
        if not case["tasks"]:
            # The pinned SDK requires a first arrival. An empty cohort has no
            # native execution; the evaluator accounts for included-worker idle.
            process = {
                "execution_kind": "analytical_empty",
                "launched": False,
                "exit_code": 0,
                "timed_out": False,
                "received_signal": None,
                "launch_error": None,
                "wall_seconds": 0,
                "cpu_total_seconds": 0,
                "peak_rss_bytes": 0,
            }
            manifest["process"] = process
            manifest["validation"] = {
                "status": "passed",
                "kind": "analytical_empty",
                "tasks": [],
                "task_count": 0,
                "scope": case["scope"],
                "native_time_origin_ms": 0,
                "initialization_mode": "provisional-trace",
                "interpretation": "empty included cohort; no native process or completions",
            }
            manifest["status"] = "succeeded"
            write_json(output / "resources.json", process)
            return 0
    command = [
        runner,
        "--strict",
        "run",
        str(output / "experiment.json"),
        "--output",
        str(output / "simulator"),
        "--parallelism",
        "1",
        "--no-progress",
        "--no-summary",
    ]
    manifest["process"] = run_process(command, output, timeout_seconds)
    process = manifest["process"]
    write_json(output / "resources.json", process)
    if process["timed_out"]:
        manifest["status"] = "timed_out"
        return 124
    if process["received_signal"]:
        manifest["status"] = "interrupted"
        return 128 + process["received_signal"]
    if process["exit_code"] != 0:
        manifest["status"] = "failed"
        manifest["error"] = process["launch_error"] or f'OpenDC exited with {process["exit_code"]}'
        return 1
    try:
        if input_manifest["contract"] == PROVISIONAL_CONTRACT:
            case = json.loads((output / "inputs/case.json").read_text())
            manifest["validation"] = validate_provisional_results(output / "simulator", case)
        else:
            fixture = json.loads((output / "inputs/fixture.json").read_text())
            manifest["validation"] = validate_results(output / "simulator", fixture)
    except ValueError as exc:
        manifest["validation"] = {"status": "failed", "error": str(exc)}
        manifest["status"] = "failed"
        return 1
    manifest["status"] = "succeeded"
    return 0


def execute(input_dir, output_dir, timeout_seconds=120, runner="/opt/opendc/bin/opendc"):
    """Execute one prepared experiment, retaining evidence on success or failure.

    Publish a started manifest before launching, then finalize it with process
    and validation status, timestamps and artifact hashes. An external kill
    can leave the started record and partial files for Kubernetes collection.

    Args:
        input_dir (str or Path): Prepared controlled or explicitly provisional experiment
            to verify and copy.
        output_dir (str or Path): New directory, separate from the input tree.
        timeout_seconds (float): Finite positive process deadline in seconds.
        runner (str): OpenDC executable path, overridable by process tests.

    Returns:
        int: 0 for validated success, 1 for execution/output failure, 2 for
            invalid input, 124 for timeout, or 128 plus the received signal.

    Raises:
        ValueError: Timeout or input/output directory separation is invalid.
        FileExistsError: The output directory already exists.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be finite and positive")
    inputs, output = Path(input_dir).resolve(), Path(output_dir).resolve()
    if output == inputs or output.is_relative_to(inputs) or inputs.is_relative_to(output):
        raise ValueError("input and output directories must be separate")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest = {
        "contract": CONTRACT,
        "status": "started",
        "started_at": utc_now(),
        "timeout_seconds": timeout_seconds,
        "process": None,
        "validation": {"status": "not_run"},
        "provenance": runtime_provenance(),
    }
    write_json(output / "execution.json", manifest)
    try:
        code = _run_prepared(inputs, output, timeout_seconds, runner, manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        code = 2 if manifest["process"] is None else 1
        manifest["status"] = "invalid_input" if code == 2 else "failed"
        manifest["error"] = str(exc)
    manifest.update(
        {
            "finished_at": utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "runner_exit_code": code,
            "sha256": file_hashes(output, exclude=("execution.json",)),
        }
    )
    write_json(output / "execution.json", manifest)
    return code


def main(argv=None):
    """Prepare or run a fixture from CLI arguments, printing a JSON status summary.

    Return the operation's exit code, or 2 for handled input/filesystem errors.
    argv defaults to the process arguments.

    Args:
        argv (list[str] or None): CLI arguments; None uses the process arguments.

    Returns:
        int: Preparation/execution exit code, or 2 for handled input/filesystem errors.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="create an empty-state synthetic experiment")
    preparation.add_argument("--fixture", choices=("controlled", "memory"), default="controlled")
    preparation.add_argument("--output-dir", type=Path, required=True)
    run = commands.add_parser("run", help="execute exactly one prepared experiment")
    run.add_argument("--input-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.fixture, args.output_dir)
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "fixture": args.fixture,
                        "output_dir": str(args.output_dir),
                    }
                )
            )
            return 0
        code = execute(args.input_dir, args.output_dir, args.timeout_seconds)
        manifest = json.loads((args.output_dir / "execution.json").read_text())
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "output_dir": str(args.output_dir),
                    "exit_code": code,
                    "error": manifest.get("error") or manifest["validation"].get("error"),
                }
            )
        )
        return code
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
