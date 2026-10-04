"""Durable bounded orchestration for selected illustrative demo captures."""

import argparse
import json
import os
import time
import sys
from pathlib import Path

from demo_lifetime import run_phase

CAPTURE_BOUND_SECONDS = 4200
MAX_CAPTURES = 5


def next_requests(records):
    """Select only predeclared captures while preserving complete alternative trios.

    Args:
        records (list[dict]): Completed accepted captures and derived qualification gates.

    Returns:
        list[tuple]: Candidate, policy and seed requests still needed for this branch.

    Raises:
        ValueError: A completed capture identity is duplicated.
    """
    by_key = {(r["candidate"], r["arm"], r["seed"]): r for r in records}
    if len(by_key) != len(records):
        raise ValueError("duplicate completed capture")
    static = by_key.get(("A", "fixed", 72001))
    forecast = by_key.get(("A", "forecast", 72001))
    reactive = by_key.get(("A", "reactive", 72001))
    if static is None:
        wanted = [("A", "fixed", 72001), ("A", "forecast", 72001), ("A", "reactive", 72001)]
    elif not static["service_passed"] or (forecast is not None and not forecast["qualified"]):
        wanted = [("B", "fixed", 72001), ("B", "forecast", 72001), ("B", "reactive", 72001)]
    elif forecast is None:
        wanted = [("A", "forecast", 72001), ("A", "reactive", 72001)]
    elif reactive is None:
        wanted = [("A", "reactive", 72001)]
    elif reactive["qualified"]:
        wanted = [("A", "forecast", 72002), ("A", "fixed", 72002)]
    else:
        wanted = [("B", "fixed", 72001), ("B", "forecast", 72001)]
    return [key for key in wanted if key not in by_key]


def require_launch(now, closure, remaining, used):
    """Keep complete remaining workflows and failed-attempt allowance within the seal.

    Args:
        now (float): Current UTC epoch seconds.
        closure (float): Absolute protected post-capture boundary.
        remaining (int): Complete captures still required for this transition.
        used (int): Attempts already launched, including failures.

    Raises:
        ValueError: Capture counts or complete remaining time violate campaign limits.
    """
    if type(remaining) is not int or type(used) is not int:  # pylint: disable=unidiomatic-typecheck
        raise ValueError("capture counts must be integers")
    if remaining < 1 or used < 0 or used + remaining > MAX_CAPTURES:
        raise ValueError("capture allowance exhausted or invalid")
    if now + remaining * (CAPTURE_BOUND_SECONDS + 120) > closure:
        raise ValueError("complete remaining workflows do not fit protected closure")


def save_checkpoint(root, state):
    """Atomically save supervisor state before any dependent physical action.

    Args:
        root (Path): Campaign evidence directory.
        state (dict): Complete checkpoint, preserving campaign and ownership metadata.
    """
    path = root / "checkpoint.json"
    temporary = root / "checkpoint.pending"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def drive_campaign(root, capture, *, now=None):
    """Advance captures synchronously from durable results without a chat dependency.

    Args:
        root (Path): Campaign evidence directory containing checkpoint.json.
        capture (callable): Bounded physical executor taking request tuple and attempt number.
        now (callable or None): UTC clock; defaults to time.time.

    Returns:
        list[dict]: Completed accepted captures and derived case gates.

    Raises:
        ValueError: Inflight ownership, capture identity or full remaining budget is invalid.
        RuntimeError: The capture executor fails; durable ownership remains for reconciliation.
    """
    root = Path(root)
    now = now or time.time
    state = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    if state.get("active_request"):
        raise ValueError("reconcile interrupted physical attempt before restarting")
    records = state.setdefault("records", [])
    state.setdefault("attempts", 0)
    while requests := next_requests(records):
        require_launch(now(), state["closure_at_seconds"], len(requests), state["attempts"])
        request = requests[0]
        state.update(
            status="capture_running",
            active_request=list(request),
            attempts=state["attempts"] + 1,
            updated_at_seconds=now(),
        )
        save_checkpoint(root, state)
        try:
            record = capture(request, state["attempts"])
            if (record["candidate"], record["arm"], record["seed"]) != request:
                raise ValueError("capture identity differs from durable request")
        except Exception as exc:
            state.update(status="capture_failed", error=repr(exc), updated_at_seconds=now())
            save_checkpoint(root, state)
            raise
        records.append(record)
        state.update(status="capture_complete", active_request=None, updated_at_seconds=now())
        save_checkpoint(root, state)
    state.update(status="captures_complete", updated_at_seconds=now())
    save_checkpoint(root, state)
    return records


def execute_capture(root, request, attempt, environment):
    """Execute one presealed singleton matrix and independently derive matched case gates.

    Args:
        root (Path): Fresh campaign evidence directory.
        request (tuple): Candidate, policy and seed declared by the state machine.
        attempt (int): Durable one-based attempt count.
        environment (dict): Operational environment with frozen-source and analysis imports.

    Returns:
        dict: Complete accepted capture summary, matched verdict and artifact paths.

    Raises:
        RuntimeError: Capture, analysis, sender fidelity or canonical acceptance fails.
        ValueError: Metrics identify more than one capture or an unmatched comparison.
    """
    candidate, arm, seed = request
    state = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    worktree = Path(state["worktree"])
    protocol = root / "protocols/sealed" / f"{candidate}-{arm}-{seed}" / "protocol.json"
    output = root / "captures" / f"attempt-{attempt:02d}"
    logs = root / "operations/supervisor"
    logs.mkdir(exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "demo_workflow",
        "run-matrix",
        "--protocol",
        str(protocol),
        "--output",
        str(output),
    ]
    run_phase(
        command,
        logs / f"capture-{attempt:02d}.log",
        cwd=worktree,
        environment=environment,
        timeout_seconds=CAPTURE_BOUND_SECONDS,
    )
    paths = list(output.glob("experiments/*-metrics.json"))
    if len(paths) != 1:
        raise ValueError("singleton matrix did not produce exactly one metrics artifact")
    same_case = [
        r["metrics"]
        for r in state.get("records", [])
        if r["candidate"] == candidate and r["seed"] == seed
    ]
    analysis = root / "analysis" / f"attempt-{attempt:02d}"
    command = [
        sys.executable,
        str(root / "operations/scripts/campaign_metrics.py"),
        "--output",
        str(analysis),
    ]
    for path in same_case + [str(paths[0])]:
        command.extend(["--metrics", path])
    run_phase(
        command,
        logs / f"analysis-{attempt:02d}.log",
        cwd=worktree,
        environment=environment,
        timeout_seconds=120,
    )
    payload = json.loads((analysis / "metrics.json").read_text(encoding="utf-8"))
    summary = next(r for r in payload["summary"] if r["arm"] == arm)
    run = next(r for r in payload["runs"] if r["arm"] == arm)
    if not run["accepted_capture"] or not run["sender_evaluated_window"]["fidelity_passed"]:
        raise RuntimeError("capture failed observation or evaluated sender validation")
    service = summary["jobs"] > 0 and summary["deadline_fraction"] >= 0.95
    verdict = payload["seed_verdicts"][0]
    observed = any(r["observed_forecast_actions"] > 0 for r in payload["summary"])
    record = dict(
        candidate=candidate,
        arm=arm,
        seed=seed,
        service_passed=service,
        qualified=verdict["passed"] and observed,
        metrics=str(paths[0]),
        analysis=str(analysis),
        summary=summary,
        case_verdict=verdict,
        protocol=str(protocol),
    )
    print(json.dumps({"event": "capture_complete", **record}), flush=True)
    return record


def restore_original(root, environment):
    """Archive idle study state and verify restoration independently of chat availability.

    Args:
        root (Path): Fresh campaign evidence directory with exact-owned closure scripts.
        environment (dict): Operational environment for bounded preservation commands.

    Raises:
        RuntimeError: An ownership, private-save, clock or baseline preservation gate fails.
    """
    state = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    state.update(status="restoration_running", restoration_started_seconds=time.time())
    save_checkpoint(root, state)
    worktree = Path(state["worktree"])
    logs = root / "operations/supervisor"
    logs.mkdir(exist_ok=True)
    for script, bound in [
        ("archive_extension.py", 600),
        ("closure.py", 3300),
        ("original_clocks.py", 300),
        ("final_preservation.py", 600),
    ]:
        run_phase(
            [sys.executable, str(root / "operations/scripts" / script)],
            logs / (script + ".log"),
            cwd=worktree,
            environment=environment,
            timeout_seconds=bound,
        )
    run_phase(
        [
            sys.executable,
            "-m",
            "demo_workflow",
            "snapshot",
            "--continuum-config",
            "configuration/fns_demo_v1.cfg",
            "--inventory",
            "/mnt/sdb/matthijs/.continuum/inventory_vms",
            "--output",
            str(root / "operations/final-original-snapshot"),
            "--baseline",
            str(root / "operations/original-baseline"),
        ],
        logs / "final-original-snapshot.log",
        cwd=worktree,
        environment=environment,
        timeout_seconds=300,
    )
    state = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    state.update(
        status="restored_pending_export_review_push",
        infrastructure_state="originals_running_verified_study_saved_shut_off",
        restoration_completed_seconds=time.time(),
    )
    save_checkpoint(root, state)
    print(json.dumps({"event": "restoration_verified"}), flush=True)


def main():
    """Run the approved bounded campaign and always attempt exact-owned restoration.

    Raises:
        RuntimeError: Physical capture or preservation fails; evidence remains available.
        ValueError: Checkpoint ownership or complete remaining budget is invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.campaign_dir.resolve()
    state = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MPLCONFIGDIR": str(root / "mpl-cache"),
        "PYTHONPATH": os.pathsep.join(
            [
                str(root / "operations/scripts"),
                str(Path(state["worktree"]) / "application/image_batch/src"),
                state["worktree"],
            ]
        ),
    }
    try:
        drive_campaign(
            root, lambda request, attempt: execute_capture(root, request, attempt, environment)
        )
    finally:
        restore_original(root, environment)


if __name__ == "__main__":
    main()
