"""Unit tests for application runtime helper extraction."""

import unittest
from unittest import mock

from application import runtime_helpers


class ApplicationRuntimeHelpersTests(unittest.TestCase):
    def test_mqtt_kubernetes_worker_vars_uses_mode_assignment_count(self):
        config = {
            "mode": "cloud",
            "infrastructure": {"cloud_nodes": 3, "endpoint_nodes": 8},
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {
                                "applications_per_worker": 2,
                                "application_worker_cpu": 0.75,
                            },
                        }
                    ]
                }
            },
        }

        worker_vars = runtime_helpers.mqtt_kubernetes_worker_vars(config)

        self.assertEqual(
            worker_vars,
            {
                "container_port": 1883,
                "mqtt_logs": True,
                "endpoint_connected": 2,
                "cpu_threads": 1,
            },
        )

    def test_mqtt_mist_worker_env_uses_edge_runtime_shape(self):
        config = {
            "infrastructure": {
                "edge_cores": 4,
                "edge_nodes": 2,
                "endpoint_nodes": 6,
            }
        }

        self.assertEqual(
            runtime_helpers.mqtt_mist_worker_env(config),
            [
                "MQTT_LOGS=True",
                "CPU_THREADS=4",
                "ENDPOINT_CONNECTED=3",
            ],
        )

    def test_mqtt_baremetal_worker_env_uses_registry_host(self):
        config = {
            "registry": "registry.local:5000",
            "infrastructure": {
                "cloud_cores": 8,
                "cloud_nodes": 1,
                "endpoint_nodes": 4,
            },
        }

        self.assertEqual(
            runtime_helpers.mqtt_baremetal_worker_env(config),
            [
                "MQTT_LOCAL_IP=registry.local",
                "MQTT_LOGS=True",
                "CPU_THREADS=8",
                "ENDPOINT_CONNECTED=4",
            ],
        )

    def test_parse_custom_kubernetes_splits_extracts_timestamp_and_marker(self):
        line = (
            "I0824 22:23:21.269974 5026 kubectl.go:32] %!s(int64=1692908601269961032) "
            "[CONTINUUM] 0401 job=test\n"
        )

        timestamp, marker = runtime_helpers.parse_custom_kubernetes_splits(line)

        self.assertAlmostEqual(timestamp, 1692908601.269961, places=6)
        self.assertEqual(marker, "0401 job=test")

    def test_get_docker_worker_output_returns_named_entries_for_mist(self):
        config = {
            "infrastructure": {"provider": "qemu"},
            "edge_ssh": ["edge0@10.0.0.2"],
        }
        machine = mock.Mock()
        machine.process.return_value = [(["line1\n", "line2\n"], [])]

        worker_output = runtime_helpers.get_docker_worker_output(
            config,
            [machine],
            ["edge0"],
        )

        self.assertEqual(worker_output, [["edge0", ["line1", "line2"]]])
        machine.process.assert_called_once_with(
            config,
            [["docker", "logs", "-t", "edge0"]],
            ssh=["edge0@10.0.0.2"],
        )

    def test_get_kubernetes_worker_output_returns_named_entries_for_pods(self):
        config = {
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "config": {"kube_deployment": "pod"},
                        }
                    ]
                }
            },
            "cloud_ssh": ["cloud0@10.0.0.1"],
            "infrastructure": {"cloud_nodes": 2},
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [(["NAME STATUS\n", "worker-a Running\n", "worker-b Succeeded\n"], [])],
            [(["line-a1\n", "DELIMITER01234\n", "line-b1\n", "DELIMITER01234\n"], [])],
        ]

        worker_output = runtime_helpers.get_kubernetes_worker_output(config, [machine])

        self.assertEqual(
            worker_output,
            [["worker-a", ["line-a1"]], ["worker-b", ["line-b1"]]],
        )
        self.assertEqual(machine.process.call_args_list[0].kwargs["ssh"], "cloud0@10.0.0.1")
        self.assertTrue(machine.process.call_args_list[1].kwargs["shell"])

    def test_get_kubernetes_worker_output_expands_container_deployment(self):
        config = {
            "mode": "cloud",
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "config": {"kube_deployment": "container"},
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "empty",
                            "config": {"applications_per_worker": 2},
                        }
                    ]
                },
            },
            "cloud_ssh": ["cloud0@10.0.0.1"],
            "infrastructure": {"cloud_nodes": 3},
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [(["NAME STATUS\n", "worker-pod Running\n"], [])],
            [(["log-1\n", "DELIMITER01234\n", "log-2\n", "DELIMITER01234\n"], [])],
        ]

        worker_output = runtime_helpers.get_kubernetes_worker_output(config, [machine])

        self.assertEqual(
            worker_output,
            [["worker-pod empty-1", ["log-1"]], ["worker-pod empty-2", ["log-2"]]],
        )

    def test_get_worker_output_dispatches_to_docker_runtime(self):
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "mist-main",
                            "type": "mist",
                            "config": {},
                        }
                    ]
                }
            },
            "edge_ssh": ["edge0@10.0.0.2"],
        }

        with mock.patch.object(
            runtime_helpers,
            "get_docker_worker_output",
            return_value=[["edge0", ["line1"]]],
        ) as mock_get_docker:
            worker_output = runtime_helpers.get_worker_output(config, [mock.Mock()], ["edge0"])

        self.assertEqual(worker_output, [["edge0", ["line1"]]])
        mock_get_docker.assert_called_once()

    @mock.patch("application.runtime_helpers.time.sleep", autospec=True)
    def test_start_worker_mist_injects_worker_ip_and_returns_container_names(self, _mock_sleep):
        config = {
            "registry": "registry.local:5000",
            "images": {"worker": "repo/worker:1.0"},
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "img",
                            "type": "image_classification",
                            "config": {
                                "application_worker_cpu": 0.5,
                                "application_worker_memory": 1.5,
                            },
                        }
                    ]
                }
            },
            "edge_ssh": ["edge0@10.0.0.2"],
            "infrastructure": {"provider": "qemu"},
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [(["started"], [])],
            [(["deadbeef: Up 2 seconds edge0"], [])],
        ]

        container_names = runtime_helpers.start_worker_mist(
            config,
            [machine],
            ["MQTT_LOGS=True"],
        )

        self.assertEqual(container_names, ["edge0"])
        first_call = machine.process.call_args_list[0]
        self.assertEqual(first_call.kwargs["ssh"], ["edge0@10.0.0.2"])
        issued_command = first_call.args[1][0]
        self.assertIn("--env MQTT_LOGS=True", issued_command)
        self.assertIn("--env MQTT_LOCAL_IP=10.0.0.2", issued_command)

    def test_launch_kubernetes_with_starttime_parses_trace_output(self):
        config = {
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "config": {"kube_deployment": "pod"},
                        }
                    ]
                }
            },
            "cloud_ssh": ["cloud0@10.0.0.1"],
        }
        machine = mock.Mock()
        machine.cloud_controller_names = ["cloud0"]
        machine.process.return_value = [
            (
                ["100.0\n", "job.batch/test created\n"],
                [
                    "I ... %!s(int64=100000000000) [CONTINUUM] 0400\n",
                    "I ... %!s(int64=101000000000) [CONTINUUM] 0401 job=test\n",
                    "I ... %!s(int64=102000000000) [CONTINUUM] 0402\n",
                ],
            )
        ]

        starttime, kubectl_output = runtime_helpers.launch_kubernetes_with_starttime(
            config,
            [machine],
        )

        self.assertEqual(starttime, 100.0)
        self.assertEqual(
            kubectl_output,
            [
                [101.0, "0401 job=test"],
                [100.0, "0400 job=test"],
                [102.0, "0402 job=test"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
