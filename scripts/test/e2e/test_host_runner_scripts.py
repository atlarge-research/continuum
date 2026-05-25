"""Regression tests for host smoke-runner helper scripts."""

# pylint: disable=missing-class-docstring,missing-function-docstring,line-too-long
# pylint: disable=too-many-public-methods

import os
import shutil
import subprocess
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

    def _write_verify_command_stubs(self, root: Path):
        fake_bin = root / "bin"
        fake_bin.mkdir()
        for command in ("sudo", "virsh"):
            path = fake_bin / command
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        return fake_bin

    def _copy_sync_probe_files(self, dedicated_repo: Path):
        probe_files = (
            "continuum.py",
            "infrastructure/ansible.py",
            "infrastructure/qemu/qemu.py",
            "input/configuration/runtime_module_loader.py",
            "scripts/test/run_smoke_host.sh",
            "scripts/test/setup_agent_host.sh",
            "scripts/test/prime_local_registry_cache.py",
            "scripts/test/test_config.json",
        )
        for rel_path in probe_files:
            source = self.repo_root / rel_path
            target = dedicated_repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def test_show_config_reports_present_sync_marker(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            dedicated_repo = temp_root / "dedicated"
            dedicated_repo.mkdir()
            marker = dedicated_repo / ".continuum-smoke-sync"
            marker.write_text(
                "SYNCED_FROM=/tmp/live\nSYNCED_AT_UTC=2026-04-22T21:00:00Z\n",
                encoding="utf-8",
            )

            result = self._run_setup_script(
                "show-config",
                extra_env={
                    "RUNNER_USER": "continuum-smoke",
                    "CALLER_USER": "matthijs",
                    "INSTALL_PATH": str(temp_root / "run-continuum-smoke"),
                    "LIVE_REPO_ROOT": str(temp_root / "live"),
                    "DEDICATED_REPO_ROOT": str(dedicated_repo),
                    "RUNNER_HOME": str(temp_root / "runner-home"),
                    "SMOKE_BASE_ROOT": str(temp_root / "runner-home/continuum_smoke"),
                    "VENV_ROOT": str(temp_root / "runner-home/venvs/continuum"),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"DEDICATED_SYNC_MARKER={marker}", result.stdout)
        self.assertIn("DEDICATED_SYNC_MARKER_STATUS=present", result.stdout)
        self.assertIn("SYNCED_FROM=/tmp/live", result.stdout)

    def test_show_config_reports_missing_sync_marker(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            dedicated_repo = temp_root / "dedicated"
            dedicated_repo.mkdir()

            result = self._run_setup_script(
                "show-config",
                extra_env={
                    "DEDICATED_REPO_ROOT": str(dedicated_repo),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DEDICATED_SYNC_MARKER_STATUS=missing", result.stdout)

    def test_print_hostctl_script_exposes_allowlisted_maintenance_interface(self):
        result = self._run_setup_script(
            "print-hostctl-script",
            extra_env={
                "HOSTCTL_PATH": "/usr/local/bin/continuum-hostctl",
                "INSTALL_PATH": "/usr/local/bin/run-continuum-smoke",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('HOSTCTL_PATH=/usr/local/bin/continuum-hostctl', result.stdout)
        self.assertIn('INSTALL_PATH=/usr/local/bin/run-continuum-smoke', result.stdout)
        self.assertIn(
            'SYNC_PROBE_FILES="continuum.py infrastructure/ansible.py '
            'infrastructure/qemu/qemu.py input/configuration/runtime_module_loader.py '
            'scripts/test/run_smoke_host.sh scripts/test/setup_agent_host.sh '
            'scripts/test/prime_local_registry_cache.py scripts/test/test_config.json"',
            result.stdout,
        )
        self.assertNotIn("SYNC_PROBE_FILES=continuum.py infrastructure/ansible.py", result.stdout)
        self.assertIn('sync-repo)', result.stdout)
        self.assertIn('install-wrapper)', result.stdout)
        self.assertIn('verify)', result.stdout)
        self.assertIn('prime-registry-cache)', result.stdout)
        self.assertIn('HOSTCTL_INTERFACE_VERSION=2026-05-24-prime-registry-cache', result.stdout)
        self.assertIn('verify_hostctl_interface()', result.stdout)
        self.assertIn('Installed maintenance helper is stale', result.stdout)
        self.assertIn('scripts/test/prime_local_registry_cache.py', result.stdout)
        self.assertIn('sudo -n \\$HOSTCTL_PATH sync-repo', result.stdout)
        self.assertNotIn('./scripts/test/setup_agent_host.sh sync-repo', result.stdout)

    def test_print_hostctl_command_formats_supported_installed_command(self):
        result = self._run_setup_script(
            "print-hostctl-command",
            "verify",
            extra_env={"HOSTCTL_PATH": "/usr/local/bin/continuum-hostctl"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "sudo -n /usr/local/bin/continuum-hostctl verify\n",
        )

    def test_print_hostctl_command_rejects_setup_only_command(self):
        result = self._run_setup_script(
            "print-hostctl-command",
            "install-hostctl",
            extra_env={"LIVE_REPO_ROOT": "/tmp/continuum-live"},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "Unsupported installed hostctl command for print-hostctl-command: install-hostctl",
            result.stderr,
        )
        self.assertIn(
            "Refresh the helper with: /tmp/continuum-live/scripts/test/setup_agent_host.sh "
            "install-hostctl",
            result.stderr,
        )
        self.assertEqual(result.stdout, "")

    def test_verify_reports_stale_installed_hostctl_interface_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            fake_bin = self._write_verify_command_stubs(temp_root)
            fake_hostctl = temp_root / "continuum-hostctl"
            fake_hostctl.write_text(
                "#!/bin/sh\n"
                "HOSTCTL_INTERFACE_VERSION=older-interface\n"
                "case \"$1\" in\n"
                "  prime-registry-cache) ;;\n"
                "esac\n",
                encoding="utf-8",
            )

            result = self._run_setup_script(
                "verify",
                extra_env={
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "HOSTCTL_PATH": str(fake_hostctl),
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Verifying maintenance helper interface", result.stdout)
        self.assertIn(
            "Installed maintenance helper is stale: interface older-interface, expected "
            "2026-05-24-prime-registry-cache",
            result.stderr,
        )

    def test_verify_reports_installed_hostctl_without_registry_cache_command(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            fake_bin = self._write_verify_command_stubs(temp_root)
            fake_hostctl = temp_root / "continuum-hostctl"
            fake_hostctl.write_text(
                "#!/bin/sh\n"
                "HOSTCTL_INTERFACE_VERSION=2026-05-24-prime-registry-cache\n"
                "case \"$1\" in\n"
                "  verify) ;;\n"
                "esac\n",
                encoding="utf-8",
            )

            result = self._run_setup_script(
                "verify",
                extra_env={
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "HOSTCTL_PATH": str(fake_hostctl),
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Verifying maintenance helper interface", result.stdout)
        self.assertIn(
            "Installed maintenance helper does not expose prime-registry-cache",
            result.stderr,
        )

    def test_verify_uses_noninteractive_sudo_for_root_owned_read_checks(self):
        if os.geteuid() == 0:
            self.skipTest("run_root_noninteractive is only exercised for non-root callers")

        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            sudo_log = temp_root / "sudo.log"
            fake_sudo = fake_bin / "sudo"
            fake_sudo.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$SUDO_LOG\"\n"
                "if [ \"$1\" = \"-n\" ]; then shift; else exit 77; fi\n"
                "if [ \"$1\" = \"-u\" ]; then\n"
                "  shift\n"
                "  shift\n"
                "  if [ \"$1\" = \"test\" ] && [ \"$2\" = \"-w\" ]; then exit 1; fi\n"
                "  exit 0\n"
                "fi\n"
                "exec \"$@\"\n",
                encoding="utf-8",
            )
            fake_sudo.chmod(0o755)
            fake_virsh = fake_bin / "virsh"
            fake_virsh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_virsh.chmod(0o755)

            dedicated_repo = temp_root / "dedicated"
            dedicated_repo.mkdir()
            self._copy_sync_probe_files(dedicated_repo)
            marker = dedicated_repo / ".continuum-smoke-sync"
            marker.write_text(
                f"SYNCED_FROM={self.repo_root}\n"
                "SYNCED_AT_UTC=2026-05-24T15:00:00Z\n",
                encoding="utf-8",
            )
            fake_wrapper = temp_root / "run-continuum-smoke"
            fake_wrapper.write_text(
                f"#!/bin/sh\nREPO_ROOT={dedicated_repo}\n"
                "# scripts/test/run_smoke_host.sh\n",
                encoding="utf-8",
            )
            fake_hostctl = temp_root / "continuum-hostctl"
            fake_hostctl.write_text(
                "#!/bin/sh\n"
                "HOSTCTL_INTERFACE_VERSION=2026-05-24-prime-registry-cache\n"
                "case \"$1\" in\n"
                "  prime-registry-cache) ;;\n"
                "esac\n",
                encoding="utf-8",
            )

            result = self._run_setup_script(
                "verify",
                extra_env={
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "SUDO_LOG": str(sudo_log),
                    "HOSTCTL_PATH": str(fake_hostctl),
                    "INSTALL_PATH": str(fake_wrapper),
                    "DEDICATED_REPO_ROOT": str(dedicated_repo),
                },
            )

            if sudo_log.exists():
                logged_sudo_calls = sudo_log.read_text(encoding="utf-8").splitlines()
            else:
                logged_sudo_calls = []
            marker_path = str(marker)
            dedicated_repo_path = str(dedicated_repo)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(logged_sudo_calls)
        self.assertTrue(
            all(call.startswith("-n ") for call in logged_sudo_calls),
            logged_sudo_calls,
        )
        self.assertIn(f"-n test -r {marker_path}", logged_sudo_calls)
        self.assertTrue(
            any(call.startswith(f"-n cksum {dedicated_repo_path}") for call in logged_sudo_calls)
        )

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
