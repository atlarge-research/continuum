"""Unit tests for network emulation helpers."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infrastructure import network


class NetworkHelpersTests(unittest.TestCase):
    def _benchmark_config(self, base_path):
        return {
            "infrastructure": {
                "base_path": base_path,
                "wireless_network_preset": "4g",
            },
            "timestamp": "2026-05-21_15:30:42",
            "control_ips_internal": ["192.168.100.2"],
            "cloud_ips_internal": [],
            "edge_ips_internal": [],
            "endpoint_ips_internal": ["192.168.100.3"],
            "cloud_ssh": ["cloud0@192.168.100.2"],
            "edge_ssh": [],
            "endpoint_ssh": ["endpoint0@192.168.100.3"],
        }

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

    def test_plan_network_benchmark_pairs_is_complete_ordered_and_directed(self):
        config = self._benchmark_config("/tmp")
        config.update(
            {
                "cloud_ips_internal": ["192.168.100.4"],
                "cloud_ssh": [
                    "cloud0@192.168.100.2",
                    "cloud1@192.168.100.4",
                ],
                "edge_ips_internal": ["192.168.100.5", "192.168.100.6"],
                "edge_ssh": [
                    "edge0@192.168.100.5",
                    "edge1@192.168.100.6",
                ],
            }
        )

        pairs = network.plan_network_benchmark_pairs(config)

        self.assertEqual(len(pairs), 20)
        relations = [(pair["source"], pair["target"]) for pair in pairs]
        self.assertEqual(
            list(dict.fromkeys(relations)),
            [
                ("cloud", "cloud"),
                ("cloud", "edge"),
                ("cloud", "endpoint"),
                ("edge", "edge"),
                ("edge", "cloud"),
                ("edge", "endpoint"),
                ("endpoint", "cloud"),
                ("endpoint", "edge"),
            ],
        )
        identities = {
            (pair["source"], pair["target"], pair["source_ssh"], pair["target_ip"])
            for pair in pairs
        }
        self.assertEqual(len(identities), len(pairs))

    def test_plan_network_benchmark_pairs_rejects_misalignment_and_duplicates(self):
        config = self._benchmark_config("/tmp")
        config["cloud_ssh"] = []
        with self.assertRaisesRegex(RuntimeError, "cardinality mismatch"):
            network.plan_network_benchmark_pairs(config)

        config = self._benchmark_config("/tmp")
        config["endpoint_ips_internal"] = ["192.168.100.3", "192.168.100.3"]
        config["endpoint_ssh"] = [
            "endpoint0@192.168.100.3",
            "endpoint1@192.168.100.4",
        ]
        with self.assertRaisesRegex(RuntimeError, "must be unique"):
            network.plan_network_benchmark_pairs(config)

    def test_benchmark_writes_header_then_complete_invocations_under_base_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            machine.process.return_value = [(["1000,40000,50000"], [])]
            config = self._benchmark_config(tempdir)

            network.benchmark(config, [machine])

            results_path = (
                Path(tempdir)
                / ".continuum"
                / "logs"
                / "network_validation"
                / "netperf_results_2026-05-21_15:30:42.ndjson"
            )
            entries = [
                json.loads(line)
                for line in results_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(len(entries), 5)
            self.assertEqual(entries[0]["kind"], "ContinuumNetperfRun")
            self.assertEqual(entries[0]["schema_version"], 1)
            self.assertEqual(len(entries[0]["planned_pairs"]), 2)
            self.assertTrue(
                all(entry["timestamp"] == "2026-05-21_15:30:42" for entry in entries)
            )
            self.assertEqual(
                [entry["direction"] for entry in entries[1:]],
                ["latency", "throughput", "latency", "throughput"],
            )
            self.assertTrue(
                all(entry["kind"] == "ContinuumNetperfInvocation" for entry in entries[1:])
            )
            self.assertEqual(entries[1]["command"][2], entries[1]["target_ip"])
            self.assertEqual(entries[1]["command"][4], "TCP_RR")
            self.assertEqual(entries[2]["command"][4], "TCP_STREAM")

    def test_benchmark_rejects_topology_without_directed_pairs(self):
        config = self._benchmark_config("/tmp")
        config["endpoint_ips_internal"] = []
        config["endpoint_ssh"] = []
        machine = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "no directed pairs"):
            network.benchmark(config, [machine])

        machine.process.assert_not_called()

    def test_benchmark_exclusive_creation_rejects_existing_current_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._benchmark_config(tempdir)
            results_dir = (
                Path(tempdir) / ".continuum" / "logs" / "network_validation"
            )
            results_dir.mkdir(parents=True)
            results_path = results_dir / "netperf_results_2026-05-21_15:30:42.ndjson"
            results_path.write_text("retained", encoding="utf-8")
            machine = mock.Mock()
            machine.process.return_value = [([], [])]

            with self.assertRaisesRegex(RuntimeError, "Failed to initialize"):
                network.benchmark(config, [machine])

            self.assertEqual(results_path.read_text(encoding="utf-8"), "retained")

    def test_network_record_write_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_path = (
                Path(tempdir)
                / ".continuum"
                / "logs"
                / "network_validation"
                / "netperf_results_2026-05-21_15:30:42.ndjson"
            )
            artifact_file = mock.Mock()
            artifact_file.write.side_effect = OSError("disk full")

            with self.assertRaises(RuntimeError) as raised:
                network._write_network_record(  # pylint: disable=protected-access
                    artifact_file, str(results_path), {"value": 1}
                )

            self.assertIn(str(results_path), str(raised.exception))
            self.assertIn("disk full", str(raised.exception))
            self.assertIsInstance(raised.exception.__cause__, OSError)


if __name__ == "__main__":
    unittest.main()
