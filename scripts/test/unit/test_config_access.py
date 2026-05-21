"""Unit tests for config access helpers after PR-3 hard cutover."""

import unittest

from input.configuration import config_access


class ConfigAccessTests(unittest.TestCase):
    def _normalized_resources(self):
        return {
            "infrastructure": {
                "resources": [
                    {
                        "vm_id": 1,
                        "cluster_id": "cloud-1",
                        "tier": "cloud",
                        "index_in_cluster": 0,
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    },
                    {
                        "vm_id": 2,
                        "cluster_id": "cloud-1",
                        "tier": "cloud",
                        "index_in_cluster": 1,
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    },
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    },
                ]
            }
        }

    def _config_with_modules(self):
        return {
            "domains": {
                "run": {"targets": ["infrastructure", "software"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"cache_worker": "true", "kube_version": "v1.27.0"},
                        },
                        {
                            "id": "openfaas-main",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                    ],
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "classify",
                            "type": "image_classification",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "tags": {"benchmark.role": "classify"},
                            "config": {"frequency": 1},
                        },
                        {
                            "id": "translate",
                            "type": "text_translation",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "tags": {"benchmark.role": "translate"},
                            "config": {"frequency": 2},
                        },
                    ]
                },
            },
        }

    def _config_single_stage(self):
        return {
            "mode": "cloud",
            "domains": {
                "run": {"targets": ["application"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"cache_worker": "true", "kube_version": "v1.27.0"},
                        },
                        {
                            "id": "openfaas-main",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                            "resolved_vm_ids": [2],
                        },
                        {
                            "id": "endpoint-runtime-main",
                            "type": "endpoint_runtime",
                            "assign_to": {"match": {"cluster": "endpoint-1"}},
                            "config": {},
                            "resolved_vm_ids": [3],
                        },
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "classify",
                            "type": "image_classification",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "tags": {"benchmark.role": "classify"},
                            "config": {
                                "frequency": 2,
                                "duration": 120,
                                "applications_per_worker": 3,
                                "application_worker_cpu": 0.5,
                                "application_worker_memory": 2.0,
                                "application_endpoint_cpu": 0.5,
                                "application_endpoint_memory": 1.5,
                            },
                        }
                    ]
                },
            },
            "normalized": self._normalized_resources(),
        }

    def _add_planner_snapshot(self, cfg):
        cfg["planner_snapshot"] = {
            "software_execution_order": ["k8s-main"],
            "software_plan_entries": [],
            "software_module_assignments": [
                {
                    "id": "endpoint-runtime-main",
                    "type": "endpoint_runtime",
                    "selector_id": "sel_endpoint_runtime",
                    "resolved_vm_ids": [3],
                    "resolved_resources": [
                        {
                            "vm_id": 3,
                            "cluster_id": "endpoint-1",
                            "tier": "endpoint",
                            "index_in_cluster": 0,
                            "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                        }
                    ],
                    "scope_identities": [
                        {"kind": "selector", "selector_id": "sel_endpoint_runtime"}
                    ],
                }
            ],
            "benchmark_stage_assignments": [
                {
                    "id": "classify",
                    "type": "image_classification",
                    "selector_id": "sel_classify",
                    "resolved_vm_ids": [1, 2, 3],
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
                            "cluster_id": "cloud-1",
                            "tier": "cloud",
                            "index_in_cluster": 1,
                            "tags": {"tier": "cloud", "cluster": "cloud-1"},
                        },
                        {
                            "vm_id": 3,
                            "cluster_id": "endpoint-1",
                            "tier": "endpoint",
                            "index_in_cluster": 0,
                            "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                        },
                    ],
                    "scope_identities": [{"kind": "selector", "selector_id": "sel_classify"}],
                    "tags": {"benchmark.role": "classify"},
                }
            ],
        }
        return cfg

    def test_run_helpers_domain_targets(self):
        cfg = {
            "domains": {
                "run": {
                    "targets": ["infrastructure", "software"],
                    "image_prefetch": "off",
                    "prepare_for_resume": False,
                }
            }
        }
        self.assertEqual(config_access.run_targets(cfg), ["infrastructure", "software"])
        self.assertTrue(config_access.runs_infrastructure(cfg))
        self.assertTrue(config_access.runs_software(cfg))
        self.assertFalse(config_access.runs_application(cfg))
        self.assertFalse(config_access.infra_only(cfg))
        self.assertEqual(config_access.image_prefetch_mode(cfg), "off")
        self.assertFalse(config_access.image_prefetch_enabled(cfg))
        self.assertFalse(config_access.prepare_for_resume_enabled(cfg))

    def test_run_helpers_require_domain_targets(self):
        cfg = {}
        with self.assertRaises(ValueError):
            config_access.run_targets(cfg)

    def test_image_prefetch_helpers(self):
        cfg = {"domains": {"run": {"targets": ["software"], "image_prefetch": "on"}}}
        self.assertEqual(config_access.image_prefetch_mode(cfg), "on")
        self.assertTrue(config_access.image_prefetch_enabled(cfg))

    def test_image_prefetch_requires_domain_path(self):
        cfg = {"domains": {"run": {"targets": ["software"]}}}
        with self.assertRaises(ValueError):
            config_access.image_prefetch_mode(cfg)

    def test_image_prefetch_rejects_invalid_mode(self):
        cfg = {"domains": {"run": {"targets": ["software"], "image_prefetch": "always"}}}
        with self.assertRaises(ValueError):
            config_access.image_prefetch_mode(cfg)

    def test_prepare_for_resume_helpers(self):
        cfg = {
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": True,
                }
            }
        }
        self.assertTrue(config_access.prepare_for_resume_enabled(cfg))

    def test_prepare_for_resume_requires_domain_path(self):
        cfg = {"domains": {"run": {"targets": ["infrastructure"]}}}
        with self.assertRaises(ValueError) as exc:
            config_access.prepare_for_resume_enabled(cfg)
        self.assertIn("domains.run.prepare_for_resume", str(exc.exception))

    def test_prepare_for_resume_rejects_invalid_type(self):
        cfg = {
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": "true",
                }
            }
        }
        with self.assertRaises(ValueError) as exc:
            config_access.prepare_for_resume_enabled(cfg)
        self.assertIn("domains.run.prepare_for_resume", str(exc.exception))

    def test_runtime_logs_dir_uses_base_path_workspace(self):
        cfg = {
            "infrastructure": {"base_path": "/tmp/continuum-run"},
            "domains": {"run": {"targets": ["infrastructure"]}},
        }
        self.assertEqual(config_access.continuum_home(cfg), "/tmp/continuum-run/.continuum")
        self.assertEqual(
            config_access.runtime_logs_dir(cfg),
            "/tmp/continuum-run/.continuum/logs",
        )
        self.assertEqual(
            config_access.network_validation_logs_dir(cfg),
            "/tmp/continuum-run/.continuum/logs/network_validation",
        )
        self.assertEqual(
            config_access.benchmark_logs_dir(cfg),
            "/tmp/continuum-run/.continuum/logs/benchmark",
        )

    def test_orchestrator_and_addon_helpers(self):
        cfg = self._config_with_modules()
        self.assertEqual(config_access.orchestrator_name(cfg), "kubernetes")
        self.assertTrue(config_access.orchestrator_name(cfg) in ("kubernetes", "kubeedge"))
        self.assertTrue(config_access.has_addon(cfg, "openfaas"))
        self.assertFalse(config_access.has_addon(cfg, "observability"))
        self.assertEqual(config_access.software_module_by_type(cfg, "openfaas")["id"], "openfaas-main")
        self.assertTrue(config_access.orchestrator_bool(cfg, "cache_worker"))
        self.assertEqual(config_access.orchestrator_value(cfg, "kube_version"), "v1.27.0")

    def test_benchmark_pipeline_helpers(self):
        cfg = self._config_with_modules()
        self.assertEqual(config_access.benchmark_stage_ids(cfg), ["classify", "translate"])
        stage = config_access.benchmark_stage(cfg, "translate")
        self.assertEqual(stage["type"], "text_translation")
        self.assertEqual(stage["tags"]["benchmark.role"], "translate")

    def test_benchmark_param_helpers(self):
        cfg = self._config_single_stage()
        self.assertEqual(config_access.benchmark_primary_stage_type(cfg), "image_classification")
        self.assertEqual(config_access.benchmark_param(cfg, "frequency"), 2)
        self.assertEqual(config_access.benchmark_param(cfg, "duration"), 120)
        self.assertEqual(config_access.benchmark_param_int(cfg, "applications_per_worker"), 3)
        self.assertEqual(config_access.benchmark_param_float(cfg, "application_worker_cpu"), 0.5)
        self.assertEqual(config_access.benchmark_param_float(cfg, "application_worker_memory"), 2.0)
        self.assertEqual(config_access.benchmark_param_float(cfg, "application_endpoint_cpu"), 0.5)
        self.assertEqual(config_access.benchmark_param_float(cfg, "application_endpoint_memory"), 1.5)

    def test_benchmark_param_with_stage_id(self):
        cfg = self._config_with_modules()
        self.assertEqual(config_access.benchmark_param_int(cfg, "frequency", stage_id="classify"), 1)
        self.assertEqual(config_access.benchmark_param_int(cfg, "frequency", stage_id="translate"), 2)

    def test_benchmark_primary_stage_returns_first_stage_in_gated_runtime_path(self):
        cfg = self._config_with_modules()
        self.assertEqual(config_access.benchmark_primary_stage(cfg)["id"], "classify")

    def test_benchmark_assignment_helpers_read_planner_snapshot(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())

        assignment = config_access.benchmark_stage_assignment(cfg)

        self.assertEqual(assignment["id"], "classify")
        self.assertEqual(config_access.benchmark_stage_resolved_resource_count(cfg), 3)
        self.assertEqual(
            config_access.benchmark_stage_resolved_resources(cfg, tier="endpoint"),
            [
                {
                    "vm_id": 3,
                    "cluster_id": "endpoint-1",
                    "tier": "endpoint",
                    "index_in_cluster": 0,
                    "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                }
            ],
        )

    def test_benchmark_stage_handoff_exposes_runtime_snapshot_metadata(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())

        handoff = config_access.benchmark_stage_handoff(cfg)

        self.assertEqual(
            handoff,
            {
                "id": "classify",
                "type": "image_classification",
                "pipeline_index": 0,
                "selector_id": "sel_classify",
                "config": {
                    "frequency": 2,
                    "duration": 120,
                    "applications_per_worker": 3,
                    "application_worker_cpu": 0.5,
                    "application_worker_memory": 2.0,
                    "application_endpoint_cpu": 0.5,
                    "application_endpoint_memory": 1.5,
                },
                "resolved_vm_ids": [1, 2, 3],
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
                        "cluster_id": "cloud-1",
                        "tier": "cloud",
                        "index_in_cluster": 1,
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    },
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    },
                ],
                "scope_identities": [{"kind": "selector", "selector_id": "sel_classify"}],
                "tags": {"benchmark.role": "classify"},
                "resource_counts_by_tier": {"cloud": 2, "endpoint": 1},
            },
        )
        handoff["resolved_resources"][0]["tags"]["tier"] = "mutated"
        handoff["config"]["frequency"] = 999
        self.assertEqual(
            cfg["planner_snapshot"]["benchmark_stage_assignments"][0]["resolved_resources"][0][
                "tags"
            ]["tier"],
            "cloud",
        )
        self.assertEqual(cfg["domains"]["benchmark"]["pipeline"][0]["config"]["frequency"], 2)

    def test_benchmark_stage_handoffs_preserve_pipeline_order(self):
        cfg = self._add_planner_snapshot(self._config_with_modules())
        cfg["planner_snapshot"]["benchmark_stage_assignments"].append(
            {
                "id": "translate",
                "type": "text_translation",
                "selector_id": "sel_translate",
                "resolved_vm_ids": [3],
                "resolved_resources": [
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    }
                ],
                "scope_identities": [{"kind": "selector", "selector_id": "sel_translate"}],
                "tags": {"benchmark.role": "translate"},
            }
        )

        handoffs = config_access.benchmark_stage_handoffs(cfg)

        self.assertEqual([handoff["id"] for handoff in handoffs], ["classify", "translate"])
        self.assertEqual([handoff["pipeline_index"] for handoff in handoffs], [0, 1])
        self.assertEqual([handoff["config"]["frequency"] for handoff in handoffs], [1, 2])
        self.assertEqual(handoffs[0]["resource_counts_by_tier"], {"cloud": 2, "endpoint": 1})
        self.assertEqual(handoffs[1]["resource_counts_by_tier"], {"endpoint": 1})

    def test_benchmark_assignment_helpers_fail_without_planner_snapshot(self):
        cfg = self._config_single_stage()
        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_stage_assignment(cfg)
        self.assertIn("planner_snapshot", str(exc.exception))

    def test_benchmark_assignment_helpers_reject_type_mismatch(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["benchmark_stage_assignments"][0]["type"] = "text_translation"
        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_stage_assignment(cfg)
        self.assertIn("type must match domains.benchmark.pipeline", str(exc.exception))

    def test_benchmark_assignment_helpers_reject_resolved_resource_vm_id_mismatch(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["benchmark_stage_assignments"][0]["resolved_resources"][0][
            "vm_id"
        ] = 2

        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_stage_assignment(cfg)

        self.assertIn("resolved_resources[0].vm_id", str(exc.exception))
        self.assertIn("must match", str(exc.exception))

    def test_benchmark_assignment_helpers_reject_malformed_scope_identity(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["benchmark_stage_assignments"][0]["scope_identities"] = [
            {"kind": "selector"}
        ]

        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_stage_assignment(cfg)

        self.assertIn("scope_identities[0].selector_id", str(exc.exception))

    def test_benchmark_assignment_helpers_reject_resolved_resource_tag_mismatch(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["benchmark_stage_assignments"][0]["resolved_resources"][0][
            "tags"
        ]["cluster"] = "other-cluster"

        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_stage_assignment(cfg)

        self.assertIn("resolved_resources[0].tags.cluster", str(exc.exception))
        self.assertIn("must match", str(exc.exception))

    def test_software_module_assignment_helpers_resolve_canonical_resources(self):
        cfg = self._config_single_stage()

        self.assertEqual(
            config_access.software_module_resolved_resources(
                cfg,
                "endpoint_runtime",
                tier="endpoint",
            ),
            [
                {
                    "vm_id": 3,
                    "cluster_id": "endpoint-1",
                    "tier": "endpoint",
                    "index_in_cluster": 0,
                    "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                }
            ],
        )
        self.assertEqual(
            config_access.software_module_resolved_resource_count(
                cfg,
                "endpoint_runtime",
                tier="endpoint",
            ),
            1,
        )

    def test_software_module_assignment_helpers_read_planner_snapshot(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["domains"]["software"]["modules"][2]["resolved_vm_ids"] = [1]

        self.assertEqual(
            config_access.software_module_assignment(cfg, "endpoint_runtime")["id"],
            "endpoint-runtime-main",
        )
        self.assertEqual(
            config_access.software_module_assignment_resolved_resources(
                cfg,
                "endpoint_runtime",
                tier="endpoint",
            ),
            [
                {
                    "vm_id": 3,
                    "cluster_id": "endpoint-1",
                    "tier": "endpoint",
                    "index_in_cluster": 0,
                    "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                }
            ],
        )
        self.assertEqual(
            config_access.software_module_assignment_resolved_resource_count(
                cfg,
                "endpoint_runtime",
                tier="endpoint",
            ),
            1,
        )

    def test_software_module_assignment_handoff_exposes_runtime_snapshot_metadata(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["domains"]["software"]["modules"][2]["resolved_vm_ids"] = [1]

        handoff = config_access.software_module_assignment_handoff(cfg, "endpoint_runtime")

        self.assertEqual(
            handoff,
            {
                "id": "endpoint-runtime-main",
                "type": "endpoint_runtime",
                "module_index": 2,
                "selector_id": "sel_endpoint_runtime",
                "config": {},
                "resolved_vm_ids": [3],
                "resolved_resources": [
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    }
                ],
                "scope_identities": [
                    {"kind": "selector", "selector_id": "sel_endpoint_runtime"}
                ],
                "resource_counts_by_tier": {"endpoint": 1},
            },
        )
        handoff["resolved_resources"][0]["tags"]["tier"] = "mutated"
        handoff["config"]["mutated"] = True
        self.assertEqual(
            cfg["planner_snapshot"]["software_module_assignments"][0]["resolved_resources"][0][
                "tags"
            ]["tier"],
            "endpoint",
        )
        self.assertEqual(cfg["domains"]["software"]["modules"][2]["config"], {})

    def test_software_module_assignment_handoffs_preserve_module_order(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["software_module_assignments"] = [
            {
                "id": "k8s-main",
                "type": "kubernetes",
                "selector_id": "sel_k8s_main",
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
                        "cluster_id": "cloud-1",
                        "tier": "cloud",
                        "index_in_cluster": 1,
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    },
                ],
                "scope_identities": [{"kind": "selector", "selector_id": "sel_k8s_main"}],
            },
            {
                "id": "openfaas-main",
                "type": "openfaas",
                "selector_id": "sel_openfaas_main",
                "resolved_vm_ids": [2],
                "resolved_resources": [
                    {
                        "vm_id": 2,
                        "cluster_id": "cloud-1",
                        "tier": "cloud",
                        "index_in_cluster": 1,
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    }
                ],
                "scope_identities": [
                    {"kind": "selector", "selector_id": "sel_openfaas_main"}
                ],
            },
            {
                "id": "endpoint-runtime-main",
                "type": "endpoint_runtime",
                "selector_id": "sel_endpoint_runtime",
                "resolved_vm_ids": [3],
                "resolved_resources": [
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    }
                ],
                "scope_identities": [
                    {"kind": "selector", "selector_id": "sel_endpoint_runtime"}
                ],
            },
        ]

        handoffs = config_access.software_module_assignment_handoffs(cfg)

        self.assertEqual(
            [handoff["id"] for handoff in handoffs],
            ["k8s-main", "openfaas-main", "endpoint-runtime-main"],
        )
        self.assertEqual([handoff["module_index"] for handoff in handoffs], [0, 1, 2])
        self.assertEqual(handoffs[0]["config"]["cache_worker"], "true")
        self.assertEqual(handoffs[1]["config"], {})
        self.assertEqual(handoffs[2]["config"], {})
        self.assertEqual(handoffs[0]["resource_counts_by_tier"], {"cloud": 2})
        self.assertEqual(handoffs[1]["resource_counts_by_tier"], {"cloud": 1})
        self.assertEqual(handoffs[2]["resource_counts_by_tier"], {"endpoint": 1})
        self.assertEqual(
            config_access.planner_runtime_handoff(cfg),
            {
                "software_modules": handoffs,
                "benchmark_stages": [config_access.benchmark_stage_handoff(cfg)],
            },
        )

    def test_software_module_assignment_handoffs_are_instance_id_based(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["domains"]["software"]["modules"] = [
            {
                "id": "obs-cloud",
                "type": "observability",
                "config": {"scope": "cloud"},
            },
            {
                "id": "obs-edge",
                "type": "observability",
                "config": {"scope": "edge"},
            },
        ]
        cfg["planner_snapshot"]["software_module_assignments"] = [
            {
                "id": "obs-cloud",
                "type": "observability",
                "selector_id": "sel_obs_cloud",
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
                "scope_identities": [{"kind": "selector", "selector_id": "sel_obs_cloud"}],
            },
            {
                "id": "obs-edge",
                "type": "observability",
                "selector_id": "sel_obs_edge",
                "resolved_vm_ids": [3],
                "resolved_resources": [
                    {
                        "vm_id": 3,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    }
                ],
                "scope_identities": [{"kind": "selector", "selector_id": "sel_obs_edge"}],
            },
        ]

        handoffs = config_access.software_module_assignment_handoffs(cfg)

        obs_edge_assignment = config_access.software_module_assignment_by_id(cfg, "obs-edge")
        obs_edge_handoff = config_access.software_module_assignment_handoff_by_id(cfg, "obs-edge")

        self.assertEqual([handoff["id"] for handoff in handoffs], ["obs-cloud", "obs-edge"])
        self.assertEqual([handoff["module_index"] for handoff in handoffs], [0, 1])
        self.assertEqual(
            [handoff["selector_id"] for handoff in handoffs],
            ["sel_obs_cloud", "sel_obs_edge"],
        )
        self.assertEqual([handoff["config"]["scope"] for handoff in handoffs], ["cloud", "edge"])
        self.assertEqual(config_access.software_module_by_id(cfg, "obs-edge")["id"], "obs-edge")
        self.assertEqual(obs_edge_assignment["selector_id"], "sel_obs_edge")
        self.assertEqual(obs_edge_handoff, handoffs[1])
        with self.assertRaises(ValueError) as exc:
            config_access.software_module_assignment_handoff(cfg, "observability")
        self.assertIn(
            "Multiple software modules found for type 'observability'",
            str(exc.exception),
        )

    def test_software_module_assignment_helpers_reject_resolved_resource_vm_id_mismatch(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["software_module_assignments"][0]["resolved_resources"][0][
            "vm_id"
        ] = 1

        with self.assertRaises(ValueError) as exc:
            config_access.software_module_assignment(cfg, "endpoint_runtime")

        self.assertIn("resolved_resources[0].vm_id", str(exc.exception))
        self.assertIn("must match", str(exc.exception))

    def test_software_module_assignment_helpers_reject_resolved_resource_tag_mismatch(self):
        cfg = self._add_planner_snapshot(self._config_single_stage())
        cfg["planner_snapshot"]["software_module_assignments"][0]["resolved_resources"][0][
            "tags"
        ]["tier"] = "cloud"

        with self.assertRaises(ValueError) as exc:
            config_access.software_module_assignment(cfg, "endpoint_runtime")

        self.assertIn("resolved_resources[0].tags.tier", str(exc.exception))
        self.assertIn("must match", str(exc.exception))

    def test_software_module_assignment_helpers_reject_unknown_resolved_vm_id(self):
        cfg = self._config_single_stage()
        cfg["domains"]["software"]["modules"][2]["resolved_vm_ids"] = [99]

        with self.assertRaises(ValueError) as exc:
            config_access.software_module_resolved_resources(cfg, "endpoint_runtime")
        self.assertIn("Resolved vm_id 99", str(exc.exception))

    def test_benchmark_param_numeric_helpers_reject_invalid_values(self):
        cfg = self._config_single_stage()
        cfg["domains"]["benchmark"]["pipeline"][0]["config"]["applications_per_worker"] = True
        with self.assertRaises(ValueError):
            config_access.benchmark_param_int(cfg, "applications_per_worker")
        cfg["domains"]["benchmark"]["pipeline"][0]["config"]["applications_per_worker"] = 1
        cfg["domains"]["benchmark"]["pipeline"][0]["config"]["application_worker_cpu"] = "not-a-number"
        with self.assertRaises(ValueError):
            config_access.benchmark_param_float(cfg, "application_worker_cpu")

    def test_benchmark_param_required_key_missing_fails_fast(self):
        cfg = self._config_single_stage()
        del cfg["domains"]["benchmark"]["pipeline"][0]["config"]["duration"]
        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_param(cfg, "duration")
        self.assertIn("domains.benchmark.pipeline[0].config.duration", str(exc.exception))

    def test_orchestrator_bool_rejects_invalid_string(self):
        cfg = self._config_with_modules()
        cfg["domains"]["software"]["modules"][0]["config"]["cache_worker"] = "yes"
        with self.assertRaises(ValueError) as exc:
            config_access.orchestrator_bool(cfg, "cache_worker")
        self.assertIn("Invalid boolean value for orchestrator config key 'cache_worker'", str(exc.exception))

    def test_optional_orchestrator_helpers_return_defaults(self):
        cfg = self._config_with_modules()
        del cfg["domains"]["software"]["modules"][0]["config"]["cache_worker"]
        self.assertIsNone(config_access.orchestrator_value_optional(cfg, "cache_worker"))
        self.assertFalse(config_access.orchestrator_bool_optional(cfg, "cache_worker"))

    def test_benchmark_pipeline_missing_fails(self):
        cfg = {"domains": {"benchmark": {}}}
        with self.assertRaises(ValueError):
            config_access.benchmark_pipeline(cfg)

    def test_benchmark_stage_missing_fails(self):
        cfg = self._config_with_modules()
        with self.assertRaises(ValueError):
            config_access.benchmark_stage(cfg, "does-not-exist")

    def test_benchmark_pipeline_rejects_malformed_stage_shape(self):
        cfg = self._config_with_modules()
        del cfg["domains"]["benchmark"]["pipeline"][0]["id"]
        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_pipeline(cfg)
        self.assertIn("domains.benchmark.pipeline[0].id", str(exc.exception))

    def test_benchmark_pipeline_rejects_duplicate_stage_ids(self):
        cfg = self._config_with_modules()
        cfg["domains"]["benchmark"]["pipeline"][1]["id"] = "classify"
        with self.assertRaises(ValueError) as exc:
            config_access.benchmark_pipeline(cfg)
        self.assertIn("domains.benchmark.pipeline[1].id", str(exc.exception))
        self.assertIn("duplicate benchmark stage id 'classify'", str(exc.exception))

    def test_software_modules_rejects_missing_module_config(self):
        cfg = self._config_with_modules()
        del cfg["domains"]["software"]["modules"][0]["config"]
        with self.assertRaises(ValueError) as exc:
            config_access.software_modules(cfg)
        self.assertIn("domains.software.modules[0].config", str(exc.exception))

    def test_software_modules_rejects_duplicate_module_ids(self):
        cfg = self._config_with_modules()
        cfg["domains"]["software"]["modules"][1]["id"] = "k8s-main"
        with self.assertRaises(ValueError) as exc:
            config_access.software_modules(cfg)
        self.assertIn("domains.software.modules[1].id", str(exc.exception))
        self.assertIn("duplicate module id 'k8s-main'", str(exc.exception))

    def test_legacy_benchmark_workload_helpers_removed_from_api(self):
        removed_names = [
            "benchmark_config",
            "benchmark_value",
            "benchmark_int",
            "docker_pull_enabled",
            "applications_per_worker",
            "worker_cpu_cores",
            "worker_memory_gb",
            "endpoint_cpu_cores",
            "endpoint_memory_gb",
            "cache_worker_enabled",
            "kube_deployment_mode",
            "kube_version",
            "runtime_name",
            "openfaas_enabled",
            "observability_enabled",
            "endpoint_runtime_enabled",
            "orchestrator_is",
            "workload",
            "workload_name",
            "workload_config",
            "workload_value",
            "workload_int",
        ]
        for name in removed_names:
            self.assertFalse(hasattr(config_access, name), msg="expected removed helper: %s" % (name,))


if __name__ == "__main__":
    unittest.main()
