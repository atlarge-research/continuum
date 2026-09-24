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
from reporting import controlled
from reporting.controlled import write_report
from reporting.assembly import write_report as combined_report
from test_opendc_report import validation_result

# pylint: enable=wrong-import-position


class ControlledReportTests(unittest.TestCase):
    """Saved numerical results must redraw offline and retain action identity."""

    def test_lifecycle_render_keeps_missing_start_unknown_and_clips_followup(self):
        """Incomplete timestamps cannot imply queuing or extend bars past follow-up."""
        # Inspect the private renderer's artists to test scientific interval semantics.
        # pylint: disable=protected-access
        figure, axis = controlled.plt.subplots()
        try:
            controlled._lifecycle_bar(axis, 0, [1, None, 16], 12, "blue")
            self.assertFalse(any(line.get_color() == "#bfbfbf" for line in axis.lines))
            self.assertFalse(axis.patches)
            self.assertTrue(any("unavailable" in text.get_text() for text in axis.texts))
            axis.clear()
            controlled._lifecycle_bar(axis, 0, [1, 5, None], 12, "blue")
            marker = next(line for line in axis.lines if line.get_marker() == "x")
            self.assertEqual(list(marker.get_xdata()), [5])
            axis.clear()
            controlled._lifecycle_bar(axis, 0, [1, 5, 16], 12, "blue")
            self.assertTrue(all(max(line.get_xdata()) <= 12 for line in axis.lines))
            self.assertTrue(all(patch.get_x() + patch.get_width() <= 12 for patch in axis.patches))
            self.assertTrue(all(patch.get_height() == 1 for patch in axis.patches))
            self.assertTrue(any(line.get_marker() == ">" for line in axis.lines))
        finally:
            controlled.plt.close(figure)

    def test_lifecycle_preserves_arrivals_remainders_and_unrepresented_work(self):
        """Timeline rows include censored/exhausted work without inventing model history."""
        observations = [
            {
                "uid": "new",
                "cohort": "future",
                "creation_ms": 11000,
                "start_ms": 12000,
                "finish_ms": 16000,
            },
            {
                "uid": "old",
                "cohort": "backlog",
                "creation_ms": 1000,
                "start_ms": 2000,
                "finish_ms": 13000,
            },
        ]
        saved = {
            "context": {"observed_action_interval_seconds": [1, 3]},
            "comparison": {
                "cutoff_ms": 10000,
                "window_seconds": 5,
                "observations": observations,
                "tasks": [
                    {
                        "uid": "new",
                        "cohort": "future",
                        "original_creation_ms": 11000,
                        "predicted_finish_ms": 20000,
                        "modeled_duration_seconds": 4,
                    },
                    {
                        "uid": "old",
                        "cohort": "backlog",
                        "original_creation_ms": 1000,
                        "predicted_finish_ms": 14000,
                        "modeled_duration_seconds": 4,
                    },
                ],
                "model_exhausted": [
                    {"uid": "exhausted", "creation_ms": 0, "start_ms": 1000, "finish_ms": 12000}
                ],
                "matched_completed_pairs": [],
            },
        }
        before = json.dumps(saved, sort_keys=True)
        rows = controlled.lifecycle_rows(saved)
        self.assertEqual([r["uid"] for r in rows], ["exhausted", "old", "new"])
        self.assertEqual(rows[0]["prediction_status"], "Model exhausted")
        self.assertIsNone(rows[0]["predicted"])
        self.assertEqual(rows[1]["predicted"], [-2, -2, 2])
        self.assertEqual(rows[1]["observed"], [-11, -10, 1])
        self.assertEqual(rows[2]["observed"], [-1, 0, 4])
        self.assertEqual(rows[2]["predicted"], [-1, 4, 8])
        self.assertEqual(rows[2]["window_end"], 3)
        self.assertEqual(before, json.dumps(saved, sort_keys=True))

    def test_lifecycle_retains_missing_outcomes_and_matched_future_identity(self):
        """Unknown finishes stay unknown and only matched futures receive the MAE marker."""
        saved = {
            "context": {},
            "comparison": {
                "cutoff_ms": 0,
                "window_seconds": 120,
                "tasks": [{"uid": "missing", "cohort": "future", "original_creation_ms": 1000}],
                "observations": [
                    {
                        "uid": "missing",
                        "cohort": "future",
                        "creation_ms": 1000,
                        "start_ms": None,
                        "finish_ms": None,
                        "censored_through_ms": 9000,
                    }
                ],
                "matched_completed_pairs": [{"uid": "missing"}],
            },
        }
        row = controlled.lifecycle_rows(saved)[0]
        self.assertEqual(row["observed"], [1, None, None])
        self.assertEqual(row["observed_through"], 9)
        self.assertIsNone(row["predicted"])
        self.assertTrue(row["matched_future"])
        self.assertEqual(controlled.lifecycle_rows({}), [])

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
            with patch("reporting.assembly.render_controlled_pages") as render:
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
