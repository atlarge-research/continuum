#!/usr/bin/env python3
"""Cloud-safe host prerequisite check for local-QEMU Kata suites."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _mem_total_gb() -> float:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        raise RuntimeError("/proc/meminfo is not available")
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / (1024 * 1024)
    raise RuntimeError("MemTotal not found in /proc/meminfo")


def _nested_kvm_state() -> str | None:
    for candidate in (
        Path("/sys/module/kvm_intel/parameters/nested"),
        Path("/sys/module/kvm_amd/parameters/nested"),
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-cores", type=int, default=16)
    parser.add_argument("--min-memory-gb", type=float, default=160.0)
    parser.add_argument("--require-nested-kvm", action="store_true")
    args = parser.parse_args()

    failures = []
    if not Path("/dev/kvm").exists():
        failures.append("MISSING /dev/kvm")

    cores = os.cpu_count() or 0
    if cores < args.min_cores:
        failures.append("ERROR only %s CPU core(s) available; require %s" % (cores, args.min_cores))

    try:
        memory_gb = _mem_total_gb()
        if memory_gb < args.min_memory_gb:
            failures.append(
                "ERROR only %.1f GiB memory available; require %.1f GiB"
                % (memory_gb, args.min_memory_gb)
            )
    except RuntimeError as exc:
        failures.append("ERROR %s" % (exc,))

    nested = _nested_kvm_state()
    if args.require_nested_kvm and nested not in ("1", "Y", "y"):
        failures.append("ERROR nested KVM is not enabled")

    if failures:
        for failure in failures:
            print(failure)
        return 1

    print(
        "OK Kata host prerequisites: /dev/kvm present, %s cores, %.1f GiB memory, nested=%s"
        % (cores, _mem_total_gb(), nested or "unknown")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
