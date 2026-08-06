"""Unit tests for experiment lock writing helpers."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

from input.configuration import experiment_lock_writer


class ExperimentLockWriterTests(unittest.TestCase):
    def _minimal_config(self, root: Path, sources=None):
        run = {
            "targets": ["infrastructure"],
            "dry_run": False,
            "clean": False,
            "image_prefetch": "off",
            "prepare_for_resume": False,
        }
        module = {
            "id": "none-main",
            "type": "none",
            "assign_to": {"match": {"cluster": "cloud-1"}},
            "config": {},
            "selector_id": "sel_none_main",
            "resolved_vm_ids": [1],
            "scope_identities": [{"kind": "selector", "selector_id": "sel_none_main"}],
        }
        resource = {
            "vm_id": 1,
            "cluster_id": "cloud-1",
            "tier": "cloud",
            "index_in_cluster": 0,
            "tags": {"tier": "cloud", "cluster": "cloud-1"},
        }
        cluster = {
            "id": "cloud-1",
            "tier": "cloud",
            "resources": {"vms": {"count": 1, "spec": {"cores": 1}}},
        }
        network = {"emulation": False, "wireless_preset": "4g", "overrides": {}}
        provider = {
            "name": "qemu",
            "config": {
                "base_path": str(root),
                "cpu_pin": False,
                "external_physical_machines": [],
                "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                "netperf": False,
                "delete_on_exit": False,
            },
        }
        return {
            "config_format": "yaml",
            "infrastructure": {"base_path": str(root), "endpoint_nodes": 0},
            "module": {"resource_manager": False},
            "domains": {
                "run": run,
                "provider": provider,
                "software": {"modules": [module]},
                "infrastructure": {
                    "clusters": [cluster],
                    "network": network,
                    "resources": [resource],
                },
                "benchmark": {},
            },
            "normalized": {
                "schema_version": 1,
                "kind": "ContinuumNormalizedConfig",
                "sources": sources or {},
                "run": run,
                "provider": provider,
                "software": {"modules": [module]},
                "infrastructure": {
                    "clusters": [cluster],
                    "network": network,
                    "resources": [resource],
                },
            },
        }

    def test_returns_none_for_non_yaml_config(self):
        self.assertIsNone(experiment_lock_writer.write_experiment_lock({"config_format": "ini"}))

    def test_raises_for_missing_normalized_config(self):
        with self.assertRaises(ValueError) as exc:
            experiment_lock_writer.write_experiment_lock(
                {
                    "config_format": "yaml",
                    "infrastructure": {"base_path": "/tmp"},
                }
            )
        self.assertIn("Missing required config.normalized", str(exc.exception))

    def test_writes_lock_file_with_hashes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp = root / "exp.yaml"
            env = root / "env.yaml"
            sw = root / "sw.yaml"
            exp.write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            env.write_text("kind: ContinuumEnvironment\n", encoding="utf-8")
            sw.write_text("kind: ContinuumSoftware\n", encoding="utf-8")

            config = self._minimal_config(
                root,
                sources={
                    "experiment": str(exp),
                    "environment_profile": str(env),
                    "software_profile": str(sw),
                },
            )

            lock_path = experiment_lock_writer.write_experiment_lock(config)
            self.assertIsNotNone(lock_path)
            lock_file = Path(lock_path)
            self.assertTrue(lock_file.exists())

            payload = yaml.safe_load(lock_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "ContinuumExperimentLock")
            hashes = payload["sources"]["hashes"]
            self.assertIn("experiment_sha256", hashes)
            self.assertIn("environment_profile_sha256", hashes)
            self.assertIn("software_profile_sha256", hashes)
            self.assertIn("resume_contract", payload)
            self.assertTrue(payload["resume_contract"]["hash"].startswith("sha256:"))

    def test_creates_lock_with_mode_0600_under_umask_022(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            previous_umask = os.umask(0o022)
            try:
                lock_path = experiment_lock_writer.write_experiment_lock(
                    self._minimal_config(root)
                )
            finally:
                os.umask(previous_umask)

            mode = stat.S_IMODE(Path(lock_path).stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_replacing_existing_lock_resets_mode_to_0600(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            lock_path = root / ".continuum" / "experiment_lock.yaml"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("old lock\n", encoding="utf-8")
            lock_path.chmod(0o644)

            written_path = experiment_lock_writer.write_experiment_lock(
                self._minimal_config(root)
            )

            self.assertEqual(Path(written_path), lock_path)
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
            payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "ContinuumExperimentLock")

    def test_replace_failure_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            lock_path = root / ".continuum" / "experiment_lock.yaml"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("old lock\n", encoding="utf-8")

            with mock.patch.object(
                experiment_lock_writer.os,
                "replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    experiment_lock_writer.write_experiment_lock(self._minimal_config(root))

            self.assertEqual(lock_path.read_text(encoding="utf-8"), "old lock\n")
            self.assertEqual(
                list(lock_path.parent.glob(".experiment_lock.yaml.*.tmp")),
                [],
            )

    def test_writes_planner_snapshot_when_domains_are_available(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = {
                "config_format": "yaml",
                "infrastructure": {"base_path": str(root), "endpoint_nodes": 1},
                "module": {
                    "resource_manager": SimpleNamespace(
                        build_phase_plan=lambda _config: [
                            SimpleNamespace(
                                kind="playbook",
                                playbook="playbooks/resource_manager/k8s_cluster.yml",
                                inventory="vms",
                                extra_vars=None,
                                command=None,
                                shell=False,
                                check=True,
                                owner_id="k8s-main",
                                owner_type="kubernetes",
                            )
                        ]
                    )
                },
                "domains": {
                    "run": {
                        "targets": ["infrastructure", "software", "application"],
                        "image_prefetch": "off",
                    },
                    "software": {
                        "modules": [
                            {
                                "id": "k8s-main",
                                "type": "kubernetes",
                                "config": {},
                                "selector_id": "sel_k8s_main",
                                "resolved_vm_ids": [1],
                                "scope_identities": [
                                    {"kind": "selector", "selector_id": "sel_k8s_main"}
                                ],
                            },
                            {
                                "id": "endpoint-runtime-main",
                                "type": "endpoint_runtime",
                                "config": {},
                                "selector_id": "sel_endpoint_runtime_main",
                                "resolved_vm_ids": [2],
                                "scope_identities": [
                                    {
                                        "kind": "selector",
                                        "selector_id": "sel_endpoint_runtime_main",
                                    }
                                ],
                            },
                        ]
                    },
                    "benchmark": {
                        "pipeline": [
                            {
                                "id": "classify",
                                "type": "image_classification",
                                "config": {"frequency": 1},
                                "tags": {"benchmark.role": "classify"},
                                "selector_id": "sel_classify",
                                "resolved_vm_ids": [2],
                                "scope_identities": [
                                    {"kind": "selector", "selector_id": "sel_classify"}
                                ],
                            }
                        ]
                    },
                },
                "normalized": {
                    "schema_version": 1,
                    "kind": "ContinuumNormalizedConfig",
                    "sources": {},
                    "provider": {
                        "name": "qemu",
                        "config": {
                            "base_path": str(root),
                            "cpu_pin": False,
                            "external_physical_machines": [],
                            "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                            "netperf": False,
                            "delete_on_exit": False,
                        },
                    },
                    "software": {
                        "modules": [
                            {
                                "id": "k8s-main",
                                "type": "kubernetes",
                                "config": {},
                                "selector_id": "sel_k8s_main",
                                "resolved_vm_ids": [1],
                                "scope_identities": [
                                    {"kind": "selector", "selector_id": "sel_k8s_main"}
                                ],
                            },
                            {
                                "id": "endpoint-runtime-main",
                                "type": "endpoint_runtime",
                                "config": {},
                                "selector_id": "sel_endpoint_runtime_main",
                                "resolved_vm_ids": [2],
                                "scope_identities": [
                                    {
                                        "kind": "selector",
                                        "selector_id": "sel_endpoint_runtime_main",
                                    }
                                ],
                            },
                        ]
                    },
                    "infrastructure": {
                        "clusters": [
                            {
                                "id": "cloud-1",
                                "tier": "cloud",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 2}}},
                            },
                            {
                                "id": "endpoint-1",
                                "tier": "endpoint",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 1}}},
                            },
                        ],
                        "network": {
                            "emulation": False,
                            "wireless_preset": "4g",
                            "overrides": {},
                        },
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
                                "cluster_id": "endpoint-1",
                                "tier": "endpoint",
                                "index_in_cluster": 0,
                                "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                            },
                        ]
                    },
                },
            }

            lock_path = experiment_lock_writer.write_experiment_lock(config)
            payload = yaml.safe_load(Path(lock_path).read_text(encoding="utf-8"))

            self.assertEqual(
                payload["planner_snapshot"]["software_execution_order"],
                ["k8s-main", "endpoint-runtime-main"],
            )
            self.assertEqual(
                payload["planner_snapshot"]["benchmark_stage_assignments"][0]["id"],
                "classify",
            )
            self.assertEqual(
                payload["planner_snapshot"]["benchmark_stage_assignments"][0][
                    "resolved_resources"
                ],
                [
                    {
                        "vm_id": 2,
                        "cluster_id": "endpoint-1",
                        "tier": "endpoint",
                        "index_in_cluster": 0,
                        "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
