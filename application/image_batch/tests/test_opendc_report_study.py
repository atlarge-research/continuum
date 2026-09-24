"""Study reports preserve a frozen choice and explicit observed comparison cohorts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Tests import the checked-out report implementation.
# pylint: disable=wrong-import-position
from opendc_report_study import study_panels
from opendc_report import write_report

# pylint: enable=wrong-import-position


def evidence():
    """Build a frozen choice and one paired held-out cutoff.

    Returns:
        dict: Minimal numerical study payload with full curve values.
    """
    window = {
        "grid_seconds": [0, 60, 120],
        "observed_curve": [0, 2, 3],
        "completion_median": [0, 1, 3],
        "completion_min": [0, 0, 2],
        "completion_max": [0, 2, 4],
        "coverage_complete": True,
        "completion_curve_mae": 1 / 3,
    }
    forecast = {
        "arrival_source": "forecast",
        "cutoff_index": 0,
        "cutoff_ms": 1000,
        "horizon_seconds": 60,
        "scenarios": 3,
        "seed": 123,
        "windows": {"120": window},
    }
    known = copy.deepcopy(forecast)
    known.update(arrival_source="known-arrival", scenarios=1)
    return {
        "schema_version": "opendc-study-evidence-v1",
        "selection": {"selected": {"horizon_seconds": 60, "scenarios": 3}, "scenario_seed": 123},
        "results": [
            {
                "run_id": "held",
                "split": "held-out",
                "workload_seed": 48,
                "groups": [forecast, known],
            }
        ],
    }


class StudyReportTests(unittest.TestCase):
    """Held-out plots never silently choose or refit a configuration."""

    def test_observed_cohort_and_grid_must_match(self):
        """A known-arrival curve cannot be compared against different observations."""
        saved = evidence()
        saved["results"][0]["groups"][1]["windows"]["120"]["observed_curve"][-1] = 5
        with self.assertRaisesRegex(ValueError, "observed cohort"):
            study_panels(saved)

    def test_held_out_cannot_hide_extra_configurations(self):
        """Only the declared frozen configuration may be evaluated in the held-out study."""
        saved = evidence()
        extra = copy.deepcopy(saved["results"][0]["groups"][0])
        extra["scenarios"] = 10
        saved["results"][0]["groups"].append(extra)
        with self.assertRaisesRegex(ValueError, "frozen"):
            study_panels(saved)

    def test_study_survives_offline_report_round_trip(self):
        """Full study evidence remains available after source files are removed."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "study.json"
            source.write_text(json.dumps(evidence()))
            first = write_report([source], root / "first")
            source.unlink()
            second = write_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(first["studies"], second["studies"])
            self.assertEqual(first["section_order"], ["study"])


if __name__ == "__main__":
    unittest.main()
