"""Safety evidence distinguishes observed defects from incomplete physical coverage."""

import copy
import unittest

from closed_loop_audit import audit_inventory, audit_journal, audit_states


class SafetyAuditTests(unittest.TestCase):
    """Exercise missing inventories, uncertain mutations and assignment boundaries."""

    def test_uncertain_request_must_resolve_before_another_action(self):
        """An API timeout is not permission to issue a duplicate or second action."""
        rows = [
            dict(sequence=0, event="action.request", action_id="a", recorded_at_ns=1),
            dict(sequence=1, event="action.uncertain", action_id="a", recorded_at_ns=2),
            dict(sequence=2, event="action.request", action_id="b", recorded_at_ns=3),
            dict(sequence=3, event="action.result", action_id="b", status="acknowledged"),
        ]
        result = audit_journal(rows)
        self.assertEqual(result["overlapping_request_ids"], ["b"])
        self.assertEqual(result["unresolved_action_ids"], ["a"])
        self.assertEqual(result["uncertain_action_ids"], ["a"])

    def test_reconciliation_is_not_another_api_request(self):
        """A later observation resolves one uncertain action without inventing a retry."""
        rows = [
            dict(sequence=0, event="action.request", action_id="a", recorded_at_ns=1),
            dict(sequence=1, event="action.uncertain", action_id="a", recorded_at_ns=2),
            dict(sequence=2, event="action.result", action_id="a", status="applied"),
        ]
        result = audit_journal(rows)
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["unresolved_action_ids"], [])
        self.assertFalse(result["violations"])

    def test_missing_terminal_pod_and_wrong_worker_are_not_clean_evidence(self):
        """Missing Pods remain inconclusive, while observed off-pool placement is a defect."""
        jobs = [dict(metadata=dict(uid=uid)) for uid in ("a", "b")]
        pods = [
            dict(
                metadata=dict(name="pa", ownerReferences=[dict(kind="Job", uid="a")]),
                spec=dict(nodeName="control"),
                status=dict(phase="Succeeded"),
            )
        ]
        result = audit_inventory(jobs, pods, {"w1"})
        self.assertEqual(result["missing_final_pod_job_uids"], ["b"])
        self.assertEqual(result["off_pool_pods"], ["pa"])
        pods[0]["metadata"]["labels"] = {"continuum.atlarge.nl/workload": "image-batch"}
        result = audit_inventory([], pods, {"w1"})
        self.assertEqual(result["unmatched_application_pods"], ["pa"])
        self.assertEqual(result["off_pool_pods"], ["pa"])

    def test_new_action_id_cannot_hide_wrong_target_admission(self):
        """A down request against an already cordoned target contradicts its claimed proposal."""
        rows = [
            dict(
                sequence=0,
                event="cycle.proposal",
                proposal=dict(action="scale-down", selected_worker="w1"),
                before=dict(nodes=dict(w1=dict(uid="node1", accepting=False))),
            ),
            dict(
                sequence=1,
                event="action.request",
                action_id="new-id",
                recorded_at_ns=1,
                action="scale-down",
                selected_worker="w1",
                node_uid="node1",
            ),
        ]
        self.assertEqual(audit_journal(rows)["mismatched_proposal_action_ids"], ["new-id"])

    def states(self, accepting, *, gap=1):
        """Build a fresh collection pair surrounding one new worker assignment.

        Args:
            accepting (bool): Worker admission state in both collections.
            gap (int): Seconds between observations.

        Returns:
            list[dict]: Before/after observations containing a complete assignment bracket.
        """
        result = []
        for index, second in enumerate((0, gap)):
            timestamp = f"2026-09-25T00:00:{second:02d}+00:00"
            result.append(
                dict(
                    timestamp=timestamp,
                    collection=dict(started_at=timestamp, missing_job_uids=[]),
                    workers=[
                        dict(
                            node_name="w1",
                            schedulable=accepting,
                            ready=True,
                            kubernetes_node_uid="node1",
                        )
                    ],
                    jobs=dict(
                        queued=[],
                        finished=[],
                        active=[]
                        if not index
                        else [
                            dict(
                                kubernetes_job_uid="a",
                                node_name="w1",
                                pod_name="pa",
                                requested_cpu_count=1,
                                requested_memory_mb=512,
                            )
                        ],
                    ),
                )
            )
        return result

    def test_new_binding_on_cordoned_worker_is_flagged_but_a_gap_is_inconclusive(self):
        """A stale bracket cannot support a zero-violation claim or definite cordon violation."""
        config = dict(
            workers=[dict(node_name="w1", configured_cores=4, memory_mib=4096)],
            minimum_workers=0,
            maximum_workers=1,
        )
        clean = audit_states(self.states(True), config, [])
        self.assertEqual(clean["covered_new_bindings"], 1)
        violation = audit_states(self.states(False), config, [])
        self.assertEqual(violation["cordoned_binding_job_uids"], ["a"])
        uncertain = audit_states(self.states(False, gap=5), config, [])
        self.assertEqual(uncertain["cordoned_binding_job_uids"], [])
        self.assertEqual(uncertain["uncertain_binding_job_uids"], ["a"])

    def test_classifier_finished_release_still_occupies_capacity(self):
        """A finished classifier cannot conceal a fourth reserved slot on a three-slot worker."""
        config = dict(
            workers=[dict(node_name="w1", configured_cores=4, memory_mib=4096)],
            minimum_workers=1,
            maximum_workers=1,
        )
        states = self.states(True)
        job = states[1]["jobs"]["active"][0]
        states[1]["jobs"]["finished"] = [
            dict(copy.deepcopy(job), kubernetes_job_uid=str(i), pod_phase="Running")
            for i in range(3)
        ]
        result = audit_states(states, config, [])
        self.assertEqual(result["capacity_violations"][0]["observed_usage"][0], 4)

    def test_action_during_prior_collection_makes_binding_inconclusive(self):
        """The first API read can precede a cordon even when collection completion follows it."""
        config = dict(
            workers=[dict(node_name="w1", configured_cores=4, memory_mib=4096)],
            minimum_workers=0,
            maximum_workers=1,
        )
        states = self.states(False)
        states[0]["collection"]["started_at"] = "2026-09-24T23:59:59+00:00"
        result = audit_states(states, config, [dict(start=1790294399.2, end=1790294399.8)])
        self.assertEqual(result["cordoned_binding_job_uids"], [])
        self.assertEqual(result["uncertain_binding_job_uids"], ["a"])


if __name__ == "__main__":
    unittest.main()
