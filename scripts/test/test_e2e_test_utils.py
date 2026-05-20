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
    module_path = Path(__file__).with_name("test_utils.py")
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
                stdout="ssh cloud0@192.168.0.10 -i /tmp/test_key\n",
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
