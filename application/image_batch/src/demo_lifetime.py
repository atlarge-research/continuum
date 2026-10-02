"""Bound local orchestration phases and account for their owned process groups."""

import os
from pathlib import Path
import signal
import subprocess
import time

from opendc_inputs import write_json


PHASE_SECONDS = {"verify": 120, "archive": 300, "metrics": 120, "recovery": 300}
STOP_SECONDS = 5
PHASE_STOP_SECONDS = 2 * STOP_SECONDS


class PhaseFailure(RuntimeError):
    """A phase failed, with explicit knowledge of its remaining local process group.

    Args:
        message (str): Failure and evidence location.
        group_stopped (bool): Whether absence of the entire owned process group was verified.
    """

    def __init__(self, message, *, group_stopped):
        super().__init__(message)
        self.group_stopped = group_stopped


def group_exists(group):
    """Check the entire group, retaining uncertain permission or operating-system failures.

    Args:
        group (int): Process group created by this supervisor.

    Returns:
        bool: True when the group exists or its absence cannot be established.
    """
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def stop_group(process):
    """Bound both stop attempts and verify descendants independently of the leader.

    Args:
        process (subprocess.Popen): Leader launched with start_new_session=True.

    Returns:
        tuple[bool, list[dict]]: Verified group absence and retained stop outcomes.
    """
    attempts = []
    for number in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + STOP_SECONDS
        attempt = {"signal": int(number)}
        try:
            os.killpg(process.pid, number)
            attempt["sent"] = True
        except ProcessLookupError:
            attempt["already_absent"] = True
        except OSError as exc:
            attempt["error"] = str(exc)
        try:
            attempt["leader_returncode"] = process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            attempt["leader_wait_timeout"] = True
        while group_exists(process.pid):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                attempt["group_grace_expired"] = True
                break
            time.sleep(min(0.05, remaining))
        else:
            attempt["group_stopped"] = True
            attempts.append(attempt)
            return True, attempts
        attempts.append(attempt)
    return False, attempts


def run_phase(command, log, *, timeout_seconds, cwd=None, environment=None):
    """Run a complete phase with a deadline, durable failure record and owned-group stop.

    Args:
        command (list[str]): Executable and argument vector.
        log (Path): New stdout/stderr destination; sibling status JSON is also retained.
        timeout_seconds (float): Phase execution budget, excluding the bounded stop allowance.
        cwd (Path or None): Child working directory.
        environment (dict or None): Child environment, or None to inherit the current one.

    Raises:
        PhaseFailure: Execution failed, timed out or left descendants; no next phase is implied.
        FileExistsError: An existing log or status would be overwritten.
        OSError: Evidence cannot be created before launch or after successful group termination.
    """
    log = Path(log)
    status_path = log.with_suffix(".status.json")
    if log.exists() or status_path.exists():
        raise FileExistsError(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "command": command,
        "timeout_seconds": timeout_seconds,
        "started_at_seconds": time.time(),
        "status": "starting",
    }
    write_json(status_path, status)
    with log.open("xb") as stream:
        try:
            # Lifetime extends through explicit group termination and durable failure recording.
            process = subprocess.Popen(  # pylint: disable=consider-using-with
                command,
                cwd=cwd,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            status.update(status="launch_failed", error=str(exc), process_group_stopped=True)
            write_json(status_path, status)
            raise PhaseFailure(f"phase launch failed: {status_path}", group_stopped=True) from exc
        status["process_group"] = process.pid
        try:
            write_json(status_path, status)
            status["returncode"] = process.wait(timeout=timeout_seconds)
            status["status"] = "complete" if status["returncode"] == 0 else "failed"
            if status["status"] == "complete" and group_exists(process.pid):
                status["status"] = "descendants_remain"
        except subprocess.TimeoutExpired:
            status["status"] = "timeout"
        except OSError as exc:
            status.update(status="record_failed", error=str(exc))
        if status["status"] == "complete":
            status.update(process_group_stopped=True, finished_at_seconds=time.time())
            write_json(status_path, status)
            return
        # Attempt the durable record before signaling, but a full disk must not skip stopping.
        try:
            write_json(status_path, status)
        except OSError as exc:
            status["record_error"] = str(exc)
        finally:
            stopped, attempts = stop_group(process)
        status.update(
            process_group_stopped=stopped,
            stop_attempts=attempts,
            finished_at_seconds=time.time(),
        )
        try:
            write_json(status_path, status)
        except OSError as exc:
            status["record_error"] = str(exc)
        detail = "; evidence write failed" if "record_error" in status else ""
        raise PhaseFailure(
            f'phase {status["status"]}: {status_path}{detail}', group_stopped=stopped
        )
