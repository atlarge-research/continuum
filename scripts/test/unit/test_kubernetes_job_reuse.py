"""Sequential MQTT Job reuse, with an inert kubectl state machine."""

import copy
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

from jinja2 import Environment
import yaml

from application import runtime_helpers


_ROLE = Path(__file__).resolve().parents[3] / "roles/application/k8s_job_deploy"


class _KubernetesMachine:
    """Model immutable Job apply and independent pod/log command failures."""

    cloud_controller = True

    def __init__(self):
        self.jobs = {"unrelated": {"metadata": {"name": "unrelated", "labels": {}}}}
        self.pods = {}
        self.commands = []
        self.fail_operation = None
        self.failure = "Command exited with non-zero return code 1: kubectl"
        self.generation = 0
        self.stderr = []

    def deploy(self, _config, variables, runner=None):
        """Render the actual role template; apply keeps existing Jobs unchanged."""
        del runner
        environment = Environment()
        environment.filters.update({"bool": bool, "string": str})
        template = environment.from_string(
            (_ROLE / "templates/job_one_file_per_job.yaml.j2").read_text(encoding="utf-8")
        )
        defaults = yaml.safe_load((_ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
        context = {key: "" for key in defaults}
        context.update({
            "app_k8s_job_deploy_app_name": variables["app_name"],
            "app_k8s_job_deploy_image": variables["image"],
            "app_k8s_job_deploy_resources_enabled": False,
            "app_k8s_job_deploy_env": [],
            "app_k8s_job_deploy_ports": [],
        })
        context.update({key: value for key, value in variables.items() if key in defaults})
        for index in range(1, variables["replicas"] + 1):
            job = yaml.safe_load(template.render(context).replace("%ITEM", str(index)))
            name = job["metadata"]["name"]
            if name in self.jobs:
                continue
            self.generation += 1
            job["metadata"]["uid"] = "job-%d" % self.generation
            job["status"] = {"active": 1}
            self.jobs[name] = job
            pod_name = "%s-pod-%d" % (name, self.generation)
            self.pods[pod_name] = {
                "metadata": {
                    "name": pod_name,
                    "uid": "pod-%d" % self.generation,
                    "labels": job["spec"]["template"]["metadata"].get("labels", {}),
                    "ownerReferences": [{"kind": "Job", "name": name,
                                         "uid": job["metadata"]["uid"], "controller": True}],
                },
                "spec": {"containers": [{"name": "image-classification"}]},
                "status": {"phase": "Running"},
            }

    def finish(self, phase="Succeeded"):
        """Mark all subscribers terminal without removing their output."""
        for job in self.jobs.values():
            if "uid" in job["metadata"]:
                job["status"] = {"conditions": [
                    {"type": "Complete" if phase == "Succeeded" else "Failed", "status": "True"}
                ]}
        for pod in self.pods.values():
            pod["status"]["phase"] = phase

    def process(self, _config, command, **_kwargs):
        """Handle only the kubectl requests needed by the lifecycle under test."""
        self.commands.append(command)
        tokens = shlex.split(command) if isinstance(command, str) else command
        if self.fail_operation and self.fail_operation in tokens:
            return [([], [self.failure])]
        if "delete" in tokens:
            name = tokens[tokens.index("job") + 1]
            del self.jobs[name]
            self.pods = {
                key: pod for key, pod in self.pods.items()
                if pod["metadata"]["ownerReferences"][0]["name"] != name
            }
            return [(['job.batch "%s" deleted' % name], self.stderr)]
        if "logs" in tokens:
            name = tokens[-1]
            return [(["retained output for " + name], self.stderr)]
        if "jobs" in tokens:
            return [([json.dumps({"items": list(self.jobs.values())})], self.stderr)]
        pods = list(self.pods.values())
        if "-l" in tokens:
            selector = tokens[tokens.index("-l") + 1]
            required = dict(item.split("=", 1) for item in selector.split(","))
            pods = [pod for pod in pods if all(
                pod["metadata"]["labels"].get(key) == value for key, value in required.items()
            )]
        if "json" in tokens:
            return [([json.dumps({"items": pods})], self.stderr)]
        rows = ["NAME STATUS"] + [
            "%s %s" % (pod["metadata"]["name"], pod["status"]["phase"]) for pod in pods
        ]
        if isinstance(command, str) and command.startswith("date"):
            rows.insert(0, "100.0")
        return [(rows, self.stderr)]


class KubernetesJobReuseTests(unittest.TestCase):
    """Exercise public worker lifecycle boundaries without a Kubernetes host."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.tempdir.cleanup)
        assignment = {
            "id": "classify", "type": "image_classification", "selector_id": "sel-classify",
            "resolved_vm_ids": [1], "resolved_resources": [
                {"vm_id": 1, "cluster_id": "cloud-1", "tier": "cloud", "index_in_cluster": 0,
                 "tags": {"tier": "cloud", "cluster": "cloud-1"}}
            ], "scope_identities": [{"kind": "selector", "selector_id": "sel-classify"}],
            "tags": {},
        }
        self.config = {
            "mode": "cloud", "timestamp": "2026-10-28_14:00:00",
            "registry": "localhost:5000", "images": {"worker": "worker:subscriber"},
            "cloud_ssh": ["cloudcontroller@10.0.0.1"],
            "infrastructure": {"base_path": self.tempdir.name, "cloud_nodes": 2,
                               "cloud_cores": 4, "edge_nodes": 0},
            "domains": {
                "software": {"modules": [{"id": "k8s", "type": "kubernetes",
                                            "config": {"cache_worker": False}}]},
                "benchmark": {"pipeline": [{
                    "id": "classify", "type": "image_classification",
                    "config": {"applications_per_worker": 1, "application_worker_cpu": 0.5,
                               "application_worker_memory": 1, "worker_ready_timeout_seconds": 2},
                }]},
            },
            "planner_snapshot": {
                "benchmark_stage_assignments": [assignment],
                "software_module_assignments": [dict(assignment, id="k8s", type="kubernetes")],
            },
        }
        self.machine = _KubernetesMachine()
        patcher = mock.patch.object(runtime_helpers, "run_kubernetes_benchmark_playbook",
                                    side_effect=self.machine.deploy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start(self):
        return runtime_helpers.start_worker(self.config, [self.machine], {})

    def _archives(self):
        return list(Path(self.tempdir.name).rglob("jobs.json"))

    def test_repeated_execution_replaces_completed_job_and_retains_old_output(self):
        """Fixed-name apply must create a fresh subscriber on every execution."""
        unrelated = copy.deepcopy(self.machine.jobs["unrelated"])
        self._start()
        first = copy.deepcopy(self.machine.jobs["image-classification-1"])
        self.machine.finish()
        self._start()
        second = self.machine.jobs["image-classification-1"]
        self.assertNotEqual(first["metadata"]["uid"], second["metadata"]["uid"])
        self.assertEqual(self.machine.jobs["unrelated"], unrelated)
        archives = self._archives()
        self.assertEqual(len(archives), 1)
        archived = json.loads(archives[0].read_text(encoding="utf-8"))
        self.assertEqual(archived[0]["metadata"]["uid"], first["metadata"]["uid"])
        self.assertTrue(list(archives[0].parent.glob("*.log")))
        output = runtime_helpers.get_worker_output(self.config, [self.machine])
        self.assertEqual(len(output), 1)
        self.assertIn("pod-2", output[0][0])
        self.machine.finish()
        runtime_helpers.wait_kubernetes_worker_completion(self.config, [self.machine])
        self._start()
        self.assertEqual(len(self._archives()), 2)

    def test_same_name_unowned_job_is_never_replaced(self):
        """A familiar app name cannot authorize cleanup of another workload."""
        self.machine.jobs["image-classification-1"] = {
            "metadata": {"name": "image-classification-1", "labels": {}},
        }
        with self.assertRaisesRegex((ValueError, RuntimeError), "own"):
            self._start()
        self.assertFalse(any("delete" in cmd for cmd in self.machine.commands))

    def test_active_owned_job_is_not_replaced(self):
        """An overlapping execution must stop without removing live work."""
        self._start()
        with self.assertRaisesRegex((ValueError, RuntimeError), "active|terminal"):
            self._start()
        self.assertFalse(self._archives())

    def test_failed_job_output_survives_replacement(self):
        """A failed prior subscriber gets the same preservation as a successful one."""
        self._start()
        self.machine.finish("Failed")
        self._start()
        self.assertEqual(len(self._archives()), 1)
        self.assertIn('"Failed"', self._archives()[0].read_text(encoding="utf-8"))

    def test_archive_log_failure_prevents_deletion(self):
        """Failed log capture must keep the original failed Job intact."""
        self._start()
        self.machine.finish("Failed")
        self.machine.fail_operation = "logs"
        with self.assertRaisesRegex(RuntimeError, "non-zero"):
            self._start()
        self.assertIn("image-classification-1", self.machine.jobs)
        self.assertFalse(any("delete" in cmd for cmd in self.machine.commands))

    def test_archive_write_failure_prevents_deletion(self):
        """A full or inaccessible archive disk cannot lead to lost evidence."""
        self._start()
        self.machine.finish()
        with mock.patch("application.runtime_helpers.os.makedirs", side_effect=OSError("full")):
            with self.assertRaisesRegex(OSError, "full"):
                self._start()
        self.assertIn("image-classification-1", self.machine.jobs)

    def test_delete_failure_is_preserved_after_archive(self):
        """Preservation success cannot suppress a subsequent cleanup failure."""
        self._start()
        self.machine.finish()
        self.machine.fail_operation = "delete"
        with self.assertRaisesRegex(RuntimeError, "non-zero"):
            self._start()
        self.assertEqual(len(self._archives()), 1)
        self.assertIn("image-classification-1", self.machine.jobs)

    def test_current_log_failure_among_multiple_pods_is_not_masked(self):
        """Every current log command must preserve its own nonzero result."""
        self.config["domains"]["benchmark"]["pipeline"][0]["config"]["applications_per_worker"] = 2
        self._start()
        self.machine.fail_operation = "image-classification-2-pod-2"
        with self.assertRaisesRegex(RuntimeError, "non-zero"):
            runtime_helpers.get_worker_output(self.config, [self.machine])

    def test_unverified_continuum_stderr_is_an_error(self):
        """A trace-looking substring cannot hide kubectl failure text."""
        self.machine.stderr = ["[CONTINUUM] arbitrary failure"]
        with self.assertRaisesRegex(RuntimeError, "arbitrary failure"):
            self._start()

    def test_verified_trace_does_not_hide_success(self):
        """The strict shared trace grammar still allows instrumented kubectl."""
        self.machine.stderr = ["[CONTINUUM] 0400"]
        self._start()
        self.assertEqual(len(self.machine.pods), 1)

    def test_readiness_rejects_terminal_fresh_subscriber(self):
        """MQTT needs a live subscriber; a completed pod cannot receive images."""
        self._start()
        for phase in ("Succeeded", "Failed"):
            with self.subTest(phase=phase):
                self.machine.finish(phase)
                with self.assertRaises((RuntimeError, SystemExit)):
                    runtime_helpers.wait_kubernetes_workers_ready(
                        self.config, [self.machine], False
                    )

    def test_empty_selection_times_out_even_with_unrelated_running_pod(self):
        """Unrelated Running pods cannot satisfy current-execution readiness."""
        self._start()
        for pod in self.machine.pods.values():
            pod["metadata"]["labels"] = {"foreign": "true"}
        with mock.patch("application.runtime_helpers.time.monotonic", side_effect=[0, 3]):
            with self.assertRaisesRegex(RuntimeError, "Timeout"):
                runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)

    def test_current_log_and_readiness_ignore_unrelated_failed_pod(self):
        """Foreign pod phases and logs must not contaminate the current result."""
        self._start()
        foreign = copy.deepcopy(next(iter(self.machine.pods.values())))
        foreign["metadata"].update(name="foreign", labels={})
        foreign["status"]["phase"] = "Failed"
        self.machine.pods["foreign"] = foreign
        runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)
        output = runtime_helpers.get_worker_output(self.config, [self.machine])
        self.assertEqual([entry[0] for entry in output], ["image-classification-1-pod-1"])

    def test_readiness_command_error_is_not_retried_as_pending(self):
        """API/transport failure must surface immediately, not become a timeout."""
        self._start()
        self.machine.fail_operation = "pods"
        with self.assertRaisesRegex(RuntimeError, "non-zero"):
            runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)


if __name__ == "__main__":
    unittest.main()
