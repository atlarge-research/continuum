"""Controlled reports pair predictions only with the physical action actually performed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Tests exercise the checked-out report module.
# pylint: disable=wrong-import-position
from opendc_report_controlled import write_report

# pylint: enable=wrong-import-position


class ControlledReportTests(unittest.TestCase):
    """Saved numerical results must redraw offline and retain action identity."""

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


if __name__ == "__main__":
    unittest.main()
