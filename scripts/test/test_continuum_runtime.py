"""Unit tests for runtime target resolution and addon compatibility."""

import argparse
import continuum as continuum_module
import contextlib
import io
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from infrastructure.qemu import qemu as qemu_module
from infrastructure import ansible as infrastructure_ansible
from infrastructure import infrastructure as infrastructure_module
from infrastructure import image_registry as image_registry_module
from infrastructure import orchestration_schema
from infrastructure import state as infra_state
from infrastructure.machine import Machine
from input.configuration import (
    config_access,
    module_registry,
    runtime_module_loader,
    runtime_option_validation,
    runtime_phase_targets,
)


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
        config = {"domains": {"run": {"targets": ["software"]}}}
        self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), (False, True, False))

    def test_resolve_targets_application_supported(self):
        config = {"domains": {"run": {"targets": ["application"]}}}
        self.assertEqual(runtime_phase_targets.resolve_runtime_targets(config), (False, False, True))

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


class ContinuumMainApplicationPhaseTests(unittest.TestCase):
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
        mock_ansible_runner.assert_called_once_with(config, machines)
        mock_resource_manager_start.assert_not_called()
        mock_application_start.assert_called_once_with(runner)
        mock_save_state.assert_called_once_with(config, "application", machines)

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

    def test_dynamic_import_loads_resource_manager_for_infra_only_resumable_stack(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-infra-only-rm")
        config = {
            "infrastructure": {"provider": "qemu"},
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

        runtime_module_loader.dynamic_import(parser, config)

        self.assertEqual(
            config["module"]["resource_manager"].__name__,
            "resource_manager.kubernetes.kubernetes",
        )

    def test_dynamic_import_keeps_none_orchestrator_unloaded_for_infra_only(self):
        parser = argparse.ArgumentParser(prog="dynamic-import-infra-only-none")
        config = {
            "infrastructure": {"provider": "qemu"},
            "domains": {
                "run": {"targets": ["infrastructure"]},
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
            "domains": {"run": {"targets": ["infrastructure"]}},
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
        self.assertEqual(len(requirements), 6)
        sources = [entry["source_ref"] for entry in requirements]
        self.assertIn("redplanet00/kube-apiserver:v1.24.0", sources)
        self.assertIn("redplanet00/etcd:3.5.3-0", sources)
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
        self.assertIn(["curl", "127.0.0.1:5000/v2/_catalog"], commands)
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
            }

            with mock.patch.dict("os.environ", {}, clear=False):
                runner = infrastructure_ansible.AnsibleRunner(config, [machine])
                self.assertEqual(os.environ["ANSIBLE_LOCAL_TEMP"], runner.ansible_local_tmp)
                self.assertEqual(os.environ["ANSIBLE_REMOTE_TMP"], runner.ansible_remote_tmp)

            self.assertEqual(
                runner.ansible_local_tmp,
                str(pathlib.Path(tempdir) / ".continuum" / "ansible" / "tmp"),
            )
            self.assertEqual(runner.ansible_remote_tmp, "/tmp/.continuum-ansible/tmp")
            self.assertTrue(pathlib.Path(runner.ansible_local_tmp).is_dir())

    def test_ansible_runner_merges_default_env_with_call_env(self):
        with tempfile.TemporaryDirectory() as tempdir:
            machine = mock.Mock()
            machine.process.return_value = [([], [])]
            config = {
                "base": tempdir,
                "infrastructure": {"base_path": tempdir},
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
    def test_base_image_cache_invalid_without_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {"infrastructure": {"base_path": tempdir}}
            raw_base_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / ("%s.qcow2" % (raw_base_name))).write_text("", encoding="utf-8")

            self.assertEqual(
                qemu_module._base_image_cache_invalid_reason(config, raw_base_name),
                "metadata missing",
            )

    def test_base_image_cache_valid_with_matching_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = {"infrastructure": {"base_path": tempdir}}
            raw_base_name = "base_cloud_kubernetes_np1_mm0_0_continuum-smoke"
            images_dir = pathlib.Path(tempdir) / ".continuum" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            qemu_module._write_base_image_metadata(config, raw_base_name)

            self.assertIsNone(qemu_module._base_image_cache_invalid_reason(config, raw_base_name))


class InfrastructureWorkspacePermissionTests(unittest.TestCase):
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
