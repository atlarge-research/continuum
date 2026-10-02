"""FIFO admission preserves original creation order and bounded outstanding work."""

import copy
import importlib
import json
import unittest
from unittest.mock import Mock, patch


class AdmissionTests(unittest.TestCase):
    """The oldest suspended Job may enter only when observed requests fit a worker."""

    def setUp(self):
        """Build one one-slot worker and two suspended homogeneous Jobs."""
        self.nodes = [
            {
                "metadata": {"name": "w1"},
                "spec": {},
                "status": {
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "allocatable": {"cpu": "2", "memory": "4Gi"},
                },
            }
        ]
        self.workers = {"w1": 2}
        self.jobs = [self.job("b", "2026-09-25T00:00:02Z"), self.job("a", "2026-09-25T00:00:01Z")]

    @staticmethod
    def job(uid, created):
        """Create a suspended one-CPU, 512-MiB workload Job.

        Args:
            uid (str): Stable Job identity.
            created (str): Original server creation timestamp.

        Returns:
            dict: Kubernetes Job fixture.
        """
        return {
            "metadata": {
                "name": uid,
                "uid": uid,
                "creationTimestamp": created,
                "resourceVersion": "1",
            },
            "spec": {
                "suspend": True,
                "template": {
                    "spec": {
                        "containers": [{"resources": {"requests": {"cpu": "1", "memory": "512Mi"}}}]
                    }
                },
            },
            "status": {},
        }

    def choose(self, pods=None):
        """Choose from this fixture's current physical admission inventory.

        Args:
            pods (list or None): Namespace workload Pods.

        Returns:
            dict: Admission decision.
        """
        self.assertIsNotNone(importlib.util.find_spec("fifo_admission"))
        return importlib.import_module("fifo_admission").choose(
            self.jobs, pods or [], self.nodes, self.workers
        )

    def test_oldest_creation_then_uid_order(self):
        """API list order never changes FIFO order, including timestamp ties."""
        self.assertEqual(self.choose()["job_uid"], "a")
        self.jobs[0]["metadata"]["creationTimestamp"] = self.jobs[1]["metadata"][
            "creationTimestamp"
        ]
        self.assertEqual(self.choose()["job_uid"], "a")

    def test_outstanding_unsuspended_job_blocks_even_before_pod_creation(self):
        """Restart recovery uses durable Job suspension state, not process memory."""
        self.jobs[1]["spec"]["suspend"] = False
        result = self.choose()
        self.assertEqual(result["reason"], "awaiting_binding")
        self.assertEqual(result["outstanding_uid"], "a")

    def test_bound_pod_holds_slot_until_terminal(self):
        """Classifier completion cannot release a still-running Pod's request."""
        self.jobs[1]["spec"]["suspend"] = False
        pod = {
            "metadata": {"ownerReferences": [{"kind": "Job", "uid": "a"}]},
            "spec": {
                "nodeName": "w1",
                "containers": copy.deepcopy(self.jobs[1]["spec"]["template"]["spec"]["containers"]),
            },
            "status": {"phase": "Running"},
        }
        self.assertEqual(self.choose([pod])["reason"], "no_fit")
        pod["status"]["phase"] = "Succeeded"
        self.jobs[1]["status"]["succeeded"] = 1
        self.assertEqual(self.choose([pod])["job_uid"], "b")

    def test_cordon_and_not_ready_workers_cannot_admit(self):
        """Admission never treats a warm reserve as accepting application capacity."""
        self.nodes[0]["spec"]["unschedulable"] = True
        self.assertEqual(self.choose()["reason"], "no_fit")
        self.nodes[0]["spec"]["unschedulable"] = False
        self.nodes[0]["status"]["conditions"][0]["status"] = "False"
        self.assertEqual(self.choose()["reason"], "no_fit")

    def test_oversized_head_does_not_allow_younger_job_to_overtake(self):
        """FIFO head-of-line blocking is explicit even when a smaller later Job fits."""
        self.jobs[1]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
            "cpu"
        ] = "2"
        self.assertEqual(self.choose()["reason"], "no_fit")

    def test_definite_patch_conflict_retries_observation_but_uncertain_error_stops_release(self):
        """Status-update races must not restart the owner or replay an uncertain mutation."""
        module = importlib.import_module("fifo_admission")
        decision = self.choose()

        api = Mock()
        for status, message, expected in [
            (409, "Conflict", "retry_snapshot"),
            (422, "testing value failed: test failed", "retry_snapshot"),
            (
                422,
                "the server rejected our request due to an error in our request",
                "retry_snapshot",
            ),
            (500, "lost server outcome", "uncertain_stop"),
        ]:
            api.patch_namespaced_job.side_effect = module.client.exceptions.ApiException(
                status=status, reason=message
            )
            self.assertEqual(module.release(api, "test", decision)["status"], expected)

    def test_binding_timeout_stops_without_releasing_younger_jobs(self):
        """The live loop halts after a30-second unbound reservation, including after restart."""
        module = importlib.import_module("fifo_admission")
        self.jobs[1]["spec"]["suspend"] = False
        api_client, batch, core = Mock(), Mock(), Mock()
        api_client.sanitize_for_serialization.side_effect = lambda value: value
        batch.list_namespaced_job.return_value = {"items": self.jobs}
        core.list_namespaced_pod.return_value = {"items": []}
        core.list_node.return_value = {"items": self.nodes}
        with patch.dict(
            module.os.environ, {"JOB_NAMESPACE": "test", "ADMISSION_WORKERS": '{"w1":2}'}
        ), patch.object(module.config, "load_incluster_config"), patch.object(
            module.client, "ApiClient", return_value=api_client
        ), patch.object(
            module.client, "BatchV1Api", return_value=batch
        ), patch.object(
            module.client, "CoreV1Api", return_value=core
        ), patch.object(
            module.time, "monotonic", side_effect=[0, 31]
        ), patch.object(
            module, "halt", side_effect=RuntimeError("stopped")
        ) as stop:
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                module.main()
        stop.assert_called_once_with("binding_timeout", job_uid="a")
        batch.patch_namespaced_job.assert_not_called()

    def test_collection_separates_sdk_calls_from_serialization(self):
        """Slow list processing is visible separately from the dictionary conversion."""
        module = importlib.import_module("fifo_admission")
        api_client, batch, core = Mock(), Mock(), Mock()
        api_client.sanitize_for_serialization.side_effect = lambda value: value
        batch.list_namespaced_job.return_value = {"items": self.jobs}
        core.list_namespaced_pod.return_value = {"items": []}
        core.list_node.return_value = {"items": self.nodes}
        with patch.object(module.time, "perf_counter", side_effect=range(9)):
            inventory = module.collect_inventory(api_client, batch, core, "test")
        self.assertEqual([job["metadata"]["uid"] for job in inventory["jobs"]], ["b", "a"])
        self.assertEqual(inventory["pods"], [])
        self.assertEqual(inventory["nodes"], self.nodes)
        self.assertEqual(
            inventory["timings"],
            {
                "jobs_api_seconds": 1,
                "jobs_serialization_seconds": 1,
                "pods_api_seconds": 1,
                "pods_serialization_seconds": 1,
                "nodes_api_seconds": 1,
                "nodes_serialization_seconds": 1,
            },
        )
        self.assertEqual(
            module.choose(inventory["jobs"], inventory["pods"], inventory["nodes"], self.workers)[
                "job_uid"
            ],
            "a",
        )

    def test_live_cycle_records_decision_cost_and_inventory_counts(self):
        """Every admission iteration exposes cost, even without a changing decision."""
        module = importlib.import_module("fifo_admission")
        api_client, batch, core = Mock(), Mock(), Mock()
        api_client.sanitize_for_serialization.side_effect = lambda value: value
        batch.list_namespaced_job.return_value = {"items": self.jobs}
        core.list_namespaced_pod.return_value = {"items": []}
        core.list_node.return_value = {"items": self.nodes}
        with patch.dict(
            module.os.environ, {"JOB_NAMESPACE": "test", "ADMISSION_WORKERS": '{"w1":2}'}
        ), patch.object(module.config, "load_incluster_config"), patch.object(
            module.client, "ApiClient", return_value=api_client
        ), patch.object(
            module.client, "BatchV1Api", return_value=batch
        ), patch.object(
            module.client, "CoreV1Api", return_value=core
        ), patch.object(
            module.time, "sleep", side_effect=RuntimeError("end iteration")
        ), patch(
            "builtins.print"
        ) as output:
            with self.assertRaisesRegex(RuntimeError, "end iteration"):
                module.main()
        records = [json.loads(call.args[0]) for call in output.call_args_list]
        cycles = [row for row in records if row["event"] == "admission.cycle"]
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["inventory_counts"], {"jobs": 2, "pods": 0, "nodes": 1})
        self.assertEqual(cycles[0]["reason"], "admit")
        self.assertEqual(cycles[0]["job_uid"], "a")
        for key in [
            "jobs_api_seconds",
            "pods_api_seconds",
            "nodes_api_seconds",
            "decision_seconds",
            "patch_seconds",
            "cpu_seconds",
            "wall_seconds",
        ]:
            self.assertGreaterEqual(cycles[0]["timings"][key], 0)
        self.assertEqual(batch.patch_namespaced_job.call_count, 1)
