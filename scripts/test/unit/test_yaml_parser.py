"""Regression tests for YAML parser PR-3 hard-cutover contracts."""

import argparse
import copy
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
        provider=None,
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

        if provider is None:
            provider = {
                "name": "qemu",
                "config": {
                    "base_path": base_path,
                    "cpu_pin": False,
                    "external_physical_machines": [],
                    "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                    "netperf": False,
                    "delete_on_exit": False,
                },
            }

        env = {
            "schema_version": 1,
            "kind": "ContinuumEnvironment",
            "provider": provider,
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

    def _write_valid_lock(self, root: Path) -> Path:
        exp_path, _ = self._build_triplet(root, str(root))
        parser = argparse.ArgumentParser()
        config = input_module.start(parser, str(exp_path))
        from input.configuration import yaml_parser

        return Path(yaml_parser.write_experiment_lock(config))

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

    def _text_translation_stage(self, frequency):
        stage = self._image_classification_stage()
        stage["id"] = "translate"
        stage["type"] = "text_translation"
        stage["tags"] = {"benchmark.role": "translate"}
        stage["config"]["frequency"] = frequency
        return stage

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

    def _provider_clusters(self):
        return [
            {
                "id": "cloud-1",
                "tier": "cloud",
                "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 0.5}}},
            },
            {
                "id": "edge-1",
                "tier": "edge",
                "resources": {"vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 1.5}}},
            },
            {
                "id": "endpoint-1",
                "tier": "endpoint",
                "resources": {"vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 2}}},
            },
        ]

    def _provider(self, name, root, provider_options):
        return {
            "name": name,
            "config": {
                "base_path": str(root),
                "cpu_pin": False,
                "external_physical_machines": [],
                "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                "netperf": False,
                "delete_on_exit": False,
                **provider_options,
            },
        }

    def test_full_parser_projects_validated_aws_provider_options(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            provider_options = {
                "aws_cloud": "m6i.large",
                "aws_edge": "m6i.medium",
                "aws_endpoint": "t3.small",
                "aws_region": "eu-west-1",
                "aws_zone": "eu-west-1a",
                "aws_access_keys": "dummy-access-key",
                "aws_secret_access_keys": "dummy-secret-key",
                "aws_ami": "ami-dummy",
            }
            exp_path, _ = self._build_triplet(
                root,
                str(root),
                clusters=self._provider_clusters(),
                modules=self._image_classification_modules(),
                provider=self._provider("aws", root, provider_options),
            )
            from infrastructure.aws import aws

            parser = argparse.ArgumentParser()
            with mock.patch.object(aws, "verify_options", wraps=aws.verify_options) as verify:
                config = input_module.start(parser, str(exp_path))

            verify.assert_called_once()
            for key, value in provider_options.items():
                self.assertEqual(config["infrastructure"][key], value)
                self.assertEqual(config["normalized"]["provider"]["config"][key], value)
            self.assertEqual(config["infrastructure"]["cloud_memory"], 0.5)
            self.assertEqual(config["infrastructure"]["edge_memory"], 1.5)
            self.assertEqual(config["infrastructure"]["endpoint_memory"], 2.0)

    def test_full_parser_projects_validated_gcp_provider_options(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            provider_options = {
                "gcp_cloud": "e2-standard-4",
                "gcp_edge": "e2-standard-2",
                "gcp_endpoint": "e2-small",
                "gcp_region": "europe-west4",
                "gcp_zone": "europe-west4-a",
                "gcp_project": "dummy-project",
                "gcp_credentials": "/tmp/dummy-credentials.json",
            }
            exp_path, _ = self._build_triplet(
                root,
                str(root),
                clusters=self._provider_clusters(),
                modules=self._image_classification_modules(),
                provider=self._provider("gcp", root, provider_options),
            )
            from infrastructure.gcp import gcp

            parser = argparse.ArgumentParser()
            with mock.patch.object(gcp, "verify_options", wraps=gcp.verify_options) as verify:
                config = input_module.start(parser, str(exp_path))

            verify.assert_called_once()
            for key, value in provider_options.items():
                self.assertEqual(config["infrastructure"][key], value)
                self.assertEqual(config["normalized"]["provider"]["config"][key], value)
            self.assertEqual(config["infrastructure"]["cloud_memory"], 0.5)
            self.assertEqual(config["infrastructure"]["edge_memory"], 1.5)
            self.assertEqual(config["infrastructure"]["endpoint_memory"], 2.0)

    def test_full_parser_rejects_trailing_slash_gcp_credentials(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            provider_options = {
                "gcp_cloud": "e2-standard-4",
                "gcp_edge": "e2-standard-2",
                "gcp_endpoint": "e2-small",
                "gcp_region": "europe-west4",
                "gcp_zone": "europe-west4-a",
                "gcp_project": "dummy-project",
                "gcp_credentials": "/tmp/dummy-credentials/",
            }
            exp_path, _ = self._build_triplet(
                root,
                str(root),
                clusters=self._provider_clusters(),
                modules=self._image_classification_modules(),
                provider=self._provider("gcp", root, provider_options),
            )

            error = self._parse_error(exp_path)

            self.assertIn(
                "Invalid gcp_credentials: must point to a file and must not end with '/'",
                error,
            )

    def test_full_parser_expands_runtime_base_path_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            home = root / "patched-home"
            exp_path, _ = self._build_triplet(root, "~")

            from infrastructure import ansible, infrastructure, state
            from input.configuration import config_access, yaml_parser

            with mock.patch.dict("os.environ", {"HOME": str(home)}):
                parser = argparse.ArgumentParser()
                config = input_module.start(parser, str(exp_path))
                runner = ansible.AnsibleRunner(config, [object()])
                infrastructure.create_tmp_dir(config, [])
                lock_path = yaml_parser.write_experiment_lock(config)

            continuum_home = home / ".continuum"
            self.assertEqual(config["infrastructure"]["base_path"], str(home))
            self.assertEqual(config["normalized"]["provider"]["config"]["base_path"], "~")
            self.assertEqual(config["domains"]["provider"]["config"]["base_path"], "~")
            self.assertEqual(Path(lock_path), continuum_home / "experiment_lock.yaml")
            self.assertEqual(Path(state.state_file_path(config)), continuum_home / "state.json")
            self.assertEqual(Path(config_access.runtime_logs_dir(config)), continuum_home / "logs")
            self.assertEqual(
                Path(config_access.network_validation_logs_dir(config)),
                continuum_home / "logs" / "network_validation",
            )
            self.assertEqual(
                Path(config_access.benchmark_logs_dir(config)),
                continuum_home / "logs" / "benchmark",
            )
            self.assertEqual(Path(config["tmp_dir"]), continuum_home / "tmp")
            self.assertEqual(Path(runner.ansible_local_tmp), continuum_home / "ansible" / "tmp")
            self.assertEqual(Path(runner.inventory_path()), continuum_home / "inventory_vms")
            self.assertEqual(Path(config["ssh_key"]), continuum_home / "ssh" / "id_rsa_continuum")
            self.assertEqual(
                Path(config["ssh_known_hosts_file"]),
                continuum_home / "ssh" / "known_hosts",
            )

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

    def test_text_translation_positive_frequency_parses_as_float(self):
        for frequency in (1, 0.5):
            with self.subTest(frequency=frequency), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                benchmark = {"pipeline": [self._text_translation_stage(frequency)]}
                exp_path, _ = self._build_triplet(
                    root,
                    tempdir,
                    run_targets=["infrastructure", "software", "application"],
                    clusters=self._image_classification_clusters(),
                    modules=self._image_classification_modules(),
                    benchmark=benchmark,
                )

                parser = argparse.ArgumentParser()
                config = input_module.start(parser, str(exp_path))
                normalized_frequency = config["domains"]["benchmark"]["pipeline"][0]["config"][
                    "frequency"
                ]
                self.assertEqual(normalized_frequency, float(frequency))
                self.assertIsInstance(normalized_frequency, float)

    def test_text_translation_invalid_frequency_fails_before_projection_or_import(self):
        for frequency in (0, -1, True, False, "1"):
            with self.subTest(frequency=frequency), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                benchmark = {"pipeline": [self._text_translation_stage(frequency)]}
                exp_path, _ = self._build_triplet(
                    root,
                    tempdir,
                    run_targets=["infrastructure", "software", "application"],
                    clusters=self._image_classification_clusters(),
                    modules=self._image_classification_modules(),
                    benchmark=benchmark,
                )

                with mock.patch(
                    "input.configuration.yaml_parser.legacy_projection.to_legacy_config"
                ) as project, mock.patch(
                    "input.configuration.yaml_parser.runtime_module_loader.dynamic_import"
                ) as dynamic_import:
                    stderr = self._parse_error(exp_path)

                project.assert_not_called()
                dynamic_import.assert_not_called()
                self.assertIn("benchmark.pipeline[0].config.frequency", stderr)
                self.assertIn("must be number > 0", stderr)

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

    def test_multiple_benchmark_stages_are_rejected_before_runtime_projection(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            benchmark = {
                "pipeline": [
                    {
                        "id": "generate",
                        "type": "generator",
                        "assign_to": {"match": {"cluster": "cloud-1"}},
                        "tags": {},
                        "config": {},
                    },
                    {
                        "id": "process",
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
            with (
                mock.patch(
                    "input.configuration.yaml_parser.legacy_projection.to_legacy_config"
                ) as project,
                mock.patch(
                    "input.configuration.yaml_parser.runtime_module_loader.dynamic_import"
                ) as dynamic_import,
                mock.patch(
                    "input.configuration.yaml_parser.plans.build_planner_snapshot"
                ) as build_snapshot,
            ):
                stderr = self._parse_error(exp_path)

            self.assertIn("benchmark.pipeline", stderr)
            self.assertIn("exactly one executable stage", stderr)
            self.assertIn("ordered multi-stage execution is not supported", stderr)
            self.assertIn("found 2 stages", stderr)
            project.assert_not_called()
            dynamic_import.assert_not_called()
            build_snapshot.assert_not_called()

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

    def test_software_any_of_resolves_complete_kubeedge_envelope(self):
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
                    "resources": {"vms": {"count": 2, "spec": {"cores": 1, "memory_gb": 1}}},
                },
            ]
            modules = [
                {
                    "id": "kubeedge-main",
                    "type": "kubeedge",
                    "assign_to": {
                        "any_of": [
                            {"cluster": "edge-1"},
                            {"cluster": "cloud-1"},
                        ]
                    },
                    "config": {"kube_version": "v1.27.0", "cache_worker": False},
                }
            ]
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                clusters=clusters,
                modules=modules,
            )

            config = input_module.start(argparse.ArgumentParser(), str(exp_path))
            module = config["domains"]["software"]["modules"][0]

            self.assertEqual(
                module["assign_to"],
                {"any_of": [{"cluster": "cloud-1"}, {"cluster": "edge-1"}]},
            )
            self.assertEqual(module["resolved_vm_ids"], [1, 2, 3])
            self.assertEqual(
                module["selector"],
                {
                    "any_of": [
                        {"match": [["cluster", "cloud-1"]]},
                        {"match": [["cluster", "edge-1"]]},
                    ]
                },
            )

    def test_software_any_of_rejects_empty_clause_and_benchmark_any_of(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            modules = [
                {
                    "id": "none-main",
                    "type": "none",
                    "assign_to": {
                        "any_of": [
                            {"cluster": "cloud-1"},
                            {"cluster": "missing"},
                        ]
                    },
                    "config": {},
                }
            ]
            exp_path, _ = self._build_triplet(root, tempdir, modules=modules)
            stderr = self._parse_error(exp_path)
            self.assertIn("software.modules[0].assign_to.any_of[1]", stderr)
            self.assertIn("selector clause resolves to no infrastructure resources", stderr)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stage = self._image_classification_stage()
            stage["assign_to"] = {"any_of": [{"cluster": "cloud-1"}]}
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                run_targets=["application"],
                clusters=self._image_classification_clusters(),
                modules=self._image_classification_modules(),
                benchmark={"pipeline": [stage]},
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("benchmark.pipeline[0].assign_to.any_of", stderr)
            self.assertIn("unexpected key for schema v1", stderr)

    def test_software_any_of_empty_clause_reports_original_source_index(self):
        clauses_by_expected_index = (
            ([{"cluster": "z-missing"}, {"cluster": "a-valid"}], 0),
            ([{"cluster": "a-valid"}, {"cluster": "z-missing"}], 1),
        )
        clusters = [
            {
                "id": "a-valid",
                "tier": "cloud",
                "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
            }
        ]

        for clauses, expected_index in clauses_by_expected_index:
            with self.subTest(expected_index=expected_index):
                with tempfile.TemporaryDirectory() as tempdir:
                    root = Path(tempdir)
                    modules = [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"any_of": clauses},
                            "config": {},
                        }
                    ]
                    exp_path, _ = self._build_triplet(
                        root,
                        tempdir,
                        clusters=clusters,
                        modules=modules,
                    )

                    stderr = self._parse_error(exp_path)
                    self.assertIn(
                        "software.modules[0].assign_to.any_of[%s]" % (expected_index,),
                        stderr,
                    )
                    self.assertIn(
                        "selector clause resolves to no infrastructure resources",
                        stderr,
                    )

    def test_partial_same_tier_software_assignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
                {
                    "id": "cloud-2",
                    "tier": "cloud",
                    "resources": {"vms": {"count": 1, "spec": {"cores": 2, "memory_gb": 2}}},
                },
            ]
            modules = [
                {
                    "id": "k8s-main",
                    "type": "kubernetes",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {"kube_version": "v1.27.0", "cache_worker": False},
                }
            ]
            exp_path, sw_path = self._build_triplet(
                root,
                tempdir,
                clusters=clusters,
                modules=modules,
            )

            stderr = self._parse_error(exp_path)
            self.assertIn("k8s-main", stderr)
            self.assertIn("cluster=cloud-2", stderr)
            self.assertIn("Partial assignments are unsupported", stderr)

            modules[0]["assign_to"] = {
                "any_of": [{"cluster": "cloud-1"}, {"cluster": "cloud-2"}]
            }
            self._write(
                sw_path,
                {
                    "schema_version": 1,
                    "kind": "ContinuumSoftware",
                    "software": {"modules": modules},
                },
            )
            config = input_module.start(argparse.ArgumentParser(), str(exp_path))
            self.assertEqual(
                config["domains"]["software"]["modules"][0]["resolved_vm_ids"],
                [1, 2],
            )

    def test_kubeedge_cloud_only_assignment_and_replayed_lock_are_rejected(self):
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
                    "id": "kubeedge-main",
                    "type": "kubeedge",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "config": {"kube_version": "v1.27.0", "cache_worker": False},
                }
            ]
            exp_path, sw_path = self._build_triplet(
                root,
                tempdir,
                clusters=clusters,
                modules=modules,
            )
            stderr = self._parse_error(exp_path)
            self.assertIn("kubeedge-main", stderr)
            self.assertIn("cluster=edge-1", stderr)

            modules[0]["assign_to"] = {
                "any_of": [{"cluster": "cloud-1"}, {"cluster": "edge-1"}]
            }
            self._write(
                sw_path,
                {
                    "schema_version": 1,
                    "kind": "ContinuumSoftware",
                    "software": {"modules": modules},
                },
            )
            parser = argparse.ArgumentParser()
            config = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            lock_path = Path(yaml_parser.write_experiment_lock(config))
            replayed = input_module.start(parser, str(lock_path))
            self.assertEqual(
                replayed["domains"]["software"]["modules"][0]["resolved_vm_ids"],
                [1, 2],
            )
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            normalized = lock_payload["normalized_config"]
            module = normalized["software"]["modules"][0]
            canonical, selector_id = selector_scope.canonical_selector(
                {"cluster": "cloud-1"}
            )
            module["assign_to"] = {"match": {"cluster": "cloud-1"}}
            module["selector"] = canonical
            module["selector_id"] = selector_id
            module["resolved_vm_ids"] = [1]
            resources = normalized["infrastructure"]["resources"]
            resources_by_vm_id = {resource["vm_id"]: resource for resource in resources}
            module["scope_identities"] = selector_scope.build_scope_identities(
                resources_by_vm_id,
                [1],
                selector_id,
            )
            assignment = lock_payload["planner_snapshot"]["software_module_assignments"][0]
            assignment["selector_id"] = selector_id
            assignment["resolved_vm_ids"] = [1]
            assignment["resolved_resources"] = [
                {
                    key: resources_by_vm_id[1][key]
                    for key in ("vm_id", "cluster_id", "tier", "index_in_cluster", "tags")
                }
            ]
            assignment["scope_identities"] = module["scope_identities"]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("kubeedge-main", stderr)
            self.assertIn("cluster=edge-1", stderr)
            self.assertIn("Partial assignments are unsupported", stderr)

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

    def test_run_targets_reject_fresh_application_without_software_in_any_order(self):
        for targets in (
            ["infrastructure", "application"],
            ["application", "infrastructure"],
        ):
            with self.subTest(targets=targets), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                exp_path, _ = self._build_triplet(root, tempdir, run_targets=targets)

                stderr = self._parse_error(exp_path)

                self.assertIn("run.targets", stderr)
                self.assertIn(
                    "fresh application execution requires the software phase", stderr
                )

    def test_lock_replay_rejects_fresh_application_without_software(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            lock_path = self._write_valid_lock(root)
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["normalized_config"]["run"]["targets"] = [
                "infrastructure",
                "application",
            ]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)

            self.assertIn("normalized_config.run.targets", stderr)
            self.assertIn(
                "fresh application execution requires the software phase", stderr
            )

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

    def test_memory_gb_preserved_through_projection_lock_and_replay(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clusters = [
                {
                    "id": "cloud-1",
                    "tier": "cloud",
                    "resources": {
                        "vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 0.5}}
                    },
                },
                {
                    "id": "edge-1",
                    "tier": "edge",
                    "resources": {
                        "vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 1.5}}
                    },
                },
                {
                    "id": "endpoint-1",
                    "tier": "endpoint",
                    "resources": {
                        "vms": {"count": 1, "spec": {"cores": 1, "memory_gb": 2}}
                    },
                },
            ]
            exp_path, _ = self._build_triplet(
                root,
                tempdir,
                clusters=clusters,
                modules=self._image_classification_modules(),
            )
            canonical = yaml.safe_load(exp_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    cluster["resources"]["vms"]["spec"]["memory_gb"]
                    for cluster in canonical["infrastructure"]["clusters"]
                ],
                [0.5, 1.5, 2],
            )

            parser = argparse.ArgumentParser()
            config = input_module.start(parser, str(exp_path))
            from input.configuration import yaml_parser

            expected = {"cloud": 0.5, "edge": 1.5, "endpoint": 2.0}

            def assert_normalized_memory(infrastructure):
                cluster_memory = {
                    cluster["tier"]: cluster["resources"]["vms"]["spec"]["memory_gb"]
                    for cluster in infrastructure["clusters"]
                }
                resource_memory = {
                    resource["tier"]: resource["spec"]["memory_gb"]
                    for resource in infrastructure["resources"]
                }
                self.assertEqual(cluster_memory, expected)
                self.assertEqual(resource_memory, expected)
                for value in cluster_memory.values():
                    self.assertIsInstance(value, float)
                for value in resource_memory.values():
                    self.assertIsInstance(value, float)

            assert_normalized_memory(config["normalized"]["infrastructure"])
            for key, value in expected.items():
                projected = config["infrastructure"]["%s_memory" % key]
                self.assertEqual(projected, value)
                self.assertIsInstance(projected, float)

            lock_path = yaml_parser.write_experiment_lock(config)
            lock_payload = yaml.safe_load(Path(lock_path).read_text(encoding="utf-8"))
            assert_normalized_memory(lock_payload["normalized_config"]["infrastructure"])
            assert_normalized_memory(lock_payload["resume_contract"]["details"]["infrastructure"])

            replayed = input_module.start(parser, lock_path)
            assert_normalized_memory(replayed["normalized"]["infrastructure"])
            for key, value in expected.items():
                projected = replayed["infrastructure"]["%s_memory" % key]
                self.assertEqual(projected, value)
                self.assertIsInstance(projected, float)

    def test_non_finite_memory_gb_fails_before_projection_or_import(self):
        for memory_gb in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(memory_gb=memory_gb), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                clusters = [
                    {
                        "id": "cloud-1",
                        "tier": "cloud",
                        "resources": {
                            "vms": {
                                "count": 1,
                                "spec": {"cores": 1, "memory_gb": memory_gb},
                            }
                        },
                    }
                ]
                exp_path, _ = self._build_triplet(root, tempdir, clusters=clusters)

                with mock.patch(
                    "input.configuration.yaml_parser.legacy_projection.to_legacy_config"
                ) as project, mock.patch(
                    "input.configuration.yaml_parser.runtime_module_loader.dynamic_import"
                ) as dynamic_import:
                    stderr = self._parse_error(exp_path)

                project.assert_not_called()
                dynamic_import.assert_not_called()
                self.assertIn(
                    "infrastructure.clusters[0].resources.vms.spec.memory_gb", stderr
                )
                self.assertIn("must be finite number >= 0", stderr)

    def test_lock_replay_rejects_non_finite_memory_gb(self):
        for memory_gb in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(memory_gb=memory_gb), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                lock_path = self._write_valid_lock(root)
                lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                lock_payload["normalized_config"]["infrastructure"]["clusters"][0][
                    "resources"
                ]["vms"]["spec"]["memory_gb"] = memory_gb
                self._write(lock_path, lock_payload)

                stderr = self._parse_error(lock_path)

                self.assertIn(
                    "normalized_config.infrastructure.clusters[0].resources.vms.spec.memory_gb",
                    stderr,
                )
                self.assertIn("must be finite number >= 0", stderr)

    def test_lock_replay_rejects_mutated_multi_stage_pipeline_before_runtime_projection(self):
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
            second_stage = copy.deepcopy(
                lock_payload["normalized_config"]["benchmark"]["pipeline"][0]
            )
            second_stage["id"] = "process"
            lock_payload["normalized_config"]["benchmark"]["pipeline"].append(second_stage)
            self._write(lock_path, lock_payload)

            with (
                mock.patch(
                    "input.configuration.yaml_parser.legacy_projection.to_legacy_config"
                ) as project,
                mock.patch(
                    "input.configuration.yaml_parser.runtime_module_loader.dynamic_import"
                ) as dynamic_import,
                mock.patch(
                    "input.configuration.yaml_parser.plans.build_planner_snapshot"
                ) as build_snapshot,
                mock.patch(
                    "input.configuration.yaml_parser.plans.validate_planner_snapshot"
                ) as validate_snapshot,
            ):
                stderr = self._parse_error(lock_path)

            self.assertIn("normalized_config.benchmark.pipeline", stderr)
            self.assertIn("exactly one executable stage", stderr)
            self.assertIn("ordered multi-stage execution is not supported", stderr)
            self.assertIn("found 2 stages", stderr)
            project.assert_not_called()
            dynamic_import.assert_not_called()
            build_snapshot.assert_not_called()
            validate_snapshot.assert_not_called()

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

    def test_lock_replay_rejects_missing_schema_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            del lock_payload["schema_version"]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("schema_version: must be integer 1", stderr)

    def test_lock_replay_rejects_unsupported_schema_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["schema_version"] = 2
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("schema_version: unsupported value 2 (expected 1)", stderr)

    def test_lock_replay_rejects_non_integer_schema_versions(self):
        for schema_version in (True, "1"):
            with self.subTest(schema_version=schema_version):
                with tempfile.TemporaryDirectory() as tempdir:
                    lock_path = self._write_valid_lock(Path(tempdir))
                    lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                    lock_payload["schema_version"] = schema_version
                    self._write(lock_path, lock_payload)

                    stderr = self._parse_error(lock_path)
                    self.assertIn("schema_version: must be integer 1", stderr)

    def test_lock_replay_rejects_incorrect_kind(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["kind"] = "WrongLockKind"
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("Expected kind", stderr)
            self.assertIn("WrongLockKind", stderr)

    def test_lock_replay_rejects_missing_planner_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            del lock_payload["planner_snapshot"]
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("planner_snapshot: is required", stderr)

    def test_lock_replay_rejects_non_mapping_planner_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["planner_snapshot"] = []
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn("planner_snapshot: must be a mapping", stderr)

    def test_lock_replay_rejects_empty_planner_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = self._write_valid_lock(Path(tempdir))
            lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            lock_payload["planner_snapshot"] = {}
            self._write(lock_path, lock_payload)

            stderr = self._parse_error(lock_path)
            self.assertIn(
                "planner_snapshot.benchmark_stage_assignments is required in planner snapshot",
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
