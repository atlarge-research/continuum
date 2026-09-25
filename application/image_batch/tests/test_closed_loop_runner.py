"""Native batch adaptation preserves complete shared cohorts and allocated core-time."""

import copy
import importlib
import unittest


class RunnerScoreTests(unittest.TestCase):
    """Hand-derived allocation and response metrics drive the real selector contract."""

    def rows(self):
        """Create two actions over three identical paired scenario cohorts.

        Returns:
            list[dict]: Validated cases and terminal native results.
        """
        rows = []
        for action in ("unchanged", "scale-down"):
            for scenario in range(3):
                case = {
                    "candidate": action,
                    "selected_worker": "w2" if action == "scale-down" else None,
                    "scenario": scenario,
                    "cutoff_ms": 100000,
                    "horizon_ms": 60000,
                    "scope": "complete",
                    "initial_membership": {"complete": True},
                    "initial_cordoned_worker": None,
                    "workers": [
                        {"node_name": "w1", "modeled_cores": 3},
                        {"node_name": "w2", "modeled_cores": 3},
                    ],
                    "tasks": [
                        {
                            "task": {"id": 1, "submission_time": 0},
                            "metadata": {"original_creation_ms": 80000},
                        }
                    ],
                    "model_exhausted_jobs": [],
                    "omitted_tasks": [],
                }
                validation = {
                    "status": "passed",
                    "tasks": [
                        {
                            "task_id": 1,
                            "finish_time": 60000 if action == "scale-down" else 30000,
                            "host_name": "w2",
                        }
                    ],
                }
                rows.append({"case": case, "validation": validation})
        return rows

    def score(self, rows):
        """Call the production batch-to-policy adapter.

        Args:
            rows (list[dict]): Candidate cases and native validation results.

        Returns:
            list[dict]: Numerical inputs for the guarded policy selector.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_runner"))
        return importlib.import_module("closed_loop_runner").score_cases(rows, scenarios=3)

    def test_original_response_and_full_window_accepting_plus_draining_allocation(self):
        """Two accepting workers cost720 core-seconds; one drains after60 seconds:540."""
        result = {row["candidate"]: row for row in self.score(self.rows())}
        self.assertEqual(result["unchanged"]["scenarios"][0]["responses_seconds"], [50])
        self.assertEqual(result["scale-down"]["scenarios"][0]["responses_seconds"], [80])
        self.assertEqual(result["unchanged"]["scenarios"][0]["allocated_core_seconds"], 720)
        self.assertEqual(result["scale-down"]["scenarios"][0]["allocated_core_seconds"], 540)

    def test_mismatched_action_cohorts_and_incomplete_membership_cannot_be_scored(self):
        """A cheap zero cohort cannot be ranked against a different nonempty cohort."""
        for kind in ("cohort", "membership", "completion", "scenario"):
            rows = self.rows()
            if kind == "cohort":
                rows[-1]["case"]["tasks"] = []
                rows[-1]["validation"]["tasks"] = []
            elif kind == "membership":
                rows[0]["case"]["initial_membership"]["complete"] = False
            elif kind == "completion":
                rows[0]["validation"]["tasks"] = []
            else:
                rows[-1]["case"]["scenario"] = 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.score(rows)

    def test_empty_cohorts_are_valid_but_keep_full_allocated_idle_time(self):
        """No Jobs does not imply free accepting capacity or a missing forecast sample."""
        rows = self.rows()
        original = copy.deepcopy(rows)
        for row in rows:
            row["case"]["tasks"] = []
            row["validation"]["tasks"] = []
        scores = {row["candidate"]: row for row in self.score(rows)}
        self.assertEqual(scores["unchanged"]["scenarios"][0]["allocated_core_seconds"], 720)
        self.assertEqual(scores["scale-down"]["scenarios"][0]["allocated_core_seconds"], 360)
        self.assertEqual(scores["scale-down"]["scenarios"][0]["cohort_size"], 0)
        self.assertEqual(len(original[0]["case"]["tasks"]), 1)


if __name__ == "__main__":
    unittest.main()
