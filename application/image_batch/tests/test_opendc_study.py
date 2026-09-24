"""Validation choices use matched windows and equal independent workload-seed weights."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Discovery imports the checked-out source rather than an installed package.
# pylint: disable=wrong-import-position
from opendc_study import select_across_runs
from test_opendc_report import validation_result

# pylint: enable=wrong-import-position


class StudyTests(unittest.TestCase):
    """Do not confuse extra cutoffs or sampled futures with new workload repetitions."""

    def test_equal_run_weights_with_different_eligible_window_counts(self):
        """A run with more overlapping cutoffs gets the same weight as another run."""
        first = {**validation_result(), "workload_seed": 46}
        second = copy.deepcopy(first)
        second.update(run_id="run-b", workload_seed=47)
        second["groups"] = [g for g in second["groups"] if g["cutoff_index"] == 0]
        for group in second["groups"]:
            group["windows"]["120"]["completion_curve_mae"] = (
                10 if group["horizon_seconds"] == 30 else 0
            )
            group["execution_seconds"] = None
        selected = select_across_runs([first, second], seed=123)
        self.assertEqual(selected["selected"]["scenarios"], 3)
        self.assertEqual([r["completion_curve_mae"] for r in selected["candidates"]], [6, 1.5])
        self.assertEqual(selected["run_cutoffs"], {"test-run": [0, 1], "run-b": [0]})
        self.assertTrue(all(r["mean_execution_seconds"] is None for r in selected["candidates"]))

    def test_held_out_and_repeated_seed_are_rejected(self):
        """Held-out outcomes and duplicate workload seeds cannot enter parameter selection."""
        first = {**validation_result(), "workload_seed": 46}
        second = copy.deepcopy(first)
        second["run_id"] = "run-b"
        with self.assertRaisesRegex(ValueError, "workload seeds"):
            select_across_runs([first, second], seed=123)
        second.update(workload_seed=47, split="held-out")
        with self.assertRaisesRegex(ValueError, "validation"):
            select_across_runs([first, second], seed=123)

    def test_incompatible_candidate_sets_are_not_silently_pooled(self):
        """Every validation run must test the same candidate configurations."""
        first = {**validation_result(), "workload_seed": 46}
        second = copy.deepcopy(first)
        second.update(run_id="run-b", workload_seed=47)
        second["groups"] = [g for g in second["groups"] if g["horizon_seconds"] == 30]
        with self.assertRaisesRegex(ValueError, "configurations"):
            select_across_runs([first, second], seed=123)


if __name__ == "__main__":
    unittest.main()
