"""Runtime review regressions for startup stabilization and diagnostic clocks."""

from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from closed_loop_controller import Controller
from closed_loop_diagnostics import cycle_diagnostic
from demo_configuration import EXPERIMENT_DEFAULTS
from forecast_trace import iso
import test_final_reactive as reactive_fixtures
import test_final_response_timing as timing_fixtures


class ReviewBoundaryTests(unittest.TestCase):
    """Catch artificial evaluated-window holds and post-selection timing export failures."""

    def test_startup_seed_is_durable_before_warmup_and_restart_does_not_reseed(self):
        """The initial count expires during warmup rather than delaying evaluation removal."""
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                **EXPERIMENT_DEFAULTS,
                worker_cores=5,
                worker_memory_mib=8192,
                workers=[f"w{i}" for i in range(6)],
                minimum_workers=2,
                maximum_workers=6,
                active_workers=4,
                controller="user@control",
                ssh_key="/key",
                control_node="control",
                control_arm="reactive",
                native_image="pinned",
            )
            args.reactive_target_fraction = 0.8
            args.reactive_downscale_stabilization_seconds = 120
            session = Namespace(args=args, output=Path(directory), namespace="test")
            with patch("closed_loop_controller.time.time", return_value=1000):
                controller = Controller(session)
            initial = controller.history.get("reactive_recommendations")
            self.assertEqual(initial, [{"at_seconds": 1000, "desired_workers": 4}])
            controller.journal.close()
            with patch("closed_loop_controller.time.time", return_value=2680):
                restored = Controller(session)
            try:
                self.assertEqual(restored.history["reactive_recommendations"], initial)
                proposal = reactive_fixtures.FinalReactiveTests().propose(
                    history=restored.history, now=2685
                )
                self.assertEqual(proposal["action"], "scale-down")
            finally:
                restored.journal.close()

    def diagnostic(self, directory, scoring_age=None):
        """Build a complete selected native prediction with a late journal timestamp.

        Args:
            directory (Path): Isolated fixture root.
            scoring_age (float or None): Actual age used by the policy before journaling.

        Returns:
            dict: Production diagnostic result.
        """
        forecast = dict(
            status="ready",
            cutoff=iso(100000),
            settings=dict(horizon_seconds=60, scenarios=3),
            predictions=[dict(mean_count=1)],
            scenario_job_counts=[1, 1, 1],
        )
        scores = [timing_fixtures.FinalResponseTimingTests().marked()]
        for name, data in (
            ("forecast/forecast.json", forecast),
            ("scores.json", scores),
            ("suite/experiments/unchanged/0000/case.json", dict(tasks=[])),
        ):
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        cycle = dict(
            tick=1,
            outcome="held",
            proposal=dict(action="unchanged"),
            forecast_valid=True,
            decision_age_seconds=60.001,
        )
        if scoring_age is not None:
            cycle["scoring_age_seconds"] = scoring_age
        return cycle_diagnostic(directory, cycle, [], 200000, 800000)

    def test_diagnostic_uses_actual_selection_age_instead_of_later_fsync_clock(self):
        """A valid59.999s selection stays valid after its proposal is written at60.001s."""
        with tempfile.TemporaryDirectory() as directory:
            result = self.diagnostic(Path(directory), scoring_age=59.999)
        self.assertEqual(result["predicted_response_p95_seconds"], [110, 110, 110])
        self.assertTrue(result["candidate_predictions"][0]["valid"])

    def test_uncovered_diagnostic_age_is_explicit_without_aborting_export(self):
        """Missing valid timing provenance retains an invalid prediction in the evidence."""
        with tempfile.TemporaryDirectory() as directory:
            result = self.diagnostic(Path(directory))
        self.assertEqual(result["predicted_response_p95_seconds"], [])
        self.assertFalse(result["candidate_predictions"][0]["valid"])
        self.assertIn("prediction_timing_error", result)


if __name__ == "__main__":
    unittest.main()
