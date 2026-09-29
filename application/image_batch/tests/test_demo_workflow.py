"""Study orchestration preserves matched inputs, time reserves and restoration evidence."""

import copy
import importlib
from pathlib import Path
import tempfile
import unittest


class WorkflowTests(unittest.TestCase):
    """Test the real study boundaries without running remote experiments."""

    def module(self):
        """Load the tracked orchestration implementation.

        Returns:
            module: Workflow implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("demo_workflow"))
        return importlib.import_module("demo_workflow")

    def test_time_gate_reserves_followup_emission_setup_and_closure(self):
        """A run cannot consume the protected closure window even if arrivals fit."""
        module = self.module()
        settings = {"period_seconds": 480, "cycles": 4, "followup_seconds": 600}
        self.assertEqual(module.run_budget_seconds(settings), 3000)
        with self.assertRaisesRegex(ValueError, "reserve"):
            module.require_time(settings, now=1000, closure_at=3999)
        module.require_time(settings, now=1000, closure_at=4000)

    def test_commands_preserve_one_protocol_and_isolate_each_seed_arm(self):
        """Matched arms share settings/source while outputs and namespaces remain unique."""
        module = self.module()
        protocol = {
            "source_root": "/frozen/source",
            "continuum_config": "/inputs/cluster.cfg",
            "inventory": "/inputs/inventory_vms",
            "experiment_config": "/inputs/trial.json",
            "native_image": "demo:native-pinned",
            "template_namespace": "original-app",
            "template_deployment": "batch",
            "run_prefix": "fns-fresh",
            "matrix": [{"seed": 81, "arm": "fixed"}, {"seed": 81, "arm": "forecast"}],
        }
        rows = module.matrix_commands(protocol, Path("/new/evidence"))
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["output"], rows[1]["output"])
        for row in rows:
            command = row["command"]
            self.assertEqual(
                command[command.index("--continuum-config") + 1], "/inputs/cluster.cfg"
            )
            self.assertEqual(command[command.index("--inventory") + 1], "/inputs/inventory_vms")
            self.assertEqual(
                command[command.index("--experiment-config") + 1], "/inputs/trial.json"
            )
            self.assertEqual(command[command.index("--admission-mode") + 1], "fifo")
            self.assertEqual(
                command[command.index("--source-dir") + 1],
                "/frozen/source/application/image_batch/src",
            )
        protocol["matrix"].append(protocol["matrix"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            module.matrix_commands(protocol, Path("/new/evidence"))

    def test_restore_comparison_detects_identity_drift_and_new_active_jobs(self):
        """Matching names alone cannot prove VM/node preservation or cleanup."""
        module = self.module()
        node = {
            "metadata": {"uid": "node-1", "name": "worker"},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }
        baseline = {
            "api": {
                "nodes": [node],
                "deployments": [],
                "services": [],
                "namespaces": [],
                "clusterrolebindings": [],
                "jobs": [],
                "pods": [],
            },
            "network": {"routes": "original"},
            "scheduler": {"manifest": "original"},
            "replay": {"state": "absent", "service": "inactive"},
            "vms": {"worker": {"uuid": "old-vm", "disks": ["disk"], "running": True}},
        }
        current = copy.deepcopy(baseline)
        checks = module.restoration_checks(baseline, current)
        self.assertTrue(all(checks.values()), checks)
        current["api"]["nodes"][0]["metadata"]["uid"] = "replacement"
        current["api"]["jobs"] = [{"status": {"active": 1}}]
        current["vms"]["worker"]["uuid"] = "replacement"
        checks = module.restoration_checks(baseline, current)
        self.assertFalse(checks["nodes_preserved"])
        self.assertFalse(checks["vms_preserved"])
        self.assertFalse(checks["no_active_jobs"])

    def test_cleanup_acceptance_does_not_depend_on_policy_success(self):
        """A restored capture with fallback remains valid evidence of policy failure."""
        module = self.module()
        cleanup = {
            "namespace_removed": True,
            "network_restored": True,
            "original_deployment_preserved": True,
        }
        self.assertTrue(module.cleanup_complete(cleanup))
        cleanup["network_restored"] = False
        self.assertFalse(module.cleanup_complete(cleanup))

    def test_source_freeze_retains_required_sibling_manifests(self):
        """A frozen source must include manifests and Continuum configuration helpers."""
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            frozen = module.freeze_source(Path(directory) / "source")
            self.assertTrue(
                (
                    Path(frozen["source_root"]) / "application/image_batch/manifests/adapter.yaml"
                ).is_file()
            )
            self.assertTrue((Path(frozen["source_root"]) / "infrastructure/network.py").is_file())
            self.assertEqual(len(frozen["archive_sha256"]), 64)
            with self.assertRaises(FileExistsError):
                module.freeze_source(Path(directory) / "source")

    def test_modified_frozen_source_is_rejected(self):
        """A source tree changed after freezing cannot masquerade as the committed revision."""
        module = self.module()
        self.assertTrue(hasattr(module, "verify_frozen_source"))
        with tempfile.TemporaryDirectory() as directory:
            frozen = module.freeze_source(Path(directory) / "source")
            module.verify_frozen_source(Path(frozen["source_root"]))
            source = (
                Path(frozen["source_root"]) / "application/image_batch/src/closed_loop_policy.py"
            )
            source.write_text("changed source\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source"):
                module.verify_frozen_source(Path(frozen["source_root"]))


if __name__ == "__main__":
    unittest.main()
