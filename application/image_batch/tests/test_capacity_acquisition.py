"""Delayed admission preserves request clocks, identity and exclusive intent."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from closed_loop_journal import Journal
from closed_loop_guards import guard_action
from capacity_acquisition import pending_activation, request_activation, activation_view
import test_closed_loop_guards as guard_fixtures
import closed_loop_controller


class AcquisitionTests(unittest.TestCase):
    """A requested reserve remains unavailable until its durable due time."""

    def setUp(self):
        """Prepare a realistic two-active/one-reserve state."""
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        self.view = fixture.view()
        self.config = {**fixture.config, "acquisition_seconds": 60.0}
        self.proposal = {"action": "scale-up", "selected_worker": "w3"}
        # setUp owns this directory until unittest cleanup after each lifecycle test.
        self.temporary = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.path = Path(self.temporary.name) / "journal.jsonl"
        self.journal = Journal(self.path)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(lambda: self.journal.close() if not self.journal.stream.closed else None)

    def request(self):
        """Reserve a worker at a known request time.

        Returns:
            dict: Durable acquisition request.
        """
        return request_activation(
            self.journal,
            self.view,
            self.view,
            self.proposal,
            self.config,
            now_seconds=1001,
            cutoff_seconds=1000,
        )

    def loop(self):
        """Construct a controller around the real journal and controlled observation.

        Returns:
            Controller: Loop with isolated transport and timing.
        """
        loop = object.__new__(closed_loop_controller.Controller)
        loop.journal, loop.config, loop.history = self.journal, self.config, {}
        loop.fresh = Mock(return_value=self.view)
        loop.session = Mock()
        loop.recover = Mock()
        return loop

    def test_request_clock_and_pending_exclusion_survive_restart(self):
        """Restart retains the original due time and charged pending capacity."""
        request = self.request()
        self.assertEqual(request["requested_at_seconds"], 1001)
        self.assertEqual(request["ready_at_seconds"], 1061)
        self.journal.close()
        self.journal = Journal(self.path)
        self.assertEqual(
            pending_activation(self.journal)["activation_id"], request["activation_id"]
        )
        decorated = activation_view(self.view, self.journal)
        self.assertEqual(decorated["pending_workers"], ["w3"])
        self.assertEqual(decorated["reserve_workers"], [])
        self.assertEqual(decorated["allocated_application_cores"], 9)
        self.assertEqual(decorated["accepting_draining_application_cores"], 6)

    def test_second_request_and_capacity_changes_are_blocked(self):
        """Neither another acquisition nor scale-down can overlap pending activation."""
        self.request()
        with self.assertRaisesRegex(ValueError, "pending"):
            self.request()
        decorated = activation_view(self.view, self.journal)
        with self.assertRaisesRegex(ValueError, "pending"):
            guard_action(
                decorated,
                decorated,
                {"action": "scale-down", "selected_worker": "w1"},
                self.config,
                decision_age=1,
            )

    def test_activation_never_dispatches_before_due_time(self):
        """Progress polling must not shorten the sixty-second availability delay."""
        self.request()
        loop = self.loop()
        with patch.object(closed_loop_controller.time, "time", return_value=1060.999), patch.object(
            closed_loop_controller, "actuate"
        ) as dispatch:
            loop.service_activation()
        dispatch.assert_not_called()
        self.assertIsNotNone(pending_activation(self.journal))

    def test_activation_progress_is_independent_of_next_policy_tick(self):
        """The sixty-second acquisition completes even before a ninety-second tick."""
        self.request()
        loop = self.loop()
        loop.origin, loop.next_tick = None, 1090
        loop.discover_origin = Mock()
        fresh = copy.deepcopy(self.view)
        fresh["timestamp_seconds"] = fresh["collection_started_seconds"] = 1061
        loop.fresh.return_value = fresh
        with patch.object(closed_loop_controller.time, "time", return_value=1061), patch.object(
            closed_loop_controller,
            "actuate",
            return_value={"action_id": "api", "last_action_at": 1061},
        ) as dispatch:
            loop.maybe_tick()
        dispatch.assert_called_once()

    def test_due_activation_dispatches_once_and_waits_for_observation(self):
        """An acknowledgement is not observed availability and cannot be repeated."""
        request = self.request()
        loop = self.loop()
        fresh = copy.deepcopy(self.view)
        fresh["timestamp_seconds"] = fresh["collection_started_seconds"] = 1061
        loop.fresh.return_value = fresh
        with patch.object(closed_loop_controller.time, "time", return_value=1061), patch.object(
            closed_loop_controller,
            "actuate",
            return_value={"action_id": "api", "last_action_at": 1061},
        ) as dispatch:
            loop.service_activation()
            loop.service_activation()
        self.assertEqual(dispatch.call_count, 1)
        self.assertIsNotNone(pending_activation(self.journal))
        observed = copy.deepcopy(fresh)
        observed["timestamp_seconds"] = 1062
        observed["nodes"]["w3"]["accepting"] = True
        observed["active_workers"].append("w3")
        observed["reserve_workers"] = []
        loop.fresh.return_value = observed
        with patch.object(closed_loop_controller.time, "time", return_value=1062):
            loop.service_activation()
        self.assertIsNone(pending_activation(self.journal))
        result = self.journal.records[-1]
        self.assertEqual(result["event"], "activation.result")
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["activation_id"], request["activation_id"])

    def test_changed_uid_or_new_assignment_cancels_without_dispatch(self):
        """Physical acquisition checks retain target identity and emptiness."""
        for mutation in ("uid", "busy"):
            with self.subTest(mutation=mutation):
                request = self.request()
                loop = self.loop()
                state = copy.deepcopy(self.view)
                state["timestamp_seconds"] = state["collection_started_seconds"] = 1061
                if mutation == "uid":
                    state["nodes"]["w3"]["uid"] = "replacement"
                else:
                    state["assignments"]["new"] = "w3"
                    state["reserve_workers"] = []
                loop.fresh.return_value = state
                with patch.object(
                    closed_loop_controller.time, "time", return_value=1061
                ), patch.object(closed_loop_controller, "actuate") as dispatch:
                    loop.service_activation()
                dispatch.assert_not_called()
                self.assertIsNone(pending_activation(self.journal))
                self.assertEqual(self.journal.records[-1]["status"], "cancelled")
                self.assertEqual(
                    self.journal.records[-1]["activation_id"], request["activation_id"]
                )

    def test_uncertain_dispatch_is_reconciled_without_repeat(self):
        """A lost API reply retains exclusive acquisition intent."""
        self.request()
        loop = self.loop()
        state = copy.deepcopy(self.view)
        state["timestamp_seconds"] = state["collection_started_seconds"] = 1061
        loop.fresh.return_value = state
        with patch.object(closed_loop_controller.time, "time", return_value=1061), patch.object(
            closed_loop_controller, "actuate", side_effect=RuntimeError("lost reply")
        ) as dispatch:
            loop.service_activation()
            loop.service_activation()
        self.assertEqual(dispatch.call_count, 1)
        self.assertIsNotNone(pending_activation(self.journal))

    def test_zero_delay_uses_existing_guarded_api_path(self):
        """Zero-delay control retains the established direct actuation behavior."""
        loop = self.loop()
        loop.config["acquisition_seconds"] = 0
        with patch.object(
            closed_loop_controller, "actuate", return_value={"last_action_at": 1001}
        ) as dispatch:
            result = loop.dispatch_capacity(
                self.view, self.view, self.proposal, cutoff_seconds=1000
            )
        dispatch.assert_called_once()
        self.assertEqual(result["last_action_at"], 1001)
        self.assertIsNone(pending_activation(self.journal))

    def test_negative_or_boolean_delay_is_rejected(self):
        """Acquisition lead time must be a finite nonnegative number."""
        for delay in (-1, True, float("inf")):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                request_activation(
                    self.journal,
                    self.view,
                    self.view,
                    self.proposal,
                    {**self.config, "acquisition_seconds": delay},
                    now_seconds=1001,
                    cutoff_seconds=1000,
                )


if __name__ == "__main__":
    unittest.main()
