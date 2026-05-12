"""Regression tests for host smoke-runner helper scripts."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class HostRunnerScriptTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[2]
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
        self.assertIn('sync-repo)', result.stdout)
        self.assertIn('install-wrapper)', result.stdout)
        self.assertIn('verify)', result.stdout)
        self.assertIn('sudo -n \\$HOSTCTL_PATH sync-repo', result.stdout)
        self.assertNotIn('./scripts/test/setup_agent_host.sh sync-repo', result.stdout)

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
