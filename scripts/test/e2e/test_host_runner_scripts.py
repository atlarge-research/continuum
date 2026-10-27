"""Regression tests for host smoke-runner helper scripts."""

# pylint: disable=missing-class-docstring,missing-function-docstring,line-too-long
# pylint: disable=too-many-public-methods

import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class HostRunnerScriptTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[3]
        self.setup_script = self.repo_root / "scripts/test/setup_agent_host.sh"
        self.run_smoke_script = self.repo_root / "scripts/test/run_smoke_host.sh"

    def _run_setup_script(self, *args, extra_env=None):
        env = os.environ.copy()
        env.update(extra_env or {})
        return subprocess.run(
            ["sh", str(self.setup_script), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=self.repo_root,
        )

    def _run_smoke_script(self, *args, extra_env=None):
        env = os.environ.copy()
        env.update(extra_env or {})
        return subprocess.run(
            ["sh", str(self.run_smoke_script), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=self.repo_root,
        )

    def _run_ansible_evidence_fixture(self, scenario, log_setting):
        ansible = Path(sys.executable).with_name("ansible-playbook")
        if not ansible.is_file():
            executable = shutil.which("ansible-playbook")
            if not executable:
                self.skipTest("ansible-playbook is required for real log transport evidence")
            ansible = Path(executable)
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            home = root / "home"
            home.mkdir()
            repo = root / "repo"
            (repo / "scripts/test").mkdir(parents=True)
            (repo / "continuum.py").touch()
            (repo / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
            play = repo / "play.yml"
            play.write_text(
                "- hosts: localhost\n  connection: local\n  gather_facts: false\n"
                "  become: false\n  tasks:\n    - ansible.builtin.debug:\n"
                "        msg: continuum-log-transport-marker\n", encoding="utf-8",
            )
            runner = repo / "scripts/test/run_tests.py"
            runner.write_text(
                "import json, os, subprocess, sys\n"
                "print(json.dumps({'argv': sys.argv[1:], 'env': {key: os.environ.get(key) "
                "for key in ['ANSIBLE_LOG_PATH', 'CONTINUUM_AMBIENT_SENTINEL', "
                "'ANSIBLE_FORCE_COLOR']}}), flush=True)\n"
                "sys.exit(subprocess.run(%r, check=False).returncode)\n"
                % [str(ansible), "-i", "localhost,", str(play)], encoding="utf-8",
            )
            venv_bin = root / "venv/bin"
            venv_bin.mkdir(parents=True)
            python = venv_bin / "python3"
            python.symlink_to(sys.executable)
            evidence = root / "private evidence"
            evidence.mkdir(mode=0o700)
            log = evidence / "ansible $(touch INJECTED); 'quoted' [literal].log"
            log.touch(mode=0o600)
            env = dict(os.environ)
            env.pop("ANSIBLE_LOG_PATH", None)
            env.update({
                "HOME": str(home), "CONTINUUM_REPO_ROOT": str(repo),
                "CONTINUUM_SMOKE_PYTHON": str(python),
                "CONTINUUM_SMOKE_BASE_ROOT": str(root / "retained"),
                "CONTINUUM_AMBIENT_SENTINEL": "must-not-leak",
                "ANSIBLE_FORCE_COLOR": "1",
            })
            if log_setting is not None:
                env["ANSIBLE_LOG_PATH"] = str(log) if log_setting else ""
            result = subprocess.run(
                ["sh", str(self.run_smoke_script), scenario], env=env, cwd=repo,
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout.splitlines()[0])
            self.assertIsNone(report["env"]["CONTINUUM_AMBIENT_SENTINEL"])
            self.assertIsNone(report["env"]["ANSIBLE_FORCE_COLOR"])
            self.assertFalse((repo / "INJECTED").exists())
            expected = {
                "infra_one_vm": ["--config", "configs/experiments/smoke/infra_one_vm.yaml"],
                "qemu_openfaas_image_parity": ["--suite", "qemu_openfaas_image_parity"],
            }
            self.assertEqual(report["argv"], expected[scenario] + [
                "--base-path", str(root / "retained" / scenario),
            ])
            return report["env"]["ANSIBLE_LOG_PATH"], str(log), log.read_text(encoding="utf-8")

    def test_run_smoke_suite_and_config_retain_real_ansible_log(self):
        for scenario in ("infra_one_vm", "qemu_openfaas_image_parity"):
            with self.subTest(scenario=scenario):
                actual, expected, content = self._run_ansible_evidence_fixture(scenario, True)
                self.assertEqual(actual, expected)
                self.assertIn("continuum-log-transport-marker", content)
                self.assertIn("PLAY RECAP", content)
                self.assertRegex(content, r"unreachable=0\s+failed=0")

    def test_run_smoke_suite_and_config_omit_unset_ansible_log(self):
        for scenario in ("infra_one_vm", "qemu_openfaas_image_parity"):
            with self.subTest(scenario=scenario):
                actual, _, content = self._run_ansible_evidence_fixture(scenario, None)
                self.assertIsNone(actual)
                self.assertEqual(content, "")

    def test_run_smoke_suite_and_config_omit_empty_ansible_log(self):
        for scenario in ("infra_one_vm", "qemu_openfaas_image_parity"):
            with self.subTest(scenario=scenario):
                actual, _, content = self._run_ansible_evidence_fixture(scenario, False)
                self.assertIsNone(actual)
                self.assertEqual(content, "")

    def test_setup_show_config_uses_invoking_user_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            result = self._run_setup_script("show-config", extra_env={"HOME": tempdir})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"BASE_ROOT={tempdir}/continuum_smoke", result.stdout)
        self.assertIn(f"PYTHON_BIN={tempdir}/venvs/continuum/bin/python3", result.stdout)
        self.assertIn(f"REPO_ROOT={self.repo_root}", result.stdout)
        self.assertIn(f"RUNNER_USER={pwd.getpwuid(os.geteuid()).pw_name}", result.stdout)

    def test_setup_show_config_honors_explicit_runtime_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            result = self._run_setup_script("show-config", extra_env={
                "HOME": tempdir,
                "CONTINUUM_SMOKE_BASE_ROOT": f"{tempdir}/retained",
                "CONTINUUM_SMOKE_PYTHON": f"{tempdir}/venv/bin/python3",
            })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"BASE_ROOT={tempdir}/retained", result.stdout)
        self.assertIn(f"PYTHON_BIN={tempdir}/venv/bin/python3", result.stdout)

    def test_setup_rejects_retired_privileged_commands(self):
        for command in ("install", "install-hostctl", "install-wrapper", "sync-repo",
                        "print-hostctl-script", "print-hostctl-command",
                        "relocate-smoke-root"):
            with self.subTest(command=command):
                result = self._run_setup_script(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Usage:", result.stderr)

    def test_setup_help_is_unprivileged(self):
        result = self._run_setup_script("help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("create-venv", result.stdout)
        self.assertIn("show-config", result.stdout)

    def test_setup_rejects_missing_or_noncanonical_home(self):
        with tempfile.TemporaryDirectory() as tempdir:
            for home in ("", "/", ".", f"{tempdir}/../{Path(tempdir).name}"):
                with self.subTest(home=home):
                    result = self._run_setup_script("show-config", extra_env={"HOME": home})
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("HOME", result.stderr)

    def test_setup_verify_rejects_missing_interpreter_without_mutation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            result = self._run_setup_script("verify", extra_env={"HOME": tempdir})
            self.assertEqual(list(Path(tempdir).iterdir()), [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python", result.stderr)

    def test_setup_create_venv_creates_only_requested_new_environment(self):
        with tempfile.TemporaryDirectory() as tempdir:
            venv = Path(tempdir) / "venvs/continuum"
            # Real venv creation; no network or dependency installation.
            result = self._run_setup_script("create-venv", extra_env={"HOME": tempdir})
            self.assertEqual(result.returncode, 0, result.stderr)
            probe = subprocess.run([str(venv / "bin/python3"), "-c",
                                    "import sys; print(sys.prefix)"],
                                   check=False, capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stdout.strip(), str(venv))
            sentinel = venv / "keep"
            sentinel.write_text("preserve", encoding="utf-8")
            repeat = self._run_setup_script("create-venv", extra_env={"HOME": tempdir})
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_run_smoke_rejects_missing_home_before_execution(self):
        result = self._run_smoke_script("list-suites", extra_env={"HOME": ""})
        self.assertEqual(result.returncode, 2)
        self.assertIn("HOME", result.stderr)

    def test_debug_run_command_playbook_accepts_debug_host_pattern_alias(self):
        playbook_content = (
            self.repo_root / "playbooks/debug/run_command.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'hosts: "{{ debug_hosts | default(debug_host_pattern | default(\'all\')) }}"',
            playbook_content,
        )

    def test_run_smoke_debug_playbook_uses_runner_ansible_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)
            fake_ansible = venv_bin / "ansible-playbook"
            fake_ansible.write_text(
                "#!/bin/sh\n"
                "printf 'ANSIBLE_CONFIG=%s\\n' \"$ANSIBLE_CONFIG\"\n"
                "printf 'ANSIBLE_LOCAL_TEMP=%s\\n' \"$ANSIBLE_LOCAL_TEMP\"\n"
                "printf 'ANSIBLE_REMOTE_TMP=%s\\n' \"$ANSIBLE_REMOTE_TMP\"\n"
                "printf 'ARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_ansible.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "debug-playbook",
                "benchmark_k8s_resume_software",
                "playbooks/resource_manager/k8s_cluster.yml",
                "--limit",
                "cloud_controller_continuum-smoke",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK": str(fake_ansible),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            expected_base = smoke_base_root / "benchmark_k8s_resume" / ".continuum"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"ANSIBLE_CONFIG={self.repo_root / 'ansible.cfg'}", result.stdout)
            self.assertIn(
                f"ANSIBLE_LOCAL_TEMP={expected_base / 'ansible' / 'tmp'}",
                result.stdout,
            )
            self.assertIn("ANSIBLE_REMOTE_TMP=~/.continuum-ansible-runner-home/tmp", result.stdout)
            self.assertIn(
                "ARGS:-i %s %s -vvv --limit cloud_controller_continuum-smoke"
                % (
                    expected_base / "inventory_vms",
                    self.repo_root / "playbooks/resource_manager/k8s_cluster.yml",
                ),
                result.stdout,
            )

    def test_run_smoke_debug_playbook_preserves_suite_scenario_base_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)
            fake_ansible = venv_bin / "ansible-playbook"
            fake_ansible.write_text(
                "#!/bin/sh\n"
                "printf 'ARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_ansible.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "debug-playbook",
                "qemu_kubeedge_software_parity",
                "playbooks/debug/run_command.yml",
                "-e",
                "debug_hosts=cloudcontroller",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK": str(fake_ansible),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            expected_base = smoke_base_root / "qemu_kubeedge_software_parity" / ".continuum"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "ARGS:-i %s %s -vvv -e debug_hosts=cloudcontroller"
                % (
                    expected_base / "inventory_vms",
                    self.repo_root / "playbooks/debug/run_command.yml",
                ),
                result.stdout,
            )

    def test_run_smoke_operational_regression_chains_smoke_matrix_and_benchmark(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "operational_regression",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("=== Running smoke scenario: phase_smoke_matrix ===", result.stdout)
            self.assertIn("=== Running smoke scenario: infra_one_vm ===", result.stdout)
            self.assertIn("=== Running smoke scenario: software_k8s_two_vm ===", result.stdout)
            self.assertIn("=== Running smoke scenario: network_netperf_two_vm ===", result.stdout)
            self.assertIn("=== Running smoke scenario: benchmark_k8s_resume ===", result.stdout)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --config "
                "configs/experiments/smoke/infra_one_vm.yaml --base-path",
                result.stdout,
            )
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --config "
                "configs/experiments/smoke/software_k8s_two_vm.yaml --base-path",
                result.stdout,
            )
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --config "
                "configs/experiments/smoke/network_netperf_two_vm.yaml --base-path",
                result.stdout,
            )
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite benchmark_smoke --base-path",
                result.stdout,
            )

    def test_run_smoke_storage_report_does_not_require_runner_python(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            smoke_base_root = temp_root / "smoke-base"
            scenario_root = smoke_base_root / "qemu_kubeedge_image_parity"
            scenario_root.mkdir(parents=True)
            (scenario_root / "artifact.txt").write_text("retained state\n", encoding="utf-8")

            result = self._run_smoke_script(
                "storage-report",
                extra_env={
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                    "CONTINUUM_SMOKE_PYTHON": str(temp_root / "missing-python"),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"SMOKE_BASE_ROOT={smoke_base_root}", result.stdout)
        self.assertIn("Retained scenario sizes:", result.stdout)
        self.assertIn("qemu_kubeedge_image_parity", result.stdout)
        self.assertIn("Total retained smoke state:", result.stdout)

    def test_run_smoke_latest_result_summary_prints_bounded_retained_json(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            smoke_base_root = temp_root / "smoke-base"
            results_dir = (
                smoke_base_root
                / "qemu_kube_kata_empty_startup_parity"
                / ".continuum"
                / "test_results"
            )
            results_dir.mkdir(parents=True)
            result_path = results_dir / "test_results_2026-07-09_13-47-58.json"
            result_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-09_13-47-58",
                        "total_tests": 1,
                        "passed": 1,
                        "failed": 0,
                        "artifacts_dir": str(results_dir / "test_results_2026-07-09_13-47-58"),
                        "results": [
                            {
                                "config_path": "configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml",
                                "success": True,
                                "exit_code": 0,
                                "success_reason": "exit_code=0",
                                "failure_class": "passed",
                                "execution_time": 12.3,
                                "timed_out": False,
                                "stdout_artifact": str(results_dir / "stdout.txt"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_smoke_script(
                "latest-result-summary",
                "qemu_kube_kata_empty_startup_parity",
                extra_env={
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                    "CONTINUUM_SMOKE_PYTHON": shutil.which("python3") or "/usr/bin/python3",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"LATEST_RESULT={result_path}", result.stdout)
        self.assertIn("PASSED=1", result.stdout)
        self.assertIn("FAILED=0", result.stdout)
        self.assertIn("RESULT_01_SUCCESS=True", result.stdout)
        self.assertIn("RESULT_01_EXIT_CODE=0", result.stdout)

    def test_run_smoke_rejects_malformed_scenario_names(self):
        for scenario in ("../evil", "/tmp/evil", "x;id"):
            with self.subTest(scenario=scenario):
                result = self._run_smoke_script(
                    scenario,
                    extra_env={"CONTINUUM_REPO_ROOT": str(self.repo_root)},
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("Invalid smoke scenario name", result.stderr)

    def test_run_smoke_prune_rejects_malformed_scenario_names(self):
        result = self._run_smoke_script(
            "prune-scenario",
            "../evil",
            "--yes-delete-retained-state",
            extra_env={"CONTINUUM_REPO_ROOT": str(self.repo_root)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid smoke scenario name", result.stderr)

    def test_run_smoke_debug_playbook_rejects_absolute_path(self):
        result = self._run_smoke_script(
            "debug-playbook",
            "benchmark_k8s_resume_software",
            "/tmp/evil.yml",
            extra_env={"CONTINUUM_REPO_ROOT": str(self.repo_root)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Debug playbook must be a repo-relative playbook path", result.stderr)

    def test_run_smoke_prime_registry_cache_runs_as_runner_mode(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'HOME=%s\\n' \"$HOME\"\n"
                "printf 'XDG_CACHE_HOME=%s\\n' \"$XDG_CACHE_HOME\"\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "prime-registry-cache",
                "--check-only",
                "--suite",
                "qemu_kubeedge_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"HOME={runner_home}", result.stdout)
        self.assertIn(f"XDG_CACHE_HOME={smoke_base_root / '.cache'}", result.stdout)
        self.assertIn(
            "PYARGS:scripts/test/prime_local_registry_cache.py --check-only --suite "
            "qemu_kubeedge_image_parity",
            result.stdout,
        )

    def test_run_smoke_check_prereqs_accepts_suite_arg(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'HOME=%s\\n' \"$HOME\"\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "check-prereqs",
                "--suite",
                "qemu_k8s_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"HOME={runner_home}", result.stdout)
        self.assertIn(
            "PYARGS:scripts/test/run_tests.py --suite qemu_k8s_image_parity --check-prereqs",
            result.stdout,
        )

    def test_run_smoke_check_prereqs_rejects_unsafe_suite_arg(self):
        result = self._run_smoke_script(
            "check-prereqs",
            "--suite",
            "../evil",
            extra_env={"CONTINUUM_REPO_ROOT": str(self.repo_root)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe suite name for check-prereqs", result.stderr)

    def test_run_smoke_release_artifact_audit_runs_as_runner_mode(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'HOME=%s\\n' \"$HOME\"\n"
                "printf 'AUDIT_ROOT=%s\\n' \"$CONTINUUM_RELEASE_AUDIT_ROOT\"\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"
            audit_root = temp_root / "live-repo"

            result = self._run_smoke_script(
                "release-artifact-audit",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_RELEASE_AUDIT_ROOT": str(audit_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"HOME={runner_home}", result.stdout)
        self.assertIn(f"AUDIT_ROOT={audit_root}", result.stdout)
        self.assertIn("PYARGS:scripts/test/check_release_evidence_artifacts.py", result.stdout)

    def test_run_smoke_prime_registry_cache_rejects_unsafe_args(self):
        result = self._run_smoke_script(
            "prime-registry-cache",
            "--suite",
            "../evil",
            extra_env={"CONTINUUM_REPO_ROOT": str(self.repo_root)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe suite name for prime-registry-cache", result.stderr)

    def test_run_smoke_prune_scenario_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            smoke_base_root = temp_root / "smoke-base"
            scenario_root = smoke_base_root / "qemu_kubeedge_image_parity"
            scenario_root.mkdir(parents=True)

            result = self._run_smoke_script(
                "prune-scenario",
                "qemu_kubeedge_image_parity",
                extra_env={
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                    "CONTINUUM_SMOKE_PYTHON": str(temp_root / "missing-python"),
                },
            )

            still_exists = scenario_root.exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(still_exists)
        self.assertIn("Refusing to delete retained state", result.stderr)
        self.assertIn("Would delete:", result.stderr)

    def test_run_smoke_prune_scenario_removes_only_selected_retained_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            smoke_base_root = temp_root / "smoke-base"
            target_root = smoke_base_root / "qemu_kubeedge_image_parity"
            other_root = smoke_base_root / "qemu_k8s_image_parity"
            target_root.mkdir(parents=True)
            other_root.mkdir(parents=True)
            (target_root / "artifact.txt").write_text("delete\n", encoding="utf-8")
            (other_root / "artifact.txt").write_text("keep\n", encoding="utf-8")

            result = self._run_smoke_script(
                "prune-scenario",
                "qemu_kubeedge_image_parity",
                "--yes-delete-retained-state",
                extra_env={
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                    "CONTINUUM_SMOKE_PYTHON": str(temp_root / "missing-python"),
                },
            )

            target_exists = target_root.exists()
            other_exists = other_root.exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target_exists)
        self.assertTrue(other_exists)
        self.assertIn("Deleted retained state for scenario: qemu_kubeedge_image_parity", result.stdout)

    def test_run_smoke_network_validation_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "network_validation",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite network_validation --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "network_validation"), result.stdout)

    def test_run_smoke_qemu_infra_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_infra_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_infra_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_infra_parity"), result.stdout)

    def test_run_smoke_qemu_k8s_nobench_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_k8s_nobench_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_k8s_nobench_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_k8s_nobench_parity"), result.stdout)

    def test_run_smoke_qemu_k8s_image_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_k8s_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_k8s_image_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_k8s_image_parity"), result.stdout)

    def test_run_smoke_qemu_kubeedge_software_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_kubeedge_software_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_kubeedge_software_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_kubeedge_software_parity"), result.stdout)

    def test_run_smoke_qemu_mist_software_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_mist_software_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_mist_software_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_mist_software_parity"), result.stdout)

    def test_run_smoke_qemu_kubeedge_image_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_kubeedge_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_kubeedge_image_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_kubeedge_image_parity"), result.stdout)

    def test_run_smoke_qemu_mist_image_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_mist_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_mist_image_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_mist_image_parity"), result.stdout)

    def test_run_smoke_qemu_endpoint_software_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_endpoint_software_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_endpoint_software_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_endpoint_software_parity"), result.stdout)

    def test_run_smoke_qemu_endpoint_image_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_endpoint_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_endpoint_image_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_endpoint_image_parity"), result.stdout)

    def test_run_smoke_qemu_openfaas_software_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_openfaas_software_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_openfaas_software_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_openfaas_software_parity"), result.stdout)

    def test_run_smoke_qemu_openfaas_image_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_openfaas_image_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_openfaas_image_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_openfaas_image_parity"), result.stdout)

    def test_run_smoke_qemu_openfaas_image_local_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_openfaas_image_local_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_openfaas_image_local_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_openfaas_image_local_parity"), result.stdout)

    def test_run_smoke_qemu_kubecontrol_empty_trace_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_kubecontrol_empty_trace_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_kubecontrol_empty_trace_parity --base-path",
                result.stdout,
            )
            self.assertIn(str(smoke_base_root / "qemu_kubecontrol_empty_trace_parity"), result.stdout)

    def test_run_smoke_qemu_kube_kata_empty_startup_parity_uses_suite_runner(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            runner_home = temp_root / "runner-home"
            runner_home.mkdir()
            venv_bin = temp_root / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'PYARGS:%s\\n' \"$*\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            smoke_base_root = temp_root / "smoke-base"

            result = self._run_smoke_script(
                "qemu_kube_kata_empty_startup_parity",
                extra_env={
                    "HOME": str(runner_home),
                    "CONTINUUM_REPO_ROOT": str(self.repo_root),
                    "CONTINUUM_SMOKE_PYTHON": str(fake_python),
                    "CONTINUUM_SMOKE_BASE_ROOT": str(smoke_base_root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "PYARGS:scripts/test/run_tests.py --suite qemu_kube_kata_empty_startup_parity --base-path",
                result.stdout,
            )
            self.assertIn(
                str(smoke_base_root / "qemu_kube_kata_empty_startup_parity"),
                result.stdout,
            )


class RetainedResultTailTests(unittest.TestCase):
    """Exercise the real inspector, including containment and byte output."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[3]
        self.base = self.root / "retained"
        self.scenario = "benchmark_k8s_resume"
        self.results = self.base / self.scenario / ".continuum/test_results"
        self.results.mkdir(parents=True)
        self.summary = self.results / "test_results_2026-10-27_18-00-00.json"
        self.entries = []
        self.contents = {}
        for index in (1, 2):
            entry = {}
            for kind in ("stdout", "stderr", "metadata"):
                path = self.results / f"entry-{index}-{kind}.txt"
                content = b"".join(
                    f"entry-{index}-{kind}-{line:03d}\n".encode() for line in range(150))
                path.write_bytes(content)
                entry[f"{kind}_artifact"] = str(path)
                self.contents[index, kind] = content
            self.entries.append(entry)
        self._save()

    def _save(self, payload=None):
        if payload is None:
            payload = {"results": self.entries}
        self.summary.write_text(json.dumps(payload), encoding="utf-8")

    def _tail(self, *args):
        env = os.environ.copy()
        env.update({"HOME": str(self.root), "CONTINUUM_SMOKE_BASE_ROOT": str(self.base),
                    "CONTINUUM_SMOKE_PYTHON": sys.executable})
        return subprocess.run(
            ["sh", str(self.repo / "scripts/test/run_smoke_host.sh"), "latest-result-tail", *args],
            check=False, capture_output=True, env=env, cwd=self.repo)

    def _content(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        headers = result.stdout.split(b"\n", 2)
        self.assertTrue(headers[0].startswith(b"LATEST_RESULT="), headers)
        self.assertTrue(headers[1].startswith(b"ARTIFACT="), headers)
        return headers[2]

    def test_default_is_first_stdout_final_120_lines(self):
        expected = b"".join(self.contents[1, "stdout"].splitlines(keepends=True)[-120:])
        self.assertEqual(self._content(self._tail(self.scenario)), expected)

    def test_every_kind_selects_requested_entry_and_full_output(self):
        for kind in ("stdout", "stderr", "metadata"):
            with self.subTest(kind=kind):
                self.assertEqual(self._content(self._tail(self.scenario, kind, "2", "--full")),
                                 self.contents[2, kind])

    def test_optional_positions_and_default_index(self):
        for args, index, kind in ((("--full",), 1, "stdout"),
                                  (("stderr", "--full"), 1, "stderr"),
                                  (("2", "--full"), 2, "stdout")):
            with self.subTest(args=args):
                self.assertEqual(self._content(self._tail(self.scenario, *args)),
                                 self.contents[index, kind])

    def test_full_and_tail_preserve_bytes_and_missing_final_newline(self):
        content = b"".join(b"line-%03d\xff\r\n" % n for n in range(150)) + b"last\xfe"
        Path(self.entries[0]["stdout_artifact"]).write_bytes(content)
        self.assertEqual(self._content(self._tail(self.scenario, "--full")), content)
        self.assertEqual(self._content(self._tail(self.scenario)),
                         b"".join(content.splitlines(keepends=True)[-120:]))

    def test_latest_summary_not_latest_artifact_or_first_filename(self):
        newer = self.results / "test_results_2026-01-01_00-00-00.json"
        newer.write_text(json.dumps({"results": [self.entries[1]]}), encoding="utf-8")
        os.utime(self.summary, (100, 100))
        os.utime(newer, (200, 200))
        result = self._tail(self.scenario, "--full")
        self.assertEqual(self._content(result), self.contents[2, "stdout"])
        self.assertIn(str(newer).encode(), result.stdout.split(b"\n", 1)[0])

    def test_only_selected_entry_is_used(self):
        self.entries[0]["stdout_artifact"] = "/etc/passwd"
        self._save()
        self.assertEqual(self._content(self._tail(self.scenario, "stdout", "2", "--full")),
                         self.contents[2, "stdout"])

    def test_rejects_invalid_indexes(self):
        for index in ("0", "-1", "1.5", "abc", "3", "9" * 5000):
            with self.subTest(index=index[:20]):
                result = self._tail(self.scenario, "stdout", index)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")

    def test_rejects_unknown_kind_order_extras_and_paths(self):
        for args in (("bogus",), ("/etc/passwd",), ("../stdout",), ("--full", "stdout"),
                     ("2", "stderr"), ("stdout", "--full", "2"),
                     ("stdout", "1", "--full", "extra"), ("stdout", "1", "--full", "--full")):
            with self.subTest(args=args):
                result = self._tail(self.scenario, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")

    def test_rejects_unknown_scenarios_and_aggregate_root(self):
        for scenario in ("unknown", "../evil", "/tmp/evil", "operational_regression"):
            with self.subTest(scenario=scenario):
                self.assertNotEqual(self._tail(scenario).returncode, 0)

    def test_every_retained_mapping_and_benchmark_alias_is_inspectable(self):
        scenarios = ("infra_one_vm", "software_k8s_two_vm", "network_netperf_two_vm",
                     "benchmark_k8s_resume", "network_validation", "qemu_infra_parity",
                     "qemu_k8s_nobench_parity", "qemu_k8s_image_parity",
                     "qemu_kubeedge_software_parity", "qemu_kubeedge_image_parity",
                     "qemu_mist_software_parity", "qemu_mist_image_parity",
                     "qemu_endpoint_software_parity", "qemu_endpoint_image_parity",
                     "qemu_openfaas_software_parity", "qemu_openfaas_image_parity",
                     "qemu_openfaas_image_local_parity", "qemu_kubecontrol_empty_parity",
                     "qemu_kubecontrol_empty_trace_parity", "qemu_kube_kata_empty_startup_parity",
                     "prereqs", "benchmark_k8s_resume_infra", "benchmark_k8s_resume_software",
                     "benchmark_k8s_resume_application")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                child = "benchmark_k8s_resume" if scenario.startswith("benchmark_k8s_resume") else scenario
                results = self.base / child / ".continuum/test_results"
                results.mkdir(parents=True, exist_ok=True)
                artifact = results / "stdout.txt"
                artifact.write_bytes(b"mapped\n")
                (results / self.summary.name).write_text(
                    json.dumps({"results": [{"stdout_artifact": str(artifact)}]}), encoding="utf-8")
                self.assertEqual(self._content(self._tail(scenario, "--full")), b"mapped\n")

    def test_rejects_missing_results_directory_summary_or_artifact(self):
        self.assertNotEqual(self._tail("infra_one_vm").returncode, 0)
        self.summary.unlink()
        self.assertNotEqual(self._tail(self.scenario).returncode, 0)
        self._save()
        Path(self.entries[0]["stdout_artifact"]).unlink()
        result = self._tail(self.scenario)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_rejects_malformed_payload_entry_or_artifact_field(self):
        for payload in ([], {"results": []}, {"results": {}}, {"results": [None]},
                        {"results": [{}]}, {"results": [{"stdout_artifact": 42}]}):
            with self.subTest(payload=payload):
                self._save(payload)
                result = self._tail(self.scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
        self.summary.write_text("{broken", encoding="utf-8")
        self.assertNotEqual(self._tail(self.scenario).returncode, 0)

    def test_rejects_arbitrary_and_parent_traversal_artifact_paths(self):
        outside = self.root / "secret.txt"
        outside.write_bytes(b"outside-secret")
        parent_secret = self.results.parent / "secret.txt"
        parent_secret.write_bytes(b"outside-secret")
        for path in (str(outside), str(self.results / ".." / "secret.txt"), "../secret.txt"):
            with self.subTest(path=path):
                self.entries[0]["stdout_artifact"] = path
                self._save()
                result = self._tail(self.scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"outside-secret", result.stdout)

    def test_rejects_symlink_escape(self):
        outside = self.root / "secret.txt"
        outside.write_bytes(b"outside-secret")
        artifact = Path(self.entries[0]["stdout_artifact"])
        artifact.unlink()
        artifact.symlink_to(outside)
        result = self._tail(self.scenario)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b"outside-secret", result.stdout)

    def test_rejects_unreadable_or_nonregular_artifact(self):
        artifact = Path(self.entries[0]["stdout_artifact"])
        artifact.unlink()
        artifact.mkdir()
        self.assertNotEqual(self._tail(self.scenario).returncode, 0)
        artifact.rmdir()
        artifact.write_bytes(b"private-content")
        if os.geteuid() != 0:
            artifact.chmod(0)
            result = self._tail(self.scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
