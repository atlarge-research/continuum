"""Unit tests for legacy projection helpers extracted from yaml_parser."""

import os
import unittest
from unittest import mock

from input.configuration import legacy_projection


class LegacyProjectionTests(unittest.TestCase):
    def _cluster(self, cluster_id, tier, count, cores, memory_gb):
        return {
            "id": cluster_id,
            "tier": tier,
            "resources": {
                "vms": {
                    "count": count,
                    "spec": {
                        "cores": cores,
                        "memory_gb": memory_gb,
                        "cpu_quota": 1.0,
                        "storage_read_mbps": 0.0,
                        "storage_write_mbps": 0.0,
                    },
                }
            },
        }

    def _normalized(self):
        return {
            "run": {
                "targets": ["infrastructure", "software"],
                "dry_run": False,
                "clean": True,
                "image_prefetch": "on",
                "prepare_for_resume": False,
            },
            "provider": {
                "name": "qemu",
                "config": {
                    "base_path": "/tmp/continuum",
                    "cpu_pin": False,
                    "external_physical_machines": [],
                    "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                    "netperf": False,
                    "delete_on_exit": False,
                },
            },
            "infrastructure": {
                "clusters": [
                    self._cluster("cloud-1", "cloud", 1, 2, 4.0),
                    self._cluster("endpoint-1", "endpoint", 1, 1, 2.0),
                ],
                "network": {
                    "emulation": False,
                    "wireless_preset": "4g",
                    "overrides": {"cloud_location": "nl", "cloud_latency_avg": 10},
                },
            },
            "software": {
                "modules": [
                    {
                        "id": "none-main",
                        "type": "none",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "config": {},
                    }
                ]
            },
            "benchmark": {},
        }

    def test_infra_only_mapping(self):
        self.assertTrue(legacy_projection.infra_only_from_targets(["infrastructure"]))
        self.assertFalse(
            legacy_projection.infra_only_from_targets(["infrastructure", "software"])
        )

    def test_aggregate_clusters_for_legacy_rejects_inconsistent_spec(self):
        clusters = [
            self._cluster("cloud-1", "cloud", 1, 2, 4.0),
            self._cluster("cloud-2", "cloud", 1, 4, 8.0),
        ]
        with self.assertRaises(ValueError) as exc:
            legacy_projection.aggregate_clusters_for_legacy(clusters, ("cloud", "edge", "endpoint"))
        self.assertIn("inconsistent VM spec", str(exc.exception))
        self.assertIn("cloud", str(exc.exception))

    def test_to_legacy_config_projects_canonical_domains(self):
        config = legacy_projection.to_legacy_config(
            self._normalized(),
            ("cloud", "edge", "endpoint"),
            ("cloud_latency_avg", "cloud_location"),
        )
        self.assertEqual(config["infrastructure"]["provider"], "qemu")
        self.assertEqual(config["infrastructure"]["cloud_nodes"], 1)
        self.assertEqual(config["infrastructure"]["endpoint_nodes"], 1)
        self.assertEqual(config["infrastructure"]["cloud_location"], "nl")
        self.assertEqual(config["infrastructure"]["cloud_latency_avg"], 10)
        self.assertEqual(config["mode"], "cloud")
        self.assertEqual(config["domains"]["run"]["image_prefetch"], "on")
        self.assertFalse(config["domains"]["run"]["prepare_for_resume"])
        self.assertEqual(config["config_format"], "yaml")

    def test_to_legacy_config_projects_prepare_for_resume(self):
        normalized = self._normalized()
        normalized["run"]["targets"] = ["infrastructure"]
        normalized["run"]["prepare_for_resume"] = True

        config = legacy_projection.to_legacy_config(
            normalized,
            ("cloud", "edge", "endpoint"),
            ("cloud_latency_avg", "cloud_location"),
        )

        self.assertTrue(config["domains"]["run"]["prepare_for_resume"])

    def test_projects_only_validated_provider_keys_in_sorted_order(self):
        normalized = self._normalized()
        provider_cfg = normalized["provider"]["config"]
        provider_cfg.update(
            {
                "aws_region": "eu-west-1",
                "aws_access_keys": "dummy-access-key",
                "provider_list": ["one", "two"],
                "unvalidated": "must-not-project",
            }
        )

        config = legacy_projection.to_legacy_config(
            normalized,
            ("cloud", "edge", "endpoint"),
            ("cloud_latency_avg", "cloud_location"),
            (
                "provider_list",
                "aws_region",
                "aws_access_keys",
            ),
        )

        infrastructure = config["infrastructure"]
        projected_keys = [
            key
            for key in infrastructure
            if key in {"aws_access_keys", "aws_region", "provider_list"}
        ]
        self.assertEqual(
            projected_keys,
            ["aws_access_keys", "aws_region", "provider_list"],
        )
        self.assertNotIn("unvalidated", infrastructure)
        self.assertEqual(infrastructure["base_path"], "/tmp/continuum")
        infrastructure["provider_list"].append("runtime-only")
        self.assertEqual(provider_cfg["provider_list"], ["one", "two"])

    def _assert_provider_runtime_key_collision(self, key):
        normalized = self._normalized()
        normalized["provider"]["config"][key] = "provider-owned-value"

        with self.assertRaises(ValueError) as exc:
            legacy_projection.to_legacy_config(
                normalized,
                ("cloud", "edge", "endpoint"),
                ("cloud_latency_avg", "cloud_location"),
                (key,),
            )

        self.assertIn(key, str(exc.exception))

    def test_rejects_provider_collision_with_derived_runtime_key(self):
        self._assert_provider_runtime_key_collision("cloud_nodes")

    def test_rejects_provider_collision_with_core_runtime_key(self):
        self._assert_provider_runtime_key_collision("delete")

    def test_rejects_provider_collision_with_absent_network_override_key(self):
        normalized = self._normalized()
        normalized["infrastructure"]["network"]["overrides"].pop("cloud_latency_avg")
        self.assertNotIn(
            "cloud_latency_avg",
            normalized["infrastructure"]["network"]["overrides"],
        )
        normalized["provider"]["config"]["cloud_latency_avg"] = "provider-owned-value"

        with self.assertRaises(ValueError) as exc:
            legacy_projection.to_legacy_config(
                normalized,
                ("cloud", "edge", "endpoint"),
                ("cloud_latency_avg", "cloud_location"),
                ("cloud_latency_avg",),
            )

        self.assertIn("cloud_latency_avg", str(exc.exception))

    def test_to_legacy_config_expands_only_home_based_base_paths(self):
        normalized = self._normalized()
        normalized["provider"]["config"]["base_path"] = "~"

        with mock.patch.dict(os.environ, {"HOME": "/tmp/expanded-home"}):
            config = legacy_projection.to_legacy_config(
                normalized,
                ("cloud", "edge", "endpoint"),
                ("cloud_latency_avg", "cloud_location"),
            )

        self.assertEqual(config["infrastructure"]["base_path"], "/tmp/expanded-home")
        self.assertEqual(normalized["provider"]["config"]["base_path"], "~")

        normalized["provider"]["config"]["base_path"] = "relative/runtime"
        config = legacy_projection.to_legacy_config(
            normalized,
            ("cloud", "edge", "endpoint"),
            ("cloud_latency_avg", "cloud_location"),
        )
        self.assertEqual(config["infrastructure"]["base_path"], "relative/runtime")

    def test_to_legacy_config_rejects_missing_required_paths(self):
        normalized = self._normalized()
        normalized["provider"]["config"].pop("base_path")
        with self.assertRaises(ValueError) as exc:
            legacy_projection.to_legacy_config(
                normalized,
                ("cloud", "edge", "endpoint"),
                ("cloud_latency_avg", "cloud_location"),
            )
        self.assertIn("provider.config.base_path", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
