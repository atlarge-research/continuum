"""Unit tests for strict self-describing network-profile verification."""

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infrastructure import network


def _load_verify_module():
    module_path = Path(__file__).resolve().parents[1] / "verify_network_profiles.py"
    spec = importlib.util.spec_from_file_location("continuum_verify_network_profiles", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_module = _load_verify_module()
TIMESTAMP = "2026-05-21_15:30:42"


def _pair(source_ssh="cloud0@192.0.2.1", target_ip="10.0.0.2"):
    return {
        "source": "cloud",
        "target": "endpoint",
        "source_ssh": source_ssh,
        "target_ip": target_ip,
        "expected_latency_ms": 45.0,
        "expected_throughput_mbps": 7.21,
    }


def _invocation(pair, direction, timestamp=TIMESTAMP):
    output = (
        "1000,90000,100000,1000,25,85000,95000,100000"
        if direction == "latency"
        else "7.50"
    )
    return {
        "kind": "ContinuumNetperfInvocation",
        "schema_version": 1,
        "timestamp": timestamp,
        **copy.deepcopy(pair),
        "direction": direction,
        "command": verify_module._canonical_command(direction, pair["target_ip"]),
        "output": output,
        "error": "",
    }


def _records(pairs=None):
    pairs = copy.deepcopy(pairs or [_pair()])
    records = [
        {
            "kind": "ContinuumNetperfRun",
            "schema_version": 1,
            "timestamp": TIMESTAMP,
            "planned_pairs": pairs,
        }
    ]
    for pair in pairs:
        records.extend((_invocation(pair, "latency"), _invocation(pair, "throughput")))
    return records


def _write_records(path, records):
    path.write_text(
        "".join(json.dumps(record, allow_nan=False) + "\n" for record in records),
        encoding="utf-8",
    )


class VerifyNetworkProfilesTests(unittest.TestCase):
    def test_latest_results_file_uses_base_path_runtime_log_dir(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_dir = Path(tempdir) / ".continuum" / "logs" / "network_validation"
            results_dir.mkdir(parents=True)
            older = results_dir / "netperf_results_2026-05-20_15:30:42.ndjson"
            newer = results_dir / "netperf_results_2026-05-21_15:30:42.ndjson"
            older.write_text("{}\n", encoding="utf-8")
            newer.write_text("{}\n", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))
            self.assertEqual(verify_module.latest_results_file(base_path=tempdir), str(newer))

    def test_complete_artifact_accepts_values_within_tolerance(self):
        records = _records()
        self.assertEqual(verify_module.validate_results(records, TIMESTAMP), [])

    def test_profile_validation_is_per_physical_pair(self):
        pairs = [_pair(), _pair("cloud1@192.0.2.2", "10.0.0.3")]
        records = _records(pairs)
        records[-1]["output"] = "30.00"
        failures = verify_module.validate_results(records)
        self.assertEqual(len(failures), 1)
        self.assertIn("cloud1@192.0.2.2", failures[0])
        self.assertIn("10.0.0.3", failures[0])

    def test_high_capacity_throughput_still_requires_parseable_output(self):
        records = _records()
        records[0]["planned_pairs"][0]["expected_throughput_mbps"] = 1000.0
        records[1]["expected_throughput_mbps"] = 1000.0
        records[2]["expected_throughput_mbps"] = 1000.0
        records[2]["output"] = "129.26"
        self.assertEqual(verify_module.validate_results(records), [])
        records[2]["output"] = "Infinity"
        self.assertIn("unparseable", verify_module.validate_results(records)[0])

    def test_latency_parser_uses_netperf_result_fields(self):
        output = (
            "MIGRATED TCP REQUEST/RESPONSE TEST from 0.0.0.0 port 0 "
            "Minimum Mean Maximum Stddev Transaction p50 p90 p99 "
            "72074 92012.55 190955 12199.53 10.777 91000 102307 109230"
        )
        self.assertAlmostEqual(verify_module._parse_latency_ms(output), 92.01255)

    def test_throughput_parser_uses_netperf_result_row(self):
        output = (
            "MIGRATED TCP STREAM TEST from 0.0.0.0 port 0\n"
            "Recv Socket Size  Send Socket Size  Send Message Size  Elapsed Time  Throughput\n"
            "bytes             bytes             bytes              secs.         10^6bits/sec\n"
            "87380             16384             16384              10.00         7.50\n"
        )
        self.assertEqual(verify_module._parse_throughput(output), 7.5)

    def test_observation_parsers_reject_numeric_error_text(self):
        self.assertIsNone(
            verify_module._parse_throughput("netperf failed with exit code 7.2")
        )
        self.assertIsNone(verify_module._parse_latency_ms("garbage 1000 90000"))

        records = _records()
        records[1]["output"] = "garbage 1000 90000"
        self.assertIn("unparseable", verify_module.validate_results(records)[0])
        records = _records()
        records[2]["output"] = "netperf failed with exit code 7.2"
        self.assertIn("unparseable", verify_module.validate_results(records)[0])

    def test_producer_preserves_and_validator_parses_machine_output_lines(self):
        latency_lines = [
            "MIGRATED TCP REQUEST/RESPONSE TEST from 0.0.0.0 port 0",
            "Minimum Mean Maximum Stddev Transaction 50th 90th 99th",
            "Latency Latency Latency Latency Rate Percentile Percentile Percentile",
            "Microseconds Microseconds Microseconds Microseconds Tran/s Latency Latency Latency",
            "74503 91700.29 193985 12030.85 10.700 91666 99000 108888",
        ]
        throughput_lines = [
            "MIGRATED TCP STREAM TEST from 0.0.0.0 port 0",
            "Recv Send Send",
            "Socket Socket Message Elapsed",
            "Size Size Size Time Throughput",
            "bytes bytes bytes secs. 10^6bits/sec",
            "131072 16384 16384 13.30 6.24",
        ]
        machine = mock.Mock()
        machine.process.side_effect = [
            [(latency_lines, [])],
            [(throughput_lines, [])],
        ]
        pair = _pair()

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "results.ndjson"
            with path.open("x", encoding="utf-8") as artifact_file:
                artifact_file.write(
                    json.dumps(
                        {
                            "kind": "ContinuumNetperfRun",
                            "schema_version": 1,
                            "timestamp": TIMESTAMP,
                            "planned_pairs": [pair],
                        }
                    )
                    + "\n"
                )
                network.benchmark_output(
                    {"timestamp": TIMESTAMP}, machine, pair, artifact_file, str(path)
                )

            records = verify_module.load_results(str(path))
            self.assertIn("\n", records[1]["output"])
            self.assertEqual(verify_module.validate_results(records, TIMESTAMP), [])

    def test_strict_loader_reports_malformed_middle_line_number(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "results.ndjson"
            path.write_text('{}\n{"broken":\n{}\n', encoding="utf-8")
            with self.assertRaisesRegex(verify_module.NetworkResultsFormatError, "line 2"):
                verify_module.load_results(str(path))

    def test_strict_loader_rejects_constants_duplicates_and_torn_last_line(self):
        cases = {
            "nan": '{"value":NaN}\n',
            "infinity": '{"value":Infinity}\n',
            "duplicate": '{"value":1,"value":2}\n',
            "torn": '{"value":1}',
        }
        for label, payload in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tempdir:
                path = Path(tempdir) / "results.ndjson"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(verify_module.NetworkResultsFormatError):
                    verify_module.load_results(str(path))

    def test_header_is_required_first_and_unique(self):
        valid = _records()
        cases = {
            "missing": valid[1:],
            "duplicate": [valid[0], copy.deepcopy(valid[0]), *valid[1:]],
            "late": [valid[1], valid[0], valid[2]],
        }
        for label, records in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(verify_module.NetworkResultsValidationError):
                    verify_module.validate_structure(records)

        duplicate_pair = _records()
        duplicate_pair[0]["planned_pairs"].append(
            copy.deepcopy(duplicate_pair[0]["planned_pairs"][0])
        )
        with self.assertRaises(verify_module.NetworkResultsValidationError):
            verify_module.validate_structure(duplicate_pair)

    def test_completeness_rejects_omitted_pair_direction_and_duplicates(self):
        pairs = [_pair(), _pair("cloud1@192.0.2.2", "10.0.0.3")]
        valid = _records(pairs)
        cases = {
            "whole-pair-omitted": valid[:-2],
            "latency-omitted": [valid[0], *valid[2:]],
            "throughput-omitted": [*valid[:-1]],
            "latency-duplicate": [*valid, copy.deepcopy(valid[1])],
            "throughput-duplicate": [*valid, copy.deepcopy(valid[2])],
        }
        for label, records in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(verify_module.NetworkResultsValidationError):
                    verify_module.validate_structure(records)

    def test_structure_rejects_wrong_schema_relation_command_and_types(self):
        mutations = {
            "header-kind": lambda records: records[0].update(kind="Wrong"),
            "header-version": lambda records: records[0].update(schema_version=2),
            "header-version-boolean": lambda records: records[0].update(schema_version=True),
            "invocation-kind": lambda records: records[1].update(kind="Wrong"),
            "unsupported-relation": lambda records: [
                record.update(target="endpoint", source="endpoint")
                for record in records
            ],
            "wrong-target-binding": lambda records: records[1]["command"].__setitem__(
                2, "10.0.0.99"
            ),
            "wrong-direction-binding": lambda records: records[1]["command"].__setitem__(
                4, "TCP_STREAM"
            ),
            "boolean-expected": lambda records: records[0]["planned_pairs"][0].update(
                expected_latency_ms=True
            ),
            "huge-expected": lambda records: records[0]["planned_pairs"][0].update(
                expected_latency_ms=10**400
            ),
            "non-string-error": lambda records: records[1].update(error=[]),
            "invocation-expectation-mismatch": lambda records: records[1].update(
                expected_latency_ms=99.0
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                records = _records()
                mutate(records)
                with self.assertRaises(verify_module.NetworkResultsValidationError):
                    verify_module.validate_structure(records)

    def test_structure_rejects_header_and_invocation_timestamp_mismatch(self):
        records = _records()
        records[1]["timestamp"] = "2026-05-20_15:30:42"
        with self.assertRaises(verify_module.NetworkResultsAttributionError):
            verify_module.validate_structure(records)
        with self.assertRaises(verify_module.NetworkResultsAttributionError):
            verify_module.validate_structure(_records(), "2026-05-20_15:30:42")

    def test_profile_rejects_nonempty_error_and_bad_observations(self):
        cases = {
            "error": ("error", "netperf failed"),
            "empty": ("output", ""),
            "nan": ("output", "NaN"),
            "infinity": ("output", "Infinity"),
            "overflow": ("output", "1e309"),
        }
        for label, (field, value) in cases.items():
            with self.subTest(case=label):
                records = _records()
                records[1][field] = value
                failures = verify_module.validate_results(records)
                self.assertEqual(len(failures), 1)

    def test_cli_reports_invalid_artifact_without_traceback(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "results.ndjson"
            path.write_text("not-json\n", encoding="utf-8")
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", ["verify", "--results-file", str(path)]):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(verify_module.main(), 1)
            self.assertIn("Network results invalid", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
