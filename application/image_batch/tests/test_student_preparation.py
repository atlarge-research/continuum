"""Preparation uses rebuilt images and preserves the original scheduler configuration."""

import copy
import json
import shlex
import subprocess
import unittest
from unittest.mock import patch

import yaml

import student_demo
import test_student_demo


class StudentPreparationTests(unittest.TestCase):
    """Run the real student helper with only its subprocess boundary replaced."""

    def setUp(self):
        """Reuse the six-worker configuration and prepare fake remote JSON responses."""
        fixture = test_student_demo.StudentDemoTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.demo = student_demo.Demo(fixture.config)
        ansible = self.demo.root / "provision/bin/ansible"
        ansible.parent.mkdir(parents=True)
        ansible.touch()
        settings = self.demo.settings
        self.nodes = {
            "items": [
                {
                    "metadata": {"name": host["name"].replace("_", ""), "uid": host["name"]},
                    "spec": {
                        "taints": [
                            {
                                "key": "node-role.kubernetes.io/control-plane",
                                "effect": "NoSchedule",
                            }
                        ]
                        if host["name"].replace("_", "") == settings["control_node"]
                        else []
                    },
                    "status": {
                        "addresses": [{"type": "InternalIP", "address": host["ansible_host"]}],
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
                for host in settings["inventory_hosts"]
                if host["name"].replace("_", "") in settings["workers"] + [settings["control_node"]]
            ]
        }
        self.jobs = {"items": []}
        self.scheduler = {
            "spec": {
                "containers": [
                    {
                        "name": "kube-scheduler",
                        "command": ["kube-scheduler", "--leader-elect=true"],
                        "livenessProbe": {"httpGet": {"path": "/healthz", "port": 10259}},
                        "volumeMounts": [{"name": "certs", "mountPath": "/certs"}],
                    }
                ],
                "volumes": [{"name": "certs", "hostPath": {"path": "/certs"}}],
            }
        }
        self.remote_backup = None
        self.replacement = None
        self.scheduler_responses = []
        self.operations = []

    def remote(self, command, **options):
        """Supply cluster reads and retain scheduler file writes at the process boundary.

        Args:
            command (list[str]): Actual local subprocess arguments.
            **options (dict): Subprocess options including manifest standard input.

        Returns:
            subprocess.CompletedProcess: Successful command output for the fake cluster.
        """
        arguments = shlex.split(command[-1]) if command[0] == "ssh" else command
        self.operations.append((arguments, options.get("input")))
        output = ""
        if arguments[:3] == ["kubectl", "get", "nodes"]:
            output = json.dumps(self.nodes)
        elif arguments[:3] == ["kubectl", "get", "jobs"]:
            output = json.dumps(self.jobs)
        elif arguments[:4] == ["kubectl", "get", "deployment", "metrics-server"]:
            output = json.dumps({"spec": {"template": {"spec": {"containers": [{"args": []}]}}}})
        elif arguments[:3] == ["kubectl", "get", "pods"] and "kube-system" in arguments:
            pod = copy.deepcopy(self.scheduler)
            pod["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
            output = json.dumps(
                self.scheduler_responses.pop(0) if self.scheduler_responses else {"items": [pod]}
            )
        elif arguments[:2] == ["sudo", "cat"]:
            original = self.remote_backup if "before-student" in arguments[-1] else self.scheduler
            output = yaml.safe_dump(original)
        elif arguments[:3] == ["sudo", "cp", "-n"]:
            if self.remote_backup is None:
                self.remote_backup = copy.deepcopy(self.scheduler)
        elif arguments[:2] == ["sudo", "tee"] and arguments[-1].endswith(".next.yaml"):
            self.replacement = yaml.safe_load(options["input"])
        elif arguments[:3] == ["sudo", "sh", "-c"]:
            if "cp -n " in arguments[-1] and self.remote_backup is None:
                self.remote_backup = copy.deepcopy(self.scheduler)
            self.scheduler = self.replacement
        elif arguments[:2] == ["sudo", "mv"]:
            self.scheduler = self.replacement
        return subprocess.CompletedProcess(command, 0, stdout=output)

    def test_prepare_restarts_service_after_rebuilding_and_importing_images(self):
        """A repeated mutable image tag must still roll every service container."""
        rounds = []
        with patch("student_demo.subprocess.run", side_effect=self.remote):
            for _ in range(2):
                self.operations = []
                self.demo.prepare()
                rounds.append(self.operations)
        for operations in rounds:
            commands = [arguments for arguments, _ in operations]
            restarts = [
                index
                for index, arguments in enumerate(commands)
                if "rollout" in arguments and "restart" in arguments
            ]
            self.assertEqual(
                len(restarts), 1, "prepare must restart the rebuilt adapter/observer Pod"
            )
            restart = restarts[0]
            self.assertIn("deployment/image-batch-adapter", commands[restart])
            builds = [
                index
                for index, arguments in enumerate(commands)
                if arguments[:2] == ["docker", "build"]
            ]
            imports = [
                index
                for index, arguments in enumerate(commands)
                if any("ctr -n k8s.io images import" in value for value in arguments)
            ]
            applies = [
                index
                for index, (arguments, data) in enumerate(operations)
                if arguments[:2] == ["kubectl", "apply"] and data and "kind: Deployment" in data
            ]
            self.assertEqual(len(builds), 4)
            self.assertTrue(imports)
            self.assertTrue(applies)
            self.assertGreater(restart, max(builds + imports + applies))
            self.assertTrue(
                any(
                    "rollout" in arguments
                    and "status" in arguments
                    and "deployment/image-batch-adapter" in arguments
                    for arguments in commands[restart + 1 :]
                )
            )

    def test_scheduler_backup_survives_repeat_install_and_refreshes_after_rebuild(self):
        """Rollback evidence must follow the guest's preserved original manifest."""
        self.demo.setup.mkdir()
        original = copy.deepcopy(self.scheduler)
        backup = self.demo.setup / "kube-scheduler.original.yaml"
        with patch("student_demo.subprocess.run", side_effect=self.remote):
            self.demo.install_packing()
            self.assertEqual(self.remote_backup, original)
            self.assertEqual(yaml.safe_load(backup.read_text(encoding="utf-8")), original)
            self.scheduler["spec"]["containers"][0]["command"].append("--v=2")
            self.demo.install_packing()
            self.assertEqual(self.remote_backup, original)
            self.assertEqual(yaml.safe_load(backup.read_text(encoding="utf-8")), original)
            rebuilt = copy.deepcopy(original)
            rebuilt["spec"]["containers"][0]["command"].append("--bind-address=127.0.0.1")
            self.scheduler = rebuilt
            self.remote_backup = None
            self.demo.install_packing()
        self.assertEqual(self.remote_backup, rebuilt)
        self.assertEqual(yaml.safe_load(backup.read_text(encoding="utf-8")), rebuilt)

    def test_scheduler_waits_for_ready_pod_using_packing_and_preserves_probes(self):
        """An old Ready mirror Pod does not establish that the new profile is active."""
        self.demo.setup.mkdir()
        original = copy.deepcopy(self.scheduler)
        old_ready = copy.deepcopy(original)
        old_ready["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
        self.scheduler_responses = [{"items": [old_ready]}]
        with patch("student_demo.subprocess.run", side_effect=self.remote), patch(
            "student_demo.time.sleep"
        ) as sleep:
            self.demo.install_packing()
        sleep.assert_called_once()
        container = self.scheduler["spec"]["containers"][0]
        previous = original["spec"]["containers"][0]
        self.assertEqual(container["livenessProbe"], previous["livenessProbe"])
        self.assertEqual(container["volumeMounts"][0], previous["volumeMounts"][0])
        self.assertEqual(self.scheduler["spec"]["volumes"][0], original["spec"]["volumes"][0])
        self.assertIn(f"--config={student_demo.PACKING_PATH}", container["command"])
        self.assertIn(
            {
                "name": "fns-packing-config",
                "mountPath": student_demo.PACKING_PATH,
                "readOnly": True,
            },
            container["volumeMounts"],
        )

    def test_preflight_refuses_unusable_cluster_before_any_write(self):
        """Active Jobs and inconsistent live nodes stop prepare and check at read-only preflight."""
        healthy = copy.deepcopy(self.nodes)
        for problem in ("active-job", "unready-node", "mismatched-address", "missing-node"):
            for action in (self.demo.prepare, self.demo.check):
                with self.subTest(problem=problem, action=action.__name__):
                    self.nodes = copy.deepcopy(healthy)
                    self.jobs = {"items": []}
                    self.operations = []
                    if problem == "active-job":
                        self.jobs = {"items": [{"status": {"active": 1}}]}
                    elif problem == "unready-node":
                        self.nodes["items"][1]["status"]["conditions"][0]["status"] = "False"
                    elif problem == "mismatched-address":
                        self.nodes["items"][1]["status"]["addresses"][0]["address"] = "10.90.0.1"
                    else:
                        self.nodes["items"].pop()
                    with patch("student_demo.subprocess.run", side_effect=self.remote):
                        with self.assertRaises(ValueError):
                            action()
                    self.assertTrue(self.operations)
                    self.assertTrue(
                        all(
                            arguments[:2] == ["kubectl", "get"]
                            and arguments[2] in {"nodes", "jobs"}
                            and data is None
                            for arguments, data in self.operations
                        ),
                        self.operations,
                    )
                    self.assertFalse(self.demo.setup.exists())


if __name__ == "__main__":
    unittest.main()
