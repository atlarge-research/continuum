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

    def test_changed_identity_vetoes_but_queue_appearance_does_not(self):
        """Topology replacement vetoes a proposal; queued arrivals remain forecast uncertainty."""
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
        self.module().guard_action(before, self.view(after), proposal, self.config, decision_age=2)
        after["jobs"]["active"] = [self.job("new", "w1")]
        with self.assertRaisesRegex(ValueError, "new assignment"):
            self.module().guard_action(
                before, self.view(after), proposal, self.config, decision_age=2
            )

    def test_configured_age_budget_is_used_at_the_physical_guard(self):
        """A measured budget applies at dispatch, not just during numerical selection."""
        before = self.view()
        proposal = {"action": "scale-up", "selected_worker": "w3"}
        config = {**self.config, "decision_age_seconds": 60}
        self.module().guard_action(before, before, proposal, config, decision_age=45)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.module().guard_action(before, before, proposal, config, decision_age=61)

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

    def test_first_complete_empty_observation_permits_down_in_both_paths(self):
        """Neither reactive nor fallback needs a preceding qualifying check."""
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                result = self.module().reactive_action(
                    self.view(), {}, now_seconds=1001, fallback=fallback, tick_id=1
                )
                self.assertEqual(result["action"], "scale-down")
                self.assertEqual(result["selected_worker"], "w1")
                self.assertEqual(result["fallback"], fallback)

    def test_each_observation_selects_the_current_empty_worker(self):
        """A newly empty worker qualifies without intersecting previous identities."""
        self.snapshot["workers"][2]["schedulable"] = True
        self.snapshot["jobs"]["active"] = [self.job(node="w2")]
        first = self.module().reactive_action(
            self.view(), {}, now_seconds=1001, fallback=False, tick_id=1
        )
        self.assertEqual(first["selected_worker"], "w1")
        self.snapshot["jobs"]["active"] = [self.job(node="w1")]
        second = self.module().reactive_action(
            self.view(), first["state"], now_seconds=1061, fallback=False, tick_id=2
        )
        self.assertEqual(second["selected_worker"], "w2")

    def test_gap_and_legacy_history_do_not_delay_fresh_qualifying_down(self):
        """Only the current complete observation establishes down eligibility."""
        history = {
            "reactive_observation": {"tick_id": 1, "eligible_workers": []},
            "last_action_at": 999,
        }
        result = self.module().reactive_action(
            self.view(), history, now_seconds=1001, fallback=False, tick_id=3
        )
        self.assertEqual(result["action"], "scale-down")
        self.assertEqual(result["state"]["last_action_at"], 999)
        self.assertNotIn("reactive_observation", result["state"])

    def test_fallback_uses_new_complete_state_after_nonqualifying_read(self):
        """A later fresh fallback observation may qualify after demand falls."""
        empty = self.view()
        self.snapshot["jobs"]["queued"] = [self.job(str(i)) for i in range(3)]
        busy = self.module().reactive_action(
            self.view(), {}, now_seconds=1001, fallback=False, tick_id=1
        )
        self.assertEqual(busy["action"], "unchanged")
        fallback = self.module().reactive_action(
            empty, busy["state"], now_seconds=1002, fallback=True, tick_id=1
        )
        self.assertEqual(fallback["action"], "scale-down")

    def test_cpu_demand_includes_queued_and_unreleased_finished_jobs(self):
        """Demand uses requested cores, including classifier-finished retained resources."""
        queued, assigned, released = self.job("q"), self.job("a", "w1"), self.job("r", "w1")
        queued["requested_cpu_count"] = 2.5
        assigned["requested_cpu_count"] = 3
        assigned["execution_state"] = "terminated"
        released["pod_phase"] = "Succeeded"
        self.snapshot["jobs"].update(queued=[queued], finished=[assigned, released])
        state = self.view()
        self.assertEqual(state.get("requested_cpu_demand"), 5.5)
        action = self.module().reactive_action(
            state, {"last_action_at": 1000}, now_seconds=1001, fallback=True, tick_id=1
        )
        self.assertEqual(action["action"], "scale-up")

    def test_down_threshold_uses_capacity_after_removal(self):
        """Current demand must fit the reduced capacity threshold on its first check."""
        self.snapshot["jobs"]["queued"] = [self.job(str(i)) for i in range(3)]
        result = self.module().reactive_action(
            self.view(), {}, now_seconds=1001, fallback=False, tick_id=1
        )
        self.assertEqual(result["action"], "unchanged")
        self.snapshot["jobs"]["queued"].pop()
        result = self.module().reactive_action(
            self.view(), result["state"], now_seconds=1002, fallback=False, tick_id=1
        )
        self.assertEqual(result["action"], "scale-down")

    def test_unknown_or_unfittable_queued_requests_fail_closed(self):
        """Queued work cannot disappear from demand or require an impossible worker."""
        for cpu in (None, float("nan"), 4):
            job = self.job()
            job["requested_cpu_count"] = cpu
            self.snapshot["jobs"]["queued"] = [job]
            with self.assertRaises(ValueError):
                self.view()

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
