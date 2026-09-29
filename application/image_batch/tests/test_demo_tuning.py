"""Offline tuning preserves unsuccessful native attempts and bounded execution."""

import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class TuningTests(unittest.TestCase):
    """A failed native process must leave its command, output and outcome reviewable."""

    def test_outer_timeout_removes_only_its_named_container(self):
        """Killing the Docker client must not leave the owned native computation running."""
        module = importlib.import_module("demo_tuning")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite, output = root / "suite", root / "native"
            suite.mkdir()
            timeout = subprocess.TimeoutExpired(
                ["docker", "run"], 105, output=b"partial output", stderr=b"timeout detail"
            )
            replies = [
                timeout,
                subprocess.CompletedProcess([], 0, b"removed", b""),
                subprocess.CompletedProcess([], 0, b"", b""),
            ]
            with patch.object(module.subprocess, "run", side_effect=replies) as runner:
                with self.assertRaises(subprocess.TimeoutExpired):
                    module.execute_native(
                        suite,
                        output,
                        "frozen:test",
                        scenarios=3,
                        timeout_seconds=45,
                        allocation_seconds=180,
                    )
            self.assertEqual((output / "stdout.txt").read_bytes(), b"partial output")
            self.assertEqual((output / "stderr.txt").read_bytes(), b"timeout detail")
            saved = json.loads((output / "container.json").read_text())
            self.assertTrue(saved.get("cleanup", {}).get("verified_absent"))
            command = json.loads((output / "command.json").read_text())
            name = command[command.index("--name") + 1]
            self.assertTrue(name.startswith("fns-opendc-local-"))
            self.assertEqual(runner.call_args_list[1].args[0], ["docker", "rm", "--force", name])
            self.assertIn(f"name=^/{name}$", runner.call_args_list[2].args[0])
            self.assertLessEqual(runner.call_args_list[1].kwargs["timeout"], 15)
            self.assertLessEqual(runner.call_args_list[2].kwargs["timeout"], 15)

    def test_unverified_absence_raises_fatal_cleanup_error(self):
        """A remaining container or unavailable Docker inventory cannot permit another run."""
        module = importlib.import_module("demo_tuning")
        checks = [
            subprocess.CompletedProcess([], 0, b"still-running\n", b""),
            subprocess.CompletedProcess([], 1, b"", b"daemon unavailable"),
            subprocess.TimeoutExpired(["docker", "ps"], 10),
        ]
        for verification in checks:
            with self.subTest(
                verification=verification
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                suite, output = root / "suite", root / "native"
                suite.mkdir()
                replies = [
                    subprocess.TimeoutExpired(["docker", "run"], 105, output=b"partial"),
                    subprocess.CompletedProcess([], 0, b"removed", b""),
                    verification,
                ]
                with patch.object(module.subprocess, "run", side_effect=replies):
                    with self.assertRaises(module.NativeCleanupError):
                        module.execute_native(
                            suite,
                            output,
                            "frozen:test",
                            scenarios=3,
                            timeout_seconds=45,
                            allocation_seconds=180,
                        )
                saved = json.loads((output / "container.json").read_text())
                self.assertFalse(saved["cleanup"]["verified_absent"])
                self.assertEqual((output / "stdout.txt").read_bytes(), b"partial")

    def test_timeout_cleanup_survives_output_write_failure(self):
        """An evidence-volume error must not skip removal of the running native container."""
        module = importlib.import_module("demo_tuning")
        original_write = Path.write_bytes

        def fail_stdout(path, data):
            """Keep command provenance while injecting a later output-volume failure.

            Args:
                path (Path): Evidence file to write.
                data (bytes): Original serialized evidence.

            Returns:
                int: Number of bytes written for unaffected files.

            Raises:
                OSError: Only the timed-out process stdout cannot be persisted.
            """
            if path.name == "stdout.txt":
                raise OSError("evidence volume full")
            return original_write(path, data)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite, output = root / "suite", root / "native"
            suite.mkdir()
            replies = [
                subprocess.TimeoutExpired(["docker", "run"], 105, output=b"partial"),
                subprocess.CompletedProcess([], 0, b"removed", b""),
                subprocess.CompletedProcess([], 0, b"", b""),
            ]
            with patch.object(
                module.subprocess, "run", side_effect=replies
            ) as runner, patch.object(Path, "write_bytes", autospec=True, side_effect=fail_stdout):
                with self.assertRaisesRegex(OSError, "evidence volume full"):
                    module.execute_native(
                        suite,
                        output,
                        "frozen:test",
                        scenarios=3,
                        timeout_seconds=45,
                        allocation_seconds=180,
                    )
            self.assertEqual(runner.call_count, 3)
            command = json.loads((output / "command.json").read_text())
            name = command[command.index("--name") + 1]
            self.assertEqual(runner.call_args_list[1].args[0], ["docker", "rm", "--force", name])

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
