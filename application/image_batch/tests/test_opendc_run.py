"""A process exit alone must never produce a successful execution manifest."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import prepare
from opendc_run import execute


class RunTests(unittest.TestCase):
    """Exercise execution manifests with a small shell stand-in for the OpenDC CLI."""

    def test_invocation_resolves_native_sdk_inputs_and_disables_interactive_output(self):
        """Check copied input paths and the noninteractive single-experiment SDK command."""
        with tempfile.TemporaryDirectory() as root:
            status, manifest, output = self._run(root, "exit 0")
            command = manifest["process"]["command"]
            self.assertEqual(command[1:], ["--strict", "run", str(output / "experiment.json"),
                                          "--output", str(output / "simulator"), "--parallelism", "1",
                                          "--no-progress", "--no-summary"])
            config = json.loads((output / "experiment.json").read_text())
            self.assertEqual(config["topologies"], [{"importFrom": str(output / "inputs/topology.json")}])
            self.assertEqual(config["workloads"][0]["source"],
                             {"type": "uri", "uri": (output / "inputs/trace").as_uri()})
            self.assertEqual(config["exportModels"][0]["exportInterval"], "1 s")
            self.assertEqual(status, 1)  # Exit zero without native tables remains a failure.

    def _run(self, root, body, timeout=5):
        """Execute a prepared memory fixture through a temporary shell runner.

        Return the runner status, finalized manifest and output path. The shell
        body controls process behavior without requiring an OpenDC installation.

        Args:
            root (str or Path): Temporary root for inputs, the shell runner and results.
            body (str): Shell statements controlling the stand-in runner.
            timeout (float): Process deadline passed to execute, in seconds.

        Returns:
            tuple[int, dict, Path]: Runner exit code, finalized execution manifest and output
        directory.
        """
        root = Path(root)
        source = root / "inputs"
        prepare("memory", source)
        runner = root / "runner"
        runner.write_text("#!/bin/sh\n" + body + "\n")
        runner.chmod(0o755)
        output = root / "result"
        status = execute(source, output, timeout, str(runner))
        manifest = json.loads((output / "execution.json").read_text())
        return status, manifest, output

    def test_success_exit_with_missing_outputs_fails_validation(self):
        """Require native simulator output even when the process itself exits zero."""
        with tempfile.TemporaryDirectory() as root:
            status, manifest, output = self._run(root, "exit 0")
            self.assertEqual(status, 1)
            self.assertEqual(manifest["process"]["exit_code"], 0)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["validation"]["status"], "failed")
            self.assertTrue((output / "inputs/source/tasks.parquet").is_file())

    def test_failed_process_retains_status_and_never_validates(self):
        """Preserve the child exit and stderr while leaving output validation unrun."""
        with tempfile.TemporaryDirectory() as root:
            status, manifest, output = self._run(root, "echo diagnostic >&2; exit 9")
            self.assertEqual(status, 1)
            self.assertEqual(manifest["process"]["exit_code"], 9)
            self.assertEqual(manifest["validation"]["status"], "not_run")
            self.assertIn("diagnostic", (output / "stderr.log").read_text())

    def test_timeout_is_distinct_from_nonzero_exit(self):
        """Represent a process deadline with status timed_out and runner exit 124."""
        with tempfile.TemporaryDirectory() as root:
            status, manifest, _ = self._run(root, "sleep 20", timeout=0.1)
            self.assertEqual(status, 124)
            self.assertEqual(manifest["status"], "timed_out")
            self.assertTrue(manifest["process"]["timed_out"])

    def test_changed_input_creates_failure_evidence_without_launch(self):
        """Finalize invalid-input evidence before any simulator process can be launched."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            prepare("memory", root / "inputs")
            (root / "inputs/trace/tasks.parquet").write_bytes(b"invalid")
            status = execute(root / "inputs", root / "result", 5)
            manifest = json.loads((root / "result/execution.json").read_text())
            self.assertEqual(status, 2)
            self.assertEqual(manifest["status"], "invalid_input")
            self.assertIsNone(manifest["process"])

    def test_existing_output_directory_is_never_reused(self):
        """Refuse an existing results directory even when it is empty."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            prepare("memory", root / "inputs")
            (root / "result").mkdir()
            with self.assertRaises(FileExistsError):
                execute(root / "inputs", root / "result", 5)
