from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from events import JsonlEventWriter  # noqa: E402
from opendt_observer import (  # noqa: E402
    OpenDTObserver,
    ResourceSampler,
    ResourceSnapshot,
    _state_job_record,
    build_cluster_state_record,
    build_workload_record,
    extract_resource_capacity,
    extract_resource_requests,
    parse_cpu_cores,
    parse_memory_mb,
    pod_execution_interval,
)


class RecordingWriter:
    def __init__(self):
        self.records = []

    def emit(self, record):
        self.records.append(record)


class FakeSampler:
    def __init__(self, snapshots=None):
        self.snapshots = snapshots or []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def take_snapshots(self, _job_uid):
        snapshots, self.snapshots = self.snapshots, []
        return snapshots


class FakeBatchApi:
    def __init__(self, jobs):
        self.jobs = jobs

    def list_namespaced_job(self, **_kwargs):
        return SimpleNamespace(
            items=self.jobs, metadata=SimpleNamespace(resource_version="17")
        )


class EmptyWatch:
    def stream(self, *_args, **_kwargs):
        return iter(())


class FakePrometheus:
    def __init__(self):
        self.queries = []

    def query(self, promql, eval_time):
        self.queries.append(promql)
        if "timestamp(" in promql:
            value = str(datetime(2026, 9, 4, 10, 0, 2, tzinfo=timezone.utc).timestamp())
        elif "memory_working_set" in promql:
            value = "268435456"
        else:
            value = "0.5"
        return [
            {
                "metric": {"pod": "pod-job-uid"},
                "value": [0, value],
            }
        ]


class FakeCoreApi:
    def __init__(self, pods=None, nodes=None, fail_nodes=False):
        self.pods = pods or []
        self.nodes = nodes or []
        self.fail_nodes = fail_nodes

    def list_namespaced_pod(self, **_kwargs):
        return SimpleNamespace(items=self.pods)

    def list_node(self):
        if self.fail_nodes:
            raise RuntimeError("node list failed")
        return SimpleNamespace(items=self.nodes)


def demo_job(*, state="Complete", uid="job-uid", include_lineage=True):
    created = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    started = created + timedelta(seconds=1)
    finished = started + timedelta(milliseconds=2200)
    labels = {
        "continuum.atlarge.nl/workload": "image-batch",
        "continuum.atlarge.nl/request-id": "a" * 32,
    }
    annotations = {
        "continuum.atlarge.nl/run-id": "run-test",
        "continuum.atlarge.nl/workload-run-id": "workload-test",
        "continuum.atlarge.nl/endpoint-batch-id": "b" * 32,
        "continuum.atlarge.nl/image-count": "4",
        "continuum.atlarge.nl/payload-bytes": "8192",
        "continuum.atlarge.nl/inference-repetitions": "8",
    }
    if not include_lineage:
        annotations.pop("continuum.atlarge.nl/run-id")
    condition = SimpleNamespace(
        type=state,
        status="True",
        last_transition_time=finished,
    )
    resources = SimpleNamespace(
        requests={"cpu": "500m", "memory": "256Mi"},
        limits={"cpu": "1", "memory": "512Mi"},
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            uid=uid,
            name="image-batch-aaaaaaaaaaaa",
            namespace="fns-demo",
            creation_timestamp=created,
            labels=labels,
            annotations=annotations,
        ),
        status=SimpleNamespace(
            conditions=[condition],
            start_time=started,
            completion_time=finished if state == "Complete" else None,
        ),
        spec=SimpleNamespace(
            parallelism=1,
            template=SimpleNamespace(
                spec=SimpleNamespace(containers=[SimpleNamespace(resources=resources)])
            ),
        ),
    )


def demo_pod(
    *,
    job_uid="job-uid",
    phase="Running",
    node_name="cloud1",
    execution_start=None,
    execution_finish=None,
    classifier_state=None,
):
    container_statuses = []
    if classifier_state is not None:
        state = SimpleNamespace(waiting=None, running=None, terminated=None)
        if classifier_state == "waiting":
            state.waiting = SimpleNamespace(reason="ContainerCreating")
        elif classifier_state == "running":
            state.running = SimpleNamespace(started_at=execution_start)
        elif classifier_state == "terminated":
            state.terminated = SimpleNamespace(
                started_at=execution_start, finished_at=execution_finish
            )
        else:
            raise ValueError(f"unsupported classifier state: {classifier_state}")
        container_statuses.append(SimpleNamespace(name="classifier", state=state))
    elif execution_start is not None and execution_finish is not None:
        container_statuses.append(
            SimpleNamespace(
                name="classifier",
                state=SimpleNamespace(
                    waiting=None,
                    running=None,
                    terminated=SimpleNamespace(
                        started_at=execution_start, finished_at=execution_finish
                    )
                )
            )
        )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            uid=f"pod-{job_uid}",
            name=f"pod-{job_uid}",
            owner_references=[
                SimpleNamespace(kind="Job", controller=True, uid=job_uid)
            ],
        ),
        status=SimpleNamespace(phase=phase, container_statuses=container_statuses),
        spec=SimpleNamespace(node_name=node_name),
    )


def demo_node(name, *, uid=None, ready=True, unschedulable=False, control_plane=False):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            uid=uid or f"uid-{name}",
            name=name,
            labels=(
                {"node-role.kubernetes.io/control-plane": ""}
                if control_plane
                else {"kubernetes.io/hostname": name}
            ),
        ),
        status=SimpleNamespace(
            conditions=[
                SimpleNamespace(type="Ready", status="True" if ready else "False")
            ],
            allocatable={"cpu": "4", "memory": "16Gi"},
        ),
        spec=SimpleNamespace(unschedulable=unschedulable),
    )


class OpenDTObserverTests(unittest.TestCase):
    def test_finalization_waits_for_collection_and_raw_flush_then_closes_uid(self):
        for blocked_stage in ("prometheus", "raw_flush"):
            with self.subTest(blocked_stage=blocked_stage):
                blocked = threading.Event()
                release = threading.Event()
                draining = threading.Event()
                drained = threading.Event()
                interval_lookup = threading.Event()
                finish_interval = threading.Event()

                def pause():
                    blocked.set()
                    if not release.wait(5):
                        raise AssertionError("collection was not released")

                class BlockingPrometheus(FakePrometheus):
                    sample_offset = 0

                    def query(self, promql, eval_time):
                        if blocked_stage == "prometheus" and not blocked.is_set():
                            pause()
                        result = super().query(promql, eval_time)
                        if "timestamp(" in promql:
                            result[0]["value"][1] = str(
                                float(result[0]["value"][1]) + self.sample_offset
                            )
                        return result

                class BlockingWriter(RecordingWriter):
                    def emit(self, record):
                        if blocked_stage == "raw_flush" and not blocked.is_set():
                            pause()
                        super().emit(record)

                finished = demo_job()
                raw, workload = BlockingWriter(), RecordingWriter()
                prom = BlockingPrometheus()
                sampler = ResourceSampler(
                    batch_api=FakeBatchApi([demo_job(state="Running")]),
                    core_api=FakeCoreApi(
                        pods=[
                            demo_pod(
                                execution_start=finished.status.start_time,
                                execution_finish=finished.status.completion_time,
                            )
                        ],
                        nodes=[demo_node("cloud1")],
                    ),
                    prometheus=prom,
                    namespace="fns-demo",
                    label_selector="x",
                    run_id="run-test",
                    state_interval_seconds=1,
                    resource_interval_seconds=5,
                    snapshot_writer=raw,
                    state_writer=RecordingWriter(),
                    emit_diagnostic=lambda *_args: None,
                )
                observer = OpenDTObserver(
                    batch_api=FakeBatchApi([]),
                    watch_factory=EmptyWatch,
                    sampler=sampler,
                    workload_writer=workload,
                    diagnostic_writer=RecordingWriter(),
                    namespace="fns-demo",
                    label_selector="x",
                    run_id="run-test",
                    cpu_frequency_mhz=2400,
                )
                original_take = sampler.take_snapshots
                original_interval = sampler.execution_interval

                def take(uid):
                    draining.set()
                    samples = original_take(uid)
                    drained.set()
                    return samples

                def interval(uid, request_id):
                    interval_lookup.set()
                    if not finish_interval.wait(5):
                        raise AssertionError("interval lookup was not released")
                    return original_interval(uid, request_id)

                sampler.take_snapshots = take
                sampler.execution_interval = interval
                errors = []

                def run(action):
                    try:
                        action()
                    except Exception as exc:
                        errors.append(exc)

                collector = threading.Thread(target=run, args=(sampler.collect_once,))
                finalizer = threading.Thread(
                    target=run, args=(lambda: observer.handle_job(finished),)
                )
                collector.start()
                try:
                    self.assertTrue(blocked.wait(5))
                    finalizer.start()
                    self.assertTrue(draining.wait(5))
                    self.assertFalse(drained.wait(0.1))
                    self.assertEqual(workload.records, [])
                    release.set()
                    collector.join(5)
                    self.assertFalse(collector.is_alive())
                    self.assertTrue(interval_lookup.wait(5))
                    self.assertEqual(len(raw.records), 1)
                    # Stale active state and a new, valid source timestamp must
                    # not add evidence after the terminal sample set is closed.
                    prom.sample_offset = 1
                    sampler.collect_once()
                    self.assertEqual(len(raw.records), 1)
                    self.assertEqual(workload.records, [])
                finally:
                    release.set()
                    finish_interval.set()
                    collector.join(5)
                    if finalizer.ident is not None:
                        finalizer.join(5)
                self.assertFalse(finalizer.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(workload.records), 1)
                record = workload.records[0]
                self.assertEqual(
                    record["source"]["resource_sample_count"], len(raw.records)
                )
                self.assertTrue(record["task"]["fragments"])
                self.assertNotIn("job-uid", sampler._snapshots)
                self.assertFalse(observer.handle_job(finished))

    def test_task_uses_worker_container_interval_not_job_queue_time(self):
        job = demo_job()
        execution_start = job.status.start_time + timedelta(seconds=1)
        execution_finish = execution_start + timedelta(seconds=1)
        pod = demo_pod(
            execution_start=execution_start, execution_finish=execution_finish
        )
        self.assertEqual(
            pod_execution_interval([pod], "job-uid"),
            (execution_start, execution_finish),
        )
        snapshots = [
            ResourceSnapshot(
                "job-uid",
                job.metadata.name,
                "fns-demo",
                execution_start + timedelta(milliseconds=500),
                0.5,
                128.0,
            )
        ]
        record = build_workload_record(
            job,
            task_id=1,
            snapshots=snapshots,
            cpu_frequency_mhz=2400,
            execution_start_time=execution_start,
            execution_finish_time=execution_finish,
        )
        self.assertEqual(record["task"]["duration"], 1000)
        self.assertEqual(
            sum(item["duration"] for item in record["task"]["fragments"]), 1000
        )
        self.assertEqual(
            record["source"]["completion_time"],
            job.status.completion_time.isoformat(),
        )

    def test_kubernetes_resource_quantities(self):
        self.assertEqual(parse_cpu_cores("500m"), 0.5)
        self.assertEqual(parse_cpu_cores("1"), 1.0)
        self.assertEqual(parse_memory_mb("512Mi"), 512.0)
        self.assertEqual(parse_memory_mb("1Gi"), 1024.0)
        self.assertEqual(extract_resource_capacity(demo_job()), (1, 512))
        self.assertEqual(extract_resource_requests(demo_job()), (0.5, 256.0))

    def test_builds_opendt_task_and_duration_covering_fragments(self):
        job = demo_job()
        start = job.status.start_time
        snapshots = [
            ResourceSnapshot(
                "job-uid",
                job.metadata.name,
                "fns-demo",
                start + timedelta(seconds=1),
                0.5,
                128.0,
            ),
            ResourceSnapshot(
                "job-uid",
                job.metadata.name,
                "fns-demo",
                start + timedelta(seconds=2),
                1.0,
                256.0,
            ),
        ]
        record = build_workload_record(
            job, task_id=7, snapshots=snapshots, cpu_frequency_mhz=2400
        )

        self.assertEqual(record["message_type"], "task")
        self.assertEqual(
            set(record["task"]),
            {
                "id",
                "submission_time",
                "duration",
                "cpu_count",
                "cpu_capacity",
                "mem_capacity",
                "fragments",
            },
        )
        self.assertEqual(record["task"]["id"], 7)
        self.assertEqual(record["task"]["duration"], 2200)
        self.assertEqual(record["task"]["cpu_count"], 1)
        self.assertEqual(record["task"]["cpu_capacity"], 2400.0)
        self.assertEqual(record["task"]["mem_capacity"], 512)
        self.assertEqual(
            sum(fragment["duration"] for fragment in record["task"]["fragments"]),
            2200,
        )
        self.assertEqual(
            [fragment["cpu_usage"] for fragment in record["task"]["fragments"]],
            [1200.0, 2400.0, 2400.0],
        )
        self.assertTrue(
            all(
                set(fragment) == {"id", "duration", "cpu_count", "cpu_usage"}
                for fragment in record["task"]["fragments"]
            )
        )
        self.assertEqual(record["source"]["kubernetes_job_uid"], "job-uid")
        self.assertEqual(record["source"]["request_id"], "a" * 32)
        self.assertEqual(record["source"]["workload_run_id"], "workload-test")
        self.assertEqual(record["source"]["inference_repetitions"], 8)
        self.assertEqual(record["source"]["inference_invocation_count"], 32)
        self.assertEqual(record["source"]["sampling_quality"], "sampled")

    def test_missing_samples_emit_degraded_task_and_duplicate_is_ignored(self):
        workload = RecordingWriter()
        diagnostics = RecordingWriter()
        observer = OpenDTObserver(
            batch_api=FakeBatchApi([]),
            watch_factory=EmptyWatch,
            sampler=FakeSampler(),
            workload_writer=workload,
            diagnostic_writer=diagnostics,
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            cpu_frequency_mhz=2400,
        )
        job = demo_job()

        conditions = job.status.conditions
        job.status.conditions = []
        self.assertFalse(observer.handle_job(job))
        self.assertEqual(workload.records, [])
        job.status.conditions = conditions
        self.assertTrue(observer.handle_job(job))
        self.assertFalse(observer.handle_job(job))
        self.assertEqual(len(workload.records), 1)
        self.assertEqual(workload.records[0]["task"]["fragments"], [])
        self.assertEqual(
            workload.records[0]["source"]["sampling_quality"],
            "degraded_no_samples",
        )

    def test_failed_and_malformed_jobs_only_emit_diagnostics(self):
        workload = RecordingWriter()
        diagnostics = RecordingWriter()
        observer = OpenDTObserver(
            batch_api=FakeBatchApi([]),
            watch_factory=EmptyWatch,
            sampler=FakeSampler(),
            workload_writer=workload,
            diagnostic_writer=diagnostics,
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            cpu_frequency_mhz=2400,
        )

        observer.handle_job(demo_job(state="Failed", uid="failed-uid"))
        observer.handle_job(demo_job(uid="malformed-uid", include_lineage=False))

        self.assertEqual(workload.records, [])
        self.assertEqual(
            [record["event_type"] for record in diagnostics.records],
            ["job.failed", "job.malformed"],
        )

    def test_jsonl_writer_appends_complete_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "workload.jsonl"
            writer = JsonlEventWriter(path)
            writer.emit({"message_type": "task", "task": {"id": 1}})
            writer.emit({"message_type": "task", "task": {"id": 2}})
            raw = path.read_bytes()

            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(
                [json.loads(line)["task"]["id"] for line in raw.splitlines()],
                [1, 2],
            )

    def test_cluster_state_separates_queued_active_and_worker_availability(self):
        active = demo_job(uid="active-uid")
        active.status.conditions = []
        active.status.completion_time = None
        queued = demo_job(uid="queued-uid")
        queued.status.conditions = []
        queued.status.completion_time = None
        observed_at = datetime(2026, 9, 4, 10, 1, tzinfo=timezone.utc)

        record = build_cluster_state_record(
            [queued, demo_job(uid="completed-uid"), active],
            [
                demo_pod(
                    job_uid="active-uid",
                    phase="Running",
                    node_name="cloud2",
                    classifier_state="running",
                    execution_start=active.status.start_time,
                ),
                demo_pod(
                    job_uid="queued-uid",
                    phase="Pending",
                    node_name=None,
                    classifier_state="waiting",
                ),
            ],
            [
                demo_node("cloud0", control_plane=True),
                demo_node("cloud1"),
                demo_node("cloud2", ready=False),
                demo_node("cloud3", unschedulable=True),
            ],
            run_id="run-test",
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            observed_at=observed_at,
        )

        self.assertEqual(record["message_type"], "cluster_state")
        self.assertEqual(record["counts"]["queued_jobs"], 1)
        self.assertEqual(record["counts"]["active_jobs"], 1)
        self.assertEqual(record["counts"]["workers"], 3)
        self.assertEqual(record["counts"]["ready_schedulable_workers"], 1)
        self.assertEqual(
            record["jobs"]["active"][0]["kubernetes_job_uid"], "active-uid"
        )
        self.assertEqual(record["jobs"]["active"][0]["node_name"], "cloud2")
        self.assertEqual(
            record["jobs"]["queued"][0]["kubernetes_job_uid"], "queued-uid"
        )
        self.assertEqual(
            [worker["node_name"] for worker in record["workers"]],
            ["cloud1", "cloud2", "cloud3"],
        )

    def test_running_container_start_is_distinct_from_job_start(self):
        job = demo_job()
        job.status.conditions = []
        actual = job.status.start_time + timedelta(seconds=20)
        pod = demo_pod(
            phase="Running", classifier_state="running", execution_start=actual
        )
        record = build_cluster_state_record(
            [job],
            [pod],
            [],
            run_id="run-test",
            namespace="fns-demo",
            label_selector="test",
            observed_at=actual,
        )
        active = record["jobs"]["active"][0]
        self.assertEqual(active["execution_state"], "running")
        self.assertEqual(active["execution_start_time"], actual.isoformat())
        self.assertIsNone(active["execution_finish_time"])
        self.assertNotEqual(active["execution_start_time"], active["start_time"])

    def test_waiting_classifier_stays_queued_while_pod_is_running(self):
        job = demo_job()
        job.status.conditions = []
        pod = demo_pod(phase="Running", classifier_state="waiting")
        observed_at = datetime(2026, 9, 4, 10, 1, tzinfo=timezone.utc)

        record = build_cluster_state_record(
            [job],
            [pod],
            [],
            run_id="run-test",
            namespace="fns-demo",
            label_selector="test",
            observed_at=observed_at,
        )

        self.assertEqual(record["counts"]["queued_jobs"], 1)
        self.assertEqual(record["counts"]["active_jobs"], 0)
        queued = record["jobs"]["queued"][0]
        self.assertEqual(queued["execution_state"], "waiting")
        self.assertIsNone(queued["execution_start_time"])
        self.assertIsNone(queued["execution_finish_time"])

    def test_unknown_classifier_state_is_explicit_on_active_running_pod(self):
        job = demo_job()
        job.status.conditions = []
        pod = demo_pod(phase="Running")
        observed_at = datetime(2026, 9, 4, 10, 1, tzinfo=timezone.utc)

        record = build_cluster_state_record(
            [job],
            [pod],
            [],
            run_id="run-test",
            namespace="fns-demo",
            label_selector="test",
            observed_at=observed_at,
        )

        self.assertEqual(record["counts"]["queued_jobs"], 0)
        self.assertEqual(record["counts"]["active_jobs"], 1)
        active = record["jobs"]["active"][0]
        self.assertEqual(active["execution_state"], "unknown")
        self.assertIsNone(active["execution_start_time"])
        self.assertIsNone(active["execution_finish_time"])

    def test_terminated_classifier_leaves_pressure_while_pod_is_running(self):
        job = demo_job()
        job.status.conditions = []
        execution_start = job.status.start_time + timedelta(seconds=20)
        execution_finish = execution_start + timedelta(seconds=5)
        pod = demo_pod(
            phase="Running",
            classifier_state="terminated",
            execution_start=execution_start,
            execution_finish=execution_finish,
        )

        state, state_job = _state_job_record(job, [pod])
        record = build_cluster_state_record(
            [job],
            [pod],
            [],
            run_id="run-test",
            namespace="fns-demo",
            label_selector="test",
            observed_at=execution_finish,
        )

        self.assertEqual(state, "finished")
        self.assertEqual(state_job["execution_state"], "terminated")
        self.assertEqual(
            state_job["execution_start_time"], execution_start.isoformat()
        )
        self.assertEqual(
            state_job["execution_finish_time"], execution_finish.isoformat()
        )
        self.assertEqual(record["counts"]["queued_jobs"], 0)
        self.assertEqual(record["counts"]["active_jobs"], 0)
        self.assertEqual(record["jobs"], {"queued": [], "active": []})

    def test_first_observation_includes_terminal_jobs_and_is_deduplicated(self):
        diagnostics = []
        job = demo_job(state="Failed")
        sampler = ResourceSampler(
            batch_api=FakeBatchApi([job]),
            core_api=FakeCoreApi(),
            prometheus=FakePrometheus(),
            namespace="fns-demo",
            label_selector="test",
            run_id="run-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=RecordingWriter(),
            state_writer=RecordingWriter(),
            emit_diagnostic=lambda event, details: diagnostics.append((event, details)),
        )
        sampler.observe_job(job)
        sampler.collect_once(collect_resources=False)
        observations = [
            details for event, details in diagnostics if event == "job.observed"
        ]
        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0]["creation_time"],
            job.metadata.creation_timestamp.isoformat(),
        )
        self.assertEqual(observations[0]["kubernetes_job_uid"], job.metadata.uid)

    def test_terminal_pods_leave_pressure_before_job_completion(self):
        job = demo_job()
        job.status.conditions = []
        job.status.completion_time = None
        for phase, expected in (
            (None, (1, 0)),
            ("Pending", (1, 0)),
            ("Running", (0, 1)),
            ("Succeeded", (0, 0)),
            ("Failed", (0, 0)),
        ):
            with self.subTest(phase=phase):
                record = build_cluster_state_record(
                    [job],
                    [demo_pod(phase=phase)] if phase else [],
                    [demo_node("cloud1")],
                    run_id="run-test",
                    namespace="fns-demo",
                    label_selector="continuum.atlarge.nl/workload=image-batch",
                    observed_at=datetime(2026, 9, 4, 10, 1, tzinfo=timezone.utc),
                )
                self.assertEqual(
                    (record["counts"]["queued_jobs"], record["counts"]["active_jobs"]),
                    expected,
                )
                self.assertEqual(
                    (len(record["jobs"]["queued"]), len(record["jobs"]["active"])),
                    expected,
                )
                self.assertEqual(record["workers"][0]["allocatable_cpu_count"], 4.0)

    def test_terminal_pod_does_not_hide_another_pending_or_running_pod(self):
        job = demo_job()
        job.status.conditions = []
        job.status.completion_time = None
        finished = demo_pod(phase="Failed")
        finished.metadata.name = "a-finished"
        for phase, group in (("Pending", "queued"), ("Running", "active")):
            with self.subTest(phase=phase):
                live = demo_pod(
                    phase=phase,
                    classifier_state=(
                        "waiting" if phase == "Pending" else "running"
                    ),
                    execution_start=(
                        job.status.start_time if phase == "Running" else None
                    ),
                )
                live.metadata.name = "z-live"
                record = build_cluster_state_record(
                    [job],
                    [finished, live],
                    [],
                    run_id="run-test",
                    namespace="fns-demo",
                    label_selector="continuum.atlarge.nl/workload=image-batch",
                    observed_at=datetime(2026, 9, 4, 10, 1, tzinfo=timezone.utc),
                )
                self.assertEqual(record["counts"][f"{group}_jobs"], 1)
                self.assertEqual(record["jobs"][group][0]["pod_name"], "z-live")

    def test_resource_sampler_records_only_active_demo_jobs(self):
        active = demo_job()
        active.status.conditions = []
        active.status.completion_time = None
        snapshots = RecordingWriter()
        states = RecordingWriter()
        prometheus = FakePrometheus()
        sampler = ResourceSampler(
            batch_api=FakeBatchApi([active, demo_job(uid="completed-uid")]),
            core_api=FakeCoreApi(
                pods=[demo_pod()],
                nodes=[demo_node("cloud0", control_plane=True), demo_node("cloud1")],
            ),
            prometheus=prometheus,
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=snapshots,
            state_writer=states,
            emit_diagnostic=lambda _event, _details: None,
        )

        sampler.collect_once()
        sampler.collect_once()
        captured = sampler.take_snapshots("job-uid")

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].cpu_usage_cores, 0.5)
        self.assertEqual(captured[0].memory_usage_mb, 256.0)
        self.assertEqual(sampler.take_snapshots("job-uid"), [])
        self.assertEqual(len(snapshots.records), 1)
        self.assertEqual(len(states.records), 2)
        self.assertEqual(states.records[0]["counts"]["active_jobs"], 1)
        self.assertEqual(captured[0].observation_time is not None, True)
        self.assertTrue(any("[15s]" in query for query in prometheus.queries))
        self.assertTrue(
            all("kube_pod_owner" not in query for query in prometheus.queries)
        )

    def test_incomplete_cluster_state_is_diagnosed_and_not_written(self):
        active = demo_job()
        active.status.conditions = []
        active.status.completion_time = None
        states = RecordingWriter()
        diagnostics = []
        sampler = ResourceSampler(
            batch_api=FakeBatchApi([active]),
            core_api=FakeCoreApi(pods=[demo_pod()], fail_nodes=True),
            prometheus=FakePrometheus(),
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=RecordingWriter(),
            state_writer=states,
            emit_diagnostic=lambda event, details: diagnostics.append((event, details)),
        )

        sampler.collect_once()

        self.assertEqual(states.records, [])
        diagnostics = [d for d in diagnostics if d[0] != "job.observed"]
        self.assertEqual(diagnostics[0][0], "cluster_state.capture_failed")
        self.assertEqual(diagnostics[0][1]["stage"], "build_snapshot")

    def test_incomplete_prometheus_sample_is_diagnosed_and_not_written(self):
        active = demo_job()
        active.status.conditions = []
        active.status.completion_time = None
        prometheus = FakePrometheus()
        original_query = prometheus.query

        def query_without_memory(promql, eval_time):
            if "memory_working_set" in promql:
                return []
            return original_query(promql, eval_time)

        prometheus.query = query_without_memory
        snapshots = RecordingWriter()
        diagnostics = []
        sampler = ResourceSampler(
            batch_api=FakeBatchApi([active]),
            core_api=FakeCoreApi(pods=[demo_pod()], nodes=[demo_node("cloud1")]),
            prometheus=prometheus,
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=snapshots,
            state_writer=RecordingWriter(),
            emit_diagnostic=lambda event, details: diagnostics.append((event, details)),
        )

        sampler.collect_once()

        self.assertEqual(snapshots.records, [])
        diagnostics = [d for d in diagnostics if d[0] != "job.observed"]
        self.assertEqual(diagnostics[0][0], "prometheus.sample_incomplete")
        self.assertEqual(diagnostics[0][1]["missing_fields"], ["memory"])

    def test_exhausted_watch_is_fatal_and_stops_sampler(self):
        sampler = FakeSampler()
        observer = OpenDTObserver(
            batch_api=FakeBatchApi([]),
            watch_factory=EmptyWatch,
            sampler=sampler,
            workload_writer=RecordingWriter(),
            diagnostic_writer=RecordingWriter(),
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            cpu_frequency_mhz=2400,
        )

        with self.assertRaisesRegex(RuntimeError, "watch ended unexpectedly"):
            observer.run()
        self.assertTrue(sampler.started)
        self.assertTrue(sampler.stopped)

    def test_manifest_keeps_observer_state_separate(self):
        manifest = (SOURCE.parent / "manifests" / "adapter.yaml").read_text()
        observer_section = manifest.split("- name: opendt-observer", 1)[1].split(
            "volumes:", 1
        )[0]

        self.assertIn("replicas: 1", manifest)
        self.assertIn('command: ["python", "-u", "opendt_observer.py"]', manifest)
        self.assertIn("mountPath: /var/lib/opendt", observer_section)
        self.assertNotIn("mountPath: /data", observer_section)
        self.assertIn("- name: opendt-state", manifest)
        self.assertIn('resources: ["pods"]', manifest)
        self.assertIn("kind: ClusterRole", manifest)
        self.assertIn('resources: ["nodes"]', manifest)
        node_role = manifest.split("kind: ClusterRole", 1)[1].split("---", 1)[0]
        self.assertIn('verbs: ["get", "list"]', node_role)
        self.assertNotIn("create", node_role)
        self.assertNotIn("update", node_role)


if __name__ == "__main__":
    unittest.main()
