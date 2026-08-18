"""Unit tests for runtime target resolution and addon compatibility."""

import argparse
import base64
import contextlib
import copy
import io
import json
import os
import pathlib
import shlex
import sys
import tempfile
import unittest
from unittest import mock

import continuum as continuum_module

from infrastructure.qemu import host_cache_helper
from infrastructure.qemu import qemu as qemu_module
from infrastructure import ansible as infrastructure_ansible
from infrastructure import infrastructure as infrastructure_module
from infrastructure import image_registry as image_registry_module
from infrastructure import machine as machine_module
from infrastructure import orchestration_schema
from infrastructure import state as infra_state
from infrastructure.machine import Machine
from input.configuration import (
    config_access,
    image_requirements,
    module_registry,
    runtime_module_loader,
    runtime_option_validation,
    runtime_phase_targets,
)
from resource_manager.endpoint import endpoint as endpoint_module


class RuntimeTargetResolutionTests(unittest.TestCase):
    def test_set_logging_uses_runtime_workspace_log_dir(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = argparse.Namespace(
                config={
                    "mode": "cloud",
                    "infrastructure": {"base_path": tempdir},
                    "domains": {"run": {"targets": ["infrastructure"]}},
                },
                verbose=False,
            )
            expected_dir = config_access.runtime_logs_dir(args.config)

            with (
                mock.patch.object(continuum_module.logging, "basicConfig"),
                mock.patch.object(continuum_module.logging, "FileHandler") as file_handler_mock,
                mock.patch.object(continuum_module.logging, "StreamHandler"),
            ):
                timestamp = continuum_module.set_logging(args)

            self.assertTrue(os.path.isdir(expected_dir))
            file_handler_mock.assert_called_once_with(
                os.path.join(expected_dir, "%s_infra_only.log" % (timestamp))
            )

    def test_log_vm_access_hints_logs_ssh_commands(self):
        config = {
            "ssh_key": "/tmp/test_key",
            "cloud_ssh": ["cloud0@192.168.0.10"],
            "edge_ssh": [],
            "endpoint_ssh": ["endpoint0@192.168.0.20"],
            "infrastructure": {"provider": "qemu"},
        }

        with mock.patch.object(continuum_module.logging, "info") as mock_info:
            continuum_module._log_vm_access_hints(config, header="debug header")

        self.assertEqual(
            mock_info.call_args_list[0].args,
            (
                "%s:\n\t%s\n",
                "debug header",
                "ssh cloud0@192.168.0.10 -i /tmp/test_key\n\tssh endpoint0@192.168.0.20 -i /tmp/test_key",
            ),
        )
        self.assertTrue(
            any(
                "virsh list --all" in call.args[0]
                for call in mock_info.call_args_list
            )
        )

    def test_log_vm_access_hints_skips_missing_ssh_targets(self):
        config = {
            "ssh_key": "/tmp/test_key",
            "cloud_ssh": [],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "infrastructure": {"provider": "gcp"},
        }

        with mock.patch.object(continuum_module.logging, "info") as mock_info:
            continuum_module._log_vm_access_hints(config)

        self.assertFalse(mock_info.called)

    def test_resolve_targets_infrastructure_only(self):
        config = {"domains": {"run": {"targets": ["infrastructure"]}}}
        self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), (True, False, False))

    def test_resolve_targets_software_only_without_infrastructure(self):
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {"run": {"targets": ["software"]}},
        }
        self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), (False, True, False))

    def test_resolve_targets_application_supported(self):
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {"run": {"targets": ["application"]}},
        }
        self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), (False, False, True))

    def test_resolve_targets_rejects_fresh_application_without_software(self):
        for targets in (
            ["infrastructure", "application"],
            ["application", "infrastructure"],
        ):
            with self.subTest(targets=targets):
                config = {"domains": {"run": {"targets": targets}}}
                with self.assertRaisesRegex(
                    ValueError,
                    r"domains\.run\.targets: fresh application execution requires the software phase",
                ):
                    runtime_phase_targets.resolve_runtime_targets(config)

    def test_resolve_targets_preserves_valid_fresh_and_resume_combinations(self):
        cases = (
            (["infrastructure"], (True, False, False)),
            (["infrastructure", "software"], (True, True, False)),
            (["infrastructure", "software", "application"], (True, True, True)),
            (["software"], (False, True, False)),
            (["software", "application"], (False, True, True)),
            (["application"], (False, False, True)),
        )
        for targets, expected in cases:
            with self.subTest(targets=targets):
                config = {
                    "infrastructure": {"provider": "qemu"},
                    "domains": {"run": {"targets": targets}},
                }
                self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), expected)

    def test_resolve_targets_allows_only_qemu_resume_but_accepts_fresh_runs(self):
        for provider_name in ("aws", "gcp", "baremetal"):
            with self.subTest(provider=provider_name, mode="resume"):
                config = {
                    "infrastructure": {"provider": provider_name},
                    "domains": {"run": {"targets": ["software"]}},
                }
                with self.assertRaisesRegex(
                    ValueError, "does not support run.targets that skip infrastructure"
                ):
                    runtime_phase_targets.resolve_runtime_targets(config)

            with self.subTest(provider=provider_name, mode="fresh"):
                config["domains"]["run"]["targets"] = ["infrastructure", "software"]
                self.assertEqual(
                    runtime_phase_targets.resolve_runtime_targets(config),
                    (True, True, False),
                )

        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {"run": {"targets": ["application"]}},
        }
        self.assertEqual(
            runtime_phase_targets.resolve_runtime_targets(config),
            (False, False, True),
        )

    def test_required_completed_phase_for_resume(self):
        self.assertIsNone(runtime_phase_targets.required_state_phase_for_targets(True, False, False))
        self.assertEqual(
            runtime_phase_targets.required_state_phase_for_targets(False, True, False),
            "infrastructure",
        )
        self.assertEqual(
            runtime_phase_targets.required_state_phase_for_targets(False, False, True),
            "software",
        )


class QemuInfrastructureResumeTopologyTests(unittest.TestCase):
    def test_infra_only_kubernetes_cloud_topology_preserves_controller_vm(self):
        config = {
            "mode": "cloud",
            "username": "continuum-smoke",
            "postfixIP_lower": 2,
            "postfixIP_upper": 252,
            "infrastructure": {
                "prefixIP": "192.168",
                "middleIP": 100,
                "middleIP_base": 90,
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }
        machine = Machine("local", True)

        qemu_module.set_ip_names(config, [machine], [{"cloud": 2, "edge": 0, "endpoint": 1}])

        self.assertEqual(machine.cloud_controller, 1)
        self.assertEqual(machine.cloud_controller_names, ["cloud_controller_continuum-smoke"])
        self.assertEqual(machine.cloud_controller_ips, ["192.168.100.2"])
        self.assertEqual(machine.cloud_names, ["cloud0_continuum-smoke"])
        self.assertEqual(machine.cloud_ips, ["192.168.100.3"])
        self.assertEqual(machine.endpoint_names, ["endpoint0_continuum-smoke"])
        self.assertEqual(machine.endpoint_ips, ["192.168.100.4"])

    def test_infra_only_mist_cloud_topology_does_not_create_controller_vm(self):
        config = {
            "mode": "cloud",
            "username": "continuum-smoke",
            "postfixIP_lower": 2,
            "postfixIP_upper": 252,
            "infrastructure": {
                "prefixIP": "192.168",
                "middleIP": 100,
                "middleIP_base": 90,
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
                "software": {
                    "modules": [
                        {
                            "id": "mist-main",
                            "type": "mist",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
        }
        machine = Machine("local", True)

        qemu_module.set_ip_names(config, [machine], [{"cloud": 2, "edge": 0, "endpoint": 0}])

        self.assertEqual(machine.cloud_controller, 0)
        self.assertEqual(machine.cloud_controller_names, [])
        self.assertEqual(machine.cloud_names, ["cloud0_continuum-smoke", "cloud1_continuum-smoke"])


class MachineProcessDiagnosticsTests(unittest.TestCase):
    def test_check_hardware_uses_local_lscpu_directly(self):
        machine = Machine("local", True)
        machine.process = mock.Mock(
            return_value=[
                (
                    ["CPU(s):              8", "Thread(s) per core:  2"],
                    [],
                )
            ]
        )

        machine.check_hardware({"infrastructure": {"provider": "qemu"}})

        machine.process.assert_called_once_with(
            {"infrastructure": {"provider": "qemu"}},
            ["lscpu"],
        )
        self.assertEqual(machine.cores, 4)

    def test_check_hardware_uses_managed_ssh_for_external_machine(self):
        machine = Machine("matthijs@node3", False)
        config = {
            "infrastructure": {"provider": "qemu"},
            "ssh_known_hosts_file": "/tmp/continuum-known-hosts",
        }
        machine.process = mock.Mock(
            return_value=[
                (
                    ["CPU(s):              32", "Thread(s) per core:  2"],
                    [],
                )
            ]
        )

        machine.check_hardware(config)

        machine.process.assert_called_once_with(
            config,
            ["lscpu"],
            ssh="matthijs@node3",
            ssh_key=False,
        )
        self.assertEqual(machine.cores, 16)

    def test_process_surfaces_silent_nonzero_return_code(self):
        machine = Machine("local", True)

        result = machine.process({}, ["false"])[0]

        self.assertEqual(result[0], [])
        self.assertEqual(len(result[1]), 1)
        self.assertIn("non-zero return code 1", result[1][0])
        self.assertIn("false", result[1][0])

    def test_process_appends_nonzero_return_code_to_warning_stderr(self):
        machine = Machine("local", True)

        result = machine.process({}, [["sh", "-c", "printf '[WARNING]: test\\n' >&2; exit 7"]])[0]

        self.assertEqual(result[0], [])
        self.assertEqual(len(result[1]), 2)
        self.assertEqual(result[1][0], "[WARNING]: test")
        self.assertIn("non-zero return code 7", result[1][1])


class ResumeSshReachabilityTests(unittest.TestCase):
    @staticmethod
    def _machines():
        local = Machine("local", True)
        local.cloud_controller = 1
        local.cloud_controller_names = ["controller0"]
        local.cloud_controller_ips = ["192.0.2.10"]
        local.clouds = 1
        local.cloud_names = ["cloud0"]
        local.cloud_ips = ["192.0.2.11"]
        external = Machine("owner@example.invalid", False)
        external.endpoints = 1
        external.endpoint_names = ["endpoint0"]
        external.endpoint_ips = ["192.0.2.12"]
        return [local, external]

    @staticmethod
    def _config(cloud_nodes=2, edge_nodes=0, endpoint_nodes=1):
        return {
            "infrastructure": {
                "cloud_nodes": cloud_nodes,
                "edge_nodes": edge_nodes,
                "endpoint_nodes": endpoint_nodes,
            }
        }

    def test_valid_multi_category_topology_requires_ordered_exact_markers(self):
        machines = self._machines()
        config = self._config()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(
            return_value=[([marker], []), ([marker], []), ([marker], [])]
        )

        targets = machine_module.validate_resume_ssh_reachability(config, machines)

        self.assertEqual(
            targets,
            [
                "controller0@192.0.2.10",
                "cloud0@192.0.2.11",
                "endpoint0@192.0.2.12",
            ],
        )
        machines[0].process.assert_called_once_with(
            config,
            ["printf", marker],
            ssh=targets,
        )

    def test_empty_stdout_is_not_success(self):
        machines = self._machines()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(
            return_value=[([], []), ([marker], []), ([marker], [])]
        )

        with self.assertRaisesRegex(RuntimeError, "controller0@192.0.2.10.*missing exact marker"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

    def test_missing_result_is_rejected(self):
        machines = self._machines()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(return_value=[([marker], []), ([marker], [])])

        with self.assertRaisesRegex(RuntimeError, "endpoint0@192.0.2.12.*missing result"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

    def test_marker_plus_synthetic_nonzero_marker_is_rejected(self):
        machines = self._machines()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(
            return_value=[
                ([marker], []),
                ([marker], ["Command exited with non-zero return code 7: printf"]),
                ([marker], []),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "cloud0@192.0.2.11.*command failed"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

    def test_each_target_must_return_its_own_marker(self):
        machines = self._machines()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(
            return_value=[([marker], []), ([marker], []), (["wrong-target-marker"], [])]
        )

        with self.assertRaisesRegex(RuntimeError, "endpoint0@192.0.2.12.*missing exact marker"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

    def test_unexpected_output_is_not_success(self):
        machines = self._machines()
        marker = machine_module._RESUME_SSH_MARKER
        machines[0].process = mock.Mock(
            return_value=[
                ([marker, "unexpected"], []),
                ([marker], []),
                ([marker], []),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "controller0@192.0.2.10.*missing exact marker"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

    def test_process_exception_is_rejected_without_an_outer_retry(self):
        machines = self._machines()
        machines[0].process = mock.Mock(side_effect=OSError("transport unavailable"))

        with self.assertRaisesRegex(RuntimeError, "SSH preflight raised.*transport unavailable"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

        machines[0].process.assert_called_once()

    def test_transient_machine_process_failure_retries_then_accepts_marker(self):
        machine = Machine("local", True)
        machine.clouds = 1
        machine.cloud_names = ["cloud0"]
        machine.cloud_ips = ["192.0.2.11"]
        marker = machine_module._RESUME_SSH_MARKER
        transient_process = mock.Mock(returncode=255)
        transient_process.communicate.return_value = (b"", b"Connection refused\n")
        successful_process = mock.Mock(returncode=0)
        successful_process.communicate.return_value = (marker.encode("utf-8"), b"")
        config = {
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
            },
            "ssh_key": "/tmp/test-key",
            "ssh_known_hosts_file": "/tmp/test-known-hosts",
        }

        with mock.patch.object(
            machine_module.subprocess,
            "Popen",
            side_effect=[transient_process, successful_process],
        ) as popen_mock, mock.patch.object(
            machine_module.time, "sleep"
        ) as sleep_mock, mock.patch.object(
            machine_module, "_backoff_seconds", return_value=0.0
        ):
            targets = machine_module.validate_resume_ssh_reachability(config, [machine])

        self.assertEqual(targets, ["cloud0@192.0.2.11"])
        self.assertEqual(popen_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.0)

    def test_duplicate_guest_name_with_different_ips_is_rejected_before_probe(self):
        machines = self._machines()
        machines[1].endpoint_names = ["cloud0"]
        machines[0].process = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "duplicate guest name cloud0"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

        machines[0].process.assert_not_called()

    def test_duplicate_complete_guest_pair_is_rejected_before_probe(self):
        machines = self._machines()
        machines[1].endpoint_names = ["cloud0"]
        machines[1].endpoint_ips = ["192.0.2.11"]
        machines[0].process = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "duplicate managed guest pair cloud0@192.0.2.11"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

        machines[0].process.assert_not_called()

    def test_duplicate_guest_ip_with_different_names_is_rejected_before_probe(self):
        machines = self._machines()
        machines[1].endpoint_ips = ["192.0.2.11"]
        machines[0].process = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "duplicate guest IP 192.0.2.11"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

        machines[0].process.assert_not_called()

    def test_category_name_ip_length_mismatch_is_rejected_before_probe(self):
        machines = self._machines()
        machines[0].cloud_ips = []
        machines[0].process = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "cloud topology length mismatch.*1 names, 0 IPs"):
            machine_module.validate_resume_ssh_reachability(self._config(), machines)

        machines[0].process.assert_not_called()

    def test_recorded_category_count_mismatch_is_rejected_before_probe(self):
        for recorded_count in (0, 2):
            with self.subTest(recorded_count=recorded_count):
                machines = self._machines()
                machines[0].clouds = recorded_count
                machines[0].process = mock.Mock()

                with self.assertRaisesRegex(RuntimeError, "cloud count mismatch for owner 0"):
                    machine_module.validate_resume_ssh_reachability(self._config(), machines)

                machines[0].process.assert_not_called()

    def test_configured_category_count_mismatch_is_rejected_before_probe(self):
        for configured_count in (1, 3):
            with self.subTest(configured_count=configured_count):
                machines = self._machines()
                machines[0].process = mock.Mock()

                with self.assertRaisesRegex(RuntimeError, "cloud_nodes count mismatch"):
                    machine_module.validate_resume_ssh_reachability(
                        self._config(cloud_nodes=configured_count),
                        machines,
                    )

                machines[0].process.assert_not_called()


class MachineProcessCommandShapeTests(unittest.TestCase):
    @staticmethod
    def _echo_argv(tokens):
        return [
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps(sys.argv[1:]))",
            *tokens,
        ]

    def test_flat_argv_preserves_ansible_tokens_with_whitespace(self):
        machine = Machine("local", True)
        tokens = [
            "ansible-playbook",
            "-i",
            "/tmp/inventory path",
            "site.yml",
            "--extra-vars",
            '{"label": "batch one"}',
            "",
            '"quoted token"',
        ]

        output, error = machine.process({}, self._echo_argv(tokens))[0]

        self.assertEqual(error, [])
        self.assertEqual(json.loads(output[0]), tokens)

    def test_flat_argv_does_not_interpret_shell_syntax(self):
        machine = Machine("local", True)
        with tempfile.TemporaryDirectory() as tempdir:
            sentinel = pathlib.Path(tempdir) / "shell-interpreted"
            token = "$(touch %s)" % (sentinel,)

            output, error = machine.process({}, self._echo_argv([token]))[0]

            self.assertEqual(error, [])
            self.assertEqual(json.loads(output[0]), [token])
            self.assertFalse(sentinel.exists())

    def test_nested_argv_commands_return_separate_ordered_results(self):
        machine = Machine("local", True)
        commands = [
            [sys.executable, "-c", "print('first')"],
            [sys.executable, "-c", "print('second')"],
        ]

        results = machine.process({}, commands)

        self.assertEqual(results, [[['first'], []], [['second'], []]])

    def test_string_shell_and_empty_command_compatibility(self):
        machine = Machine("local", True)

        self.assertEqual(machine.process({}, None), [])
        self.assertEqual(machine.process({}, []), [])
        self.assertEqual(
            machine.process({}, "printf string-command"),
            [[['string-command'], []]],
        )
        self.assertEqual(
            machine.process({}, "printf left' ' && printf right", shell=True),
            [[['left right'], []]],
        )
        self.assertEqual(
            machine.process({}, ["printf first", "printf second"], shell=True),
            [[['first'], []], [['second'], []]],
        )


class EndpointDockerStartDiagnosticsTests(unittest.TestCase):
    class _FakeMachine:
        def __init__(self, results):
            self.results = results
            self.calls = []

        def process(self, config, commands, ssh=None):
            self.calls.append({"config": config, "commands": commands, "ssh": ssh})
            return self.results

    def test_docker_container_status_command_uses_remote_shell_quotes(self):
        command = endpoint_module._DOCKER_CONTAINER_STATUS_COMMAND

        self.assertEqual(
            command,
            'docker container ls -a --format "{{.ID}}: {{.Status}} {{.Names}}"',
        )
        self.assertNotIn("\\\"", command)

    def test_docker_start_allows_pull_progress_with_container_id(self):
        stderr = [
            "Unable to find image '192.168.1.104:5000/image:latest' locally\n"
            "latest: Pulling from image\n"
            "Digest: sha256:abc\n"
            "Status: Downloaded newer image for 192.168.1.104:5000/image:latest\n"
            "WARNING: Your kernel does not support swap limit capabilities or the "
            "cgroup is not mounted. Memory limited without swap."
        ]

        self.assertFalse(endpoint_module._docker_start_stderr_is_fatal(["abc123"], stderr))

    def test_docker_start_treats_daemon_error_as_fatal_even_with_output(self):
        stderr = ["docker: Error response from daemon: pull access denied for image."]

        self.assertTrue(endpoint_module._docker_start_stderr_is_fatal(["abc123"], stderr))

    def test_docker_start_requires_container_id_before_accepting_stderr(self):
        stderr = ["WARNING: Your kernel does not support swap limit capabilities."]

        self.assertTrue(endpoint_module._docker_start_stderr_is_fatal([], stderr))

    def test_remove_existing_endpoint_containers_ignores_absent_container(self):
        machine = self._FakeMachine(
            [([], ["Error: No such container: cloud0_endpoint0"])]
        )

        endpoint_module._remove_existing_endpoint_containers(
            {},
            [machine],
            ["cloud0_endpoint0"],
            sshs=["endpoint0@192.168.100.4"],
        )

        self.assertEqual(
            machine.calls[0]["commands"],
            [["docker", "container", "rm", "--force", "cloud0_endpoint0"]],
        )
        self.assertEqual(machine.calls[0]["ssh"], ["endpoint0@192.168.100.4"])

    def test_remove_existing_endpoint_containers_fails_on_real_error(self):
        machine = self._FakeMachine([([], ["permission denied"])])

        with self.assertRaises(SystemExit):
            endpoint_module._remove_existing_endpoint_containers(
                {},
                [machine],
                ["cloud0_endpoint0"],
                sshs=["endpoint0@192.168.100.4"],
            )


class AnsibleCheckOutputDiagnosticsTests(unittest.TestCase):
    def test_check_output_accepts_wrapped_ansible_warning_blocks(self):
        stderr_lines = [
            "[WARNING]: Module remote_tmp /root/.continuum-ansible/tmp did",
            "not exist and was created with a mode of 0700, this may cause issues",
            "when running as another user.",
            "[WARNING]: Could not match supplied host pattern, ignoring: edges",
        ]

        infrastructure_ansible.check_output((["PLAY RECAP"], stderr_lines))

    def test_check_output_logs_stdout_context_for_synthetic_nonzero_failure(self):
        stdout_lines = [
            "PLAY [Example]",
            "TASK [Launch jobs]",
            "fatal: [node]: FAILED! => msg=boom",
        ]
        stderr_lines = [
            "Command exited with non-zero return code 2: ansible-playbook -i inventory example.yml"
        ]

        with (
            self.assertRaises(SystemExit),
            mock.patch.object(infrastructure_ansible.logging, "error") as mock_error,
        ):
            infrastructure_ansible.check_output((stdout_lines, stderr_lines))

        logged = mock_error.call_args.args[0]
        self.assertIn("Ansible command failed.", logged)
        self.assertIn("stdout:", logged)
        self.assertIn("TASK [Launch jobs]", logged)
        self.assertIn("fatal: [node]: FAILED! => msg=boom", logged)
        self.assertIn("stderr:", logged)
        self.assertIn("non-zero return code 2", logged)

    def test_check_output_logs_failed_playbook_output(self):
        stdout_lines = [
            "PLAY [Example]",
            "TASK [Launch jobs]",
            "fatal: [node]: FAILED! => msg=boom",
        ]

        with (
            self.assertRaises(SystemExit),
            mock.patch.object(infrastructure_ansible.logging, "error") as mock_error,
        ):
            infrastructure_ansible.check_output((stdout_lines, []))

        logged = mock_error.call_args.args[0]
        self.assertIn("Ansible playbook reported FAILED!", logged)
        self.assertIn("TASK [Launch jobs]", logged)
        self.assertIn("fatal: [node]: FAILED! => msg=boom", logged)


class ContinuumMainApplicationPhaseTests(unittest.TestCase):
    class _FakeHostIpSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, _target):
            return None

        def getsockname(self):
            return ("192.168.1.104", 5000)

    class _FakeSocketModule:
        AF_INET = runtime_module_loader.socket_lib.AF_INET
        SOCK_DGRAM = runtime_module_loader.socket_lib.SOCK_DGRAM
        gaierror = runtime_module_loader.socket_lib.gaierror

        def __init__(self):
            self.socket_calls = 0

        def socket(self, *_args, **_kwargs):
            self.socket_calls += 1
            return ContinuumMainApplicationPhaseTests._FakeHostIpSocket()

    def _config(self, targets):
        return {
            "mode": "cloud",
            "module": {
                "application": object(),
            },
            "domains": {
                "run": {"targets": targets},
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
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {
                                "frequency": 5,
                                "duration": 300,
                            },
                        }
                    ]
                },
            },
            "infrastructure": {
                "provider": "qemu",
                "delete": False,
                "base_path": "/tmp/continuum-smoke",
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 1,
            },
        }

    def test_main_rejects_fresh_application_without_software_before_side_effects(self):
        config = self._config(["infrastructure", "application"])
        args = argparse.Namespace(config=config)

        with (
            mock.patch.object(
                continuum_module.yaml_parser, "write_experiment_lock"
            ) as mock_write_lock,
            mock.patch.object(
                continuum_module.infrastructure, "start"
            ) as mock_infrastructure_start,
            mock.patch.object(
                continuum_module.infra_state, "load_resume_state"
            ) as mock_load_resume_state,
            mock.patch.object(
                continuum_module.machine_utils, "validate_resume_ssh_reachability"
            ) as mock_resume_preflight,
            mock.patch.object(
                continuum_module.ansible, "AnsibleRunner"
            ) as mock_ansible_runner,
            mock.patch.object(
                continuum_module.resource_manager, "start"
            ) as mock_resource_manager_start,
            mock.patch.object(
                continuum_module.application, "start"
            ) as mock_application_start,
            mock.patch.object(continuum_module.infra_state, "save_state") as mock_save_state,
        ):
            with self.assertRaises(SystemExit) as exc:
                continuum_module.main(args)

        self.assertEqual(exc.exception.code, 1)
        mock_write_lock.assert_not_called()
        mock_infrastructure_start.assert_not_called()
        mock_load_resume_state.assert_not_called()
        mock_resume_preflight.assert_not_called()
        mock_ansible_runner.assert_not_called()
        mock_resource_manager_start.assert_not_called()
        mock_application_start.assert_not_called()
        mock_save_state.assert_not_called()

    def test_main_rejects_cloud_resume_before_lock_or_state_access(self):
        for provider_name in ("aws", "gcp"):
            with self.subTest(provider=provider_name):
                config = self._config(["software"])
                config["infrastructure"]["provider"] = provider_name
                args = argparse.Namespace(config=config)
                with mock.patch.object(
                    continuum_module.yaml_parser, "write_experiment_lock"
                ) as write_lock, mock.patch.object(
                    continuum_module.infra_state, "load_resume_state"
                ) as load_state, mock.patch.object(
                    continuum_module.image_registry, "prepare_runtime_images"
                ) as prepare_images:
                    with self.assertRaises(SystemExit) as exc:
                        continuum_module.main(args)

                self.assertEqual(exc.exception.code, 1)
                write_lock.assert_not_called()
                load_state.assert_not_called()
                prepare_images.assert_not_called()

    def test_main_application_only_resumes_software_state_and_saves_application_phase(self):
        config = self._config(["application"])
        args = argparse.Namespace(config=config)
        machines = [mock.Mock()]
        runner = mock.Mock()

        with mock.patch.object(continuum_module.infrastructure, "start") as mock_infra_start, mock.patch.object(
            continuum_module.infra_state,
            "load_resume_state",
            return_value=({"phase_completed": "software"}, machines),
        ) as mock_load_resume_state, mock.patch.object(
            continuum_module.machine_utils,
            "validate_resume_ssh_reachability",
            return_value=["cloud0@192.0.2.10"],
        ) as mock_preflight, mock.patch.object(
            continuum_module.image_registry, "prepare_runtime_images"
        ) as mock_prepare_images, mock.patch.object(
            continuum_module.ansible, "AnsibleRunner", return_value=runner
        ) as mock_ansible_runner, mock.patch.object(
            continuum_module.yaml_parser,
            "write_experiment_lock",
            return_value="/tmp/continuum-smoke/.continuum/experiment_lock.yaml",
        ), mock.patch.object(
            continuum_module.resource_manager, "start"
        ) as mock_resource_manager_start, mock.patch.object(
            continuum_module.application, "start"
        ) as mock_application_start, mock.patch.object(
            continuum_module.infra_state,
            "save_state",
            return_value="/tmp/continuum-smoke/.continuum/state.json",
        ) as mock_save_state, mock.patch.object(
            continuum_module, "_log_vm_access_hints"
        ):
            continuum_module.main(args)

        mock_infra_start.assert_not_called()
        mock_load_resume_state.assert_called_once_with(config, "software")
        mock_preflight.assert_called_once_with(config, machines)
        mock_prepare_images.assert_called_once_with(config, machines)
        mock_ansible_runner.assert_called_once_with(config, machines)
        mock_resource_manager_start.assert_not_called()
        mock_application_start.assert_called_once_with(runner)
        mock_save_state.assert_called_once_with(config, "application", machines)

    def test_infrastructure_target_does_not_discover_or_preflight_existing_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(["infrastructure"])
            config["infrastructure"]["base_path"] = tempdir
            args = argparse.Namespace(config=config)
            machines = [mock.Mock()]
            state_path = pathlib.Path(infra_state.state_file_path(config))
            state_path.parent.mkdir(parents=True)
            state_path.write_text("last-known-state", encoding="utf-8")

            with mock.patch.object(
                continuum_module.infrastructure, "start", return_value=machines
            ), mock.patch.object(
                continuum_module.infra_state, "load_resume_state"
            ) as mock_load, mock.patch.object(
                continuum_module.machine_utils, "validate_resume_ssh_reachability"
            ) as mock_preflight, mock.patch.object(
                continuum_module.infra_state,
                "save_state",
                return_value=str(state_path),
            ), mock.patch.object(
                continuum_module.ansible, "AnsibleRunner", return_value=mock.Mock()
            ), mock.patch.object(
                continuum_module.yaml_parser, "write_experiment_lock", return_value=None
            ), mock.patch.object(continuum_module, "_log_vm_access_hints"):
                continuum_module.main(args)

            mock_load.assert_not_called()
            mock_preflight.assert_not_called()

    def test_main_software_and_application_resume_from_infrastructure_state(self):
        config = self._config(["software", "application"])
        args = argparse.Namespace(config=config)
        machines = [mock.Mock()]
        runner = mock.Mock()

        with mock.patch.object(continuum_module.infrastructure, "start") as mock_infra_start, mock.patch.object(
            continuum_module.infra_state,
            "load_resume_state",
            return_value=({"phase_completed": "infrastructure"}, machines),
        ) as mock_load_resume_state, mock.patch.object(
            continuum_module.machine_utils,
            "validate_resume_ssh_reachability",
            return_value=["cloud0@192.0.2.10"],
        ) as mock_preflight, mock.patch.object(
            continuum_module.image_registry, "prepare_runtime_images"
        ) as mock_prepare_images, mock.patch.object(
            continuum_module.ansible, "AnsibleRunner", return_value=runner
        ) as mock_ansible_runner, mock.patch.object(
            continuum_module.yaml_parser,
            "write_experiment_lock",
            return_value="/tmp/continuum-smoke/.continuum/experiment_lock.yaml",
        ), mock.patch.object(
            continuum_module.resource_manager, "start"
        ) as mock_resource_manager_start, mock.patch.object(
            continuum_module.application, "start"
        ) as mock_application_start, mock.patch.object(
            continuum_module.infra_state,
            "save_state",
            return_value="/tmp/continuum-smoke/.continuum/state.json",
        ) as mock_save_state, mock.patch.object(
            continuum_module, "_log_vm_access_hints"
        ):
            continuum_module.main(args)

        mock_infra_start.assert_not_called()
        mock_load_resume_state.assert_called_once_with(config, "infrastructure")
        mock_preflight.assert_called_once_with(config, machines)
        mock_prepare_images.assert_called_once_with(config, machines)
        mock_ansible_runner.assert_called_once_with(config, machines)
        mock_resource_manager_start.assert_called_once_with(runner)
        mock_application_start.assert_called_once_with(runner)
        self.assertEqual(
            mock_save_state.call_args_list,
            [
                mock.call(config, "software", machines),
                mock.call(config, "application", machines),
            ],
        )

    def test_main_application_target_calls_application_start_even_without_module(self):
        config = self._config(["application"])
        config["module"]["application"] = False
        args = argparse.Namespace(config=config)
        machines = [mock.Mock()]
        runner = mock.Mock()

        with mock.patch.object(continuum_module.infrastructure, "start"), mock.patch.object(
            continuum_module.infra_state,
            "load_resume_state",
            return_value=({"phase_completed": "software"}, machines),
        ), mock.patch.object(
            continuum_module.machine_utils,
            "validate_resume_ssh_reachability",
            return_value=["cloud0@192.0.2.10"],
        ), mock.patch.object(
            continuum_module.image_registry, "prepare_runtime_images"
        ), mock.patch.object(
            continuum_module.ansible, "AnsibleRunner", return_value=runner
        ), mock.patch.object(
            continuum_module.yaml_parser,
            "write_experiment_lock",
            return_value="/tmp/continuum-smoke/.continuum/experiment_lock.yaml",
        ), mock.patch.object(
            continuum_module.resource_manager, "start"
        ) as mock_resource_manager_start, mock.patch.object(
            continuum_module.application,
            "start",
            side_effect=SystemExit(1),
        ) as mock_application_start, mock.patch.object(
            continuum_module.infra_state,
            "save_state",
        ) as mock_save_state, mock.patch.object(
            continuum_module, "_log_vm_access_hints"
        ):
            with self.assertRaises(SystemExit):
                continuum_module.main(args)

        mock_resource_manager_start.assert_not_called()
        mock_application_start.assert_called_once_with(runner)
        mock_save_state.assert_not_called()

    def test_delete_on_exit_preserves_state_snapshot_during_successful_teardown(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(["infrastructure"])
            config["infrastructure"]["base_path"] = tempdir
            config["infrastructure"]["delete"] = True
            args = argparse.Namespace(config=config)
            machines = [mock.Mock()]
            state_path = pathlib.Path(infra_state.state_file_path(config))

            def save_current_state(_config, _phase, _machines):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text("current-state", encoding="utf-8")
                return str(state_path)

            def assert_state_is_persistent(_config, _machines):
                self.assertEqual(state_path.read_text(encoding="utf-8"), "current-state")

            with mock.patch.object(
                continuum_module.infrastructure, "start", return_value=machines
            ), mock.patch.object(
                continuum_module.infra_state, "save_state", side_effect=save_current_state
            ), mock.patch.object(
                continuum_module.infrastructure,
                "delete_vms",
                side_effect=assert_state_is_persistent,
            ) as mock_delete, mock.patch.object(
                continuum_module.ansible, "AnsibleRunner", return_value=mock.Mock()
            ), mock.patch.object(
                continuum_module.yaml_parser, "write_experiment_lock", return_value=None
            ), mock.patch.object(continuum_module, "_log_vm_access_hints"):
                continuum_module.main(args)

            mock_delete.assert_called_once_with(config, machines)
            self.assertEqual(state_path.read_text(encoding="utf-8"), "current-state")

    def test_delete_on_exit_provider_failure_preserves_state_and_exception(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(["infrastructure"])
            config["infrastructure"]["base_path"] = tempdir
            config["infrastructure"]["delete"] = True
            args = argparse.Namespace(config=config)
            machines = [mock.Mock()]
            state_path = pathlib.Path(infra_state.state_file_path(config))

            def save_current_state(_config, _phase, _machines):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text("current-state", encoding="utf-8")
                return str(state_path)

            provider_error = RuntimeError("provider teardown failed")
            with mock.patch.object(
                continuum_module.infrastructure, "start", return_value=machines
            ), mock.patch.object(
                continuum_module.infra_state, "save_state", side_effect=save_current_state
            ), mock.patch.object(
                continuum_module.infrastructure, "delete_vms", side_effect=provider_error
            ), mock.patch.object(
                continuum_module.ansible, "AnsibleRunner", return_value=mock.Mock()
            ), mock.patch.object(
                continuum_module.yaml_parser, "write_experiment_lock", return_value=None
            ), mock.patch.object(continuum_module, "_log_vm_access_hints"):
                with self.assertRaises(RuntimeError) as exc:
                    continuum_module.main(args)

            self.assertIs(exc.exception, provider_error)
            self.assertEqual(state_path.read_text(encoding="utf-8"), "current-state")

    def test_resume_preflight_failure_aborts_before_downstream_work_or_state_save(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(["software", "application"])
            config["infrastructure"]["base_path"] = tempdir
            args = argparse.Namespace(config=config)
            machines = [mock.Mock()]
            state_path = pathlib.Path(infra_state.state_file_path(config))
            state_path.parent.mkdir(parents=True)
            state_path.write_text("last-known-state", encoding="utf-8")

            with mock.patch.object(
                continuum_module.infra_state,
                "load_resume_state",
                return_value=({"phase_completed": "infrastructure"}, machines),
            ), mock.patch.object(
                continuum_module.machine_utils,
                "validate_resume_ssh_reachability",
                side_effect=RuntimeError("cloud0@192.0.2.10 (missing exact marker)"),
            ), mock.patch.object(
                continuum_module.image_registry, "prepare_runtime_images"
            ) as mock_prepare_images, mock.patch.object(
                continuum_module.ansible, "AnsibleRunner"
            ) as mock_ansible_runner, mock.patch.object(
                continuum_module.resource_manager, "start"
            ) as mock_resource_manager_start, mock.patch.object(
                continuum_module.application, "start"
            ) as mock_application_start, mock.patch.object(
                continuum_module.infra_state, "save_state"
            ) as mock_save_state, mock.patch.object(
                continuum_module.yaml_parser, "write_experiment_lock", return_value=None
            ), mock.patch.object(continuum_module, "_log_vm_access_hints"):
                with self.assertRaises(SystemExit):
                    continuum_module.main(args)

            mock_ansible_runner.assert_not_called()
            mock_prepare_images.assert_not_called()
            mock_resource_manager_start.assert_not_called()
            mock_application_start.assert_not_called()
            mock_save_state.assert_not_called()
            self.assertEqual(state_path.read_text(encoding="utf-8"), "last-known-state")

    def test_resume_image_preparation_failure_stops_before_runner_dispatch_and_state_save(self):
        config = self._config(["software"])
        args = argparse.Namespace(config=config)
        machines = [mock.Mock()]
        events = []

        def fail_image_preparation(*_args):
            events.append("prepare")
            raise SystemExit(1)

        with mock.patch.object(
            continuum_module.yaml_parser, "write_experiment_lock", return_value=None
        ), mock.patch.object(
            continuum_module.infra_state,
            "load_resume_state",
            return_value=({"phase_completed": "infrastructure"}, machines),
        ), mock.patch.object(
            continuum_module.machine_utils,
            "validate_resume_ssh_reachability",
            side_effect=lambda *_args: events.append("preflight") or ["cloud0@192.0.2.10"],
        ), mock.patch.object(
            continuum_module.image_registry,
            "prepare_runtime_images",
            side_effect=fail_image_preparation,
        ), mock.patch.object(
            continuum_module.ansible, "AnsibleRunner"
        ) as ansible_runner, mock.patch.object(
            continuum_module.resource_manager, "start"
        ) as resource_manager_start, mock.patch.object(
            continuum_module.application, "start"
        ) as application_start, mock.patch.object(
            continuum_module.infra_state, "save_state"
        ) as save_state, mock.patch.object(
            continuum_module, "_log_vm_access_hints"
        ):
            with self.assertRaises(SystemExit):
                continuum_module.main(args)

        self.assertEqual(events, ["preflight", "prepare"])
        ansible_runner.assert_not_called()
        resource_manager_start.assert_not_called()
        application_start.assert_not_called()
        save_state.assert_not_called()

    def test_apply_module_options_application_scope_defaults_primary_stage_config(self):
        parser = argparse.ArgumentParser(prog="apply-options-application")
        config = {
            "module": {
                "application": object(),
                "provider": False,
                "resource_manager": False,
            },
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {
                                "frequency": 5,
                                "applications_per_worker": 1,
                                "application_worker_cpu": 0.5,
                                "application_worker_memory": 1.0,
                                "application_endpoint_cpu": 0.5,
                                "application_endpoint_memory": 1.0,
                            },
                        }
                    ]
                }
            },
        }

        with mock.patch("input.configuration.runtime_option_validation.application.add_options") as mock_add_options:
            mock_add_options.return_value = [
                ("frequency", int, lambda value: value >= 1, True, None),
                ("duration", int, lambda value: value >= 1, False, 300),
            ]

            runtime_option_validation.apply_module_options(parser, config)

        self.assertEqual(
            config["domains"]["benchmark"]["pipeline"][0]["config"],
            {
                "frequency": 5,
                "applications_per_worker": 1,
                "application_worker_cpu": 0.5,
                "application_worker_memory": 1.0,
                "application_endpoint_cpu": 0.5,
                "application_endpoint_memory": 1.0,
                "duration": 300,
            },
        )

    def test_runtime_option_float_overflow_uses_parser_error_boundary(self):
        parser = argparse.ArgumentParser(prog="apply-options-overflow")
        config = {
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {"application_worker_cpu": 10**400},
                        }
                    ]
                }
            }
        }
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation._coerce_option_value(  # pylint: disable=protected-access
                    parser,
                    config,
                    "application",
                    "application_worker_cpu",
                    float,
                    10**400,
                )

        self.assertIn("application_worker_cpu", stderr.getvalue())
        self.assertIn("expected <class 'float'>", stderr.getvalue())

    def test_apply_module_options_application_scope_accepts_shared_stage_contract_keys(self):
        parser = argparse.ArgumentParser(prog="apply-options-application-shared")
        config = {
            "module": {
                "application": object(),
                "provider": False,
                "resource_manager": False,
            },
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {
                                "frequency": 5,
                                "applications_per_worker": 1,
                                "application_worker_cpu": 1,
                                "application_worker_memory": 1.0,
                                "application_endpoint_cpu": 0.5,
                                "application_endpoint_memory": 1.0,
                            },
                        }
                    ]
                }
            },
        }

        with mock.patch("input.configuration.runtime_option_validation.application.add_options") as mock_add_options:
            mock_add_options.return_value = [
                ("frequency", int, lambda value: value >= 1, True, None),
                ("duration", int, lambda value: value >= 1, False, 300),
            ]

            runtime_option_validation.apply_module_options(parser, config)

        self.assertEqual(
            config["domains"]["benchmark"]["pipeline"][0]["config"],
            {
                "frequency": 5,
                "applications_per_worker": 1,
                "application_worker_cpu": 1.0,
                "application_worker_memory": 1.0,
                "application_endpoint_cpu": 0.5,
                "application_endpoint_memory": 1.0,
                "duration": 300,
            },
        )

    def test_apply_module_options_missing_application_scope_fails_fast(self):
        parser = argparse.ArgumentParser(prog="apply-options-application-missing")
        config = {
            "module": {
                "application": object(),
                "provider": False,
                "resource_manager": False,
            },
            "domains": {},
        }
        stderr = io.StringIO()
        with mock.patch("input.configuration.runtime_option_validation.application.add_options") as mock_add_options:
            mock_add_options.return_value = [
                ("frequency", int, lambda value: value >= 1, True, None),
            ]
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    runtime_option_validation.apply_module_options(parser, config)
        self.assertIn("domains.benchmark.pipeline[*].config", stderr.getvalue())

    def test_verify_options_application_scope_delegates_to_application_module(self):
        parser = argparse.ArgumentParser(prog="verify-options-application")
        config = {
            "module": {
                "application": object(),
                "provider": False,
                "resource_manager": False,
            },
            "domains": {
                "run": {"targets": ["application"]},
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {"frequency": 5, "duration": 300},
                        }
                    ]
                },
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"cache_worker": False},
                        }
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 1},
        }

        with mock.patch(
            "input.configuration.runtime_option_validation.application.verify_options"
        ) as mock_verify:
            with mock.patch(
                "input.configuration.runtime_option_validation.module_contract_validation.evaluate_module_contracts"
            ) as mock_evaluate:
                mock_evaluate.return_value = {"violations": []}
                runtime_option_validation.verify_options(parser, config)

        mock_verify.assert_called_once_with(parser, config)

    @mock.patch("input.configuration.runtime_option_validation.infrastructure.add_options")
    def test_apply_module_options_missing_provider_scope_fails_fast(self, mock_add_options):
        parser = argparse.ArgumentParser(prog="apply-options-provider-scope")
        mock_add_options.return_value = [("cpu_pin", bool, lambda value: isinstance(value, bool), False, False)]

        config = {
            "module": {
                "application": False,
                "provider": object(),
                "resource_manager": False,
            },
            "domains": {},
        }

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation.apply_module_options(parser, config)
        self.assertIn("Missing option scope domains.provider.config", stderr.getvalue())

    @mock.patch("input.configuration.runtime_option_validation.infrastructure.add_options")
    def test_apply_module_options_unknown_provider_option_fails_fast(self, mock_add_options):
        parser = argparse.ArgumentParser(prog="apply-options-provider-unknown")
        mock_add_options.return_value = []

        config = {
            "module": {
                "application": False,
                "provider": object(),
                "resource_manager": False,
            },
            "domains": {
                "provider": {
                    "config": {
                        "unexpected": "value",
                    }
                }
            },
        }

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation.apply_module_options(parser, config)
        self.assertIn("Unknown option(s) in domains.provider.config: unexpected", stderr.getvalue())

    @mock.patch("input.configuration.runtime_option_validation.infrastructure.add_options")
    def test_apply_module_options_accepts_core_provider_keys(self, mock_add_options):
        parser = argparse.ArgumentParser(prog="apply-options-provider-core")
        mock_add_options.return_value = []

        config = {
            "module": {
                "application": False,
                "provider": object(),
                "resource_manager": False,
            },
            "domains": {
                "provider": {
                    "config": {
                        "base_path": "/tmp/continuum",
                        "cpu_pin": False,
                        "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                    }
                }
            },
        }

        runtime_option_validation.apply_module_options(parser, config)

    @mock.patch("input.configuration.runtime_option_validation.resource_manager.add_options")
    def test_apply_module_options_missing_rm_scope_fails_fast(self, mock_add_options):
        parser = argparse.ArgumentParser(prog="apply-options-rm-scope")
        mock_add_options.return_value = [("runtime", str, lambda value: isinstance(value, str), False, "docker")]

        config = {
            "module": {
                "application": False,
                "provider": False,
                "resource_manager": object(),
            },
            "domains": {},
        }

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation.apply_module_options(parser, config)
        self.assertIn("Missing option scope domains.software.modules", stderr.getvalue())

    @mock.patch("input.configuration.runtime_option_validation.resource_manager.add_options")
    def test_apply_module_options_unknown_rm_option_fails_fast(self, mock_add_options):
        parser = argparse.ArgumentParser(prog="apply-options-rm-unknown")
        mock_add_options.return_value = []

        config = {
            "module": {
                "application": False,
                "provider": False,
                "resource_manager": object(),
            },
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"unexpected": True},
                        }
                    ]
                }
            },
        }

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation.apply_module_options(parser, config)
        self.assertIn("Unknown option(s) in domains.software.modules[0].config: unexpected", stderr.getvalue())

    def test_dynamic_import_invalid_provider_fails_cleanly(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-provider")
        config = {
            "infrastructure": {"provider": "does-not-exist"},
            "domains": {"run": {"targets": ["infrastructure"]}},
        }
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_module_loader.dynamic_import(parser, config)
        self.assertIn("does-not-exist", stderr.getvalue())
        self.assertIn("does not have an implementation", stderr.getvalue())

    def test_dynamic_import_loads_application_module_and_sets_images(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-application")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {"targets": ["application"]},
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
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "image_classification",
                            "config": {"frequency": 5, "duration": 300},
                        }
                    ]
                },
            },
        }

        runtime_module_loader.dynamic_import(parser, config)

        self.assertEqual(
            config["module"]["application"].__name__,
            "application.image_classification.image_classification",
        )
        self.assertEqual(
            config["images"]["worker"],
            "redplanet00/kubeedge-applications:image_classification_subscriber",
        )
        self.assertEqual(
            config["images"]["endpoint"],
            "redplanet00/kubeedge-applications:image_classification_publisher",
        )

    def test_dynamic_import_rejects_multi_stage_pipeline_before_config_mutation_or_import(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-multi-stage")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {"targets": ["application"]},
                "benchmark": {
                    "pipeline": [
                        {"id": "stage-1", "type": "publisher", "config": {}},
                        {"id": "stage-2", "type": "publisher", "config": {}},
                    ]
                },
            },
        }

        stderr = io.StringIO()
        with mock.patch.object(runtime_module_loader.importlib, "import_module") as import_module:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    runtime_module_loader.dynamic_import(parser, config)

        self.assertIn("domains.benchmark.pipeline", stderr.getvalue())
        self.assertIn("exactly one executable stage", stderr.getvalue())
        self.assertIn("ordered multi-stage execution is not supported", stderr.getvalue())
        self.assertIn("found 2 stages", stderr.getvalue())
        self.assertNotIn("module", config)
        import_module.assert_not_called()

    def test_dynamic_import_tolerates_non_runtime_benchmark_stage_without_application_module(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-application-optional")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {"targets": ["application"]},
                "software": {
                    "modules": [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "bench-1",
                            "type": "publisher",
                            "config": {},
                        }
                    ]
                },
            },
        }

        runtime_module_loader.dynamic_import(parser, config)

        self.assertFalse(config["module"]["application"])
        self.assertNotIn("images", config)

    def test_dynamic_import_skips_resource_manager_for_plain_infra_only_stack(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-infra-only-no-prep")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                },
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }

        runtime_module_loader.dynamic_import(parser, config)

        self.assertFalse(config["module"]["resource_manager"])

    def test_dynamic_import_loads_resource_manager_for_infra_only_resume_prep_stack(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-infra-only-rm")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": True,
                },
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }

        runtime_module_loader.dynamic_import(parser, config)

        self.assertEqual(
            config["module"]["resource_manager"].__name__,
            "resource_manager.kubernetes.kubernetes",
        )

    def test_add_constants_skips_registry_for_plain_infra_only_stack(self):
        parser = argparse.ArgumentParser(prog="add-constants-infra-only-no-prep")
        config = {
            "infrastructure": {"provider": "qemu", "base_path": "/tmp/continuum-smoke"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                },
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }
        socket_module = self._FakeSocketModule()

        runtime_module_loader.dynamic_import(parser, config)
        runtime_module_loader.add_constants(parser, config, socket_module=socket_module)

        self.assertNotIn("registry", config)
        self.assertEqual(socket_module.socket_calls, 0)

    def test_add_constants_sets_registry_for_infra_only_resume_prep_stack(self):
        parser = argparse.ArgumentParser(prog="add-constants-infra-only-rm-registry")
        config = {
            "infrastructure": {"provider": "qemu", "base_path": "/tmp/continuum-smoke"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": True,
                },
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }
        socket_module = self._FakeSocketModule()

        runtime_module_loader.dynamic_import(parser, config)
        runtime_module_loader.add_constants(parser, config, socket_module=socket_module)

        self.assertEqual(config["registry"], "192.168.1.104:5000")
        self.assertEqual(socket_module.socket_calls, 1)

    def test_dynamic_import_keeps_none_orchestrator_unloaded_for_infra_only(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-infra-only-none")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                },
                "software": {
                    "modules": [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
        }

        runtime_module_loader.dynamic_import(parser, config)

        self.assertFalse(config["module"]["resource_manager"])

    def test_add_constants_skips_registry_for_pure_infra_only_none_stack(self):
        parser = argparse.ArgumentParser(prog="add-constants-infra-only-none-registry")
        config = {
            "infrastructure": {"provider": "qemu", "base_path": "/tmp/continuum-smoke"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                },
                "software": {
                    "modules": [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
        }
        socket_module = self._FakeSocketModule()

        runtime_module_loader.dynamic_import(parser, config)
        runtime_module_loader.add_constants(parser, config, socket_module=socket_module)

        self.assertNotIn("registry", config)
        self.assertEqual(socket_module.socket_calls, 0)

    def test_add_constants_host_ip_lookup_failure_fails_cleanly(self):
        parser = argparse.ArgumentParser(prog="add-constants-host-ip")
        config = {"domains": {"run": {"targets": ["software"]}}}

        class FailingSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def connect(self, _target):
                raise runtime_module_loader.socket_lib.gaierror("mock-no-ip")

        stderr = io.StringIO()
        with mock.patch(
            "input.configuration.runtime_module_loader.socket_lib.socket",
            return_value=FailingSocket(),
        ):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    runtime_module_loader.add_constants(parser, config)

        self.assertIn("Could not get host ip with error", stderr.getvalue())
        self.assertIn("mock-no-ip", stderr.getvalue())

    def test_add_constants_host_ip_socket_permission_failure_fails_cleanly(self):
        parser = argparse.ArgumentParser(prog="add-constants-host-ip-permission")
        config = {"domains": {"run": {"targets": ["software"]}}}

        stderr = io.StringIO()
        with mock.patch(
            "input.configuration.runtime_module_loader.socket_lib.socket",
            side_effect=PermissionError("mock-permission-denied"),
        ):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    runtime_module_loader.add_constants(parser, config)

        self.assertIn("Could not get host ip with error", stderr.getvalue())
        self.assertIn("mock-permission-denied", stderr.getvalue())

    def test_add_constants_places_ssh_key_under_base_path(self):
        parser = argparse.ArgumentParser(prog="add-constants-ssh-key")
        config = {
            "infrastructure": {"base_path": "/tmp/continuum-smoke"},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                }
            },
        }

        runtime_module_loader.add_constants(parser, config)

        self.assertEqual(
            config["ssh_key"],
            "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum",
        )
        self.assertEqual(
            config["ssh_known_hosts_file"],
            "/tmp/continuum-smoke/.continuum/ssh/known_hosts",
        )

    def test_create_inventory_vm_infra_only_cloud_does_not_require_kube_version(self):
        config = {
            "mode": "cloud",
            "ssh_key": "/tmp/id_rsa_continuum",
            "infrastructure": {
                "base_path": "/tmp/continuum-smoke",
                "provider": "qemu",
                "endpoint_nodes": 0,
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
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
        }
        machine = mock.Mock(
            cloud_controller_ips_internal=["10.0.0.10"],
            cloud_controller_ips=["192.168.122.10"],
            cloud_controller_names=["cloudcontroller0"],
            cloud_names=[],
            cloud_ips=[],
            edge_names=[],
            edge_ips=[],
            endpoint_names=[],
            endpoint_ips=[],
            base_ips=[],
            base_names=[],
        )

        with mock.patch("builtins.open", mock.mock_open()) as open_mock:
            infrastructure_ansible.create_inventory_vm(config, [machine])

        written = "".join(call.args[0] for call in open_mock().write.call_args_list)
        self.assertIn("continuum_home=/tmp/continuum-smoke/.continuum", written)
        self.assertIn("kubeversion=1.27.0", written)

    def test_create_inventory_vm_infra_only_cloud_allows_missing_controller_vm(self):
        config = {
            "mode": "cloud",
            "ssh_key": "/tmp/id_rsa_continuum",
            "infrastructure": {
                "base_path": "/tmp/continuum-smoke",
                "provider": "qemu",
                "endpoint_nodes": 0,
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
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
        }
        machine = mock.Mock(
            cloud_controller_ips_internal=[],
            cloud_controller_ips=[],
            cloud_controller_names=[],
            cloud_names=["cloud0"],
            cloud_ips=["192.168.122.10"],
            edge_names=[],
            edge_ips=[],
            endpoint_names=[],
            endpoint_ips=[],
            base_ips=[],
            base_names=[],
        )

        with mock.patch("builtins.open", mock.mock_open()) as open_mock:
            infrastructure_ansible.create_inventory_vm(config, [machine])

        written = "".join(call.args[0] for call in open_mock().write.call_args_list)
        self.assertIn("[clouds]", written)
        self.assertIn("cloud0 ansible_connection=ssh", written)

    def test_create_inventory_vm_infra_only_cloud_maps_generic_base_into_base_cloud(self):
        config = {
            "mode": "cloud",
            "ssh_key": "/tmp/id_rsa_continuum",
            "infrastructure": {
                "base_path": "/tmp/continuum-smoke",
                "provider": "qemu",
                "endpoint_nodes": 1,
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
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
        }
        machine = mock.Mock(
            cloud_controller_ips_internal=["10.0.0.10"],
            cloud_controller_ips=["192.168.122.10"],
            cloud_controller_names=["cloudcontroller0"],
            cloud_names=["cloud0"],
            cloud_ips=["192.168.122.11"],
            edge_names=[],
            edge_ips=[],
            endpoint_names=["endpoint0"],
            endpoint_ips=["192.168.122.12"],
            base_ips=["192.168.90.2"],
            base_names=["base0_continuum-smoke"],
            cloud_controller=1,
            clouds=1,
            edges=0,
            endpoints=1,
        )

        with mock.patch("builtins.open", mock.mock_open()) as open_mock:
            infrastructure_ansible.create_inventory_vm(config, [machine])

        written = "".join(call.args[0] for call in open_mock().write.call_args_list)
        self.assertIn("[base_cloud]", written)
        self.assertIn(
            "base0_continuum-smoke ansible_connection=ssh ansible_host=192.168.90.2",
            written,
        )
        self.assertIn("kubeversion=1.27.0", written)

    def test_create_inventory_vm_shortens_long_base_login_user(self):
        long_base_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"
        expected_user = orchestration_schema.guest_login_name(long_base_name)
        config = {
            "mode": "cloud",
            "ssh_key": "/tmp/id_rsa_continuum",
            "infrastructure": {
                "base_path": "/tmp/continuum-smoke",
                "provider": "qemu",
                "endpoint_nodes": 0,
            },
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {"kube_version": "v1.27.0"},
                        }
                    ]
                },
            },
        }
        machine = mock.Mock(
            cloud_controller_ips_internal=["10.0.0.10"],
            cloud_controller_ips=["192.168.122.10"],
            cloud_controller_names=["cloudcontroller0"],
            cloud_names=["cloud0"],
            cloud_ips=["192.168.122.11"],
            edge_names=[],
            edge_ips=[],
            endpoint_names=[],
            endpoint_ips=[],
            base_ips=["192.168.90.2"],
            base_names=[long_base_name],
        )

        with mock.patch("builtins.open", mock.mock_open()) as open_mock:
            infrastructure_ansible.create_inventory_vm(config, [machine])

        written = "".join(call.args[0] for call in open_mock().write.call_args_list)
        self.assertIn("continuum_repo_root=", written)
        self.assertIn("continuum_resource_manager_type=kubernetes", written)
        self.assertIn(
            "%s ansible_connection=ssh ansible_host=192.168.90.2 ansible_user=%s username=%s"
            % (long_base_name, expected_user, expected_user),
            written,
        )

    def test_generate_group_vars_infra_only_cloud_uses_default_kube_version(self):
        config = {
            "mode": "cloud",
            "username": "tester",
            "ssh_key": "/tmp/id_rsa_continuum",
            "infrastructure": {
                "base_path": "/tmp/continuum-smoke",
            },
            "domains": {
                "run": {"targets": ["infrastructure"]},
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
        }
        machine = mock.Mock(
            cloud_controller_ips_internal=[],
            cloud_controller_ips=[],
        )

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(infrastructure_ansible, "_write_group_vars") as write_mock:
                infrastructure_ansible.generate_group_vars(config, [machine], tempdir)

        all_vars = write_mock.call_args_list[0].args[1]
        self.assertEqual(all_vars["continuum_kubeversion"], "1.27.0")


class ImagePrefetchFlowTests(unittest.TestCase):
    def _process_result(self, output=None, error=None):
        return [(output or [], error or [])]

    def _none_software_domain(self):
        return {
            "modules": [
                {
                    "id": "none-main",
                    "type": "none",
                    "assign_to": {"match": {"cluster": "cloud-1"}},
                    "resolved_vm_ids": [1],
                    "config": {},
                }
            ]
        }

    def _digest_requirement(self, source_ref, local_name):
        return {
            "source_ref": source_ref,
            "local_name": local_name,
            "owners": ["benchmark.stage:text-translation"],
            "tier_targets": ["cloud", "endpoint"],
        }

    def _manifest_payload(self, config_digest, media_type=None):
        manifest_media_type = media_type or "application/vnd.oci.image.manifest.v1+json"
        if manifest_media_type == "application/vnd.docker.distribution.manifest.v2+json":
            config_media_type = "application/vnd.docker.container.image.v1+json"
        else:
            config_media_type = "application/vnd.oci.image.config.v1+json"
        return {
            "schemaVersion": 2,
            "mediaType": manifest_media_type,
            "config": {
                "mediaType": config_media_type,
                "digest": config_digest,
                "size": 1,
            },
            "layers": [],
        }

    def _local_registry_machine(self, repo_name, manifest_responses, tags=None):
        responses = list(manifest_responses)
        manifest_digest = "sha256:%s" % ("b" * 64)
        machine = mock.Mock()

        def process(_config, command, **_kwargs):
            if command[0] == "docker":
                return self._process_result(["ok"])
            self.assertEqual(command[0], "curl")
            self.assertTrue(command[-1].startswith("127.0.0.1:5000/v2/"))
            if command[-1].endswith("/v2/_catalog"):
                return self._process_result(
                    [json.dumps({"repositories": [repo_name]})]
                )
            if command[-1].endswith("/%s/tags/list" % repo_name):
                return self._process_result(
                    [json.dumps({"name": repo_name, "tags": tags or ["latest"]})]
                )
            if "/%s/manifests/" % repo_name in command[-1]:
                if "-I" in command:
                    return self._process_result(
                        ["Docker-Content-Digest: %s" % manifest_digest]
                    )
                self.assertTrue(command[-1].endswith("/manifests/%s" % manifest_digest))
                response = responses.pop(0) if responses else None
                if response is None:
                    return self._process_result([])
                if not isinstance(response, str):
                    response = json.dumps(response)
                return self._process_result([response])
            self.fail("Unexpected local registry command: %r" % (command,))

        machine.process.side_effect = process
        return machine

    def _text_translation_digest_requirements(self):
        return (
            (
                "redplanet00/continuum-text-translation-publisher"
                "@sha256:502142b93182c63f1225165f44d0308537aac95ee75a99b6f0ba19e668f6f6bf",
                "text_translation_publisher_en-nl-8aad73b-r1",
                "sha256:5fab1472b1ba67c56b86dcb48c7d9aeee270604a42514f0edf6f853988f57cfe",
            ),
            (
                "redplanet00/continuum-text-translation-subscriber"
                "@sha256:9aac61a0a1f0fe8938db7283b7f09ab9f9c5f84d95467fa267e9ca3220aabd26",
                "text_translation_subscriber_en-nl-8aad73b-r1",
                "sha256:8973a8d27ba02c08b5dbbc43329a1c8f54c56a887945e3520cc10bab63167417",
            ),
        )

    def test_prepare_runtime_images_resolves_before_registry_verification(self):
        config = {"marker": "config"}
        machines = [mock.Mock()]
        events = []
        with mock.patch.object(
            image_registry_module,
            "resolve_prefetch_requirements",
            side_effect=lambda *_args: events.append("resolve"),
        ) as resolve, mock.patch.object(
            image_registry_module,
            "docker_registry",
            side_effect=lambda *_args: events.append("registry"),
        ) as registry:
            image_registry_module.prepare_runtime_images(config, machines)

        self.assertEqual(events, ["resolve", "registry"])
        resolve.assert_called_once_with(config)
        registry.assert_called_once_with(config, machines)

    def test_fresh_infrastructure_prepares_images_before_provider_start(self):
        config = {
            "infrastructure": {
                "cpu_pin": False,
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "cloud_cores": 1,
                "edge_cores": 1,
                "endpoint_cores": 1,
                "network_emulation": False,
                "netperf": False,
            }
        }
        machine = mock.Mock(cores=4)
        events = []
        with mock.patch.object(
            infrastructure_module.m, "make_machine_objects", return_value=[machine]
        ), mock.patch.object(
            infrastructure_module.m,
            "remove_idle",
            return_value=([machine], [{"cloud": 1, "edge": 0, "endpoint": 0}]),
        ), mock.patch.object(
            infrastructure_module, "delete_vms"
        ), mock.patch.object(
            infrastructure_module, "create_tmp_dir"
        ), mock.patch.object(
            infrastructure_module, "delete_old_content"
        ), mock.patch.object(
            infrastructure_module, "create_continuum_dir"
        ), mock.patch.object(
            infrastructure_module, "set_ip_names"
        ), mock.patch.object(
            infrastructure_module.m, "print_schedule"
        ), mock.patch.object(
            infrastructure_module.image_registry,
            "prepare_runtime_images",
            side_effect=lambda *_args: events.append("prepare"),
        ) as prepare, mock.patch.object(
            infrastructure_module,
            "start_provider",
            side_effect=lambda *_args: events.append("provider"),
        ) as provider:
            result = infrastructure_module.start(config)

        self.assertEqual(result, [machine])
        self.assertEqual(events, ["prepare", "provider"])
        prepare.assert_called_once_with(config, [machine])
        provider.assert_called_once_with(config, [machine])

    def test_get_prefetch_requirements_requires_prefetch_key(self):
        with self.assertRaises(SystemExit):
            image_registry_module.get_prefetch_requirements({})

    def test_get_prefetch_requirements_rejects_non_list_payload(self):
        with self.assertRaises(SystemExit):
            image_registry_module.get_prefetch_requirements({"prefetch_image_requirements": {}})

    def test_get_prefetch_requirements_rejects_non_mapping_entry(self):
        with self.assertRaises(SystemExit):
            image_registry_module.get_prefetch_requirements({"prefetch_image_requirements": [1]})

    def test_get_prefetch_requirements_rejects_empty_owners(self):
        config = {
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/repo:latest",
                    "local_name": "repo:latest",
                    "owners": [],
                    "tier_targets": ["cloud"],
                }
            ]
        }
        with self.assertRaises(SystemExit):
            image_registry_module.get_prefetch_requirements(config)

    def test_get_prefetch_requirements_normalizes_and_dedupes_values(self):
        config = {
            "prefetch_image_requirements": [
                {
                    "source_ref": " registry.example/repo:latest ",
                    "local_name": " repo:latest ",
                    "owners": [" software.module:a ", "software.module:a", "benchmark.stage:s1"],
                    "tier_targets": [" cloud ", "endpoint", "cloud"],
                }
            ]
        }

        requirements = image_registry_module.get_prefetch_requirements(config)
        self.assertEqual(
            requirements,
            [
                {
                    "source_ref": "registry.example/repo:latest",
                    "local_name": "repo:latest",
                    "owners": ["benchmark.stage:s1", "software.module:a"],
                    "tier_targets": ["cloud", "endpoint"],
                }
            ],
        )

    def test_resolve_prefetch_requirements_defaults_to_empty(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {"infrastructure": {"resources": []}},
        }
        requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(requirements, [])
        self.assertEqual(config.get("prefetch_image_requirements"), [])

    def test_resolve_prefetch_requirements_rejects_missing_resolved_vm_ids(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "addon-a",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        with mock.patch(
            "input.configuration.module_registry.get_spec",
            return_value=module_registry.ModuleSpec(
                scope="addon",
                image_catalog_refs=("catalog.shared",),
            ),
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.shared": "registry.example/shared-repo:latest"},
            clear=True,
        ):
            with self.assertRaises(SystemExit):
                image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_rejects_unknown_resolved_vm_id(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "addon-a",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [99],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        with mock.patch(
            "input.configuration.module_registry.get_spec",
            return_value=module_registry.ModuleSpec(
                scope="addon",
                image_catalog_refs=("catalog.shared",),
            ),
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.shared": "registry.example/shared-repo:latest"},
            clear=True,
        ):
            with self.assertRaises(SystemExit):
                image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_rejects_unknown_module_type(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "unknown-main",
                            "type": "unknown-module",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_rejects_malformed_resource_record(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "none-main",
                            "type": "none",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {"infrastructure": {"resources": [1]}},
        }

        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_kubecontrol_control_plane_images(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "kubecontrol-main",
                            "type": "kubecontrol",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {"kube_version": "v1.24.0"},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(len(requirements), 7)
        sources = [entry["source_ref"] for entry in requirements]
        self.assertIn("redplanet00/kube-apiserver:v1.24.0", sources)
        self.assertIn("redplanet00/etcd:3.5.3-0", sources)
        self.assertIn("redplanet00/coredns:v1.8.6", sources)
        self.assertIn("redplanet00/pause:3.7", sources)
        for entry in requirements:
            self.assertEqual(entry["owners"], ["software.module:kubecontrol-main"])
            self.assertEqual(entry["tier_targets"], ["cloud"])

    def test_resolve_prefetch_requirements_rejects_unsupported_kube_version(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "kubecontrol-main",
                            "type": "kubecontrol",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {"kube_version": "v9.99.0"},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_rejects_missing_kube_version(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "kubecontrol-main",
                            "type": "kubecontrol",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_is_deduplicated_and_deterministic(self):
        config = {
            "domains": {
                "run": {"targets": ["software"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "addon-a",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        },
                        {
                            "id": "addon-b",
                            "type": "observability",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        },
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }

        original_get_spec = module_registry.get_spec

        def patched_get_spec(module_type):
            if module_type in {"openfaas", "observability"}:
                return module_registry.ModuleSpec(
                    scope="addon",
                    image_catalog_refs=("catalog.shared",),
                )
            return original_get_spec(module_type)

        with mock.patch(
            "input.configuration.module_registry.get_spec",
            side_effect=patched_get_spec,
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.shared": "registry.example/shared-repo:latest"},
            clear=True,
        ):
            requirements = image_registry_module.resolve_prefetch_requirements(config)

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["source_ref"], "registry.example/shared-repo:latest")
        self.assertEqual(requirements[0]["owners"], ["software.module:addon-a", "software.module:addon-b"])
        self.assertEqual(requirements[0]["tier_targets"], ["cloud"])

    def test_resolve_prefetch_requirements_ignores_software_when_not_targeted(self):
        config = {
            "domains": {
                "run": {"targets": ["infrastructure"], "image_prefetch": "on"},
                "software": {
                    "modules": [
                        {
                            "id": "addon-a",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }
        with mock.patch(
            "input.configuration.module_registry.get_spec",
            return_value=module_registry.ModuleSpec(
                scope="addon",
                image_catalog_refs=("catalog.shared",),
            ),
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.shared": "registry.example/shared-repo:latest"},
            clear=True,
        ):
            requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(requirements, [])

    def test_resolve_prefetch_requirements_unknown_stage_type_fails_fast(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": self._none_software_domain(),
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-1",
                            "type": "unknown-stage-type",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }
        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_application_target_requires_pipeline(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": self._none_software_domain(),
            },
            "normalized": {"infrastructure": {"resources": []}},
        }
        with self.assertRaises(SystemExit):
            image_registry_module.resolve_prefetch_requirements(config)

    def test_resolve_prefetch_requirements_builtin_empty_stage_mapping(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": self._none_software_domain(),
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-empty",
                            "type": "empty",
                            "assign_to": {"match": {"cluster": "endpoint-1"}},
                            "resolved_vm_ids": [2],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 2, "tags": {"tier": "endpoint", "cluster": "endpoint-1"}}
                    ]
                }
            },
        }
        requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["source_ref"], "redplanet00/kubeedge-applications:empty")
        self.assertEqual(requirements[0]["owners"], ["benchmark.stage:stage-empty"])
        self.assertEqual(requirements[0]["tier_targets"], ["endpoint"])

    def test_resolve_prefetch_requirements_builtin_image_classification_stage_mapping(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": self._none_software_domain(),
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-ic",
                            "type": "image_classification",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }
        requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(len(requirements), 3)
        self.assertEqual(
            [entry["source_ref"] for entry in requirements],
            sorted(entry["source_ref"] for entry in requirements),
        )
        self.assertIn(
            "redplanet00/kubeedge-applications:image_classification_combined",
            [entry["source_ref"] for entry in requirements],
        )
        self.assertIn(
            "redplanet00/kubeedge-applications:image_classification_publisher",
            [entry["source_ref"] for entry in requirements],
        )
        self.assertIn(
            "redplanet00/kubeedge-applications:image_classification_subscriber",
            [entry["source_ref"] for entry in requirements],
        )
        self.assertNotIn(
            "redplanet00/kubeedge-applications:image_classification_publisher_serverless",
            [entry["source_ref"] for entry in requirements],
        )
        for entry in requirements:
            self.assertEqual(entry["owners"], ["benchmark.stage:stage-ic"])
            self.assertEqual(entry["tier_targets"], ["cloud"])

    def test_resolve_prefetch_requirements_image_classification_with_openfaas(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "openfaas-main",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-ic",
                            "type": "image_classification",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                    ]
                }
            },
        }
        requirements = image_registry_module.resolve_prefetch_requirements(config)
        self.assertEqual(len(requirements), 2)
        sources = [entry["source_ref"] for entry in requirements]
        self.assertEqual(sources, sorted(sources))
        self.assertIn(
            "redplanet00/kubeedge-applications:image_classification_publisher_serverless",
            sources,
        )
        self.assertIn(
            "redplanet00/kubeedge-applications:image_classification_subscriber_serverless",
            sources,
        )
        self.assertNotIn("redplanet00/kubeedge-applications:image_classification_combined", sources)
        self.assertNotIn("redplanet00/kubeedge-applications:image_classification_publisher", sources)
        self.assertNotIn("redplanet00/kubeedge-applications:image_classification_subscriber", sources)
        for entry in requirements:
            self.assertEqual(entry["owners"], ["benchmark.stage:stage-ic"])
            self.assertEqual(entry["tier_targets"], ["cloud"])

    def test_resolve_prefetch_requirements_includes_stage_images_when_mapped(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": self._none_software_domain(),
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-1",
                            "type": "generator",
                            "assign_to": {"match": {"cluster": "edge-1"}},
                            "resolved_vm_ids": [2],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 2, "tags": {"tier": "edge", "cluster": "edge-1"}}
                    ]
                }
            },
        }
        with mock.patch.dict(
            "input.configuration.image_requirements._STAGE_IMAGE_CATALOG",
            {"generator": ("catalog.stage",)},
            clear=True,
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.stage": "registry.example/stage-repo:v1"},
            clear=True,
        ):
            requirements = image_registry_module.resolve_prefetch_requirements(config)

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["source_ref"], "registry.example/stage-repo:v1")
        self.assertEqual(requirements[0]["owners"], ["benchmark.stage:stage-1"])
        self.assertEqual(requirements[0]["tier_targets"], ["edge"])

    def test_resolve_prefetch_requirements_dedupes_shared_module_and_stage_images(self):
        config = {
            "domains": {
                "run": {"targets": ["application"], "image_prefetch": "off"},
                "software": {
                    "modules": [
                        {
                            "id": "addon-a",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "resolved_vm_ids": [1],
                            "config": {},
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-1",
                            "type": "generator",
                            "assign_to": {"match": {"cluster": "endpoint-1"}},
                            "resolved_vm_ids": [2],
                            "config": {},
                        }
                    ]
                },
            },
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {"vm_id": 1, "tags": {"tier": "cloud", "cluster": "cloud-1"}},
                        {"vm_id": 2, "tags": {"tier": "endpoint", "cluster": "endpoint-1"}},
                    ]
                }
            },
        }

        original_get_spec = module_registry.get_spec

        def patched_get_spec(module_type):
            if module_type == "openfaas":
                return module_registry.ModuleSpec(
                    scope="addon",
                    image_catalog_refs=("catalog.shared",),
                )
            return original_get_spec(module_type)

        with mock.patch(
            "input.configuration.module_registry.get_spec",
            side_effect=patched_get_spec,
        ), mock.patch.dict(
            "input.configuration.image_requirements._STAGE_IMAGE_CATALOG",
            {"generator": ("catalog.shared",)},
            clear=True,
        ), mock.patch.dict(
            "input.configuration.image_requirements._IMAGE_CATALOG",
            {"catalog.shared": "registry.example/shared-repo:latest"},
            clear=True,
        ):
            requirements = image_registry_module.resolve_prefetch_requirements(config)

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["source_ref"], "registry.example/shared-repo:latest")
        self.assertEqual(
            requirements[0]["owners"],
            ["benchmark.stage:stage-1", "software.module:addon-a"],
        )
        self.assertEqual(requirements[0]["tier_targets"], ["cloud", "endpoint"])

    def test_docker_registry_skips_when_no_requirements(self):
        machine = mock.Mock()
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [],
        }
        requirements = image_registry_module.docker_registry(config, [machine])
        self.assertEqual(requirements, [])
        machine.process.assert_not_called()

    def test_wrong_text_translation_cache_identity_refreshes_each_pinned_source(self):
        wrong_digest = "sha256:%s" % ("0" * 64)
        for source_ref, local_name, expected_digest in self._text_translation_digest_requirements():
            with self.subTest(source_ref=source_ref):
                machine = self._local_registry_machine(
                    local_name,
                    [
                        self._manifest_payload(wrong_digest),
                        self._manifest_payload(expected_digest),
                    ],
                )
                config = {
                    "registry": "127.0.0.1:5000",
                    "domains": {"run": {"targets": ["application"], "image_prefetch": "off"}},
                    "prefetch_image_requirements": [
                        self._digest_requirement(source_ref, local_name)
                    ],
                }

                image_registry_module.docker_registry(config, [machine])

                commands = [call.args[1] for call in machine.process.call_args_list]
                self.assertIn(["docker", "pull", source_ref], commands)
                manifest_commands = [
                    command for command in commands if "/manifests/latest" in command[-1]
                ]
                self.assertEqual(len(manifest_commands), 2)

    def test_matching_digest_cache_identity_reuses_oci_and_docker_manifests(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        media_types = (
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        )
        for media_type in media_types:
            with self.subTest(media_type=media_type):
                machine = self._local_registry_machine(
                    local_name,
                    [self._manifest_payload(expected_digest, media_type=media_type)],
                )
                config = {
                    "registry": "127.0.0.1:5000",
                    "domains": {"run": {"targets": ["application"], "image_prefetch": "off"}},
                    "prefetch_image_requirements": [
                        self._digest_requirement(source_ref, local_name)
                    ],
                }

                image_registry_module.docker_registry(config, [machine])

                commands = [call.args[1] for call in machine.process.call_args_list]
                self.assertFalse(any(command[0] == "docker" for command in commands))
                manifest_command = next(
                    command for command in commands if "/manifests/latest" in command[-1]
                )
                self.assertEqual(
                    manifest_command[:5], ["curl", "-fsS", "-I", "-H", mock.ANY]
                )
                immutable_ref = config["verified_runtime_image_refs"][local_name]
                self.assertEqual(
                    immutable_ref,
                    "127.0.0.1:5000/%s@sha256:%s"
                    % (local_name, "b" * 64),
                )

    def test_incomplete_digest_cache_manifests_are_missing(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        missing_field = object()
        valid_manifest = self._manifest_payload(expected_digest)
        valid_manifest_with_layer = copy.deepcopy(valid_manifest)
        valid_manifest_with_layer["layers"] = [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": "sha256:%s" % ("1" * 64),
                "size": 1,
            }
        ]

        def changed(base, path, value):
            payload = copy.deepcopy(base)
            target = payload
            for key in path[:-1]:
                target = target[key]
            if value is missing_field:
                target.pop(path[-1])
            else:
                target[path[-1]] = value
            return payload

        cases = {
            "missing-response": None,
            "malformed-json": "not-json",
            "index": {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [],
            },
            "schema-version-missing": changed(
                valid_manifest, ("schemaVersion",), missing_field
            ),
            "schema-version-wrong-value": changed(valid_manifest, ("schemaVersion",), 3),
            "schema-version-boolean": changed(valid_manifest, ("schemaVersion",), True),
            "schema-version-float": changed(valid_manifest, ("schemaVersion",), 2.0),
            "schema-version-string": changed(valid_manifest, ("schemaVersion",), "2"),
            "config-missing": changed(valid_manifest, ("config",), missing_field),
            "config-not-mapping": changed(valid_manifest, ("config",), []),
            "config-media-type-missing": changed(
                valid_manifest, ("config", "mediaType"), missing_field
            ),
            "config-media-type-empty": changed(valid_manifest, ("config", "mediaType"), ""),
            "config-media-type-whitespace": changed(
                valid_manifest, ("config", "mediaType"), " \t"
            ),
            "config-media-type-wrong-type": changed(
                valid_manifest, ("config", "mediaType"), 1
            ),
            "config-media-type-wrong-family": changed(
                valid_manifest,
                ("config", "mediaType"),
                "application/vnd.docker.container.image.v1+json",
            ),
            "config-digest-missing": changed(
                valid_manifest, ("config", "digest"), missing_field
            ),
            "config-digest-empty": changed(valid_manifest, ("config", "digest"), ""),
            "config-digest-whitespace": changed(
                valid_manifest, ("config", "digest"), " \t"
            ),
            "config-digest-wrong-type": changed(valid_manifest, ("config", "digest"), 1),
            "malformed-config-digest": self._manifest_payload("sha256:not-a-digest"),
            "config-size-missing": changed(
                valid_manifest, ("config", "size"), missing_field
            ),
            "config-size-negative": changed(valid_manifest, ("config", "size"), -1),
            "config-size-boolean": changed(valid_manifest, ("config", "size"), True),
            "config-size-float": changed(valid_manifest, ("config", "size"), 1.0),
            "config-size-string": changed(valid_manifest, ("config", "size"), "1"),
            "layers-missing": changed(valid_manifest, ("layers",), missing_field),
            "layers-null": changed(valid_manifest, ("layers",), None),
            "layers-mapping": changed(valid_manifest, ("layers",), {}),
            "layers-scalar": changed(valid_manifest, ("layers",), 1),
            "layer-not-mapping": changed(valid_manifest, ("layers",), [None]),
            "layer-media-type-missing": changed(
                valid_manifest_with_layer,
                ("layers", 0, "mediaType"),
                missing_field,
            ),
            "layer-media-type-empty": changed(
                valid_manifest_with_layer, ("layers", 0, "mediaType"), ""
            ),
            "layer-media-type-whitespace": changed(
                valid_manifest_with_layer, ("layers", 0, "mediaType"), " \t"
            ),
            "layer-media-type-wrong-type": changed(
                valid_manifest_with_layer, ("layers", 0, "mediaType"), 1
            ),
            "layer-media-type-wrong-family": changed(
                valid_manifest_with_layer,
                ("layers", 0, "mediaType"),
                "application/vnd.docker.image.rootfs.diff.tar.gzip",
            ),
            "layer-media-type-unknown": changed(
                valid_manifest_with_layer,
                ("layers", 0, "mediaType"),
                "application/vnd.example.layer",
            ),
            "layer-digest-missing": changed(
                valid_manifest_with_layer,
                ("layers", 0, "digest"),
                missing_field,
            ),
            "layer-digest-empty": changed(
                valid_manifest_with_layer, ("layers", 0, "digest"), ""
            ),
            "layer-digest-whitespace": changed(
                valid_manifest_with_layer, ("layers", 0, "digest"), " \t"
            ),
            "layer-digest-wrong-type": changed(
                valid_manifest_with_layer, ("layers", 0, "digest"), 1
            ),
            "layer-size-missing": changed(
                valid_manifest_with_layer, ("layers", 0, "size"), missing_field
            ),
            "layer-size-negative": changed(
                valid_manifest_with_layer, ("layers", 0, "size"), -1
            ),
            "layer-size-boolean": changed(
                valid_manifest_with_layer, ("layers", 0, "size"), True
            ),
            "layer-size-float": changed(
                valid_manifest_with_layer, ("layers", 0, "size"), 1.0
            ),
            "layer-size-string": changed(
                valid_manifest_with_layer, ("layers", 0, "size"), "1"
            ),
        }
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["application"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }
        for label, response in cases.items():
            with self.subTest(case=label):
                machine = self._local_registry_machine(local_name, [response])
                missing = image_registry_module.missing_cached_requirements(config, [machine])
                self.assertEqual(missing, config["prefetch_image_requirements"])
        self.assertEqual(
            image_requirements.expected_local_config_digest(source_ref), expected_digest
        )

    def test_manifest_descriptor_media_type_families_are_accepted(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        families = {
            "application/vnd.oci.image.manifest.v1+json": (
                "application/vnd.oci.image.config.v1+json",
                (
                    "application/vnd.oci.image.layer.v1.tar",
                    "application/vnd.oci.image.layer.v1.tar+gzip",
                    "application/vnd.oci.image.layer.v1.tar+zstd",
                    "application/vnd.oci.image.layer.nondistributable.v1.tar",
                    "application/vnd.oci.image.layer.nondistributable.v1.tar+gzip",
                    "application/vnd.oci.image.layer.nondistributable.v1.tar+zstd",
                ),
            ),
            "application/vnd.docker.distribution.manifest.v2+json": (
                "application/vnd.docker.container.image.v1+json",
                (
                    "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip",
                ),
            ),
        }
        for manifest_type, (config_type, layer_types) in families.items():
            for layer_type in layer_types:
                with self.subTest(manifest_type=manifest_type, layer_type=layer_type):
                    manifest = self._manifest_payload(expected_digest, manifest_type)
                    manifest["config"]["mediaType"] = config_type
                    manifest["layers"] = [
                        {
                            "mediaType": layer_type,
                            "digest": "sha256:%s" % ("1" * 64),
                            "size": 1,
                        }
                    ]
                    machine = self._local_registry_machine(local_name, [manifest])
                    config = {
                        "registry": "127.0.0.1:5000",
                        "prefetch_image_requirements": [
                            self._digest_requirement(source_ref, local_name)
                        ],
                    }

                    self.assertEqual(
                        image_registry_module.missing_cached_requirements(config, [machine]),
                        [],
                    )

    def test_manifest_head_requires_one_valid_content_digest(self):
        source_ref, local_name, _expected_digest = self._text_translation_digest_requirements()[0]
        valid_digest = "sha256:%s" % ("b" * 64)
        cases = {
            "missing": [],
            "wrong-header": ["Content-Digest: %s" % valid_digest],
            "invalid": ["Docker-Content-Digest: sha256:not-a-digest"],
            "duplicate": [
                "Docker-Content-Digest: %s" % valid_digest,
                "docker-content-digest: %s" % valid_digest,
            ],
            "conflicting": [
                "Docker-Content-Digest: %s" % valid_digest,
                "Docker-Content-Digest: sha256:%s" % ("c" * 64),
            ],
        }
        for label, headers in cases.items():
            with self.subTest(case=label):
                machine = mock.Mock()
                machine.process.side_effect = [
                    self._process_result([json.dumps({"repositories": [local_name]})]),
                    self._process_result(
                        [json.dumps({"name": local_name, "tags": ["latest"]})]
                    ),
                    self._process_result(headers),
                ]
                config = {
                    "registry": "127.0.0.1:5000",
                    "prefetch_image_requirements": [
                        self._digest_requirement(source_ref, local_name)
                    ],
                }

                missing = image_registry_module.missing_cached_requirements(config, [machine])

                self.assertEqual(missing, config["prefetch_image_requirements"])
                self.assertEqual(len(machine.process.call_args_list), 3)

    def test_empty_layers_list_remains_a_valid_digest_cache_hit(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        manifest = self._manifest_payload(expected_digest)
        self.assertEqual(manifest["layers"], [])
        machine = self._local_registry_machine(local_name, [manifest])
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["application"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }

        missing = image_registry_module.missing_cached_requirements(config, [machine])

        self.assertEqual(missing, [])

    def test_refreshed_digest_identity_is_verified_and_failure_is_closed(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        wrong_digest = "sha256:%s" % ("0" * 64)
        incomplete_matching_manifest = self._manifest_payload(expected_digest)
        incomplete_matching_manifest["config"].pop("size")
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["application"], "image_prefetch": "on"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }
        responses = {
            "wrong-digest": self._manifest_payload(wrong_digest),
            "incomplete-matching-manifest": incomplete_matching_manifest,
        }
        for label, response in responses.items():
            with self.subTest(case=label):
                machine = self._local_registry_machine(local_name, [response])

                with self.assertRaises(SystemExit):
                    image_registry_module.docker_registry(config, [machine])

                commands = [call.args[1] for call in machine.process.call_args_list]
                self.assertIn(["docker", "pull", source_ref], commands)
                self.assertTrue(any("/manifests/latest" in command[-1] for command in commands))

    def test_unknown_digest_pinned_source_is_refreshed_without_tag_cache_acceptance(self):
        source_ref = "registry.example/future@sha256:%s" % ("a" * 64)
        local_name = "future:latest"
        machine = self._local_registry_machine(local_name.split(":", 1)[0], [])
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }

        image_registry_module.docker_registry(config, [machine])

        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertIn(["docker", "pull", source_ref], commands)
        self.assertFalse(any("/tags/list" in command[-1] for command in commands))
        self.assertFalse(any("/manifests/" in command[-1] for command in commands))

    def test_malformed_expected_config_digest_fails_clearly(self):
        source_ref, local_name, _expected_digest = self._text_translation_digest_requirements()[0]
        machine = self._local_registry_machine(local_name, [])
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["application"], "image_prefetch": "on"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }
        with mock.patch.dict(
            image_requirements._LOCAL_IMAGE_CONFIG_DIGEST_BY_SOURCE,
            {source_ref: "not-a-digest"},
        ):
            with self.assertRaisesRegex(ValueError, "Invalid expected local image-config digest"):
                image_registry_module.docker_registry(config, [machine])
        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertFalse(any(command[0] == "docker" for command in commands))

    def test_missing_and_registry_refresh_share_digest_cache_validity(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        wrong_digest = "sha256:%s" % ("0" * 64)
        cases = {
            "correct": self._manifest_payload(expected_digest),
            "incorrect": self._manifest_payload(wrong_digest),
            "unverifiable": {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [],
            },
        }
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["application"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [self._digest_requirement(source_ref, local_name)],
        }
        for label, cached_response in cases.items():
            with self.subTest(case=label):
                missing_machine = self._local_registry_machine(local_name, [cached_response])
                missing = image_registry_module.missing_cached_requirements(
                    config, [missing_machine]
                )

                refresh_responses = [cached_response]
                if label != "correct":
                    refresh_responses.append(self._manifest_payload(expected_digest))
                registry_machine = self._local_registry_machine(local_name, refresh_responses)
                image_registry_module.docker_registry(config, [registry_machine])
                commands = [call.args[1] for call in registry_machine.process.call_args_list]
                pulled = ["docker", "pull", source_ref] in commands

                self.assertEqual(bool(missing), pulled)

    def test_docker_registry_mode_off_pulls_only_missing(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(['{"repositories":["cached-repo"]}']),
            self._process_result(['{"name":"cached-repo","tags":["latest"]}']),
            self._process_result(["pull-ok"]),
            self._process_result(["tag-ok"]),
            self._process_result(["push-ok"]),
        ]
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/cached-repo:latest",
                    "local_name": "cached-repo:latest",
                    "owners": ["software.module:a"],
                    "tier_targets": ["cloud"],
                },
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                },
            ],
        }
        image_registry_module.docker_registry(config, [machine])

        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertIn(["curl", "-fsS", "127.0.0.1:5000/v2/_catalog"], commands)
        self.assertIn(["curl", "-fsS", "127.0.0.1:5000/v2/cached-repo/tags/list"], commands)
        self.assertIn(["docker", "pull", "registry.example/missing-repo:latest"], commands)
        self.assertNotIn(["docker", "pull", "registry.example/cached-repo:latest"], commands)

    def test_docker_registry_mode_off_pulls_when_required_tag_missing(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(['{"repositories":["cached-repo"]}']),
            self._process_result(['{"name":"cached-repo","tags":["v1"]}']),
            self._process_result(["pull-ok"]),
            self._process_result(["tag-ok"]),
            self._process_result(["push-ok"]),
        ]
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/cached-repo:latest",
                    "local_name": "cached-repo:latest",
                    "owners": ["software.module:a"],
                    "tier_targets": ["cloud"],
                }
            ],
        }
        image_registry_module.docker_registry(config, [machine])

        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertIn(["docker", "pull", "registry.example/cached-repo:latest"], commands)

    def test_docker_registry_mode_on_forces_pull(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(['{"repositories":["cached-repo","missing-repo"]}']),
            self._process_result(["pull-a"]),
            self._process_result(["tag-a"]),
            self._process_result(["push-a"]),
            self._process_result(["pull-b"]),
            self._process_result(["tag-b"]),
            self._process_result(["push-b"]),
        ]
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "on"}},
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/cached-repo:latest",
                    "local_name": "cached-repo:latest",
                    "owners": ["software.module:a"],
                    "tier_targets": ["cloud"],
                },
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                },
            ],
        }
        image_registry_module.docker_registry(config, [machine])

        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertIn(["docker", "pull", "registry.example/cached-repo:latest"], commands)
        self.assertIn(["docker", "pull", "registry.example/missing-repo:latest"], commands)

    def test_missing_cached_requirements_reports_unreachable_registry(self):
        machine = mock.Mock()
        machine.process.return_value = self._process_result(
            [],
            ["curl: (7) Failed to connect to 127.0.0.1 port 5000"],
        )
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:a"],
                    "tier_targets": ["cloud"],
                },
            ],
        }

        missing = image_registry_module.missing_cached_requirements(config, [machine])

        self.assertEqual(
            [requirement["source_ref"] for requirement in missing],
            ["registry.example/missing-repo:latest"],
        )

    def test_missing_cached_requirements_reports_only_missing_tags(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(['{"repositories":["cached-repo","missing-tag"]}']),
            self._process_result(['{"name":"cached-repo","tags":["latest"]}']),
            self._process_result(['{"name":"missing-tag","tags":["v1"]}']),
        ]
        config = {
            "registry": "127.0.0.1:5000",
            "domains": {"run": {"targets": ["software"], "image_prefetch": "off"}},
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/cached-repo:latest",
                    "local_name": "cached-repo:latest",
                    "owners": ["software.module:a"],
                    "tier_targets": ["cloud"],
                },
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                },
                {
                    "source_ref": "registry.example/missing-tag:latest",
                    "local_name": "missing-tag:latest",
                    "owners": ["software.module:c"],
                    "tier_targets": ["cloud"],
                },
            ],
        }

        missing = image_registry_module.missing_cached_requirements(config, [machine])

        self.assertEqual(
            [requirement["source_ref"] for requirement in missing],
            [
                "registry.example/missing-repo:latest",
                "registry.example/missing-tag:latest",
            ],
        )

    def test_set_remote_registry_endpoint_uses_cloud_internal_ip(self):
        machine = mock.Mock()
        machine.cloud_controller_ips_internal = ["10.0.0.10"]
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
        }

        image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

        self.assertEqual(config["old_registry"], "127.0.0.1:5000")
        self.assertEqual(config["registry"], "10.0.0.10:5000")

    def test_set_remote_registry_endpoint_control_mode_uses_public_registry(self):
        machine = mock.Mock()
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
        }

        image_registry_module.set_remote_registry_endpoint(config, [machine], control=True)

        self.assertEqual(config["old_registry"], "127.0.0.1:5000")
        self.assertEqual(config["registry"], "docker.io/redplanet00")

    def test_set_remote_registry_endpoint_uses_edge_internal_ip(self):
        machine = mock.Mock()
        machine.edge_ips_internal = ["10.0.1.20"]
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 0, "edge_nodes": 1, "endpoint_nodes": 0},
        }

        image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

        self.assertEqual(config["old_registry"], "127.0.0.1:5000")
        self.assertEqual(config["registry"], "10.0.1.20:5000")

    def test_set_remote_registry_endpoint_uses_endpoint_internal_ip(self):
        machine = mock.Mock()
        machine.endpoint_ips_internal = ["10.0.2.30"]
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 0, "edge_nodes": 0, "endpoint_nodes": 1},
        }

        image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

        self.assertEqual(config["old_registry"], "127.0.0.1:5000")
        self.assertEqual(config["registry"], "10.0.2.30:5000")

    def test_set_remote_registry_endpoint_missing_cloud_ip_fails_fast(self):
        machine = mock.Mock()
        machine.cloud_controller_ips_internal = []
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
        }
        with self.assertRaises(SystemExit):
            image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

    def test_set_remote_registry_endpoint_missing_edge_ip_fails_fast(self):
        machine = mock.Mock()
        machine.edge_ips_internal = []
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 0, "edge_nodes": 1, "endpoint_nodes": 0},
        }
        with self.assertRaises(SystemExit):
            image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

    def test_set_remote_registry_endpoint_missing_endpoint_ip_fails_fast(self):
        machine = mock.Mock()
        machine.endpoint_ips_internal = []
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 0, "edge_nodes": 0, "endpoint_nodes": 1},
        }
        with self.assertRaises(SystemExit):
            image_registry_module.set_remote_registry_endpoint(config, [machine], control=False)

    def test_set_remote_registry_endpoint_no_machines_fails_fast(self):
        config = {
            "registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
        }
        with self.assertRaises(SystemExit):
            image_registry_module.set_remote_registry_endpoint(config, [], control=False)

    def test_move_prefetched_images_to_remote_registry_skips_without_requirements(self):
        machine = mock.Mock()
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [],
        }

        image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])
        machine.process.assert_not_called()

    def test_move_prefetched_images_to_remote_registry_migrates_images(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result(["pull-ok"]),
            self._process_result(["save-ok"]),
            self._process_result([], []),
            self._process_result(["load-ok"]),
            self._process_result(["tag-ok"]),
            self._process_result(["push-ok"]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

        first_call = machine.process.call_args_list[0]
        self.assertEqual(first_call.kwargs.get("ssh"), "cloud0@198.51.100.1")
        self.assertEqual(first_call.args[1][:3], ["docker", "run", "-d"])

        commands = [call.args[1] for call in machine.process.call_args_list]
        self.assertIn(["docker", "pull", "127.0.0.1:5000/missing-repo:latest"], commands)
        self.assertIn(["docker", "push", "10.0.0.10:5000/missing-repo:latest"], commands)

    def test_remote_migration_reverifies_pinned_identity_over_ssh(self):
        source_ref, local_name, expected_digest = self._text_translation_digest_requirements()[0]
        manifest_digest = "sha256:%s" % ("d" * 64)
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result(["pull-ok"]),
            self._process_result(["save-ok"]),
            self._process_result([], []),
            self._process_result(["load-ok"]),
            self._process_result(["tag-ok"]),
            self._process_result(["push-ok"]),
            self._process_result(["Docker-Content-Digest: %s" % manifest_digest]),
            self._process_result([json.dumps(self._manifest_payload(expected_digest))]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                self._digest_requirement(source_ref, local_name)
            ],
            "verified_runtime_image_refs": {
                local_name: "127.0.0.1:5000/%s@sha256:%s" % (local_name, "b" * 64)
            },
        }

        image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

        head_call, get_call = machine.process.call_args_list[-2:]
        self.assertIn("-I", head_call.args[1])
        self.assertTrue(get_call.args[1][-1].endswith("/manifests/%s" % manifest_digest))
        self.assertEqual(head_call.kwargs["ssh"], "cloud0@198.51.100.1")
        self.assertEqual(get_call.kwargs["ssh"], "cloud0@198.51.100.1")
        self.assertEqual(
            config["verified_runtime_image_refs"][local_name],
            "10.0.0.10:5000/%s@%s" % (local_name, manifest_digest),
        )

    def test_move_prefetched_images_to_remote_registry_requires_old_registry(self):
        machine = mock.Mock()
        config = {
            "registry": "10.0.0.10:5000",
            "infrastructure": {"cloud_nodes": 1, "edge_nodes": 0, "endpoint_nodes": 0},
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

        machine.process.assert_not_called()

    def test_move_prefetched_images_to_remote_registry_fails_fast_on_pull_error(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result([], ["pull failed"]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

    def test_move_prefetched_images_to_remote_registry_missing_ssh_target_fails_fast(self):
        machine = mock.Mock()
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": [],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

        machine.process.assert_not_called()

    def test_move_prefetched_images_to_remote_registry_fails_fast_on_save_error(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result(["pull-ok"]),
            self._process_result([], ["save failed"]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

    def test_move_prefetched_images_to_remote_registry_fails_fast_on_load_error(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result(["pull-ok"]),
            self._process_result(["save-ok"]),
            self._process_result([], []),
            self._process_result([], ["load failed"]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])

    def test_move_prefetched_images_to_remote_registry_fails_fast_on_push_error(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            self._process_result(["registry-started"]),
            self._process_result(["pull-ok"]),
            self._process_result(["save-ok"]),
            self._process_result([], []),
            self._process_result(["load-ok"]),
            self._process_result(["tag-ok"]),
            self._process_result([], ["push failed"]),
        ]
        config = {
            "registry": "10.0.0.10:5000",
            "old_registry": "127.0.0.1:5000",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp",
            },
            "cloud_ssh": ["cloud0@198.51.100.1"],
            "edge_ssh": [],
            "endpoint_ssh": [],
            "prefetch_image_requirements": [
                {
                    "source_ref": "registry.example/missing-repo:latest",
                    "local_name": "missing-repo:latest",
                    "owners": ["software.module:b"],
                    "tier_targets": ["cloud"],
                }
            ],
        }

        with self.assertRaises(SystemExit):
            image_registry_module.move_prefetched_images_to_remote_registry(config, [machine])


class ResumeStateTests(unittest.TestCase):
    def _resume_config(self, base_path):
        module = {
            "id": "none-main",
            "type": "none",
            "assign_to": {"match": {"cluster": "cloud-1"}},
            "config": {},
            "selector_id": "sel_none_main",
            "resolved_vm_ids": [1],
            "scope_identities": [{"kind": "selector", "selector_id": "sel_none_main"}],
        }
        resource = {
            "vm_id": 1,
            "cluster_id": "cloud-1",
            "tier": "cloud",
            "index_in_cluster": 0,
            "tags": {"tier": "cloud", "cluster": "cloud-1"},
        }
        cluster = {
            "id": "cloud-1",
            "tier": "cloud",
            "resources": {"vms": {"count": 1, "spec": {"cores": 1}}},
        }
        run = {
            "targets": ["infrastructure", "software"],
            "dry_run": False,
            "clean": False,
            "image_prefetch": "off",
            "prepare_for_resume": False,
        }
        provider = {
            "name": "qemu",
            "config": {
                "base_path": base_path,
                "cpu_pin": False,
                "external_physical_machines": [],
                "ip": {"prefix": "192.168", "middle": 100, "middle_base": 90},
                "netperf": False,
                "delete_on_exit": False,
            },
        }
        network = {"emulation": False, "wireless_preset": "4g", "overrides": {}}
        return {
            "config_format": "yaml",
            "ssh_key": "/tmp/id_rsa",
            "infrastructure": {
                "provider": "qemu",
                "base_path": base_path,
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
            },
            "domains": {
                "run": run,
                "provider": provider,
                "software": {"modules": [module]},
                "infrastructure": {
                    "clusters": [cluster],
                    "network": network,
                    "resources": [resource],
                },
                "benchmark": {},
            },
            "normalized": {
                "schema_version": 1,
                "kind": "ContinuumNormalizedConfig",
                "run": run,
                "provider": provider,
                "software": {"modules": [module]},
                "infrastructure": {
                    "clusters": [cluster],
                    "network": network,
                    "resources": [resource],
                },
            },
            "planner_snapshot": {
                "software_execution_order": [],
                "software_plan_entries": [],
                "software_module_assignments": [
                    {
                        "id": "none-main",
                        "type": "none",
                        "selector_id": "sel_none_main",
                        "resolved_vm_ids": [1],
                        "resolved_resources": [resource],
                        "scope_identities": [
                            {"kind": "selector", "selector_id": "sel_none_main"}
                        ],
                    }
                ],
                "benchmark_stage_assignments": [],
            },
        }

    def test_save_state_writes_schema_v2_atomically(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._resume_config(tempdir)
            machine = Machine("local", True)

            state_path = infra_state.save_state(config, "infrastructure", [machine])

            self.assertEqual(state_path, str(pathlib.Path(tempdir) / ".continuum" / "state.json"))
            with open(state_path, "r", encoding="utf-8") as filep:
                payload = json.load(filep)

            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["kind"], "ContinuumState")
            self.assertEqual(payload["phase_completed"], "infrastructure")
            self.assertTrue(payload["resume_contract"]["hash"].startswith("sha256:"))
            self.assertFalse(list((pathlib.Path(tempdir) / ".continuum").glob(".state.*.tmp")))

    def test_load_resume_state_rejects_legacy_state_without_schema(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._resume_config(tempdir)
            state_dir = pathlib.Path(tempdir) / ".continuum"
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text(
                json.dumps({"phase_completed": "infrastructure"}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as exc:
                infra_state.load_resume_state(config, "infrastructure")

            self.assertIn("State schema mismatch", str(exc.exception))

    def test_load_resume_state_rejects_contract_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._resume_config(tempdir)
            machine = Machine("local", True)
            infra_state.save_state(config, "infrastructure", [machine])

            config["normalized"]["provider"]["config"]["ip"]["middle"] = 101

            with self.assertRaises(ValueError) as exc:
                infra_state.load_resume_state(config, "infrastructure")

            self.assertIn("Resume contract mismatch", str(exc.exception))

    @mock.patch("infrastructure.state.machine_utils.gather_ips")
    @mock.patch("infrastructure.state.machine_utils.gather_ssh")
    @mock.patch("infrastructure.state.validate_state_compatibility")
    @mock.patch("infrastructure.state.load_and_reconstruct")
    @mock.patch("infrastructure.state.state_file_path")
    def test_load_resume_state_success(
        self,
        mock_state_path,
        mock_load_and_reconstruct,
        mock_validate,
        mock_gather_ssh,
        mock_gather_ips,
    ):
        state_payload = {"phase_completed": "software", "ssh_key": "/tmp/id_rsa_state"}
        machines = [object()]
        config = {}

        mock_state_path.return_value = "/tmp/state.json"
        mock_load_and_reconstruct.return_value = (state_payload, machines)
        mock_validate.return_value = []

        loaded_state, loaded_machines = infra_state.load_resume_state(config, "software")

        self.assertEqual(loaded_state, state_payload)
        self.assertEqual(loaded_machines, machines)
        self.assertEqual(config["ssh_key"], "/tmp/id_rsa_state")
        mock_gather_ssh.assert_called_once_with(config, machines)
        mock_gather_ips.assert_called_once_with(config, machines)

    @mock.patch("infrastructure.state.validate_state_compatibility")
    @mock.patch("infrastructure.state.load_and_reconstruct")
    @mock.patch("infrastructure.state.state_file_path")
    def test_load_resume_state_fails_when_phase_too_early(
        self,
        mock_state_path,
        mock_load_and_reconstruct,
        mock_validate,
    ):
        state_payload = {"phase_completed": "infrastructure"}
        machines = [object()]

        mock_state_path.return_value = "/tmp/state.json"
        mock_load_and_reconstruct.return_value = (state_payload, machines)
        mock_validate.return_value = []

        with self.assertRaises(ValueError):
            infra_state.load_resume_state({}, "software")


class AddonCompatibilityTests(unittest.TestCase):
    def _compat_error(self, config):
        parser = argparse.ArgumentParser(prog="addon-compat-test")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                runtime_option_validation.verify_addon_compatibility(parser, config)
        return stderr.getvalue()

    def test_endpoint_nodes_require_endpoint_runtime_capability(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
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
            "infrastructure": {"endpoint_nodes": 1},
        }
        stderr = self._compat_error(config)
        self.assertIn("Endpoint nodes require a software addon with endpoint-runtime capability", stderr)

    def test_endpoint_runtime_must_target_endpoint_resources(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                            "resolved_vm_ids": [1],
                        },
                        {
                            "id": "endpoint-runtime-main",
                            "type": "endpoint_runtime",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                            "resolved_vm_ids": [1],
                        },
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 1},
            "normalized": {
                "infrastructure": {
                    "resources": [
                        {
                            "vm_id": 1,
                            "cluster_id": "cloud-1",
                            "tier": "cloud",
                            "index_in_cluster": 0,
                            "tags": {"tier": "cloud", "cluster": "cloud-1"},
                        },
                        {
                            "vm_id": 2,
                            "cluster_id": "endpoint-1",
                            "tier": "endpoint",
                            "index_in_cluster": 0,
                            "tags": {"tier": "endpoint", "cluster": "endpoint-1"},
                        },
                    ]
                }
            },
        }
        stderr = self._compat_error(config)
        self.assertIn(
            "Endpoint runtime module endpoint-runtime-main (type=endpoint_runtime) "
            "must be assigned to endpoint resources",
            stderr,
        )

    def test_openfaas_requires_kubernetes_orchestrator(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "kubeedge-main",
                            "type": "kubeedge",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                        {
                            "id": "openfaas-main",
                            "type": "openfaas",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 0},
        }
        stderr = self._compat_error(config)
        self.assertIn("OpenFaaS addon requires orchestrator Kubernetes", stderr)

    def test_observability_requires_supported_orchestrator_capability(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "kubeedge-main",
                            "type": "kubeedge",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                        {
                            "id": "obs-main",
                            "type": "observability",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 0},
        }
        stderr = self._compat_error(config)
        self.assertIn("Observability addon requires orchestrator observability support", stderr)

    def test_exclusive_capability_collision_is_rejected(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                        {
                            "id": "kubeedge-main",
                            "type": "kubeedge",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 0},
        }
        stderr = self._compat_error(config)
        self.assertIn("capability slot.orchestrator is exclusive", stderr)
        self.assertIn("kubeedge-main", stderr)

    def test_conflict_capability_is_rejected(self):
        config = {
            "domains": {
                "run": {"targets": ["software"]},
                "software": {
                    "modules": [
                        {
                            "id": "k8s-main",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                        {
                            "id": "endpoint-runtime",
                            "type": "endpoint_runtime",
                            "assign_to": {"match": {"cluster": "endpoint-1"}},
                            "config": {},
                        },
                        {
                            "id": "obs-main",
                            "type": "observability",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        },
                    ]
                },
            },
            "infrastructure": {"endpoint_nodes": 0},
        }

        original_get_spec = module_registry.get_spec

        def patched_get_spec(module_type):
            if module_type == "endpoint_runtime":
                return module_registry.ModuleSpec(
                    scope="addon",
                    conflicts=("capability.synthetic",),
                )
            if module_type == "observability":
                return module_registry.ModuleSpec(
                    scope="addon",
                    provides=("capability.synthetic",),
                )
            return original_get_spec(module_type)

        with mock.patch(
            "input.configuration.module_registry.get_spec",
            side_effect=patched_get_spec,
        ):
            stderr = self._compat_error(config)

        self.assertIn(
            "Module endpoint-runtime (type=endpoint_runtime) conflicts with module obs-main "
            "via capability capability.synthetic",
            stderr,
        )


class QemuMachinePlaybookEnvTests(unittest.TestCase):
    def test_machine_playbook_env_disables_ansible_become(self):
        self.assertEqual(qemu_module._machine_playbook_env(), {"ANSIBLE_BECOME": "False"})

    def test_ansible_runner_uses_base_path_local_tmp(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            config = {
                "base": tempdir,
                "infrastructure": {"base_path": tempdir},
                "username": "continuum-smoke",
            }

            with mock.patch.dict("os.environ", {}, clear=False):
                runner = infrastructure_ansible.AnsibleRunner(config, [machine])
                self.assertEqual(os.environ["ANSIBLE_LOCAL_TEMP"], runner.ansible_local_tmp)
                self.assertEqual(os.environ["ANSIBLE_REMOTE_TMP"], runner.ansible_remote_tmp)

            self.assertEqual(
                runner.ansible_local_tmp,
                str(pathlib.Path(tempdir) / ".continuum" / "ansible" / "tmp"),
            )
            self.assertEqual(runner.ansible_remote_tmp, "~/.continuum-ansible-continuum-smoke/tmp")
            self.assertTrue(pathlib.Path(runner.ansible_local_tmp).is_dir())

    def test_ansible_runner_merges_default_env_with_call_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            machine.process.return_value = [([], [])]
            config = {
                "base": tempdir,
                "infrastructure": {"base_path": tempdir},
                "username": "continuum-smoke",
            }
            runner = infrastructure_ansible.AnsibleRunner(config, [machine])

            runner.run_playbook("playbooks/resource_manager/k8s_cluster.yml", env={"ANSIBLE_BECOME": "False"})

            passed_env = machine.process.call_args.kwargs["env"]
            self.assertEqual(passed_env["ANSIBLE_CONFIG"], runner.ansible_config)
            self.assertEqual(passed_env["ANSIBLE_LOCAL_TEMP"], runner.ansible_local_tmp)
            self.assertEqual(passed_env["ANSIBLE_REMOTE_TMP"], runner.ansible_remote_tmp)
            self.assertEqual(passed_env["ANSIBLE_BECOME"], "False")

    def test_ansible_runner_prefers_interpreter_local_ansible_playbook(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            config = {
                "base": tempdir,
                "infrastructure": {"base_path": tempdir},
            }
            fake_bin = pathlib.Path(tempdir) / "bin"
            fake_bin.mkdir()
            fake_playbook = fake_bin / "ansible-playbook"
            fake_playbook.write_text("#!/bin/sh\n", encoding="utf-8")
            fake_playbook.chmod(0o755)

            with mock.patch("infrastructure.ansible.sys.executable", str(fake_bin / "python3")):
                runner = infrastructure_ansible.AnsibleRunner(config, [machine])

            self.assertEqual(runner.ansible_playbook_bin, str(fake_playbook))

    def test_os_image_runs_machine_playbook_without_become(self):
        machine = mock.Mock()
        machine.name = "local"
        machine.process.return_value = [([], ["missing image"])]
        runner = mock.Mock()
        config = {"infrastructure": {"base_path": "/tmp/continuum"}}

        qemu_module.os_image(config, [machine], runner=runner)

        runner.run_playbook.assert_called_once_with(
            "playbooks/infrastructure/qemu_prepare_os.yml",
            inventory="machine",
            env={"ANSIBLE_BECOME": "False"},
        )

    def test_start_vms_uses_machine_playbooks_without_become(self):
        runner = mock.Mock()
        runner.run_playbook.return_value = ([], [])
        config = {
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 0,
                "base_path": "/tmp/continuum",
            }
        }
        machine = mock.Mock()
        machine.cloud_controller_names = []
        machine.cloud_names = ["cloud0"]
        machine.edge_names = []
        machine.endpoint_names = []
        machine.base_names = ["base_cloud_kubernetes0"]
        machine.cloud_controller = 0
        machine.clouds = 1
        machine.edges = 0
        machine.endpoints = 0
        machines = [machine]

        with mock.patch.object(qemu_module, "os_image"), mock.patch.object(
            qemu_module, "base_image"
        ), mock.patch.object(qemu_module, "launch_vms", return_value=[]):
            qemu_module.start_vms(config, machines, runner=runner)

        self.assertEqual(
            runner.run_playbook.call_args_list[0],
            mock.call(
                "playbooks/infrastructure/qemu_cleanup.yml",
                inventory="machine",
                env={"ANSIBLE_BECOME": "False"},
            ),
        )
        self.assertEqual(
            runner.run_playbook.call_args_list[1],
            mock.call(
                "playbooks/infrastructure/qemu_create_vms.yml",
                inventory="machine",
                extra_vars=mock.ANY,
                env={"ANSIBLE_BECOME": "False"},
            ),
        )


class QemuBaseImageMetadataTests(unittest.TestCase):
    RAW_BASE_NAME = "base_cloud_none_np1_mm0_0_continuum-smoke"

    @staticmethod
    def _protocol(payload):
        response = dict(payload)
        response["protocol"] = qemu_module._CACHE_PROTOCOL
        return [([json.dumps(response, sort_keys=True)], [])]

    @classmethod
    def _config(cls, base_path):
        return {
            "base": str(pathlib.Path(__file__).parents[3]),
            "home": base_path,
            "mode": "cloud",
            "module": {},
            "prefetch_image_requirements": [],
            "infrastructure": {
                "base_path": base_path,
                "wireless_network_preset": "",
            },
        }

    @classmethod
    def _machine(cls, is_local=True, raw_base_name=None):
        raw_base_name = raw_base_name or cls.RAW_BASE_NAME
        machine = mock.Mock()
        machine.is_local = is_local
        machine.name = "local" if is_local else "owner@example host"
        machine.name_sanitized = "localhost" if is_local else "owner_example_host"
        machine.base_names = [raw_base_name]
        machine.base_ips = ["192.0.2.20"]
        machine.cloud_controller = 0
        machine.clouds = 1
        machine.edges = 0
        machine.endpoints = 0
        return machine

    @classmethod
    def _metadata_response(cls, config, machines, raw_base_name=None):
        raw_base_name = raw_base_name or cls.RAW_BASE_NAME
        payload = qemu_module._expected_base_image_metadata(config, machines, raw_base_name)
        metadata = json.dumps(payload, sort_keys=True).encode("utf-8")
        return cls._protocol(
            {"status": "ok", "metadata_b64": base64.b64encode(metadata).decode("ascii")}
        )

    def test_valid_local_reuse(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            machine = Machine("local", True)
            machine.base_names = [self.RAW_BASE_NAME]
            machine.base_ips = ["192.0.2.20"]
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True)
            (images_dir / (self.RAW_BASE_NAME + ".qcow2")).write_bytes(b"qcow2")
            qemu_module._write_base_image_metadata(
                config,
                [machine],
                self.RAW_BASE_NAME,
                machine=machine,
            )
            original_config = copy.deepcopy(config)
            runner = mock.Mock()

            qemu_module.base_image(config, [machine], runner=runner)

            runner.run_playbook.assert_not_called()
            self.assertEqual(config, original_config)

    def test_valid_external_owner_reuse_uses_managed_ssh(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            machine = self._machine(is_local=False)
            machine.process.return_value = self._metadata_response(config, [machine])
            runner = mock.Mock()

            qemu_module.base_image(config, [machine], runner=runner)

            runner.run_playbook.assert_not_called()
            command = machine.process.call_args.args[1]
            self.assertEqual(
                shlex.split(" ".join(command))[:4],
                ["python3", "-c", qemu_module._HOST_CACHE_HELPER_SOURCE, "check"],
            )
            self.assertEqual(
                machine.process.call_args.kwargs,
                {"ssh": machine.name, "ssh_key": False},
            )

    def test_missing_and_unreadable_owner_artifacts_are_invalid(self):
        reasons = (
            "image missing",
            "metadata missing",
            "image unreadable",
            "metadata unreadable",
        )
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            for reason in reasons:
                with self.subTest(reason=reason):
                    machine = self._machine(is_local=False)
                    machine.process.return_value = self._protocol(
                        {"status": "invalid", "reason": reason}
                    )
                    self.assertEqual(
                        qemu_module._base_image_cache_invalid_reason(
                            config,
                            [machine],
                            self.RAW_BASE_NAME,
                            machine=machine,
                        ),
                        reason,
                    )

    def test_malformed_and_non_mapping_metadata_are_invalid(self):
        payloads = (b"{", b"[]", b"not-json", b"\xff")
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            for payload in payloads:
                with self.subTest(payload=payload):
                    machine = self._machine(is_local=False)
                    machine.process.return_value = self._protocol(
                        {
                            "status": "ok",
                            "metadata_b64": base64.b64encode(payload).decode("ascii"),
                        }
                    )
                    reason = qemu_module._base_image_cache_invalid_reason(
                        config,
                        [machine],
                        self.RAW_BASE_NAME,
                        machine=machine,
                    )
                    self.assertIn(reason, ("metadata malformed", "metadata invalid"))

    def test_every_schema_v1_field_mismatch_is_invalid(self):
        fields = (
            "schema_version",
            "status",
            "guest_user",
            "base_install_playbooks",
            "base_install_fingerprints",
        )
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            for field in fields:
                with self.subTest(field=field):
                    machine = self._machine(is_local=False)
                    payload = qemu_module._expected_base_image_metadata(
                        config, [machine], self.RAW_BASE_NAME
                    )
                    payload[field] = "mismatch"
                    metadata = json.dumps(payload).encode("utf-8")
                    machine.process.return_value = self._protocol(
                        {
                            "status": "ok",
                            "metadata_b64": base64.b64encode(metadata).decode("ascii"),
                        }
                    )
                    self.assertEqual(
                        qemu_module._base_image_cache_invalid_reason(
                            config,
                            [machine],
                            self.RAW_BASE_NAME,
                            machine=machine,
                        ),
                        "metadata %s mismatch" % (field,),
                    )

    def test_schema_version_requires_exact_integer_one(self):
        cases = (
            ("integer", 1, False),
            ("boolean", True, True),
            ("float", 1.0, True),
            ("missing", None, True),
            ("string", "1", True),
            ("unsupported", 2, True),
        )
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            for label, schema_version, invalid in cases:
                with self.subTest(label=label):
                    machine = self._machine(is_local=False)
                    payload = qemu_module._expected_base_image_metadata(
                        config, [machine], self.RAW_BASE_NAME
                    )
                    if label == "missing":
                        del payload["schema_version"]
                    else:
                        payload["schema_version"] = schema_version
                    metadata = json.dumps(payload).encode("utf-8")
                    machine.process.return_value = self._protocol(
                        {
                            "status": "ok",
                            "metadata_b64": base64.b64encode(metadata).decode("ascii"),
                        }
                    )

                    reason = qemu_module._base_image_cache_invalid_reason(
                        config,
                        [machine],
                        self.RAW_BASE_NAME,
                        machine=machine,
                    )

                    if invalid:
                        self.assertEqual(reason, "metadata schema_version mismatch")
                    else:
                        self.assertIsNone(reason)

    def test_protocol_transport_failures_abort_instead_of_rebuilding(self):
        synthetic = "Command exited with non-zero return code 7: python3"
        results = (
            [],
            [(["partial"], [synthetic])],
            [([], [])],
            [(["not-json"], [])],
            [([json.dumps({"protocol": qemu_module._CACHE_PROTOCOL, "status": "ok"})], [])],
            [(["one", "two"], [])],
        )
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            for result in results:
                with self.subTest(result=result):
                    machine = self._machine(is_local=False)
                    machine.process.return_value = result
                    with self.assertRaises(RuntimeError):
                        qemu_module._base_image_cache_invalid_reason(
                            config,
                            [machine],
                            self.RAW_BASE_NAME,
                            machine=machine,
                        )

    def test_exact_cleanup_order_and_already_absent_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            machine = Machine("local", True)
            paths = qemu_module._base_image_paths(config, self.RAW_BASE_NAME)
            for path in paths.values():
                pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(path).write_bytes(b"artifact")

            qemu_module._cleanup_base_image_cache(machine, config, self.RAW_BASE_NAME)
            qemu_module._cleanup_base_image_cache(machine, config, self.RAW_BASE_NAME)

            self.assertTrue(all(not pathlib.Path(path).exists() for path in paths.values()))

    def test_cleanup_paths_and_payloads_are_inert_argv_data(self):
        raw_base_name = "base $(touch SHOULD_NOT_EXIST); peer user"
        with tempfile.TemporaryDirectory(prefix="continuum cache ; ") as tempdir:
            config = self._config(tempdir)
            machine = self._machine(is_local=False, raw_base_name=raw_base_name)
            machine.process.return_value = self._protocol({"status": "ok"})

            qemu_module._cleanup_base_image_cache(machine, config, raw_base_name)

            command = machine.process.call_args.args[1]
            decoded_command = shlex.split(" ".join(command))
            expected = qemu_module._base_image_paths(config, raw_base_name)
            self.assertEqual(decoded_command[3], "cleanup")
            self.assertEqual(
                decoded_command[4:],
                [
                    expected["metadata"],
                    expected["image"],
                    expected["cloud_init"],
                    expected["user_data"],
                ],
            )
            self.assertNotIn("shell", machine.process.call_args.kwargs)

    def test_local_and_external_protocol_commands_have_semantic_parity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            local = self._machine(is_local=True)
            external = self._machine(is_local=False)
            for machine in (local, external):
                machine.process.return_value = self._protocol(
                    {"status": "invalid", "reason": "image missing"}
                )
                self.assertEqual(
                    qemu_module._base_image_cache_invalid_reason(
                        config,
                        [machine],
                        self.RAW_BASE_NAME,
                        machine=machine,
                    ),
                    "image missing",
                )

            self.assertEqual(
                local.process.call_args.args[1],
                shlex.split(" ".join(external.process.call_args.args[1])),
            )
            self.assertEqual(local.process.call_args.kwargs, {})
            self.assertEqual(
                external.process.call_args.kwargs,
                {"ssh": external.name, "ssh_key": False},
            )

    def test_publication_path_and_canonical_payload_are_inert_argv_data(self):
        raw_base_name = "base0_peer user;$(touch SHOULD_NOT_EXIST)"
        with tempfile.TemporaryDirectory(prefix="continuum publish ; ") as tempdir:
            config = self._config(tempdir)
            machine = self._machine(is_local=False, raw_base_name=raw_base_name)
            machine.process.return_value = self._protocol({"status": "ok"})

            qemu_module._write_base_image_metadata(
                config,
                [machine],
                raw_base_name,
                machine=machine,
            )

            command = machine.process.call_args.args[1]
            decoded_command = shlex.split(" ".join(command))
            self.assertEqual(decoded_command[3], "publish")
            self.assertEqual(
                decoded_command[4], qemu_module._base_image_metadata_path(config, raw_base_name)
            )
            self.assertEqual(
                base64.b64decode(decoded_command[5]),
                qemu_module._canonical_base_image_metadata(
                    config,
                    [machine],
                    raw_base_name,
                ),
            )
            self.assertNotIn("shell", machine.process.call_args.kwargs)

    def test_all_participating_markers_are_invalidated_before_prepare_failure(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            first_name = "base_cloud_none_np1_mm0_0_user"
            second_name = "base_cloud_none_np1_mm0_1_user"
            valid_owner = self._machine(is_local=False, raw_base_name=first_name)
            valid_owner.name = "valid-owner"
            valid_owner.name_sanitized = "valid_owner"
            invalid_owner = self._machine(is_local=False, raw_base_name=second_name)
            invalid_owner.name = "invalid-owner"
            invalid_owner.name_sanitized = "invalid_owner"
            machines = [valid_owner, invalid_owner]
            events = []
            valid_paths = qemu_module._base_image_paths(config, first_name)
            invalid_paths = qemu_module._base_image_paths(config, second_name)
            for path in tuple(valid_paths.values()) + tuple(invalid_paths.values()):
                pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(path).write_bytes(b"cache artifact")

            def valid_process(_config, command, **_kwargs):
                operation = command[3]
                events.append("valid:%s" % (operation,))
                if operation == "check":
                    return self._metadata_response(config, machines, first_name)
                if operation == "invalidate":
                    host_cache_helper.remove_paths([valid_paths["metadata"]])
                    return self._protocol({"status": "ok"})
                self.fail("valid peer cache files must not be deleted")

            def invalid_process(_config, command, **_kwargs):
                operation = command[3]
                events.append("invalid:%s" % (operation,))
                if operation == "check":
                    return self._protocol({"status": "invalid", "reason": "image unreadable"})
                if operation == "invalidate":
                    host_cache_helper.remove_paths([invalid_paths["metadata"]])
                    return self._protocol({"status": "ok"})
                if operation == "cleanup":
                    for path in invalid_paths.values():
                        if os.path.exists(path):
                            os.remove(path)
                    return self._protocol({"status": "ok"})
                self.fail("unexpected invalid-owner operation %s" % (operation,))

            valid_owner.process.side_effect = valid_process
            invalid_owner.process.side_effect = invalid_process
            runner = mock.Mock()

            def prepare_failure(*_args, **_kwargs):
                events.append("prepare")
                raise RuntimeError("stop at preparation boundary")

            runner.run_playbook.side_effect = prepare_failure
            real_fsync_parent = host_cache_helper._fsync_parent

            def durable_parent(path):
                real_fsync_parent(path)
                owner = "valid" if path == valid_paths["metadata"] else "invalid"
                events.append("%s:invalidate-durable" % (owner,))

            with mock.patch.object(
                host_cache_helper, "_fsync_parent", side_effect=durable_parent
            ):
                with self.assertRaisesRegex(RuntimeError, "preparation boundary"):
                    qemu_module.base_image(config, machines, runner=runner)

            valid_operations = [call.args[1][3] for call in valid_owner.process.call_args_list]
            invalid_operations = [call.args[1][3] for call in invalid_owner.process.call_args_list]
            self.assertEqual(valid_operations, ["check", "invalidate"])
            self.assertEqual(invalid_operations, ["check", "invalidate", "cleanup"])
            self.assertEqual(
                events,
                [
                    "valid:check",
                    "invalid:check",
                    "valid:invalidate",
                    "valid:invalidate-durable",
                    "invalid:invalidate",
                    "invalid:invalidate-durable",
                    "invalid:cleanup",
                    "prepare",
                ],
            )
            prepare_mapping = runner.run_playbook.call_args.kwargs["extra_vars"][
                "continuum_base_images_by_host"
            ]
            self.assertEqual(prepare_mapping[valid_owner.name_sanitized], [first_name])
            self.assertEqual(prepare_mapping[invalid_owner.name_sanitized], [second_name])
            self.assertFalse(pathlib.Path(valid_paths["metadata"]).exists())
            self.assertFalse(pathlib.Path(invalid_paths["metadata"]).exists())
            self.assertTrue(pathlib.Path(valid_paths["image"]).exists())
            self.assertTrue(pathlib.Path(valid_paths["cloud_init"]).exists())
            self.assertTrue(pathlib.Path(valid_paths["user_data"]).exists())
            self.assertFalse(pathlib.Path(invalid_paths["image"]).exists())

    def test_partial_multi_owner_invalidation_failure_prevents_prepare_and_restore(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            first_name = "base_cloud_none_np1_mm0_0_user"
            second_name = "base_cloud_none_np1_mm0_1_user"
            first_owner = self._machine(is_local=False, raw_base_name=first_name)
            second_owner = self._machine(is_local=False, raw_base_name=second_name)
            first_owner.name = "first-owner"
            second_owner.name = "second-owner"
            machines = [first_owner, second_owner]
            events = []
            first_marker = qemu_module._base_image_metadata_path(config, first_name)
            second_marker = qemu_module._base_image_metadata_path(config, second_name)
            pathlib.Path(first_marker).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(first_marker).write_bytes(b"ready")
            pathlib.Path(second_marker).write_bytes(b"ready")

            def owner_process(owner_name, fail_invalidation):
                def process(_config, command, **_kwargs):
                    operation = command[3]
                    events.append("%s:%s" % (owner_name, operation))
                    if operation == "check":
                        return self._protocol(
                            {"status": "invalid", "reason": "image unreadable"}
                        )
                    if operation == "invalidate" and fail_invalidation:
                        with mock.patch.object(
                            host_cache_helper,
                            "_fsync_parent",
                            side_effect=OSError("injected directory fsync failure"),
                        ):
                            try:
                                host_cache_helper.remove_paths([second_marker])
                            except OSError:
                                synthetic = (
                                    "Command exited with non-zero return code 7: invalidate"
                                )
                                return [([], [synthetic])]
                    if operation == "invalidate":
                        host_cache_helper.remove_paths([first_marker])
                        return self._protocol({"status": "ok"})
                    self.fail("cleanup or publication must not run after invalidation failure")

                return process

            first_owner.process.side_effect = owner_process("first", False)
            second_owner.process.side_effect = owner_process("second", True)
            runner = mock.Mock()

            with self.assertRaisesRegex(RuntimeError, "returned nonzero"):
                qemu_module.base_image(config, machines, runner=runner)

            self.assertEqual(
                events,
                [
                    "first:check",
                    "second:check",
                    "first:invalidate",
                    "second:invalidate",
                ],
            )
            runner.run_playbook.assert_not_called()
            self.assertFalse(pathlib.Path(first_marker).exists())
            self.assertFalse(pathlib.Path(second_marker).exists())

    def test_cleanup_failure_prevents_prepare_role(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            machine = self._machine(is_local=False)
            synthetic = "Command exited with non-zero return code 1: cleanup"
            machine.process.side_effect = [
                self._protocol({"status": "invalid", "reason": "image unreadable"}),
                self._protocol({"status": "ok"}),
                [([], [synthetic])],
            ]
            runner = mock.Mock()

            with self.assertRaisesRegex(RuntimeError, "returned nonzero"):
                qemu_module.base_image(config, [machine], runner=runner)

            runner.run_playbook.assert_not_called()

    def _successful_rebuild_process(self, machine, published_operations, fail_operation=None):
        synthetic = "Command exited with non-zero return code 9: injected"

        def process(_config, command, **kwargs):
            decoded_command = (
                shlex.split(" ".join(command)) if kwargs.get("ssh") else command
            )
            operation = (
                decoded_command[3]
                if decoded_command[:3]
                == ["python3", "-c", qemu_module._HOST_CACHE_HELPER_SOURCE]
                else None
            )
            if operation:
                if operation == "check":
                    return self._protocol({"status": "invalid", "reason": "metadata missing"})
                if operation == "publish":
                    published_operations.append(operation)
                if fail_operation == operation:
                    return [(["partial"], [synthetic])]
                return self._protocol({"status": "ok"})

            if decoded_command[0] == "virsh":
                operation = decoded_command[3]
                if fail_operation == operation:
                    return [(["partial"], [synthetic])]
                if operation == "create":
                    message = "Domain %s created from %s" % (
                        machine.base_names[0],
                        decoded_command[4],
                    )
                    return [([message], [])]
                if operation == "shutdown":
                    return [(["Domain %s is being shutdown" % (machine.base_names[0],)], [])]
                if operation == "list":
                    return [([], [])]

            if decoded_command[0] == "ls":
                if fail_operation == "timezone-discovery":
                    return [(["partial"], [synthetic])]
                return [(["/etc/localtime -> /usr/share/zoneinfo/Europe/Amsterdam"], [])]
            if decoded_command[:2] == ["sudo", "ln"]:
                if fail_operation == "timezone":
                    return [([], [synthetic])]
                return [([], [])]
            if decoded_command[:2] == ["sudo", "cloud-init"]:
                if fail_operation == "cloud-init":
                    return [([], [synthetic])]
                return [([], [])]
            self.fail("unexpected rebuild command %r" % (command,))

        return process

    def _run_rebuild(
        self,
        fail_operation=None,
        runner_failure=None,
        prefetch_failure=False,
        readiness_failure=False,
    ):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        config = self._config(tempdir.name)
        machine = self._machine(is_local=False)
        published = []
        machine.process.side_effect = self._successful_rebuild_process(
            machine, published, fail_operation=fail_operation
        )
        runner = mock.Mock()
        self._last_rebuild = (machine, runner, published)
        if runner_failure == "prepare":
            runner.run_playbook.side_effect = RuntimeError("prepare failed")
        elif runner_failure == "common":
            runner.run_playbook.side_effect = [mock.DEFAULT, RuntimeError("common failed")]
        elif runner_failure == "install":
            runner.run_playbooks.side_effect = RuntimeError("install failed")

        prefetch_enabled = prefetch_failure
        patches = (
            mock.patch.object(
                infrastructure_module,
                "add_ssh",
                side_effect=RuntimeError("SSH readiness failed") if readiness_failure else None,
            ),
            mock.patch.object(
                image_registry_module,
                "has_prefetch_requirements",
                return_value=prefetch_enabled,
            ),
            mock.patch.object(
                image_registry_module,
                "docker_pull",
                side_effect=RuntimeError("prefetch failed") if prefetch_failure else None,
            ),
            mock.patch.object(qemu_module.time, "sleep"),
            mock.patch.object(qemu_module.config_access, "orchestrator_name", return_value=None),
        )
        install_patch = mock.patch.object(
            qemu_module,
            "_base_install_playbooks_for_base_names",
            return_value=["install.yml"] if runner_failure == "install" else [],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], install_patch:
            qemu_module.base_image(config, [machine], runner=runner)
        return machine, runner, published

    def test_successful_build_confirms_shutdown_then_publishes_atomically(self):
        machine, _runner, published = self._run_rebuild()

        decoded_commands = [
            shlex.split(" ".join(call.args[1]))
            if call.kwargs.get("ssh")
            else call.args[1]
            for call in machine.process.call_args_list
        ]
        operations = [
            command[3]
            for command in decoded_commands
            if command[:3] == ["python3", "-c", qemu_module._HOST_CACHE_HELPER_SOURCE]
        ]
        self.assertEqual(operations, ["check", "invalidate", "cleanup", "publish"])
        self.assertEqual(published, ["publish"])
        virsh_operations = [
            call.args[1][3]
            for call in machine.process.call_args_list
            if call.args[1][0] == "virsh"
        ]
        self.assertEqual(virsh_operations, ["create", "shutdown", "list"])
        cache_or_virsh_operations = [
            command[3]
            for command in decoded_commands
            if command[:3] == ["python3", "-c", qemu_module._HOST_CACHE_HELPER_SOURCE]
            or command[0] == "virsh"
        ]
        self.assertEqual(
            cache_or_virsh_operations,
            ["check", "invalidate", "cleanup", "create", "shutdown", "list", "publish"],
        )

    def test_failed_machine_process_stages_prevent_publication(self):
        stages = (
            "create",
            "timezone-discovery",
            "timezone",
            "cloud-init",
            "shutdown",
            "list",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                with self.assertRaises(RuntimeError):
                    self._run_rebuild(fail_operation=stage)
                self.assertEqual(self._last_rebuild[2], [])

    def test_failed_readiness_and_software_stages_prevent_publication(self):
        cases = (
            {"runner_failure": "prepare"},
            {"readiness_failure": True},
            {"runner_failure": "install"},
            {"runner_failure": "common"},
            {"prefetch_failure": True},
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(RuntimeError):
                    self._run_rebuild(**case)
                self.assertEqual(self._last_rebuild[2], [])

    def test_shutdown_confirmation_is_bounded_and_prevents_publication(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = self._config(tempdir)
            machine = self._machine(is_local=False)
            selected = [(machine, self.RAW_BASE_NAME, "base_cloud_none_np1_mm0", "invalid")]
            machine.process.return_value = [([self.RAW_BASE_NAME], [])]
            with mock.patch.object(qemu_module, "_BASE_SHUTDOWN_ATTEMPTS", 3):
                with mock.patch.object(qemu_module.time, "sleep") as sleep_mock:
                    with self.assertRaisesRegex(
                        RuntimeError, "not confirmed after 3 attempts"
                    ):
                        qemu_module._confirm_base_vms_stopped(config, selected)
            self.assertEqual(machine.process.call_count, 3)
            self.assertEqual(sleep_mock.call_count, 2)

    def test_base_image_cache_invalid_without_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {"infrastructure": {"base_path": tempdir}, "module": {}}
            raw_base_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / ("%s.qcow2" % (raw_base_name))).write_text("", encoding="utf-8")

            self.assertEqual(
                qemu_module._base_image_cache_invalid_reason(config, [], raw_base_name),
                "metadata missing",
            )

    def test_base_image_cache_valid_with_matching_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {"infrastructure": {"base_path": tempdir}, "module": {}}
            raw_base_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / ("%s.qcow2" % (raw_base_name))).write_bytes(b"qcow2")

            qemu_module._write_base_image_metadata(config, [], raw_base_name)

            self.assertIsNone(
                qemu_module._base_image_cache_invalid_reason(config, [], raw_base_name)
            )

    def test_infra_only_base_install_playbooks_require_resume_prep(self):
        rm_module = mock.Mock(
            base_install_playbook=mock.Mock(
                side_effect=lambda _config, tier: "playbooks/%s_base.yml" % (tier)
            )
        )
        config = {
            "mode": "cloud",
            "module": {"resource_manager": rm_module},
            "domains": {
                "run": {
                    "targets": ["infrastructure"],
                    "prepare_for_resume": False,
                }
            },
        }
        raw_base_name = "base0_continuum-smoke"
        machines = [
            mock.Mock(
                base_names=[raw_base_name],
                cloud_controller=1,
                clouds=1,
                edges=0,
                endpoints=0,
            )
        ]

        playbooks = qemu_module._base_install_playbooks_for_base_names(
            config,
            machines,
            [orchestration_schema.normalized_base_name(raw_base_name)],
        )

        self.assertEqual(playbooks, [])
        rm_module.base_install_playbook.assert_not_called()

    def test_base_image_cache_invalid_when_required_playbooks_change(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {
                "mode": "cloud",
                "module": {
                    "resource_manager": mock.Mock(
                        base_install_playbook=mock.Mock(
                            side_effect=lambda _config, tier: "playbooks/%s_base.yml" % (tier)
                        )
                    )
                },
                "infrastructure": {"base_path": tempdir},
                "domains": {
                    "run": {
                        "targets": ["infrastructure"],
                        "prepare_for_resume": True,
                    }
                },
            }
            raw_base_name = "base0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / ("%s.qcow2" % (raw_base_name))).write_bytes(b"qcow2")
            machines = [
                mock.Mock(
                    base_names=[raw_base_name],
                    cloud_controller=1,
                    clouds=1,
                    edges=0,
                    endpoints=1,
                )
            ]
            (images_dir / ("%s.meta.json" % (raw_base_name))).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "ready",
                        "guest_user": orchestration_schema.guest_login_name(raw_base_name),
                        "base_install_playbooks": [],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                qemu_module._base_image_cache_invalid_reason(config, machines, raw_base_name),
                "metadata base_install_playbooks mismatch",
            )

    def test_base_image_cache_invalid_when_base_install_role_changes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = pathlib.Path(tempdir)
            playbook_path = repo_root / "playbooks/resource_manager/k8s_base_install.yml"
            playbook_path.parent.mkdir(parents=True)
            playbook_path.write_text(
                "---\n- hosts: base_cloud\n  roles:\n    - role: containerd_setup\n",
                encoding="utf-8",
            )
            role_task_path = (
                repo_root
                / "roles/resource_manager/containerd_setup/tasks/main.yml"
            )
            role_task_path.parent.mkdir(parents=True)
            role_task_path.write_text("---\n- debug:\n    msg: old\n", encoding="utf-8")

            config = {
                "base": tempdir,
                "mode": "cloud",
                "module": {
                    "resource_manager": mock.Mock(
                        base_install_playbook=mock.Mock(
                            return_value="playbooks/resource_manager/k8s_base_install.yml"
                        )
                    )
                },
                "infrastructure": {"base_path": tempdir},
                "domains": {
                    "run": {
                        "targets": ["infrastructure"],
                        "prepare_for_resume": True,
                    }
                },
            }
            raw_base_name = "base0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / ("%s.qcow2" % (raw_base_name))).write_bytes(b"qcow2")
            machines = [
                mock.Mock(
                    base_names=[raw_base_name],
                    cloud_controller=1,
                    clouds=1,
                    edges=0,
                    endpoints=1,
                )
            ]
            (images_dir / ("%s.meta.json" % (raw_base_name))).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "ready",
                        "guest_user": orchestration_schema.guest_login_name(raw_base_name),
                        "base_install_playbooks": [
                            "playbooks/resource_manager/k8s_base_install.yml"
                        ],
                        "base_install_fingerprints": [],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                qemu_module._base_image_cache_invalid_reason(
                    config,
                    machines,
                    raw_base_name,
                ),
                "metadata base_install_fingerprints mismatch",
            )

    def test_common_base_install_hosts_target_only_rebuilt_tiers(self):
        self.assertEqual(
            qemu_module._common_base_install_hosts_for_base_names(
                ["base_cloud_kubeedge_np1", "base_edge_kubeedge_np1"]
            ),
            "base_cloud:base_edge",
        )

    def test_common_base_install_hosts_falls_back_for_legacy_base_names(self):
        self.assertEqual(
            qemu_module._common_base_install_hosts_for_base_names(["base0_continuum-smoke"]),
            "base",
        )


class InfrastructureWorkspacePermissionTests(unittest.TestCase):
    def test_create_keypair_creates_local_keys_without_shell_compound_command(self):
        machine = mock.Mock()
        machine.is_local = True
        machine.process.side_effect = [
            [([], []), ([], [])],
            [([], []), ([], [])],
        ]
        config = {"ssh_key": "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum"}

        with mock.patch("infrastructure.infrastructure.os.path.isfile", return_value=False):
            infrastructure_module.create_keypair(config, [machine])

        create_call = machine.process.call_args_list[0]
        self.assertEqual(
            create_call.args[1],
            [
                ["mkdir", "-p", "/tmp/continuum-smoke/.continuum/ssh"],
                [
                    "ssh-keygen",
                    "-t",
                    "rsa",
                    "-b",
                    "4096",
                    "-f",
                    "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum",
                    "-N",
                    "",
                    "-q",
                ],
            ],
        )
        self.assertNotIn("shell", create_call.kwargs)

        chmod_call = machine.process.call_args_list[1]
        self.assertEqual(
            chmod_call.args[1],
            [
                ["chmod", "600", "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum"],
                ["chmod", "600", "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum.pub"],
            ],
        )

    def test_create_keypair_skips_regeneration_when_private_key_exists(self):
        machine = mock.Mock()
        machine.is_local = True
        machine.process.side_effect = [
            [([], [])],
            [([], []), ([], [])],
        ]
        config = {"ssh_key": "/tmp/continuum-smoke/.continuum/ssh/id_rsa_continuum"}

        with mock.patch("infrastructure.infrastructure.os.path.isfile", return_value=True):
            infrastructure_module.create_keypair(config, [machine])

        create_call = machine.process.call_args_list[0]
        self.assertEqual(
            create_call.args[1],
            [["mkdir", "-p", "/tmp/continuum-smoke/.continuum/ssh"]],
        )

    def test_create_tmp_dir_uses_base_path_workspace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = pathlib.Path(tempdir) / "repo"
            repo_root.mkdir()
            legacy_tmp = repo_root / ".tmp"
            legacy_tmp.mkdir()
            (legacy_tmp / "stale.txt").write_text("stale", encoding="utf-8")

            config = {
                "infrastructure": {
                    "base_path": str(pathlib.Path(tempdir) / "continuum_smoke"),
                },
                "base": str(repo_root),
            }

            infrastructure_module.create_tmp_dir(config, [mock.Mock()])

            self.assertEqual(
                config["tmp_dir"],
                str(pathlib.Path(tempdir) / "continuum_smoke" / ".continuum" / "tmp"),
            )
            self.assertTrue(pathlib.Path(config["tmp_dir"]).is_dir())
            self.assertTrue((legacy_tmp / "stale.txt").exists())

    def test_delete_old_content_preserves_phase_zero_lock(self):
        machine = mock.Mock()
        machine.is_local = True
        machine.process.return_value = [([], [])]
        config = {"infrastructure": {"base_path": "/tmp/continuum_smoke"}}

        infrastructure_module.delete_old_content(config, [machine])

        command = machine.process.call_args.args[1][0]
        self.assertIn("! -name experiment_lock.yaml -delete", command)

    def test_create_continuum_dir_normalizes_local_directory_modes(self):
        machine = mock.Mock()
        machine.is_local = True
        machine.process.return_value = [([], [])]
        config = {
            "infrastructure": {
                "base_path": "/tmp/continuum_smoke",
                "wireless_network_preset": "",
            },
            "base": "/tmp/repo",
            "username": "continuum-smoke",
        }

        infrastructure_module.create_continuum_dir(config, [machine])

        machine.process.assert_called_once()
        command = machine.process.call_args.args[1][0]
        self.assertIn("mkdir -p /tmp/continuum_smoke/.continuum", command)
        self.assertIn("mkdir -p /tmp/continuum_smoke/.continuum/images", command)
        self.assertIn("chmod 755 /tmp/continuum_smoke/.continuum", command)
        self.assertIn("chmod 755 /tmp/continuum_smoke/.continuum/images", command)
        self.assertIn("setfacl -m u:continuum-smoke:rwx,g:kvm:rwx /tmp/continuum_smoke/.continuum/images >/dev/null 2>&1 || true", command)
        self.assertIn("setfacl -d -m u:continuum-smoke:rwx,g:kvm:rwx /tmp/continuum_smoke/.continuum/images >/dev/null 2>&1 || true", command)

    def test_create_continuum_dir_does_not_fetch_mahimahi_for_mahimahi_preset(self):
        machine = mock.Mock()
        machine.is_local = True
        machine.process.return_value = [([], [])]
        config = {
            "infrastructure": {
                "base_path": "/tmp/continuum_smoke",
                "wireless_network_preset": "4g_us_verizon_mahimahi",
            },
            "base": "/tmp/repo",
            "username": "continuum-smoke",
        }

        infrastructure_module.create_continuum_dir(config, [machine])

        machine.process.assert_called_once()
        commands = machine.process.call_args.args[1]
        self.assertEqual(len(commands), 1)
        joined = "\n".join(commands)
        self.assertNotIn("git clone", joined)
        self.assertNotIn("rsync", joined)
        self.assertNotIn("/tmp/repo/mahimahi", joined)


class MahimahiRoleTests(unittest.TestCase):
    repo_root = pathlib.Path(__file__).resolve().parents[3]

    def test_role_defaults_use_runtime_cache(self):
        defaults = (
            self.repo_root / "roles" / "infrastructure" / "mahimahi" / "defaults" / "main.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'mahimahi_repo_url: "https://github.com/atlarge-research/continuum-modded-mahimahi.git"',
            defaults,
        )
        self.assertIn('mahimahi_repo_version: "master"', defaults)
        self.assertIn("mahimahi_repo_update: false", defaults)
        self.assertIn(
            'mahimahi_cache_dir: "{{ continuum_base_path }}/.continuum/mahimahi"',
            defaults,
        )
        self.assertIn('mahimahi_repo_dir: "{{ mahimahi_cache_dir }}/repo"', defaults)
        self.assertIn('mahimahi_source_dir: "{{ mahimahi_cache_dir }}/source"', defaults)
        self.assertNotIn("continuum_repo_root", defaults)

    def test_role_fetches_and_exports_clean_source_on_control_host(self):
        tasks = (
            self.repo_root / "roles" / "infrastructure" / "mahimahi" / "tasks" / "main.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("ansible.builtin.git:", tasks)
        self.assertIn("repo: \"{{ mahimahi_repo_url }}\"", tasks)
        self.assertIn("dest: \"{{ mahimahi_repo_dir }}\"", tasks)
        self.assertIn("update: \"{{ mahimahi_repo_update }}\"", tasks)
        self.assertIn("delegate_to: localhost", tasks)
        self.assertIn("run_once: true", tasks)
        self.assertIn("become: false", tasks)
        self.assertIn("path: \"{{ mahimahi_source_dir }}/.git\"", tasks)
        self.assertIn("state: absent", tasks)
        self.assertIn("src: \"{{ mahimahi_source_dir }}/\"", tasks)
        self.assertIn("dest: \"{{ mahimahi_build_dir }}/\"", tasks)


class QemuGatewayDetectionTests(unittest.TestCase):
    def test_extract_gateway_from_proc_net_route_decodes_default_gateway(self):
        lines = [
            "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n",
            "br0\t00000000\t6301A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n",
        ]

        gateway = qemu_module.generate._extract_gateway_from_proc_net_route(lines, "br0")

        self.assertEqual(gateway, "192.168.1.99")

    def test_find_bridge_gateway_falls_back_to_proc_net_route_for_br0(self):
        machine = mock.Mock()
        machine.process.side_effect = [
            [([], ["Cannot open netlink socket: Operation not permitted\n"])],
            [([], ["Cannot open netlink socket: Operation not permitted\n"])],
            [([], ["Cannot open netlink socket: Operation not permitted\n"])],
            [(
                [
                    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n",
                    "br0\t00000000\t6301A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n",
                ],
                [],
            )],
        ]

        gateway = qemu_module.generate._find_bridge_gateway({}, machine, "br0")

        self.assertEqual(gateway, "192.168.1.99")

    def test_bridge_runtime_overrides_reads_environment(self):
        with mock.patch.dict(
            "os.environ",
            {
                "CONTINUUM_QEMU_BRIDGE_NAME": "br0",
                "CONTINUUM_QEMU_BRIDGE_GATEWAY": "192.168.1.99",
            },
            clear=False,
        ):
            bridge_name, gateway = qemu_module.generate._bridge_runtime_overrides()

        self.assertEqual(bridge_name, "br0")
        self.assertEqual(gateway, "192.168.1.99")


class QemuUserDataTests(unittest.TestCase):
    def test_render_user_data_matches_primary_ethernet_by_pattern(self):
        rendered = qemu_module.generate._render_user_data(
            "base0continuum-smoke",
            "base0_continuum-smoke",
            "ssh-rsa TESTKEY continuum-smoke@test",
            "192.168.90.2",
            "192.168.1.99",
        )

        self.assertIn('name: "e*"', rendered)
        self.assertIn("primary:", rendered)
        self.assertNotIn("ens2:", rendered)


if __name__ == "__main__":
    unittest.main()
