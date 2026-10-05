"""Versioned native response clocks avoid redundant decision-age scoring."""

import copy
import unittest

from closed_loop_diagnostics import candidate_predictions
from closed_loop_policy import select_action, summarize_candidate
from closed_loop_runner import score_cases
from opendc_acquisition import apply_acquisition
from test_closed_loop_policy import candidate
import test_closed_loop_runner as runner_fixtures
import test_opendc_acquisition as acquisition_fixtures


TIMING_CONTRACT = "original_creation_with_modeled_action_offsets_v1"


class FinalResponseTimingTests(unittest.TestCase):
    """Preserve modeled waiting and legacy behavior while rejecting uncovered clocks."""

    def marked(self, action="unchanged", response=110, cost=720):
        """Build a complete score with an explicit modeled decision allowance.

        Args:
            action (str): Capacity alternative.
            response (float): Reconstructed original-creation response seconds.
            cost (float): Modeled allocated application core-seconds.

        Returns:
            dict: Shared-future score carrying the new clock contract.
        """
        result = candidate(action, cost, response=response)
        result.update(
            response_time_contract=TIMING_CONTRACT,
            modeled_request_delay_seconds=60,
        )
        return result

    def test_covered_computation_age_does_not_change_response_guardrail_or_choice(self):
        """A110-second response stays feasible at every covered decision age."""
        scores = [self.marked(), self.marked("scale-up", 60, 1080)]
        for age in (0, 15, 60):
            with self.subTest(age=age):
                result = select_action(
                    scores, {}, now_seconds=1000, decision_age=age, age_budget_seconds=60
                )
                self.assertEqual(result["action"], "unchanged")
                self.assertTrue(result["guardrail_feasible"])
                self.assertEqual(result["scores"][0]["worst_late_fraction"], 0)
        self.assertEqual(
            select_action(scores, {}, now_seconds=1000, decision_age=61, age_budget_seconds=60)[
                "reason"
            ],
            "decision_stale",
        )

    def test_diagnostics_and_counterfactual_summary_share_uninflated_responses(self):
        """Diagnostic p95 and policy metrics use the same original-creation clocks."""
        predictions = candidate_predictions([self.marked()], 45, scenarios=3, deadline_seconds=120)
        self.assertEqual(predictions[0]["response_p95_seconds"], [110, 110, 110])
        self.assertEqual(predictions[0]["worst_late_fraction"], 0)

    def test_legacy_zero_offset_scores_keep_the_existing_latency_margin(self):
        """Unmarked saved scores remain numerically compatible."""
        result = summarize_candidate(candidate("unchanged", 720, response=110), 15)
        self.assertEqual(result["worst_late_fraction"], 1)
        self.assertEqual(result["mean_tardiness_seconds"], 5)
        fixtures = acquisition_fixtures.AcquisitionModelTests()
        case = apply_acquisition(fixtures.case(), dict(fixtures.contract(), acquisition_seconds=0))
        self.assertNotIn("response_time_contract", case)

    def test_uncovered_or_unknown_timing_contract_cannot_be_a_valid_alternative(self):
        """Invalid timing provenance cannot obtain cheap feasible scores."""
        for change in (
            {"response_time_contract": "unknown"},
            {"modeled_request_delay_seconds": 10},
            {"modeled_request_delay_seconds": True},
            {"modeled_request_delay_seconds": float("nan")},
        ):
            score = dict(self.marked(), **change)
            with self.subTest(change=change):
                self.assertFalse(summarize_candidate(score, 15)["valid"])

    def test_original_backlog_waiting_and_future_birth_are_reconstructed_once(self):
        """Backlog includes20s old waiting; a future born30s later has35s response."""
        rows = runner_fixtures.RunnerScoreTests().rows()
        for row in rows:
            case = row["case"]
            case.update(response_time_contract=TIMING_CONTRACT)
            case["acquisition"] = {"modeled_request_delay_seconds": 60}
            case["tasks"].append(
                {
                    "task": {"id": 2, "submission_time": 30000},
                    "metadata": {"original_creation_ms": 130000, "cohort": "future"},
                }
            )
            row["validation"]["tasks"].append(
                {"task_id": 2, "finish_time": 65000, "host_name": "w1"}
            )
        scores = score_cases(rows)
        self.assertEqual(scores[0]["response_time_contract"], TIMING_CONTRACT)
        self.assertEqual(scores[0]["scenarios"][0]["responses_seconds"], [50, 35])
        predictions = candidate_predictions(scores, 20, scenarios=3, deadline_seconds=120)
        self.assertEqual(predictions[0]["response_p95_seconds"], [49.25] * 3)

    def test_new_delayed_case_marks_the_contract_but_zero_offsets_do_not(self):
        """Only newly prepared cases explicitly covering computation receive the marker."""
        fixtures = acquisition_fixtures.AcquisitionModelTests()
        settings = dict(
            fixtures.contract(),
            modeled_request_delay_seconds=60,
            modeled_admission_margin_seconds=30,
        )
        case = apply_acquisition(fixtures.case(), settings)
        self.assertEqual(case["response_time_contract"], TIMING_CONTRACT)
        legacy = apply_acquisition(fixtures.case(), fixtures.contract())
        self.assertNotIn("response_time_contract", legacy)

    def test_mixed_timing_provenance_is_rejected_across_the_native_matrix(self):
        """Actions sharing a cohort must also share their scoring clock contract."""
        rows = copy.deepcopy(runner_fixtures.RunnerScoreTests().rows())
        rows[0]["case"].update(response_time_contract=TIMING_CONTRACT)
        rows[0]["case"]["acquisition"] = {"modeled_request_delay_seconds": 60}
        with self.assertRaisesRegex(ValueError, "timing"):
            score_cases(rows)


if __name__ == "__main__":
    unittest.main()
