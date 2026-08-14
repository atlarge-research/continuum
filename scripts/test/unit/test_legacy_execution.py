"""Characterization tests for the transitional legacy execution adapter."""

import unittest
from unittest import mock

from application import application
from infrastructure import ansible
from resource_manager import legacy_execution, plans


def _resource(vm_id, cluster_id, tier, index):
    return {
        "vm_id": vm_id,
        "cluster_id": cluster_id,
        "tier": tier,
        "index_in_cluster": index,
        "tags": {"cluster": cluster_id, "tier": tier},
    }


def _inventory_groups(payload):
    groups = {}
    current_group = None
    for line in payload.splitlines():
        if line.startswith("[") and line.endswith("]"):
            current_group = line[1:-1]
            groups.setdefault(current_group, [])
            continue
        if current_group and line and "=" in line and current_group != "all:vars":
            groups[current_group].append(line.split()[0])
    return groups


class LegacyExecutionProjectionTests(unittest.TestCase):
    def _config(self, module_type, mode, resources):
        return {
            "base": "/repo",
            "mode": mode,
            "username": "continuum",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "base_path": "/tmp/continuum",
                "provider": "qemu",
                "endpoint_nodes": sum(1 for resource in resources if resource["tier"] == "endpoint"),
            },
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "%s-main" % (module_type,),
                            "type": module_type,
                            "assign_to": {"match": {"cluster": resources[0]["cluster_id"]}},
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {"infrastructure": {"resources": resources}},
        }

    def _inventory_payload(self, config, machine):
        with mock.patch("builtins.open", mock.mock_open()) as open_mock:
            ansible.create_inventory_vm(config, [machine])
        return "".join(call.args[0] for call in open_mock().write.call_args_list)

    def _assert_group_counts_match_inventory(self, config, machine):
        projected = legacy_execution.project_legacy_inventory_groups(config)
        inventory_groups = _inventory_groups(self._inventory_payload(config, machine))
        for group in legacy_execution.LEGACY_TARGET_GROUPS:
            self.assertEqual(
                len(projected[group]),
                len(inventory_groups.get(group, [])),
                group,
            )
        return projected

    def test_kubernetes_cloud_projection_matches_inventory(self):
        resources = [
            _resource(1, "cloud-a", "cloud", 0),
            _resource(2, "cloud-a", "cloud", 1),
            _resource(3, "cloud-b", "cloud", 0),
            _resource(4, "endpoint-a", "endpoint", 0),
        ]
        config = self._config("kubernetes", "cloud", resources)
        machine = mock.Mock(
            cloud_controller_ips_internal=["10.0.0.1"],
            cloud_controller_ips=["192.0.2.1"],
            cloud_controller_names=["controller"],
            cloud_names=["cloud0", "cloud1"],
            cloud_ips=["192.0.2.2", "192.0.2.3"],
            edge_names=[],
            edge_ips=[],
            endpoint_names=["endpoint0"],
            endpoint_ips=["192.0.2.4"],
            base_ips=[],
            base_names=[],
        )

        projected = self._assert_group_counts_match_inventory(config, machine)

        self.assertEqual(projected["cloudcontroller"], (1,))
        self.assertEqual(projected["clouds"], (2, 3))
        self.assertEqual(projected["edges"], ())
        self.assertEqual(projected["endpoints"], (4,))

    def test_kubeedge_edge_projection_matches_inventory(self):
        resources = [
            _resource(1, "cloud-1", "cloud", 0),
            _resource(2, "edge-1", "edge", 0),
            _resource(3, "edge-1", "edge", 1),
            _resource(4, "endpoint-1", "endpoint", 0),
        ]
        config = self._config("kubeedge", "edge", resources)
        machine = mock.Mock(
            cloud_controller_ips_internal=["10.0.0.1"],
            cloud_controller_ips=["192.0.2.1"],
            cloud_controller_names=["controller"],
            cloud_names=[],
            cloud_ips=[],
            edge_names=["edge0", "edge1"],
            edge_ips=["192.0.2.2", "192.0.2.3"],
            endpoint_names=["endpoint0"],
            endpoint_ips=["192.0.2.4"],
            base_ips=[],
            base_names=[],
        )

        projected = self._assert_group_counts_match_inventory(config, machine)

        self.assertEqual(projected["cloudcontroller"], (1,))
        self.assertEqual(projected["clouds"], ())
        self.assertEqual(projected["edges"], (2, 3))
        self.assertEqual(projected["endpoints"], (4,))

    def test_mist_and_endpoint_only_projections_match_inventory(self):
        cases = [
            (
                self._config(
                    "mist",
                    "edge",
                    [
                        _resource(1, "edge-1", "edge", 0),
                        _resource(2, "endpoint-1", "endpoint", 0),
                    ],
                ),
                mock.Mock(
                    cloud_controller_ips_internal=[],
                    cloud_controller_ips=[],
                    cloud_controller_names=[],
                    cloud_names=[],
                    cloud_ips=[],
                    edge_names=["edge0"],
                    edge_ips=["192.0.2.1"],
                    endpoint_names=["endpoint0"],
                    endpoint_ips=["192.0.2.2"],
                    base_ips=[],
                    base_names=[],
                ),
            ),
            (
                self._config(
                    "none",
                    "endpoint",
                    [_resource(1, "endpoint-1", "endpoint", 0)],
                ),
                mock.Mock(
                    cloud_controller_ips_internal=[],
                    cloud_controller_ips=[],
                    cloud_controller_names=[],
                    cloud_names=[],
                    cloud_ips=[],
                    edge_names=[],
                    edge_ips=[],
                    endpoint_names=["endpoint0"],
                    endpoint_ips=["192.0.2.1"],
                    base_ips=[],
                    base_names=[],
                ),
            ),
        ]

        for config, machine in cases:
            with self.subTest(module=config["domains"]["software"]["modules"][0]["type"]):
                self._assert_group_counts_match_inventory(config, machine)


class LegacyExecutionEnvelopeTests(unittest.TestCase):
    def _config(self, module_id, module_type, mode, resources, resolved_vm_ids):
        modules = []
        if module_type in ("endpoint_runtime", "openfaas", "observability"):
            modules.append(
                {
                    "id": "none-main",
                    "type": "none",
                    "config": {},
                    "resolved_vm_ids": [resource["vm_id"] for resource in resources],
                }
            )
        modules.append(
            {
                "id": module_id,
                "type": module_type,
                "config": {},
                "resolved_vm_ids": resolved_vm_ids,
            }
        )
        return {
            "mode": mode,
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "software": {"modules": modules}
            },
            "normalized": {"infrastructure": {"resources": resources}},
        }

    def test_partial_mist_endpoint_openfaas_and_observability_scopes_fail_closed(self):
        cases = [
            (
                "mist-main",
                "mist",
                "edge",
                [
                    _resource(1, "edge-1", "edge", 0),
                    _resource(2, "edge-2", "edge", 0),
                ],
                [1],
                "playbooks/resource_manager/mist_install.yml",
                ("edges",),
                "cluster=edge-2",
            ),
            (
                "endpoint-runtime",
                "endpoint_runtime",
                "endpoint",
                [
                    _resource(1, "endpoint-1", "endpoint", 0),
                    _resource(2, "endpoint-2", "endpoint", 0),
                ],
                [1],
                "playbooks/resource_manager/endpoint_install.yml",
                ("endpoints",),
                "cluster=endpoint-2",
            ),
            (
                "openfaas-main",
                "openfaas",
                "cloud",
                [
                    _resource(1, "cloud-1", "cloud", 0),
                    _resource(2, "cloud-2", "cloud", 0),
                ],
                [2],
                "playbooks/resource_manager/openfaas.yml",
                ("cloudcontroller",),
                "cluster=cloud-1",
            ),
            (
                "observability-main",
                "observability",
                "cloud",
                [
                    _resource(1, "cloud-1", "cloud", 0),
                    _resource(2, "cloud-2", "cloud", 0),
                ],
                [2],
                "playbooks/resource_manager/k8s_observability.yml",
                ("cloudcontroller",),
                "cluster=cloud-1",
            ),
        ]

        for (
            module_id,
            module_type,
            mode,
            resources,
            resolved_vm_ids,
            playbook,
            groups,
            missing_resource,
        ) in cases:
            config = self._config(
                module_id,
                module_type,
                mode,
                resources,
                resolved_vm_ids,
            )
            entry = plans.PlanEntry(
                kind="playbook",
                playbook=playbook,
                owner_id=module_id,
                owner_type=module_type,
                legacy_target_groups=groups,
            )

            with self.subTest(module=module_type):
                with self.assertRaises(ValueError) as exc:
                    legacy_execution.validate_software_execution_envelopes(
                        config,
                        [entry],
                        use_planner_snapshot=False,
                    )
                self.assertIn(missing_resource, str(exc.exception))
                self.assertIn("Partial assignments are unsupported", str(exc.exception))

    def test_none_with_no_entries_has_no_mutation_scope(self):
        config = self._config(
            "none-main",
            "none",
            "cloud",
            [_resource(1, "cloud-1", "cloud", 0)],
            [1],
        )

        legacy_execution.validate_software_execution_envelopes(
            config,
            [],
            use_planner_snapshot=False,
        )


class LegacyBenchmarkExecutionEnvelopeTests(unittest.TestCase):
    def _config(self, mode, resources, resolved_vm_ids):
        orchestrator = {
            "cloud": "kubernetes",
            "edge": "kubeedge",
            "endpoint": "none",
        }[mode]
        selector_id = "sel_stage_main"
        config = {
            "mode": mode,
            "infrastructure": {
                "provider": "qemu",
                "endpoint_nodes": sum(
                    1 for resource in resources if resource["tier"] == "endpoint"
                ),
            },
            "module": {
                "application": mock.Mock(),
                "resource_manager": None,
            },
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "%s-main" % (orchestrator,),
                            "type": orchestrator,
                            "config": {},
                            "selector_id": "sel_%s_main" % (orchestrator,),
                            "resolved_vm_ids": [resource["vm_id"] for resource in resources],
                            "scope_identities": [
                                {
                                    "kind": "selector",
                                    "selector_id": "sel_%s_main" % (orchestrator,),
                                }
                            ],
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-main",
                            "type": "image_classification",
                            "config": {},
                            "tags": {"benchmark.role": "primary"},
                            "selector_id": selector_id,
                            "resolved_vm_ids": resolved_vm_ids,
                            "scope_identities": [
                                {"kind": "selector", "selector_id": selector_id}
                            ],
                        }
                    ]
                },
            },
            "normalized": {"infrastructure": {"resources": resources}},
        }
        config["planner_snapshot"] = plans.build_planner_snapshot(config)
        return config

    def test_cloud_cluster_assignment_with_controller_and_all_workers_passes(self):
        config = self._config(
            "cloud",
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "cloud-1", "cloud", 1),
                _resource(3, "cloud-1", "cloud", 2),
            ],
            [1, 2, 3],
        )

        legacy_execution.validate_benchmark_execution_envelope(config)

    def test_cloud_assignment_omitting_one_worker_fails_closed(self):
        config = self._config(
            "cloud",
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "cloud-1", "cloud", 1),
                _resource(3, "cloud-2", "cloud", 0),
            ],
            [1, 2],
        )

        with self.assertRaises(ValueError) as exc:
            legacy_execution.validate_benchmark_execution_envelope(config)

        self.assertIn("cloud worker group 'clouds'", str(exc.exception))
        self.assertIn("vm_id=3 cluster=cloud-2 tier=cloud", str(exc.exception))
        self.assertIn("Partial benchmark assignments are unsupported", str(exc.exception))

    def test_edge_assignment_omitting_one_worker_fails_closed(self):
        config = self._config(
            "edge",
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "edge-1", "edge", 0),
                _resource(3, "edge-2", "edge", 0),
            ],
            [2],
        )

        with self.assertRaises(ValueError) as exc:
            legacy_execution.validate_benchmark_execution_envelope(config)

        self.assertIn("edge worker group 'edges'", str(exc.exception))
        self.assertIn("vm_id=3 cluster=edge-2 tier=edge", str(exc.exception))

    def test_complete_endpoint_worker_assignment_passes(self):
        config = self._config(
            "endpoint",
            [
                _resource(1, "endpoint-1", "endpoint", 0),
                _resource(2, "endpoint-2", "endpoint", 0),
            ],
            [1, 2],
        )

        legacy_execution.validate_benchmark_execution_envelope(config)

    def test_extra_authorized_non_worker_resource_passes(self):
        config = self._config(
            "cloud",
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "cloud-1", "cloud", 1),
                _resource(3, "endpoint-1", "endpoint", 0),
            ],
            [1, 2, 3],
        )

        legacy_execution.validate_benchmark_execution_envelope(config)

    def test_cloud_and_edge_assignments_do_not_require_endpoint_publishers(self):
        cases = [
            (
                "cloud",
                [
                    _resource(1, "cloud-1", "cloud", 0),
                    _resource(2, "cloud-1", "cloud", 1),
                    _resource(3, "endpoint-1", "endpoint", 0),
                ],
                [1, 2],
            ),
            (
                "edge",
                [
                    _resource(1, "cloud-1", "cloud", 0),
                    _resource(2, "edge-1", "edge", 0),
                    _resource(3, "endpoint-1", "endpoint", 0),
                ],
                [2],
            ),
        ]

        for mode, resources, resolved_vm_ids in cases:
            with self.subTest(mode=mode):
                config = self._config(mode, resources, resolved_vm_ids)
                legacy_execution.validate_benchmark_execution_envelope(config)

    def test_application_boundary_rejects_before_dispatch_or_runner_mutation(self):
        config = self._config(
            "cloud",
            [
                _resource(1, "cloud-1", "cloud", 0),
                _resource(2, "cloud-1", "cloud", 1),
                _resource(3, "cloud-2", "cloud", 0),
            ],
            [1, 2],
        )
        runner = mock.Mock(config=config, machines=[mock.Mock()])

        with mock.patch.object(application, "kube") as dispatch:
            with self.assertRaises(ValueError):
                application.start(runner)

        dispatch.assert_not_called()
        runner.run_playbook.assert_not_called()
        self.assertEqual(config["module"]["application"].mock_calls, [])


if __name__ == "__main__":
    unittest.main()
