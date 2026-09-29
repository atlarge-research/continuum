"""Oracle ranking changes future arrival knowledge without changing causal calibration."""

import copy
import unittest

from closed_loop_counterfactuals import derive_case


class CounterfactualDerivationTests(unittest.TestCase):
    """Keep already-calibrated residual work and only change the declared action topology."""

    def test_preserves_calibration_and_tasks_without_applying_occupancy_twice(self):
        """A later-known future does not authorize later runtime or backlog information."""
        oracle = dict(
            candidate="unchanged",
            scenario=0,
            cutoff_ms=1000,
            horizon_ms=60000,
            initial_membership=dict(complete=True),
            initial_cordoned_worker=None,
            occupancy_model=dict(startup_ms=2000, release_ms=1000),
            tasks=[dict(task=dict(id=1, duration=9000), metadata=dict(cohort="future"))],
            model_exhausted_jobs=[],
            workers=[dict(node_name="w1")],
            selected_worker=None,
            scope="complete",
            omitted_tasks=[],
        )
        primary = copy.deepcopy(oracle)
        primary.update(candidate="scale-down", selected_worker="w1")
        original = copy.deepcopy(oracle)
        result = derive_case(oracle, primary)
        self.assertEqual(result["tasks"], original["tasks"])
        self.assertEqual(result["occupancy_model"], original["occupancy_model"])
        self.assertEqual(result["candidate"], "scale-down")
        self.assertEqual(oracle, original)
        primary["occupancy_model"]["startup_ms"] = 3000
        with self.assertRaises(ValueError):
            derive_case(oracle, primary)


if __name__ == "__main__":
    unittest.main()
