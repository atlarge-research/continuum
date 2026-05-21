"""Unit tests for selector/scope helper utilities."""

import unittest

from input.configuration import selector_scope


class SelectorScopeTests(unittest.TestCase):
    def test_canonical_selector_is_deterministic(self):
        canonical, selector_id = selector_scope.canonical_selector({"b": "2", "a": "1"})
        self.assertEqual(canonical, {"match": [["a", "1"], ["b", "2"]]})
        self.assertTrue(selector_id.startswith("sel_"))

    def test_first_overlap_prefers_vm_scope(self):
        left = [
            {"kind": "vm", "vm_id": 3},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_a"},
        ]
        right = [
            {"kind": "vm", "vm_id": 3},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_b"},
        ]
        self.assertEqual(selector_scope.first_overlap_scope_identity(left, right), {"kind": "vm", "vm_id": 3})

    def test_first_overlap_cluster_scope(self):
        left = [
            {"kind": "vm", "vm_id": 1},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_a"},
        ]
        right = [
            {"kind": "vm", "vm_id": 2},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_b"},
        ]
        self.assertEqual(
            selector_scope.first_overlap_scope_identity(left, right),
            {"kind": "cluster", "cluster_id": "cloud-1"},
        )

    def test_first_overlap_selector_scope(self):
        left = [
            {"kind": "vm", "vm_id": 1},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_same"},
        ]
        right = [
            {"kind": "vm", "vm_id": 2},
            {"kind": "cluster", "cluster_id": "edge-1"},
            {"kind": "selector", "selector_id": "sel_same"},
        ]
        self.assertEqual(
            selector_scope.first_overlap_scope_identity(left, right),
            {"kind": "selector", "selector_id": "sel_same"},
        )

    def test_first_overlap_disjoint_returns_none(self):
        left = [
            {"kind": "vm", "vm_id": 1},
            {"kind": "cluster", "cluster_id": "cloud-1"},
            {"kind": "selector", "selector_id": "sel_a"},
        ]
        right = [
            {"kind": "vm", "vm_id": 2},
            {"kind": "cluster", "cluster_id": "edge-1"},
            {"kind": "selector", "selector_id": "sel_b"},
        ]
        self.assertIsNone(selector_scope.first_overlap_scope_identity(left, right))

    def test_resolve_selector_vm_ids_returns_sorted_matches(self):
        resources = [
            {"vm_id": 3, "tags": {"tier": "cloud", "cluster": "cloud-1"}},
            {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-2"}},
            {"vm_id": 2, "tags": {"tier": "edge", "cluster": "edge-1"}},
        ]
        vm_ids = selector_scope.resolve_selector_vm_ids(resources, {"tier": "cloud"})
        self.assertEqual(vm_ids, [1, 3])

    def test_resolve_selector_vm_ids_rejects_missing_tags(self):
        with self.assertRaises(ValueError) as exc:
            selector_scope.resolve_selector_vm_ids([{"vm_id": 1}], {"tier": "cloud"})
        self.assertIn("resources[0].tags", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
