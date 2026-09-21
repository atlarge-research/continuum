"""Manual batches must stop at failure and reject unsafe suite input references."""
import json
import shutil
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import opendc_batch
from opendc_inputs import file_hashes, write_json
from test_opendc_provisional import provisional_input


class BatchTests(unittest.TestCase):
    """Exercise persisted batch outcomes with an external runner substitute."""

    def test_failure_stops_remaining_experiments(self):
        """A failed first runner leaves later cases unexecuted and records failure."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            suite = root / "suite"
            suite.mkdir()
            provisional_input(suite / "first")
            second = provisional_input(suite / "second")
            second["scenario"] = 1
            write_json(suite / "second/case.json", second)
            second_manifest = json.loads((suite / "second/manifest.json").read_text())
            second_manifest["sha256"] = file_hashes(suite / "second", exclude=("manifest.json",))
            write_json(suite / "second/manifest.json", second_manifest)
            write_json(
                suite / "manifest.json",
                {
                    "contract": "opendc-scenarios-v1",
                    "status": "ready",
                    "experiments": [
                        {"candidate": "unchanged", "scenario": n, "input_dir": name}
                        for n, name in enumerate(("first", "second"))
                    ],
                    "sha256": file_hashes(suite),
                },
            )
            with patch.object(opendc_batch, "run_local_case", return_value={"status": "failed"}):
                result = opendc_batch.run_suite(suite, root / "results", image="test:v1")
            persisted = json.loads((root / "results/batch.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(persisted["experiments"]), 1)
            self.assertEqual(persisted["remaining_experiments"], 1)

    def test_suite_cannot_reference_outside_inputs(self):
        """Reject path traversal before invoking Docker or SSH."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            suite = root / "suite"
            suite.mkdir()
            write_json(
                suite / "manifest.json",
                {
                    "contract": "opendc-scenarios-v1",
                    "status": "ready",
                    "experiments": [
                        {"candidate": "unchanged", "scenario": 0, "input_dir": "../outside"}
                    ],
                    "sha256": {},
                },
            )
            with self.assertRaises(ValueError):
                opendc_batch.run_suite(suite, root / "results", image="test:v1")

    def test_candidate_labels_must_match_executed_case(self):
        """Reject a scale-down label referencing an unchanged experiment."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            suite = root / "suite"
            suite.mkdir()
            provisional_input(suite / "case")
            write_json(
                suite / "manifest.json",
                {
                    "contract": "opendc-scenarios-v1",
                    "status": "ready",
                    "experiments": [
                        {"candidate": "scale-down", "scenario": 99, "input_dir": "case"}
                    ],
                    "sha256": file_hashes(suite),
                },
            )
            with self.assertRaises(ValueError):
                opendc_batch.run_suite(suite, root / "output", image="test:v1")

    def test_local_success_requires_matching_validation_and_process_evidence(self):
        """A zero Docker exit cannot bless a success-labelled invalid runner record."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            provisional_input(root / "inputs")

            def fake_docker(*_args, **_kwargs):
                """Write the malformed evidence a broken external image could return.

                Args:
                    _args (tuple): Ignored subprocess positional arguments.
                    _kwargs (dict): Ignored subprocess keyword arguments.

                Returns:
                    SimpleNamespace: Successful process exit with invalid saved evidence.
                """
                run = root / "result/run"
                run.mkdir()
                shutil.copytree(root / "inputs", run / "inputs")
                write_json(
                    run / "execution.json",
                    {
                        "contract": "opendc-provisional-v1",
                        "status": "succeeded",
                        "validation": {"status": "failed"},
                        "runner_exit_code": 0,
                        "process": {},
                        "sha256": file_hashes(run),
                    },
                )
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

            with patch.object(opendc_batch.subprocess, "run", side_effect=fake_docker):
                result = opendc_batch.run_local_case(root / "inputs", root / "result", "test:v1", 5)
            self.assertFalse(result["validated"])
