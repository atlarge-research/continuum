"""Causal occupancy estimates preserve measured classifier profiles and uncertainty."""

import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from forecast_trace import iso
from opendc_inputs import verify_inputs
from opendc_scenarios import prepare_suite
from opendc_native_batch import plan_suite
from opendc_validation import compare_tasks
from test_opendc_scenarios import CUTOFF, configuration, make_forecast, observer_rows, job


class OccupancyModelTests(unittest.TestCase):
    """Hand-calculated startup and residual examples exercise the practical model."""

    def module(self):
        """Load the production model after asserting its presence.

        Returns:
            module: Causal occupancy implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("opendc_occupancy"))
        return importlib.import_module("opendc_occupancy")

    def calibration(self):
        """Return frozen pre-cutoff durations and observed lifecycle estimates.

        Returns:
            dict: Literal calibration with no post-cutoff observations.
        """
        return {
            "contract": "causal-occupancy-v1",
            "cutoff_ms": 100000,
            "startup_ms": 2000,
            "release_ms": 1000,
            "duration_samples_ms": [30000, 35000, 40000],
            "residual_resources": {
                "cpu_count": 1,
                "cpu_capacity": 2400.0,
                "mem_capacity": 512,
                "cpu_usage": 2000.0,
            },
        }

    def case(self):
        """Construct one queued task and one running task past its frozen profile.

        Returns:
            dict: Case retaining explicit original exhausted-work evidence.
        """
        return {
            "cutoff_ms": 110000,
            "tasks": [
                {
                    "task": {
                        "id": 1,
                        "submission_time": 0,
                        "duration": 30000,
                        "cpu_count": 1,
                        "cpu_capacity": 2400.0,
                        "mem_capacity": 512,
                        "fragments": [
                            {"id": 1, "duration": 30000, "cpu_count": 1, "cpu_usage": 2000.0}
                        ],
                    },
                    "metadata": {"phase": "queued"},
                }
            ],
            "model_exhausted_jobs": [
                {
                    "task_id": 2,
                    "metadata": {"phase": "running", "elapsed_ms": 36000, "node_name": "w1"},
                    "remaining_execution_ms": 0,
                    "observed_completed": False,
                }
            ],
        }

    def test_lifecycle_occupancy_and_conditional_residual_keep_raw_evidence(self):
        """Known longer profiles imply a four-second conditional residual."""
        case = self.case()
        original = copy.deepcopy(case)
        modeled = self.module().apply_occupancy(case, self.calibration())
        self.assertEqual(case, original)
        self.assertEqual(modeled["tasks"][0]["task"]["duration"], 33000)
        self.assertEqual(
            modeled["tasks"][0]["task"]["fragments"][1],
            original["tasks"][0]["task"]["fragments"][0],
        )
        self.assertEqual(modeled["tasks"][1]["task"]["duration"], 5000)
        self.assertEqual(
            modeled["tasks"][1]["metadata"]["occupancy"]["residual_basis"],
            "conditional_completed_durations",
        )
        self.assertEqual(modeled["model_exhausted_jobs"], original["model_exhausted_jobs"])

    def test_no_longer_observation_uses_labeled_five_second_fallback(self):
        """The fallback is an occupancy estimate, never an observed completion."""
        case = self.case()
        case["model_exhausted_jobs"][0]["metadata"]["elapsed_ms"] = 45000
        modeled = self.module().apply_occupancy(case, self.calibration())
        self.assertEqual(modeled["tasks"][1]["task"]["duration"], 6000)
        self.assertEqual(
            modeled["tasks"][1]["metadata"]["occupancy"]["residual_basis"], "five_second_fallback"
        )
        self.assertIs(modeled["model_exhausted_jobs"][0]["observed_completed"], False)

    def test_future_calibration_is_rejected(self):
        """A later calibration cannot silently leak into an earlier replay."""
        calibration = self.calibration()
        calibration["cutoff_ms"] = 120000
        with self.assertRaisesRegex(ValueError, "cutoff"):
            self.module().apply_occupancy(self.case(), calibration)

    def test_estimated_exhausted_work_keeps_observed_outcome_and_censoring(self):
        """A modeled residual cannot remove its actual Job from comparison totals."""
        metadata = {
            "cohort": "backlog",
            "phase": "running",
            "original_creation_ms": 80000,
            "identity": {"kubernetes_job_uid": "a"},
            "occupancy": {"startup_ms": 0, "release_ms": 1000},
        }
        case = {
            "cutoff_ms": 100000,
            "experiment_kind": "known-arrival",
            "tasks": [
                {"task": {"id": 1, "submission_time": 0, "duration": 6000}, "metadata": metadata}
            ],
            "model_exhausted_jobs": [{"task_id": 1, "metadata": metadata}],
        }
        native = [{"task_id": 1, "schedule_time": 0, "finish_time": 6000}]
        observed = [
            {
                "uid": "a",
                "creation_ms": 80000,
                "start_ms": 99000,
                "finish_ms": 105000,
                "job_finish_ms": 106000,
                "status": "Complete",
                "censored_through_ms": None,
            }
        ]
        result = compare_tasks(case, native, observed, 160000)
        self.assertEqual(result["predicted_completed"], 1)
        self.assertEqual(result["observed_completed"], 1)
        self.assertEqual(result["tasks"][0]["finish_error_seconds"], 0)
        observed[0].update(
            finish_ms=None, job_finish_ms=None, status="running", censored_through_ms=101000
        )
        result = compare_tasks(case, native, observed, 160000)
        self.assertIn("a", result["unknown_outcome_uids"])
        self.assertFalse(result["coverage_complete"])

    def test_calibration_uses_only_eligible_bounded_completion_and_assignment_evidence(self):
        """First-observation censoring remains separate from measured startup samples."""
        source = {
            "kubernetes_job_uid": "a",
            "image_count": 4,
            "inference_repetitions": 128,
            "sampling_quality": "sampled",
            "resource_sample_count": 4,
            "completion_time": iso(90000),
            "execution_start_time": iso(53000),
            "execution_completion_time": iso(88000),
        }
        task = self.case()["tasks"][0]["task"]
        record = {"source": source, "task": task}
        template = {"selection_cutoff": iso(100000), "record": record}
        trace = SimpleNamespace(
            cutoff=100000,
            completed=[record],
            states=[
                (
                    50000,
                    {
                        "jobs": {
                            "queued": [{"kubernetes_job_uid": "a", "node_name": None}],
                            "active": [],
                        }
                    },
                ),
                (
                    51000,
                    {
                        "jobs": {
                            "queued": [{"kubernetes_job_uid": "a", "node_name": "w1"}],
                            "active": [],
                        }
                    },
                ),
            ],
        )
        calibrated = self.module().calibrate_occupancy(trace, template)
        self.assertEqual(calibrated["startup_ms"], 2000)
        self.assertEqual(calibrated["release_ms"], 2000)
        self.assertEqual(calibrated["source_job_uids"], ["a"])
        trace.cutoff = 110000
        with self.assertRaisesRegex(ValueError, "selection"):
            self.module().calibrate_occupancy(trace, template)

    @patch.dict(os.environ, {"OPENDC_RUNTIME": "fns-demo"})
    def test_prepared_cases_retain_exhausted_identity_and_block_down(self):
        """An estimated residual occupies its original worker in every shared future."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            config = {**configuration(), "occupancy_model": "causal-occupancy-v1"}
            manifest = prepare_suite(forecast, observer, config, root / "suite", "pinned-trace")
            self.assertIn(
                {"candidate": "scale-down", "reason": "exhausted_or_unresolved_work"},
                manifest["unavailable_candidates"],
            )
            for entry in manifest["experiments"]:
                path = root / "suite" / entry["input_dir"]
                verify_inputs(path)
                case = json.loads((path / "case.json").read_text())
                raw = case["model_exhausted_jobs"][0]
                estimate = next(row for row in case["tasks"] if row["task"]["id"] == raw["task_id"])
                self.assertEqual(estimate["metadata"]["preserved_assignment"], "worker-a")
                self.assertIs(raw["observed_completed"], False)
            self.assertEqual(plan_suite(root / "suite")["actions"], ["unchanged", "scale-up"])

    @patch.dict(os.environ, {"OPENDC_RUNTIME": "fns-demo"})
    def test_finished_classifier_retains_pod_requests_without_predicting_another_finish(self):
        """A still-running Pod is occupied even after its classifier has terminated."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = observer_rows()
            releasing = job("releasing", "worker-b", "terminated", CUTOFF - 2000)
            releasing.update(execution_finish_time=iso(CUTOFF - 1000), pod_phase="Running")
            rows["cluster-state.jsonl"][-1]["jobs"]["finished"] = [releasing]
            with patch("test_opendc_scenarios.observer_rows", return_value=rows):
                forecast, observer = make_forecast(root)
            config = {**configuration(), "occupancy_model": "causal-occupancy-v1"}
            manifest = prepare_suite(forecast, observer, config, root / "suite", "pinned-trace")
            path = root / "suite" / manifest["experiments"][0]["input_dir"]
            verify_inputs(path)
            case = json.loads((path / "case.json").read_text())
            records = [
                row
                for row in case["tasks"]
                if row["metadata"].get("kubernetes_job_uid") == "releasing"
            ]
            self.assertEqual(len(records), 1)
            release = records[0]
            self.assertEqual(release["metadata"]["phase"], "release")
            self.assertEqual(
                release["metadata"]["occupancy"]["observed_classifier_finish_ms"], CUTOFF - 1000
            )
            self.assertEqual(release["metadata"]["preserved_assignment"], "worker-b")
            self.assertEqual(release["task"]["duration"], 1000)
            self.assertTrue(
                all(fragment["cpu_usage"] == 0 for fragment in release["task"]["fragments"])
            )


if __name__ == "__main__":
    unittest.main()
