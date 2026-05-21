"""Unit tests for orchestration schema helper mappings."""

import unittest
from types import SimpleNamespace

from infrastructure import orchestration_schema


class OrchestrationSchemaTests(unittest.TestCase):
    def test_guest_login_name_shortens_long_names_deterministically(self):
        node_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"

        derived = orchestration_schema.guest_login_name(node_name)

        self.assertLessEqual(len(derived), 32)
        self.assertEqual(derived, orchestration_schema.guest_login_name(node_name))
        self.assertNotEqual(
            derived,
            orchestration_schema.guest_login_name(node_name + "_other"),
        )

    def test_base_images_by_host_returns_raw_names_for_selected_normalized_identities(self):
        machine = SimpleNamespace(
            is_local=True,
            name_sanitized="local",
            base_names=[
                "base0_matthijs",
                "base_cloud_kubernetes_0_matthijs",
                "base_cloud_kubernetes_1_matthijs",
            ],
        )

        result = orchestration_schema.base_images_by_host(
            [machine],
            ["base", "base_cloud_kubernetes"],
        )

        self.assertEqual(
            result,
            {
                "localhost": [
                    "base0_matthijs",
                    "base_cloud_kubernetes_0_matthijs",
                    "base_cloud_kubernetes_1_matthijs",
                ]
            },
        )

    def test_tier_base_image_by_host_falls_back_to_single_legacy_base_name(self):
        machine = SimpleNamespace(
            is_local=True,
            name_sanitized="local",
            base_names=["base0_matthijs"],
            cloud_controller=0,
            clouds=1,
            edges=0,
            endpoints=0,
        )

        result = orchestration_schema.tier_base_image_by_host([machine], "cloud")

        self.assertEqual(result, {"localhost": "base0_matthijs"})


if __name__ == "__main__":
    unittest.main()
