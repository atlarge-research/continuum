"""Regression tests for QEMU worker and guest SSH policy."""

import os
import shlex
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from infrastructure import ansible
from infrastructure.qemu import qemu


class QemuSshTests(unittest.TestCase):
    """Check the inventories and commands passed to external tools."""

    def test_only_physical_inventory_requires_verified_host_keys(self):
        """Require worker keys while retaining guest bootstrap settings."""
        config = {
            "username": "operator",
            "ssh_key": "/test/guest_key",
            "mode": "endpoint",
            "infrastructure": {
                "base_path": "/test",
                "infra_only": True,
                "cloud_nodes": 0,
                "edge_nodes": 0,
                "endpoint_nodes": 1,
            },
        }
        worker = SimpleNamespace(
            is_local=False,
            name_sanitized="operator_worker",
            ip="worker.example",
            user="operator",
            base_names=["base_endpoint_operator"],
            base_ips=[],
            endpoints=1,
            endpoint_names=["endpoint0_operator"],
            endpoint_ips=["192.0.2.2"],
        )
        with tempfile.TemporaryDirectory() as directory:
            original_directory = Path.cwd()
            os.chdir(directory)
            try:
                Path(".tmp").mkdir()
                ansible.create_inventory_machine(config, [worker])
                ansible.create_inventory_vm(config, [worker])
                physical = Path(".tmp/inventory").read_text(encoding="utf-8").splitlines()
                guests = Path(".tmp/inventory_vms").read_text(encoding="utf-8").splitlines()
            finally:
                os.chdir(original_directory)

        self.assertIn("ansible_host_key_checking=True", physical)
        self.assertIn("ansible_ssh_common_args='-o StrictHostKeyChecking=yes'", physical)
        self.assertIn("ansible_ssh_common_args='-o StrictHostKeyChecking=no'", guests)
        self.assertFalse(any(line.startswith("ansible_host_key_checking=") for line in guests))

    def test_remote_launch_and_teardown_disable_tty(self):
        """Disable PTYs for worker lifecycle commands and execute local commands directly."""
        config = {"username": "operator", "infrastructure": {"base_path": "/test"}}
        local = SimpleNamespace(
            is_local=True,
            cloud_controller_names=["controller"],
            cloud_names=[],
            edge_names=[],
            endpoint_names=[],
            process=Mock(return_value=[(["Domain vm created from fixture"], [])] * 2),
        )
        worker = SimpleNamespace(
            is_local=False,
            name="operator@worker.example",
            cloud_controller_names=[],
            cloud_names=["worker"],
            edge_names=[],
            endpoint_names=[],
        )

        for lifecycle in (qemu.launch_vms, qemu.delete_vms):
            with self.subTest(lifecycle=lifecycle.__name__), patch.object(qemu.time, "sleep"):
                local.process.reset_mock()
                lifecycle(config, [local, worker])
                local.process.assert_called_once()
                local_command, remote_command = local.process.call_args.args[1]
                self.assertEqual(shlex.split(local_command)[0], "virsh")
                self.assertEqual(
                    shlex.split(remote_command)[:3], ["ssh", "-T", "operator@worker.example"]
                )
