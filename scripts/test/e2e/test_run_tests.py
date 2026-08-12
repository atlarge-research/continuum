"""Regression tests for the end-to-end test runner CLI."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
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


def _wait_for_path(path, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for %s" % path)


def _spawn_process_tree(directory, ignore_grandchild_sigterm=False):
    ready_path = directory / "grandchild-ready"
    release_path = directory / "release-grandchild"
    sentinel_path = directory / "delayed-sentinel"
    grandchild_code = """
import signal
import sys
import time
from pathlib import Path

ready_path = Path(sys.argv[1])
release_path = Path(sys.argv[2])
sentinel_path = Path(sys.argv[3])
if sys.argv[4] == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
ready_path.write_text("ready", encoding="utf-8")
while not release_path.exists():
    time.sleep(0.01)
sentinel_path.write_text("survived", encoding="utf-8")
"""
    child_code = """
import subprocess
import sys
import time

subprocess.Popen(
    [sys.executable, "-u", "-c", %r, *sys.argv[1:]],
)
print("child-output", flush=True)
print("child-error", file=sys.stderr, flush=True)
while True:
    time.sleep(1)
""" % grandchild_code
    parent_code = """
import subprocess
import sys
import time

subprocess.Popen(
    [sys.executable, "-u", "-c", %r, *sys.argv[1:]],
)
print("parent-output", flush=True)
while True:
    time.sleep(1)
""" % child_code
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            parent_code,
            str(ready_path),
            str(release_path),
            str(sentinel_path),
            "ignore-term" if ignore_grandchild_sigterm else "handle-term",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_for_path(ready_path)
    except BaseException:
        coordinator = run_tests_module._RunnerSignalCoordinator()
        coordinator.claim(process)
        _emergency_cleanup(process, coordinator)
        raise
    return process, release_path, sentinel_path


def _emergency_cleanup(process, coordinator):
    """Test-only cleanup, gated against a confirmed-stale process group."""
    if coordinator.group_absent:
        return
    try:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            coordinator.group_absent = True
        process.communicate(timeout=2)
    except BaseException as exc:
        raise run_tests_module._RunnerInfrastructureError("Emergency cleanup failed") from exc


class _SignalingProcess:
    def __init__(self, process, signum):
        self._process = process
        self._signum = signum
        self._signaled = False

    @property
    def pid(self):
        return self._process.pid

    @property
    def returncode(self):
        return self._process.returncode

    def poll(self):
        return self._process.poll()

    def communicate(self, *args, **kwargs):
        if not self._signaled:
            self._signaled = True
            os.kill(os.getpid(), self._signum)
        return self._process.communicate(*args, **kwargs)


def _basic_config():
    return {
        "infrastructure": {"base_path": "/tmp", "infra_only": False},
        "benchmark": {"resource_manager_only": False},
    }


def _mock_process(returncode=0, stdout=b"output\n", stderr=b""):
    process = mock.Mock(pid=424242)
    process.returncode = returncode
    process.poll.return_value = returncode
    process.communicate.return_value = (stdout, stderr)
    return process


def _run_with_process(process, detection=(True, "ok"), **kwargs):
    with (
        mock.patch.object(run_tests_module.test_utils, "parse_config_simple", return_value=_basic_config()),
        mock.patch.object(run_tests_module.test_utils, "identify_base_images", return_value=[]),
        mock.patch.object(run_tests_module.test_utils, "detect_success", return_value=detection),
        mock.patch.object(run_tests_module.subprocess, "Popen", return_value=process) as popen,
        mock.patch.object(run_tests_module.os, "killpg", side_effect=ProcessLookupError),
    ):
        result = run_tests_module.run_single_test("config.yaml", {}, **kwargs)
    return result, popen


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
    def test_direct_wrapper_preserves_success_temp_cleanup_and_session_launch(self):
        previous = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
        with tempfile.TemporaryDirectory() as tempdir:
            override = Path(tempdir) / "override.yaml"
            override.write_text("infrastructure: {}\n", encoding="utf-8")
            process = _mock_process()
            with (
                mock.patch.object(
                    run_tests_module.test_utils,
                    "parse_config_simple",
                    side_effect=[_basic_config(), _basic_config()],
                ),
                mock.patch.object(
                    run_tests_module.test_utils, "identify_base_images", return_value=[]
                ),
                mock.patch.object(
                    run_tests_module.test_utils,
                    "override_config_parameters",
                    return_value=str(override),
                ),
                mock.patch.object(
                    run_tests_module.test_utils,
                    "detect_success",
                    return_value=(True, "completed"),
                ),
                mock.patch.object(
                    run_tests_module.subprocess, "Popen", return_value=process
                ) as popen,
                mock.patch.object(
                    run_tests_module.os, "killpg", side_effect=ProcessLookupError
                ),
            ):
                result = run_tests_module.run_single_test(
                    "config.yaml", {}, base_path_override=tempdir
                )
        self.assertTrue(result["success"])
        self.assertFalse(override.exists())
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(
            previous,
            (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)),
        )
    def test_normal_nonzero_execution_preserves_output(self):
        result, _ = _run_with_process(
            _mock_process(23, b"normal output\n", b"normal error\n"),
            detection=(False, "nonzero"),
        )
        self.assertEqual(result["exit_code"], 23)
        self.assertEqual(result["stdout"], "normal output\n")
        self.assertEqual(result["stderr"], "normal error\n")
        self.assertFalse(result["success"])
        self.assertFalse(result["timed_out"])
    def test_child_inherits_unblocked_sigint_and_sigterm(self):
        child_code = """
import signal
line = next(line for line in open("/proc/self/status", encoding="utf-8")
            if line.startswith("SigBlk:"))
mask = int(line.split()[1], 16)
print(int(bool(mask & (1 << (signal.SIGINT - 1)))),
      int(bool(mask & (1 << (signal.SIGTERM - 1)))), flush=True)
"""
        real_popen = subprocess.Popen
        def launch(_cmd, **kwargs):
            return real_popen([sys.executable, "-u", "-c", child_code], **kwargs)
        with (
            mock.patch.object(
                run_tests_module.test_utils,
                "parse_config_simple",
                return_value=_basic_config(),
            ),
            mock.patch.object(
                run_tests_module.test_utils, "identify_base_images", return_value=[]
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "detect_success",
                return_value=(True, "probe"),
            ),
            mock.patch.object(run_tests_module.subprocess, "Popen", side_effect=launch),
        ):
            result = run_tests_module.run_single_test("config.yaml", {})
        self.assertEqual(result["stdout"].strip(), "0 0")
    def test_timeout_result_contract_and_already_absent_group(self):
        process = _mock_process(stdout=b"before timeout\n", stderr=b"timeout error\n")
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["continuum"], 0),
            (b"before timeout\n", b"timeout error\n"),
        ]
        result, _ = _run_with_process(process, timeout_minutes=0)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], -1)
        self.assertEqual(result["stdout"], "before timeout\n")
        self.assertEqual(result["stderr"], "timeout error\n")
    def _run_real_timeout(self, ignore_term):
        real_killpg = os.killpg
        with tempfile.TemporaryDirectory() as tempdir:
            process, release, sentinel = _spawn_process_tree(
                Path(tempdir), ignore_grandchild_sigterm=ignore_term
            )
            coordinator = run_tests_module._RunnerSignalCoordinator()
            try:
                with (
                    coordinator,
                    mock.patch.object(
                        run_tests_module.test_utils,
                        "parse_config_simple",
                        return_value=_basic_config(),
                    ),
                    mock.patch.object(
                        run_tests_module.test_utils,
                        "identify_base_images",
                        return_value=[],
                    ),
                    mock.patch.object(
                        run_tests_module.subprocess, "Popen", return_value=process
                    ),
                    mock.patch.object(
                        run_tests_module.os, "killpg", wraps=real_killpg
                    ) as killpg,
                    mock.patch.object(
                        run_tests_module,
                        "_PROCESS_GROUP_CLEANUP_GRACE_SECONDS",
                        0.05,
                    ),
                ):
                    result = run_tests_module._run_single_test(
                        "config.yaml", {}, timeout_minutes=0, coordinator=coordinator
                    )
            finally:
                _emergency_cleanup(process, coordinator)
            release.write_text("release", encoding="utf-8")
            time.sleep(0.1)
            self.assertFalse(sentinel.exists())
            self.assertIn("parent-output", result["stdout"])
            self.assertIn("child-output", result["stdout"])
            return result, [call.args[1] for call in killpg.call_args_list]
    def test_graceful_tree_timeout_uses_sigterm_and_drains_pipes(self):
        result, signals = self._run_real_timeout(ignore_term=False)
        self.assertTrue(result["timed_out"])
        self.assertIn(signal.SIGTERM, signals)
        self.assertNotIn(signal.SIGKILL, signals)
    def test_sigterm_ignoring_descendant_requires_sigkill_without_sentinel(self):
        result, signals = self._run_real_timeout(ignore_term=True)
        self.assertTrue(result["timed_out"])
        self.assertIn(signal.SIGKILL, signals)

    def _assert_real_cancellation(self, signum, expected_exception):
        with tempfile.TemporaryDirectory() as tempdir:
            process, release, sentinel = _spawn_process_tree(Path(tempdir))
            signaling_process = _SignalingProcess(process, signum)
            coordinator = run_tests_module._RunnerSignalCoordinator()
            try:
                with (
                    self.assertRaises(expected_exception) as raised,
                    coordinator,
                    mock.patch.object(
                        run_tests_module.test_utils,
                        "parse_config_simple",
                        return_value=_basic_config(),
                    ),
                    mock.patch.object(
                        run_tests_module.test_utils,
                        "identify_base_images",
                        return_value=[],
                    ),
                    mock.patch.object(
                        run_tests_module.subprocess,
                        "Popen",
                        return_value=signaling_process,
                    ),
                    mock.patch.object(
                        run_tests_module,
                        "_PROCESS_GROUP_CLEANUP_GRACE_SECONDS",
                        0.2,
                    ),
                ):
                    run_tests_module._run_single_test(
                        "config.yaml", {}, coordinator=coordinator
                    )
            finally:
                _emergency_cleanup(process, coordinator)
            release.write_text("release", encoding="utf-8")
            time.sleep(0.1)
            self.assertFalse(sentinel.exists())
            self.assertTrue(coordinator.group_absent)
            self.assertIsNone(coordinator.process)
            return raised.exception
    def test_real_tree_sigint_cleans_then_raises_keyboard_interrupt(self):
        self._assert_real_cancellation(signal.SIGINT, KeyboardInterrupt)
    def test_real_tree_sigterm_cleans_then_exits_143(self):
        exception = self._assert_real_cancellation(signal.SIGTERM, SystemExit)
        self.assertEqual(exception.code, 143)
    def test_cancellation_during_popen_claims_and_cleans_returned_process(self):
        process = _mock_process()
        def launch(_cmd, **_kwargs):
            os.kill(os.getpid(), signal.SIGINT)
            return process
        with (
            mock.patch.object(
                run_tests_module.test_utils,
                "parse_config_simple",
                return_value=_basic_config(),
            ),
            mock.patch.object(
                run_tests_module.test_utils, "identify_base_images", return_value=[]
            ),
            mock.patch.object(run_tests_module.subprocess, "Popen", side_effect=launch),
            mock.patch.object(
                run_tests_module.os, "killpg", side_effect=ProcessLookupError
            ) as killpg,
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_tests_module.run_single_test("config.yaml", {})
        self.assertEqual(killpg.call_args.args, (process.pid, signal.SIGTERM))
        process.communicate.assert_called_once()
    def test_popen_failure_gives_recorded_cancellation_precedence_and_context(self):
        launch_error = OSError("launch failed")
        def launch(_cmd, **_kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            raise launch_error
        with (
            mock.patch.object(
                run_tests_module.test_utils,
                "parse_config_simple",
                return_value=_basic_config(),
            ),
            mock.patch.object(
                run_tests_module.test_utils, "identify_base_images", return_value=[]
            ),
            mock.patch.object(run_tests_module.subprocess, "Popen", side_effect=launch),
        ):
            with self.assertRaises(SystemExit) as raised:
                run_tests_module.run_single_test("config.yaml", {})
        self.assertEqual(raised.exception.code, 143)
        self.assertIs(raised.exception.__context__, launch_error)
    def test_cancellation_between_tests_prevents_launch_and_handlers_are_scoped_once(self):
        calls = []
        real_signal = signal.signal

        def execute(*_args, **kwargs):
            calls.append(kwargs["coordinator"])
            kwargs["coordinator"]._record_cancellation(signal.SIGINT, None)
            return {"success": True, "execution_time": 0, "success_reason": "ok"}
        with (
            mock.patch.object(
                run_tests_module.test_utils,
                "parse_config_simple",
                return_value=_basic_config(),
            ),
            mock.patch.object(
                run_tests_module.test_utils, "identify_base_images", return_value=[]
            ),
            mock.patch.object(
                run_tests_module.test_utils, "get_base_image_paths", return_value=[]
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "should_rebuild_base_images",
                return_value=False,
            ),
            mock.patch.object(run_tests_module, "_run_single_test", side_effect=execute),
            mock.patch.object(
                run_tests_module.signal, "signal", wraps=real_signal
            ) as signal_mock,
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_tests_module.run_tests(["one.yaml", "two.yaml"], {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(signal_mock.call_count, 4)

    def test_first_cancellation_signal_wins(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        coordinator._record_cancellation(signal.SIGTERM, None)
        coordinator._record_cancellation(signal.SIGINT, None)
        exception = coordinator.cancellation_exception()
        self.assertIsInstance(exception, SystemExit)
        self.assertEqual(exception.code, 143)

    def test_esrch_publishes_absence_and_stops_stale_group_operations(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        process = _mock_process()
        coordinator.claim(process)
        with mock.patch.object(
            run_tests_module.os, "killpg", side_effect=ProcessLookupError
        ) as killpg:
            output = run_tests_module._cleanup_owned_process(coordinator)
            coordinator.release()

        self.assertEqual(output, (b"output\n", b""))
        killpg.assert_called_once_with(process.pid, signal.SIGTERM)
        self.assertTrue(coordinator.group_absent)
        self.assertIsNone(coordinator.process)

    def test_unresolved_cleanup_failure_prevents_restoration_and_next_test(self):
        process = _mock_process()
        executions = []

        def fail(*_args, **kwargs):
            executions.append(1)
            kwargs["coordinator"].claim(process)
            raise run_tests_module._RunnerInfrastructureError("cleanup failed")

        with (
            mock.patch.object(
                run_tests_module.test_utils,
                "parse_config_simple",
                return_value=_basic_config(),
            ),
            mock.patch.object(
                run_tests_module.test_utils, "identify_base_images", return_value=[]
            ),
            mock.patch.object(
                run_tests_module.test_utils, "get_base_image_paths", return_value=[]
            ),
            mock.patch.object(
                run_tests_module.test_utils,
                "should_rebuild_base_images",
                return_value=False,
            ),
            mock.patch.object(run_tests_module, "_run_single_test", side_effect=fail),
            mock.patch.object(run_tests_module.signal, "signal") as signal_mock,
        ):
            with self.assertRaisesRegex(
                run_tests_module._RunnerInfrastructureError, "cleanup failed"
            ):
                run_tests_module.run_tests(["one.yaml", "two.yaml"], {})

        self.assertEqual(executions, [1])
        self.assertEqual(signal_mock.call_count, 2)

    def test_ownership_clears_only_after_absence_and_leader_reap(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        process = _mock_process()
        process.returncode = None
        coordinator.claim(process)
        coordinator.group_absent = True
        with self.assertRaises(run_tests_module._RunnerInfrastructureError):
            coordinator.release()
        process.returncode = 0
        coordinator.release()
        self.assertIsNone(coordinator.process)

    def test_drain_failure_after_absence_does_not_touch_stale_group(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        coordinator.previous_handlers = (object(), object())
        coordinator.installed = 2
        process = _mock_process()
        process.communicate.side_effect = OSError("drain failed")
        coordinator.claim(process)
        coordinator.group_absent = True

        with (
            mock.patch.object(run_tests_module.os, "killpg") as killpg,
            mock.patch.object(run_tests_module.signal, "signal") as restore,
        ):
            with self.assertRaises(run_tests_module._RunnerInfrastructureError) as raised:
                run_tests_module._cleanup_owned_process(coordinator)
            self.assertFalse(coordinator.__exit__(
                run_tests_module._RunnerInfrastructureError, raised.exception, None
            ))
            restore.assert_not_called()
            coordinator.release()
            self.assertFalse(coordinator.__exit__(None, None, None))

        killpg.assert_not_called()
        self.assertEqual(restore.call_count, 2)

    def test_permission_error_is_cleanup_failure_and_keeps_ownership(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        process = _mock_process()
        coordinator.claim(process)
        with mock.patch.object(
            run_tests_module.os, "killpg", side_effect=PermissionError("denied")
        ):
            with self.assertRaisesRegex(
                run_tests_module._RunnerInfrastructureError, "denied"
            ):
                run_tests_module._cleanup_owned_process(coordinator)
        self.assertFalse(coordinator.group_absent)
        self.assertIs(coordinator.process, process)

    def test_final_restoration_failure_is_infrastructure_failure_and_attempts_both(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        coordinator.previous_handlers = (object(), object())
        coordinator.installed = 2
        with mock.patch.object(
            run_tests_module.signal,
            "signal",
            side_effect=[OSError("restore failed"), None],
        ) as restore:
            with self.assertRaisesRegex(
                run_tests_module._RunnerInfrastructureError, "restore failed"
            ):
                coordinator.__exit__(None, None, None)
        self.assertEqual(restore.call_count, 2)

    def test_test_emergency_cleanup_is_gated_after_confirmed_absence(self):
        coordinator = run_tests_module._RunnerSignalCoordinator()
        process = _mock_process()
        coordinator.group_absent = True
        with mock.patch.object(run_tests_module.os, "killpg") as killpg:
            _emergency_cleanup(process, coordinator)
        killpg.assert_not_called()
        process.communicate.assert_not_called()
    def test_process_tree_setup_failure_uses_owned_emergency_cleanup(self):
        process = _mock_process()
        setup_error = RuntimeError("setup failed")
        with (
            mock.patch.object(subprocess, "Popen", return_value=process),
            mock.patch(__name__ + "._wait_for_path", side_effect=setup_error),
            mock.patch.object(os, "killpg") as killpg,
        ):
            with self.assertRaises(RuntimeError) as raised:
                _spawn_process_tree(Path("/tmp"))
        self.assertIs(raised.exception, setup_error)
        killpg.assert_called_once_with(process.pid, signal.SIGKILL)
        process.communicate.assert_called_once_with(timeout=2)
