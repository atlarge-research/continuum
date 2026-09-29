"""Offline tuning preserves unsuccessful native attempts and bounded execution."""

import importlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class TuningTests(unittest.TestCase):
    """A failed native process must leave its command, output and outcome reviewable."""

    def test_native_failure_preserves_command_and_both_output_streams(self):
        """A nonzero native exit is evidence, never a silently retried candidate."""
        self.assertIsNotNone(importlib.util.find_spec("demo_tuning"))
        module = importlib.import_module("demo_tuning")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite, output = root / "suite", root / "native"
            suite.mkdir()
            failure = subprocess.CompletedProcess([], 7, b"partial output", b"native failure")
            with patch.object(module.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "native"):
                    module.execute_native(
                        suite,
                        output,
                        "frozen:test",
                        scenarios=3,
                        timeout_seconds=45,
                        allocation_seconds=180,
                    )
            self.assertEqual((output / "stdout.txt").read_bytes(), b"partial output")
            self.assertEqual((output / "stderr.txt").read_bytes(), b"native failure")
            self.assertTrue((output / "command.json").is_file())
            self.assertTrue((output / "container.json").is_file())
            with self.assertRaises(FileExistsError):
                module.execute_native(
                    suite,
                    output,
                    "frozen:test",
                    scenarios=3,
                    timeout_seconds=45,
                    allocation_seconds=180,
                )
