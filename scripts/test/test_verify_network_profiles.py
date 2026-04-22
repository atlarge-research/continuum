"""Unit tests for structured network-profile verification."""

import importlib.util
import unittest
from pathlib import Path


def _load_verify_module():
    module_path = Path(__file__).with_name("verify_network_profiles.py")
    spec = importlib.util.spec_from_file_location("continuum_verify_network_profiles", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_module = _load_verify_module()


class VerifyNetworkProfilesTests(unittest.TestCase):
    def test_validate_results_accepts_values_within_combined_tolerance(self):
        results = [
            {
                "source": "cloud",
                "target": "endpoint",
                "direction": "latency",
                "output": "1000,40000,50000,1000,25,30000,45000,50000",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
            {
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
                "source": "cloud",
                "target": "endpoint",
                "direction": "latency",
                "output": "1000,70000,80000,1000,25,60000,75000,80000",
                "expected_latency_ms": 45.0,
                "expected_throughput_mbps": 7.21,
            },
            {
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
