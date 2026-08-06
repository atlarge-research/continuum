"""Unit tests for selector-resolution reconciliation helpers."""

import unittest
from pathlib import Path

from input.configuration import selector_resolution


class SelectorResolutionTests(unittest.TestCase):
    def setUp(self):
        self.resources = [
            {"vm_id": 1, "cluster_id": "cloud-1", "tags": {"tier": "cloud", "cluster": "cloud-1"}},
            {"vm_id": 2, "cluster_id": "cloud-1", "tags": {"tier": "cloud", "cluster": "cloud-1"}},
            {"vm_id": 3, "cluster_id": "edge-1", "tags": {"tier": "edge", "cluster": "edge-1"}},
        ]
        self.resources_by_vm_id = {resource["vm_id"]: resource for resource in self.resources}

    def test_reconcile_assignment_without_candidates(self):
        entity = {
            "assign_to": {"match": {"cluster": "missing"}},
            "selector_id": "sel_missing",
        }
        result = selector_resolution.reconcile_assignment(
            entity,
            self.resources,
            self.resources_by_vm_id,
        )
        self.assertFalse(result["has_candidates"])
        self.assertEqual(result["resolved_vm_ids"], [])
        self.assertEqual(result["scope_identities"], [])
        self.assertFalse(result["resolved_vm_ids_mismatch"])
        self.assertFalse(result["scope_identities_mismatch"])

    def test_reconcile_assignment_happy_path(self):
        entity = {
            "assign_to": {"match": {"cluster": "cloud-1"}},
            "selector_id": "sel_cloud",
        }
        result = selector_resolution.reconcile_assignment(
            entity,
            self.resources,
            self.resources_by_vm_id,
        )
        self.assertTrue(result["has_candidates"])
        self.assertEqual(result["resolved_vm_ids"], [1, 2])
        self.assertIn({"kind": "selector", "selector_id": "sel_cloud"}, result["scope_identities"])
        self.assertFalse(result["resolved_vm_ids_mismatch"])
        self.assertFalse(result["scope_identities_mismatch"])

    def test_reconcile_assignment_detects_existing_mismatch(self):
        entity = {
            "assign_to": {"match": {"cluster": "cloud-1"}},
            "selector_id": "sel_cloud",
            "resolved_vm_ids": [1],
            "scope_identities": [{"kind": "selector", "selector_id": "sel_other"}],
        }
        result = selector_resolution.reconcile_assignment(
            entity,
            self.resources,
            self.resources_by_vm_id,
        )
        self.assertTrue(result["has_candidates"])
        self.assertTrue(result["resolved_vm_ids_mismatch"])
        self.assertTrue(result["scope_identities_mismatch"])

    def test_reconcile_assignment_resolves_union_and_deduplicates_overlap(self):
        entity = {
            "assign_to": {
                "any_of": [
                    {"cluster": "cloud-1"},
                    {"tier": "cloud"},
                    {"cluster": "edge-1"},
                ]
            },
            "selector_id": "sel_union",
        }

        result = selector_resolution.reconcile_assignment(
            entity,
            self.resources,
            self.resources_by_vm_id,
        )

        self.assertTrue(result["has_candidates"])
        self.assertEqual(result["empty_clause_indexes"], [])
        self.assertEqual(result["resolved_vm_ids"], [1, 2, 3])

    def test_reconcile_assignment_reports_empty_union_clause(self):
        entity = {
            "assign_to": {
                "any_of": [
                    {"cluster": "cloud-1"},
                    {"cluster": "missing"},
                ]
            },
            "selector_id": "sel_union",
        }

        result = selector_resolution.reconcile_assignment(
            entity,
            self.resources,
            self.resources_by_vm_id,
        )

        self.assertTrue(result["has_candidates"])
        self.assertEqual(result["empty_clause_indexes"], [1])
        self.assertEqual(result["resolved_vm_ids"], [1, 2])

    def test_reconcile_assignment_rejects_missing_assign_to_match(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.reconcile_assignment(
                {"selector_id": "sel_cloud"},
                self.resources,
                self.resources_by_vm_id,
            )
        self.assertIn("entity.assign_to", str(exc.exception))

    def test_reconcile_assignment_rejects_missing_selector_id(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.reconcile_assignment(
                {"assign_to": {"match": {"cluster": "cloud-1"}}},
                self.resources,
                self.resources_by_vm_id,
            )
        self.assertIn("entity.selector_id", str(exc.exception))

    def test_validate_assign_to_normalizes_and_canonicalizes_selector(self):
        assign_to, canonical_selector, selector_id = selector_resolution.validate_assign_to(
            {"match": {" cluster ": " cloud-1 ", "tier": "cloud"}},
            Path("/tmp/selector-resolution.yaml"),
            "software.modules[0].assign_to",
        )
        self.assertEqual(assign_to, {"match": {"cluster": "cloud-1", "tier": "cloud"}})
        self.assertEqual(canonical_selector, {"match": [["cluster", "cloud-1"], ["tier", "cloud"]]})
        self.assertTrue(selector_id.startswith("sel_"))

    def test_validate_assign_to_rejects_missing_match(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_assign_to(
                {},
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
            )
        self.assertIn("software.modules[0].assign_to.match", str(exc.exception))
        self.assertIn("must be a non-empty mapping", str(exc.exception))

    def test_validate_assign_to_rejects_empty_selector_value(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_assign_to(
                {"match": {"cluster": "   "}},
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
            )
        self.assertIn("software.modules[0].assign_to.match.cluster", str(exc.exception))
        self.assertIn("selector value must be a non-empty string", str(exc.exception))

    def test_validate_assign_to_rejects_trimmed_key_collision_independent_of_order(self):
        matches = [
            {"tier": "cloud", " tier ": "edge"},
            {" tier ": "edge", "tier": "cloud"},
        ]
        messages = []

        for match in matches:
            with self.subTest(match=list(match.items())):
                with self.assertRaises(ValueError) as exc:
                    selector_resolution.validate_assign_to(
                        {"match": match},
                        Path("/tmp/selector-resolution.yaml"),
                        "software.modules[0].assign_to",
                    )
                message = str(exc.exception)
                self.assertIn("software.modules[0].assign_to.match", message)
                self.assertIn("collide after trimming to normalized key 'tier'", message)
                messages.append(message)

        self.assertEqual(messages[0], messages[1])

    def test_validate_assign_to_normalizes_any_of_independent_of_clause_order(self):
        selectors = [
            {"any_of": [{" cluster ": " edge-1 "}, {"cluster": "cloud-1"}]},
            {"any_of": [{"cluster": "cloud-1"}, {" cluster ": " edge-1 "}]},
        ]
        results = [
            selector_resolution.validate_assign_to(
                selector,
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
                allow_any_of=True,
            )
            for selector in selectors
        ]

        expected_canonical = {
            "any_of": [
                {"match": [["cluster", "cloud-1"]]},
                {"match": [["cluster", "edge-1"]]},
            ]
        }
        self.assertEqual(
            results[0][0],
            {"any_of": [{"cluster": "edge-1"}, {"cluster": "cloud-1"}]},
        )
        self.assertEqual(
            results[1][0],
            {"any_of": [{"cluster": "cloud-1"}, {"cluster": "edge-1"}]},
        )
        resolved_vm_ids = []
        for assign_to, canonical, result_selector_id in results:
            self.assertEqual(canonical, expected_canonical)
            assignment = selector_resolution.reconcile_assignment(
                {"assign_to": assign_to, "selector_id": result_selector_id},
                self.resources,
                self.resources_by_vm_id,
            )
            resolved_vm_ids.append(assignment["resolved_vm_ids"])
        self.assertEqual(results[0][2], results[1][2])
        self.assertEqual(resolved_vm_ids, [[1, 2, 3], [1, 2, 3]])

    def test_validate_assign_to_rejects_match_and_any_of_together(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_assign_to(
                {
                    "match": {"cluster": "cloud-1"},
                    "any_of": [{"cluster": "edge-1"}],
                },
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
                allow_any_of=True,
            )
        self.assertIn("must contain exactly one of match or any_of", str(exc.exception))

    def test_validate_assign_to_rejects_duplicate_normalized_union_clause(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_assign_to(
                {
                    "any_of": [
                        {"cluster": "cloud-1"},
                        {" cluster ": " cloud-1 "},
                    ]
                },
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
                allow_any_of=True,
            )
        self.assertIn("duplicate normalized selector clause at indexes 0, 1", str(exc.exception))

    def test_validate_assign_to_rejects_trimmed_key_collision_in_union_clause(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_assign_to(
                {"any_of": [{"tier": "cloud", " tier ": "edge"}]},
                Path("/tmp/selector-resolution.yaml"),
                "software.modules[0].assign_to",
                allow_any_of=True,
            )
        message = str(exc.exception)
        self.assertIn("software.modules[0].assign_to.any_of[0]", message)
        self.assertIn("normalized key 'tier'", message)

    def test_scope_identity_repr_is_deterministic(self):
        scope_identity = {"selector_id": "sel_a", "kind": "selector"}
        self.assertEqual(
            selector_resolution.scope_identity_repr(scope_identity),
            '{"kind":"selector","selector_id":"sel_a"}',
        )

    def test_validate_scope_identities_accepts_canonical_shape(self):
        selector_resolution.validate_scope_identities(
            [
                {"kind": "vm", "vm_id": 1},
                {"kind": "cluster", "cluster_id": "cloud-1"},
                {"kind": "selector", "selector_id": "sel_cloud"},
            ],
            Path("/tmp/selector-resolution.yaml"),
            "normalized.software.modules[0].scope_identities",
        )

    def test_validate_scope_identities_rejects_missing_selector_scope(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_scope_identities(
                [{"kind": "vm", "vm_id": 1}],
                Path("/tmp/selector-resolution.yaml"),
                "normalized.software.modules[0].scope_identities",
            )
        self.assertIn("must include exactly one selector scope identity", str(exc.exception))

    def test_validate_selector_derivatives_rejects_selector_id_mismatch(self):
        with self.assertRaises(ValueError) as exc:
            selector_resolution.validate_selector_derivatives(
                {"selector": {"match": [["cluster", "cloud-1"]]}, "selector_id": "sel_other"},
                {"match": [["cluster", "cloud-1"]]},
                "sel_expected",
                Path("/tmp/selector-resolution.yaml"),
                "normalized.software.modules[0].selector",
                "normalized.software.modules[0].selector_id",
            )
        self.assertIn("must match canonical selector_id derived from assign_to.match", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
