"""Unit tests for Kubernetes runtime handoff helpers."""

import unittest

from resource_manager.kubernetes import kubernetes


class KubernetesRuntimeTests(unittest.TestCase):
    def _config(self):
        return {
            "registry": "registry.local:5000",
            "images": {"worker": "continuum/worker:1.0"},
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

    def test_worker_global_vars_forward_benchmark_handoff_metadata(self):
        global_vars = kubernetes._worker_global_vars(
            self._config(),
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


if __name__ == "__main__":
    unittest.main()
