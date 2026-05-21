"""Unit tests for shared module contract validation helpers."""

import unittest
from unittest import mock

from input.configuration import module_contract_validation, module_registry


class ModuleContractValidationTests(unittest.TestCase):
    def test_exclusive_violation_detected_on_shared_scope(self):
        modules = [
            {
                "id": "a-main",
                "type": "a",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_shared"}],
            },
            {
                "id": "b-main",
                "type": "b",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_shared"}],
            },
        ]

        def fake_get_spec(module_type):
            if module_type == "a":
                return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
            if module_type == "b":
                return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
            return None

        with mock.patch("input.configuration.module_registry.get_spec", side_effect=fake_get_spec):
            evaluation = module_contract_validation.evaluate_module_contracts(
                modules,
                {"software"},
                require_endpoint_runtime=False,
            )

        violations = [v for v in evaluation["violations"] if v["kind"] == "exclusive"]
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["module"]["id"], "b-main")
        self.assertEqual(violations[0]["other_module"]["id"], "a-main")
        self.assertEqual(violations[0]["capability"], "slot.synthetic")
        self.assertEqual(violations[0]["scope_identity"], {"kind": "selector", "selector_id": "sel_shared"})

    def test_exclusive_violation_skipped_on_disjoint_scope(self):
        modules = [
            {
                "id": "a-main",
                "type": "a",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_a"}],
            },
            {
                "id": "b-main",
                "type": "b",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_b"}],
            },
        ]

        def fake_get_spec(module_type):
            if module_type == "a":
                return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
            if module_type == "b":
                return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
            return None

        with mock.patch("input.configuration.module_registry.get_spec", side_effect=fake_get_spec):
            evaluation = module_contract_validation.evaluate_module_contracts(
                modules,
                {"software"},
                require_endpoint_runtime=False,
            )

        self.assertFalse([v for v in evaluation["violations"] if v["kind"] == "exclusive"])

    def test_conflict_violation_treats_missing_scope_as_global_when_enabled(self):
        modules = [
            {"id": "a-main", "type": "a"},
            {"id": "b-main", "type": "b"},
        ]

        def fake_get_spec(module_type):
            if module_type == "a":
                return module_registry.ModuleSpec(scope="addon", conflicts=("cap.synthetic",))
            if module_type == "b":
                return module_registry.ModuleSpec(scope="addon", provides=("cap.synthetic",))
            return None

        with mock.patch("input.configuration.module_registry.get_spec", side_effect=fake_get_spec):
            evaluation = module_contract_validation.evaluate_module_contracts(
                modules,
                {"software"},
                require_endpoint_runtime=False,
                treat_missing_scope_as_global=True,
            )

        conflicts = [v for v in evaluation["violations"] if v["kind"] == "conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["scope_identity"], None)

    def test_requires_violation_and_endpoint_runtime_violation(self):
        modules = [
            {
                "id": "openfaas-main",
                "type": "openfaas",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_shared"}],
            }
        ]

        def fake_get_spec(module_type):
            if module_type == "openfaas":
                return module_registry.ModuleSpec(
                    scope="addon",
                    requires=("orchestrator.kubernetes",),
                )
            return None

        with mock.patch("input.configuration.module_registry.get_spec", side_effect=fake_get_spec):
            evaluation = module_contract_validation.evaluate_module_contracts(
                modules,
                {"software"},
                require_endpoint_runtime=True,
            )

        violation_kinds = [v["kind"] for v in evaluation["violations"]]
        self.assertIn("requires", violation_kinds)
        self.assertIn("endpoint_runtime_missing", violation_kinds)

    def test_requires_violation_detected_on_disjoint_scope(self):
        modules = [
            {
                "id": "provider-main",
                "type": "provider",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_cloud"}],
            },
            {
                "id": "consumer-main",
                "type": "consumer",
                "scope_identities": [{"kind": "selector", "selector_id": "sel_edge"}],
            },
        ]

        def fake_get_spec(module_type):
            if module_type == "provider":
                return module_registry.ModuleSpec(scope="orchestrator", provides=("cap.synthetic",))
            if module_type == "consumer":
                return module_registry.ModuleSpec(scope="addon", requires=("cap.synthetic",))
            return None

        with mock.patch("input.configuration.module_registry.get_spec", side_effect=fake_get_spec):
            evaluation = module_contract_validation.evaluate_module_contracts(
                modules,
                {"software"},
                require_endpoint_runtime=False,
            )

        violations = [
            violation
            for violation in evaluation["violations"]
            if violation["kind"] == "requires_scope"
        ]
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["module"]["id"], "consumer-main")
        self.assertEqual(violations[0]["required_capability"], "cap.synthetic")

    def test_endpoint_runtime_provider_must_target_endpoint_resources(self):
        modules = [
            {
                "id": "k8s-main",
                "type": "kubernetes",
                "resolved_vm_ids": [1],
                "scope_identities": [{"kind": "vm", "vm_id": 1}],
            },
            {
                "id": "endpoint-runtime-main",
                "type": "endpoint_runtime",
                "resolved_vm_ids": [1],
                "scope_identities": [{"kind": "vm", "vm_id": 1}],
            },
        ]

        evaluation = module_contract_validation.evaluate_module_contracts(
            modules,
            {"software"},
            require_endpoint_runtime=True,
            endpoint_resource_vm_ids={2},
        )

        violations = [
            violation
            for violation in evaluation["violations"]
            if violation["kind"] == "endpoint_runtime_not_on_endpoint"
        ]
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["module"]["id"], "endpoint-runtime-main")

    def test_module_identity_fallback_for_missing_fields(self):
        self.assertEqual(module_contract_validation.module_identity({}), ("unknown", "unknown"))


if __name__ == "__main__":
    unittest.main()
