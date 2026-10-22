"""Student commands preserve cluster configuration and fail on unusable evidence."""

import copy
import importlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class StudentDemoTests(unittest.TestCase):
    """Exercise local transformations and remote command boundaries without a cluster."""

    def setUp(self):
        """Create a six-worker inventory with paths containing spaces."""
        self.directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "student team"
        self.root.mkdir()
        self.config = self.root / "cluster.cfg"
        self.config.write_text(
            "[infrastructure]\nprovider=qemu\nbase_path="
            + str(self.root)
            + "\ncloud_nodes=7\ncloud_cores=5\ncloud_memory=8\nendpoint_nodes=1\n"
            "network_emulation=False\n"
        )
        inventory = self.root / ".continuum/inventory_vms"
        inventory.parent.mkdir()
        inventory.write_text(
            "[all:vars]\nansible_ssh_private_key_file='/keys/student key'\n"
            "[cloudcontroller]\ncontrol_alice ansible_host=10.12.0.2 ansible_user=control_alice\n"
            "[clouds]\n"
            + "".join(
                f"worker_{index} ansible_host=10.12.0.{index + 3} ansible_user=alice\n"
                for index in range(6)
            )
            + "[endpoints]\nclient_alice ansible_host=10.12.0.9 ansible_user=client_alice\n"
        )

    def module(self):
        """Load the student entrypoint once it exists.

        Returns:
            module: Production helper under test.
        """
        self.assertIsNotNone(importlib.util.find_spec("student_demo"))
        return importlib.import_module("student_demo")

    def test_packing_preserves_scheduler_settings_and_is_idempotent(self):
        """Installing a profile must retain existing flags, probes and unrelated mounts."""
        original = {
            "spec": {
                "containers": [
                    {
                        "name": "kube-scheduler",
                        "command": ["kube-scheduler", "--leader-elect=true", "--config=/old"],
                        "livenessProbe": {"httpGet": {"path": "/healthz", "port": 10259}},
                        "volumeMounts": [{"name": "certs", "mountPath": "/certs"}],
                    }
                ],
                "volumes": [{"name": "certs", "hostPath": {"path": "/certs"}}],
            }
        }
        before = copy.deepcopy(original)
        result = self.module().packing_manifest(original)
        container = result["spec"]["containers"][0]
        self.assertEqual(original, before)
        self.assertEqual(
            container["livenessProbe"], before["spec"]["containers"][0]["livenessProbe"]
        )
        self.assertEqual(
            container["command"],
            ["kube-scheduler", "--leader-elect=true", "--config=/etc/kubernetes/fns-packing.yaml"],
        )
        self.assertEqual(container["volumeMounts"][0], {"name": "certs", "mountPath": "/certs"})
        self.assertEqual(len(result["spec"]["volumes"]), 2)
        self.assertEqual(self.module().packing_manifest(result), result)

    def test_ssh_preserves_arguments_and_inventory_key(self):
        """Spaces and shell punctuation must arrive as literal kubectl arguments."""
        demo = self.module().Demo(self.config)
        with patch("student_demo.subprocess.run") as remote:
            demo.kubectl("get", "pods", "-l", "label=a b; echo surprise")
        command = remote.call_args.args[0]
        self.assertEqual(command[:4], ["ssh", "-i", "/keys/student key", "control_alice@10.12.0.2"])
        self.assertEqual(
            shlex.split(command[4]), ["kubectl", "get", "pods", "-l", "label=a b; echo surprise"]
        )

    def test_capture_preview_uses_configured_cluster_without_creating_output(self):
        """The wrapper must select the built images and preserve scientific overrides."""
        self.module()
        output = self.root / "never created"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "student_demo",
                "--config",
                str(self.config),
                "capture",
                "--preview",
                "--output",
                str(output),
                "--namespace",
                "fns-student-test",
                "--seed",
                "71",
                "--cadence-seconds",
                "30",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "OPENDC_RUNTIME": "fns-demo"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertEqual(settings["controller"], "control_alice@10.12.0.2")
        self.assertEqual(len(settings["workers"]), 6)
        self.assertEqual(settings["native_image"], "continuum/opendc:fns-cf10c06")
        self.assertEqual(settings["endpoint_image"], "continuum/image-batch-endpoint:fns-v1")
        self.assertEqual(settings["seed"], 71)
        self.assertEqual(settings["cadence_seconds"], 30)
        self.assertFalse(output.exists())

    def test_profile_check_rejects_success_without_sufficient_samples(self):
        """A completed Job with fewer than three observations cannot establish readiness."""
        profile = {
            "task": {
                "duration": 5000,
                "cpu_count": 1,
                "cpu_capacity": 2400.0,
                "mem_capacity": 512,
                "fragments": [{"duration": 5000, "cpu_count": 1, "cpu_usage": 1800.0}],
            },
            "source": {
                "image_count": 4,
                "inference_repetitions": 128,
                "resource_sample_count": 2,
                "sampling_quality": "sampled",
            },
        }
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.module().check_profiles(json.dumps(profile))
        profile["source"]["resource_sample_count"] = 3
        self.assertEqual(self.module().check_profiles(json.dumps(profile)), 1)

    def test_readiness_rejects_stalled_observer(self):
        """An old usable profile cannot mask an observer that has stopped publishing state."""
        module = self.module()
        demo = module.Demo(self.config)
        pods = {
            "items": [
                {
                    "status": {
                        "containerStatuses": [
                            {"name": "adapter", "ready": True, "restartCount": 0},
                            {"name": "opendt-observer", "ready": True, "restartCount": 0},
                        ]
                    }
                }
            ]
        }
        profile = {
            "task": {
                "duration": 5000,
                "cpu_count": 1,
                "cpu_capacity": 2400.0,
                "mem_capacity": 512,
                "fragments": [{"duration": 5000, "cpu_count": 1, "cpu_usage": 1800.0}],
            },
            "source": {
                "image_count": 4,
                "inference_repetitions": 128,
                "resource_sample_count": 3,
                "sampling_quality": "sampled",
            },
        }

        def remote(*arguments, **_kwargs):
            """Return a stable state timestamp even though the Pod remains running.

            Args:
                arguments (str): kubectl arguments.
                _kwargs (dict): Unused output options.

            Returns:
                str: Observer JSON or an empty command response.
            """
            if "cat" in arguments:
                return json.dumps(profile)
            if "tail" in arguments:
                return '{"timestamp_unix_ns":1000000000}'
            return ""

        with patch.object(demo, "preflight"), patch.object(
            demo, "get", return_value=pods
        ), patch.object(demo, "kubectl", side_effect=remote), patch("student_demo.time.sleep"):
            with self.assertRaisesRegex(ValueError, "advanc"):
                demo.check()


if __name__ == "__main__":
    unittest.main()
