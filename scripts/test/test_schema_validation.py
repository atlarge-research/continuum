"""Unit tests for shared schema validation helpers."""

import unittest
from pathlib import Path

from input.configuration import (
    infrastructure_schema_validation,
    provider_schema_validation,
    run_schema_validation,
)


class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp/schema-validation.yaml")
        self.allowed_targets = {"infrastructure", "software", "application"}
        self.allowed_image_prefetch_modes = {"off", "on"}
        self.allowed_tiers = ("cloud", "edge", "endpoint")
        self.network_override_keys = {"cloud_latency_avg", "cloud_location"}
        self.network_override_numeric_keys = ("cloud_latency_avg",)
        self.network_override_string_keys = ("cloud_location",)

    def test_validate_run_normalizes_and_defaults_image_prefetch(self):
        run = {
            "targets": [" infrastructure ", "software"],
            "dry_run": False,
            "clean": True,
        }
        targets = run_schema_validation.validate_run(
            run,
            self.path,
            "run",
            self.allowed_targets,
            self.allowed_image_prefetch_modes,
        )
        self.assertEqual(targets, ["infrastructure", "software"])
        self.assertEqual(run["image_prefetch"], "off")
        self.assertFalse(run["prepare_for_resume"])

    def test_validate_run_defaults_clean_and_dry_run(self):
        run = {"targets": ["software"]}
        targets = run_schema_validation.validate_run(
            run,
            self.path,
            "run",
            self.allowed_targets,
            self.allowed_image_prefetch_modes,
        )
        self.assertEqual(targets, ["software"])
        self.assertFalse(run["dry_run"])
        self.assertFalse(run["clean"])
        self.assertEqual(run["image_prefetch"], "off")
        self.assertFalse(run["prepare_for_resume"])

    def test_validate_run_accepts_prepare_for_resume_for_infra_only(self):
        run = {"targets": ["infrastructure"], "prepare_for_resume": True}
        targets = run_schema_validation.validate_run(
            run,
            self.path,
            "run",
            self.allowed_targets,
            self.allowed_image_prefetch_modes,
        )
        self.assertEqual(targets, ["infrastructure"])
        self.assertTrue(run["prepare_for_resume"])

    def test_validate_run_rejects_non_boolean_prepare_for_resume(self):
        run = {"targets": ["infrastructure"], "prepare_for_resume": "true"}
        with self.assertRaises(ValueError) as exc:
            run_schema_validation.validate_run(
                run,
                self.path,
                "run",
                self.allowed_targets,
                self.allowed_image_prefetch_modes,
            )
        self.assertIn("run.prepare_for_resume", str(exc.exception))
        self.assertIn("must be boolean", str(exc.exception))

    def test_validate_run_rejects_prepare_for_resume_outside_infra_only(self):
        run = {
            "targets": ["infrastructure", "software"],
            "prepare_for_resume": True,
        }
        with self.assertRaises(ValueError) as exc:
            run_schema_validation.validate_run(
                run,
                self.path,
                "run",
                self.allowed_targets,
                self.allowed_image_prefetch_modes,
            )
        self.assertIn("run.prepare_for_resume", str(exc.exception))
        self.assertIn("run.targets is exactly [infrastructure]", str(exc.exception))

    def test_validate_run_rejects_invalid_image_prefetch(self):
        run = {"targets": ["infrastructure"], "image_prefetch": "always"}
        with self.assertRaises(ValueError) as exc:
            run_schema_validation.validate_run(
                run,
                self.path,
                "run",
                self.allowed_targets,
                self.allowed_image_prefetch_modes,
            )
        self.assertIn("run.image_prefetch", str(exc.exception))
        self.assertIn("must be one of off, on", str(exc.exception))

    def test_validate_infrastructure_rejects_legacy_image_prefetch_location(self):
        infrastructure = {"image_prefetch": "on", "clusters": []}
        with self.assertRaises(ValueError) as exc:
            infrastructure_schema_validation.validate_infrastructure(
                infrastructure,
                self.path,
                "infrastructure",
                self.allowed_tiers,
                self.network_override_keys,
                self.network_override_numeric_keys,
                self.network_override_string_keys,
                1,
                1.0,
                1.0,
                0.0,
                lambda clusters: [],
            )
        self.assertIn("infrastructure.image_prefetch", str(exc.exception))
        self.assertIn("use run.image_prefetch", str(exc.exception))

    def test_validate_infrastructure_normalizes_clusters_and_resources(self):
        calls = []

        def build_resources(clusters):
            calls.append(clusters)
            return [{"vm_id": 1, "cluster_id": "cloud-1"}]

        infrastructure = {
            "clusters": [
                {
                    "id": " cloud-1 ",
                    "tier": "cloud",
                    "resources": {
                        "vms": {
                            "count": 1,
                            "spec": {"cores": 2, "memory_gb": 4, "cpu_quota": 1},
                        }
                    },
                }
            ]
        }
        infrastructure_schema_validation.validate_infrastructure(
            infrastructure,
            self.path,
            "infrastructure",
            self.allowed_tiers,
            self.network_override_keys,
            self.network_override_numeric_keys,
            self.network_override_string_keys,
            1,
            1.0,
            1.0,
            0.0,
            build_resources,
        )
        self.assertEqual(infrastructure["clusters"][0]["id"], "cloud-1")
        self.assertEqual(infrastructure["clusters"][0]["resources"]["vms"]["spec"]["cores"], 2)
        self.assertEqual(
            infrastructure["network"],
            {"emulation": False, "wireless_preset": "4g", "overrides": {}},
        )
        self.assertEqual(infrastructure["resources"], [{"vm_id": 1, "cluster_id": "cloud-1"}])
        self.assertEqual(len(calls), 1)

    def test_validate_infrastructure_rejects_null_network(self):
        infrastructure = {
            "clusters": [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 0, "spec": {}}},
                }
            ],
            "network": None,
        }
        with self.assertRaises(ValueError) as exc:
            infrastructure_schema_validation.validate_infrastructure(
                infrastructure,
                self.path,
                "infrastructure",
                self.allowed_tiers,
                self.network_override_keys,
                self.network_override_numeric_keys,
                self.network_override_string_keys,
                1,
                1.0,
                1.0,
                0.0,
                lambda clusters: [],
            )
        self.assertIn("infrastructure.network", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))

    def test_validate_infrastructure_rejects_null_network_overrides(self):
        infrastructure = {
            "clusters": [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 0, "spec": {}}},
                }
            ],
            "network": {"overrides": None},
        }
        with self.assertRaises(ValueError) as exc:
            infrastructure_schema_validation.validate_infrastructure(
                infrastructure,
                self.path,
                "infrastructure",
                self.allowed_tiers,
                self.network_override_keys,
                self.network_override_numeric_keys,
                self.network_override_string_keys,
                1,
                1.0,
                1.0,
                0.0,
                lambda clusters: [],
            )
        self.assertIn("infrastructure.network.overrides", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))

    def test_validate_provider_rejects_invalid_ip_middle(self):
        provider = {
            "name": "qemu",
            "config": {
                "ip": {"prefix": "192.168", "middle": 999, "middle_base": 90},
            },
        }
        with self.assertRaises(ValueError) as exc:
            provider_schema_validation.validate_provider(provider, self.path, "provider")
        self.assertIn("provider.config.ip.middle", str(exc.exception))
        self.assertIn("must be integer in [0,255]", str(exc.exception))

    def test_validate_provider_rejects_unknown_top_level_key(self):
        provider = {
            "name": "qemu",
            "config": {},
            "unexpected": True,
        }
        with self.assertRaises(ValueError) as exc:
            provider_schema_validation.validate_provider(provider, self.path, "provider")
        self.assertIn("provider.unexpected", str(exc.exception))
        self.assertIn("unexpected key for schema v1", str(exc.exception))

    def test_validate_provider_rejects_unknown_ip_key(self):
        provider = {
            "name": "qemu",
            "config": {
                "ip": {
                    "prefix": "192.168",
                    "middle": 100,
                    "middle_base": 90,
                    "unknown": "value",
                },
            },
        }
        with self.assertRaises(ValueError) as exc:
            provider_schema_validation.validate_provider(provider, self.path, "provider")
        self.assertIn("provider.config.ip.unknown", str(exc.exception))
        self.assertIn("unexpected key for schema v1", str(exc.exception))

    def test_validate_provider_defaults_optional_config_values(self):
        provider = {"name": "qemu", "config": {}}
        provider_schema_validation.validate_provider(provider, self.path, "provider")
        cfg = provider["config"]
        self.assertEqual(cfg["base_path"], provider_schema_validation.os.getenv("HOME", "~"))
        self.assertFalse(cfg["cpu_pin"])
        self.assertFalse(cfg["netperf"])
        self.assertFalse(cfg["delete_on_exit"])
        self.assertEqual(cfg["external_physical_machines"], [])
        self.assertEqual(cfg["ip"]["prefix"], "192.168")
        self.assertEqual(cfg["ip"]["middle"], 100)
        self.assertEqual(cfg["ip"]["middle_base"], 90)

    def test_validate_provider_rejects_null_config(self):
        provider = {"name": "qemu", "config": None}
        with self.assertRaises(ValueError) as exc:
            provider_schema_validation.validate_provider(provider, self.path, "provider")
        self.assertIn("provider.config", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))

    def test_validate_provider_rejects_null_ip_config(self):
        provider = {"name": "qemu", "config": {"ip": None}}
        with self.assertRaises(ValueError) as exc:
            provider_schema_validation.validate_provider(provider, self.path, "provider")
        self.assertIn("provider.config.ip", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
