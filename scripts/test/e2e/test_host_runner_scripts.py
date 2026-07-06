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

    def test_smoke_runner_isolation_contract_lists_local_openfaas_image_parity(self):
        docs = (self.repo_root / "docs/smoke_runner_isolation.md").read_text(
            encoding="utf-8"
        )
        wrapper_values = docs.split("## 6. Wrapper Contract", 1)[1].split(
            "The wrapper contract is:", 1
        )[0]

        self.assertIn("`qemu_openfaas_image_parity`", wrapper_values)
        self.assertIn("`qemu_openfaas_image_local_parity`", wrapper_values)
        self.assertIn("`qemu_kubecontrol_empty_parity`", wrapper_values)
        self.assertIn("`qemu_kubecontrol_empty_trace_parity`", wrapper_values)

    def test_smoke_runner_isolation_contract_documents_sudo_health(self):
        docs = (self.repo_root / "docs/smoke_runner_isolation.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`sudo -n true`", docs)
        self.assertIn("owned by `root:root` with the setuid bit set", docs)
        self.assertIn("repair the host sudo installation first", docs)

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
        self.assertIn('relocate-smoke-root)', result.stdout)
        self.assertIn('HOSTCTL_INTERFACE_VERSION=2026-07-06-kubecontrol-trace-cache', result.stdout)
        self.assertIn('umask 027', result.stdout)
        self.assertIn('PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', result.stdout)
        self.assertIn('validate_fixed_roots()', result.stdout)
        self.assertIn('validate_prime_registry_args()', result.stdout)
        self.assertIn('prime_registry_cache_as_root()', result.stdout)
        self.assertIn('docker pull "$source_ref"', result.stdout)
        self.assertIn('image_classification_publisher_serverless', result.stdout)
        self.assertIn(
            'qemu_kubecontrol_empty_parity|qemu_kubecontrol_empty_trace_parity',
            result.stdout,
        )
        self.assertIn('redplanet00/kube-apiserver:v1.27.0', result.stdout)
        self.assertIn('redplanet00/coredns:v1.10.1', result.stdout)
        self.assertIn('redplanet00/kubeedge-applications:empty', result.stdout)
        self.assertIn('validate_smoke_base_root()', result.stdout)
        self.assertIn('prepare_base_root_path()', result.stdout)
        self.assertIn('relocate_smoke_root()', result.stdout)
        self.assertIn('INSTALLED_WRAPPER_BASE_ROOT=', result.stdout)
        self.assertIn('CONTINUUM_RELEASE_AUDIT_ROOT=', result.stdout)
        self.assertIn('verify_hostctl_interface()', result.stdout)
        self.assertIn('Installed maintenance helper is stale', result.stdout)
        self.assertIn('scripts/test/prime_local_registry_cache.py', result.stdout)
        self.assertIn('runner_exec "$INSTALL_PATH" prime-registry-cache "$@"', result.stdout)
        self.assertNotIn('PYTHONPATH=. "$VENV_ROOT/bin/python3" scripts/test/prime_local_registry_cache.py', result.stdout)
        self.assertIn('rsync -rt --delete --delete-excluded --no-owner --no-group --no-perms', result.stdout)
        self.assertIn('--chmod=Du=rwx,Dg=rx,Do=,Fu=rwX,Fg=rX,Fo=,ugo-s', result.stdout)
        self.assertIn('find "$DEDICATED_REPO_ROOT" -type f -perm /111 -exec chmod 0750 {} +', result.stdout)
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

    def test_print_hostctl_command_formats_relocate_smoke_root(self):
        result = self._run_setup_script(
            "print-hostctl-command",
            "relocate-smoke-root",
            "/mnt/sdc/continuum_smoke",
            "--replace-source-with-symlink",
            extra_env={"HOSTCTL_PATH": "/usr/local/bin/continuum-hostctl"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "sudo -n /usr/local/bin/continuum-hostctl relocate-smoke-root "
            "/mnt/sdc/continuum_smoke --replace-source-with-symlink\n",
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
            "Hostctl replacement is a manual reviewed operator action.",
            result.stderr,
        )
        self.assertEqual(result.stdout, "")

    def test_setup_sync_repo_rejects_extra_target_argument(self):
        result = self._run_setup_script("sync-repo", "/tmp/evil")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertIn("sync-repo", result.stderr)

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
            "2026-07-06-kubecontrol-trace-cache",
            result.stderr,
        )
        self.assertIn(
            f"sh {self.repo_root}/scripts/test/setup_agent_host.sh print-hostctl-script",
            result.stderr,
        )
        self.assertIn("sudo -n", result.stderr)

    def test_verify_reports_installed_hostctl_without_registry_cache_command(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            fake_bin = self._write_verify_command_stubs(temp_root)
            fake_hostctl = temp_root / "continuum-hostctl"
            fake_hostctl.write_text(
                "#!/bin/sh\n"
                "HOSTCTL_INTERFACE_VERSION=2026-07-06-kubecontrol-trace-cache\n"
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
        self.assertIn(
            f"Reviewed helper source: sh {self.repo_root}/scripts/test/setup_agent_host.sh "
            "print-hostctl-script",
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
                "  if [ \"$1\" = \"test\" ] && [ \"$2\" = \"-w\" ]; then\n"
                "    case \"$3\" in\n"
                "      */dedicated|*/continuum.py) exit 1 ;;\n"
                "      *) exit 0 ;;\n"
                "    esac\n"
                "  fi\n"
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
            wrapper_base_root = temp_root / "runner-home" / "continuum_smoke"
            wrapper_base_root.mkdir(parents=True)
            fake_wrapper.write_text(
                f"#!/bin/sh\nREPO_ROOT={dedicated_repo}\n"
                f"BASE_ROOT={wrapper_base_root}\n"
                "# scripts/test/run_smoke_host.sh\n",
                encoding="utf-8",
            )
            fake_hostctl = temp_root / "continuum-hostctl"
            fake_hostctl.write_text(
                "#!/bin/sh\n"
                "HOSTCTL_INTERFACE_VERSION=2026-07-06-kubecontrol-trace-cache\n"
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

    def test_verify_fails_early_when_sudo_is_misconfigured(self):
        if os.geteuid() == 0:
            self.skipTest("sudo health check is only exercised for non-root callers")

        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            fake_sudo = fake_bin / "sudo"
            fake_sudo.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit set' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_sudo.chmod(0o755)
            fake_virsh = fake_bin / "virsh"
            fake_virsh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_virsh.chmod(0o755)

            result = self._run_setup_script(
                "verify",
                extra_env={
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "HOSTCTL_PATH": str(temp_root / "continuum-hostctl"),
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "Noninteractive sudo is unavailable or misconfigured",
            result.stderr,
        )
        self.assertIn("must be owned by uid 0", result.stderr)
        self.assertNotIn("Verifying maintenance helper interface", result.stdout)

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
