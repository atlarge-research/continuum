"""Known-arrival comparisons retain run identity and matched observation cohorts."""
import copy
import json
import re
from pathlib import Path
import sys
import unittest
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Discovery uses the repository source path rather than an installed package.
# pylint: disable=wrong-import-position
from opendc_report_replay import replay_panels
from opendc_report import write_report

# pylint: enable=wrong-import-position


def replay_fixture():
    """Return two explicitly labeled engines on one identical observed cohort.

    Returns:
        list[dict]: Minimal old/new unchanged replay evidence.
    """
    group = {
        "arrival_source": "known-arrival",
        "cutoff_index": 0,
        "cutoff_ms": 1000,
        "horizon_seconds": 60,
        "seed": 123,
        "scenarios": 1,
        "windows": {
            "120": {
                "grid_seconds": [0, 120],
                "observed_curve": [0, 2],
                "completion_median": [0, 1],
                "coverage_complete": True,
            }
        },
    }
    case = {
        "arrival_source": "known-arrival",
        "cutoff_index": 0,
        "horizon_seconds": 60,
        "seed": 123,
        "comparisons": {"120": {"observations": [{"uid": "a"}, {"uid": "b"}]}},
    }
    result = {"run_id": "run-a", "groups": [group], "cases": [case]}
    return [{"label": "old", "result": result}, {"label": "new", "result": copy.deepcopy(result)}]


class ReplayReportTests(unittest.TestCase):
    """Reject apparently comparable curves drawn from different physical cohorts."""

    def test_panels_pair_exact_run_and_cutoff(self):
        """Same offsets from different runs must never become one comparison."""
        entries = replay_fixture()
        self.assertEqual(len(replay_panels(entries)), 1)
        entries[1]["result"]["run_id"] = "run-b"
        self.assertEqual(len(replay_panels(entries)), 2)

    def test_equal_curves_do_not_hide_different_observed_identities(self):
        """Counts alone cannot establish identical cohorts."""
        entries = replay_fixture()
        entries[1]["result"]["cases"][0]["comparisons"]["120"]["observations"][1]["uid"] = "c"
        with self.assertRaisesRegex(ValueError, "cohort"):
            replay_panels(entries)

    def test_missing_engine_member_is_explicit(self):
        """Missing cases remain visible instead of changing comparison denominators."""
        entries = replay_fixture()
        entries[1]["result"]["groups"] = []
        entries[1]["result"]["cases"] = []
        self.assertEqual(replay_panels(entries)[0]["unavailable_labels"], ["new"])

    def test_replay_only_report_regenerates_offline(self):
        """Saved old/new replay evidence needs neither live observations nor native results."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "metrics.json"
            source.write_text(json.dumps({"results": [], "replay_reports": replay_fixture()}))
            audit = write_report([source], root / "first")
            self.assertEqual(audit["section_order"], ["unchanged-replay"])
            self.assertEqual(
                len(re.findall(rb"/Type /Page\b", (root / "first/report.pdf").read_bytes())), 2
            )
            source.unlink()
            repeated = write_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(repeated["replay"], audit["replay"])


if __name__ == "__main__":
    unittest.main()
