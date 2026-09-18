"""Bounded child-process execution and Linux resource evidence."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time


def read_cgroup(root=Path("/sys/fs/cgroup")):
    """Read the mounted cgroup, keeping absent counters distinct from zero.

    In the container this is the container cgroup. Outside a cgroup namespace,
    the mounted root may be an ancestor; run_process records membership too.

    Args:
        root (Path): Mounted cgroup root, overridable for v1/v2 test fixtures.

    Returns:
        dict: Counter snapshot with CPU seconds, memory bytes, raw limits/events
            and unavailable paths. Missing counters remain None, not zero.
    """
    root = Path(root)
    unavailable = []

    def read(relative):
        """Read a cgroup file, recording unreadable paths and returning None.

        Args:
            relative (str): Counter path relative to the mounted cgroup root.

        Returns:
            str or None: Stripped file contents, or None when the file cannot be read.
        """
        try:
            return (root / relative).read_text().strip()
        except OSError:
            unavailable.append(relative)
            return None

    def number(relative):
        """Read an integer counter while preserving an unavailable value as None.

        Args:
            relative (str): Integer counter path relative to the mounted cgroup root.

        Returns:
            int or None: Parsed counter, or None when the file is unavailable.
        """
        raw = read(relative)
        return int(raw) if raw is not None else None

    if (root / "cgroup.controllers").exists():
        version = 2
        cpu = dict(line.split() for line in (read("cpu.stat") or "").splitlines())
        usage = int(cpu["usage_usec"]) / 1e6 if "usage_usec" in cpu else None
        peak = number("memory.peak")
        current = number("memory.current")
        limits = {"cpu": read("cpu.max"), "memory": read("memory.max")}
        events = read("memory.events")
    else:
        version = 1
        cpu_directory = "cpuacct" if (root / "cpuacct").exists() else "cpu,cpuacct"
        raw_usage = number(f"{cpu_directory}/cpuacct.usage")
        usage = raw_usage / 1e9 if raw_usage is not None else None
        cpu = {"cpuacct.stat": read(f"{cpu_directory}/cpuacct.stat")}
        peak = number("memory/memory.max_usage_in_bytes")
        current = number("memory/memory.usage_in_bytes")
        limits = {"memory": read("memory/memory.limit_in_bytes")}
        events = read("memory/memory.failcnt")
    return {"version": version, "scope": "mounted cgroup root", "cpu_usage_seconds": usage,
            "memory_peak_bytes": peak, "memory_current_bytes": current,
            "cpu_stat": cpu, "memory_events": events, "limits": limits, "unavailable": unavailable}


def _signal_group(pid, signum):
    """Signal the child's process group, tolerating a group that already exited.

    Args:
        pid (int): Process-group ID of the child session leader.
        signum (int): Signal to send to every process in the group.
    """
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def run_process(command, directory, timeout_seconds):
    """Run a child in its own session and capture logs, exit status and resources.

    Timeout or SIGTERM/SIGINT triggers group termination, followed by SIGKILL
    after one second even if the group leader has already exited. Reap the
    direct child and restore the caller's handlers. Run from the main thread
    on Linux because signal handlers and wait4 are required.

    Args:
        command (list): Executable and arguments, invoked without a shell.
        directory (str or Path): Existing working directory receiving stdout.log
            and stderr.log; these log files are overwritten if already present.
        timeout_seconds (float): Positive wall-clock deadline in seconds.

    Returns:
        dict: Child exit/signal or launch error, wall time, wait4 CPU/RSS usage,
            and cgroup snapshots. Missing measurements remain explicit.

    Raises:
        ValueError: The timeout is nonpositive, or signal handlers cannot be installed.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    directory = Path(directory)
    started = time.monotonic()
    result = {"command": command, "exit_code": None, "signal": None, "timed_out": False,
              "launch_error": None, "received_signal": None, "cgroup_before": read_cgroup()}
    process = None
    handlers = {}
    received = []

    def handle_signal(signum, _frame):
        """Accept Python's signal callback arguments and defer termination to the loop.

        Args:
            signum (int): Signal received by the supervisor.
            _frame (frame or None): Interpreter signal frame; unused by this handler.
        """
        received.append(signum)

    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                handlers[signum] = signal.signal(signum, handle_signal)
            process = subprocess.Popen(command, cwd=directory, stdout=stdout, stderr=stderr, start_new_session=True)
            termination_started = None
            reaped = None
            while True:
                now = time.monotonic()
                if termination_started is None and (received or now - started >= timeout_seconds):
                    result["timed_out"] = not received
                    result["received_signal"] = received[0] if received else None
                    termination_started = now
                    _signal_group(process.pid, signal.SIGTERM)
                if reaped is None:
                    pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        reaped = (status, usage)
                if termination_started is not None:
                    # The group can outlive its leader; always send KILL after grace.
                    if now - termination_started >= 1:
                        _signal_group(process.pid, signal.SIGKILL)
                        if reaped is not None:
                            break
                elif reaped is not None:
                    break
                time.sleep(0.02)
            status, usage = reaped
            process.returncode = os.waitstatus_to_exitcode(status)
            result.update({"exit_code": process.returncode,
                           "signal": -process.returncode if process.returncode < 0 else None,
                           "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
                           "max_rss_bytes": usage.ru_maxrss * 1024})
        except OSError as exc:
            result["launch_error"] = str(exc)
            stderr.write((str(exc) + "\n").encode())
        finally:
            if process is not None:
                _signal_group(process.pid, signal.SIGKILL)
                if process.returncode is None:
                    process.wait()
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
    result["wall_seconds"] = time.monotonic() - started
    result["cgroup_after"] = read_cgroup()
    before = result["cgroup_before"]["cpu_usage_seconds"]
    after = result["cgroup_after"]["cpu_usage_seconds"]
    result["cgroup_cpu_seconds"] = after - before if before is not None and after is not None else None
    result["cgroup_membership"] = Path("/proc/self/cgroup").read_text()
    return result
