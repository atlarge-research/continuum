"""Exercise the replay playbook without connecting to a VM."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import yaml

from infrastructure.qemu import qemu


PLAYBOOK = Path(__file__).resolve().parents[1] / "qemu/infrastructure/mahimati.yml"


class ReplayProvisioningTests(unittest.TestCase):
    def test_replay_verification_runs_after_endpoint_launch_even_with_cached_images(
        self,
    ):
        for enabled, preset, installs in (
            (False, "5g_nl_kpn_mahimahi", False),
            (True, "5g", False),
            (True, "5g_nl_kpn_mahimahi", True),
        ):
            events = []

            class Machine:
                def process(self, _config, command):
                    events.append(command)
                    return [(["PLAY RECAP\n"], [])]

            cfg = {
                "infrastructure": {
                    "base_path": "/tmp/continuum-test",
                    "network_emulation": enabled,
                    "wireless_network_preset": preset,
                }
            }
            with self.subTest(enabled=enabled, preset=preset), ExitStack() as stack:
                for module, name in (
                    (qemu.m, "gather_ips"),
                    (qemu.m, "gather_ssh"),
                    (qemu.infrastructure, "create_keypair"),
                    (qemu.ansible, "create_inventory_machine"),
                    (qemu.ansible, "create_inventory_vm"),
                    (qemu.ansible, "copy"),
                    (qemu.generate, "start"),
                    (qemu, "copy"),
                ):
                    stack.enter_context(patch.object(module, name))
                stack.enter_context(
                    patch.object(
                        qemu,
                        "start_vms",
                        side_effect=lambda *_: events.append("launched"),
                    )
                )
                stack.enter_context(
                    patch.object(
                        qemu.infrastructure,
                        "add_ssh",
                        side_effect=lambda *_: events.append("ssh-ready"),
                    )
                )
                qemu.start(cfg, [Machine()])
                self.assertEqual(events[:2], ["launched", "ssh-ready"])
                self.assertEqual(len(events), 3 if installs else 2)
                if installs:
                    self.assertEqual(
                        events[2][-1],
                        "/tmp/continuum-test/.continuum/infrastructure/mahimati.yml",
                    )

    def test_vm_start_has_no_source_acquisition_or_installation_fallback(self):
        play = yaml.safe_load(PLAYBOOK.read_text())[0]
        forbidden = {
            "apt",
            "package",
            "git",
            "unarchive",
            "shell",
            "include_tasks",
            "import_tasks",
        }
        for task in play["tasks"]:
            self.assertFalse(forbidden.intersection(task), task["name"])
            self.assertNotIn("block", task)
        self.assertTrue(any("assert" in task for task in play["tasks"]))

    def test_installer_and_launcher_share_expected_build_identity(self):
        manifest = PLAYBOOK.with_name("mahimahi-build.json")
        self.assertTrue(manifest.is_file())
        expected = json.loads(manifest.read_text())
        spec = importlib.util.spec_from_file_location(
            "replay_identity", PLAYBOOK.with_name("continuum_replay.py")
        )
        replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay)
        self.assertEqual(replay.REVISION, expected["mahimahi_revision"])
        self.assertEqual(replay.PATCH_ID, expected["mahimahi_patch_id"])
        for name in ("mahimati.yml", "base_mahimahi.yml"):
            play = yaml.safe_load(PLAYBOOK.with_name(name).read_text())[0]
            self.assertIn("{{ playbook_dir }}/mahimahi-build.json", play["vars_files"])
            self.assertNotIn("mahimahi_revision", play.get("vars", {}))

    def test_new_bases_install_replay_only_on_endpoint_backing_images(self):
        for infra_only, cached_cloud in ((False, False), (False, True), (True, False)):
            for enabled in (False, True):
                calls = []

                class Machine:
                    name = "local"
                    is_local = True
                    endpoints = 1
                    base_names = (
                        ["base0_test"]
                        if infra_only
                        else ["base_cloud_kubernetes0_test", "base_endpoint0_test"]
                    )
                    base_ips = (
                        ["192.168.211.2"] if infra_only else ["192.168.211.2", "192.168.211.3"]
                    )

                    def process(self, _config, command, **_kwargs):
                        commands = command if isinstance(command[0], list) else [command]
                        results = []
                        for item in commands:
                            calls.append(item)
                            if isinstance(item, list) and item[0] == "find":
                                present = cached_cloud and "base_cloud" in item[-1]
                                results.append(([item[-1]] if present else [], []))
                            elif isinstance(item, list) and item[:2] == ["ls", "-alh"]:
                                results.append((["/etc/localtime -> /usr/share/zoneinfo/UTC"], []))
                            elif isinstance(item, list) and item[:2] == ["sudo", "ln"]:
                                results.append(([], []))
                            else:
                                results.append(
                                    (
                                        ["Domain test created from config and is being shutdown"],
                                        [],
                                    )
                                )
                        return results

                cfg = {
                    "ssh_key": "/tmp/test-key",
                    "benchmark": {"resource_manager_only": True},
                    "infrastructure": {
                        "base_path": "/tmp/continuum-test",
                        "infra_only": infra_only,
                        "network_emulation": enabled,
                        "wireless_network_preset": "5g_nl_kpn_mahimahi",
                    },
                }
                with self.subTest(
                    infra_only=infra_only, enabled=enabled, cached_cloud=cached_cloud
                ), patch.object(qemu.infrastructure, "add_ssh"), patch.object(
                    qemu.ansible, "check_output"
                ), patch.object(
                    qemu.time, "sleep"
                ):
                    qemu.base_image(cfg, [Machine()])
                installs = [
                    c
                    for c in calls
                    if isinstance(c, list) and any(str(v).endswith("base_mahimahi.yml") for v in c)
                ]
                self.assertEqual(len(installs), int(enabled))
                if enabled:
                    command = installs[0]
                    self.assertEqual(
                        command[command.index("--limit") + 1],
                        "base0_test" if infra_only else "base_endpoint0_test",
                    )
                netperf = next(
                    c
                    for c in calls
                    if isinstance(c, list) and any(str(v).endswith("netperf.yml") for v in c)
                )
                expected_bases = [
                    name
                    for name in Machine.base_names
                    if not (cached_cloud and "base_cloud" in name)
                ]
                self.assertEqual(netperf[netperf.index("--limit") + 1], ",".join(expected_bases))

    @unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
    def test_playbook_targets_live_endpoints_not_cached_base_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = root / "inventory"
            inventory.write_text("[endpoints]\nendpoint-under-test\n[base]\nbase-not-running\n")
            result = subprocess.run(
                [
                    "ansible-playbook",
                    "-i",
                    str(inventory),
                    str(PLAYBOOK),
                    "--list-hosts",
                ],
                env=dict(os.environ, ANSIBLE_LOCAL_TEMP=str(root / "ansible")),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("endpoint-under-test", result.stdout)
            self.assertNotIn("base-not-running", result.stdout)
