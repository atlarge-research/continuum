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
NETWORK_RESULTS_TIMESTAMP = "2026-05-21_15:30:42"


def _contract_section(details=None):
    return resume_contract.persisted_resume_contract_from_details(details or {"test": "contract"})


def _state_payload(
    phase_completed,
    contract=None,
    machine_data=None,
    created_at="2026-05-20T00:00:01+00:00",
):
    return {
        "schema_version": 2,
        "kind": "ContinuumState",
        "created_at": created_at,
        "phase_completed": phase_completed,
        "resume_contract": contract or _contract_section(),
        "machine_data": machine_data or [{"cloud_names": ["cloud0_test"]}],
    }


def _write_success_artifacts(
    root: Path,
    phase_completed,
    contract=None,
    machine_data=None,
    lock_created_at="2026-05-20T00:00:00+00:00",
    state_created_at="2026-05-20T00:00:01+00:00",
):
    continuum_dir = root / ".continuum"
    continuum_dir.mkdir(parents=True)
    contract = contract or _contract_section()
    (continuum_dir / "experiment_lock.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "ContinuumExperimentLock",
                "created_at": lock_created_at,
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
                created_at=state_created_at,
            )
        ),
        encoding="utf-8",
    )


def _network_result_entries(timestamp=NETWORK_RESULTS_TIMESTAMP):
    return [
        {
            "timestamp": timestamp,
            "source": "cloud",
            "target": "endpoint",
            "direction": "latency",
            "output": "1000,90000,100000,1000,25,85000,95000,100000",
            "expected_latency_ms": 45.0,
            "expected_throughput_mbps": 7.21,
        },
        {
            "timestamp": timestamp,
            "source": "cloud",
            "target": "endpoint",
            "direction": "throughput",
            "output": "7.50",
            "expected_latency_ms": 45.0,
            "expected_throughput_mbps": 7.21,
        },
    ]


def _write_network_results(root: Path, timestamp=NETWORK_RESULTS_TIMESTAMP, entries=None):
    results_dir = root / ".continuum" / "logs" / "network_validation"
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / ("netperf_results_%s.ndjson" % (timestamp,))
    if entries is None:
        entries = _network_result_entries(timestamp)
    with results_path.open("w", encoding="utf-8") as filep:
        for entry in entries:
            filep.write(json.dumps(entry) + "\n")
    return results_path


def _run_log_stdout(timestamp=NETWORK_RESULTS_TIMESTAMP):
    return "Logging has been enabled. Writing to stdout and file %s_infra_only.log\n" % (
        timestamp,
    )


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
                            "stat_assertions": [
                                {
                                    "column": "latency_avg (ms)",
                                    "min": 0.0,
                                    "max": 100.0,
                                    "mean_min": 0.0,
                                    "mean_max": 100.0,
                                }
                            ],
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

    def test_detect_success_rejects_benchmark_metric_artifact_stat_bounds(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "application")
            _write_benchmark_metrics(root, latency_value="12.5")

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
                            "stat_assertions": [
                                {
                                    "column": "latency_avg (ms)",
                                    "max": 10.0,
                                }
                            ],
                        }
                    ],
                },
            )

            self.assertFalse(success)
            self.assertIn("Benchmark metric artifact statistic failed", reason)

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
                stdout=_run_log_stdout(),
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

    def test_detect_success_rejects_older_network_results_when_current_is_missing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "infrastructure")
            older_path = _write_network_results(root, timestamp="2026-05-20_15:30:42")
            current_path = older_path.parent / (
                "netperf_results_%s.ndjson" % (NETWORK_RESULTS_TIMESTAMP,)
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
                stdout=_run_log_stdout(),
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
            self.assertIn(str(current_path), reason)
            self.assertNotIn(str(older_path), reason)

    def test_network_validation_fails_when_current_run_timestamp_is_unknown(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_network_results(root)
            config = {"infrastructure": {"base_path": tempdir}}

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("current run timestamp could not be determined", reason)

    def test_network_validation_prefers_explicit_config_timestamp(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            results_path = _write_network_results(root)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(
                config,
                stdout=_run_log_stdout("2026-05-20_15:30:42"),
            )

            self.assertTrue(success)
            self.assertIn(str(results_path), reason)

    def test_network_validation_rejects_entry_with_missing_timestamp(self):
        with tempfile.TemporaryDirectory() as tempdir:
            entries = _network_result_entries()
            entries[0].pop("timestamp")
            _write_network_results(Path(tempdir), entries=entries)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("entry 1 is missing timestamp", reason)

    def test_network_validation_rejects_entry_with_wrong_timestamp(self):
        with tempfile.TemporaryDirectory() as tempdir:
            entries = _network_result_entries()
            entries[0]["timestamp"] = "2026-05-20_15:30:42"
            _write_network_results(Path(tempdir), entries=entries)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("entry 1 timestamp '2026-05-20_15:30:42'", reason)
            self.assertIn("current run timestamp %r" % (NETWORK_RESULTS_TIMESTAMP,), reason)

    def test_network_validation_rejects_mixed_current_and_stale_timestamps(self):
        with tempfile.TemporaryDirectory() as tempdir:
            entries = _network_result_entries()
            entries[1]["timestamp"] = "2026-05-20_15:30:42"
            _write_network_results(Path(tempdir), entries=entries)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("entry 2 timestamp '2026-05-20_15:30:42'", reason)

    def test_network_validation_rejects_non_mapping_entry_clearly(self):
        with tempfile.TemporaryDirectory() as tempdir:
            entries = _network_result_entries()
            entries.append(["malformed"])
            _write_network_results(Path(tempdir), entries=entries)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("entry 3 must be a mapping", reason)

    def test_network_validation_rejects_empty_current_run_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_network_results(Path(tempdir), entries=[])
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("no netperf entries found", reason)

    def test_network_validation_preserves_profile_failures(self):
        with tempfile.TemporaryDirectory() as tempdir:
            entries = _network_result_entries()
            entries[0]["output"] = "1000,140000,150000,1000,25,135000,145000,150000"
            entries[1]["output"] = "30.00"
            _write_network_results(Path(tempdir), entries=entries)
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("Network validation profile mismatch", reason)
            self.assertIn("latency", reason)
            self.assertIn("throughput", reason)

    def test_network_validation_reports_exact_current_artifact_as_unreadable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            _write_network_results(Path(tempdir))
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }
            verifier = test_utils._load_verify_network_profiles()

            with mock.patch.object(verifier, "load_results", side_effect=OSError("denied")):
                success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("Network validation artifact unreadable", reason)
            self.assertIn("denied", reason)

    def test_network_validation_rejects_non_utf8_current_artifact_as_unreadable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_path = _write_network_results(Path(tempdir))
            results_path.write_bytes(b"\xff")
            config = {
                "timestamp": NETWORK_RESULTS_TIMESTAMP,
                "infrastructure": {"base_path": tempdir},
            }

            success, reason = test_utils.verify_network_validation_results(config)

            self.assertFalse(success)
            self.assertIn("Network validation artifact unreadable", reason)
            self.assertIn("utf-8", reason)

    def test_detect_success_allows_successful_ansible_retry_noise(self):
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
                stdout="FAILED - RETRYING: [node]: Install package\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={"require_ssh_output": False},
            )

            self.assertTrue(success)
            self.assertIn("exit_code=0", reason)

    def test_detect_success_rejects_fatal_ansible_stdout(self):
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
                stdout="fatal: [node]: FAILED! => msg=boom\n",
                stderr="",
                exit_code=0,
                config=config,
                success_config={"require_ssh_output": False},
            )

            self.assertFalse(success)
            self.assertEqual(reason, "Ansible reported FAILED in stdout despite exit_code=0")

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

    @staticmethod
    def _qemu_delete_config(base_path):
        return {
            "infrastructure": {
                "base_path": base_path,
                "delete_on_exit": True,
                "infra_only": False,
                "provider": "qemu",
            },
            "benchmark": {"resource_manager_only": False},
        }

    @staticmethod
    def _owner_state(name="local", is_local=True, domains=None):
        return {
            "name": name,
            "is_local": is_local,
            "cloud_controller_names": [],
            "cloud_names": domains or ["cloud0_test"],
            "edge_names": [],
            "endpoint_names": [],
            "base_names": [],
        }

    def test_qemu_delete_without_optional_flag_uses_state_machine_data(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            machine_data = [self._owner_state(domains=["cloud0_current"])]
            _write_success_artifacts(root, "application", machine_data=machine_data)
            config = self._qemu_delete_config(tempdir)
            state_payload = json.loads(
                (root / ".continuum" / "state.json").read_text(encoding="utf-8")
            )

            with mock.patch.object(
                test_utils,
                "verify_qemu_teardown",
                return_value=(True, "teardown_verified"),
            ) as verify_mock:
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={
                        "require_ssh_output": False,
                        "require_experiment_lock": False,
                        "require_state_file": False,
                        "require_state_phase": False,
                        "require_resume_contract": False,
                        "require_teardown": False,
                    },
                )

            self.assertTrue(success)
            self.assertIn("teardown_evidence_current_run", reason)
            self.assertIn("teardown_verified", reason)
            verify_mock.assert_called_once_with(config, state_payload)

    def test_qemu_delete_rejects_older_same_contract_state_from_previous_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(
                root,
                "application",
                machine_data=[self._owner_state()],
                lock_created_at="2026-05-20T00:00:02+00:00",
                state_created_at="2026-05-20T00:00:01+00:00",
            )
            config = self._qemu_delete_config(tempdir)

            with mock.patch.object(test_utils, "verify_qemu_teardown") as verify_mock:
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={},
                )

            self.assertFalse(success)
            self.assertIn("state.created_at predates", reason)
            verify_mock.assert_not_called()

    def test_qemu_delete_rejects_malformed_or_naive_evidence_timestamps(self):
        cases = (
            ("missing lock", None, "2026-05-20T00:00:01+00:00"),
            ("malformed lock", "not-a-timestamp", "2026-05-20T00:00:01+00:00"),
            ("naive lock", "2026-05-20T00:00:00", "2026-05-20T00:00:01+00:00"),
            ("missing state", "2026-05-20T00:00:00+00:00", None),
            ("malformed state", "2026-05-20T00:00:00+00:00", "not-a-timestamp"),
            ("naive state", "2026-05-20T00:00:00+00:00", "2026-05-20T00:00:01"),
        )
        for label, lock_created_at, state_created_at in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                _write_success_artifacts(
                    root,
                    "application",
                    machine_data=[self._owner_state()],
                    lock_created_at=lock_created_at,
                    state_created_at=state_created_at,
                )
                config = self._qemu_delete_config(tempdir)

                with mock.patch.object(test_utils, "verify_qemu_teardown") as verify_mock:
                    success, reason = test_utils.detect_success(
                        stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                        stderr="",
                        exit_code=0,
                        config=config,
                        success_config={},
                    )

                self.assertFalse(success)
                self.assertIn("timestamp", reason)
                verify_mock.assert_not_called()

    def test_qemu_delete_fails_when_expected_domain_remains(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(
                root,
                "application",
                machine_data=[self._owner_state()],
            )
            config = self._qemu_delete_config(tempdir)

            with mock.patch.object(
                test_utils.Machine,
                "process",
                return_value=[(["cloud0_test"], [])],
            ):
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={},
                )

            self.assertFalse(success)
            self.assertIn("VM domain(s) still present on local: cloud0_test", reason)

    def test_qemu_delete_passes_when_expected_domains_are_absent(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(
                root,
                "application",
                machine_data=[self._owner_state()],
            )
            config = self._qemu_delete_config(tempdir)

            with mock.patch.object(
                test_utils.Machine,
                "process",
                return_value=[([], [])],
            ):
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={"require_teardown": False},
                )

            self.assertTrue(success)
            self.assertIn("teardown_verified", reason)

    def test_non_qemu_delete_preserves_explicitly_disabled_artifact_criteria(self):
        criteria = {
            "require_ssh_output": False,
            "require_experiment_lock": False,
            "require_state_file": False,
            "require_state_phase": False,
            "require_resume_contract": False,
            "require_teardown": False,
        }
        for provider in ("aws", "gcp"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as tempdir:
                config = self._qemu_delete_config(tempdir)
                config["infrastructure"]["provider"] = provider

                with mock.patch.object(test_utils, "verify_qemu_teardown") as verify_mock:
                    success, reason = test_utils.detect_success(
                        stdout="",
                        stderr="",
                        exit_code=0,
                        config=config,
                        success_config=criteria,
                    )

                self.assertTrue(success)
                self.assertEqual(reason, "Success: exit_code=0")
                verify_mock.assert_not_called()

    def test_explicit_require_teardown_behavior_remains_enabled(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(
                root,
                "application",
                machine_data=[self._owner_state()],
            )
            config = self._qemu_delete_config(tempdir)

            with mock.patch.object(
                test_utils,
                "verify_qemu_teardown",
                return_value=(True, "teardown_verified"),
            ) as verify_mock:
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={"require_teardown": True},
                )

            self.assertTrue(success)
            self.assertIn("teardown_verified", reason)
            verify_mock.assert_called_once()

    def test_retained_qemu_skips_teardown_verification(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            _write_success_artifacts(root, "application")
            config = self._qemu_delete_config(tempdir)
            config["infrastructure"]["delete_on_exit"] = False

            with mock.patch.object(test_utils, "verify_qemu_teardown") as verify_mock:
                success, reason = test_utils.detect_success(
                    stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
                    stderr="",
                    exit_code=0,
                    config=config,
                    success_config={"require_teardown": False},
                )

            self.assertTrue(success)
            self.assertNotIn("teardown_verified", reason)
            verify_mock.assert_not_called()

    def test_qemu_teardown_verification_isolates_domains_by_physical_owner(self):
        config = self._qemu_delete_config("/tmp/not-used")
        state_payload = {
            "machine_data": [
                self._owner_state(domains=["local-domain"]),
                self._owner_state(
                    name="operator@external.invalid",
                    is_local=False,
                    domains=["external-domain"],
                ),
            ]
        }
        calls = []

        def owner_aware_result(machine, _config, command, ssh=None, ssh_key=True):
            calls.append((machine.name, command, ssh, ssh_key))
            if machine.is_local:
                return [(["external-domain"], [])]
            return [(["local-domain"], [])]

        with mock.patch.object(test_utils.Machine, "process", autospec=True) as process_mock:
            process_mock.side_effect = owner_aware_result
            success, reason = test_utils.verify_qemu_teardown(config, state_payload)

        self.assertTrue(success)
        self.assertEqual(reason, "teardown_verified")
        self.assertEqual(
            calls,
            [
                ("local", ["virsh", "list", "--all", "--name"], "local", False),
                (
                    "operator@external.invalid",
                    ["virsh", "list", "--all", "--name"],
                    "operator@external.invalid",
                    False,
                ),
            ],
        )

    def test_qemu_teardown_rejects_malformed_non_local_owner_identities(self):
        malformed_names = (
            None,
            "",
            "   ",
            "external.invalid",
            "@external.invalid",
            "operator@",
            "operator@external.invalid@extra",
            "operator @external.invalid",
            "operator@external invalid",
        )
        config = self._qemu_delete_config("/tmp/not-used")
        for owner_name in malformed_names:
            with self.subTest(owner_name=owner_name):
                state_payload = {
                    "machine_data": [
                        self._owner_state(name=owner_name, is_local=False),
                    ]
                }
                with mock.patch.object(test_utils.Machine, "process") as process_mock:
                    success, reason = test_utils.verify_qemu_teardown(config, state_payload)

                self.assertFalse(success)
                self.assertIn("physical owner identity", reason)
                process_mock.assert_not_called()

    def test_qemu_teardown_contains_owner_constructor_failures(self):
        config = self._qemu_delete_config("/tmp/not-used")
        state_payload = {
            "machine_data": [
                self._owner_state(name="operator@external.invalid", is_local=False),
            ]
        }

        with mock.patch.object(
            test_utils,
            "Machine",
            side_effect=ValueError("constructor rejected owner"),
        ):
            success, reason = test_utils.verify_qemu_teardown(config, state_payload)

        self.assertFalse(success)
        self.assertIn("constructor rejected owner", reason)

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
                    "success_reason": "Benchmark metric artifact statistic failed: latency",
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
