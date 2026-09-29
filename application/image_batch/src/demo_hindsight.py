"""Bounded hindsight at predeclared cutoffs after the frozen physical matrix completes."""

import argparse
import json
from pathlib import Path
import subprocess
import time

from closed_loop_counterfactuals import prepare_known_ranking
from closed_loop_policy import select_action
from demo_tuning import execute_native
from demo_workflow import cleanup_complete, matrix_commands, verify_protocol
from opendc_inputs import write_json
from opendc_validation import prepare_validation_suite


def evaluate_cycle(capture, tick, output, image):
    """Compare sampled and known arrivals with identical causal state and eligible actions.

    Args:
        capture (Path): Completed forecast capture.
        tick (int): Predeclared original controller cycle, never replaced when missing.
        output (Path): New per-cutoff diagnostic destination.
        image (str): Frozen native wrapper image.

    Returns:
        dict: Local objective choices or an explicit missing-evidence exclusion.

    Raises:
        ValueError: Known arrivals change causal calibration, membership or eligible actions.
        FileExistsError: Diagnostic output already exists.
        RuntimeError: Native execution fails, retaining its command and artifacts.
    """
    original = capture / "controller" / f"cycle-{tick:04d}"
    if not (original / "scores.json").exists():
        return {"tick": tick, "excluded": "original cycle has no complete native scores"}
    events = [
        json.loads(line) for line in (capture / "controller/journal.jsonl").read_text().splitlines()
    ]
    proposal = next(
        (row for row in events if row["event"] == "cycle.proposal" and row["tick"] == tick), None
    )
    if proposal is None or not proposal["forecast_valid"]:
        return {"tick": tick, "excluded": "original forecast proposal missing or invalid"}
    invocation = json.loads((capture / "invocation.json").read_text())
    config = json.loads((capture / "controller/identity.json").read_text())["settings"]["config"]
    manifest = json.loads((original / "suite/manifest.json").read_text())
    config.update(
        active_workers=manifest["active_workers"], draining_workers=manifest["draining_workers"]
    )
    output.mkdir(parents=True, exist_ok=False)
    prepare_validation_suite(
        original / "forecast",
        capture / "observer",
        config,
        output / "known-unchanged",
        horizon_seconds=invocation["horizon_seconds"],
        scenarios=1,
        arrival_source="known-arrival",
        initialization_mode="pinned-trace",
    )
    prepare_known_ranking(output / "known-unchanged", original / "suite", output / "known-suite")
    known = execute_native(
        output / "known-suite",
        output / "known-native",
        image,
        scenarios=1,
        timeout_seconds=invocation["native_timeout_seconds"],
        allocation_seconds=invocation["allocation_seconds"],
    )
    age = proposal["recorded_at_ns"] / 1e9 - proposal["cutoff_seconds"]
    primary = json.loads((original / "scores.json").read_text())
    choices = {}
    for name, scores, count in (("sampled", primary, invocation["scenarios"]), ("known", known, 1)):
        choices[name] = select_action(
            scores,
            {},
            now_seconds=proposal["recorded_at_ns"] / 1e9,
            decision_age=age,
            scenarios=count,
            age_budget_seconds=invocation["decision_age_seconds"],
            deadline_seconds=invocation["deadline_seconds"],
            deadline_fraction=invocation["deadline_fraction"],
        )
    result = dict(
        tick=tick,
        cutoff_seconds=proposal["cutoff_seconds"],
        decision_age_seconds=age,
        choices=choices,
        agrees=choices["sampled"]["action"] == choices["known"]["action"],
        eligible_candidates=len([row for row in known if row.get("scenarios")]),
        actual_proposal=proposal["proposal"],
    )
    write_json(output / "comparison.json", result)
    return result


def run_diagnostics(protocol_path, evaluation_root, output):
    """Run at most four frozen cutoffs per forecast arm after all physical captures restore.

    Args:
        protocol_path (Path): Sealed evaluation protocol declaring hindsight_ticks.
        evaluation_root (Path): Matrix output containing completed captures.
        output (Path): New hindsight evidence root.

    Returns:
        dict: All prescribed cutoffs, preserving failed and unavailable attempts.

    Raises:
        ValueError: Protocol, bounded cutoff inventory or physical completion is invalid.
        FileExistsError: Diagnostic output already exists.
    """
    protocol = verify_protocol(protocol_path)
    ticks = protocol.get("hindsight_ticks", [])
    if (
        not ticks
        or len(ticks) > 4
        or len(set(ticks)) != len(ticks)
        or any(not isinstance(tick, int) or isinstance(tick, bool) or tick < 1 for tick in ticks)
    ):
        raise ValueError("protocol must predeclare one to four unique positive hindsight ticks")
    commands = matrix_commands(protocol, evaluation_root)
    for row in commands:
        cleanup = Path(row["output"]) / "cleanup.json"
        if not cleanup.exists() or not cleanup_complete(json.loads(cleanup.read_text())):
            raise ValueError("physical matrix has not completed and restored")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "protocol": str(protocol_path),
        "expected_ticks": ticks,
        "runs": [],
        "interpretation": "Known arrivals only; causal profiles, backlog and candidate set "
        "are preserved. Per-cutoff choices are not trajectory regret, deployable foresight "
        "or measured physical benefit. Single-candidate agreement is uninformative.",
    }
    for row in commands:
        if row["arm"] != "forecast":
            continue
        capture = Path(row["output"])
        run = {"run_id": capture.name, "comparisons": []}
        result["runs"].append(run)
        for tick in ticks:
            if time.time() + 180 > protocol["closure_at_seconds"]:
                comparison = {"tick": tick, "excluded": "protected closure reserve"}
            else:
                try:
                    comparison = evaluate_cycle(
                        capture,
                        tick,
                        output / capture.name / f"cycle-{tick:04d}",
                        protocol["native_image"],
                    )
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    comparison = {"tick": tick, "excluded": str(exc)}
            run["comparisons"].append(comparison)
            write_json(output / "summary.json", result)
    return result


def main():
    """Run the predeclared optional diagnostic after physical measurement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_diagnostics(args.protocol, args.evaluation_root, args.output)))


if __name__ == "__main__":
    main()
