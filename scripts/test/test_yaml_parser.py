"""Regression tests for YAML parser PR-3 hard-cutover contracts."""

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from input import input as input_module
from input.configuration import module_registry, selector_scope


class YamlParserTests(unittest.TestCase):
    class _FakeHostIpSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, _target):
            return None

        def getsockname(self):
            return ("127.0.0.1", 5000)

    def setUp(self):
        self._socket_patcher = mock.patch(
            "input.configuration.runtime_module_loader.socket_lib.socket",
            side_effect=lambda *_args, **_kwargs: self._FakeHostIpSocket(),
        )
        self._socket_patcher.start()

    def tearDown(self):
        self._socket_patcher.stop()

    def _write(self, path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as filep:
            yaml.safe_dump(payload, filep, sort_keys=False)

    def _build_triplet(
        self,
        root: Path,
        base_path: str,
        run_targets=None,
        run_image_prefetch: str | None = None,
        run_prepare_for_resume: bool | str | None = None,
        clusters=None,
        modules=None,
        benchmark=None,
        include_workload: bool = False,
    ):
        run_targets = run_targets or ["infrastructure", "software"]
        clusters = clusters or [
            {
                "id": "cloud-1",
                "tier": "cloud",
                "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 4}}},
            }
        ]
        modules = modules or [
            {
                "id": "none-main",
                "type": "none",
                "assign_to": {"match": {"cluster": "cloud-1"}},
                "config": {},
            }
        ]

        env = {
            "schema_version": 1,
            "kind": "ContinuumEnvironment",
            "provider": {
                "name": "qemu",
                "config": {
                    "base_path": base_path,
                    "cpu_pin": False,
                    "external_physical_machines": [],
                    "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                    "netperf": False,
                    "delete_on_exit": False,
                },
            },
        }
        sw = {
            "schema_version": 1,
            "kind": "ContinuumSoftware",
            "software": {"modules": modules},
        }
        run = {"targets": run_targets}
        if run_image_prefetch is not None:
            run["image_prefetch"] = run_image_prefetch
        if run_prepare_for_resume is not None:
            run["prepare_for_resume"] = run_prepare_for_resume

        exp = {
            "schema_version": 1,
            "kind": "ContinuumExperiment",
            "use": {"environment": "env", "software": "sw"},
            "run": run,
            "infrastructure": {
                "clusters": clusters,
                "network": {"emulation": False, "wireless_preset": "4g", "overrides": {}},
            },
        }
        if benchmark is not None:
            exp["benchmark"] = benchmark
        if include_workload:
            exp["workload"] = {"name": "legacy", "config": {}}

        env_path = root / "env.yaml"
        sw_path = root / "sw.yaml"
        exp_path = root / "exp.yaml"
        self._write(env_path, env)
        self._write(sw_path, sw)
        self._write(exp_path, exp)
        return exp_path, sw_path

    def _parse_error(self, config_path: Path) -> str:
        parser = argparse.ArgumentParser(prog="yaml-parser-test")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                input_module.start(parser, str(config_path))
        return stderr.getvalue()

    def _image_classification_stage(self):
        return {
            "id": "classify",
            "type": "image_classification",
            "assign_to": {"match": {"cluster": "cloud-1"}},
            "tags": {"benchmark.role": "classify"},
            "config": {
                "frequency": 2,
                "duration": 120,
                "applications_per_worker": 2,
                "application_worker_cpu": 0.5,
                "application_worker_memory": 1.0,
                "application_endpoint_cpu": 0.5,
                "application_endpoint_memory": 1.0,
            },
        }

    def _image_classification_clusters(self):
        return [
            {
                "id": "cloud-1",
                "tier": "cloud",
                "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 4}}},
            },
            {
                "id": "endpoint-1",
                "tier": "endpoint",
                "resources": {"vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 2}}},
            },
        ]

    def _image_classification_modules(self):
        return [
            {
                "id": "none-main",
                "type": "none",
                "assign_to": {"match": {"cluster": "cloud-1"}},
                "config": {},
            },
            {
                "id": "endpoint-runtime-main",
                "type": "endpoint_runtime",
                "assign_to": {"match": {"tier": "endpoint"}},
                "config": {},
            },
        ]

    def test_valid_benchmark_pipeline_parses(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )

            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            stages = cfg["domains"]["benchmark"]["pipeline"]
            self.assertEqual(stages[0]["id"], "generate")
            self.assertTrue(stages[0]["selector_id"].startswith("sel_"))
            self.assertEqual(stages[0]["resolved_vm_ids"], [1])
            self.assertTrue(stages[0]["scope_identities"])
            self.assertNotIn("workload", cfg["domains"])
            self.assertFalse(cfg["module"]["application"])

    def test_application_requires_benchmark_pipeline(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                benchmark=None,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark", stderr)
            self.assertIn("is required when run.targets includes application", stderr)

    def test_legacy_benchmark_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                benchmark={"name": "default", "config": {}},
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.config", stderr)
            self.assertIn("unexpected key for schema v1", stderr)

    def test_workload_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir, include_workload=True)
            stderr = self._parse_error(exp_path)
            self.assertIn("workload", stderr)
            self.assertIn("unexpected key for schema v1", stderr)

    def test_benchmark_reserved_tag_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "stage-1",
                        "type": "generator",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"role": "writer"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].tags.role", stderr)
            self.assertIn("reserved benchmark tag key 'role' cannot be overwritten", stderr)

    def test_duplicate_benchmark_stage_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "dup",
                        "type": "generator",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": {},
                    },
                    {
                        "id": "dup",
                        "type": "processor",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": {},
                    },
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[1].id", stderr)
            self.assertIn("duplicate benchmark stage id", stderr)

    def test_selector_resolution_failure_reports_pipeline_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "stage-1",
                        "type": "generator",
                        "assign_to": {"match": {"cluster": "missing"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].assign_to.match", stderr)
            self.assertIn("selector resolves to no infrastructure resources", stderr)

    def test_known_stage_type_config_contract_accepts_valid_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {"pipeline": [self._image_classification_stage()]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            self.assertEqual(cfg["domains"]["benchmark"]["pipeline"][0]["type"], "image_classification")

    def test_known_stage_type_config_contract_rejects_missing_required_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stage = self._image_classification_stage()
            del stage["config"]["application_worker_cpu"]
            benchmark = {"pipeline": [stage]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].config.application_worker_cpu", stderr)
            self.assertIn("is required for benchmark stage type", stderr)

    def test_known_stage_type_config_contract_rejects_invalid_value_type(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stage = self._image_classification_stage()
            stage["config"]["applications_per_worker"] = True
            benchmark = {"pipeline": [stage]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].config.applications_per_worker", stderr)
            self.assertIn("must be integer >= 1", stderr)

    def test_known_stage_type_config_contract_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stage = self._image_classification_stage()
            stage["config"]["unexpected"] = 1
            benchmark = {"pipeline": [stage]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].config.unexpected", stderr)
            self.assertIn("unexpected key for benchmark stage type", stderr)

    def test_selector_id_is_deterministic_and_vm_ids_are_sorted(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-b",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
                {
                    "id": "cloud-a",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 2, "spec": {"cores": 2, "memory_gb": 2}}},
                },
            ]
            modules = [
                {
                    "id": "none-main",
                    "type": "none",
                    "assign_to": {"match": {"cluster": "cloud-a", "tier": "cloud"}},
                    "config": {},
                }
            ]
            exp_path, _ = self._build_triplet(root, tempdir, clusters=clusters, modules=modules)
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            module = cfg["domains"]["software"]["modules"][0]
            self.assertEqual(module["resolved_vm_ids"], [1, 2])
            canonical, expected_selector_id = selector_scope.canonical_selector(
                {"tier": "cloud", "cluster": "cloud-a"}
            )
            self.assertEqual(module["selector"], canonical)
            self.assertEqual(module["selector_id"], expected_selector_id)
            self.assertIn({"kind": "selector", "selector_id": expected_selector_id}, module["scope_identities"])

    def test_run_image_prefetch_defaults_to_off(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir)
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            self.assertEqual(cfg["domains"]["run"]["image_prefetch"], "off")

    def test_run_prepare_for_resume_defaults_to_false(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir)
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            self.assertFalse(cfg["domains"]["run"]["prepare_for_resume"])

    def test_run_prepare_for_resume_accepts_infrastructure_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure"],
                run_prepare_for_resume=True,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            self.assertTrue(cfg["domains"]["run"]["prepare_for_resume"])

    def test_run_prepare_for_resume_rejects_non_boolean(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure"],
                run_prepare_for_resume="true",
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("run.prepare_for_resume", stderr)
            self.assertIn("must be boolean", stderr)

    def test_run_prepare_for_resume_rejects_non_infrastructure_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software"],
                run_prepare_for_resume=True,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("run.prepare_for_resume", stderr)
            self.assertIn("run.targets is exactly [infrastructure]", stderr)

    def test_run_image_prefetch_accepts_on_and_off(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            for mode in ("off", "on"):
                exp_path, _ = self._build_triplet(root, tempdir, run_image_prefetch=mode)
                parser = argparse.ArgumentParser()
                cfg = input_module.start(parser, str(exp_path))
                self.assertEqual(cfg["domains"]["run"]["image_prefetch"], mode)

    def test_run_image_prefetch_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir, run_image_prefetch="always")
            stderr = self._parse_error(exp_path)
            self.assertIn("run.image_prefetch", stderr)
            self.assertIn("must be one of", stderr)

    def test_infrastructure_image_prefetch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir)
            payload = yaml.safe_load(exp_path.read_text(encoding="utf-8"))
            payload["infrastructure"]["image_prefetch"] = "on"
            self._write(exp_path, payload)
            stderr = self._parse_error(exp_path)
            self.assertIn("infrastructure.image_prefetch", stderr)
            self.assertIn("use run.image_prefetch", stderr)

    def test_scoped_exclusive_conflict_on_shared_vm_fails(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            modules = [
                {
                    "id": "none-main",
                    "type": "none",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "endpoint-runtime-main",
                    "type": "endpoint_runtime",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "obs-main",
                    "type": "observability",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
            ]
            exp_path, _ = self._build_triplet(root, tempdir, modules=modules)
            original_get_spec = module_registry.get_spec

            def patched_get_spec(module_type):
                if module_type == "endpoint_runtime":
                    return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
                if module_type == "observability":
                    return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
                return original_get_spec(module_type)

            with mock.patch(
                "input.configuration.module_registry.get_spec",
                side_effect=patched_get_spec,
            ):
                stderr = self._parse_error(exp_path)

            self.assertIn("slot.synthetic", stderr)
            self.assertIn('"kind":"vm"', stderr)

    def test_scoped_exclusive_conflict_disjoint_scopes_is_allowed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
                {
                    "id": "edge-1",
                    "tier": "edge",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
            ]
            modules = [
                {
                    "id": "none-main",
                    "type": "none",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "endpoint-runtime-main",
                    "type": "endpoint_runtime",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "obs-main",
                    "type": "observability",
                    "assign_to": {"match": {"cluster": "edge-1"}},
                    "config": {},
                },
            ]
            exp_path, _ = self._build_triplet(root, tempdir, clusters=clusters, modules=modules)
            original_get_spec = module_registry.get_spec

            def patched_get_spec(module_type):
                if module_type == "endpoint_runtime":
                    return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
                if module_type == "observability":
                    return module_registry.ModuleSpec(scope="addon", exclusive_provides=("slot.synthetic",))
                return original_get_spec(module_type)

            parser = argparse.ArgumentParser()
            with mock.patch(
                "input.configuration.module_registry.get_spec",
                side_effect=patched_get_spec,
            ):
                cfg = input_module.start(parser, str(exp_path))
            self.assertEqual(cfg["config_format"], "yaml")

    def test_endpoint_runtime_assigned_away_from_endpoint_resources_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
                {
                    "id": "endpoint-1",
                    "tier": "endpoint",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 1}}},
                },
            ]
            modules = [
                {
                    "id": "k8s-main",
                    "type": "kubernetes",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "endpoint-runtime-main",
                    "type": "endpoint_runtime",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
            ]
            exp_path, _ = self._build_triplet(root, tempdir, clusters=clusters, modules=modules)

            stderr = self._parse_error(exp_path)

            self.assertIn("software.modules[1].assign_to.match", stderr)
            self.assertIn("endpoint_runtime module must be assigned to endpoint resources", stderr)

    def test_required_capability_must_overlap_assignment_scope(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
                {
                    "id": "edge-1",
                    "tier": "edge",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 1}}},
                },
            ]
            modules = [
                {
                    "id": "k8s-main",
                    "type": "kubernetes",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {},
                },
                {
                    "id": "openfaas-main",
                    "type": "openfaas",
                    "assign_to": {"match": {"cluster": "edge-1"}},
                    "config": {},
                },
            ]
            exp_path, _ = self._build_triplet(root, tempdir, clusters=clusters, modules=modules)

            stderr = self._parse_error(exp_path)

            self.assertIn("software.modules[1].assign_to.match", stderr)
            self.assertIn("openfaas module requires orchestrator type kubernetes", stderr)
            self.assertIn("overlapping assignment scope", stderr)

    def test_lock_roundtrip_preserves_pipeline_and_scope_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = yaml_parser.write_experiment_lock(cfg)
            cfg_lock = input_module.start(parser, lock_path)
            stages = cfg_lock["domains"]["benchmark"]["pipeline"]
            self.assertEqual(stages[0]["id"], "generate")
            self.assertTrue(stages[0]["scope_identities"])
            self.assertEqual(
                cfg_lock["planner_snapshot"]["benchmark_stage_assignments"][0]["id"],
                "generate",
            )

    def test_lock_roundtrip_rejects_planner_snapshot_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["planner_snapshot"]["benchmark_stage_assignments"][0]["resolved_vm_ids"] = [999]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn(
                "planner_snapshot.benchmark_stage_assignments[0].resolved_vm_ids[0]",
                stderr,
            )
            self.assertIn(
                "must match deterministic planner snapshot derived from canonical config",
                stderr,
            )

    def test_lock_roundtrip_rejects_module_selector_id_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir)
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["software"]["modules"][0]["selector_id"] = "sel_invalid"
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.software.modules[0].selector_id", stderr)
            self.assertIn("must match canonical selector_id derived from assign_to.match", stderr)

    def test_lock_roundtrip_rejects_missing_module_derived_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            exp_path, _ = self._build_triplet(root, tempdir)
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            del lock_payload["normalized_config"]["software"]["modules"][0]["resolved_vm_ids"]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.software.modules[0].resolved_vm_ids", stderr)
            self.assertIn("is required in normalized lock config", stderr)

    def test_lock_roundtrip_rejects_stage_resolved_vm_ids_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["resolved_vm_ids"] = [999]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.benchmark.pipeline[0].resolved_vm_ids", stderr)
            self.assertIn("must match selector resolution derived from assign_to.match", stderr)

    def test_lock_roundtrip_rejects_stage_empty_resolved_vm_ids(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["resolved_vm_ids"] = []
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.benchmark.pipeline[0].resolved_vm_ids", stderr)
            self.assertIn("must match selector resolution derived from assign_to.match", stderr)

    def test_lock_roundtrip_rejects_missing_stage_derived_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "publisher",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {"benchmark.role": "generator"},
                        "config": {},
                    }
                ]
            }
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            del lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["scope_identities"]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.benchmark.pipeline[0].scope_identities", stderr)
            self.assertIn("is required in normalized lock config", stderr)

    def test_lock_roundtrip_rejects_unknown_known_stage_config_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {"pipeline": [self._image_classification_stage()]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["config"]["unexpected"] = 1
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.benchmark.pipeline[0].config.unexpected", stderr)
            self.assertIn("unexpected key for benchmark stage type", stderr)

    def test_lock_roundtrip_rejects_missing_known_stage_required_key(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {"pipeline": [self._image_classification_stage()]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            del lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["config"][
                "application_worker_cpu"
            ]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("normalized_config.benchmark.pipeline[0].config.application_worker_cpu", stderr)
            self.assertIn("is required for benchmark stage type", stderr)

    def test_lock_roundtrip_rejects_invalid_known_stage_value(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {"pipeline": [self._image_classification_stage()]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["infrastructure", "software", "application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark=benchmark,
            )
            parser = argparse.ArgumentParser()
            cfg = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(cfg))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["benchmark"]["pipeline"][0]["config"][
                "applications_per_worker"
            ] = True
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn(
                "normalized_config.benchmark.pipeline[0].config.applications_per_worker", stderr
            )
            self.assertIn("must be integer >= 1", stderr)

    def test_write_experiment_lock_non_yaml_returns_none(self):
        from input.configuration import yaml_parser

        self.assertIsNone(yaml_parser.write_experiment_lock({"config_format": "legacy"}))

    def test_write_experiment_lock_requires_normalized_for_yaml(self):
        from input.configuration import yaml_parser

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValueError):
                yaml_parser.write_experiment_lock(
                    {
                        "config_format": "yaml",
                        "infrastructure": {"base_path": tempdir},
                    }
                )

    def test_write_experiment_lock_requires_base_path_for_yaml(self):
        from input.configuration import yaml_parser

        with self.assertRaises(ValueError):
            yaml_parser.write_experiment_lock(
                {
                    "config_format": "yaml",
                    "normalized": {"schema_version": 1},
                    "infrastructure": {},
                }
            )

    def test_write_experiment_lock_rejects_non_mapping_sources(self):
        from input.configuration import yaml_parser

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValueError):
                yaml_parser.write_experiment_lock(
                    {
                        "config_format": "yaml",
                        "normalized": {"schema_version": 1, "sources": "invalid"},
                        "infrastructure": {"base_path": tempdir},
                    }
                )


if __name__ == "__main__":
    unittest.main()
