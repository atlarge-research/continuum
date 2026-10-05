"""Frozen capacity-target policy retains demand peaks across fallback and recovery."""

import copy
from pathlib import Path
import tempfile
import unittest

from closed_loop_guards import reactive_action, snapshot_view
from closed_loop_journal import Journal
from demo_configuration import EXPERIMENT_DEFAULTS, validate_experiment
import test_closed_loop_guards as fixtures


class FinalReactiveTests(unittest.TestCase):
    """Catch delayed upscaling, premature downscaling and lost durable demand history."""

    def view(self, demand=0, accepting=4):
        """Build a homogeneous six-worker validated-policy input.

        Args:
            demand (float): Unfinished requested application CPU.
            accepting (int): Current accepting worker count.

        Returns:
            dict: Complete capacity-policy input with empty accepting workers.
        """
        names = [f"w{number}" for number in range(6)]
        return {
            "nodes": {name: {"application_cores": 4} for name in names},
            "requested_cpu_demand": demand,
            "application_slots": accepting * 4,
            "active_workers": names[:accepting],
            "empty_workers": names[:accepting],
            "reserve_workers": names[accepting:],
            "draining_workers": [],
            "minimum_workers": 2,
            "maximum_workers": 6,
            "reactive_up_threshold": 0.9,
            "reactive_down_threshold": 0.7,
            "reactive_target_fraction": 0.8,
            "reactive_downscale_stabilization_seconds": 120,
        }

    def propose(self, view=None, history=None, now=1000, fallback=False):
        """Run the actual policy at a declared observation time.

        Args:
            view (dict or None): Optional custom capacity inventory.
            history (dict or None): Previous durable policy state.
            now (float): UTC observation time.
            fallback (bool): Whether this observation is a forecast fallback.

        Returns:
            dict: Actual policy proposal and next history.
        """
        return reactive_action(
            view or self.view(), history or {}, now_seconds=now, fallback=fallback, tick_id=1
        )

    def test_eighty_percent_target_scales_up_eagerly_and_clips_bounds(self):
        """Demand just above 80% needs another worker without waiting for stabilization."""
        for demand, desired, action in (
            (0, 2, "unchanged"),
            (12.8, 4, "unchanged"),
            (12.81, 5, "scale-up"),
            (100, 6, "scale-up"),
        ):
            with self.subTest(demand=demand):
                result = self.propose(self.view(demand))
                self.assertEqual(result.get("desired_workers"), desired)
                self.assertEqual(result["action"], action)

    def test_initial_capacity_is_retained_through_exact_window_boundary(self):
        """Startup low demand must not erase the initial four-worker recommendation."""
        first = self.propose()
        self.assertEqual(first["action"], "unchanged")
        boundary = self.propose(history=first["state"], now=1120)
        self.assertEqual(boundary["action"], "unchanged")
        expired = self.propose(history=boundary["state"], now=1120.001)
        self.assertEqual(expired["action"], "scale-down")
        self.assertEqual(expired["selected_worker"], "w0")

    def test_fallback_retains_same_tick_peak_and_history_is_not_mutated(self):
        """A lower-demand fallback read must retain the earlier high recommendation."""
        first = self.propose(self.view(16))
        original = copy.deepcopy(first["state"])
        lower = self.propose(self.view(0, 5), first["state"], now=1001, fallback=True)
        self.assertEqual(lower["action"], "unchanged")
        self.assertEqual(lower.get("stabilized_desired_workers"), 5)
        self.assertEqual(first["state"], original)
        expired = self.propose(self.view(0, 5), lower["state"], now=1120.001)
        self.assertEqual(expired["action"], "scale-down")

    def test_removal_requires_empty_worker_and_no_draining_worker(self):
        """Expired demand history never overrides physical removal safety."""
        history = self.propose()["state"]
        for key, value in (("empty_workers", []), ("draining_workers", ["w5"])):
            view = self.view()
            view[key] = value
            self.assertEqual(self.propose(view, history, now=1121)["action"], "unchanged")
        self.assertEqual(self.propose(self.view(0, 2), history, now=1121)["action"], "unchanged")

    def test_backward_clock_rejects_stabilization_history(self):
        """Recovery cannot expire a demand peak using a clock earlier than its observation."""
        history = self.propose()["state"]
        with self.assertRaises(ValueError):
            self.propose(history=history, now=999)

    def test_recommendation_survives_restart_without_cycle_end(self):
        """A crash during native prediction cannot discard an already observed peak."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            journal = Journal(path)
            journal.append("cycle.end", history={"last_action_at": 900})
            journal.append(
                "reactive.recommendation",
                recommendations=[{"at_seconds": 1000, "desired_workers": 5}],
                tick=1,
            )
            journal.close()
            restored = Journal(path)
            try:
                history = restored.history()
                self.assertEqual(history["last_action_at"], 900)
                self.assertEqual(
                    self.propose(self.view(0, 5), history, now=1100)["action"], "unchanged"
                )
                self.assertEqual(
                    history.get("reactive_recommendations"),
                    [{"at_seconds": 1000, "desired_workers": 5}],
                )
            finally:
                restored.close()

    def test_snapshot_counts_queue_and_unreleased_requests_with_new_settings(self):
        """Classifier completion does not erase demand and queued work contributes equally."""
        fixture = fixtures.GuardTests()
        fixture.setUp()
        fixture.config.update(
            reactive_target_fraction=0.8, reactive_downscale_stabilization_seconds=120
        )
        fixture.snapshot["jobs"]["queued"] = [fixture.job("queued")]
        held = fixture.job("held", "w1")
        held["execution_state"] = "terminated"
        fixture.snapshot["jobs"]["finished"] = [held]
        view = snapshot_view(fixture.snapshot, fixture.config, now_seconds=1001)
        self.assertEqual(view["requested_cpu_demand"], 2)
        self.assertEqual(view.get("reactive_target_fraction"), 0.8)
        self.assertEqual(view.get("reactive_downscale_stabilization_seconds"), 120)

    def test_settings_reject_partial_or_invalid_policy_and_preserve_legacy(self):
        """Both new settings must be valid together; old settings remain supported."""
        legacy = dict(EXPERIMENT_DEFAULTS)
        legacy.pop("reactive_target_fraction", None)
        legacy.pop("reactive_downscale_stabilization_seconds", None)
        validate_experiment(legacy)
        valid = {
            **legacy,
            "reactive_target_fraction": 0.8,
            "reactive_downscale_stabilization_seconds": 120,
        }
        validate_experiment(valid)
        for target, window in (
            (True, 120),
            (float("nan"), 120),
            (1.1, 120),
            (0.8, 0),
            (0, 120),
            (0.8, -1),
        ):
            with self.subTest(target=target, window=window), self.assertRaises(ValueError):
                validate_experiment(
                    {
                        **legacy,
                        "reactive_target_fraction": target,
                        "reactive_downscale_stabilization_seconds": window,
                    }
                )


if __name__ == "__main__":
    unittest.main()
