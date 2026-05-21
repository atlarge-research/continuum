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
