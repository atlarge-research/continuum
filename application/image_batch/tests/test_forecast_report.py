"""Accuracy keeps forecast-relative leads, coverage gaps and observed zeros distinct."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from forecast_report import (
    cumulative_counts,
    horizon_summary,
    lead_summary,
    prepare_forecasts,
    rebin_predictions,
)
from forecast_trace import iso
from forecast_workload import run_once
from test_forecast_workload import BASE, fixture, save_rows, settings


class ForecastReportTests(unittest.TestCase):
    def test_future_total_error_allows_bin_errors_to_cancel_and_requires_full_prefix(
        self,
    ):
        forecast = {
            "cutoff": iso(BASE),
            "predictions": [
                {
                    "start_ms": BASE + i * 5000,
                    "mean_count": mean,
                    "reference_mean_count": 1,
                }
                for i, mean in enumerate((1, 2, 3, 4))
            ],
        }
        scores = [
            {
                "forecast_cutoff": iso(BASE),
                "bin_start_ms": BASE + i * 5000,
                "observed_count": count,
            }
            for i, count in enumerate((3, 0, 1, 1))
        ]
        summary, totals = horizon_summary([forecast], scores, 5)
        self.assertEqual(summary[0]["horizon_seconds"], 10)
        self.assertEqual(summary[0]["cyclic"]["mean_absolute_count_error"], 0)
        self.assertEqual(summary[0]["constant"]["mean_absolute_count_error"], 1)
        self.assertEqual(totals[0]["observed_count"], 3)
        # Missing a bin must stop the running total, even when later bins exist.
        del scores[1]
        cumulative = cumulative_counts(forecast, scores, 5)
        self.assertEqual(cumulative["observed_count"], [0, 3, None, None, None])
        summary, totals = horizon_summary([forecast], scores, 5)
        self.assertEqual(totals, [])
        self.assertTrue(all(row["eligible_forecasts"] == 0 for row in summary))
        self.assertTrue(
            all(row["cyclic"]["mean_absolute_count_error"] is None for row in summary)
        )

    def test_rate_rebinning_matches_absolute_windows_and_omits_partial_windows(self):
        predictions = [
            {"start_ms": start, "mean_count": mean}
            for start, mean in ((1000, 1), (6000, 3), (11000, 5))
        ]
        bins = rebin_predictions(predictions, 5, [0, 3000, 6000, 9000], 10)
        self.assertEqual([b["start_ms"] for b in bins], [3000, 6000])
        self.assertAlmostEqual(bins[0]["mean_count"], 5.6)
        self.assertAlmostEqual(bins[0]["rate"], 0.56)
        self.assertEqual(bins[1]["mean_count"], 8)

    def test_lead_error_groups_issue_relative_bins_with_unequal_coverage(self):
        scores = []
        for issued, lead, observed, mean in [
            (1001, 0, 3, 1),
            (11002, 0, 0, 1),
            (1001, 5000, 2, 2),
        ]:
            value = {
                "mean_count": mean,
                "absolute_error": abs(observed - mean),
                "covered_90": observed < 3,
            }
            scores.append(
                {
                    "forecast_cutoff": iso(BASE + issued),
                    "bin_start_ms": BASE + issued + lead,
                    "observed_count": observed,
                    "cyclic": value,
                    "constant": value,
                }
            )
        evaluation = {"settings": {"bin_seconds": 5}, "scores": scores}
        result = lead_summary(evaluation)
        self.assertEqual([r["lead_end_seconds"] for r in result], [5, 10])
        self.assertEqual([r["scored_bins"] for r in result], [2, 1])
        self.assertEqual(result[0]["cyclic"]["mean_absolute_count_error"], 1.5)
        self.assertEqual(result[0]["cyclic"]["predictive_coverage_90"], 0.5)
        self.assertEqual(result[1]["cyclic"]["mean_absolute_count_error"], 0)
        invalid = copy.deepcopy(evaluation)
        invalid["scores"][0]["bin_start_ms"] += 1
        with self.assertRaisesRegex(ValueError, "forecast-relative"):
            lead_summary(invalid)

    def test_capture_gaps_and_shutdown_are_excluded_but_observed_zeros_are_scored(self):
        rows = fixture()
        rows["cluster-state.jsonl"] = [
            r
            for r in rows["cluster-state.jsonl"]
            if not iso(BASE + 46000) <= r["timestamp"] < iso(BASE + 50000)
        ]
        rows["observer-events.jsonl"].append(
            {
                "schema_version": 1,
                "timestamp": iso(BASE + 42001),
                "event_type": "job.observed",
                "details": {
                    "kubernetes_job_uid": "future-job",
                    "workload_run_id": "test",
                    "creation_time": iso(BASE + 42000),
                },
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root / "inputs", rows)
            run_once(root / "inputs", root / "forecast", BASE + 40000, settings())
            result = prepare_forecasts(
                root / "forecast", root / "inputs", iso(BASE + 55000)
            )
            self.assertEqual(
                [s["observed_count"] for s in result["evaluation"]["scores"]], [1, 0]
            )
            self.assertEqual(
                [r["lead_end_seconds"] for r in result["lead_summary"]], [5, 15]
            )
            self.assertEqual(result["evaluation"]["uncovered_or_future_bins"], 2)
            actual = {b["start_ms"] - BASE: b for b in result["actual_bins"]}
            self.assertFalse(actual[45000]["eligible"])
            self.assertTrue(actual[50000]["eligible"])
            self.assertEqual(actual[50000]["count"], 0)
            self.assertFalse(result["examples_have_full_coverage"])
            self.assertEqual(result["horizon_summary"][0]["eligible_forecasts"], 0)
            with self.assertRaisesRegex(ValueError, "no covered subsequent"):
                prepare_forecasts(root / "forecast", root / "inputs", iso(BASE + 40000))


if __name__ == "__main__":
    unittest.main()
