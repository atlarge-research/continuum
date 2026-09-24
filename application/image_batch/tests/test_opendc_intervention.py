"""Controlled cluster interventions require observed placement and drain evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Discovery imports checked-out source modules.
# pylint: disable=wrong-import-position
from opendc_intervention import validate_intervention

# pylint: enable=wrong-import-position


def pod(uid, node="worker-a", phase="Running", scheduled="2026-09-24T01:00:00Z"):
    """Create a captured worker Pod for a controlled intervention fixture.

    Args:
        uid (str): Stable Pod identity.
        node (str): Assigned node.
        phase (str): Observed Pod lifecycle phase.
        scheduled (str): Original scheduling condition timestamp.

    Returns:
        dict: Minimal Kubernetes Pod record.
    """
    return {
        "metadata": {"uid": uid, "labels": {"app.kubernetes.io/name": "image-batch-worker"}},
        "spec": {"nodeName": node},
        "status": {
            "phase": phase,
            "conditions": [
                {"type": "PodScheduled", "status": "True", "lastTransitionTime": scheduled}
            ],
        },
    }


def capture(kind="busy"):
    """Build an acknowledged cordon or reserve-admission operation.

    Args:
        kind (str): busy, empty or up operation.

    Returns:
        dict: Before/after API evidence including the request interval.
    """
    nodes = {"items": [{"metadata": {"name": "worker-a"}, "spec": {"unschedulable": kind == "up"}}]}
    after = copy.deepcopy(nodes)
    after["items"][0]["spec"]["unschedulable"] = kind != "up"
    before = {"items": [pod("initial")] if kind == "busy" else []}
    return {
        "kind": kind,
        "command": "uncordon" if kind == "up" else "cordon",
        "selected_worker": "worker-a",
        "request_unix_seconds": 1790211610.2,
        "acknowledged_unix_seconds": 1790211610.8,
        "controller_clock_offset_seconds": {"lower": 0, "upper": 0},
        "before_nodes": nodes,
        "after_nodes": after,
        "before_pods": before,
        "after_ack_pods": copy.deepcopy(before),
    }


class InterventionTests(unittest.TestCase):
    """Do not infer admission, drain or power-off from a successful API response."""

    def test_busy_cordon_preserves_and_drains_initial_assignments(self):
        """A later container start is allowed when the Pod was already assigned."""
        result = validate_intervention(capture(), {"items": [pod("initial", phase="Succeeded")]})
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["initial_active_pod_uids"], ["initial"])
        self.assertFalse(result["physical_power_off_measured"])

    def test_new_assignment_after_ack_is_a_violation(self):
        """Fresh bindings to the cordoned worker fail the observed behavior check."""
        pods = [
            pod("initial", phase="Succeeded"),
            pod("late", phase="Succeeded", scheduled="2026-09-24T01:00:12Z"),
        ]
        result = validate_intervention(capture(), {"items": pods})
        self.assertEqual(result["status"], "violated")
        self.assertEqual(result["new_assignments_after_ack"], ["late"])

    def test_api_boundary_assignments_are_explicitly_inconclusive(self):
        """Second-resolution timestamps cannot establish ordering inside the API interval."""
        evidence = capture("empty")
        boundary = pod("boundary", phase="Succeeded", scheduled="2026-09-24T01:00:10Z")
        evidence["after_ack_pods"]["items"] = [boundary]
        result = validate_intervention(evidence, {"items": [boundary]})
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["boundary_assignment_uids"], ["boundary"])

    def test_missing_or_failed_initial_pod_does_not_prove_drain(self):
        """Evicted, failed or absent initial work is not a successful drain."""
        for final in (
            [],
            [pod("initial", phase="Failed")],
            [pod("initial", node="worker-b", phase="Succeeded")],
        ):
            with self.subTest(final=final):
                self.assertNotEqual(
                    validate_intervention(capture(), {"items": final})["status"], "supported"
                )

    def test_reserve_requires_observed_new_admission(self):
        """Uncordon success alone does not show that the reserve worker accepts tasks."""
        evidence = capture("up")
        self.assertEqual(validate_intervention(evidence, {"items": []})["status"], "inconclusive")
        result = validate_intervention(
            evidence, {"items": [pod("new", phase="Succeeded", scheduled="2026-09-24T01:00:12Z")]}
        )
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["new_assignments_after_ack"], ["new"])

    def test_empty_cordon_cannot_be_relabeled_from_busy_capture(self):
        """The actual immediate pre-action Pod list must support the claimed initial state."""
        evidence = capture()
        evidence["kind"] = "empty"
        self.assertEqual(
            validate_intervention(evidence, {"items": [pod("initial", phase="Succeeded")]})[
                "status"
            ],
            "violated",
        )

    def test_unmeasured_clock_cannot_prove_assignment_ordering(self):
        """A host/controller clock assumption cannot silently become a supported verdict."""
        saved = capture()
        saved.pop("controller_clock_offset_seconds")
        self.assertEqual(
            validate_intervention(saved, {"items": [pod("initial", phase="Succeeded")]})["status"],
            "inconclusive",
        )

    def test_clock_bound_can_make_apparent_late_binding_inconclusive(self):
        """Controller timestamp offset must not be mistaken for a cordon violation."""
        saved = capture("empty")
        saved["controller_clock_offset_seconds"] = {"lower": 2, "upper": 2.5}
        result = validate_intervention(
            saved, {"items": [pod("new", phase="Succeeded", scheduled="2026-09-24T01:00:12Z")]}
        )
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["new_assignments_after_ack"])


if __name__ == "__main__":
    unittest.main()
