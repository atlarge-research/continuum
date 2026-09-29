"""Fresh physical state controls actuation independently of a forecast's score."""

import copy
import importlib
import unittest

from forecast_trace import iso


class GuardTests(unittest.TestCase):
    """Staleness, changed identities and retained requests must veto unsafe proposals."""

    def setUp(self):
        """Build two accepting workers and one empty warm reserve."""
        self.config = {
            "workers": [
                {"node_name": name, "configured_cores": 4, "memory_mib": 8192}
                for name in ("w1", "w2", "w3")
            ],
            "minimum_workers": 1,
            "maximum_workers": 3,
        }
        self.snapshot = {
            "timestamp": iso(1000000),
            "collection": {"missing_job_uids": [], "atomic": False, "started_at": iso(1000000)},
            "workers": [
                {
                    "node_name": name,
                    "kubernetes_node_uid": "uid-" + name,
                    "ready": True,
                    "schedulable": name != "w3",
                    "allocatable_cpu_count": 4,
                    "allocatable_memory_mb": 8192,
                }
                for name in ("w1", "w2", "w3")
            ],
            "jobs": {"queued": [], "active": [], "finished": []},
        }

    def module(self):
        """Load the production guard implementation.

        Returns:
            module: Pure controller state/guard functions.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_guards"))
        return importlib.import_module("closed_loop_guards")

    def view(self, snapshot=None, now=1001):
        """Validate a snapshot at a specific physical decision time.

        Args:
            snapshot (dict or None): Optional altered snapshot.
            now (float): Current epoch seconds.

        Returns:
            dict: Fresh allocation and queue inventory.
        """
        return self.module().snapshot_view(snapshot or self.snapshot, self.config, now_seconds=now)

    def job(self, uid="a", node=None, created=960000):
        """Return one live Job with explicit requested resources.

        Args:
            uid (str): Job identity.
            node (str or None): Observed worker assignment.
            created (int): Original creation milliseconds.

        Returns:
            dict: Observer Job entry.
        """
        return {
            "kubernetes_job_uid": uid,
            "node_name": node,
            "creation_time": iso(created),
            "pod_phase": "Running" if node else "Pending",
            "execution_state": "running" if node else "waiting",
            "requested_cpu_count": 1,
            "requested_memory_mb": 512,
        }

    def test_stale_future_and_incomplete_observations_fail_closed(self):
        """A ready-looking cluster is unusable when its observation is stale or incomplete."""
        for now in (999, 1004):
            with self.assertRaises(ValueError):
                self.view(now=now)
        self.snapshot["collection"]["missing_job_uids"] = ["lost"]
        with self.assertRaisesRegex(ValueError, "membership"):
            self.view()

    def test_finished_classifier_does_not_make_a_busy_cordoned_worker_a_reserve(self):
        """Requested slots remain allocated until the Pod releases them."""
        job = self.job(node="w3")
        job["execution_state"] = "terminated"
        self.snapshot["jobs"]["finished"] = [job]
        state = self.view()
        self.assertEqual(state["draining_workers"], ["w3"])
        self.assertEqual(state["reserve_workers"], [])
        self.assertEqual(state["allocated_application_cores"], 9)

    def test_changed_node_identity_and_new_queue_veto_down(self):
        """The proposal cannot silently cross topology replacement or fresh queue pressure."""
        before = self.view()
        after = copy.deepcopy(self.snapshot)
        after["workers"][0]["kubernetes_node_uid"] = "replacement"
        proposal = {"action": "scale-down", "selected_worker": "w1"}
        with self.assertRaisesRegex(ValueError, "topology"):
            self.module().guard_action(
                before, self.view(after), proposal, self.config, decision_age=2
            )
        after = copy.deepcopy(self.snapshot)
        after["jobs"]["queued"] = [self.job()]
        with self.assertRaisesRegex(ValueError, "queue"):
            self.module().guard_action(
                before, self.view(after), proposal, self.config, decision_age=2
            )

    def test_up_needs_an_empty_reserve_and_down_cannot_add_a_second_drain(self):
        """Only one worker changes admission and existing Pod assignments are retained."""
        before = self.view()
        up = {"action": "scale-up", "selected_worker": "w3"}
        self.assertIsNone(
            self.module().guard_action(before, before, up, self.config, decision_age=2)
        )
        self.snapshot["jobs"]["active"] = [self.job(node="w3")]
        busy = self.view()
        with self.assertRaises(ValueError):
            self.module().guard_action(before, busy, up, self.config, decision_age=2)
        with self.assertRaisesRegex(ValueError, "draining"):
            self.module().guard_action(
                busy,
                busy,
                {"action": "scale-down", "selected_worker": "w1"},
                self.config,
                decision_age=2,
            )

    def test_fallback_is_up_only_and_reactive_down_needs_two_empty_ticks(self):
        """Invalid forecasts cannot authorize down even during an idle interval."""
        empty = self.view()
        first = self.module().reactive_action(empty, {}, now_seconds=1001, fallback=False)
        self.assertEqual(first["action"], "unchanged")
        second = self.module().reactive_action(
            empty, first["state"], now_seconds=1061, fallback=False
        )
        self.assertEqual(second["action"], "scale-down")
        self.assertEqual(
            self.module().reactive_action(empty, first["state"], now_seconds=1061, fallback=True)[
                "action"
            ],
            "unchanged",
        )
        self.snapshot["jobs"]["queued"] = [self.job()]
        self.assertEqual(
            self.module().reactive_action(self.view(), {}, now_seconds=1001, fallback=True)[
                "action"
            ],
            "scale-up",
        )

    def test_uncertain_api_result_is_reconciled_without_repeating_the_request(self):
        """A restart observes the target's UID and admission state before proceeding."""
        pending = {"action": "scale-up", "selected_worker": "w3", "node_uid": "uid-w3"}
        self.assertEqual(
            self.module().reconcile_pending(pending, self.view()), "not_observed_applied"
        )
        self.snapshot["workers"][2]["schedulable"] = True
        self.assertEqual(self.module().reconcile_pending(pending, self.view()), "observed_applied")
        self.snapshot["workers"][2]["kubernetes_node_uid"] = "replaced"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.module().reconcile_pending(pending, self.view())

    def test_slow_collection_cannot_relabel_old_membership_as_fresh(self):
        """Completion-time availability does not make an old API collection safe for action."""
        self.snapshot["collection"]["started_at"] = iso(960000)
        with self.assertRaisesRegex(ValueError, "collection"):
            self.view(now=1001)


if __name__ == "__main__":
    unittest.main()
