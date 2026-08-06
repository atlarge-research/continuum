"""Unit tests for software/benchmark domain validation helpers."""

import unittest
from pathlib import Path

from input.configuration import (
    benchmark_domain_validation,
    selector_assignment_validation,
    software_domain_validation,
)


class DomainValidationTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp/domain-validation.yaml")

    def test_validate_phase_domains_requires_benchmark_for_application_target(self):
        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                {"run": {"targets": ["application"]}},
                ["application"],
                self.path,
                "normalized_config",
            )
        self.assertIn("normalized_config.benchmark", str(exc.exception))
        self.assertIn("is required when run.targets includes application", str(exc.exception))

    def test_validate_phase_domains_rejects_benchmark_without_application_target(self):
        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                {"benchmark": {"pipeline": []}},
                ["infrastructure", "software"],
                self.path,
                "normalized_config",
            )
        self.assertIn("normalized_config.benchmark", str(exc.exception))
        self.assertIn("must be omitted when run.targets does not include application", str(exc.exception))

    def test_validate_phase_domains_preserves_empty_pipeline_diagnostic(self):
        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                {"benchmark": {"pipeline": []}},
                ["application"],
                self.path,
                "normalized_config",
            )

        self.assertIn("normalized_config.benchmark.pipeline", str(exc.exception))
        self.assertIn("must be a non-empty list", str(exc.exception))
        self.assertNotIn("exactly one executable stage", str(exc.exception))

    def test_validate_phase_domains_rejects_multiple_executable_stages(self):
        container = {
            "benchmark": {
                "pipeline": [
                    {
                        "id": "stage-1",
                        "type": "custom-stage",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": {},
                    },
                    {
                        "id": "stage-2",
                        "type": "custom-stage",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": {},
                    },
                ]
            }
        }

        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                container,
                ["application"],
                self.path,
                "normalized_config",
            )

        self.assertIn("normalized_config.benchmark.pipeline", str(exc.exception))
        self.assertIn("exactly one executable stage", str(exc.exception))
        self.assertIn("ordered multi-stage execution is not supported", str(exc.exception))
        self.assertIn("found 2 stages", str(exc.exception))

    def test_validate_software_rejects_unknown_module_type(self):
        software = {
            "modules": [
                {
                    "id": "invalid-main",
                    "type": "totally-unknown-module",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                }
            ]
        }
        with self.assertRaises(ValueError) as exc:
            software_domain_validation.validate_software(software, self.path, "software")
        self.assertIn("software.modules[0].type", str(exc.exception))
        self.assertIn("unknown module type", str(exc.exception))

    def test_selector_resolution_requires_infrastructure_resources(self):
        normalized = {
            "run": {"targets": ["software"]},
            "infrastructure": {},
            "software": {"modules": []},
        }
        with self.assertRaises(ValueError) as exc:
            selector_assignment_validation.validate_selector_resolution(
                normalized, self.path, "normalized_config"
            )
        self.assertIn("normalized_config.infrastructure.resources", str(exc.exception))
        self.assertIn("must be a list", str(exc.exception))

    def test_selector_resolution_requires_benchmark_for_application_target(self):
        normalized = {
            "run": {"targets": ["application"]},
            "infrastructure": {
                "resources": [
                    {
                        "vm_id": 1,
                        "cluster_id": "cloud-1",
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    }
                ]
            },
            "software": {
                "modules": [
                    {
                        "id": "k8s-main",
                        "type": "kubernetes",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "selector_id": "sel_cloud",
                        "config": {},
                    }
                ]
            },
        }
        with self.assertRaises(ValueError) as exc:
            selector_assignment_validation.validate_selector_resolution(
                normalized, self.path, "normalized_config"
            )
        self.assertIn("normalized_config.benchmark", str(exc.exception))
        self.assertIn("is required when run.targets includes application", str(exc.exception))

    def test_selector_resolution_rejects_module_without_config_mapping(self):
        normalized = {
            "run": {"targets": ["software"]},
            "infrastructure": {
                "resources": [
                    {
                        "vm_id": 1,
                        "cluster_id": "cloud-1",
                        "tags": {"tier": "cloud", "cluster": "cloud-1"},
                    }
                ]
            },
            "software": {
                "modules": [
                    {
                        "id": "k8s-main",
                        "type": "kubernetes",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "selector_id": "sel_cloud",
                    }
                ]
            },
        }
        with self.assertRaises(ValueError) as exc:
            selector_assignment_validation.validate_selector_resolution(
                normalized, self.path, "normalized_config"
            )
        self.assertIn("normalized_config.software.modules[0].config", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))

    def test_validate_software_requires_module_config_key(self):
        software = {
            "modules": [
                {
                    "id": "k8s-main",
                    "type": "kubernetes",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                }
            ]
        }
        with self.assertRaises(ValueError) as exc:
            software_domain_validation.validate_software(software, self.path, "software")
        self.assertIn("software.modules[0].config", str(exc.exception))
        self.assertIn("is required", str(exc.exception))

    def test_validate_phase_domains_rejects_null_stage_tags(self):
        container = {
            "benchmark": {
                "pipeline": [
                    {
                        "id": "stage-1",
                        "type": "custom-stage",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": None,
                        "config": {},
                    }
                ]
            }
        }
        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                container,
                ["application"],
                self.path,
                "normalized_config",
            )
        self.assertIn("normalized_config.benchmark.pipeline[0].tags", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))

    def test_validate_phase_domains_rejects_null_stage_config(self):
        container = {
            "benchmark": {
                "pipeline": [
                    {
                        "id": "stage-1",
                        "type": "custom-stage",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": None,
                    }
                ]
            }
        }
        with self.assertRaises(ValueError) as exc:
            benchmark_domain_validation.validate_phase_domains(
                container,
                ["application"],
                self.path,
                "normalized_config",
            )
        self.assertIn("normalized_config.benchmark.pipeline[0].config", str(exc.exception))
        self.assertIn("must be a mapping", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
