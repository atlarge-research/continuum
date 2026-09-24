"""Controlled reports pair predictions only with the physical action actually performed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Tests exercise the checked-out report module.
# pylint: disable=wrong-import-position
import opendc_report_controlled as controlled
from opendc_report_controlled import write_report
from opendc_report import write_report as combined_report
from test_opendc_report import validation_result

# pylint: enable=wrong-import-position


class ControlledReportTests(unittest.TestCase):
    """Saved numerical results must redraw offline and retain action identity."""

    def test_action_axis_uses_measured_interval_without_changing_evidence(self):
        """Time zero is the bounded API action, not the earlier model snapshot."""
        saved = {"context": {"observed_action_interval_seconds": [1, 3]}}
        self.assertEqual(controlled.action_reference(saved), 2)
        self.assertEqual(saved["context"]["observed_action_interval_seconds"], [1, 3])
        self.assertIsNone(controlled.action_reference({"context": {}}))
        with self.assertRaises(ValueError):
            controlled.action_reference({"context": {"observed_action_interval_seconds": [3, 1]}})

    def test_timing_breakdown_matches_completed_future_cohort(self):
        """A censored future or a pinned remainder must not enter the new-Job timing mean."""
        saved = {
            "comparison": {
                "matched_completed_pairs": [{"uid": "first"}, {"uid": "second"}, {"uid": "old"}],
                "tasks": [
                    {
                        "uid": uid,
                        "cohort": cohort,
                        "start_or_resume_error_seconds": start,
                        "runtime_or_remainder_error_seconds": runtime,
                        "original_creation_ms": 1000,
                        "observed": {"start_ms": 6000 if uid == "first" else 10000},
                    }
                    for uid, cohort, start, runtime in [
                        ("first", "future", -30, 1),
                        ("second", "future", 10, -3),
                        ("old", "backlog", 90, 90),
                        ("censored", "future", 100, 100),
                    ]
                ],
            }
        }
        self.assertEqual(
            controlled.timing_summary(saved),
            {
                "matched_future_jobs": 2,
                "start_error_jobs": 2,
                "runtime_error_jobs": 2,
                "start_mae_seconds": 20,
                "runtime_mae_seconds": 2,
                "observed_wait_jobs": 2,
                "observed_wait_range_seconds": [5, 9],
            },
        )
        self.assertIsNone(controlled.timing_summary({})["start_mae_seconds"])

    def test_combined_report_appends_controls_and_preserves_offline_payload(self):
        """Controlled evidence is last, and offline regeneration retains it unchanged."""
        saved = {
            "schema_version": "opendc-controlled-report-v1",
            "comparisons": [{"context": {"candidate": "scale-down"}, "physical": {"kind": "busy"}}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main, actions = root / "main.json", root / "actions.json"
            main.write_text(json.dumps({"results": [validation_result()]}))
            actions.write_text(json.dumps(saved))
            with patch("opendc_report.render_controlled_pages") as render:
                audit = combined_report([actions, main], root / "first")
                self.assertEqual(audit["section_order"], ["configuration", "controlled-validation"])
                self.assertEqual(render.call_args.args[1], saved["comparisons"])
                combined_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(
                json.loads((root / "first/metrics.json").read_text()),
                json.loads((root / "second/metrics.json").read_text()),
            )
            saved["comparisons"][0]["context"]["candidate"] = "scale-up"
            actions.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "observed action"):
                combined_report([actions], root / "invalid")

    def test_wrong_observed_action_is_rejected(self):
        """A scale-up prediction cannot be labeled as an observed cordon replay."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "comparison.json"
            source.write_text(
                json.dumps({"context": {"candidate": "scale-up"}, "physical": {"kind": "busy"}})
            )
            with self.assertRaisesRegex(ValueError, "observed action"):
                write_report([source], root / "report")

    def test_failed_or_unavailable_comparison_is_visible_and_round_trips(self):
        """Missing native results remain explicit rather than becoming zero-valued predictions."""
        saved = {
            "context": {"candidate": "scale-down", "run_id": "run", "selected_worker": "worker-a"},
            "physical": {
                "kind": "busy",
                "status": "inconclusive",
                "initial_active_pod_uids": ["pod"],
                "drained_initial_pod_uids": [],
                "new_assignments_after_ack": [],
                "boundary_assignment_uids": ["ambiguous"],
            },
            "comparison": None,
            "native_unavailable_reason": "incomplete native output",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "comparison.json"
            source.write_text(json.dumps(saved))
            first = write_report([source], root / "first")
            source.unlink()
            second = write_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(first, second)
            self.assertIsNone(first["comparisons"][0]["comparison"])
            saved["comparison"] = {
                "grid_seconds": [0, 120],
                "observed_curve": [0, 0],
                "predicted_curve": [0, 1],
                "completion_curve_mae": None,
                "coverage_complete": False,
                "initial_membership": {"complete": False},
                "model_exhausted": [],
                "unmatched_observed_backlog": [],
                "observed_censored_uids": ["job"],
            }
            source.write_text(json.dumps(saved))
            incomplete = write_report([source], root / "incomplete")
            self.assertIsNone(incomplete["comparisons"][0]["comparison"]["completion_curve_mae"])


if __name__ == "__main__":
    unittest.main()
