"""Unit tests for software module registry contracts."""

import unittest

from input.configuration import module_registry


class ModuleRegistryTests(unittest.TestCase):
    def test_supported_types_match_registry_keys(self):
        self.assertEqual(set(module_registry.SUPPORTED_MODULE_TYPES), set(module_registry.MODULE_REGISTRY))

    def test_scope_catalogs_match_registry(self):
        orchestrators = {
            module_type
            for module_type, spec in module_registry.MODULE_REGISTRY.items()
            if spec.scope == "orchestrator"
        }
        addons = {
            module_type
            for module_type, spec in module_registry.MODULE_REGISTRY.items()
            if spec.scope == "addon"
        }
        self.assertEqual(set(module_registry.ORCHESTRATOR_MODULE_TYPES), orchestrators)
        self.assertEqual(set(module_registry.ADDON_MODULE_TYPES), addons)

    def test_all_required_capabilities_are_provided(self):
        provided_capabilities = set()
        for spec in module_registry.MODULE_REGISTRY.values():
            provided_capabilities.update(spec.provides)
            provided_capabilities.update(spec.exclusive_provides)

        for module_type, spec in module_registry.MODULE_REGISTRY.items():
            for requirement in spec.requires:
                self.assertIn(
                    requirement,
                    provided_capabilities,
                    "module '%s' requires unknown capability '%s'" % (module_type, requirement),
                )

    def test_lookup_returns_none_for_unknown_type(self):
        self.assertIsNone(module_registry.get_spec("does-not-exist"))

    def test_kubecontrol_and_kube_kata_expose_prefetch_catalog_refs(self):
        kubecontrol = module_registry.get_spec("kubecontrol")
        kube_kata = module_registry.get_spec("kube_kata")
        self.assertIsNotNone(kubecontrol)
        self.assertIsNotNone(kube_kata)
        self.assertIn("kube.control_plane", kubecontrol.image_catalog_refs)
        self.assertIn("kube.control_plane", kube_kata.image_catalog_refs)
        self.assertIn("kube.kata_jaeger", kube_kata.image_catalog_refs)


if __name__ == "__main__":
    unittest.main()
