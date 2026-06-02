"""Unit tests for application runtime helper extraction."""

import json
import os
import tempfile
import unittest
from unittest import mock

from application import runtime_helpers


class ApplicationRuntimeHelpersTests(unittest.TestCase):
    def test_write_benchmark_metric_artifacts_persists_manifest_and_csv(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {
                "timestamp": "2026-05-21_15:30:42",
                "infrastructure": {"base_path": tempdir},
                "domains": {
                    "benchmark": {
                        "pipeline": [
                            {
                                "id": "classify",
                                "type": "image_classification",
                                "config": {},
                            }
                        ]
                    }
                },
            }
            dataframe = runtime_helpers.pd.DataFrame(
                [{"endpoint_id": 0, "latency_avg (ms)": 12.5}]
            )

            manifest_path = runtime_helpers.write_benchmark_metric_artifacts(
                config,
                [{"label": "ENDPOINT OUTPUT", "dataframe": dataframe}],
            )

            self.assertIsNotNone(manifest_path)
            self.assertTrue(os.path.isfile(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as filep:
                manifest = json.load(filep)

            self.assertEqual(manifest["kind"], "ContinuumBenchmarkMetrics")
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["stage_id"], "classify")
            self.assertEqual(manifest["stage_type"], "image_classification")
            self.assertEqual(manifest["tables"][0]["label"], "ENDPOINT OUTPUT")
            self.assertEqual(manifest["tables"][0]["rows"], 1)
            self.assertIn("latency_avg (ms)", manifest["tables"][0]["columns"])
            self.assertTrue(os.path.isfile(manifest["tables"][0]["path"]))

    def test_batched_kubernetes_command_leaves_semicolons_for_remote_shell(self):
        command = runtime_helpers._batched_kubernetes_command(
            [
                ["kubectl", "logs", "--timestamps=true", "image-classification-1-kltqv"],
                ["kubectl", "logs", "--timestamps=true", "image-classification-1-kltqv", "empty-1"],
            ]
        )

        self.assertEqual(
            command,
            'kubectl logs --timestamps=true image-classification-1-kltqv;'
            'echo "DELIMITER01234";'
            'kubectl logs --timestamps=true image-classification-1-kltqv empty-1;'
            'echo "DELIMITER01234"',
        )
        self.assertFalse(command.startswith('"'))
        self.assertNotRegex(command, r'^".*"$')

    def _planner_handoff_config(self):
        return {
            "registry": "registry.local:5000",
            "images": {"worker": "continuum/worker:1.0"},
            "infrastructure": {
                "base_path": "/tmp/continuum-run",
                "cloud_nodes": 3,
                "cloud_cores": 8,
                "endpoint_nodes": 0,
            },
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "config": {
                                "kube_deployment": "pod",
                                "runtime": "runc",
                                "runtime_filesystem": "overlayfs",
                            },
                            "resolved_vm_ids": [1, 2],
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "classify",
                            "type": "image_classification",
                            "config": {
                                "applications_per_worker": 2,
                                "application_worker_cpu": 0.5,
                                "application_worker_memory": 1.5,
                            },
                        }
                    ]
                },
            },
            "planner_snapshot": {
                "software_execution_order": ["k8s-main"],
                "software_plan_entries": [],
                "software_module_assignments": [
                    {
                        "id": "k8s-main",
                        "type": "kubernetes",
                        "selector_id": "sel_k8s_main",
                        "resolved_vm_ids": [1],
                        "resolved_resources": [
                            {
                                "vm_id": 1,
                                "cluster_id": "cloud-1",
                                "tier": "cloud",
                                "index_in_cluster": 0,
                                "tags": {"tier": "cloud", "cluster": "cloud-1"},
                            }
                        ],
                        "scope_identities": [
                            {"kind": "selector", "selector_id": "sel_k8s_main"}
                        ],
                    }
                ],
                "benchmark_stage_assignments": [
                    {
                        "id": "classify",
                        "type": "image_classification",
                        "selector_id": "sel_classify",
                        "resolved_vm_ids": [1, 2],
                        "resolved_resources": [
                            {
                                "vm_id": 1,
                                "cluster_id": "cloud-1",
                                "tier": "cloud",
                                "index_in_cluster": 0,
                                "tags": {"tier": "cloud", "cluster": "cloud-1"},
                            },
                            {
                                "vm_id": 2,
                                "cluster_id": "edge-1",
                                "tier": "edge",
                                "index_in_cluster": 0,
                                "tags": {"tier": "edge", "cluster": "edge-1"},
                            },
                        ],
                        "scope_identities": [
                            {"kind": "selector", "selector_id": "sel_classify"}
                        ],
                        "tags": {"benchmark.role": "classify"},
                    }
                ],
            },
        }

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

        self.assertEqual(runtime_helpers.kubernetes_worker_count(config), 2)
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
        self.assertEqual(first_call.kwargs["ssh"], "edge0@10.0.0.2")
        issued_command = first_call.args[1]
        self.assertIn("--env MQTT_LOGS=True", issued_command)
        self.assertIn("--env MQTT_LOCAL_IP=10.0.0.2", issued_command)
        status_call = machine.process.call_args_list[1]
        self.assertEqual(
            status_call.args[1],
            'docker container ls -a --format "{{.ID}}: {{.Status}} {{.Names}}"',
        )

    @mock.patch("application.runtime_helpers.time.sleep", autospec=True)
    def test_start_worker_mist_allows_nonfatal_ssh_and_docker_warnings(self, _mock_sleep):
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
            [
                (
                    ["container-id"],
                    [
                        "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\n",
                        "WARNING: Your kernel does not support swap limit capabilities.\n",
                    ],
                )
            ],
            [(["deadbeef: Up 2 seconds edge0"], [])],
        ]

        container_names = runtime_helpers.start_worker_mist(
            config,
            [machine],
            ["MQTT_LOGS=True"],
        )

        self.assertEqual(container_names, ["edge0"])

    @mock.patch("application.runtime_helpers.time.sleep", autospec=True)
    def test_start_worker_mist_retries_transient_ssh_startup_failure(self, mock_sleep):
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
            [([], ["Timeout, server 10.0.0.2 not responding.\n"])],
            [(["container-id"], [])],
            [(["deadbeef: Up 2 seconds edge0"], [])],
        ]

        container_names = runtime_helpers.start_worker_mist(
            config,
            [machine],
            ["MQTT_LOGS=True"],
        )

        self.assertEqual(container_names, ["edge0"])
        self.assertEqual(machine.process.call_args_list[0].kwargs["ssh"], "edge0@10.0.0.2")
        self.assertEqual(machine.process.call_args_list[1].kwargs["ssh"], "edge0@10.0.0.2")
        mock_sleep.assert_any_call(2)

    def test_run_kubernetes_benchmark_playbook_uses_generated_path(self):
        config = self._planner_handoff_config()
        runner = mock.Mock()
        with mock.patch("application.runtime_helpers.os.path.isfile", return_value=True):
            runtime_helpers.run_kubernetes_benchmark_playbook(
                config,
                {"key": "value"},
                runner=runner,
            )

        runner.run_playbook.assert_called_once_with(
            "/tmp/continuum-run/.continuum/launch_benchmark.yml",
            inventory="vms",
            extra_vars={"key": "value"},
        )

    def test_resolve_benchmark_launch_playbook_prefers_openfaas_addon_playbook(self):
        config = self._planner_handoff_config()
        config["base"] = "/tmp/continuum-repo"
        config["domains"]["software"]["modules"].append(
            {
                "id": "openfaas-main",
                "type": "openfaas",
                "config": {},
            }
        )
        runner = mock.Mock()
        runner.repo_root = "/repo-root"

        def fake_isfile(path):
            return path in {
                "/tmp/continuum-run/.continuum/launch_benchmark.yml",
                "/repo-root/application/image_classification/launch_benchmark_openfaas.yml",
            }

        with mock.patch("application.runtime_helpers.os.path.isfile", side_effect=fake_isfile):
            playbook = runtime_helpers.resolve_benchmark_launch_playbook(
                config,
                runner=runner,
            )

        self.assertEqual(
            playbook,
            "/repo-root/application/image_classification/launch_benchmark_openfaas.yml",
        )

    def test_resolve_benchmark_launch_playbook_falls_back_to_repo_playbook(self):
        config = self._planner_handoff_config()
        config["base"] = "/tmp/continuum-repo"
        runner = mock.Mock()
        runner.repo_root = "/repo-root"

        def fake_isfile(path):
            return path == (
                "/repo-root/application/image_classification/launch_benchmark_kubernetes.yml"
            )

        with mock.patch("application.runtime_helpers.os.path.isfile", side_effect=fake_isfile):
            playbook = runtime_helpers.resolve_benchmark_launch_playbook(
                config,
                runner=runner,
            )

        self.assertEqual(
            playbook,
            "/repo-root/application/image_classification/launch_benchmark_kubernetes.yml",
        )

    def test_resolve_benchmark_launch_playbook_without_kube_deployment_uses_plain_orchestrator_name(self):
        config = self._planner_handoff_config()
        config["base"] = "/tmp/continuum-repo"
        config["domains"]["software"]["modules"][0]["config"].pop("kube_deployment", None)
        runner = mock.Mock()
        runner.repo_root = "/repo-root"

        def fake_isfile(path):
            return path == (
                "/repo-root/application/image_classification/launch_benchmark_kubernetes.yml"
            )

        with mock.patch("application.runtime_helpers.os.path.isfile", side_effect=fake_isfile):
            playbook = runtime_helpers.resolve_benchmark_launch_playbook(
                config,
                runner=runner,
            )

        self.assertEqual(
            playbook,
            "/repo-root/application/image_classification/launch_benchmark_kubernetes.yml",
        )

    def test_start_worker_dispatches_to_kubernetes_runtime_helpers(self):
        config = self._planner_handoff_config()
        machine = mock.Mock()

        with mock.patch.object(
            runtime_helpers,
            "start_kubernetes_workers",
            return_value=(12.0, [["trace"]]),
        ) as mock_start_kube, mock.patch.object(
            runtime_helpers,
            "wait_kubernetes_workers_ready",
            return_value=[{"Running": 2, "Succeeded": 0}],
        ) as mock_wait:
            starttime, kubectl_output, status = runtime_helpers.start_worker(
                config,
                [machine],
                {"key": "value"},
                get_starttime=True,
                runner=mock.sentinel.runner,
            )

        self.assertEqual(starttime, 12.0)
        self.assertEqual(kubectl_output, [["trace"]])
        self.assertEqual(status, [{"Running": 2, "Succeeded": 0}])
        mock_start_kube.assert_called_once_with(
            config,
            [machine],
            {"key": "value"},
            get_starttime=True,
            runner=mock.sentinel.runner,
        )
        mock_wait.assert_called_once_with(config, [machine], True)

    def test_wait_kubernetes_workers_ready_defaults_missing_kube_deployment_to_pod_mode(self):
        config = self._planner_handoff_config()
        config["domains"]["software"]["modules"][0]["config"].pop("kube_deployment")
        config["mode"] = "cloud"
        config["cloud_ssh"] = ["cloudcontroller@10.0.0.1"]
        machine = mock.Mock()
        machine.process.return_value = [
            (
                [
                    "100.0\n",
                    "NAME STATUS\n",
                    "worker-a Running\n",
                    "worker-b Running\n",
                    "worker-c Succeeded\n",
                    "worker-d Running\n",
                ],
                [],
            )
        ]

        status = runtime_helpers.wait_kubernetes_workers_ready(
            config,
            [machine],
            get_starttime=True,
        )

        self.assertEqual(status[0]["Arriving"], 0)
        self.assertEqual(status[0]["Running"], 3)
        self.assertEqual(status[0]["Succeeded"], 1)
        machine.process.assert_called_once()
        command = machine.process.call_args.args[1]
        self.assertTrue(command.startswith("date +'%s.%N'; kubectl get pods "))
        self.assertFalse(command.startswith("\""))

    def test_wait_kubernetes_workers_ready_exits_on_empty_status_output(self):
        config = self._planner_handoff_config()
        config["mode"] = "cloud"
        config["cloud_ssh"] = ["cloudcontroller@10.0.0.1"]
        machine = mock.Mock()
        machine.process.return_value = [([], [])]

        with self.assertRaises(SystemExit):
            runtime_helpers.wait_kubernetes_workers_ready(
                config,
                [machine],
                get_starttime=False,
            )

    @mock.patch("application.runtime_helpers.time.sleep", autospec=True)
    def test_wait_kubernetes_worker_completion_tracks_succeeded_pods(self, mock_sleep):
        config = {
            "mode": "cloud",
            "cloud_ssh": ["cloud0@10.0.0.1"],
            "infrastructure": {
                "cloud_nodes": 2,
                "edge_nodes": 0,
            },
        }
        controller = mock.Mock()
        controller.cloud_controller = True
        worker = mock.Mock()
        worker.cloud_controller = False
        controller.process.side_effect = [
            [(["NAME STATUS\n", "worker-a Running\n"], [])],
            [(["NAME STATUS\n", "worker-a Succeeded\n"], [])],
        ]

        runtime_helpers.wait_kubernetes_worker_completion(config, [controller, worker])

        self.assertEqual(controller.process.call_count, 2)
        mock_sleep.assert_called_once_with(5)

    def test_start_kubernetes_workers_runs_playbook_with_shared_vars(self):
        config = self._planner_handoff_config()
        config["mode"] = "cloud"
        machine = mock.Mock()

        with mock.patch.object(
            runtime_helpers,
            "run_kubernetes_benchmark_playbook",
        ) as mock_run_playbook:
            starttime, kubectl_output = runtime_helpers.start_kubernetes_workers(
                config,
                [machine],
                {"custom": "value"},
                runner=mock.sentinel.runner,
            )

        self.assertIsNone(starttime)
        self.assertIsNone(kubectl_output)
        mock_run_playbook.assert_called_once()
        called_config, extra_vars = mock_run_playbook.call_args.args
        self.assertIs(called_config, config)
        self.assertEqual(extra_vars["custom"], "value")
        self.assertEqual(extra_vars["replicas"], 4)
        self.assertEqual(extra_vars["app_name"], "image-classification")
        self.assertEqual(extra_vars["benchmark_stage_id"], "classify")
        self.assertEqual(extra_vars["runtime"], "runc")
        self.assertEqual(extra_vars["runtime_filesystem"], "overlayfs")
        self.assertEqual(extra_vars["pull_policy"], "IfNotPresent")
        self.assertEqual(
            mock_run_playbook.call_args.kwargs,
            {"runner": mock.sentinel.runner},
        )

    def test_start_kubernetes_workers_uses_never_pull_policy_after_cache_worker(self):
        config = self._planner_handoff_config()
        config["mode"] = "cloud"
        config["domains"]["software"]["modules"][0]["config"]["cache_worker"] = True
        machine = mock.Mock()

        with mock.patch.object(
            runtime_helpers,
            "run_kubernetes_benchmark_playbook",
        ) as mock_run_playbook:
            runtime_helpers.start_kubernetes_workers(
                config,
                [machine],
                {"custom": "value"},
                runner=mock.sentinel.runner,
            )

        _called_config, extra_vars = mock_run_playbook.call_args.args
        self.assertEqual(extra_vars["pull_policy"], "Never")

    def test_cache_kubernetes_workers_runs_cache_lifecycle(self):
        config = self._planner_handoff_config()
        config["mode"] = "cloud"
        config["cloud_ssh"] = ["cloudcontroller@10.0.0.1"]
        config["infrastructure"].update(
            {
                "cloud_nodes": 3,
                "cloud_cores": 8,
            }
        )
        config["domains"]["software"]["modules"][0]["config"]["kube_deployment"] = "pod"

        machine = mock.Mock()
        machine.cloud_controller_names = ["cloudcontroller"]
        machine.process.side_effect = [
            [(["job.batch/demo created\n"], [])],
            [(["NAME STATUS\n", "job-0 Succeeded\n", "job-1 Succeeded\n"], [])],
            [(["job.batch/demo deleted\n"], [])],
        ]

        with mock.patch.object(
            runtime_helpers,
            "run_kubernetes_benchmark_playbook",
        ) as mock_run_playbook, mock.patch(
            "application.runtime_helpers.time.sleep",
            autospec=True,
        ) as mock_sleep:
            runtime_helpers.cache_kubernetes_workers(
                config,
                [machine],
                {"custom": "value"},
                runner=mock.sentinel.runner,
            )

        self.assertEqual(mock_run_playbook.call_count, 1)
        called_config, extra_vars = mock_run_playbook.call_args.args
        self.assertIs(called_config, config)
        self.assertEqual(extra_vars["custom"], "value")
        self.assertEqual(extra_vars["replicas"], 2)
        self.assertEqual(extra_vars["pull_policy"], "IfNotPresent")
        self.assertEqual(extra_vars["cpu_req"], 4.0)
        self.assertEqual(
            mock_run_playbook.call_args.kwargs,
            {"runner": mock.sentinel.runner},
        )
        self.assertEqual(machine.process.call_args_list[0].kwargs["ssh"], "cloudcontroller@10.0.0.1")
        self.assertEqual(machine.process.call_args_list[0].kwargs["shell"], True)
        self.assertEqual(
            machine.process.call_args_list[2].args[1],
            ["kubectl", "delete", "-f", "/home/cloudcontroller/job-template.yaml"],
        )
        self.assertEqual(mock_sleep.call_count, 2)

    def test_start_kubernetes_resource_metrics_waits_then_launches_collectors(self):
        config = {
            "cloud_ssh": ["cloudcontroller@10.0.0.1", "cloud0@10.0.0.2"],
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [([], ["metrics api unavailable"])],
            [(["ok"], [])],
            [([], [])],
            [([], [])],
        ]

        with mock.patch("application.runtime_helpers.time.sleep", autospec=True) as mock_sleep:
            runtime_helpers.start_kubernetes_resource_metrics(config, [machine])

        self.assertEqual(machine.process.call_args_list[0].args[1], ["kubectl", "top", "nodes"])
        self.assertEqual(machine.process.call_args_list[0].kwargs["ssh"], "cloudcontroller@10.0.0.1")
        self.assertEqual(machine.process.call_args_list[2].kwargs["wait"], False)
        self.assertEqual(machine.process.call_args_list[3].kwargs["wait"], False)
        self.assertEqual(machine.process.call_args_list[3].kwargs["ssh"], config["cloud_ssh"])
        self.assertEqual(mock_sleep.call_count, 1)

    def test_get_kubernetes_control_output_parses_and_filters_component_logs(self):
        config = {
            "cloud_ssh": ["cloudcontroller@10.0.0.1"],
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [([], [])],
            [([], [])],
            [(
                [
                    "I ... kubelet.go %!s(int64=101000000000) [CONTINUUM] 0401 worker\n",
                    "I ... scheduler.go %!s(int64=102000000000) [CONTINUUM] 0402 done\n",
                    "noise without component\n",
                ],
                [],
            )],
        ]

        control_output, endtime = runtime_helpers.get_kubernetes_control_output(
            config,
            [machine],
            starttime=100.0,
            status=[{"time_orig": 103.0}],
        )

        self.assertEqual(endtime, 103.0)
        self.assertEqual(control_output["cloudcontroller"]["kubelet"], [[101.0, "0401 worker"]])
        self.assertEqual(control_output["cloudcontroller"]["scheduler"], [[102.0, "0402 done"]])

    def test_get_kubernetes_resource_output_fetches_and_filters_csv_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            continuum_dir = os.path.join(tempdir, ".continuum")
            os.makedirs(continuum_dir, exist_ok=True)
            with open(os.path.join(continuum_dir, "resource_usage.csv"), "w", encoding="utf-8") as handle:
                handle.write("timestamp,cpu,memory\n")
                handle.write("9000000000,1,10\n")
                handle.write("10500000000,2,20\n")
                handle.write("12000000000,3,30\n")
            with open(
                os.path.join(continuum_dir, "resource_usage_os-cloudcontroller.csv"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("timestamp,cpu-used (%),memory-used (%)\n")
                handle.write("10500000000,11,21\n")
                handle.write("11000000000,12,22\n")

            config = {
                "infrastructure": {"base_path": tempdir},
                "cloud_ssh": ["cloudcontroller@10.0.0.1"],
            }
            runner = mock.Mock()

            kube_df, os_df = runtime_helpers.get_kubernetes_resource_output(
                config,
                [mock.Mock()],
                starttime=10.0,
                endtime=11.0,
                runner=runner,
            )

        runner.run_playbook.assert_any_call("playbooks/resource_manager/k8s_resource_usage_back.yml")
        runner.run_playbook.assert_any_call("playbooks/resource_manager/k8s_resource_usage_os_back.yml")
        self.assertEqual(runner.run_playbook.call_count, 2)
        self.assertEqual(list(kube_df["timestamp"]), [0.5])
        self.assertEqual(list(os_df["Time (s)"]), [0.5, 1.0])
        self.assertIn("cpu-used cloudcontroller (%)", os_df.columns)
        self.assertIn("memory-used cloudcontroller (%)", os_df.columns)

    def test_kubernetes_worker_global_vars_forward_planner_handoff_metadata(self):
        global_vars = runtime_helpers.kubernetes_worker_global_vars(
            self._planner_handoff_config(),
            worker_apps=4,
            cpu_req=0.5,
            pull_policy="Never",
        )

        self.assertEqual(global_vars["app_name"], "image-classification")
        self.assertEqual(global_vars["image"], "registry.local:5000/1.0")
        self.assertEqual(global_vars["memory_req"], 1500)
        self.assertEqual(global_vars["replicas"], 4)
        self.assertEqual(global_vars["benchmark_stage_id"], "classify")
        self.assertEqual(global_vars["benchmark_stage_type"], "image_classification")
        self.assertEqual(global_vars["benchmark_selector_id"], "sel_classify")
        self.assertEqual(global_vars["benchmark_handoff"]["pipeline_index"], 0)
        self.assertEqual(global_vars["benchmark_handoff"]["config"]["applications_per_worker"], 2)
        self.assertEqual(global_vars["benchmark_resolved_vm_ids"], [1, 2])
        self.assertEqual(global_vars["benchmark_resource_counts_by_tier"], {"cloud": 1, "edge": 1})
        self.assertEqual(
            global_vars["benchmark_scope_identities"],
            [{"kind": "selector", "selector_id": "sel_classify"}],
        )
        self.assertEqual(global_vars["benchmark_tags"], {"benchmark.role": "classify"})
        self.assertEqual(
            global_vars["benchmark_handoff"]["resource_counts_by_tier"],
            global_vars["benchmark_resource_counts_by_tier"],
        )
        self.assertEqual(
            global_vars["benchmark_pipeline_handoffs"],
            [global_vars["benchmark_handoff"]],
        )
        self.assertEqual(
            global_vars["planner_handoff"]["benchmark_stages"],
            global_vars["benchmark_pipeline_handoffs"],
        )
        self.assertEqual(
            global_vars["planner_handoff"]["software_modules"],
            global_vars["software_module_handoffs"],
        )
        self.assertEqual(
            [handoff["id"] for handoff in global_vars["software_module_handoffs"]],
            ["k8s-main"],
        )
        self.assertEqual(
            global_vars["software_module_handoffs"][0]["resource_counts_by_tier"],
            {"cloud": 1},
        )
        self.assertEqual(global_vars["software_module_handoffs"][0]["module_index"], 0)
        self.assertEqual(
            global_vars["software_module_handoffs"][0]["config"]["runtime"],
            "runc",
        )
        self.assertEqual(global_vars["runtime"], "runc")
        self.assertEqual(global_vars["runtime_filesystem"], "overlayfs")

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
