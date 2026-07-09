"""Unit tests for centralized resource-manager planning helpers."""

import unittest
from types import SimpleNamespace
from unittest import mock

from resource_manager import plans
from resource_manager.endpoint import endpoint
from resource_manager.kube_kata import kube_kata
from resource_manager.kubecontrol import kubecontrol
from resource_manager.kubeedge import kubeedge
from resource_manager.kubernetes import kubernetes


def _module(
    module_id,
    module_type,
    config=None,
    resolved_vm_ids=None,
    scope_identities=None,
):
    return {
        "id": module_id,
        "type": module_type,
        "config": config or {},
        "selector_id": "sel_%s" % (module_id.replace("-", "_"),),
        "resolved_vm_ids": resolved_vm_ids or [1],
        "scope_identities": scope_identities
        or [{"kind": "selector", "selector_id": "sel_%s" % (module_id.replace("-", "_"),)}],
    }


def _stage(stage_id, stage_type, resolved_vm_ids=None, tags=None):
    return {
        "id": stage_id,
        "type": stage_type,
        "config": {"frequency": 1},
        "tags": tags or {"benchmark.role": stage_id},
        "selector_id": "sel_%s" % (stage_id.replace("-", "_"),),
        "resolved_vm_ids": resolved_vm_ids or [1],
        "scope_identities": [
            {"kind": "selector", "selector_id": "sel_%s" % (stage_id.replace("-", "_"),)}
        ],
    }


def _resource(vm_id, cluster_id, tier, index_in_cluster):
    return {
        "vm_id": vm_id,
        "cluster_id": cluster_id,
        "tier": tier,
        "index_in_cluster": index_in_cluster,
        "tags": {"tier": tier, "cluster": cluster_id},
    }


def _config(resource_manager=None, endpoint_nodes=0, modules=None, run_targets=None, pipeline=None):
    modules = modules or [_module("k8s-main", "kubernetes")]
    run_targets = run_targets or ["infrastructure", "software"]
    return {
        "module": {"resource_manager": resource_manager},
        "infrastructure": {"endpoint_nodes": endpoint_nodes},
        "domains": {
            "run": {"targets": run_targets, "image_prefetch": "off"},
            "software": {"modules": modules},
            "benchmark": {"pipeline": pipeline or []},
        },
        "normalized": {
            "infrastructure": {
                "resources": [
                    _resource(1, "cloud-1", "cloud", 0),
                    _resource(2, "cloud-1", "cloud", 1),
                    _resource(3, "endpoint-1", "endpoint", 0),
                ]
            }
        },
    }


def _add_planner_snapshot(config, software_assignments=None):
    config["planner_snapshot"] = {
        "software_execution_order": [],
        "software_plan_entries": [],
        "software_module_assignments": software_assignments or [],
        "benchmark_stage_assignments": [],
    }
    return config


def _software_assignment(module_id, module_type, resolved_vm_ids=None, resolved_resources=None):
    resolved_vm_ids = resolved_vm_ids or [1]
    return {
        "id": module_id,
        "type": module_type,
        "selector_id": "sel_%s" % (module_id.replace("-", "_"),),
        "resolved_vm_ids": resolved_vm_ids,
        "resolved_resources": resolved_resources
        or [_resource(vm_id, "cloud-1", "cloud", vm_id - 1) for vm_id in resolved_vm_ids],
        "scope_identities": [
            {"kind": "selector", "selector_id": "sel_%s" % (module_id.replace("-", "_"),)}
        ],
    }


class ExecuteEntriesTests(unittest.TestCase):
    def test_execute_entries_dispatches_playbooks_and_commands(self):
        runner = mock.Mock()
        entries = [
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/k8s_cluster.yml",
                inventory="machine",
                extra_vars={"ignore_preflight_errors": True},
                check=False,
            ),
            plans.PlanEntry(
                kind="command",
                command=["echo", "ready"],
                shell=True,
                check=False,
            ),
        ]

        plans.execute_entries(runner, entries)

        self.assertEqual(
            runner.mock_calls,
            [
                mock.call.run_playbook(
                    "playbooks/resource_manager/k8s_cluster.yml",
                    inventory="machine",
                    extra_vars={"ignore_preflight_errors": True},
                    check=False,
                ),
                mock.call.run_command(["echo", "ready"], check=False, shell=True),
            ],
        )

    def test_execute_entries_rejects_unknown_kind(self):
        runner = mock.Mock()
        with self.assertRaises(SystemExit):
            plans.execute_entries(runner, [plans.PlanEntry(kind="unsupported")])

    def test_execute_entries_rejects_playbook_without_path(self):
        runner = mock.Mock()
        with self.assertRaises(SystemExit):
            plans.execute_entries(runner, [plans.PlanEntry(kind="playbook")])

    def test_execute_entries_rejects_command_without_payload(self):
        runner = mock.Mock()
        with self.assertRaises(SystemExit):
            plans.execute_entries(runner, [plans.PlanEntry(kind="command")])


class BaseInstallPlanTests(unittest.TestCase):
    def test_build_base_image_playbooks_deduplicates_and_includes_endpoint_when_enabled(self):
        rm_module = SimpleNamespace(
            base_install_playbook=lambda _config, tier: "playbooks/%s_base.yml" % (tier)
        )
        config = _config(
            resource_manager=rm_module,
            modules=[
                _module("k8s-main", "kubernetes"),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[3]),
            ],
        )
        _add_planner_snapshot(
            config,
            [
                _software_assignment(
                    "endpoint-runtime-main",
                    "endpoint_runtime",
                    resolved_vm_ids=[3],
                    resolved_resources=[_resource(3, "endpoint-1", "endpoint", 0)],
                )
            ],
        )
        base_names = [
            "base_cloud_ubuntu",
            "base_edge_ubuntu",
            "base_endpoint_ubuntu",
            "base_cloud_ubuntu_alt",
        ]

        with mock.patch(
            "resource_manager.plans.endpoint.base_install_playbook",
            return_value="playbooks/resource_manager/endpoint_base_install.yml",
        ):
            playbooks = plans.build_base_image_playbooks(config, base_names)

        self.assertEqual(
            playbooks,
            [
                "playbooks/cloud_base.yml",
                "playbooks/edge_base.yml",
                "playbooks/resource_manager/endpoint_base_install.yml",
            ],
        )

    def test_build_base_image_playbooks_skips_endpoint_when_endpoint_runtime_disabled(self):
        rm_module = SimpleNamespace(
            base_install_playbook=lambda _config, tier: "playbooks/%s_base.yml" % (tier)
        )
        config = _config(resource_manager=rm_module)
        _add_planner_snapshot(config)
        base_names = ["base_endpoint_ubuntu", "base_cloud_ubuntu"]

        with mock.patch("resource_manager.plans.endpoint.base_install_playbook") as endpoint_playbook:
            playbooks = plans.build_base_image_playbooks(config, base_names)

        endpoint_playbook.assert_not_called()
        self.assertEqual(playbooks, ["playbooks/cloud_base.yml"])

    def test_build_base_image_playbooks_skips_endpoint_when_runtime_not_on_endpoint(self):
        rm_module = SimpleNamespace(
            base_install_playbook=lambda _config, tier: "playbooks/%s_base.yml" % (tier)
        )
        config = _config(
            resource_manager=rm_module,
            modules=[
                _module("k8s-main", "kubernetes"),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[1]),
            ],
        )
        _add_planner_snapshot(
            config,
            [
                _software_assignment(
                    "endpoint-runtime-main",
                    "endpoint_runtime",
                    resolved_vm_ids=[1],
                )
            ],
        )

        with mock.patch("resource_manager.plans.endpoint.base_install_playbook") as endpoint_playbook:
            playbooks = plans.build_base_image_playbooks(
                config,
                ["base_endpoint_ubuntu", "base_cloud_ubuntu"],
            )

        endpoint_playbook.assert_not_called()
        self.assertEqual(playbooks, ["playbooks/cloud_base.yml"])

    def test_build_base_image_playbooks_fails_when_rm_has_no_base_install_hook(self):
        config = _config(resource_manager=SimpleNamespace())
        _add_planner_snapshot(config)
        with mock.patch(
            "resource_manager.plans.config_access.has_addon",
            return_value=False,
        ), mock.patch(
            "resource_manager.plans.config_access.orchestrator_name",
            return_value="kubernetes",
        ):
            with self.assertRaises(SystemExit):
                plans.build_base_image_playbooks(config, ["base_cloud_ubuntu"])


class SoftwarePhasePlanTests(unittest.TestCase):
    def test_build_software_phase_entries_preserves_rm_order_then_addons(self):
        rm_module = SimpleNamespace(
            build_phase_plan=lambda _config: [
                plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/k8s_cluster.yml"),
                plans.PlanEntry(kind="command", command=["echo", "cluster-ready"]),
            ]
        )
        config = _config(
            resource_manager=rm_module,
            endpoint_nodes=2,
            modules=[
                _module("k8s-main", "kubernetes"),
                _module("openfaas-main", "openfaas"),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[3]),
            ],
        )

        _add_planner_snapshot(
            config,
            [
                _software_assignment(
                    "endpoint-runtime-main",
                    "endpoint_runtime",
                    resolved_vm_ids=[3],
                    resolved_resources=[_resource(3, "endpoint-1", "endpoint", 0)],
                )
            ],
        )

        entries = plans.build_software_phase_entries(config)

        self.assertEqual(
            entries,
            [
                plans.PlanEntry(
                    kind="playbook",
                    playbook="playbooks/resource_manager/k8s_cluster.yml",
                    owner_id="k8s-main",
                    owner_type="kubernetes",
                ),
                plans.PlanEntry(
                    kind="command",
                    command=["echo", "cluster-ready"],
                    owner_id="k8s-main",
                    owner_type="kubernetes",
                ),
                plans.PlanEntry(
                    kind="playbook",
                    playbook="playbooks/resource_manager/openfaas.yml",
                    owner_id="openfaas-main",
                    owner_type="openfaas",
                ),
                plans.PlanEntry(
                    kind="playbook",
                    playbook="playbooks/resource_manager/endpoint_install.yml",
                    owner_id="endpoint-runtime-main",
                    owner_type="endpoint_runtime",
                ),
            ],
        )

    def test_rm_module_start_hooks_delegate_to_centralized_entrypoint(self):
        runner = SimpleNamespace(config={})
        rm_modules = [kubernetes, kubecontrol, kube_kata, kubeedge, endpoint]

        with mock.patch("resource_manager.resource_manager.start") as centralized_start:
            for rm_module in rm_modules:
                rm_module.start(runner)

        self.assertEqual(
            centralized_start.mock_calls,
            [mock.call(runner) for _rm_module in rm_modules],
        )

    def test_kube_kata_post_phase_hook_verifies_runtime_classes_and_guest_runtime(self):
        config = {
            "cloud_ssh": ["ubuntu@10.0.0.1", "ubuntu@10.0.0.2"],
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "kube-kata-main",
                            "type": "kube_kata",
                            "config": {"runtime": "kata-qemu"},
                        }
                    ]
                }
            },
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [(
                [
                    "runtimeclass.node.k8s.io/kata-qemu\n",
                    "runtimeclass.node.k8s.io/kata-fc\n",
                    "runtimeclass.node.k8s.io/runc\n",
                ],
                ["I0709 kubectl.go:32] [CONTINUUM] 0400\n"],
            )],
            [(["kata-runtime 3.1.3\n"], [])],
        ]
        runner = SimpleNamespace(config=config, machines=[machine])

        with mock.patch(
            "resource_manager.kube_kata.kube_kata.kubernetes.verify_running_cluster"
        ) as verify_cluster, mock.patch(
            "resource_manager.kube_kata.kube_kata.requests.get"
        ) as mock_requests_get:
            mock_requests_get.return_value.raise_for_status.return_value = None
            kube_kata.post_phase_hook(runner)

        verify_cluster.assert_called_once_with(config, [machine])
        mock_requests_get.assert_called_once_with("http://10.0.0.2:16686/api/services", timeout=10)
        self.assertEqual(machine.process.call_count, 2)
        self.assertIn(
            "kubectl get runtimeclass kata-qemu kata-fc runc -o name",
            machine.process.call_args_list[0].args[1],
        )
        self.assertIn("/opt/kata/bin/kata-runtime --version", machine.process.call_args_list[1].args[1])
        self.assertIn("http://127.0.0.1:16686/api/services", machine.process.call_args_list[1].args[1])
        self.assertEqual(machine.process.call_args_list[1].kwargs["ssh"], "ubuntu@10.0.0.2")

    def test_kube_kata_post_phase_hook_fails_fast_when_jaeger_is_unreachable(self):
        config = {
            "cloud_ssh": ["ubuntu@10.0.0.1", "ubuntu@10.0.0.2"],
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "kube-kata-main",
                            "type": "kube_kata",
                            "config": {"runtime": "kata-qemu"},
                        }
                    ]
                }
            },
        }
        machine = mock.Mock()
        machine.process.side_effect = [
            [(["runtimeclass.node.k8s.io/kata-qemu\n", "runtimeclass.node.k8s.io/runc\n"], [])],
            [(["kata-runtime 3.1.3\n"], [])],
        ]
        runner = SimpleNamespace(config=config, machines=[machine])

        with mock.patch(
            "resource_manager.kube_kata.kube_kata.kubernetes.verify_running_cluster"
        ), mock.patch(
            "resource_manager.kube_kata.kube_kata.requests.get",
            side_effect=kube_kata.requests.ConnectionError("connection refused"),
        ):
            with self.assertRaises(RuntimeError) as exc:
                kube_kata.post_phase_hook(runner)

        self.assertIn("Kata Jaeger query API is not reachable", str(exc.exception))
        self.assertIn("http://10.0.0.2:16686/api/services", str(exc.exception))

    def test_kube_kata_timestamps_skip_incomplete_jaeger_traces(self):
        complete_trace = [
            {"operationName": "rootSpan", "startTime": 100, "duration": 1},
            {"operationName": "StartVM", "startTime": 110, "duration": 20},
            {"operationName": "connect", "startTime": 140, "duration": 5},
            {"operationName": "ttrpc.StartContainer", "startTime": 150, "duration": 2},
            {"operationName": "ttrpc.StartContainer", "startTime": 160, "duration": 3},
        ]
        incomplete_trace = [
            {"operationName": "rootSpan", "startTime": 200, "duration": 1},
            {"operationName": "StartVM", "startTime": 210, "duration": 20},
            {"operationName": "connect", "startTime": 240, "duration": 5},
        ]

        with self.assertLogs(level="WARNING") as logs:
            timestamps = kube_kata.get_kata_period_timestamps([incomplete_trace, complete_trace])

        self.assertEqual(timestamps, [[100, 110, 130, 145, 163]])
        self.assertIn("Skipped 1 incomplete Kata trace", "\n".join(logs.output))

    def test_kube_kata_timestamps_fail_when_no_complete_jaeger_trace_exists(self):
        traces = [
            [
                {"operationName": "rootSpan", "startTime": 100, "duration": 1},
                {"operationName": "connect", "startTime": 140, "duration": 5},
            ]
        ]

        with self.assertRaises(RuntimeError) as exc:
            kube_kata.get_kata_period_timestamps(traces)

        self.assertIn("No complete Kata traces", str(exc.exception))

    def test_kube_kata_timestamps_retry_until_expected_rows_are_available(self):
        config = {
            "mode": "cloud",
            "cloud_ssh": ["ubuntu@10.0.0.1", "ubuntu@10.0.0.2"],
            "infrastructure": {"cloud_nodes": 2, "edge_nodes": 0},
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "empty-kata-pod",
                            "type": "empty_kata",
                            "config": {"applications_per_worker": 2},
                        }
                    ]
                }
            },
        }
        incomplete_trace = [
            {"operationName": "rootSpan", "startTime": 50, "duration": 1},
            {"operationName": "StartVM", "startTime": 60, "duration": 5},
        ]
        complete_trace_1 = [
            {"operationName": "rootSpan", "startTime": 100, "duration": 1},
            {"operationName": "StartVM", "startTime": 110, "duration": 20},
            {"operationName": "connect", "startTime": 140, "duration": 5},
            {"operationName": "ttrpc.StartContainer", "startTime": 150, "duration": 2},
            {"operationName": "ttrpc.StartContainer", "startTime": 160, "duration": 3},
        ]
        complete_trace_2 = [
            {"operationName": "rootSpan", "startTime": 200, "duration": 1},
            {"operationName": "StartVM", "startTime": 210, "duration": 20},
            {"operationName": "connect", "startTime": 240, "duration": 5},
            {"operationName": "ttrpc.StartContainer", "startTime": 250, "duration": 2},
            {"operationName": "ttrpc.StartContainer", "startTime": 260, "duration": 3},
        ]

        with mock.patch(
            "resource_manager.kube_kata.kube_kata._gather_kata_traces",
            side_effect=[
                [incomplete_trace, complete_trace_1],
                [incomplete_trace, complete_trace_1, complete_trace_2],
            ],
        ) as gather, mock.patch("resource_manager.kube_kata.kube_kata.time.sleep") as sleep:
            timestamps = kube_kata.get_kata_timestamps(config, _worker_output=None)

        self.assertEqual(
            timestamps,
            [
                [100, 110, 130, 145, 163],
                [200, 210, 230, 245, 263],
            ],
        )
        self.assertEqual(gather.call_count, 2)
        sleep.assert_called_once_with(15)

    def test_build_software_phase_entries_skips_endpoint_install_when_runtime_absent(self):
        config = _config(resource_manager=None, endpoint_nodes=0)
        _add_planner_snapshot(config)
        entries = plans.build_software_phase_entries(config)

        self.assertEqual(entries, [])

    def test_build_software_phase_entries_skips_endpoint_install_when_addon_not_on_endpoint(self):
        config = _config(
            endpoint_nodes=1,
            modules=[
                _module("k8s-main", "kubernetes"),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[1]),
            ],
        )
        _add_planner_snapshot(
            config,
            [
                _software_assignment(
                    "endpoint-runtime-main",
                    "endpoint_runtime",
                    resolved_vm_ids=[1],
                )
            ],
        )

        entries = plans.build_software_phase_entries(config)

        self.assertEqual(entries, [])

    def test_build_software_phase_entries_fails_when_rm_has_no_phase_plan_hook(self):
        config = _config(resource_manager=SimpleNamespace(), endpoint_nodes=0)
        _add_planner_snapshot(config)
        with mock.patch(
            "resource_manager.plans.config_access.orchestrator_name",
            return_value="kubernetes",
        ):
            with self.assertRaises(SystemExit):
                plans.build_software_phase_entries(config)

    def test_build_software_phase_entries_uses_planner_snapshot_for_endpoint_install(self):
        config = _config(
            modules=[
                _module("k8s-main", "kubernetes"),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[1]),
            ],
        )
        _add_planner_snapshot(
            config,
            [
                _software_assignment(
                    "endpoint-runtime-main",
                    "endpoint_runtime",
                    resolved_vm_ids=[3],
                    resolved_resources=[_resource(3, "endpoint-1", "endpoint", 0)],
                )
            ],
        )

        entries = plans.build_software_phase_entries(config)

        self.assertEqual(
            entries,
            [
                plans.PlanEntry(
                    kind="playbook",
                    playbook="playbooks/resource_manager/endpoint_install.yml",
                    owner_id="endpoint-runtime-main",
                    owner_type="endpoint_runtime",
                )
            ],
        )

    def test_build_planner_snapshot_captures_execution_order_and_assignments(self):
        rm_module = SimpleNamespace(
            build_phase_plan=lambda _config: [
                plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/k8s_cluster.yml"),
                plans.PlanEntry(
                    kind="playbook",
                    playbook="playbooks/resource_manager/k8s_observability.yml",
                    owner_id="obs-main",
                    owner_type="observability",
                ),
            ]
        )
        config = _config(
            resource_manager=rm_module,
            endpoint_nodes=1,
            modules=[
                _module("k8s-main", "kubernetes", resolved_vm_ids=[1, 2]),
                _module("obs-main", "observability", resolved_vm_ids=[1]),
                _module("endpoint-runtime-main", "endpoint_runtime", resolved_vm_ids=[3]),
            ],
            run_targets=["infrastructure", "software", "application"],
            pipeline=[_stage("classify", "image_classification", resolved_vm_ids=[2, 3])],
        )

        snapshot = plans.build_planner_snapshot(config)

        self.assertEqual(
            snapshot["software_execution_order"],
            ["k8s-main", "obs-main", "endpoint-runtime-main"],
        )
        self.assertEqual(
            snapshot["software_plan_entries"],
            [
                {
                    "kind": "playbook",
                    "owner_id": "k8s-main",
                    "owner_type": "kubernetes",
                    "playbook": "playbooks/resource_manager/k8s_cluster.yml",
                },
                {
                    "kind": "playbook",
                    "owner_id": "obs-main",
                    "owner_type": "observability",
                    "playbook": "playbooks/resource_manager/k8s_observability.yml",
                },
                {
                    "kind": "playbook",
                    "owner_id": "endpoint-runtime-main",
                    "owner_type": "endpoint_runtime",
                    "playbook": "playbooks/resource_manager/endpoint_install.yml",
                },
            ],
        )
        self.assertEqual(snapshot["software_module_assignments"][0]["resolved_vm_ids"], [1, 2])
        self.assertEqual(
            snapshot["benchmark_stage_assignments"],
            [
                {
                    "id": "classify",
                    "type": "image_classification",
                    "selector_id": "sel_classify",
                    "resolved_vm_ids": [2, 3],
                    "resolved_resources": [
                        _resource(2, "cloud-1", "cloud", 1),
                        _resource(3, "endpoint-1", "endpoint", 0),
                    ],
                    "scope_identities": [{"kind": "selector", "selector_id": "sel_classify"}],
                    "tags": {"benchmark.role": "classify"},
                }
            ],
        )
        self.assertEqual(
            snapshot["software_module_assignments"][0]["resolved_resources"],
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "cloud-1", "cloud", 1),
            ],
        )

    def test_build_planner_snapshot_rejects_unknown_assignment_resource(self):
        config = _config(
            modules=[
                _module("k8s-main", "kubernetes", resolved_vm_ids=[99]),
            ],
        )

        with self.assertRaises(ValueError) as exc:
            plans.build_planner_snapshot(config)

        self.assertIn(
            "Resolved vm_id 99 for software module 'k8s-main' is missing",
            str(exc.exception),
        )

    def test_build_planner_snapshot_rejects_resource_tag_mismatch(self):
        config = _config()
        config["normalized"]["infrastructure"]["resources"][0]["tags"]["tier"] = "edge"

        with self.assertRaises(ValueError) as exc:
            plans.build_planner_snapshot(config)

        self.assertIn("Invalid resolved resource tier tag", str(exc.exception))

    def test_validate_planner_snapshot_rejects_mismatch_at_precise_path(self):
        expected = {
            "software_execution_order": ["k8s-main"],
            "software_plan_entries": [],
            "software_module_assignments": [],
            "benchmark_stage_assignments": [],
        }
        observed = {
            "software_execution_order": ["other-main"],
            "software_plan_entries": [],
            "software_module_assignments": [],
            "benchmark_stage_assignments": [],
        }

        with self.assertRaises(ValueError) as exc:
            plans.validate_planner_snapshot(observed, expected)

        self.assertIn("planner_snapshot.software_execution_order[0]", str(exc.exception))
        self.assertIn(
            "must match deterministic planner snapshot derived from canonical config",
            str(exc.exception),
        )


class PostPhaseHookTests(unittest.TestCase):
    def test_run_post_phase_hook_calls_rm_post_hook(self):
        post_hook = mock.Mock()
        runner = SimpleNamespace(
            config={"module": {"resource_manager": SimpleNamespace(post_phase_hook=post_hook)}}
        )

        plans.run_post_phase_hook(runner)

        post_hook.assert_called_once_with(runner)

    def test_run_post_phase_hook_is_noop_without_hook(self):
        runner = SimpleNamespace(config={"module": {"resource_manager": SimpleNamespace()}})

        plans.run_post_phase_hook(runner)


if __name__ == "__main__":
    unittest.main()
