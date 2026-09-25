"""Resume only the controller attached to a preserved, still-running capture."""

import argparse
import json
from pathlib import Path
import time

from capture_run import CaptureSession
from closed_loop_controller import Controller


def attach(output):
    """Validate preserved capture identity before attaching controller I/O.

    This never replays arrivals, deploys resources, changes initial cordons or
    overwrites capture artifacts. Normal controller guards and durable intent
    reconciliation still apply; namespace ownership and the journal lock remain
    mandatory. Capture collection/cleanup stays with the capture owner.

    Args:
        output (Path): Existing capture evidence directory.

    Returns:
        CaptureSession: Attached transport with the original observer Pod identity.

    Raises:
        ValueError: The capture was uncontrolled, cleaned up or its observer was replaced.
    """
    values = json.loads((output / "invocation.json").read_text())
    if values.get("control_arm", "none") == "none" or (output / "cleanup.json").exists():
        raise ValueError("only a preserved controlled capture can be resumed")
    values["output"] = output
    values["source_dir"] = Path(values["source_dir"])
    session = CaptureSession(argparse.Namespace(**values))
    recorded = json.loads((output / "pod-start.json").read_text())
    session.pod_name = recorded["metadata"]["name"]
    current = session.get("pod", session.pod_name, "-n", session.namespace)
    if current["metadata"]["uid"] != recorded["metadata"]["uid"] or any(
        item.get("restartCount") for item in current["status"].get("containerStatuses", [])
    ):
        raise ValueError("capture observer identity or uninterrupted lifetime changed")
    return session


def main():
    """Resume causal decisions without restarting the workload or bypassing journal recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-output", type=Path, required=True)
    args = parser.parse_args()
    session = attach(args.capture_output.resolve())
    loop = Controller(session)
    try:
        # Ownership is reverified. Existing native image was already staged before arrivals.
        loop.prepare(stage_runner=False)
        loop.recover(loop.fresh())
        while True:
            loop.maybe_tick()
            jobs, sample = session.observe()
            if loop.origin is not None:
                finish = loop.origin + session.args.period_seconds * session.args.cycles
                if time.time() >= finish + 600 or (
                    time.time() >= finish and sample["completed"] + sample["failed"] == len(jobs)
                ):
                    break
            time.sleep(5)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
