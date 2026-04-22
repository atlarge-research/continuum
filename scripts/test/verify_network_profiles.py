#!/usr/bin/env python3
"""Verify network-profile behavior from structured netperf output."""

import argparse
import json
import os
import re
from collections import defaultdict
from typing import Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "network_validation")
RELATIVE_TOLERANCE = 0.25
LATENCY_ABSOLUTE_TOLERANCE_MS = 10.0
THROUGHPUT_ABSOLUTE_TOLERANCE_MBPS = 10.0


def _latest_results_file() -> str:
    """Return the newest netperf_results_*.ndjson file, or raise if none exist."""
    if not os.path.isdir(LOG_DIR):
        raise FileNotFoundError(f"Network validation log directory not found: {LOG_DIR}")

    candidates = [
        os.path.join(LOG_DIR, f)
        for f in os.listdir(LOG_DIR)
        if f.startswith("netperf_results_") and f.endswith(".ndjson")
    ]
    if not candidates:
        raise FileNotFoundError(f"No netperf results files found in {LOG_DIR}")

    return max(candidates, key=os.path.getmtime)


def _parse_throughput(output: str) -> float:
    """Very simple netperf TCP_STREAM throughput parser.

    We look for the last float in the output, which for standard netperf
    output corresponds to throughput (often in Mbit/s). This is heuristic
    but works well enough for relative comparisons.
    """
    numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+", output)
    if not numbers:
        return 0.0
    try:
        return float(numbers[-1])
    except ValueError:
        return 0.0


def _parse_latency_ms(output: str) -> float:
    """Parse mean latency from a TCP_RR `-O ...` result line.

    Netperf returns latency fields in microseconds for TCP_RR. We extract the
    mean latency (the second numeric field) and convert it to milliseconds.
    """
    numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+", output)
    if len(numbers) < 2:
        return 0.0
    try:
        return float(numbers[1]) / 1000.0
    except ValueError:
        return 0.0


def load_results(path: str) -> List[Dict]:
    """Load NDJSON netperf entries from file."""
    results: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


def group_by_scenario(results: List[Dict]) -> Dict[str, List[Dict]]:
    """Group entries by a simple scenario key derived from source/target."""
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entry in results:
        key = f"{entry.get('source','?')}->{entry.get('target','?')}"
        grouped[key].append(entry)
    return grouped


def summarize_throughput(group: List[Dict]) -> float:
    """Compute an average throughput (in arbitrary units) for throughput entries."""
    values: List[float] = []
    for entry in group:
        if entry.get("direction") != "throughput":
            continue
        tp = _parse_throughput(entry.get("output", ""))
        if tp > 0:
            values.append(tp)
    if not values:
        return 0.0
    return sum(values) / len(values)


def summarize_latency_ms(group: List[Dict]) -> float:
    """Compute average latency in milliseconds for latency entries."""
    values: List[float] = []
    for entry in group:
        if entry.get("direction") != "latency":
            continue
        latency_ms = _parse_latency_ms(entry.get("output", ""))
        if latency_ms > 0:
            values.append(latency_ms)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _within_tolerance(observed: float, expected: float, absolute_floor: float) -> bool:
    lower = max(0.0, expected - max(absolute_floor, expected * RELATIVE_TOLERANCE))
    upper = expected + max(absolute_floor, expected * RELATIVE_TOLERANCE)
    return lower <= observed <= upper


def validate_results(results: List[Dict]) -> List[str]:
    """Return validation failures for a structured netperf result set."""
    grouped = group_by_scenario(results)
    failures: List[str] = []

    for scenario_key, entries in grouped.items():
        latency_expected = next(
            (
                float(entry["expected_latency_ms"])
                for entry in entries
                if entry.get("expected_latency_ms") is not None
            ),
            None,
        )
        throughput_expected = next(
            (
                float(entry["expected_throughput_mbps"])
                for entry in entries
                if entry.get("expected_throughput_mbps") is not None
            ),
            None,
        )

        observed_latency = summarize_latency_ms(entries)
        observed_throughput = summarize_throughput(entries)

        if latency_expected is not None and observed_latency > 0:
            if not _within_tolerance(
                observed_latency, latency_expected, LATENCY_ABSOLUTE_TOLERANCE_MS
            ):
                failures.append(
                    "%s latency %.2fms is outside tolerated range for expected %.2fms"
                    % (scenario_key, observed_latency, latency_expected)
                )

        if throughput_expected is not None and observed_throughput > 0:
            if not _within_tolerance(
                observed_throughput,
                throughput_expected,
                THROUGHPUT_ABSOLUTE_TOLERANCE_MBPS,
            ):
                failures.append(
                    "%s throughput %.2fmbps is outside tolerated range for expected %.2fmbps"
                    % (scenario_key, observed_throughput, throughput_expected)
                )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Continuum network profiles using netperf results."
    )
    parser.add_argument(
        "--results-file",
        help="Optional explicit path to a netperf_results_*.ndjson file "
        "(defaults to latest in logs/network_validation/).",
    )
    args = parser.parse_args()

    results_file = args.results_file or _latest_results_file()
    print(f"Using netperf results file: {results_file}")
    results = load_results(results_file)
    if not results:
        print("No netperf entries found in results file.")
        return 1

    grouped = group_by_scenario(results)
    scenario_tp: Dict[str, float] = {
        key: summarize_throughput(entries) for key, entries in grouped.items()
    }
    scenario_latency: Dict[str, float] = {
        key: summarize_latency_ms(entries) for key, entries in grouped.items()
    }

    # Print summary for transparency
    print("Scenario summary:")
    for key in sorted(grouped):
        print(
            "  %s: latency=%.2fms throughput=%.2fmbps"
            % (key, scenario_latency.get(key, 0.0), scenario_tp.get(key, 0.0))
        )

    failures = validate_results(results)

    if failures:
        print("Network profile validation FAILED:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print(
        "Network profile validation PASSED "
        "(tolerance: 25%% or 10ms / 10mbps, whichever is larger)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
