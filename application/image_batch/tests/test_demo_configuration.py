"""Deployment resolution uses Continuum evidence rather than machine-specific defaults."""

import importlib
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DeploymentTests(unittest.TestCase):
    """Exercise alternate inventory identities without contacting a deployment."""

    def setUp(self):
        """Create a complete alternate Continuum deployment fixture."""
        # unittest cleanup owns this fixture across setUp and each test method.
        self.directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "demo.cfg"
        self.config.write_text(
            "[infrastructure]\nprovider=qemu\nbase_path="
            + str(self.root)
            + "\ncloud_nodes=3\ncloud_cores=8\ncloud_memory=12\nendpoint_nodes=1\n"
            "network_emulation=True\nwireless_network_preset=lte_nl_kpn_mahimahi\n"
        )
        self.inventory = self.root / ".continuum/inventory_vms"
        self.inventory.parent.mkdir()
        self.inventory.write_text(
            "[all:vars]\nansible_ssh_private_key_file='/keys/other key'\n"
            "[cloudcontroller]\ncontrol_alice ansible_host=10.12.0.2 ansible_user=control_alice\n"
            "[clouds]\nworker_a ansible_host=10.12.0.3 ansible_user=alice_a\n"
            "worker_b ansible_host=10.12.0.4 ansible_user=alice_b\n"
            "[endpoints]\nclient_alice ansible_host=10.12.0.5 ansible_user=client_alice\n"
        )

    def module(self):
        """Load the production deployment resolver.

        Returns:
            module: Configuration implementation under test.
        """
        self.assertIsNotNone(importlib.util.find_spec("demo_configuration"))
        return importlib.import_module("demo_configuration")

    def test_inventory_controls_identity_resources_and_replay(self):
        """Personal addresses, key paths and presets cannot leak into another deployment."""
        result = self.module().resolve_deployment(self.config)
        self.assertEqual(result["controller"], "control_alice@10.12.0.2")
        self.assertEqual(result["endpoint"], "client_alice@10.12.0.5")
        self.assertEqual(result["ssh_key"], "/keys/other key")
        self.assertEqual(result["workers"], ["workera", "workerb"])
        self.assertEqual(result["control_node"], "controlalice")
        self.assertEqual(result["worker_cores"], 8)
        self.assertEqual(result["worker_memory_mib"], 12288)
        self.assertEqual(result["adapter_address"], "10.12.0.3")
        self.assertEqual(
            result["replay_command"][-6:],
            [
                "10.12.0.5",
                "/home/mahimahi/traces/KPN_4G.up",
                "/home/mahimahi/traces/KPN_4G.down",
                "10.12.0.2",
                "10.12.0.3",
                "10.12.0.4",
            ],
        )

    def test_mismatched_or_ambiguous_inventory_is_rejected(self):
        """A stale inventory cannot silently select a different cluster size."""
        module = self.module()
        self.config.write_text(self.config.read_text().replace("cloud_nodes=3", "cloud_nodes=4"))
        with self.assertRaisesRegex(ValueError, "inventory"):
            module.resolve_deployment(self.config)

    def test_disabled_replay_has_no_start_command(self):
        """Wired or disabled emulation does not start a cellular trace accidentally."""
        self.config.write_text(
            self.config.read_text().replace("network_emulation=True", "network_emulation=False")
        )
        self.assertEqual(self.module().resolve_deployment(self.config)["replay_command"], [])

    def test_live_inventory_mismatch_fails_before_mutation(self):
        """Matching node names alone cannot authorize operations on another address pool."""
        module = self.module()
        settings = module.resolve_deployment(self.config)
        nodes = {
            "items": [
                {
                    "metadata": {"name": name, "uid": name + "-uid"},
                    "status": {
                        "addresses": [{"type": "InternalIP", "address": address}],
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
                for name, address in [
                    ("controlalice", "10.12.0.2"),
                    ("workera", "10.12.0.3"),
                    ("workerb", "10.12.0.4"),
                ]
            ]
        }
        self.assertTrue(hasattr(module, "validate_live_inventory"))
        module.validate_live_inventory(nodes, settings)
        nodes["items"][1]["status"]["addresses"][0]["address"] = "10.99.0.3"
        with self.assertRaisesRegex(ValueError, "address"):
            module.validate_live_inventory(nodes, settings)

    def test_preview_resolves_settings_without_creating_capture(self):
        """The supported CLI exposes all effective settings without remote mutation."""
        output = self.root / "never-created"
        settings = self.root / "trial.json"
        settings.write_text(
            json.dumps({"cadence_seconds": 90, "horizon_seconds": 240, "scenarios": 5})
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "capture_run",
                "--continuum-config",
                str(self.config),
                "--experiment-config",
                str(settings),
                "--preview",
                "--output",
                str(output),
                "--namespace",
                "fns-preview",
                "--seed",
                "71",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["controller"], "control_alice@10.12.0.2")
        self.assertEqual(values["cadence_seconds"], 90)
        self.assertEqual(values["horizon_seconds"], 240)
        self.assertEqual(values["scenarios"], 5)
        self.assertFalse(output.exists())

    def test_native_placement_requires_explicit_control_plane_role(self):
        """A historic personal node name must not implicitly grant a control-plane toleration."""
        module = importlib.import_module("opendc_kubernetes")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = module.main(
                [
                    "manifest",
                    "--namespace",
                    "fns-test",
                    "--job",
                    "native",
                    "--remote-dir",
                    "/var/tmp/fns-opendc-test",
                    "--image",
                    "test:pinned",
                    "--node",
                    "cloudcontrollermatthijs",
                ]
            )
        self.assertEqual(code, 0)
        spec = json.loads(output.getvalue())["spec"]["template"]["spec"]
        self.assertFalse(spec.get("tolerations"))


if __name__ == "__main__":
    unittest.main()
