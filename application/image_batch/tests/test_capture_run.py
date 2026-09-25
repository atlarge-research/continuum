"""Capture preparation preserves live configuration and immutable run evidence."""

import copy
import importlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class CaptureTests(unittest.TestCase):
    """Exercise real manifests and output directories without a cluster."""

    def module(self):
        """Load the implementation, reporting the missing feature as an assertion.

        Returns:
            module: Capture implementation under test.
        """
        self.assertIsNotNone(importlib.util.find_spec("capture_run"), "capture module is missing")
        return importlib.import_module("capture_run")

    def test_prepare_preserves_image_and_source_without_mutating_live_deployment(self):
        """Changing namespace must not change the calibrated worker or original spec."""
        module = self.module()
        original = {
            "spec": {
                "replicas": 1,
                "template": {
                    "metadata": {"annotations": {"restartedAt": "old"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "adapter",
                                "image": "adapter:calibrated",
                                "env": [
                                    {"name": "WORKER_IMAGE", "value": "worker:calibrated"},
                                    {"name": "JOB_NAMESPACE", "value": "fns-demo"},
                                    {"name": "WORKER_SCHEDULER_NAME", "value": "old"},
                                ],
                            },
                            {"name": "opendt-observer", "image": "adapter:calibrated"},
                            {"name": "forecast", "image": "forecast:old"},
                        ],
                        "volumes": [],
                    },
                },
            }
        }
        before = copy.deepcopy(original)
        manifests = module.capture_manifests(original, "fns-test-new", {"adapter.py": "source"})
        deployment = next(item for item in manifests if item["kind"] == "Deployment")
        containers = deployment["spec"]["template"]["spec"]["containers"]
        self.assertEqual([item["name"] for item in containers], ["adapter", "opendt-observer"])
        env = {item["name"]: item["value"] for item in containers[0]["env"]}
        self.assertEqual(env["WORKER_IMAGE"], "worker:calibrated")
        self.assertEqual(env["JOB_NAMESPACE"], "fns-test-new")
        self.assertEqual(env["WORKER_SCHEDULER_NAME"], "fns-packing")
        self.assertEqual(len(env), len(containers[0]["env"]))
        self.assertEqual(original, before)
        self.assertEqual(containers[0]["command"], ["python", "-u", "/review/adapter.py"])
        service = next(item for item in manifests if item["kind"] == "Service")
        self.assertNotIn("nodePort", service["spec"]["ports"][0])
        binding = next(item for item in manifests if item["kind"] == "ClusterRoleBinding")
        self.assertEqual(binding["metadata"]["name"], "fns-test-new")
        self.assertEqual(binding["subjects"][0]["namespace"], "fns-test-new")

    def test_existing_output_is_never_reused(self):
        """A rerun must not overwrite invocation or historical capture files."""
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            module.prepare_output(output, {"seed": 52})
            with self.assertRaises(FileExistsError):
                module.prepare_output(output, {"seed": 53})
            self.assertEqual(json.loads((output / "invocation.json").read_text()), {"seed": 52})

    def test_prefix_archive_never_includes_newly_appended_bytes(self):
        """Archival records a fixed evidence boundary while the observer grows."""
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream.jsonl"
            path.write_bytes(b'{"first":1}\n')
            result = subprocess.run(
                [sys.executable, "-c", module.FREEZE_SCRIPT, directory],
                check=True,
                capture_output=True,
            )
            path.write_bytes(path.read_bytes() + b'{"later":2}\n')
            with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
                self.assertEqual(archive.extractfile("stream.jsonl").read(), b'{"first":1}\n')

    def test_unsafe_namespace_is_rejected_before_manifest_generation(self):
        """Namespace input cannot identify or overwrite the original deployment."""
        module = self.module()
        for namespace in ["fns-demo", "kube-system", "../old", ""]:
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                module.capture_manifests({}, namespace, {})

    def test_failed_cli_does_not_replace_existing_failure_evidence(self):
        """Collision rejection must not write a new failure record into the old run."""
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "failure.json"
            marker.write_text("original failure\n")
            result = subprocess.run(
                [
                    sys.executable,
                    module.__file__,
                    "--output",
                    directory,
                    "--namespace",
                    "fns-collision-test",
                    "--seed",
                    "52",
                ],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), "original failure\n")


if __name__ == "__main__":
    unittest.main()
