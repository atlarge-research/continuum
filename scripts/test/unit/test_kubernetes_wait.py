"""Unit tests for Kubernetes post-install readiness failure semantics."""

import argparse
import unittest
from types import SimpleNamespace
from unittest import mock

import continuum as continuum_module
from resource_manager.kubernetes import kubernetes


class _FakeMachine:  # pylint: disable=too-few-public-methods
    """Return configured Machine.process results while recording calls."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def process(self, config, command, ssh=None):
        """Return the configured result for this invocation."""
        self.calls.append({"config": config, "command": command, "ssh": ssh})
        index = min(len(self.calls) - 1, len(self.results) - 1)
        return [self.results[index]]


class KubernetesWaitSemanticsTests(unittest.TestCase):
    """Cover kubectl wait success, failure, trace, and retry semantics."""

    @staticmethod
    def _config():
        """Return the minimal configuration needed by cluster verification."""
        return {"cloud_ssh": ["controller@192.0.2.10"]}

    def test_partial_readiness_with_timeout_and_nonzero_marker_fails(self):
        """Partial readiness cannot override timeout and nonzero diagnostics."""
        result = (
            ["node/worker-0 condition met"],
            [
                "error: timed out waiting for the condition on nodes/worker-1",
                "Command exited with non-zero return code 1: kubectl wait --all",
            ],
        )
        machine = _FakeMachine([result])

        with mock.patch.object(kubernetes.time, "sleep"), self.assertRaises(SystemExit):
            kubernetes.verify_running_cluster(self._config(), [machine])

        self.assertEqual(len(machine.calls), 5)

    def test_partial_readiness_with_other_nonzero_failure_fails(self):
        """Partial readiness cannot override another nonzero failure."""
        result = (
            ["node/worker-0 condition met"],
            [
                "permission denied",
                "Command exited with non-zero return code 2: kubectl wait --all",
            ],
        )
        machine = _FakeMachine([result])

        with mock.patch.object(kubernetes.time, "sleep"), self.assertRaises(SystemExit):
            kubernetes.verify_running_cluster(self._config(), [machine])

        self.assertEqual(len(machine.calls), 5)

    def test_positive_readiness_without_failure_succeeds(self):
        """Positive readiness without stderr succeeds on the first attempt."""
        machine = _FakeMachine([(["node/worker-0 condition met"], [])])
        config = self._config()

        kubernetes.verify_running_cluster(config, [machine])

        self.assertEqual(len(machine.calls), 1)
        self.assertEqual(
            machine.calls[0]["command"],
            ["kubectl", "wait", "--for=condition=Ready", "node", "--all", "--timeout=10m"],
        )
        self.assertEqual(machine.calls[0]["ssh"], config["cloud_ssh"][0])

    def test_controlled_trace_stderr_is_benign(self):
        """A controlled trace-prefix line does not mask successful readiness."""
        machine = _FakeMachine(
            [(["node/worker-0 condition met"], ["  [CONTINUUM] kubectl wait timing=1.0"])]
        )

        kubernetes.verify_running_cluster(self._config(), [machine])

        self.assertEqual(len(machine.calls), 1)

    def test_trace_cannot_hide_adjacent_or_embedded_errors(self):
        """Continuum trace text cannot make real stderr failures benign."""
        cases = [
            [
                "[CONTINUUM] kubectl wait timing=1.0",
                "Command exited with non-zero return code 1: kubectl wait --all",
            ],
            ["[CONTINUUM] error: timed out waiting for the condition on nodes/worker-0"],
            ["[CONTINUUM] error: permission denied"],
            ["permission denied [CONTINUUM] kubectl wait timing=1.0"],
            ["warning: [CONTINUUM] kubectl wait timing=1.0"],
        ]

        for stderr in cases:
            with self.subTest(stderr=stderr):
                self.assertTrue(
                    kubernetes._stderr_has_real_error(stderr)  # pylint: disable=protected-access
                )

    def test_non_readiness_stdout_exhausts_retries(self):
        """Unrelated stdout is not a positive readiness signal."""
        machine = _FakeMachine([(["kubectl wait started"], [])])

        with mock.patch.object(kubernetes.time, "sleep"), self.assertRaises(SystemExit):
            kubernetes.verify_running_cluster(self._config(), [machine])

        self.assertEqual(len(machine.calls), 5)


class KubernetesWaitStateBoundaryTests(unittest.TestCase):
    """Cover the software-state boundary after cluster verification."""

    def test_wait_failure_prevents_software_state_and_application_phase(self):
        """Wait exhaustion stops state persistence and the application phase."""
        config = {
            "cloud_ssh": ["controller@192.0.2.10"],
            "domains": {"run": {"targets": ["software", "application"]}},
            "infrastructure": {
                "base_path": "/tmp/continuum-kubernetes-wait-test",
                "delete": False,
                "provider": "qemu",
            },
            "module": {"application": object(), "resource_manager": kubernetes},
        }
        result = (
            ["node/worker-0 condition met"],
            ["Command exited with non-zero return code 1: kubectl wait --all"],
        )
        machine = _FakeMachine([result])
        runner = SimpleNamespace(config=config, machines=[machine])

        def start_resource_manager(active_runner):
            kubernetes.post_phase_hook(active_runner)

        with mock.patch.object(
            continuum_module.yaml_parser,
            "write_experiment_lock",
            return_value="/tmp/continuum-kubernetes-wait-test/experiment_lock.yaml",
        ), mock.patch.object(
            continuum_module.infra_state,
            "load_resume_state",
            return_value=({"phase_completed": "infrastructure"}, [machine]),
        ), mock.patch.object(
            continuum_module.ansible, "AnsibleRunner", return_value=runner
        ), mock.patch.object(
            continuum_module.resource_manager,
            "start",
            side_effect=start_resource_manager,
        ) as mock_resource_manager_start, mock.patch.object(
            continuum_module.infra_state, "save_state"
        ) as mock_save_state, mock.patch.object(
            continuum_module.application, "start"
        ) as mock_application_start, mock.patch.object(
            continuum_module, "_log_vm_access_hints"
        ), mock.patch.object(
            kubernetes.time, "sleep"
        ), self.assertRaises(SystemExit):
            continuum_module.main(argparse.Namespace(config=config))

        mock_resource_manager_start.assert_called_once_with(runner)
        mock_save_state.assert_not_called()
        mock_application_start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
