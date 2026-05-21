"""Unit tests for network emulation helpers."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infrastructure import network


class NetworkHelpersTests(unittest.TestCase):
    def test_tc_values_accepts_yaml_projection_without_legacy_location_keys(self):
        config = {
            "infrastructure": {
                "wireless_network_preset": "4g",
            }
        }

        cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint = network.tc_values(config)

        self.assertEqual(cloud, [0, 0, 1000])
        self.assertEqual(edge, [7.5, 2.5, 1000])
        self.assertEqual(cloud_edge, [7.5, 2.5, 1000])
        self.assertEqual(cloud_endpoint, [45, 5, 7.21])
        self.assertEqual(edge_endpoint, [7.5, 2.5, 7.21])

    def test_generate_tc_commands_builds_commands_without_target_name_error(self):
        config = {"infrastructure": {"provider": "qemu"}}

        commands = network.generate_tc_commands(config, [45, 5, 7.21], ["10.0.0.2"], 1)

        self.assertTrue(commands)
        self.assertEqual(commands[0][:7], ["sudo", "tc", "qdisc", "add", "dev", "ens2", "root"])
        self.assertTrue(any(command[-1] == "10.0.0.2" for command in commands))

    def test_generate_mahimahi_command_includes_all_targets(self):
        commands = network.generate_mahimati_command(
            "10.0.0.10",
            ["10.0.0.20", "10.0.0.21"],
            "/tmp/uplink",
            "/tmp/downlink",
        )

        joined = "\n".join(" ".join(command) for command in commands)
        self.assertIn("/home/mahimahi/setup_container.sh 10.0.0.10 10.0.0.20 10.0.0.21", joined)
        self.assertIn("/home/mahimahi/setup_traffic.sh 10.0.0.10 10.0.0.20 10.0.0.21", joined)

    def test_start_passes_unquoted_shell_commands_to_remote_tc_runner(self):
        machine = mock.Mock()
        machine.process.return_value = [([], []), ([], [])]
        config = {
            "infrastructure": {
                "provider": "qemu",
                "wireless_network_preset": "4g",
            },
            "control_ips_internal": [],
            "cloud_ips_internal": ["192.168.100.2"],
            "edge_ips_internal": [],
            "endpoint_ips_internal": ["192.168.100.3"],
            "cloud_ssh": ["cloud0@192.168.100.2"],
            "edge_ssh": [],
            "endpoint_ssh": ["endpoint0@192.168.100.3"],
        }

        network.start(config, [machine])

        commands = machine.process.call_args.args[1]
        self.assertEqual(machine.process.call_args.kwargs["shell"], True)
        self.assertTrue(all(not command.startswith('"') for command in commands))
        self.assertTrue(all(not command.endswith('"') for command in commands))
        self.assertTrue(any(";" in command for command in commands))

    def test_benchmark_output_writes_results_under_base_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            machine.process.return_value = [(["1000,40000,50000"], [])]
            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "wireless_network_preset": "4g",
                },
                "timestamp": "2026-05-21T000000",
            }

            network.benchmark_output(
                config,
                machine,
                ["192.168.100.3"],
                [["netperf", "-t", "TCP_RR"]],
                [["netperf", "-t", "TCP_STREAM"]],
                "cloud0@192.168.100.2",
                "cloud",
                "endpoint",
            )

            results_path = (
                Path(tempdir)
                / ".continuum"
                / "logs"
                / "network_validation"
                / "netperf_results_2026-05-21T000000.ndjson"
            )
            entries = [
                json.loads(line)
                for line in results_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["direction"], "latency")
            self.assertEqual(entries[1]["direction"], "throughput")


if __name__ == "__main__":
    unittest.main()
