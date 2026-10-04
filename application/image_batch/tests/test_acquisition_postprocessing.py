"""Infrastructure availability never enters application analysis or validation cohorts."""

import copy
import unittest

from opendc_evaluate import analyze_case
from opendc_validation import compare_tasks
from test_opendc_evaluate import evaluation_case, completions


def delayed_case(real=True):
    """Add one native availability reservation to an ordinary evaluation case.

    Args:
        real (bool): Retain the three real application tasks.

    Returns:
        tuple[dict, list[dict]]: Case and all native completions, including infrastructure.
    """
    case = evaluation_case(tasks=real)
    case["model_exhausted_jobs"] = []
    for item in case["tasks"]:
        item["task"]["duration"] = 1000
        item["metadata"]["identity"] = {}
    case["tasks"].append(
        {
            "task": {"id": 10, "submission_time": 0, "duration": 60000},
            "metadata": {
                "cohort": "infrastructure",
                "original_creation_ms": case["cutoff_ms"],
                "identity": {"synthetic_worker": "reserve"},
            },
        }
    )
    rows = completions() if real else []
    rows.append({"task_id": 10, "finish_time": 60000})
    for row in rows:
        row["schedule_time"] = 0
    return case, rows


def energy_rows(end=60000):
    """Provide complete native energy coverage independently of real completions.

    Args:
        end (int): Last native sample in milliseconds.

    Returns:
        list[dict]: Two cumulative host-energy samples at ten watts.
    """
    return [{"host_name": "worker-0", "timestamp": at, "energy_usage": at / 100} for at in (0, end)]


class AcquisitionPostprocessingTests(unittest.TestCase):
    """Keep complete native validation while scoring only real application work."""

    def test_analysis_mixed_cohort_excludes_blocker_without_extending_job_followup(self):
        """An availability blocker changes neither real responses nor real completion counts."""
        case, rows = delayed_case()
        result = analyze_case(case, rows, energy_rows())
        baseline = copy.deepcopy(case)
        baseline["tasks"] = baseline["tasks"][:-1]
        expected = analyze_case(baseline, rows[:-1], energy_rows())
        self.assertEqual(result, expected)
        self.assertEqual(result["inventory"]["simulated_tasks"], 3)
        self.assertEqual(result["boundaries"]["cohort_end_seconds"], 10)

    def test_analysis_infrastructure_only_is_native_with_zero_application_jobs(self):
        """An empty application cohort still validates real native energy output."""
        case, rows = delayed_case(real=False)
        result = analyze_case(case, rows, energy_rows())
        self.assertEqual(result["lifecycles"], [])
        self.assertEqual(result["inventory"]["simulated_tasks"], 0)
        self.assertEqual(set(result["curves"]["completed_tasks"]), {0})
        self.assertEqual(result["windows"]["fixed_window"]["energy_joules"], 50)
        with self.assertRaisesRegex(ValueError, "analytical empty"):
            analyze_case(case, rows, [], analytical_empty=True)

    def test_analysis_requires_energy_through_infrastructure_completion(self):
        """Dropping infrastructure from service does not weaken native coverage."""
        case, rows = delayed_case()
        with self.assertRaisesRegex(ValueError, "energy ends"):
            analyze_case(case, rows, energy_rows(end=10000))

    def test_comparison_mixed_cohort_is_invariant_to_infrastructure(self):
        """Predicted real response distributions and curves are unaffected by blockers."""
        case, rows = delayed_case()
        result = compare_tasks(case, rows, [], case["cutoff_ms"] + 120000)
        baseline = copy.deepcopy(case)
        baseline["tasks"] = baseline["tasks"][:-1]
        expected = compare_tasks(baseline, rows[:-1], [], case["cutoff_ms"] + 120000)
        self.assertEqual(result, expected)
        self.assertEqual(len(result["tasks"]), 3)

    def test_comparison_infrastructure_only_does_not_invent_service_samples(self):
        """Zero real Jobs yield zero curves and no paired response-error sample."""
        case, rows = delayed_case(real=False)
        result = compare_tasks(case, rows, [], case["cutoff_ms"] + 120000)
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["predicted_completed"], 0)
        self.assertEqual(result["observed_completed"], 0)
        self.assertEqual(result["completion_curve_mae"], 0)
        self.assertIsNone(result["matched_response_mae_seconds"])
        self.assertEqual(set(result["predicted_curve"]), {0})

    def test_both_entry_points_still_require_every_native_identity_once(self):
        """Missing or duplicate blockers fail before application cohort filtering."""
        case, rows = delayed_case()
        for invalid in (rows[:-1], rows + [rows[-1]]):
            with self.subTest(records=len(invalid)):
                with self.assertRaises(ValueError):
                    analyze_case(case, invalid, energy_rows())
                with self.assertRaises(ValueError):
                    compare_tasks(case, invalid, [], case["cutoff_ms"] + 120000)
