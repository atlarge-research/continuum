"""Unit tests for YAML-only e2e test utility helpers."""

import importlib.util
import json
import tempfile
import unittest
from argparse import ArgumentParser
from pathlib import Path
from unittest import mock

import yaml

from input.configuration import resume_contract, yaml_parser


def _load_test_utils_module():
    module_path = Path(__file__).resolve().parents[1] / "support" / "e2e_utils.py"
    spec = importlib.util.spec_from_file_location("continuum_test_utils", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


test_utils = _load_test_utils_module()


def _contract_section(details=None):
    return resume_contract.persisted_resume_contract_from_details(details or {"test": "contract"})


def _state_payload(phase_completed, contract=None, machine_data=None):
    return {
        "schema_version": 2,
        "kind": "ContinuumState",
        "created_at": "2026-05-20T00:00:00+00:00",
        "phase_completed": phase_completed,
        "resume_contract": contract or _contract_section(),
        "machine_data": machine_data or [{"cloud_names": ["cloud0_test"]}],
    }


def _write_success_artifacts(root: Path, phase_completed, contract=None, machine_data=None):
    continuum_dir = root / ".continuum"
    continuum_dir.mkdir(parents=True)
    contract = contract or _contract_section()
    (continuum_dir / "experiment_lock.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "ContinuumExperimentLock",
                "resume_contract": contract,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (continuum_dir / "state.json").write_text(
        json.dumps(
            _state_payload(
                phase_completed,
                contract=contract,
                machine_data=machine_data,
            )
        ),
        encoding="utf-8",
    )


def _write_network_results(root: Path, entries=None):
    results_dir = root / ".continuum" / "logs" / "network_validation"
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "netperf_results_2026-05-21T000000.ndjson"
    entries = entries or [
        {
            "source": "cloud",
            "target": "endpoint",
            "direction": "latency",
            "output": "1000,40000,50000,1000,25,30000,45000,50000",
            "expected_latency_ms": 45.0,
            "expected_throughput_mbps": 7.21,
        },
        {
            "source": "cloud",
            "target": "endpoint",
            "direction": "throughput",
            "output": "7.50",
            "expected_latency_ms": 45.0,
            "expected_throughput_mbps": 7.21,
        },
    ]
    with results_path.open("w", encoding="utf-8") as filep:
        for entry in entries:
            filep.write(json.dumps(entry) + "\n")
    return results_path


def _write_benchmark_metrics(root: Path, latency_value="12.5"):
    results_dir = root / ".continuum" / "logs" / "benchmark"
    results_dir.mkdir(parents=True, exist_ok=True)
    table_path = results_dir / "2026-05-21_15-30-42_classify_01_ENDPOINT_OUTPUT.csv"
    table_path.write_text(
        "endpoint_id,latency_avg (ms)\n0,%s\n" % (latency_value,),
        encoding="utf-8",
    )
    manifest_path = results_dir / "2026-05-21_15-30-42_classify_metrics_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "ContinuumBenchmarkMetrics",
                "timestamp": "2026-05-21_15:30:42",
                "stage_id": "classify",
                "stage_type": "image_classification",
                "tables": [
                    {
                        "label": "ENDPOINT OUTPUT",
                        "path": str(table_path),
                        "columns": ["endpoint_id", "latency_avg (ms)"],
                        "rows": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


class E2ETestUtilsYamlTests(unittest.TestCase):
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
        self._socket_patcher = unittest.mock.patch(
            "input.configuration.runtime_module_loader.socket_lib.socket",
            side_effect=lambda *_args, **_kwargs: self._FakeHostIpSocket(),
        )
        self._socket_patcher.start()

    def tearDown(self):
        self._socket_patcher.stop()

    def _write_yaml(self, path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as filep:
            yaml.safe_dump(payload, filep, sort_keys=False)

    def test_discover_config_files_only_returns_yaml(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "a.yaml").write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            (root / "b.yml").write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            (root / "legacy.cfg").write_text("[infrastructure]\n", encoding="utf-8")

            discovered = test_utils.discover_config_files([tempdir], [])
            self.assertIn(str(root / "a.yaml"), discovered)
            self.assertIn(str(root / "b.yml"), discovered)
            self.assertNotIn(str(root / "legacy.cfg"), discovered)

    def test_parse_config_simple_rejects_non_yaml(self):
        with tempfile.TemporaryDirectory() as tempdir:
            cfg_path = Path(tempdir) / "legacy.cfg"
            cfg_path.write_text("[infrastructure]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                test_utils.parse_config_simple(str(cfg_path))

    def test_parse_yaml_experiment_resolves_profiles(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_yaml(
                root / "env.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumEnvironment",
                    "provider": {
                        "name": "qemu",
                        "config": {
                            "base_path": tempdir,
                            "cpu_pin": True,
                            "external_physical_machines": ["alice@node1"],
                            "ip": {"middle": 120, "middle_base": 99},
                        },
                    },
                },
            )
            self._write_yaml(
                root / "sw.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumSoftware",
                    "software": {
                        "modules": [
                            {
                                "id": "kubeedge-main",
                                "type": "kubeedge",
                                "assign_to": {"match": {"cluster": "cloud-1"}},
                                "config": {"kube_version": "v1.27.0"},
                            }
                        ]
                    },
                },
            )
            self._write_yaml(
                root / "exp.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumExperiment",
                    "use": {"environment": "env", "software": "sw"},
                    "run": {"targets": ["infrastructure", "software", "application"]},
                    "infrastructure": {
                        "clusters": [
                            {
                                "id": "cloud-1",
                                "tier": "cloud",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 4}}},
                            },
                            {
                                "id": "edge-1",
                                "tier": "edge",
                                "resources": {"vms": {"count": 2, "spec": {"cores": 2}}},
                            },
                            {
                                "id": "endpoint-1",
                                "tier": "endpoint",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 1}}},
                            },
                        ]
                    },
                    "benchmark": {
                        "pipeline": [
                            {
                                "id": "stage-1",
                                "type": "generator",
                                "assign_to": {"match": {"cluster": "cloud-1"}},
                                "tags": {"benchmark.role": "generator"},
                                "config": {},
                            }
                        ]
                    },
                },
            )

            parsed = test_utils.parse_config_simple(str(root / "exp.yaml"))
            self.assertEqual(parsed["infrastructure"]["provider"], "qemu")
            self.assertEqual(parsed["benchmark"]["resource_manager"], "kubeedge")
            self.assertFalse(parsed["infrastructure"]["infra_only"])
            self.assertEqual(parsed["infrastructure"]["middleIP"], 120)
            self.assertEqual(parsed["infrastructure"]["middleIP_base"], 99)
            self.assertEqual(parsed["infrastructure"]["external_physical_machines"], "alice@node1")

    def test_parse_yaml_lock_uses_normalized_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = Path(tempdir) / "lock.yaml"
            self._write_yaml(
                lock_path,
                {
                    "schema_version": 1,
                    "kind": "ContinuumExperimentLock",
                    "normalized_config": {
                        "run": {"targets": ["software"]},
                        "infrastructure": {
                            "clusters": [
                                {
                                    "id": "cloud-1",
                                    "tier": "cloud",
                                    "resources": {"vms": {"count": 1, "spec": {"cores": 4}}},
                                }
                            ]
                        },
                        "provider": {"name": "qemu", "config": {"base_path": tempdir}},
                        "software": {
                            "modules": [
                                {
                                    "id": "k8s-main",
                                    "type": "kubernetes",
                                    "assign_to": {"match": {"cluster": "cloud-1"}},
                                    "config": {},
                                }
                            ]
                        },
                    },
                },
            )
            parsed = test_utils.parse_config_simple(str(lock_path))
            self.assertFalse(parsed["infrastructure"]["infra_only"])
            self.assertTrue(parsed["benchmark"]["resource_manager_only"])
            self.assertEqual(parsed["benchmark"]["resource_manager"], "kubernetes")

    def test_override_experiment_parameters_generates_lock_payload(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_yaml(
                root / "env.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumEnvironment",
                    "provider": {"name": "qemu", "config": {"base_path": tempdir}},
                },
            )
            self._write_yaml(
                root / "sw.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumSoftware",
                    "software": {
                        "modules": [
                            {
                                "id": "k8s-main",
                                "type": "kubernetes",
                                "assign_to": {"match": {"cluster": "cloud-1"}},
                                "config": {},
                            }
                        ]
                    },
                },
            )
            self._write_yaml(
                root / "exp.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumExperiment",
                    "use": {"environment": "env", "software": "sw"},
                    "run": {"targets": ["infrastructure", "software"]},
                    "infrastructure": {
                        "clusters": [
                            {
                                "id": "cloud-1",
                                "tier": "cloud",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 4}}},
                            }
                        ]
                    },
                },
            )

            temp_path = test_utils.override_config_parameters(
                str(root / "exp.yaml"),
                base_path="/tmp/new-base/",
                middle_ip=111,
                middle_ip_base=96,
                external_physical_machines="alice@node1,bob@node2",
            )
            try:
                payload = yaml.safe_load(Path(temp_path).read_text(encoding="utf-8"))
                self.assertEqual(payload["kind"], "ContinuumExperimentLock")
                provider_cfg = payload["normalized_config"]["provider"]["config"]
                self.assertEqual(provider_cfg["base_path"], "/tmp/new-base")
                self.assertEqual(provider_cfg["ip"]["middle"], 111)
                self.assertEqual(provider_cfg["ip"]["middle_base"], 96)
                self.assertEqual(
                    provider_cfg["external_physical_machines"],
                    ["alice@node1", "bob@node2"],
                )
            finally:
                Path(temp_path).unlink(missing_ok=True)

    def test_override_experiment_parameters_emits_parser_valid_lock(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self._write_yaml(
                root / "env.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumEnvironment",
                    "provider": {"name": "qemu", "config": {"base_path": tempdir}},
                },
            )
            self._write_yaml(
                root / "sw.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumSoftware",
                    "software": {
                        "modules": [
                            {
                                "id": "infra-only",
                                "type": "none",
                                "assign_to": {"match": {"cluster": "cloud-1"}},
                                "config": {},
                            }
                        ]
                    },
                },
            )
            self._write_yaml(
                root / "exp.yaml",
                {
                    "schema_version": 1,
                    "kind": "ContinuumExperiment",
                    "use": {"environment": "env", "software": "sw"},
                    "run": {"targets": ["infrastructure"]},
                    "infrastructure": {
                        "clusters": [
                            {
                                "id": "cloud-1",
                                "tier": "cloud",
                                "resources": {"vms": {"count": 1, "spec": {"cores": 2}}},
                            }
                        ]
                    },
                },
            )

            temp_path = test_utils.override_config_parameters(
                str(root / "exp.yaml"),
                base_path=str(root / "override-base"),
            )
            try:
                parsed = yaml_parser.start(ArgumentParser(prog="override-lock-parse"), temp_path)
                self.assertEqual(
                    parsed["infrastructure"]["base_path"],
                    str((root / "override-base").resolve()),
                )
            finally:
                Path(temp_path).unlink(missing_ok=True)

    def test_detect_success_requires_experiment_lock_and_state_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "software")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": True,
                },
            }
            success, reason = test_utils.detect_success(
                stdout=(
                    "Logging has been enabled. Writing to stdout and file "
                    "/tmp/run/.continuum/logs/2026-05-21_15:30:42_cloud_kubernetes_classify.log\n"
                    "ssh cloud0@192.168.0.10 -i /tmp/test_key\n"
                ),
                stderr="",
                exit_code=0,
                config=config,
                success_config={},
            )

            self.assertTrue(success)
            self.assertIn("experiment_lock_written", reason)
            self.assertIn("state_phase=software", reason)
            self.assertIn("resume_contract_match", reason)

    def test_detect_success_accepts_application_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "application")

            config = {
                "timestamp": "2026-05-21_15:30:42",
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={},
            )

            self.assertTrue(success)
            self.assertIn("state_phase=application", reason)

    def test_detect_success_requires_configured_benchmark_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "application")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            stdout = "\n".join(
                [
                    "ssh cloud0@192.168.0.10 -i /tmp/test_key",
                    "Benchmark has been finished, prepare results",
                    "ENDPOINT OUTPUT",
                    "latency_avg (ms)",
                ]
            )
            success, reason = test_utils.detect_success(
                stdout=stdout,
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_stdout_markers": [
                        "Benchmark has been finished, prepare results",
                        "ENDPOINT OUTPUT",
                        "latency_avg (ms)",
                    ],
                },
            )

            self.assertTrue(success)
            self.assertIn("benchmark_evidence_found", reason)

    def test_detect_success_rejects_missing_benchmark_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "application")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout=(
                    "ssh cloud0@192.168.0.10 -i /tmp/test_key\n"
                    "Benchmark has been finished, prepare results\n"
                ),
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_stdout_markers": [
                        "Benchmark has been finished, prepare results",
                        "ENDPOINT OUTPUT",
                        "latency_avg (ms)",
                    ],
                },
            )

            self.assertFalse(success)
            self.assertIn(
                "Benchmark evidence missing: ENDPOINT OUTPUT, latency_avg (ms)",
                reason,
            )

    def test_detect_success_requires_benchmark_metric_table_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "application")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            stdout = "\n".join(
                [
                    "ssh cloud0@192.168.0.10 -i /tmp/test_key",
                    "[2026-05-21 path:1 - f() ] ENDPOINT OUTPUT",
                    "[2026-05-21 path:1 - f() ] endpoint_id  latency_avg (ms)",
                    "[2026-05-21 path:1 - f() ]           0             12.5",
                ]
            )
            success, reason = test_utils.detect_success(
                stdout=stdout,
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_stdout_metric_tables": [
                        {
                            "label": "ENDPOINT OUTPUT",
                            "columns": ["latency_avg (ms)"],
                            "min_rows": 1,
                        }
                    ],
                },
            )

            self.assertTrue(success)
            self.assertIn("benchmark_metric_tables_found", reason)

    def test_detect_success_rejects_benchmark_metric_table_without_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "application")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            stdout = "\n".join(
                [
                    "ssh cloud0@192.168.0.10 -i /tmp/test_key",
                    "ENDPOINT OUTPUT",
                    "endpoint_id  latency_avg (ms)",
                ]
            )
            success, reason = test_utils.detect_success(
                stdout=stdout,
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_stdout_metric_tables": [
                        {
                            "label": "ENDPOINT OUTPUT",
                            "columns": ["latency_avg (ms)"],
                            "min_rows": 1,
                        }
                    ],
                },
            )

            self.assertFalse(success)
            self.assertIn("Benchmark metric evidence missing rows for ENDPOINT OUTPUT", reason)

    def test_detect_success_requires_benchmark_metric_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "application")
            manifest_path = _write_benchmark_metrics(root)

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_benchmark_metric_artifacts": [
                        {
                            "label": "ENDPOINT OUTPUT",
                            "columns": ["latency_avg (ms)"],
                            "numeric_columns": ["latency_avg (ms)"],
                            "min_rows": 1,
                        }
                    ],
                },
            )

            self.assertTrue(success)
            self.assertIn("benchmark_metric_artifacts=%s" % (manifest_path,), reason)

    def test_detect_success_rejects_invalid_benchmark_metric_artifact_value(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "application")
            _write_benchmark_metrics(root, latency_value="not-a-number")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "required_benchmark_metric_artifacts": [
                        {
                            "label": "ENDPOINT OUTPUT",
                            "columns": ["latency_avg (ms)"],
                            "numeric_columns": ["latency_avg (ms)"],
                            "min_rows": 1,
                        }
                    ],
                },
            )

            self.assertFalse(success)
            self.assertIn("Benchmark metric artifact invalid", reason)

    def test_detect_success_skips_benchmark_evidence_for_non_application_leg(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "infrastructure")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "require_ssh_output": False,
                    "required_stdout_markers": [
                        "Benchmark has been finished, prepare results",
                    ],
                },
            )

            self.assertTrue(success)
            self.assertNotIn("benchmark_evidence_found", reason)

    def test_detect_success_validates_network_results_for_network_suite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "infrastructure")
            results_path = _write_network_results(root)

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "infra_only_override": {
                        "require_ssh_output": False,
                        "require_network_validation_results": True,
                    }
                },
            )

            self.assertTrue(success)
            self.assertIn("network_validation_results=%s" % (results_path,), reason)

    def test_detect_success_rejects_missing_network_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "infrastructure")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "infra_only_override": {
                        "require_ssh_output": False,
                        "require_network_validation_results": True,
                    }
                },
            )

            self.assertFalse(success)
            self.assertIn("Network validation artifact missing", reason)

    def test_detect_success_rejects_missing_lock_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            continuum_dir = Path(tempdir) / ".continuum"
            continuum_dir.mkdir(parents=True)
            (continuum_dir / "state.json").write_text(
                json.dumps(_state_payload("infrastructure")),
                encoding="utf-8",
            )

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={
                    "require_ssh_output": False,
                },
            )

            self.assertFalse(success)
            self.assertIn("Experiment lock file missing", reason)

    def test_detect_success_rejects_wrong_state_phase(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(Path(tempdir), "infrastructure")

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": False,
                },
                "benchmark": {
                    "resource_manager_only": True,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={},
            )

            self.assertFalse(success)
            self.assertIn("expected 'software'", reason)

    def test_detect_success_rejects_legacy_state_schema(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            continuum_dir = root / ".continuum"
            continuum_dir.mkdir(parents=True)
            contract = _contract_section()
            (continuum_dir / "experiment_lock.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "kind": "ContinuumExperimentLock",
                        "resume_contract": contract,
                    }
                ),
                encoding="utf-8",
            )
            (continuum_dir / "state.json").write_text(
                json.dumps({"phase_completed": "infrastructure"}),
                encoding="utf-8",
            )

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={"require_ssh_output": False},
            )

            self.assertFalse(success)
            self.assertIn("State schema mismatch", reason)

    def test_detect_success_rejects_resume_contract_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_contract = _contract_section({"test": "lock"})
            state_contract = _contract_section({"test": "state"})
            root = Path(tempdir)
            continuum_dir = root / ".continuum"
            continuum_dir.mkdir(parents=True)
            (continuum_dir / "experiment_lock.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "kind": "ContinuumExperimentLock",
                        "resume_contract": lock_contract,
                    }
                ),
                encoding="utf-8",
            )
            (continuum_dir / "state.json").write_text(
                json.dumps(_state_payload("infrastructure", contract=state_contract)),
                encoding="utf-8",
            )

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            success, reason = test_utils.detect_success(
                stdout="",
                stderr="",
                exit_code=0,
                config=config,
                success_config={"require_ssh_output": False},
            )

            self.assertFalse(success)
            self.assertIn("Resume contract mismatch", reason)

    def test_detect_success_verifies_qemu_teardown_when_requested(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(
                Path(tempdir),
                "application",
                machine_data=[{"cloud_names": ["cloud0_test"]}],
            )

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "delete_on_exit": True,
                    "infra_only": False,
                    "provider": "qemu",
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            virsh_result = mock.Mock(returncode=0, stdout=" Id Name State\n", stderr="")
            with mock.patch.object(test_utils.shutil, "which", return_value="/usr/bin/virsh"), mock.patch.object(
                test_utils.subprocess,
                "run",
                return_value=virsh_result,
            ) as run_mock:
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={"require_teardown": True},
                )

            self.assertTrue(success)
            self.assertIn("teardown_verified", reason)
            run_mock.assert_called_once_with(
                ["/usr/bin/virsh", "list", "--all"],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_detect_success_rejects_remaining_qemu_domain(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_success_artifacts(
                Path(tempdir),
                "application",
                machine_data=[{"cloud_names": ["cloud0_test"]}],
            )

            config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "delete_on_exit": True,
                    "infra_only": False,
                    "provider": "qemu",
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            virsh_result = mock.Mock(
                returncode=0,
                stdout=" Id Name State\n 1 cloud0_test running\n",
                stderr="",
            )
            with mock.patch.object(test_utils.shutil, "which", return_value="/usr/bin/virsh"), mock.patch.object(
                test_utils.subprocess,
                "run",
                return_value=virsh_result,
            ):
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={"require_teardown": True},
                )

            self.assertFalse(success)
            self.assertIn("VM domain(s) still present: cloud0_test", reason)

    def test_classify_test_failure_uses_stable_buckets(self):
        self.assertEqual(
            test_utils.classify_test_failure(
                {"success": False, "timed_out": True, "error": "Test timed out after 90 minutes"}
            ),
            "timeout",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {"success": False, "error": "Experiment lock file missing: /tmp/x/.continuum/experiment_lock.yaml"}
            ),
            "missing_lock",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {"success": False, "success_reason": "No SSH output found (expected SSH commands)"}
            ),
            "missing_ssh",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": (
                        "Teardown verification failed: VM domain(s) still present: cloud0_test"
                    ),
                }
            ),
            "teardown_failure",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "State schema mismatch: expected schema_version 2",
                }
            ),
            "state_schema_mismatch",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Resume contract mismatch: lock a != state b",
                }
            ),
            "resume_contract_mismatch",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Benchmark evidence missing: ENDPOINT OUTPUT",
                }
            ),
            "missing_benchmark_evidence",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": (
                        "Benchmark metric evidence missing rows for ENDPOINT OUTPUT"
                    ),
                }
            ),
            "missing_benchmark_metric_evidence",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Benchmark metric artifact missing: no manifest",
                }
            ),
            "missing_benchmark_metric_artifact",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Benchmark metric artifact invalid: not numeric",
                }
            ),
            "invalid_benchmark_metric_artifact",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Network validation artifact missing: no results",
                }
            ),
            "missing_network_artifact",
        )
        self.assertEqual(
            test_utils.classify_test_failure(
                {
                    "success": False,
                    "success_reason": "Network validation profile mismatch: latency",
                }
            ),
            "network_profile_mismatch",
        )
        self.assertIsNone(test_utils.classify_test_failure({"success": True}))

    def test_save_test_results_writes_per_test_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            result_path = Path(
                test_utils.save_test_results(
                    [
                        {
                            "config_path": "configs/experiments/smoke/infra_one_vm.yaml",
                            "success": False,
                            "error": "Experiment lock file missing: /tmp/run/.continuum/experiment_lock.yaml",
                            "stdout": "stdout payload\n",
                            "stderr": "stderr payload\n",
                            "execution_time": 1.2,
                            "timed_out": False,
                        }
                    ],
                    tempdir,
                )
            )

            summary = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["failed"], 1)
            self.assertTrue(Path(summary["artifacts_dir"]).is_dir())

            stored_result = summary["results"][0]
            self.assertEqual(stored_result["failure_class"], "missing_lock")
            self.assertTrue(Path(stored_result["stdout_artifact"]).is_file())
            self.assertTrue(Path(stored_result["stderr_artifact"]).is_file())
            self.assertTrue(Path(stored_result["metadata_artifact"]).is_file())
            self.assertEqual(
                Path(stored_result["stdout_artifact"]).read_text(encoding="utf-8"),
                "stdout payload\n",
            )


if __name__ == "__main__":
    unittest.main()
