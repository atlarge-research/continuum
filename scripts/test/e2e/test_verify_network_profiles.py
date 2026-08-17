"""Unit tests for structured network-profile verification."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


def _load_verify_module():
    module_path = Path(__file__).resolve().parents[1] / "verify_network_profiles.py"
    spec = importlib.util.spec_from_file_location("continuum_verify_network_profiles", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_module = _load_verify_module()


class VerifyNetworkProfilesTests(unittest.TestCase):
    def test_latest_results_file_uses_base_path_runtime_log_dir(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_dir = (
                Path(tempdir) / ".continuum" / "logs" / "network_validation"
            )
            results_dir.mkdir(parents=True)
            older = results_dir / "netperf_results_2026-05-20_15:30:42.ndjson"
            newer = results_dir / "netperf_results_2026-05-21_15:30:42.ndjson"
            older.write_text("{}\n", encoding="utf-8")
            newer.write_text("{}\n", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))

            self.assertEqual(
                verify_module.results_dir_for_base_path(tempdir),
                str(results_dir),
            )
            self.assertEqual(
                verify_module.latest_results_file(base_path=tempdir),
                str(newer),
            )

    def test_validate_results_accepts_values_within_combined_tolerance(self):
        results = [
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "endpoint",
                "direction": "latency",
                "output": "1000,90000,100000,1000,25,85000,95000,100000",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "endpoint",
                "direction": "throughput",
                "output": "7.50",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
        ]

        self.assertEqual(verify_module.validate_results(results), [])

    def test_validate_results_rejects_values_outside_tolerance(self):
        results = [
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "endpoint",
                "direction": "latency",
                "output": "1000,140000,150000,1000,25,135000,145000,150000",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "endpoint",
                "direction": "throughput",
                "output": "30.00",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
        ]

        failures = verify_module.validate_results(results)
        self.assertEqual(len(failures), 2)
        self.assertTrue(any("latency" in failure for failure in failures))
        self.assertTrue(any("throughput" in failure for failure in failures))

    def test_validate_results_parses_netperf_header_latency(self):
        output = (
            "MIGRATED TCP REQUEST/RESPONSE TEST from 0.0.0.0 (0.0.0.0) port 0 "
            "AF_INET to 192.168.100.4 () port 0 AF_INET : spin interval : first burst 0 "
            "Minimum      Mean         Maximum      Stddev       Transaction 50th "
            "Microseconds Microseconds Microseconds Microseconds Tran/s      Latency "
            "72074        92012.55     190955       12199.53     10.777 "
            "91000        102307       109230"
        )

        self.assertAlmostEqual(verify_module._parse_latency_ms(output), 92.01255)

    def test_validate_results_skips_strict_high_capacity_throughput(self):
        results = [
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "edge",
                "direction": "latency",
                "output": "1000,16000,20000,1000,25,15000,18000,20000",
                "expected_latency_ms": 7.5,
                "expected_throughput_mbps": 1000.0,
            },
            {
                "timestamp": "2026-05-21_15:30:42",
                "source": "cloud",
                "target": "edge",
                "direction": "throughput",
                "output": "129.26",
                "expected_latency_ms": 7.5,
                "expected_throughput_mbps": 1000.0,
            },
        ]

        self.assertEqual(verify_module.validate_results(results), [])
