"""Cloud-safe tests for mem-usage runner propagation and deployment failures."""

import unittest
from unittest import mock

from application import application
from application import runtime_helpers
from application.mem_usage import mem_usage  # pylint: disable=import-error
from infrastructure import ansible as infrastructure_ansible


class _DispatchStop(Exception):
    """Stop application dispatch immediately after the mem-usage handoff."""


class MemUsageRunnerTests(unittest.TestCase):
    """Validate ownership of the shared runner throughout mem-usage deployment."""

    @staticmethod
    def _config(application_module=None):
        resources = [
            {
                "vm_id": 1,
                "cluster_id": "cloud-1",
                "tier": "cloud",
                "index_in_cluster": 0,
                "tags": {"cluster": "cloud-1", "tier": "cloud"},
            },
            {
                "vm_id": 2,
                "cluster_id": "cloud-1",
                "tier": "cloud",
                "index_in_cluster": 1,
                "tags": {"cluster": "cloud-1", "tier": "cloud"},
            },
        ]
        return {
            "mode": "cloud",
            "cloud_ssh": ["controller@10.0.0.1", "worker@10.0.0.2"],
            "infrastructure": {
                "provider": "qemu",
            },
            "module": {
                "application": application_module or mock.Mock(),
            },
            "domains": {
                "software": {
                    "modules": [
                        {
                            "id": "orchestrator",
                            "type": "kubecontrol",
                            "config": {},
                        }
                    ]
                },
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "memory",
                            "type": "mem_usage",
                            "config": {"applications_per_worker": 2},
                        }
                    ]
                },
            },
            "normalized": {"infrastructure": {"resources": resources}},
            "planner_snapshot": {
                "benchmark_stage_assignments": [
                    {
                        "id": "memory",
                        "type": "mem_usage",
                        "selector_id": "sel_memory_cloud_1",
                        "resolved_vm_ids": [1, 2],
                        "resolved_resources": resources,
                        "scope_identities": [
                            {
                                "kind": "selector",
                                "selector_id": "sel_memory_cloud_1",
                            }
                        ],
                        "tags": {"benchmark.role": "memory"},
                    }
                ]
            },
        }

    def test_application_dispatch_passes_shared_runner_and_existing_callback(self):
        """Application dispatch hands the exact active runner to mem-usage."""
        application_module = mock.Mock()
        application_module.get_mem_usage.side_effect = _DispatchStop
        config = self._config(application_module)
        machines = [mock.Mock()]
        runner = mock.Mock()
        runner.config = config
        runner.machines = machines

        with mock.patch.object(
            application.application_runtime_helpers,
            "start_kubernetes_resource_metrics",
        ) as start_metrics, mock.patch.object(
            infrastructure_ansible,
            "AnsibleRunner",
        ) as runner_constructor:
            with self.assertRaises(_DispatchStop):
                application.start(runner)

        start_metrics.assert_called_once_with(config, machines)
        application_module.get_mem_usage.assert_called_once_with(
            config,
            machines,
            runtime_helpers.start_kubernetes_workers,
            runner,
        )
        runner_constructor.assert_not_called()

    def test_get_mem_usage_requires_runner_argument(self):
        """The deployment API has no missing-runner fallback."""
        with self.assertRaises(TypeError):
            mem_usage.get_mem_usage(self._config(), [mock.Mock()], mock.Mock())

    def test_get_mem_usage_deploys_with_injected_callback_and_shared_runner(self):
        """A mocked supported path continues after deployment with the same runner."""
        config = self._config()
        machine = mock.Mock()
        machine.process.side_effect = [
            [(["1000"], [])],
            [(["2"], [])],
            [(["800"], [])],
            [(["job.batch/memory deleted"], [])],
        ]
        machines = [machine]
        runner = mock.sentinel.shared_runner
        deploy = mock.Mock(return_value=(mock.sentinel.starttime, ["kubectl output"]))

        with mock.patch.object(mem_usage.time, "sleep") as sleep, mock.patch.object(
            runtime_helpers,
            "start_kubernetes_workers",
        ) as direct_start, mock.patch.object(
            infrastructure_ansible,
            "AnsibleRunner",
        ) as runner_constructor:
            mem_usage.get_mem_usage(config, machines, deploy, runner)

        deploy.assert_called_once_with(
            config,
            machines,
            {"sleep_time": 6000},
            get_starttime=True,
            runner=runner,
        )
        self.assertEqual(machine.process.call_count, 4)
        sleep.assert_called_once_with(5)
        direct_start.assert_not_called()
        runner_constructor.assert_not_called()

    def test_deployment_failure_propagates_without_post_deployment_work(self):
        """Deployment errors prevent polling, post-deployment measurement, and teardown."""
        config = self._config()
        machine = mock.Mock()
        machine.process.return_value = [(["1000"], [])]
        machines = [machine]
        runner = mock.sentinel.shared_runner
        deployment_error = RuntimeError("deployment failed")
        deploy = mock.Mock(side_effect=deployment_error)

        with mock.patch.object(mem_usage.time, "sleep") as sleep, mock.patch.object(
            runtime_helpers,
            "start_kubernetes_workers",
        ) as direct_start, mock.patch.object(
            infrastructure_ansible,
            "AnsibleRunner",
        ) as runner_constructor:
            with self.assertRaises(RuntimeError) as raised:
                mem_usage.get_mem_usage(config, machines, deploy, runner)

        self.assertIs(raised.exception, deployment_error)
        deploy.assert_called_once_with(
            config,
            machines,
            {"sleep_time": 6000},
            get_starttime=True,
            runner=runner,
        )
        machine.process.assert_called_once_with(
            config,
            "free -m | awk 'NR==2{print $4}'",
            shell=True,
            ssh="worker@10.0.0.2",
        )
        sleep.assert_not_called()
        direct_start.assert_not_called()
        runner_constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
