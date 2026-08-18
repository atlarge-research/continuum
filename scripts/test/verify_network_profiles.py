#!/usr/bin/env python3
"""Verify network-profile behavior from self-describing structured netperf output."""

import argparse
import json
import math
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
RUN_KIND = "ContinuumNetperfRun"
INVOCATION_KIND = "ContinuumNetperfInvocation"
SCHEMA_VERSION = 1
_NUMBER_PATTERN = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")
_PAIR_FIELDS = {
    "source",
    "target",
    "source_ssh",
    "target_ip",
    "expected_latency_ms",
    "expected_throughput_mbps",
}
_HEADER_FIELDS = {"kind", "schema_version", "timestamp", "planned_pairs"}
_INVOCATION_FIELDS = {
    "kind",
    "schema_version",
    "timestamp",
    *_PAIR_FIELDS,
    "direction",
    "command",
    "output",
    "error",
}
_RELATIONS = (
    ("cloud", "cloud"),
    ("cloud", "edge"),
    ("cloud", "endpoint"),
    ("edge", "edge"),
    ("edge", "cloud"),
    ("edge", "endpoint"),
    ("endpoint", "cloud"),
    ("endpoint", "edge"),
)
_RELATION_ORDER = {relation: index for index, relation in enumerate(_RELATIONS)}
_LATENCY_FIELDS = (
    "min_latency,mean_latency,max_latency,stddev_latency,"
    "transaction_rate,p50_latency,p90_latency,p99_latency"
)


class NetworkResultsFormatError(ValueError):
    """Raised for malformed physical NDJSON lines."""

    def __init__(self, line_number, message):
        self.line_number = line_number
        super().__init__("line %s: %s" % (line_number, message))


class NetworkResultsValidationError(ValueError):
    """Raised for schema or completeness failures in parsed records."""


class NetworkResultsAttributionError(NetworkResultsValidationError):
    """Raised when an artifact does not belong to the expected run timestamp."""


def results_dir_for_base_path(base_path: str) -> str:
    """Return the network validation result directory below a runtime base path."""
    return os.path.join(os.path.expanduser(base_path), NETWORK_VALIDATION_LOG_SUFFIX)


def _latest_results_file(results_dir: str) -> str:
    if not os.path.isdir(results_dir):
        raise FileNotFoundError("Network validation log directory not found: %s" % results_dir)
    candidates = [
        os.path.join(results_dir, name)
        for name in os.listdir(results_dir)
        if name.startswith("netperf_results_") and name.endswith(".ndjson")
    ]
    if not candidates:
        raise FileNotFoundError("No netperf results files found in %s" % results_dir)
    return max(candidates, key=os.path.getmtime)


def latest_results_file(base_path: str = None, results_dir: str = None) -> str:
    """Return the newest structured network result file in the selected directory."""
    if results_dir:
        return _latest_results_file(results_dir)
    if base_path:
        return _latest_results_file(results_dir_for_base_path(base_path))
    env_base_path = os.environ.get("CONTINUUM_BASE_PATH")
    if env_base_path:
        return _latest_results_file(results_dir_for_base_path(env_base_path))
    return _latest_results_file(LEGACY_LOG_DIR)


def _reject_json_constant(value):
    raise ValueError("non-standard JSON constant %s" % value)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key %r" % key)
        result[key] = value
    return result


def load_results(path: str) -> List[Dict]:
    """Load strict, newline-terminated NDJSON records with physical line diagnostics."""
    results: List[Dict] = []
    with open(path, "r", encoding="utf-8") as filep:
        for line_number, raw_line in enumerate(filep, 1):
            if not raw_line.endswith("\n"):
                raise NetworkResultsFormatError(line_number, "record is not newline-terminated")
            line = raw_line[:-1]
            if not line.strip():
                raise NetworkResultsFormatError(line_number, "blank records are not allowed")
            try:
                record = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_unique_json_object,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise NetworkResultsFormatError(line_number, str(exc)) from exc
            results.append(record)
    return results


def _finite_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _numeric_fields(payload, expected_count):
    fields = [field for field in re.split(r"[\s,]+", payload.strip()) if field]
    if len(fields) != expected_count or any(
        _NUMBER_PATTERN.fullmatch(field) is None for field in fields
    ):
        return None
    return fields


def _parse_throughput(output: str):
    if not isinstance(output, str):
        return None
    payload = output.strip()
    if _NUMBER_PATTERN.fullmatch(payload):
        return _finite_float(payload)
    if not re.search(r"(?i)TCP\s+STREAM\s+TEST", payload):
        return None
    heading = re.search(r"(?i)\bThroughput\b", payload)
    if heading is None:
        return None
    metric_rows = []
    for line in payload[heading.end() :].splitlines():
        fields = _numeric_fields(line, 5)
        if fields is not None:
            metric_rows.append(fields)
    return _finite_float(metric_rows[-1][-1]) if metric_rows else None


def _parse_latency_ms(output: str):
    if not isinstance(output, str):
        return None
    payload = output.strip()
    fields = _numeric_fields(payload, 8)
    if fields is None:
        marker = re.search(r"(?i)TCP\s+REQUEST/RESPONSE\s+TEST", payload)
        heading = re.search(
            r"(?is)\bMinimum\b.*\bMean\b.*\bMaximum\b.*\bStddev\b.*"
            r"\bTransaction\b.*(?:\bp50\b|\b50th\b).*"
            r"(?:\bp90\b|\b90th\b).*(?:\bp99\b|\b99th\b)",
            payload,
        )
        if marker is None or heading is None or heading.start() < marker.end():
            return None
        metric_rows = []
        for line in payload[heading.end() :].splitlines():
            candidate_fields = _numeric_fields(line, 8)
            if candidate_fields is not None:
                metric_rows.append(candidate_fields)
        fields = metric_rows[-1] if metric_rows else None
    observed_microseconds = _finite_float(fields[1]) if fields is not None else None
    return observed_microseconds / 1000.0 if observed_microseconds is not None else None


def _pair_identity(pair):
    return pair["source"], pair["target"], pair["source_ssh"], pair["target_ip"]


def _pair_label(pair):
    return "%s->%s (%s to %s)" % _pair_identity(pair)


def _require_exact_fields(record, expected_fields, label):
    if not isinstance(record, dict):
        raise NetworkResultsValidationError("%s must be a mapping" % label)
    missing = sorted(expected_fields - set(record))
    unknown = sorted(set(record) - expected_fields)
    if missing:
        raise NetworkResultsValidationError(
            "%s is missing fields: %s" % (label, ", ".join(missing))
        )
    if unknown:
        raise NetworkResultsValidationError(
            "%s has unknown fields: %s" % (label, ", ".join(unknown))
        )


def _require_number(value, label, minimum=None, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NetworkResultsValidationError("%s must be a finite JSON number" % label)
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NetworkResultsValidationError("%s must be representable as float" % label) from exc
    if not math.isfinite(converted):
        raise NetworkResultsValidationError("%s must be finite" % label)
    if strictly_positive and converted <= 0:
        raise NetworkResultsValidationError("%s must be > 0" % label)
    if minimum is not None and converted < minimum:
        raise NetworkResultsValidationError("%s must be >= %s" % (label, minimum))
    return converted


def _validate_pair(pair, label):
    _require_exact_fields(pair, _PAIR_FIELDS, label)
    for field in ("source", "target", "source_ssh", "target_ip"):
        if not isinstance(pair[field], str) or not pair[field].strip():
            raise NetworkResultsValidationError(
                "%s.%s must be a non-empty string" % (label, field)
            )
    relation = pair["source"], pair["target"]
    if relation not in _RELATION_ORDER:
        raise NetworkResultsValidationError(
            "%s has unsupported tier relation %s->%s" % (label, *relation)
        )
    latency = _require_number(
        pair["expected_latency_ms"], label + ".expected_latency_ms", minimum=0
    )
    throughput = _require_number(
        pair["expected_throughput_mbps"],
        label + ".expected_throughput_mbps",
        strictly_positive=True,
    )
    return latency, throughput


def _canonical_command(direction, target_ip):
    if direction == "latency":
        return ["netperf", "-H", target_ip, "-t", "TCP_RR", "--", "-O", _LATENCY_FIELDS]
    return ["netperf", "-H", target_ip, "-t", "TCP_STREAM"]


def validate_structure(records: List[Dict], expected_timestamp=None) -> List[Dict]:
    """Validate schema, attribution, pair completeness, and canonical command binding."""
    if not records:
        raise NetworkResultsValidationError("no network result records found")
    header = records[0]
    _require_exact_fields(header, _HEADER_FIELDS, "record 1 run header")
    if (
        header["kind"] != RUN_KIND
        or not isinstance(header["schema_version"], int)
        or isinstance(header["schema_version"], bool)
        or header["schema_version"] != SCHEMA_VERSION
    ):
        raise NetworkResultsValidationError(
            "record 1 must be a %s schema v%s header" % (RUN_KIND, SCHEMA_VERSION)
        )
    timestamp = header["timestamp"]
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise NetworkResultsValidationError("record 1 timestamp must be a non-empty string")
    if expected_timestamp is not None and timestamp != expected_timestamp:
        raise NetworkResultsAttributionError(
            "run header timestamp %r does not match current run timestamp %r"
            % (timestamp, expected_timestamp)
        )
    planned_pairs = header["planned_pairs"]
    if not isinstance(planned_pairs, list) or not planned_pairs:
        raise NetworkResultsValidationError("run header planned_pairs must be a non-empty list")

    planned = {}
    previous_relation_index = -1
    for index, pair in enumerate(planned_pairs, 1):
        label = "run header planned_pairs[%s]" % (index - 1)
        expected_values = _validate_pair(pair, label)
        relation_index = _RELATION_ORDER[(pair["source"], pair["target"])]
        if relation_index < previous_relation_index:
            raise NetworkResultsValidationError(
                "run header planned_pairs relation order is not deterministic"
            )
        previous_relation_index = relation_index
        identity = _pair_identity(pair)
        if identity in planned:
            raise NetworkResultsValidationError(
                "run header contains duplicate planned pair %r" % (identity,)
            )
        planned[identity] = expected_values

    observed = defaultdict(dict)
    invocations = []
    for record_index, record in enumerate(records[1:], 2):
        label = "record %s invocation" % record_index
        _require_exact_fields(record, _INVOCATION_FIELDS, label)
        if (
            record["kind"] != INVOCATION_KIND
            or not isinstance(record["schema_version"], int)
            or isinstance(record["schema_version"], bool)
            or record["schema_version"] != SCHEMA_VERSION
        ):
            raise NetworkResultsValidationError(
                "%s must be a %s schema v%s record" % (label, INVOCATION_KIND, SCHEMA_VERSION)
            )
        if record["timestamp"] != timestamp:
            raise NetworkResultsAttributionError(
                "%s timestamp %r does not match run header timestamp %r"
                % (label, record["timestamp"], timestamp)
            )
        expected_values = _validate_pair(
            {field: record[field] for field in _PAIR_FIELDS}, label
        )
        identity = _pair_identity(record)
        if identity not in planned:
            raise NetworkResultsValidationError(
                "%s is not present in the run header plan" % label
            )
        if expected_values != planned[identity]:
            raise NetworkResultsValidationError(
                "%s expected profile values do not match run header" % label
            )
        direction = record["direction"]
        if direction not in ("latency", "throughput"):
            raise NetworkResultsValidationError(
                "%s.direction must be latency or throughput" % label
            )
        if direction in observed[identity]:
            raise NetworkResultsValidationError(
                "%s duplicates %s for planned pair %r" % (label, direction, identity)
            )
        if record["command"] != _canonical_command(direction, record["target_ip"]):
            raise NetworkResultsValidationError(
                "%s command is not canonical for direction/target_ip" % label
            )
        for field in ("output", "error"):
            if not isinstance(record[field], str):
                raise NetworkResultsValidationError("%s.%s must be a string" % (label, field))
        observed[identity][direction] = record
        invocations.append(record)

    for identity in planned:
        directions = set(observed[identity])
        if directions != {"latency", "throughput"}:
            raise NetworkResultsValidationError(
                "planned pair %r must have exactly one latency and one throughput invocation"
                % (identity,)
            )
    return invocations


def group_by_scenario(results: List[Dict]) -> Dict[str, List[Dict]]:
    """Group validated invocation records by tier relation for CLI summaries."""
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entry in results:
        if isinstance(entry, dict) and entry.get("kind") == INVOCATION_KIND:
            grouped["%s->%s" % (entry["source"], entry["target"])].append(entry)
    return grouped


def summarize_throughput(group: List[Dict]) -> float:
    """Return average parseable throughput for a validated scenario group."""
    values = [
        _parse_throughput(entry["output"])
        for entry in group
        if entry.get("direction") == "throughput"
    ]
    values = [value for value in values if value is not None and value > 0]
    return sum(values) / len(values) if values else 0.0


def summarize_latency_ms(group: List[Dict]) -> float:
    """Return average parseable latency for a validated scenario group."""
    values = [
        _parse_latency_ms(entry["output"])
        for entry in group
        if entry.get("direction") == "latency"
    ]
    values = [value for value in values if value is not None and value > 0]
    return sum(values) / len(values) if values else 0.0


def _within_tolerance(observed: float, expected: float, absolute_floor: float) -> bool:
    lower = max(0.0, expected - max(absolute_floor, expected * RELATIVE_TOLERANCE))
    upper = expected + max(absolute_floor, expected * RELATIVE_TOLERANCE)
    return lower <= observed <= upper


def validate_profile_results(invocations: List[Dict]) -> List[str]:
    """Return observation and profile-tolerance failures for validated invocations."""
    failures = []
    for entry in invocations:
        label = _pair_label(entry) + " " + entry["direction"]
        if entry["error"].strip():
            failures.append("%s netperf error is non-empty" % label)
            continue
        if entry["direction"] == "latency":
            observed = _parse_latency_ms(entry["output"])
            expected = float(entry["expected_latency_ms"]) * 2.0
            if observed is None or observed <= 0:
                failures.append("%s result is missing, non-finite, or unparseable" % label)
            elif not _within_tolerance(observed, expected, LATENCY_ABSOLUTE_TOLERANCE_MS):
                failures.append(
                    "%s %.2fms is outside tolerated range for expected %.2fms"
                    % (label, observed, expected)
                )
        else:
            observed = _parse_throughput(entry["output"])
            expected = float(entry["expected_throughput_mbps"])
            if observed is None or observed <= 0:
                failures.append("%s result is missing, non-finite, or unparseable" % label)
            elif expected <= THROUGHPUT_STRICT_VALIDATION_MAX_MBPS and not _within_tolerance(
                observed, expected, THROUGHPUT_ABSOLUTE_TOLERANCE_MBPS
            ):
                failures.append(
                    "%s %.2fmbps is outside tolerated range for expected %.2fmbps"
                    % (label, observed, expected)
                )
    return failures


def validate_results(records: List[Dict], expected_timestamp=None) -> List[str]:
    """Validate structure and return any profile-observation failures."""
    return validate_profile_results(validate_structure(records, expected_timestamp))


def main() -> int:
    """Run the standalone verifier CLI without exposing tracebacks for bad artifacts."""
    parser = argparse.ArgumentParser(
        description="Verify Continuum network profiles using netperf results."
    )
    parser.add_argument("--results-file")
    parser.add_argument("--base-path")
    parser.add_argument("--results-dir")
    args = parser.parse_args()
    try:
        results_file = args.results_file or latest_results_file(
            base_path=args.base_path, results_dir=args.results_dir
        )
        records = load_results(results_file)
        invocations = validate_structure(records)
    except NetworkResultsFormatError as exc:
        print("Network results invalid: %s" % exc)
        return 1
    except NetworkResultsValidationError as exc:
        print("Network results invalid: %s" % exc)
        return 1
    except (OSError, UnicodeError) as exc:
        print("Network results unreadable: %s" % exc)
        return 1

    print("Using netperf results file: %s" % results_file)
    grouped = group_by_scenario(invocations)
    print("Scenario summary:")
    for key in sorted(grouped):
        print(
            "  %s: latency=%.2fms throughput=%.2fmbps"
            % (key, summarize_latency_ms(grouped[key]), summarize_throughput(grouped[key]))
        )
    failures = validate_profile_results(invocations)
    if failures:
        print("Network profile validation FAILED:")
        for message in failures:
            print("  - %s" % message)
        return 1
    print(
        "Network profile validation PASSED "
        "(latency uses TCP_RR round-trip expectation; constrained throughput "
        "tolerance: 25% or 10mbps, whichever is larger)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
