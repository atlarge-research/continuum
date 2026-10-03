"""Study orchestration preserves matched inputs, time reserves and restoration evidence."""

import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from demo_configuration import EXPERIMENT_DEFAULTS


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
        self.assertEqual(module.capture_budget_seconds(settings), 3000)
        self.assertEqual(module.run_budget_seconds(settings), 3890)
        with self.assertRaisesRegex(ValueError, "reserve"):
            module.require_time(settings, now=1000, closure_at=4889)
        module.require_time(settings, now=1000, closure_at=4890)
        with self.assertRaisesRegex(ValueError, "reserve"):
            module.require_time(
                settings, now=1000, closure_at=12799, runs=3, initial_verification=True
            )
        module.require_time(settings, now=1000, closure_at=12800, runs=3, initial_verification=True)

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

    def test_sealed_worker_bounds_start_all_arms_at_normal_allocation(self):
        """The sealed matrix must preserve initial four workers and dynamic two-to-six bounds."""
        module = self.module()
        protocol = dict(
            source_root="/frozen",
            continuum_config="/cluster.cfg",
            inventory="/inventory",
            experiment_config="/settings.json",
            native_image="native:pinned",
            run_prefix="bounds",
            matrix=[dict(seed=1, arm=arm) for arm in ("fixed", "reactive", "forecast")],
            worker_bounds={"active_workers": 4, "minimum_workers": 2, "maximum_workers": 6},
        )
        for row in module.matrix_commands(protocol, Path("/new/evidence")):
            for flag, value in (
                ("--active-workers", "4"),
                ("--minimum-workers", "2"),
                ("--maximum-workers", "6"),
            ):
                self.assertEqual(row["command"][row["command"].index(flag) + 1], value)
        for invalid in (
            {"active_workers": True, "minimum_workers": 2, "maximum_workers": 6},
            {"active_workers": 1, "minimum_workers": 2, "maximum_workers": 6},
            {"active_workers": 4, "minimum_workers": 2},
            {"active_workers": 4, "minimum_workers": 2, "maximum_workers": 6, "unknown": 1},
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "worker bounds"):
                protocol["worker_bounds"] = invalid
                module.matrix_commands(protocol, Path("/new/evidence"))

    def test_sealed_arm_cadences_are_explicit_and_strictly_validated(self):
        """Reactive can check more often while sharing the frozen workload and deployment."""
        module = self.module()
        protocol = dict(
            source_root="/frozen",
            continuum_config="/cluster.cfg",
            inventory="/inventory",
            experiment_config="/settings.json",
            native_image="native:pinned",
            run_prefix="cadence",
            matrix=[dict(seed=1, arm=arm) for arm in ("fixed", "reactive", "forecast")],
            arm_cadence_seconds={"reactive": 30},
        )
        rows = module.matrix_commands(protocol, Path("/new/evidence"))
        self.assertNotIn("--cadence-seconds", rows[0]["command"])
        self.assertNotIn("--cadence-seconds", rows[2]["command"])
        command = rows[1]["command"]
        self.assertEqual(command[command.index("--cadence-seconds") + 1], "30")
        for invalid in (
            {"unknown": 30},
            {"reactive": 0},
            {"reactive": True},
            {"reactive": 1.5},
            {"reactive": "30"},
        ):
            with self.subTest(invalid=invalid):
                protocol["arm_cadence_seconds"] = invalid
                with self.assertRaisesRegex(ValueError, "cadence"):
                    module.matrix_commands(protocol, Path("/new/evidence"))

    def test_matrix_timeout_records_recovery_and_never_launches_next_capture(self):
        """All phases are bounded; a capture timeout stops even after sender recovery."""
        module = self.module()
        for stopped in (True, False):
            with self.subTest(group_stopped=stopped), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                settings = root / "settings.json"
                settings.write_text(json.dumps(EXPERIMENT_DEFAULTS))
                protocol = {
                    "source_root": str(root),
                    "experiment_config": str(settings),
                    "closure_at_seconds": 100000,
                    "require_complete_budget": True,
                    "role": "heldout",
                }
                protocol_path = root / "protocol.json"
                protocol_path.write_text(json.dumps(protocol))
                rows = [
                    {
                        "seed": 1,
                        "arm": arm,
                        "output": str(root / "evaluation/experiments" / arm),
                        "command": ["capture", arm],
                    }
                    for arm in ("fixed", "forecast")
                ]
                with patch.object(module.time, "time", return_value=1000), patch.object(
                    module, "matrix_commands", return_value=rows
                ), patch.object(
                    module, "workflow_phase", return_value=protocol
                ) as phase, patch.object(
                    module,
                    "run_phase",
                    side_effect=module.PhaseFailure("timed out", group_stopped=stopped),
                ) as capture:
                    with self.assertRaises(module.PhaseFailure):
                        module.run_matrix(protocol_path, root / "evaluation")
                capture.assert_called_once()
                self.assertEqual(capture.call_args.args[0], ["capture", "fixed"])
                self.assertEqual(capture.call_args.kwargs["timeout_seconds"], 3480)
                kinds = [call.args[0] for call in phase.call_args_list]
                self.assertEqual(kinds, ["verify", "verify"] + (["recovery"] if stopped else []))
                failure = json.loads(
                    (root / "evaluation/experiments/fixed.matrix-failure.json").read_text()
                )
                self.assertTrue(failure["requires_reconciliation"])
                self.assertFalse(failure["may_continue"])

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

    def test_collected_metrics_are_direct_report_inputs(self):
        """Tracked collection emits the report schema rather than an unrecognized bare run."""
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture"
            with patch.object(
                module, "capture_evidence", return_value={"run_id": "capture"}
            ), patch.object(module, "audit_capture", return_value={"violations": False}):
                paths = module.collect_metrics(capture, "pilot")
            saved = json.loads(Path(paths["metrics"]).read_text(encoding="utf-8"))
            self.assertEqual(saved.get("schema_version"), "opendc-closed-loop-evidence-v1")
            self.assertEqual(saved["runs"], [{"run_id": "capture"}])

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

    def test_protocol_freeze_rejects_changed_settings_and_image_identity(self):
        """A frozen matrix cannot silently execute modified inputs or a retagged image."""
        module = self.module()
        self.assertTrue(hasattr(module, "seal_protocol"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = module.freeze_source(root / "source")
            for name in ("continuum.cfg", "inventory.ini"):
                (root / name).write_text("preserved input")
            (root / "settings.json").write_text(json.dumps(EXPERIMENT_DEFAULTS))
            protocol = dict(
                source_root=frozen["source_root"],
                continuum_config=str(root / "continuum.cfg"),
                inventory=str(root / "inventory.ini"),
                experiment_config=str(root / "settings.json"),
                native_image="exact:tag",
                matrix=[dict(seed=107, arm="forecast")],
                run_prefix="fns-sealed",
                role="heldout",
                closure_at_seconds=9999999999,
            )
            source = root / "draft.json"
            source.write_text(json.dumps(protocol))
            with patch.object(
                module.subprocess, "check_output", return_value="sha256:original"
            ), patch.object(
                module,
                "deployment_identity",
                return_value={"worker": "sha256:worker-original"},
                create=True,
            ):
                sealed = module.seal_protocol(source, root / "protocol")
                with patch.object(module, "resolve_deployment", return_value={}), patch.object(
                    module, "clock_alignment", return_value={}
                ) as clocks:
                    module.verify_protocol(sealed)
                clocks.assert_called_once_with({})
            with patch.object(
                module.subprocess, "check_output", return_value="sha256:original"
            ), patch.object(
                module,
                "deployment_identity",
                return_value={"worker": "sha256:worker-changed"},
                create=True,
            ):
                with self.assertRaisesRegex(ValueError, "deployment"):
                    module.verify_protocol(sealed)
            with patch.object(module.subprocess, "check_output", return_value="sha256:changed"):
                with self.assertRaisesRegex(ValueError, "image"):
                    module.verify_protocol(sealed)
            settings = root / "protocol/experiment.json"
            settings.write_text("changed settings")
            with self.assertRaisesRegex(ValueError, "input"):
                module.verify_protocol(sealed)

    def test_runtime_image_identity_uses_resolved_hosts_and_template_images(self):
        """Every physical image is read from its actual runtime, using configured identities."""
        module = self.module()
        deployment = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "adapter",
                                "image": "custom:adapter",
                                "env": [{"name": "WORKER_IMAGE", "value": "custom:worker"}],
                            },
                            {"name": "opendt-observer", "image": "custom:adapter"},
                            {"name": "forecast", "image": "unused:forecast"},
                        ]
                    }
                }
            }
        }
        settings = {
            "controller": "alice@control",
            "endpoint": "alice@endpoint",
            "ssh_key": "/key",
            "workers": ["workera"],
            "inventory_hosts": [
                {"name": "worker_a", "ansible_user": "alice", "ansible_host": "worker-ip"}
            ],
        }

        def remote(host, key, command):
            self.assertEqual(key, "/key")
            if command[0] == "kubectl":
                self.assertEqual(host, "alice@control")
                return json.dumps(deployment).encode()
            if "crictl" in command:
                self.assertEqual(host, "alice@worker-ip")
                return json.dumps({"status": {"id": "digest:" + command[-1]}}).encode()
            self.assertEqual(host, "alice@endpoint")
            self.assertIn("custom:endpoint", command)
            return b"sha256:endpoint\n"

        with patch.object(module, "resolve_deployment", return_value=settings), patch.object(
            module, "ssh", side_effect=remote
        ):
            identity = module.deployment_identity(
                {"continuum_config": "cfg", "inventory": "ini", "endpoint_image": "custom:endpoint"}
            )
        self.assertEqual(
            set(identity["worker_images"]["workera"]), {"custom:adapter", "custom:worker"}
        )
        self.assertEqual(identity["endpoint_image_id"], "sha256:endpoint")
        self.assertEqual(len(identity["deployment_spec_sha256"]), 64)

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
