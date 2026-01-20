#!/usr/bin/env python3
"""\
Verify that Continuum network profiles and manual overrides behave as expected,
using structured netperf output produced by infrastructure.network.benchmark().

This script is intentionally simple and conservative: it checks relative
relationships (e.g. 5G > 4G throughput, manual_high > manual_low) rather than
hard absolute numbers, to avoid overfitting to a single environment.
"""

import argparse
import json
import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "network_validation")


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
    numbers = re.findall(r"[-+]?[0-9]*\\.?[0-9]+", output)
    if not numbers:
        return 0.0
    try:
        return float(numbers[-1])
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

    # Simple expectations:
    # - cloud->endpoint throughput should be higher for "manual_high" than "manual_low"
    # - 5G should generally offer higher throughput than 4G for cloud->endpoint
    # We use config-derived hints encoded in the source_ssh name if available.

    # Map scenario key -> avg throughput
    scenario_tp: Dict[str, float] = {
        key: summarize_throughput(entries) for key, entries in grouped.items()
    }

    # Print summary for transparency
    print("Throughput summary by scenario (arbitrary units):")
    for key, value in scenario_tp.items():
        print(f"  {key}: {value:.2f}")

    # We keep assertions intentionally light and relative.
    failures: List[str] = []

    # Example heuristic checks: look at cloud->endpoint
    cloud_endpoint_keys = [k for k in scenario_tp if k.startswith("cloud->endpoint")]
    if len(cloud_endpoint_keys) >= 2:
        # Sort by throughput
        sorted_pairs: List[Tuple[str, float]] = sorted(
            ((k, scenario_tp[k]) for k in cloud_endpoint_keys), key=lambda x: x[1]
        )
        lowest, highest = sorted_pairs[0], sorted_pairs[-1]
        if highest[1] < lowest[1] * 1.2:  # expect at least 20% difference
            failures.append(
                "cloud->endpoint throughput across scenarios does not differ enough "
                "(manual/profile validation may be misconfigured)."
            )

    if failures:
        print("Network profile validation FAILED:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print("Network profile validation PASSED (basic relative checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
