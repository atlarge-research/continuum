"""Regression tests for the end-to-end test runner CLI."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_run_tests_module():
    module_path = Path(__file__).resolve().parents[1] / "run_tests.py"
    spec = importlib.util.spec_from_file_location("continuum_run_tests", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_tests_module = _load_run_tests_module()


class RunTestsCliTests(unittest.TestCase):
    def setUp(self):
        self.test_config_path = str(
            (Path(__file__).resolve().parents[1] / "test_config.json").resolve()
        )

    def test_kubecontrol_trace_suite_requires_full_metric_evidence(self):
        config = run_tests_module.load_test_config(self.test_config_path)
        suite = config["test_suites"]["qemu_kubecontrol_empty_trace_parity"]
        success_detection = suite["success_detection"]
        expected_columns = [
            "controller_read_workload (s)",
            "controller_unpacked_workload (s)",
            "scheduler_read_pod (s)",
            "kubelet_pod_received (s)",
            "kubelet_applied_sandbox (s)",
            "started_application (s)",
        ]

        stdout_table = success_detection["required_stdout_metric_tables"][0]
        artifact_table = success_detection["required_benchmark_metric_artifacts"][0]

        self.assertEqual(stdout_table["label"], "CLOUD OUTPUT")
        self.assertEqual(stdout_table["columns"], expected_columns)
        self.assertEqual(stdout_table["min_rows"], 1)
        self.assertEqual(artifact_table["label"], "CLOUD OUTPUT")
        self.assertEqual(artifact_table["columns"], expected_columns)
        self.assertEqual(artifact_table["numeric_columns"], expected_columns)
        self.assertEqual(artifact_table["min_rows"], 1)
        checks_by_name = {
            check["name"]: check["command"]
            for check in suite["prerequisites"]["checks"]
        }
        self.assertEqual(
            checks_by_name["Host helper interface"],
            ["sh", "scripts/test/setup_agent_host.sh", "verify"],
        )
        helper_check = next(
            check
            for check in suite["prerequisites"]["checks"]
            if check["name"] == "Host helper interface"
        )
        self.assertEqual(helper_check["skip_when_env"], ["CONTINUUM_SMOKE_BASE_ROOT"])
        self.assertIn("--check-only", checks_by_name["Local registry cache"])

    def test_kube_kata_empty_startup_suite_requires_kata_artifact_evidence(self):
        config = run_tests_module.load_test_config(self.test_config_path)
        suite = config["test_suites"]["qemu_kube_kata_empty_startup_parity"]
        success_detection = suite["success_detection"]

        self.assertTrue(success_detection["require_teardown"])
        self.assertIn(
            "configs/experiments/parity/qemu_kube_kata_empty_startup/",
            suite["directories"],
        )
        self.assertIn(
            "Wrote benchmark metric artifact manifest",
            success_detection["required_stdout_markers"],
        )

        stdout_table = success_detection["required_stdout_metric_tables"][0]
        self.assertEqual(stdout_table["label"], "CLOUD OUTPUT")
        self.assertEqual(stdout_table["min_rows"], 100)

        artifact_tables = {
            table["label"]: table
            for table in success_detection["required_benchmark_metric_artifacts"]
        }
        self.assertEqual(artifact_tables["CLOUD OUTPUT"]["min_rows"], 100)
        self.assertEqual(artifact_tables["KATA OUTPUT"]["min_rows"], 100)
        self.assertIn(
            "kata_create_vm (s)",
            artifact_tables["KATA OUTPUT"]["columns"],
        )
        checks_by_name = {
            check["name"]: check["command"]
            for check in suite["prerequisites"]["checks"]
        }
        self.assertEqual(
            checks_by_name["Kata host prerequisites"],
            [
                "python3",
                "scripts/test/check_kata_host_prereqs.py",
                "--min-cores",
                "16",
                "--min-memory-gb",
                "160",
                "--require-nested-kvm",
            ],
        )
        self.assertIn("--check-only", checks_by_name["Local registry cache"])

    def test_main_accepts_dynamic_suite_from_loaded_config(self):
        fake_test_config = {
            "test_suites": {
                "smoke": {"directories": ["configs/experiments/"]},
                "network_validation": {
                    "directories": ["configs/experiments/network_validation/"],
                    "use_cache": True,
                    "rebuild_base_images": False,
                },
            },
            "exclude_patterns": ["template.yaml"],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "network_validation",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "discover_config_files",
                return_value=["configs/experiments/network_validation/bench_net_4g.yaml"],
            ) as discover_mock,
            mock.patch.object(
                run_tests_module,
                "run_tests",
                return_value=[{"success": True, "execution_time": 0.1}],
            ),
            mock.patch.object(run_tests_module, "print_summary"),
            mock.patch.object(
                run_tests_module.test_utils,
                "save_test_results",
                return_value="logs/test_results/test.json",
            ),
            mock.patch.object(run_tests_module, "print_colored"),
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 0)
        discover_mock.assert_called_once_with(
            ["configs/experiments/network_validation/"],
            ["template.yaml"],
            manifest=None,
            provider=None,
        )

    def test_main_rejects_unknown_suite_from_loaded_config(self):
        fake_test_config = {
            "test_suites": {
                "smoke": {"directories": ["configs/experiments/"]},
            },
            "exclude_patterns": [],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "network_validation",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(run_tests_module, "print_colored") as print_mock,
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 1)
        printed_messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertTrue(
            any("Unknown test suite 'network_validation'" in message for message in printed_messages)
        )

    def test_main_uses_suite_stop_on_failure_default(self):
        fake_test_config = {
            "stop_on_failure": False,
            "test_suites": {
                "smoke": {
                    "directories": ["configs/experiments/smoke/"],
                    "stop_on_failure": True,
                },
            },
            "exclude_patterns": ["template.yaml"],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "smoke",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "discover_config_files",
                return_value=["configs/experiments/smoke/infra_one_vm.yaml"],
            ),
            mock.patch.object(
                run_tests_module,
                "run_tests",
                return_value=[{"success": True, "execution_time": 0.1}],
            ) as run_tests_mock,
            mock.patch.object(run_tests_module, "print_summary"),
            mock.patch.object(
                run_tests_module.test_utils,
                "save_test_results",
                return_value="logs/test_results/test.json",
            ),
            mock.patch.object(run_tests_module, "print_colored"),
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 0)
        self.assertTrue(run_tests_mock.call_args.kwargs["stop_on_failure"])

    def test_main_merges_suite_success_detection_overrides(self):
        fake_test_config = {
            "success_detection": {
                "require_exit_code_zero": True,
            },
            "test_suites": {
                "benchmark_smoke": {
                    "directories": ["configs/experiments/benchmark_smoke/"],
                    "success_detection": {
                        "require_teardown": True,
                        "required_stdout_markers": ["ENDPOINT OUTPUT"],
                    },
                },
            },
            "exclude_patterns": [],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "benchmark_smoke",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "discover_config_files",
                return_value=[
                    "configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml"
                ],
            ),
            mock.patch.object(
                run_tests_module,
                "run_tests",
                return_value=[{"success": True, "execution_time": 0.1}],
            ) as run_tests_mock,
            mock.patch.object(run_tests_module, "print_summary"),
            mock.patch.object(
                run_tests_module.test_utils,
                "save_test_results",
                return_value="logs/test_results/test.json",
            ),
            mock.patch.object(run_tests_module, "print_colored"),
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 0)
        run_config = run_tests_mock.call_args.args[1]
        self.assertTrue(run_config["success_detection"]["require_exit_code_zero"])
        self.assertTrue(run_config["success_detection"]["require_teardown"])
        self.assertEqual(
            run_config["success_detection"]["required_stdout_markers"],
            ["ENDPOINT OUTPUT"],
        )

    def test_merge_success_detection_allows_network_infra_override(self):
        merged = run_tests_module.merge_success_detection_config(
            {
                "success_detection": {
                    "require_exit_code_zero": True,
                    "infra_only_override": {
                        "require_ssh_output": False,
                    },
                }
            },
            {
                "success_detection": {
                    "infra_only_override": {
                        "require_ssh_output": False,
                        "require_network_validation_results": True,
                    }
                }
            },
        )

        self.assertTrue(
            merged["success_detection"]["infra_only_override"][
                "require_network_validation_results"
            ]
        )

    def test_main_rejects_suite_when_prerequisite_commands_are_missing(self):
        fake_test_config = {
            "test_suites": {
                "smoke": {
                    "directories": ["configs/experiments/smoke/"],
                    "prerequisites": {
                        "summary": "Requires local QEMU/libvirt access",
                        "commands": ["virsh", "ssh"],
                    },
                },
            },
            "exclude_patterns": [],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "smoke",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(run_tests_module.shutil, "which", side_effect=lambda cmd: None),
            mock.patch.object(run_tests_module, "print_colored") as print_mock,
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 1)
        printed_messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertTrue(any("Suite 'smoke' prerequisites" in message for message in printed_messages))
        self.assertTrue(
            any(
                "Missing required host command(s) for suite 'smoke': virsh, ssh" in message
                for message in printed_messages
            )
        )

    def test_main_rejects_suite_when_prerequisite_check_fails(self):
        fake_test_config = {
            "test_suites": {
                "app_parity": {
                    "directories": ["configs/experiments/parity/qemu_k8s_image/"],
                    "prerequisites": {
                        "summary": "Requires Docker daemon access",
                        "commands": ["docker"],
                        "checks": [
                            {
                                "name": "Docker daemon access",
                                "command": ["docker", "info"],
                            }
                        ],
                    },
                },
            },
            "exclude_patterns": [],
        }

        failed_check = run_tests_module.subprocess.CompletedProcess(
            args=["docker", "info"],
            returncode=1,
            stdout="",
            stderr="permission denied while trying to connect to the Docker daemon socket\n",
        )
        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "app_parity",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(run_tests_module.shutil, "which", return_value="/usr/bin/mock"),
            mock.patch.object(run_tests_module.subprocess, "run", return_value=failed_check),
            mock.patch.object(run_tests_module, "print_colored") as print_mock,
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 1)
        printed_messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertTrue(
            any(
                "Failed prerequisite check(s) for suite 'app_parity': Docker daemon access: permission denied"
                in message
                for message in printed_messages
            )
        )

    def test_prerequisite_check_can_be_skipped_when_env_is_set(self):
        suite_config = {
            "prerequisites": {
                "checks": [
                    {
                        "name": "Operator-only check",
                        "command": ["false"],
                        "skip_when_env": ["CONTINUUM_SMOKE_BASE_ROOT"],
                    }
                ]
            }
        }

        with mock.patch.dict(
            run_tests_module.os.environ,
            {"CONTINUUM_SMOKE_BASE_ROOT": "/tmp/smoke"},
        ):
            failures = run_tests_module.validate_suite_prerequisite_checks(
                "app_parity",
                suite_config,
            )

        self.assertEqual(failures, [])

    def test_prerequisite_check_rejects_invalid_skip_env_config(self):
        suite_config = {
            "prerequisites": {
                "checks": [
                    {
                        "name": "Operator-only check",
                        "command": ["true"],
                        "skip_when_env": "CONTINUUM_SMOKE_BASE_ROOT",
                    }
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, "skip_when_env must be a list"):
            run_tests_module.validate_suite_prerequisite_checks(
                "app_parity",
                suite_config,
            )

    def test_prerequisite_check_failure_prefers_actionable_stdout(self):
        failed_check = run_tests_module.subprocess.CompletedProcess(
            args=["python3", "scripts/test/prime_local_registry_cache.py"],
            returncode=1,
            stdout="MISSING config.yaml: 8 of 8 image(s) absent from 127.0.0.1:5000\n",
            stderr="Matplotlib created a temporary cache directory at /tmp/mpl\n",
        )

        reason = run_tests_module._prerequisite_check_failure_reason(failed_check)

        self.assertEqual(
            reason,
            "MISSING config.yaml: 8 of 8 image(s) absent from 127.0.0.1:5000",
        )

    def test_main_lists_configured_suites(self):
        fake_test_config = {
            "test_suites": {
                "smoke": {
                    "directories": ["configs/experiments/smoke/"],
                    "prerequisites": {
                        "summary": "Requires local QEMU/libvirt access",
                        "commands": ["virsh", "ssh"],
                    },
                },
                "full": {
                    "directories": ["configs/experiments/"],
                },
            },
            "exclude_patterns": [],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--list-suites",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(run_tests_module, "print_colored") as print_mock,
            mock.patch("builtins.print") as builtins_print,
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 0)
        colored_messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertTrue(any("Configured test suites:" in message for message in colored_messages))
        plain_messages = [call.args[0] for call in builtins_print.call_args_list]
        self.assertTrue(any("directories: configs/experiments/smoke/" in message for message in plain_messages))
        self.assertTrue(any("prerequisites: Requires local QEMU/libvirt access" in message for message in plain_messages))

    def test_main_check_prereqs_succeeds_for_selected_suite(self):
        fake_test_config = {
            "test_suites": {
                "smoke": {
                    "directories": ["configs/experiments/smoke/"],
                    "prerequisites": {
                        "summary": "Requires local QEMU/libvirt access",
                        "commands": ["virsh", "ssh"],
                    },
                },
            },
            "exclude_patterns": [],
        }

        with (
            mock.patch.object(
                run_tests_module.sys,
                "argv",
                [
                    "run_tests.py",
                    "--suite",
                    "smoke",
                    "--check-prereqs",
                    "--test-config",
                    self.test_config_path,
                ],
            ),
            mock.patch.object(
                run_tests_module, "load_test_config", return_value=fake_test_config
            ),
            mock.patch.object(run_tests_module.shutil, "which", return_value="/usr/bin/mock"),
            mock.patch.object(run_tests_module, "print_colored") as print_mock,
        ):
            with self.assertRaises(SystemExit) as exc:
                run_tests_module.main()

        self.assertEqual(exc.exception.code, 0)
        colored_messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertTrue(any("Suite 'smoke': Requires local QEMU/libvirt access" in message for message in colored_messages))
        self.assertTrue(any("Prerequisites satisfied" in message for message in colored_messages))

    def test_resolve_results_dir_prefers_env_override(self):
        with mock.patch.dict(
            run_tests_module.os.environ,
            {"CONTINUUM_TEST_RESULTS_DIR": "/tmp/custom-results"},
        ):
            self.assertEqual(
                run_tests_module.resolve_results_dir(base_path_override="/tmp/ignored"),
                "/tmp/custom-results",
            )

    def test_resolve_results_dir_uses_base_path_workspace(self):
        with mock.patch.dict(run_tests_module.os.environ, {}, clear=True):
            self.assertEqual(
                run_tests_module.resolve_results_dir(base_path_override="/tmp/continuum-run"),
                "/tmp/continuum-run/.continuum/test_results",
            )


class RunSingleTestTests(unittest.TestCase):
    def test_run_single_test_uses_overridden_base_path_for_success_detection(self):
        with tempfile.TemporaryDirectory() as tempdir:
            override_path = Path(tempdir) / "override-lock.yaml"
            override_path.write_text("kind: ContinuumExperimentLock\n", encoding="utf-8")

            continuum_dir = Path(tempdir) / ".continuum"
            continuum_dir.mkdir(parents=True)
            contract = (
                run_tests_module.test_utils.resume_contract
                .persisted_resume_contract_from_details({"test": "contract"})
            )
            (continuum_dir / "experiment_lock.yaml").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "ContinuumExperimentLock",
                        "resume_contract": contract,
                    }
                ),
                encoding="utf-8",
            )
            (continuum_dir / "state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "kind": "ContinuumState",
                        "created_at": "2026-05-20T00:00:00+00:00",
                        "phase_completed": "infrastructure",
                        "resume_contract": contract,
                        "machine_data": [{"cloud_names": ["cloud0_test"]}],
                    }
                ),
                encoding="utf-8",
            )

            original_config = {
                "infrastructure": {
                    "base_path": "/home/continuum-smoke",
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }
            overridden_config = {
                "infrastructure": {
                    "base_path": tempdir,
                    "infra_only": True,
                },
                "benchmark": {
                    "resource_manager_only": False,
                },
            }

            process = mock.Mock()
            process.communicate.return_value = (b"ssh cloud0@192.168.0.10 -i /tmp/test_key\n", b"")
            process.returncode = 0

            with (
                mock.patch.object(
                    run_tests_module.test_utils,
                    "parse_config_simple",
                    side_effect=[original_config, overridden_config],
                ),
                mock.patch.object(
                    run_tests_module.test_utils,
                    "identify_base_images",
                    return_value=[],
                ),
                mock.patch.object(
                    run_tests_module.test_utils,
                    "override_config_parameters",
                    return_value=str(override_path),
                ),
                mock.patch.object(run_tests_module.subprocess, "Popen", return_value=process),
            ):
                result = run_tests_module.run_single_test(
                    "configs/experiments/smoke/infra_one_vm.yaml",
                    {"success_detection": {}},
                    base_path_override=tempdir,
                )

            self.assertTrue(result["success"])
            self.assertIn("experiment_lock_written", result["success_reason"])
