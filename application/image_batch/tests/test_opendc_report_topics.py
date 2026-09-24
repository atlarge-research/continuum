"""Topic summaries retain run weights, held-out separation and measurement contracts."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# pylint: disable=wrong-import-position
import matplotlib.pyplot as plt
from reporting.topics import arrival_summary
from reporting.physical import _ecdf
from reporting.study import render_completion
from reporting.arrivals import _accuracy_page
from reporting.study_evidence import study_panels
from test_opendc_report_study import evidence

# pylint: enable=wrong-import-position


def arrival_evidence(run_id, errors):
    """Make per-cutoff count errors with intentionally unequal run sizes.

    Args:
        run_id (str): Independent workload identifier.
        errors (list[float]): Absolute periodic count errors.

    Returns:
        dict: Minimal saved arrival report with a common measurement contract.
    """
    return {
        "evaluation": {
            "settings": {
                "run_id": run_id,
                "bin_seconds": 5,
                "period_seconds": 240,
                "horizon_seconds": 60,
            }
        },
        "horizon_scores": [
            {
                "horizon_seconds": 60,
                "forecast_cutoff": str(index),
                "observed_count": 10,
                "cyclic": {"absolute_error": error},
                "constant": {"absolute_error": 4},
            }
            for index, error in enumerate(errors)
        ],
        "horizon_summary": [
            {"horizon_seconds": 60, "eligible_forecasts": len(errors), "excluded_forecasts": 0}
        ],
    }


class FigureSink:
    """Capture rendered panel titles before the figure is closed."""

    def __init__(self):
        """Start with no saved plots."""
        self.titles = []
        self.y_limits = []

    def savefig(self, figure):
        """Retain the visible conclusions from a completed page.

        Args:
            figure (Figure): Rendered report slide.
        """
        self.titles.extend(axis.get_title() for axis in figure.axes)
        self.y_limits.extend(axis.get_ylim() for axis in figure.axes)


class TopicSummaryTests(unittest.TestCase):
    """A large run or a held-out run cannot change the selection-run mean."""

    def setUp(self):
        """Use two selection runs and one deliberately very inaccurate held-out run."""
        self.reports = [
            arrival_evidence("a", [1]),
            arrival_evidence("b", [3, 3, 3]),
            arrival_evidence("c", [100]),
        ]
        self.roles = {
            "a": {"split": "validation", "workload_seed": 46},
            "b": {"split": "validation", "workload_seed": 47},
            "c": {"split": "held-out", "workload_seed": 48},
        }

    def test_equal_run_weights_and_held_out_isolation(self):
        """Pooling forecast rows would incorrectly return 2.5 rather than 2."""
        rows = arrival_summary(self.reports, self.roles)
        selected = next(row for row in rows if row["split"] == "validation")
        held = next(row for row in rows if row["split"] == "held-out")
        self.assertEqual(selected["cyclic_mean"], 2)
        self.assertEqual(selected["cyclic_range"], [1, 3])
        self.assertEqual(selected["eligible_forecasts"], 4)
        self.assertEqual(selected["independent_runs"], 2)
        self.assertEqual(held["cyclic_mean"], 100)

    def test_duplicate_run_cannot_gain_weight(self):
        """Supplying the same payload twice must fail rather than count a repetition."""
        with self.assertRaisesRegex(ValueError, "duplicate"):
            arrival_summary(self.reports + [self.reports[0]], self.roles)

    def test_different_periods_cannot_be_aggregated(self):
        """Incompatible workload periods must not be hidden by a pooled summary."""
        changed = copy.deepcopy(self.reports)
        changed[1]["evaluation"]["settings"]["period_seconds"] = 120
        with self.assertRaisesRegex(ValueError, "settings"):
            arrival_summary(changed, self.roles)

    def test_fully_excluded_run_keeps_its_coverage_denominator(self):
        """Unusable forecasts remain visible rather than disappearing from the report."""
        self.reports[1]["horizon_scores"] = []
        self.reports[1]["horizon_summary"][0].update(eligible_forecasts=0, excluded_forecasts=3)
        rows = arrival_summary(self.reports, self.roles)
        selected = next(row for row in rows if row["split"] == "validation")
        self.assertEqual(selected["excluded_forecasts"], 3)
        self.assertEqual(selected["independent_runs"], 2)
        self.assertEqual(selected["scored_runs"], 1)
        self.assertEqual(selected["cyclic_mean"], 1)

    def test_unscored_split_keeps_missing_error_not_zero(self):
        """No observed score is missing evidence, never a perfect forecast."""
        self.reports[2]["horizon_scores"] = []
        self.reports[2]["horizon_summary"][0].update(eligible_forecasts=0, excluded_forecasts=4)
        held = next(
            r for r in arrival_summary(self.reports, self.roles) if r["split"] == "held-out"
        )
        self.assertIsNone(held["cyclic_mean"])
        self.assertEqual(held["excluded_forecasts"], 4)
        sink = FigureSink()
        _accuracy_page(sink, arrival_summary(self.reports, self.roles))
        self.assertTrue(any("no eligible forecasts" in title for title in sink.titles))

    def test_known_arrival_overprediction_is_not_clipped(self):
        """The common completion scale must include all three plotted sources."""
        saved = evidence()
        saved["results"][0]["groups"][1]["windows"]["120"]["completion_median"][-1] = 50
        sink = FigureSink()
        render_completion(sink, study_panels(saved), {"held": {"workload_seed": 48}})
        self.assertGreaterEqual(sink.y_limits[0][1], 50)

    def test_incomplete_completion_coverage_is_visible(self):
        """A valid unavailable MAE must render as missing coverage, not crash or claim accuracy."""
        saved = evidence()
        for group in saved["results"][0]["groups"]:
            group["windows"]["120"].update(coverage_complete=False, completion_curve_mae=None)
        sink = FigureSink()
        render_completion(sink, study_panels(saved), {"held": {"workload_seed": 48}})
        self.assertTrue(any("Incomplete coverage" in title for title in sink.titles))
        self.assertFalse(any("forecasts too" in title for title in sink.titles))

    def test_later_run_distribution_tail_remains_visible(self):
        """The first run must not freeze axis limits and clip a later run's tail."""
        figure, axis = plt.subplots()
        try:
            _ecdf(axis, [0.5, 1], "First", "blue")
            _ecdf(axis, [0.5, 11], "Second", "orange")
            self.assertGreaterEqual(axis.get_xlim()[1], 11)
        finally:
            plt.close(figure)

    def test_missing_role_cannot_be_assumed_to_be_validation(self):
        """Unknown run identities cannot silently become selection evidence."""
        del self.roles["b"]
        with self.assertRaisesRegex(ValueError, "role"):
            arrival_summary(self.reports, self.roles)


if __name__ == "__main__":
    unittest.main()
