#!/usr/bin/env python3
"""Verify network-profile behavior from structured netperf output."""

import argparse
import json
import os
import re
from collections import defaultdict
from typing import Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEGACY_LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "network_validation")
NETWORK_VALIDATION_LOG_SUFFIX = os.path.join(".continuum", "logs", "network_validation")
RELATIVE_TOLERANCE = 0.25
LATENCY_ABSOLUTE_TOLERANCE_MS = 10.0
THROUGHPUT_ABSOLUTE_TOLERANCE_MBPS = 10.0
THROUGHPUT_STRICT_VALIDATION_MAX_MBPS = 100.0


def results_dir_for_base_path(base_path: str) -> str:
    """Return the network-validation log directory for one Continuum base path."""
    return os.path.join(os.path.expanduser(base_path), NETWORK_VALIDATION_LOG_SUFFIX)


def _latest_results_file(results_dir: str) -> str:
    """Return the newest netperf_results_*.ndjson file, or raise if none exist."""
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"Network validation log directory not found: {results_dir}")

    candidates = [
        os.path.join(results_dir, f)
        for f in os.listdir(results_dir)
        if f.startswith("netperf_results_") and f.endswith(".ndjson")
    ]
    if not candidates:
        raise FileNotFoundError(f"No netperf results files found in {results_dir}")

    return max(candidates, key=os.path.getmtime)


def latest_results_file(base_path: str = None, results_dir: str = None) -> str:
    """Return the newest structured netperf result file for a base path or directory."""
    if results_dir:
        return _latest_results_file(results_dir)
    if base_path:
        return _latest_results_file(results_dir_for_base_path(base_path))

    env_base_path = os.environ.get("CONTINUUM_BASE_PATH")
    if env_base_path:
        return _latest_results_file(results_dir_for_base_path(env_base_path))

    return _latest_results_file(LEGACY_LOG_DIR)


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

    Netperf returns latency fields in microseconds for TCP_RR. Its human-readable
    output includes header numbers such as 0.0 before the result row, so use the
    final eight numeric fields when available:

    min, mean, max, stddev, transaction_rate, p50, p90, p99.
    """
    numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+", output)
    if len(numbers) < 2:
        return 0.0
    try:
        metrics = numbers[-8:] if len(numbers) >= 8 else numbers
        return float(metrics[1]) / 1000.0
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
        has_latency_entry = any(entry.get("direction") == "latency" for entry in entries)
        has_throughput_entry = any(entry.get("direction") == "throughput" for entry in entries)

        if latency_expected is not None and has_latency_entry:
            if observed_latency <= 0:
                failures.append("%s latency result is missing or unparseable" % (scenario_key,))
                continue
            # TC profile values are one-way delays. Netperf TCP_RR measures a round trip.
            latency_expected = latency_expected * 2.0
            if not _within_tolerance(
                observed_latency, latency_expected, LATENCY_ABSOLUTE_TOLERANCE_MS
            ):
                failures.append(
                    "%s latency %.2fms is outside tolerated range for expected %.2fms"
                    % (scenario_key, observed_latency, latency_expected)
                )

        if throughput_expected is not None and has_throughput_entry:
            if observed_throughput <= 0:
                failures.append("%s throughput result is missing or unparseable" % (scenario_key,))
                continue
            if throughput_expected > THROUGHPUT_STRICT_VALIDATION_MAX_MBPS:
                continue
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
        "(defaults to latest under --base-path/.continuum/logs/network_validation, "
        "CONTINUUM_BASE_PATH, or legacy repo-local logs/network_validation).",
    )
    parser.add_argument(
        "--base-path",
        help=(
            "Continuum base_path whose .continuum/logs/network_validation "
            "directory should be used."
        ),
    )
    parser.add_argument(
        "--results-dir",
        help="Optional explicit directory containing netperf_results_*.ndjson files.",
    )
    args = parser.parse_args()

    results_file = args.results_file or latest_results_file(
        base_path=args.base_path,
        results_dir=args.results_dir,
    )
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
        "(latency uses TCP_RR round-trip expectation; constrained throughput "
        "tolerance: 25%% or 10mbps, whichever is larger)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
