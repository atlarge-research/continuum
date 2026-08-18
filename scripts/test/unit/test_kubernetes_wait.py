"""Unit tests for Kubernetes post-install readiness failure semantics."""

import argparse
import logging
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

    @staticmethod
    def _trace_forms(payload):
        """Return every verified source form carrying a Continuum payload."""
        return [
            f"[CONTINUUM] {payload}",
            f"I0709 kubectl.go:32] [CONTINUUM] {payload}",
            (
                "I0824 22:23:21.269974 5026 kubectl.go:32] "
                f"%!s(int64=1692908601269961032) [CONTINUUM] {payload}"
            ),
        ]

    def test_stderr_classifier_rejects_command_failures(self):
        """Timeouts, nonzero markers, and mixed trace/error stderr remain fatal."""
        cases = {
            "timeout": ["error: timed out waiting for the condition on nodes/worker-1"],
            "synthetic-nonzero": [
                "Command exited with non-zero return code 1: kubectl wait --all"
            ],
            "other-nonzero": [
                "permission denied",
                "Command exited with non-zero return code 2: kubectl wait --all",
            ],
            "mixed-trace-and-failure": [
                "I0709 kubectl.go:32] [CONTINUUM] 0400",
                "error: timed out waiting for the condition on nodes/worker-1",
                "Command exited with non-zero return code 1: kubectl wait --all",
            ],
            "trace-adjacent-error": [
                "I0709 kubectl.go:32] [CONTINUUM] 0400 permission denied"
            ],
        }

        for case, stderr in cases.items():
            with self.subTest(case=case):
                self.assertTrue(
                    kubernetes._stderr_has_real_error(  # pylint: disable=protected-access
                        stderr
                    )
                )

    def test_stderr_classifier_rejects_keyword_free_malformed_traces(self):
        """Unknown Continuum payloads remain fatal without command-error keywords."""
        for trace in self._trace_forms("0499"):
            with self.subTest(trace=trace):
                self.assertTrue(
                    kubernetes._stderr_has_real_error(  # pylint: disable=protected-access
                        [trace]
                    )
                )

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

    def test_missing_readiness_retries_then_succeeds(self):
        """Clean stderr cannot make non-readiness stdout satisfy the wait."""
        machine = _FakeMachine(
            [
                (["kubectl wait started"], []),
                (["node/worker-0 condition met"], []),
            ]
        )

        with self.assertLogs(level="WARNING") as captured_logs:
            with mock.patch.object(kubernetes.time, "sleep") as mock_sleep:
                kubernetes.verify_running_cluster(self._config(), [machine])

        self.assertEqual(len(machine.calls), 2)
        mock_sleep.assert_called_once_with(5)
        self.assertEqual(
            [record.levelno for record in captured_logs.records],
            [logging.WARNING],
        )
        self.assertIn(
            "kubectl wait failed (attempt 0/5): kubectl wait started",
            captured_logs.output[0],
        )

    def test_trace_validator_accepts_verified_sources_and_payloads(self):
        """Every verified source form accepts each controlled payload shape."""
        for payload in ("0400", "0401 job=a-b.c9", "0402"):
            for trace in self._trace_forms(payload):
                with self.subTest(payload=payload, trace=trace):
                    self.assertTrue(
                        kubernetes._is_benign_continuum_trace(  # pylint: disable=protected-access
                            trace
                        )
                    )

    def test_trace_validator_rejects_malformed_payloads(self):
        """Every verified source form rejects malformed payloads."""
        payloads = [
            "kubectl wait timing=1.0",
            "0499",
            "0401",
            "0401 job=",
            "0401 job=a..b",
        ]

        for payload in payloads:
            for trace in self._trace_forms(payload):
                with self.subTest(payload=payload, trace=trace):
                    self.assertFalse(
                        kubernetes._is_benign_continuum_trace(  # pylint: disable=protected-access
                            trace
                        )
                    )

    def test_trace_validator_rejects_wrong_sources_or_adjacent_text(self):
        """Wrong trace sources and adjacent errors fail closed."""
        traces = [
            "I0709 kubelet.go:32] [CONTINUUM] 0400",
            "I0709 kubectl.go:99] [CONTINUUM] 0400",
            "I0709 kubectl.go:32] [CONTINUUM] 0400 permission denied",
            "permission denied I0709 kubectl.go:32] [CONTINUUM] 0400",
            "I0709 kubectl.go:32] [CONTINUUM] 0401 job=a-b.c9 error: timeout",
        ]

        for trace in traces:
            with self.subTest(trace=trace):
                self.assertFalse(
                    kubernetes._is_benign_continuum_trace(  # pylint: disable=protected-access
                        trace
                    )
                )

    def test_job_name_validator_accepts_dns_subdomain_boundaries(self):
        """The dedicated validator accepts valid labels and exact length boundaries."""
        valid_names = [
            "a",
            "a-b",
            "a.b",
            "a-b.c9",
            "a" * 63,
            f"{'a' * 30}.{'b' * 32}",
        ]

        for job_name in valid_names:
            with self.subTest(job_name=job_name):
                self.assertTrue(
                    kubernetes._is_valid_kubernetes_job_name(  # pylint: disable=protected-access
                        job_name
                    )
                )

    def test_job_name_validator_rejects_invalid_dns_subdomains(self):
        """The dedicated validator rejects malformed names and length overflows."""
        invalid_names = {
            "empty": "",
            "empty-interior-label": "a..b",
            "leading-hyphen-label": "a.-b",
            "trailing-hyphen-label": "a-.b",
            "leading-dot": ".a",
            "trailing-dot": "a.",
            "leading-hyphen": "-a",
            "trailing-hyphen": "a-",
            "oversized-label": "a" * 64,
            "oversized-total": f"{'a' * 31}.{'b' * 32}",
            "uppercase": "a.B",
            "underscore": "a_b",
            "space": "a b",
            "tab": "a\tb",
            "leading-whitespace": " a",
            "trailing-whitespace": "a ",
            "slash": "a/b",
            "colon": "a:b",
            "plus": "a+b",
            "at-sign": "a@b",
        }

        for case, job_name in invalid_names.items():
            with self.subTest(case=case, job_name=job_name):
                self.assertFalse(
                    kubernetes._is_valid_kubernetes_job_name(  # pylint: disable=protected-access
                        job_name
                    )
                )

    def test_verified_trace_sources_succeed_through_wait_path(self):
        """Bare, simplified-klog, and full-klog traces preserve wait success."""
        traces = [
            "[CONTINUUM] 0400",
            "I0709 kubectl.go:32] [CONTINUUM] 0401 job=a-b.c9",
            (
                "I0824 22:23:21.269974    5026 kubectl.go:32] "
                "%!s(int64=1692908601269961032) [CONTINUUM] 0402"
            ),
        ]

        for trace in traces:
            with self.subTest(trace=trace):
                machine = _FakeMachine([(["node/worker-0 condition met"], [trace])])
                kubernetes.verify_running_cluster(self._config(), [machine])
                self.assertEqual(len(machine.calls), 1)

    def test_readiness_output_classifier_requires_positive_result(self):
        """Only positive readiness stdout satisfies the wait output contract."""
        self.assertTrue(
            kubernetes._stdout_has_readiness(  # pylint: disable=protected-access
                ["node/worker-0 condition met"]
            )
        )
        for stdout in ([], ["kubectl wait started"], ["node/worker-0 pending"]):
            with self.subTest(stdout=stdout):
                self.assertFalse(
                    kubernetes._stdout_has_readiness(  # pylint: disable=protected-access
                        stdout
                    )
                )


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

        with self.assertLogs(level="WARNING") as captured_logs:
            with mock.patch.object(
                continuum_module.yaml_parser,
                "write_experiment_lock",
                return_value="/tmp/continuum-kubernetes-wait-test/experiment_lock.yaml",
            ), mock.patch.object(
                continuum_module.infra_state,
                "load_resume_state",
                return_value=({"phase_completed": "infrastructure"}, [machine]),
            ), mock.patch.object(
                continuum_module.machine_utils,
                "validate_resume_ssh_reachability",
                return_value=["controller@192.0.2.10"],
            ), mock.patch.object(
                continuum_module.image_registry, "prepare_runtime_images"
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
        self.assertEqual(len(machine.calls), 5)
        self.assertEqual(
            [record.levelno for record in captured_logs.records],
            ([logging.WARNING] * 5) + [logging.ERROR],
        )
        self.assertIn("Cluster did not become Ready after 5 attempts", captured_logs.output[-1])


if __name__ == "__main__":
    unittest.main()
