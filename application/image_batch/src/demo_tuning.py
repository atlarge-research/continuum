"""Bounded offline development probes using preserved causal capture prefixes."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from closed_loop_guards import snapshot_view
from closed_loop_policy import select_action
from closed_loop_runner import load_scores
from demo_configuration import EXPERIMENT_DEFAULTS, validate_experiment
from forecast_trace import milliseconds
from forecast_workload import Settings, run_once
from opendc_inputs import write_json
from opendc_scenarios import prepare_suite


class NativeCleanupError(RuntimeError):
    """An owned local native container could not be verified absent after timeout."""


def _cleanup_timed_out_container(name):
    """Remove only the named attempt and retain bounded cleanup/absence evidence.

    Args:
        name (str): Unique container name assigned before the attempted native launch.

    Returns:
        dict: Removal and inventory command outcomes, including verified absence.
    """
    commands = [
        ["docker", "rm", "--force", name],
        ["docker", "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
    ]
    attempts = []
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, timeout=10, check=False)
            attempts.append(
                dict(
                    command=command,
                    exit_code=result.returncode,
                    stdout=result.stdout.decode(errors="replace"),
                    stderr=result.stderr.decode(errors="replace"),
                )
            )
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append(dict(command=command, error=str(exc)))
    inventory = attempts[-1]
    return dict(
        container_name=name,
        attempts=attempts,
        verified_absent=inventory.get("exit_code") == 0 and not inventory["stdout"].strip(),
    )


def execute_native(suite, output, image, *, scenarios, timeout_seconds, allocation_seconds):
    """Run a local isolated native batch while preserving unsuccessful attempts.

    Args:
        suite (Path): Prepared immutable native suite.
        output (Path): Fresh command, log and result directory.
        image (str): Exact locally available wrapper image.
        scenarios (int): Required shared future count.
        timeout_seconds (float): Native process time limit.
        allocation_seconds (float): Shared allocation scoring window.

    Returns:
        list[dict]: Verified complete candidate scores.

    Raises:
        FileExistsError: Evidence output already exists.
        RuntimeError: Native execution failed, with stdout/stderr retained.
        subprocess.TimeoutExpired: Outer deadline elapsed and the owned container is absent.
        NativeCleanupError: Timeout cleanup could not verify absence; stop further native work.
        OSError: Evidence could not be written; timeout cleanup is still attempted.
    """
    suite, output = Path(suite).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    container_name = "fns-opendc-local-" + uuid.uuid4().hex
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--pull=never",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        "none",
        "--read-only",
        "--hostname",
        "opendc-controlled",
        "--add-host",
        "opendc-controlled:127.0.0.1",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=256m",
        "--cpus=1",
        "--memory=2g",
        "-v",
        f"{suite}:/inputs:ro",
        "-v",
        f"{output}:/results",
        "--entrypoint",
        "python",
        image,
        "/app/opendc_native_batch.py",
        "--suite-dir",
        "/inputs",
        "--output-dir",
        "/results/batch",
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    write_json(output / "command.json", command)
    started = time.monotonic()
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout_seconds + 60, check=False
        )
    except subprocess.TimeoutExpired as exc:
        outcome = dict(
            status="outer_timeout",
            container_name=container_name,
            elapsed_seconds=time.monotonic() - started,
        )
        outcome["cleanup"] = _cleanup_timed_out_container(container_name)
        try:
            (output / "stdout.txt").write_bytes(exc.stdout or b"")
            (output / "stderr.txt").write_bytes(exc.stderr or b"")
            write_json(output / "container.json", outcome)
        finally:
            if not outcome["cleanup"]["verified_absent"]:
                raise NativeCleanupError(
                    f"native timeout cleanup remains unverified: {output}"
                ) from exc
        raise
    (output / "stdout.txt").write_bytes(result.stdout)
    (output / "stderr.txt").write_bytes(result.stderr)
    write_json(
        output / "container.json",
        dict(exit_code=result.returncode, elapsed_seconds=time.monotonic() - started),
    )
    if result.returncode:
        raise RuntimeError(f"offline native container failed: {output}")
    scores, _ = load_scores(
        output / "batch", scenarios=scenarios, allocation_seconds=allocation_seconds
    )
    write_json(output / "scores.json", scores)
    return scores


def probe(capture, tick, settings, output, image):
    """Evaluate a development configuration on one retained historical observation prefix.

    This measures preparation/native cost and revised candidate behavior. The
    historical arrival pattern is not a fresh physical evaluation of new timing.
    No historical artifacts or live cluster resources are changed.

    Args:
        capture (Path): Historical capture with a saved causal controller cycle.
        tick (int): Preselected original cycle identity.
        settings (dict): Complete numerical development configuration.
        output (Path): New trial evidence directory.
        image (str): Locally available exact native wrapper image.

    Returns:
        dict: Timing, policy choice and immutable historical input provenance.

    Raises:
        FileExistsError: Trial output already exists.
        ValueError: Forecast readiness, settings or native scoring are invalid.
        RuntimeError: Native execution fails, preserving its attempt.
    """
    validate_experiment(settings)
    output.mkdir(parents=True, exist_ok=False)
    original = capture / "controller" / f"cycle-{tick:04d}"
    saved = json.loads((original / "forecast/forecast.json").read_text())
    config = json.loads((capture / "controller/identity.json").read_text())["settings"]["config"]
    config.update(settings)
    forecast_settings = Settings(
        run_id=saved["settings"]["run_id"],
        origin_ms=saved["settings"]["origin_ms"],
        period_seconds=settings["period_seconds"],
        warmup_periods=settings["warmup_cycles"],
        horizon_seconds=settings["horizon_seconds"],
        scenarios=settings["scenarios"],
        seed=settings["scenario_seed"],
    )
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    provenance = dict(
        role="development-offline",
        capture=str(capture),
        tick=tick,
        settings=settings,
        native_image=image,
        native_image_id=image_id,
        source_commit=commit,
        interpretation=(
            "Historical workload prefix for timing and behavior only; "
            "no new physical outcomes or matched forecast-quality comparison."
        ),
    )
    write_json(output / "invocation.json", provenance)
    started = time.monotonic()
    status, _ = run_once(
        original / "observer",
        output / "forecast",
        milliseconds(saved["requested_cutoff"]),
        forecast_settings,
        simulation_inputs=True,
    )
    if status["status"] != "ready" or status.get("simulation_inputs", {}).get("status") != "ready":
        raise ValueError("development forecast not ready; preserve this trial")
    state = json.loads((output / "forecast/state.json").read_text())
    view = snapshot_view(state, config, now_seconds=milliseconds(status["cutoff"]) / 1000)
    config.update(active_workers=view["active_workers"], draining_workers=view["draining_workers"])
    write_json(output / "worker-config.json", config)
    prepare_suite(
        output / "forecast", original / "observer", config, output / "suite", "pinned-trace"
    )
    prepared = time.monotonic()
    scores = execute_native(
        output / "suite",
        output / "native",
        image,
        scenarios=settings["scenarios"],
        timeout_seconds=settings["native_timeout_seconds"],
        allocation_seconds=settings["allocation_seconds"],
    )
    elapsed = time.monotonic() - started
    choice = select_action(
        scores,
        {},
        now_seconds=time.time(),
        decision_age=elapsed,
        scenarios=settings["scenarios"],
        age_budget_seconds=settings["decision_age_seconds"],
        deadline_seconds=settings["deadline_seconds"],
        deadline_fraction=settings["deadline_fraction"],
    )
    result = dict(
        **provenance,
        preparation_seconds=prepared - started,
        total_seconds=elapsed,
        choice=choice,
        status="completed",
    )
    write_json(output / "summary.json", result)
    return result


def main():
    """Run at most six explicitly numbered offline candidates in one study root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--tick", type=int, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial", type=int, choices=range(1, 7), required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    supplied = json.loads(args.settings.read_text())
    if set(supplied) - set(EXPERIMENT_DEFAULTS):
        parser.error("unknown development settings")
    settings = {**EXPERIMENT_DEFAULTS, **supplied}
    result = probe(
        args.capture.resolve(),
        args.tick,
        settings,
        args.output.resolve() / f"offline-{args.trial:02d}",
        args.image,
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
