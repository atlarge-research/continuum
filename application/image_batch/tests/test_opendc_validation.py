"""Behavioral checks for retrospective replay and matched observation windows."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Discovery runs these tests without an installed image_batch package.
# pylint: disable=wrong-import-position
from forecast_trace import canonical, iso
from opendc_inputs import verify_inputs
import opendc_validation as validation
from test_opendc_scenarios import CUTOFF, configuration, make_forecast

# pylint: enable=wrong-import-position


class ValidationTests(unittest.TestCase):
    """Protect common futures, causal profiles, identity and censoring semantics."""

    def test_finished_snapshot_supplies_outcome_before_profile_emission(self):
        """Classifier completion is observable even when resource-profile emission is absent."""
        job = {
            "kubernetes_job_uid": "finished",
            "node_name": "worker-a",
            "execution_state": "terminated",
            "pod_phase": "Succeeded",
            "execution_start_time": iso(CUTOFF - 5000),
            "execution_finish_time": iso(CUTOFF - 1000),
        }
        trace = SimpleNamespace(
            arrivals={"finished": {"creation_ms": CUTOFF - 10000}},
            completed=[],
            states=[(CUTOFF, {"jobs": {"queued": [], "active": [], "finished": [job]}})],
        )
        observed = validation.observed_jobs(trace)[0]
        self.assertEqual(observed["start_ms"], CUTOFF - 5000)
        self.assertEqual(observed["finish_ms"], CUTOFF - 1000)
        self.assertEqual(observed["status"], "classifier_finished")
        self.assertIsNone(observed["job_finish_ms"])
        job["pod_phase"] = "Failed"
        failed = validation.observed_jobs(trace)[0]
        self.assertEqual(failed["status"], "Failed")
        self.assertIsNone(failed["finish_ms"])

    def test_truncation_preserves_backlog_and_parent_future(self):
        """A shorter horizon retains exact profiles and removes only later arrivals."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            suite = validation.prepare_validation_suite(
                forecast,
                observer,
                configuration(),
                root / "suite",
                horizon_seconds=10,
                scenarios=1,
                arrival_source="forecast",
            )
            self.assertEqual(len(suite["experiments"]), 1)
            path = root / "suite" / suite["experiments"][0]["input_dir"]
            verify_inputs(path)
            case = json.loads((path / "case.json").read_text())
            self.assertEqual(
                [r["task"]["id"] for r in case["tasks"] if r["metadata"]["cohort"] == "future"],
                [20],
            )
            self.assertEqual(
                len([r for r in case["tasks"] if r["metadata"]["cohort"] == "backlog"]), 3
            )
            self.assertEqual(case["workers"][0]["modeled_cores"], 3)
            self.assertEqual(case["horizon_ms"], 10000)
            self.assertEqual(len(case["model_exhausted_jobs"]), 1)
            self.assertEqual(case["initial_membership"], suite["initial_membership"])

    def test_known_arrivals_use_real_identity_and_frozen_profile(self):
        """Post-cutoff arrival evidence supplies timestamps, never actual future runtimes."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            event = {
                "schema_version": 1,
                "event_type": "job.observed",
                "timestamp": iso(CUTOFF + 2000),
                "details": {
                    "kubernetes_job_uid": "future-real",
                    "workload_run_id": "run-test",
                    "creation_time": iso(CUTOFF + 1000),
                },
            }
            with (observer / "observer-events.jsonl").open("ab") as stream:
                stream.write(canonical(event))
            suite = validation.prepare_validation_suite(
                forecast,
                observer,
                configuration(),
                root / "suite",
                horizon_seconds=10,
                scenarios=1,
                arrival_source="known-arrival",
            )
            path = root / "suite" / suite["experiments"][0]["input_dir"]
            verify_inputs(path)
            case = json.loads((path / "case.json").read_text())
            future = [r for r in case["tasks"] if r["metadata"]["cohort"] == "future"]
            self.assertEqual(len(future), 1)
            self.assertEqual(future[0]["metadata"]["identity"]["kubernetes_job_uid"], "future-real")
            self.assertEqual(future[0]["task"]["submission_time"], 1000)
            self.assertEqual(future[0]["task"]["duration"], 6000)

    def test_comparison_retains_original_wait_and_censored_jobs(self):
        """A future observation beyond E is censored, and late context is not a target."""
        case = {
            "cutoff_ms": 100000,
            "experiment_kind": "known-arrival",
            "tasks": [
                {
                    "task": {"id": 1, "submission_time": 0, "duration": 20000},
                    "metadata": {
                        "cohort": "backlog",
                        "phase": "running",
                        "original_creation_ms": 80000,
                        "identity": {"kubernetes_job_uid": "a"},
                    },
                },
                {
                    "task": {"id": 2, "submission_time": 70000, "duration": 20000},
                    "metadata": {
                        "cohort": "future",
                        "original_creation_ms": 170000,
                        "identity": {"kubernetes_job_uid": "context"},
                    },
                },
            ],
            "model_exhausted_jobs": [],
        }
        observed = [
            {
                "uid": "a",
                "creation_ms": 80000,
                "start_ms": 90000,
                "finish_ms": 170000,
                "job_finish_ms": 173000,
                "node_name": "worker-a",
                "status": "Complete",
            },
            {
                "uid": "context",
                "creation_ms": 170000,
                "start_ms": 170000,
                "finish_ms": 190000,
                "job_finish_ms": 191000,
                "node_name": "worker-a",
                "status": "Complete",
            },
        ]
        result = validation.compare_tasks(
            case,
            [
                {"task_id": 1, "finish_time": 20000, "schedule_time": 0},
                {"task_id": 2, "finish_time": 90000, "schedule_time": 70000},
            ],
            observed,
            220000,
            window_seconds=60,
        )
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["predicted_response_seconds"], 40)
        self.assertEqual(result["observed_completed"], 0)
        self.assertEqual(result["observed_unfinished"], 1)
        self.assertEqual(result["predicted_completed"], 1)
        self.assertEqual(result["matched_completed_pairs"], [])
        self.assertIsNone(result["matched_response_mae_seconds"])

    def test_short_capture_and_internal_gap_are_not_zero_observations(self):
        """A missing interval invalidates scoring even when later observations exist."""
        coverage = validation.observation_coverage([0, 1000, 2000, 6000, 7000], [], 0, 7000)
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["gaps"], [[2000, 6000]])
        self.assertFalse(validation.observation_coverage([0, 1000], [], 0, 2000)["complete"])
        self.assertFalse(
            validation.observation_coverage([0, 1000, 2000], [1500], 0, 2000)["complete"]
        )

    def test_summary_uses_ensemble_median_and_counts_empirical_coverage(self):
        """One outlying scenario must not turn the median curve into its mean."""
        rows = [
            {
                "predicted_curve": values,
                "observed_curve": [0, 3],
                "tasks": [],
                "observations": [],
                "coverage_complete": True,
                "completion_curve_mae": 0,
            }
            for values in ([0, 1], [0, 2], [0, 9])
        ]
        summary = validation.summarize_scenarios(rows)
        self.assertEqual(summary["completion_median"], [0, 2])
        self.assertEqual(summary["completion_curve_mae"], 0.5)
        self.assertEqual(summary["completion_envelope_coverage"], 1)

    def test_parameter_selection_rejects_held_out_results(self):
        """Held-out outcomes cannot be passed into parameter selection."""
        with self.assertRaisesRegex(ValueError, "validation"):
            validation.select_configuration({"split": "held-out", "groups": []})

    def test_missing_outcome_is_not_established_censoring(self):
        """Continuous snapshots do not turn a missing outcome into zero completions."""
        case = {
            "cutoff_ms": 100000,
            "model_exhausted_jobs": [],
            "tasks": [
                {
                    "task": {"id": 1, "submission_time": 0, "duration": 10000},
                    "metadata": {
                        "cohort": "backlog",
                        "phase": "running",
                        "original_creation_ms": 90000,
                        "identity": {"kubernetes_job_uid": "missing"},
                    },
                }
            ],
        }
        native = [{"task_id": 1, "schedule_time": 0, "finish_time": 10000}]
        observations = [
            {
                "uid": "missing",
                "creation_ms": 90000,
                "start_ms": None,
                "finish_ms": None,
                "job_finish_ms": None,
                "node_name": "worker",
                "status": "unknown",
            }
        ]
        result = validation.compare_tasks(
            case, native, observations, 220000, window_seconds=60, state_coverage={"complete": True}
        )
        self.assertFalse(result["coverage_complete"])
        self.assertIsNone(result["completion_curve_mae"])
        self.assertEqual(result["unknown_outcome_uids"], ["missing"])
        observations[0]["censored_through_ms"] = 220000
        result = validation.compare_tasks(case, native, observations, 220000, window_seconds=60)
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["observed_completed"], 0)
        result = validation.compare_tasks(
            case, native, [], 220000, window_seconds=60, state_coverage={"complete": True}
        )
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["unknown_outcome_uids"], ["missing"])
        trace = SimpleNamespace(
            arrivals={"active": {"creation_ms": 90000}, "missing": {"creation_ms": 90000}},
            completed=[],
            states=[
                (
                    220000,
                    {
                        "jobs": {
                            "active": [
                                {
                                    "kubernetes_job_uid": "active",
                                    "execution_state": "running",
                                    "node_name": "worker",
                                }
                            ],
                            "queued": [],
                        }
                    },
                )
            ],
        )
        records = {r["uid"]: r for r in validation.observed_jobs(trace)}
        self.assertEqual(records["active"]["censored_through_ms"], 220000)
        self.assertIsNone(records["missing"]["censored_through_ms"])

    def test_runner_cost_uses_measured_resources_and_keeps_missing_unknown(self):
        """Kubernetes has terminal time rather than Docker wall time; neither is CPU cost."""
        self.assertEqual(
            validation.execution_cost([{"resources": {"actual_elapsed_seconds": 7}}]), 7
        )
        self.assertIsNone(validation.execution_cost([{"resources": {}}]))

    def test_failed_observation_is_retained_without_inventing_a_completion(self):
        """A failed Job remains in the arrival cohort but cannot become successful work."""
        with tempfile.TemporaryDirectory() as temporary:
            _, observer = make_forecast(Path(temporary))
            rows, _ = validation.bounded_read(observer)
            failed = json.loads(json.dumps(rows["workload.jsonl"][0]))
            failed["source"]["terminal_status"] = "Failed"
            rows["workload.jsonl"] = [failed]
            _, observations = validation.read_observations(rows, "run-test")
            item = next(
                r for r in observations if r["uid"] == failed["source"]["kubernetes_job_uid"]
            )
            self.assertEqual(item["status"], "Failed")
            self.assertIsNone(item["finish_ms"])

    def test_failed_event_is_reported_without_a_workload_profile(self):
        """The observer emits job.failed diagnostics instead of successful workload records."""
        with tempfile.TemporaryDirectory() as temporary:
            _, observer = make_forecast(Path(temporary))
            rows, _ = validation.bounded_read(observer)
            failed = rows["workload.jsonl"].pop(0)
            uid = failed["source"]["kubernetes_job_uid"]
            rows["observer-events.jsonl"].append(
                {
                    "event_type": "job.observed",
                    "timestamp": iso(CUTOFF),
                    "details": {
                        "kubernetes_job_uid": uid,
                        "workload_run_id": "run-test",
                        "creation_time": failed["task"]["submission_time"],
                    },
                }
            )
            rows["observer-events.jsonl"].append(
                {
                    "event_type": "job.failed",
                    "timestamp": iso(CUTOFF),
                    "details": {"kubernetes_job_uid": uid},
                }
            )
            _, observations = validation.read_observations(rows, "run-test")
            self.assertEqual(next(r for r in observations if r["uid"] == uid)["status"], "Failed")


if __name__ == "__main__":
    unittest.main()
