"""Sequential MQTT Job reuse, with an inert kubectl state machine."""

import copy
import json
import itertools
from pathlib import Path
import shlex
import tempfile
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from jinja2 import Environment
import yaml

from application import application as application_module, runtime_helpers
from infrastructure import machine as machine_module
from resource_manager.endpoint import endpoint


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
                "status": {"phase": "Running", "conditions": [
                    {"type": "Ready", "status": "True"}
                ]},
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
        if "jobs" in tokens or "events" in tokens:
            items = list(self.jobs.values()) if "jobs" in tokens else []
            return [([json.dumps({"items": items})], self.stderr)]
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


class KubernetesJobReuseTests(unittest.TestCase):  # pylint: disable=too-many-public-methods
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
        for phase in ("Succeeded", "Failed", "Unknown"):
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

    def test_current_worker_output_preserves_node_order(self):
        """Worker IDs follow node order even when the API returns reversed pods."""
        self.config["infrastructure"]["cloud_nodes"] = 3
        for assignments in self.config["planner_snapshot"].values():
            assignments[0]["resolved_vm_ids"] = [1, 2]
            assignments[0]["resolved_resources"] = [
                {"vm_id": index, "cluster_id": "cloud-1", "tier": "cloud",
                 "index_in_cluster": index - 1,
                 "tags": {"tier": "cloud", "cluster": "cloud-1"}}
                for index in (1, 2)
            ]
        self._start()
        self.machine.pods["image-classification-1-pod-1"]["spec"]["nodeName"] = "cloud2"
        self.machine.pods["image-classification-2-pod-2"]["spec"]["nodeName"] = "cloud1"
        stale = copy.deepcopy(self.machine.pods["image-classification-1-pod-1"])
        stale["metadata"]["name"] = "stale-pod"
        stale["metadata"]["labels"]["continuum.io/benchmark-execution"] = "previous-execution"
        self.machine.pods["stale-pod"] = stale

        output = runtime_helpers.get_worker_output(self.config, [self.machine])
        descriptions = runtime_helpers.get_worker_output(
            self.config, [self.machine], get_description=True
        )
        self.assertEqual(output, [
            ["image-classification-2-pod-2", ["retained output for image-classification-2-pod-2"]],
            ["image-classification-1-pod-1", ["retained output for image-classification-1-pod-1"]],
        ])
        records = [json.loads("\n".join(lines)) for lines in descriptions]
        self.assertEqual(
            [(pod["metadata"]["name"], pod["spec"]["nodeName"]) for pod in records],
            [("image-classification-2-pod-2", "cloud1"),
             ("image-classification-1-pod-1", "cloud2")],
        )

    def test_readiness_command_error_is_not_retried_as_pending(self):
        """API/transport failure must surface immediately, not become a timeout."""
        self._start()
        self.machine.fail_operation = "pods"
        with self.assertRaisesRegex(RuntimeError, "non-zero"):
            runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)

    def _wait_sequence(self, snapshots, completion=False):
        """Poll changing API snapshots without real sleeps."""
        with mock.patch.object(runtime_helpers, "_execution_pods", side_effect=snapshots), \
                mock.patch.object(runtime_helpers.time, "sleep") as sleep:
            runtime_helpers._wait_kubernetes_execution(  # pylint: disable=protected-access
                self.config, [self.machine], completion=completion
            )
        return sleep.call_count

    def test_missing_unready_then_ready_subscriber(self):
        """Publishers must wait through absent pods and missing/false Ready conditions."""
        self._start()
        ready = copy.deepcopy(next(iter(self.machine.pods.values())))
        unready = copy.deepcopy(ready)
        unready["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
        missing = copy.deepcopy(ready)
        missing["status"].pop("conditions")
        boolean = copy.deepcopy(ready)
        boolean["status"]["conditions"][0]["status"] = True
        self.assertEqual(self._wait_sequence(
            [[], [missing], [unready], [boolean], [ready]]
        ), 4)

    def test_completion_succeeds_first_poll_without_ready(self):
        """Completed subscribers need no live readiness condition."""
        self._start()
        self.machine.finish()
        pod = copy.deepcopy(next(iter(self.machine.pods.values())))
        pod["status"].pop("conditions")
        self.assertEqual(self._wait_sequence([[pod]], completion=True), 0)

    def test_image_pull_recovery_and_init_wait_changes_are_logged_once(self):
        """Kubernetes retries images; log changes, including init state and recovery."""
        self._start()
        ready = copy.deepcopy(next(iter(self.machine.pods.values())))
        pending = copy.deepcopy(ready)
        pending["status"] = {"phase": "Pending", "initContainerStatuses": [
            {"name": "init", "state": {"waiting": {"reason": "ErrImagePull",
                                                   "message": "init image unavailable"}}}
        ]}
        backoff = copy.deepcopy(pending)
        backoff["status"].pop("initContainerStatuses")
        backoff["status"]["containerStatuses"] = [
            {"name": "subscriber", "state": {"waiting": {"reason": "ImagePullBackOff",
                                                         "message": "retrying image"}}}
        ]
        with self.assertLogs(level="INFO") as logs:
            self.assertEqual(self._wait_sequence([
                [pending], [pending], [backoff], [ready]
            ]), 3)
        output = "\n".join(logs.output)
        self.assertEqual(output.count("ErrImagePull"), 1)
        self.assertIn("init image unavailable", output)
        self.assertIn("ImagePullBackOff", output)
        self.assertIn("Running", output)

    def test_timeout_collects_bounded_uid_scoped_events(self):
        """Persistent image failures retain only current-pod event excerpts."""
        self._start()
        pod = next(iter(self.machine.pods.values()))
        pod["status"] = {"phase": "Pending", "containerStatuses": [
            {"name": "subscriber", "state": {"waiting": {"reason": "ImagePullBackOff"}}}
        ]}
        events = [{"reason": "Failed", "message": "bad image " + str(index)}
                  for index in range(20)]
        with mock.patch.object(runtime_helpers, "_kubectl_items", return_value=events) as query, \
                mock.patch.object(runtime_helpers, "_execution_pods", return_value=[pod]), \
                mock.patch.object(runtime_helpers.time, "monotonic",
                                  side_effect=itertools.chain([0, 0], itertools.repeat(3))), \
                self.assertLogs(level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "Timeout"):
                runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)
        args = query.call_args.args[2]
        self.assertIn("events", args)
        self.assertIn("--field-selector=involvedObject.uid=" + pod["metadata"]["uid"], args)
        self.assertIn("--request-timeout=5s", args)
        output = "\n".join(logs.output)
        self.assertIn("ImagePullBackOff", output)
        self.assertIn("bad image 19", output)
        self.assertNotIn("bad image 0", output)

    def test_event_diagnostic_failure_preserves_primary_error(self):
        """An API, transport or JSON failure during diagnostics is secondary."""
        self._start()
        pod = next(iter(self.machine.pods.values()))
        for phase in ("Failed", "Pending"):
            pod["status"]["phase"] = phase
            for failure in (RuntimeError("event API unavailable"), ValueError("invalid JSON")):
                with self.subTest(phase=phase, failure=failure), \
                        mock.patch.object(runtime_helpers, "_execution_pods", return_value=[pod]), \
                        mock.patch.object(runtime_helpers, "_kubectl_items", side_effect=failure), \
                        mock.patch.object(runtime_helpers.time, "monotonic",
                                          side_effect=itertools.chain([0, 0],
                                                                      itertools.repeat(3))):
                    with self.assertRaisesRegex(RuntimeError, "invalid status|Timeout"):
                        runtime_helpers.wait_kubernetes_workers_ready(
                            self.config, [self.machine], False
                        )

    def test_primary_pod_api_failure_does_not_collect_events(self):
        """Main-query failure still surfaces immediately without diagnostic calls."""
        self._start()
        with mock.patch.object(runtime_helpers, "_execution_pods",
                               side_effect=RuntimeError("API")), \
                mock.patch.object(runtime_helpers, "_kubectl_items") as query:
            with self.assertRaisesRegex(RuntimeError, "API"):
                runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)
        query.assert_not_called()

    def test_all_selected_subscribers_must_be_ready(self):
        """One ready subscriber cannot hide an unready peer."""
        self._start()
        ready = copy.deepcopy(next(iter(self.machine.pods.values())))
        peer = copy.deepcopy(ready)
        peer["metadata"].update(name="peer", uid="peer-uid")
        peer["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
        self.config["_kubernetes_worker_execution"]["count"] = 2
        self.assertEqual(self._wait_sequence([[ready, peer], [ready, ready]]), 1)

    def test_event_excerpt_caps_requests_and_skips_missing_uids(self):
        """Diagnostic work is bounded and never falls back to unscoped events."""
        self._start()
        pod = next(iter(self.machine.pods.values()))
        pods = [copy.deepcopy(pod) for _index in range(5)]
        for index, selected in enumerate(pods):
            selected["metadata"]["uid"] = "selected-%d" % index
        events = [{"reason": "Failed", "message": "x" * 2000}] * 20
        with mock.patch.object(runtime_helpers, "_kubectl_items", return_value=events) as query, \
                self.assertLogs(level="WARNING") as logs:
            runtime_helpers._log_kubernetes_pod_events(  # pylint: disable=protected-access
                self.config, [self.machine], pods
            )
        self.assertEqual(query.call_count, 3)
        self.assertEqual(len(logs.output), 30)
        self.assertNotIn("x" * 501, "\n".join(logs.output))
        pod["metadata"].pop("uid")
        with mock.patch.object(runtime_helpers, "_kubectl_items") as query:
            runtime_helpers._log_kubernetes_pod_events(  # pylint: disable=protected-access
                self.config, [self.machine], [pod]
            )
        query.assert_not_called()

    def test_primary_query_timeout_uses_real_process_and_preserves_stderr(self):
        """A stuck transport returns a primary error without starting event diagnostics."""
        self._start()
        self.config["domains"]["benchmark"]["pipeline"][0]["config"][
            "worker_ready_timeout_seconds"
        ] = 1
        local = machine_module.Machine("local", True)

        def blocked_query(_config, command, **kwargs):
            self.assertNotIn("events", command)
            self.assertGreater(kwargs.get("timeout_seconds", 0), 0)
            self.assertLessEqual(kwargs["timeout_seconds"], 1)
            return local.process({}, [sys.executable, "-u", "-c",
                                     "import sys,time; print('transport detail',file=sys.stderr); "
                                     "time.sleep(20)"],
                                 timeout_seconds=kwargs["timeout_seconds"])

        started = time.monotonic()
        with mock.patch.object(self.machine, "process", side_effect=blocked_query):
            with self.assertRaisesRegex(RuntimeError, "transport detail[\\s\\S]*timed out"):
                runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)
        self.assertLess(time.monotonic() - started, 4)

    def test_exhausted_polling_budget_does_not_start_a_query(self):
        """There is no subprocess launch after the polling deadline has expired."""
        self._start()
        with mock.patch.object(runtime_helpers.time, "monotonic", side_effect=[0, 3]), \
                mock.patch.object(runtime_helpers, "_execution_pods", return_value=[]) as query:
            with self.assertRaisesRegex(RuntimeError, "Timeout"):
                runtime_helpers.wait_kubernetes_workers_ready(self.config, [self.machine], False)
        query.assert_not_called()

    def test_event_requests_share_one_diagnostic_budget(self):
        """Later pods receive only the remaining diagnostic execution budget."""
        self._start()
        pod = next(iter(self.machine.pods.values()))
        now = [0]
        budgets = []

        def events(_config, _machines, _arguments, timeout_seconds=None):
            budgets.append(timeout_seconds)
            now[0] += 6  # Five-second timeout plus one second of cleanup overhead.
            return []

        with mock.patch.object(runtime_helpers.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(runtime_helpers, "_kubectl_items", side_effect=events):
            runtime_helpers._log_kubernetes_pod_events(  # pylint: disable=protected-access
                self.config, [self.machine], [pod, pod, pod]
            )
        self.assertEqual(budgets, [5, 5, 3])

    def test_public_kube_unready_or_terminal_worker_prevents_publisher_start(self):
        """Actual start_worker/readiness composition gates the publisher boundary."""
        for phase in ("Running", "Succeeded"):
            with self.subTest(phase=phase):
                self.machine.jobs = {}
                self.machine.pods = {}
                self.config["module"] = {"application": mock.Mock()}
                self.config["module"]["application"].start_worker.return_value = {}
                self.config["endpoint_ssh"] = ["endpoint0@192.0.2.1"]
                now = SimpleNamespace(value=0)

                def deploy(config, variables, runner=None, phase=phase):
                    self.machine.deploy(config, variables, runner=runner)
                    for pod in self.machine.pods.values():
                        pod["status"] = {"phase": phase, "conditions": [
                            {"type": "Ready", "status": "False"}
                        ]}

                def pause(seconds, clock=now):
                    clock.value += seconds

                with mock.patch.object(runtime_helpers, "run_kubernetes_benchmark_playbook",
                                       side_effect=deploy), \
                        mock.patch.object(endpoint, "start_endpoint", side_effect=AssertionError(
                            "Publisher started before subscriber readiness"
                        )) as publisher, \
                        mock.patch.object(runtime_helpers.time, "monotonic",
                                          side_effect=lambda clock=now: clock.value), \
                        mock.patch.object(runtime_helpers.time, "sleep",
                                          side_effect=pause):
                    with self.assertRaisesRegex(RuntimeError, "Timeout|invalid status"):
                        application_module.kube(self.config, [self.machine])
                publisher.assert_not_called()
                self.config["module"]["application"].gather_worker_metrics.assert_not_called()

    def test_public_kube_publisher_failure_prevents_completion_and_metrics(self):
        """A wrong publisher container cannot advance into worker results processing."""
        self.config["module"] = {"application": mock.Mock()}
        self.config["module"]["application"].start_worker.return_value = {}
        self.config["endpoint_ssh"] = ["endpoint0@192.0.2.1"]
        self.config["infrastructure"]["provider"] = "qemu"
        self.config["domains"]["benchmark"]["pipeline"][0]["config"]["duration"] = 30
        original_process = self.machine.process

        def process(config, command, **options):
            if isinstance(command, str) and command.startswith("docker container ls"):
                return [(["abc: Exited (0) 1 second ago endpoint00"], [])]
            return original_process(config, command, **options)

        with mock.patch.object(self.machine, "process", side_effect=process), \
                mock.patch.object(endpoint, "start_endpoint", return_value=["endpoint0"]), \
                mock.patch.object(endpoint.time, "sleep"):
            with self.assertRaises(SystemExit):
                application_module.kube(self.config, [self.machine])
        pod_queries = [command for command in self.machine.commands
                       if isinstance(command, list) and "pods" in command]
        self.assertEqual(len(pod_queries), 1)
        self.config["module"]["application"].gather_worker_metrics.assert_not_called()
        self.config["module"]["application"].gather_endpoint_metrics.assert_not_called()


if __name__ == "__main__":
    unittest.main()
