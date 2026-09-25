"""Contract regressions for one-process FNS sample/action execution."""
import json
import os
from pathlib import Path
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# pylint: disable=wrong-import-position
from opendc_inputs import file_hashes, write_json
from opendc_scenarios import prepare_suite, _write_case
from opendc_native_batch import plan_suite, execute_suite
from opendc_evaluate import _resources
from opendc_validation import evaluate_matrix
from test_opendc_scenarios import make_forecast, observer_rows, configuration

# pylint: enable=wrong-import-position


def batch_fixture(root):
    """Prepare two distinct futures across unchanged/up/busy-cordon actions.

    Args:
        root (Path): Empty evidence directory.

    Returns:
        Path: Verified suite with six individual cases.
    """
    rows = observer_rows()
    for state in rows["cluster-state.jsonl"]:
        state["jobs"]["active"] = [
            job for job in state["jobs"]["active"] if job["kubernetes_job_uid"] != "exhausted"
        ]
    with patch("test_opendc_scenarios.observer_rows", return_value=rows):
        forecast, observer = make_forecast(root)
    prepare_suite(forecast, observer, configuration(), root / "suite", "pinned-trace")
    return root / "suite"


def empty_sample_fixture(root, all_empty=False):
    """Replace initial work with empty backlog and one or all empty future samples.

    Args:
        root (Path): Fresh fixture parent.
        all_empty (bool): Remove future work from every sample when true.

    Returns:
        Path: Hash-verified suite containing analytically empty cohorts.
    """
    suite = batch_fixture(root)
    manifest = json.loads((suite / "manifest.json").read_text())
    for entry in manifest["experiments"]:
        path = suite / entry["input_dir"]
        case = json.loads((path / "case.json").read_text())
        records = [
            row
            for row in case["tasks"]
            if row["metadata"]["cohort"] == "future" and entry["scenario"] != 0 and not all_empty
        ]
        shutil.rmtree(path)
        _write_case(
            path,
            case["candidate"],
            case["scenario"],
            case["workers"],
            [row["task"] for row in records],
            records,
            [],
            [],
            {"cutoff_ms": case["cutoff_ms"], "horizon_ms": case["horizon_ms"]},
            "pinned-trace",
            case["selected_worker"],
            "explicit-empty-sample-fixture",
        )
    manifest["sha256"] = file_hashes(suite, exclude=("manifest.json",))
    write_json(suite / "manifest.json", manifest)
    return suite


class NativeBatchTests(unittest.TestCase):
    """Batch identity must follow the pinned Cartesian contract, not directory order."""

    def test_mapping_preserves_actions_samples_and_individual_inputs(self):
        """A union topology closes only the absent reserve and requested drain host."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            suite = batch_fixture(Path(temporary))
            before = file_hashes(suite)
            plan = plan_suite(suite)
            self.assertEqual(plan["samples"], [0, 1])
            self.assertEqual(plan["actions"], ["unchanged", "scale-up", "scale-down"])
            self.assertEqual(
                plan["experiment"]["cordonHosts"], [["worker-c"], [], ["worker-a", "worker-c"]]
            )
            self.assertEqual(
                [(r["native_index"], r["candidate"], r["scenario"]) for r in plan["mapping"]],
                [
                    (i, action, sample)
                    for i, (action, sample) in enumerate(
                        (a, s) for a in plan["actions"] for s in plan["samples"]
                    )
                ],
            )
            self.assertEqual(file_hashes(suite), before)

    def test_empty_samples_keep_identity_without_entering_native_workload_matrix(self):
        """An empty draw is a complete zero cohort, not a missing or fabricated sample."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            suite = empty_sample_fixture(Path(temporary))
            plan = plan_suite(suite)
            self.assertEqual(plan["samples"], [0, 1])
            self.assertEqual(plan["native_samples"], [1])
            self.assertEqual(
                [row["native_index"] for row in plan["mapping"]], [None, 0, None, 1, None, 2]
            )
            self.assertEqual(len(plan["experiment"]["workloads"]), 1)

    def test_all_empty_samples_produce_verified_members_without_native_process(self):
        """Idle decisions remain possible when every sampled future is empty."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            suite = empty_sample_fixture(root, all_empty=True)
            with patch("opendc_native_batch.run_process") as launch:
                self.assertEqual(execute_suite(suite, root / "output"), 0)
                launch.assert_not_called()
            saved = json.loads((root / "output/batch.json").read_text())
            self.assertEqual(saved["remaining_experiments"], 0)
            self.assertEqual(len(saved["experiments"]), 6)
            self.assertTrue(all(row["validated"] for row in saved["experiments"]))

    def test_missing_cartesian_member_is_rejected_before_launch(self):
        """Incomplete action/sample pairing cannot silently become another experiment."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            suite = batch_fixture(Path(temporary))
            manifest = json.loads((suite / "manifest.json").read_text())
            manifest["experiments"].pop()
            write_json(suite / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "Cartesian"):
                plan_suite(suite)

    def test_shared_process_failure_preserves_incomplete_evidence(self):
        """A process error never yields successful members or a complete batch."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            suite = batch_fixture(root)
            failure = {
                "exit_code": 1,
                "timed_out": False,
                "received_signal": None,
                "launch_error": None,
                "wall_seconds": 2.5,
            }
            with patch("opendc_native_batch.run_process", return_value=failure):
                self.assertEqual(execute_suite(suite, root / "output"), 1)
            saved = json.loads((root / "output/batch.json").read_text())
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["remaining_experiments"], 6)
            self.assertEqual(saved["experiments"], [])
            self.assertEqual(saved["shared_process"]["wall_seconds"], 2.5)
            self.assertTrue((root / "output/experiment.json").exists())

    def test_shared_cost_cannot_be_attributed_to_each_member(self):
        """A repeated shared wall time must never be summed as individual measurements."""
        with tempfile.TemporaryDirectory() as temporary:
            values, missing = _resources(
                Path(temporary),
                {
                    "process": {
                        "execution_kind": "shared_native_batch",
                        "wall_seconds": 12,
                        "shared_process_path": "../../../shared-resources.json",
                    }
                },
            )
            self.assertIsNone(values["actual_elapsed_seconds"])
            self.assertTrue(all("shared" in item["reason"] for item in missing))

    def test_duplicate_trace_bytes_keep_distinct_sample_uris(self):
        """Duplicated developer samples retain two declared identities without deduplication."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            suite = batch_fixture(Path(temporary))
            manifest = json.loads((suite / "manifest.json").read_text())
            for action in ("unchanged", "scale-up", "scale-down"):
                source = suite / next(
                    r["input_dir"]
                    for r in manifest["experiments"]
                    if r["candidate"] == action and r["scenario"] == 0
                )
                destination = suite / next(
                    r["input_dir"]
                    for r in manifest["experiments"]
                    if r["candidate"] == action and r["scenario"] == 1
                )
                shutil.rmtree(destination)
                shutil.copytree(source, destination)
                case = json.loads((destination / "case.json").read_text())
                case["scenario"] = 1
                write_json(destination / "case.json", case)
                copied = json.loads((destination / "manifest.json").read_text())
                copied["sha256"] = file_hashes(destination, exclude=("manifest.json",))
                write_json(destination / "manifest.json", copied)
            manifest["sha256"] = file_hashes(suite, exclude=("manifest.json",))
            manifest["experiments"].reverse()
            write_json(suite / "manifest.json", manifest)
            plan = plan_suite(suite)
            uris = [w["source"]["uri"] for w in plan["experiment"]["workloads"]]
            self.assertEqual(len(set(uris)), 2)
            self.assertEqual(len(plan["mapping"]), 6)
            self.assertEqual(plan["samples"], [0, 1])

    def test_missing_native_outputs_reject_successful_process_exit(self):
        """An exit code of zero without the full output matrix is not validation."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            suite = batch_fixture(root)
            process = {"exit_code": 0, "timed_out": False, "received_signal": None}
            with patch("opendc_native_batch.run_process", return_value=process):
                self.assertEqual(execute_suite(suite, root / "output"), 1)
            result = json.loads((root / "output/batch.json").read_text())
            self.assertIn("output inventory", result["error"])
            self.assertEqual(result["remaining_experiments"], 6)

    def test_native_timeout_preserves_process_evidence(self):
        """The shared process deadline remains distinct from invalid simulator output."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            suite = batch_fixture(root)
            process = {"exit_code": -15, "timed_out": True, "received_signal": None}
            with patch("opendc_native_batch.run_process", return_value=process):
                self.assertEqual(execute_suite(suite, root / "output"), 124)
            self.assertEqual(
                json.loads((root / "output/batch.json").read_text())["status"], "timed_out"
            )

    def test_member_workload_settings_cannot_be_replaced_silently(self):
        """Every member's workload/scheduler options must match the shared experiment."""
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            suite = batch_fixture(Path(temporary))
            manifest = json.loads((suite / "manifest.json").read_text())
            case = suite / manifest["experiments"][-1]["input_dir"]
            config = json.loads((case / "experiment.json").read_text())
            config["workloads"][0]["sampleFraction"] = 0.5
            write_json(case / "experiment.json", config)
            member = json.loads((case / "manifest.json").read_text())
            member["sha256"] = file_hashes(case, exclude=("manifest.json",))
            write_json(case / "manifest.json", member)
            manifest["sha256"] = file_hashes(suite, exclude=("manifest.json",))
            write_json(suite / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "experiment settings"):
                plan_suite(suite)

    def test_observation_matrix_cannot_pool_actions_as_future_samples(self):
        """Unchanged observations must never score a mixed counterfactual action matrix."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "index.json", {"observer_dir": "/unused", "experiments": []})
            batch = {
                "experiments": [
                    {"candidate": action, "scenario": 0}
                    for action in ("unchanged", "scale-up", "scale-down")
                ]
            }
            with patch("opendc_validation.load_batch", return_value=(root, batch)), patch(
                "opendc_validation.bounded_read",
                side_effect=AssertionError("must reject actions first"),
            ):
                with self.assertRaisesRegex(ValueError, "unchanged"):
                    evaluate_matrix(root / "index.json", root)


if __name__ == "__main__":
    unittest.main()
