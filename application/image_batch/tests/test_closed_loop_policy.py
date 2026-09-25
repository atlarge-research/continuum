"""Action choices require complete forecasts, response guardrails and hysteresis."""

import copy
import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def candidate(action, cost, response=60, *, count=20, complete=True, worker=None):
    """Make three independent score records with explicit represented cohort size.

    Args:
        action (str): Candidate action name.
        cost (float): Application core-seconds over the common evaluation window.
        response (float): Original-creation-to-finish response before decision latency.
        count (int): Represented cohort cardinality.
        complete (bool): Whether native execution covers the full cohort.
        worker (str or None): Selected target node.

    Returns:
        dict: Candidate input to the production selector.
    """
    return {
        "candidate": action,
        "selected_worker": worker,
        "scenarios": [
            {
                "responses_seconds": [response] * count,
                "cohort_size": count,
                "allocated_core_seconds": cost,
                "complete": complete,
            }
            for _ in range(3)
        ],
    }


class PolicyTests(unittest.TestCase):
    """Hand-derived choices distinguish a valid action from a useful one."""

    def choose(self, candidates, *, state=None, age=0, now=1000):
        """Call the real selector with the approved initial settings.

        Args:
            candidates (list[dict]): Candidate score records.
            state (dict or None): Persisted controller history.
            age (float): Cutoff-to-decision seconds.
            now (float): Current epoch seconds.

        Returns:
            dict: Selected action, explanation and next proposal history.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_policy"), "policy is missing")
        module = importlib.import_module("closed_loop_policy")
        return module.select_action(candidates, state or {}, now_seconds=now, decision_age=age)

    def test_down_needs_two_consecutive_wins_and_ten_percent_savings(self):
        """A single attractive forecast cannot immediately reduce capacity."""
        candidates = [candidate("unchanged", 1080), candidate("scale-down", 720, worker="w2")]
        first = self.choose(candidates)
        self.assertEqual(first["action"], "unchanged")
        second = self.choose(candidates, state=first["state"], now=1060)
        self.assertEqual(second["action"], "scale-down")
        self.assertEqual(second["selected_worker"], "w2")
        low_saving = [candidate("unchanged", 1080), candidate("scale-down", 1000, worker="w2")]
        self.assertEqual(self.choose(low_saving, state=first["state"])["action"], "unchanged")

    def test_one_bad_future_prevents_down_even_when_mean_response_is_good(self):
        """Every sampled future must satisfy the response guardrail."""
        down = candidate("scale-down", 720, worker="w2")
        down["scenarios"][1]["responses_seconds"][:2] = [121, 121]
        result = self.choose(
            [candidate("unchanged", 1080), down], state={"down_worker": "w2", "down_wins": 1}
        )
        self.assertEqual(result["action"], "unchanged")

    def test_decision_latency_is_included_and_old_decisions_cannot_actuate(self):
        """A forecast near its deadline cannot ignore execution latency."""
        candidates = [candidate("unchanged", 720, response=110), candidate("scale-up", 1080)]
        self.assertEqual(self.choose(candidates, age=15)["action"], "scale-up")
        self.assertEqual(self.choose(candidates, age=31)["action"], "unchanged")

    def test_partial_or_missing_scenarios_cannot_win_on_cheap_totals(self):
        """Successful partial results must not establish a winning scale-down action."""
        for down in [
            candidate("scale-down", 1, complete=False, worker="w2"),
            candidate("scale-down", 1, worker="w2"),
        ]:
            if down["scenarios"][0]["complete"]:
                down["scenarios"].pop()
            result = self.choose(
                [candidate("unchanged", 1080), down], state={"down_worker": "w2", "down_wins": 1}
            )
            self.assertEqual(result["action"], "unchanged")

    def test_infeasible_guardrail_allows_only_an_improving_scale_up(self):
        """An infeasible target is reported even when extra capacity reduces tardiness."""
        hold = candidate("unchanged", 720, response=180)
        up = candidate("scale-up", 1080, response=140)
        result = self.choose([hold, up])
        self.assertEqual(result["action"], "scale-up")
        self.assertFalse(result["guardrail_feasible"])
        up["scenarios"] = copy.deepcopy(hold["scenarios"])
        self.assertEqual(self.choose([hold, up])["action"], "unchanged")

    def test_cooldown_and_changed_down_target_reset_the_streak(self):
        """Proposal history cannot bypass cooldown or transfer a win to another worker."""
        candidates = [candidate("unchanged", 1080), candidate("scale-down", 720, worker="w2")]
        state = {"last_action_at": 950, "down_worker": "w2", "down_wins": 1}
        before = copy.deepcopy(state)
        result = self.choose(candidates, state=state)
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(state, before)
        changed = self.choose(candidates, state={"down_worker": "w1", "down_wins": 1})
        self.assertEqual(changed["action"], "unchanged")
        self.assertEqual(changed["state"]["down_wins"], 1)

    def test_empty_cohort_is_valid_but_incomplete_identity_count_is_not(self):
        """Zero arrivals differ from missing responses for represented Jobs."""
        hold = candidate("unchanged", 1080, count=0)
        down = candidate("scale-down", 720, count=0, worker="w2")
        state = {"down_worker": "w2", "down_wins": 1}
        self.assertEqual(self.choose([hold, down], state=state)["action"], "scale-down")
        down["scenarios"][0]["cohort_size"] = 1
        self.assertEqual(self.choose([hold, down], state=state)["action"], "unchanged")


if __name__ == "__main__":
    unittest.main()
