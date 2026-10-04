"""Closed-loop prediction comparisons use causal cohorts and label subsequent control."""

import importlib
import json
from pathlib import Path
import tempfile
import unittest

from forecast_trace import iso


class LoopDiagnosticTests(unittest.TestCase):
    """Hand-computed response and arrival evidence keeps execution identity explicit."""

    def test_actual_candidate_and_original_creation_are_retained(self):
        """A shadow down proposal compares unchanged capacity and original-creation response."""
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_diagnostics"))
        module = importlib.import_module("closed_loop_diagnostics")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast = dict(
                status="ready",
                cutoff=iso(100000),
                settings=dict(horizon_seconds=60),
                predictions=[dict(mean_count=2)],
                scenario_job_counts=[1, 2, 3],
            )
            case = dict(tasks=[dict(metadata=dict(cohort="backlog", kubernetes_job_uid="old"))])
            scores = [
                dict(
                    candidate="unchanged",
                    scenarios=[dict(complete=True, responses_seconds=[10, 20])],
                )
            ]
            for name, data in (
                ("forecast/forecast.json", forecast),
                ("suite/experiments/unchanged/0000/case.json", case),
                ("scores.json", scores),
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
            observed = [
                dict(uid="old", creation_ms=90000, job_finish_ms=120000, status="Complete"),
                dict(uid="future", creation_ms=110000, job_finish_ms=140000, status="Complete"),
            ]
            cycle = dict(
                tick=1,
                outcome="shadow",
                proposal=dict(action="scale-down"),
                action_observed=False,
                decision_age_seconds=2,
                forecast_valid=True,
            )
            result = module.cycle_diagnostic(root, cycle, observed, 200000, 800000)
            self.assertEqual(result["actual_candidate"], "unchanged")
            self.assertEqual(result["observed_future_jobs"], 1)
            self.assertEqual(result["predicted_mean_future_jobs"], 2)
            self.assertEqual(result["observed_cohort_response_p95_seconds"], 30)
            self.assertAlmostEqual(result["predicted_response_p95_seconds"][0], 21.5)
            cycle.update(outcome="vetoed_or_failed", actions=[dict(action="scale-down")])
            result = module.cycle_diagnostic(root, cycle, observed, 200000, 800000)
            self.assertIsNone(result["actual_candidate"])
            self.assertEqual(result["predicted_response_p95_seconds"], [])
            cycle.update(
                outcome="acknowledged",
                action_observed=True,
                forecast_valid=False,
                proposal=dict(action="scale-down", fallback=True),
            )
            result = module.cycle_diagnostic(root, cycle, observed, 200000, 800000)
            self.assertIsNone(result["actual_candidate"])
            self.assertEqual(result["predicted_response_p95_seconds"], [])

    def test_cancelled_proposal_retains_all_counterfactual_candidates(self):
        """Cancellation cannot erase alternatives or turn a prediction into physical validation."""
        module = importlib.import_module("closed_loop_diagnostics")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast = dict(
                status="ready",
                cutoff=iso(100000),
                settings=dict(horizon_seconds=60, scenarios=3),
                predictions=[dict(mean_count=2)],
                scenario_job_counts=[2, 2, 2],
            )
            scores = [
                dict(
                    candidate=name,
                    selected_worker="worker-a",
                    scenarios=[
                        dict(
                            complete=True,
                            cohort_size=2,
                            responses_seconds=[10, late],
                            allocated_core_seconds=cost,
                        )
                        for _ in range(3)
                    ],
                )
                for name, late, cost in (("unchanged", 100, 120), ("scale-down", 120, 90))
            ]
            for name, data in (("forecast/forecast.json", forecast), ("scores.json", scores)):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
            cycle = dict(
                tick=2,
                outcome="vetoed_or_failed",
                decision_age_seconds=2,
                proposal=dict(action="scale-down"),
                forecast_valid=True,
            )
            result = module.cycle_diagnostic(root, cycle, [], 200000, 800000)
            self.assertIsNone(result["actual_candidate"])
            alternatives = result["candidate_predictions"]
            self.assertEqual(
                [row["candidate"] for row in alternatives], ["unchanged", "scale-down"]
            )
            self.assertTrue(all(row["valid"] for row in alternatives))
            self.assertEqual(alternatives[0]["worst_late_fraction"], 0)
            self.assertEqual(alternatives[1]["worst_late_fraction"], 0.5)
            self.assertEqual(alternatives[1]["allocated_core_seconds"], 90)
            self.assertAlmostEqual(alternatives[1]["response_p95_seconds"][0], 116.5)
