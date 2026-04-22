"""Unit tests for legacy projection helpers extracted from yaml_parser."""

import unittest

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
        self.assertEqual(config["config_format"], "yaml")

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
