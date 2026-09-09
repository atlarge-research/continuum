"""Observe image-batch Jobs and append OpenDT-compatible workload records."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

from kubernetes import client, config, watch

from events import JsonlEventWriter, new_event
from job_submitter import LABEL_REQUEST_ID, LABEL_WORKLOAD


SCHEMA_VERSION = 1
WORKLOAD_LABEL_VALUE = "image-batch"
ANNOTATION_PREFIX = "continuum.atlarge.nl/"
ANNOTATION_RUN_ID = ANNOTATION_PREFIX + "run-id"
ANNOTATION_WORKLOAD_RUN_ID = ANNOTATION_PREFIX + "workload-run-id"
ANNOTATION_ENDPOINT_BATCH_ID = ANNOTATION_PREFIX + "endpoint-batch-id"
ANNOTATION_PAYLOAD_BYTES = ANNOTATION_PREFIX + "payload-bytes"
ANNOTATION_IMAGE_COUNT = ANNOTATION_PREFIX + "image-count"
ANNOTATION_INFERENCE_REPETITIONS = ANNOTATION_PREFIX + "inference-repetitions"
CPU_RATE_WINDOW = "15s"


class MalformedJobError(ValueError):
    """Raised when a terminal Job cannot become an OpenDT Task."""


@dataclass(frozen=True)
class ResourceSnapshot:
    job_uid: str
    job_name: str
    namespace: str
    capture_time: datetime
    cpu_usage_cores: float
    memory_usage_mb: float
    observation_time: datetime | None = None

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["schema_version"] = SCHEMA_VERSION
        record["capture_time"] = utc_iso(self.capture_time)
        if self.observation_time is not None:
            record["observation_time"] = utc_iso(self.observation_time)
        return record


def utc_iso(value: datetime) -> str:
    """Return a timezone-aware ISO timestamp accepted by OpenDT."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_cpu_cores(value: Any) -> float:
    """Parse the Kubernetes CPU quantities used by the demo Jobs."""
    text = str(value)
    suffixes = {
        "n": Decimal("0.000000001"),
        "u": Decimal("0.000001"),
        "m": Decimal("0.001"),
    }
    multiplier = suffixes.get(text[-1:])
    if multiplier is not None:
        text = text[:-1]
    else:
        multiplier = Decimal(1)
    return float(Decimal(text) * multiplier)


def parse_memory_mb(value: Any) -> float:
    """Parse Kubernetes memory quantities into MiB."""
    text = str(value)
    suffixes = {
        "Ki": Decimal(1) / Decimal(1024),
        "Mi": Decimal(1),
        "Gi": Decimal(1024),
        "Ti": Decimal(1024 * 1024),
        "K": Decimal(1000) / Decimal(1024 * 1024),
        "M": Decimal(1000 * 1000) / Decimal(1024 * 1024),
        "G": Decimal(1000 * 1000 * 1000) / Decimal(1024 * 1024),
    }
    for suffix in sorted(suffixes, key=len, reverse=True):
        if text.endswith(suffix):
            return float(Decimal(text[: -len(suffix)]) * suffixes[suffix])
    return float(Decimal(text) / Decimal(1024 * 1024))


def extract_resource_capacity(job: Any) -> tuple[int, int]:
    """Return OpenDT CPU-count and memory-capacity values for a Job."""
    try:
        containers = job.spec.template.spec.containers or []
    except AttributeError as exc:
        raise MalformedJobError("Job has no Pod container specification") from exc

    requested_cpu = limited_cpu = 0.0
    requested_memory = limited_memory = 0.0
    for container in containers:
        resources = getattr(container, "resources", None)
        requests = getattr(resources, "requests", None) or {}
        limits = getattr(resources, "limits", None) or {}
        if requests.get("cpu") is not None:
            requested_cpu += parse_cpu_cores(requests["cpu"])
        if limits.get("cpu") is not None:
            limited_cpu += parse_cpu_cores(limits["cpu"])
        if requests.get("memory") is not None:
            requested_memory += parse_memory_mb(requests["memory"])
        if limits.get("memory") is not None:
            limited_memory += parse_memory_mb(limits["memory"])

    parallelism = getattr(job.spec, "parallelism", None) or 1
    cpu_count = math.ceil(max(requested_cpu, limited_cpu) * parallelism)
    memory_mb = math.ceil(max(requested_memory, limited_memory) * parallelism)
    if cpu_count <= 0:
        raise MalformedJobError("Job has no positive CPU request or limit")
    return cpu_count, memory_mb


def extract_resource_requests(job: Any) -> tuple[float, float]:
    """Return the scheduler-facing CPU and memory requests for a Job."""
    try:
        containers = job.spec.template.spec.containers or []
    except AttributeError as exc:
        raise MalformedJobError("Job has no Pod container specification") from exc
    cpu = 0.0
    memory_mb = 0.0
    for container in containers:
        resources = getattr(container, "resources", None)
        requests = getattr(resources, "requests", None) or {}
        if requests.get("cpu") is not None:
            cpu += parse_cpu_cores(requests["cpu"])
        if requests.get("memory") is not None:
            memory_mb += parse_memory_mb(requests["memory"])
    parallelism = getattr(job.spec, "parallelism", None) or 1
    cpu *= parallelism
    memory_mb *= parallelism
    if cpu <= 0:
        raise MalformedJobError("Job has no positive CPU request")
    return cpu, memory_mb


def _pod_job_uid(pod: Any) -> str | None:
    metadata = getattr(pod, "metadata", None)
    for owner in getattr(metadata, "owner_references", None) or []:
        if (
            getattr(owner, "kind", None) == "Job"
            and getattr(owner, "controller", False)
            and getattr(owner, "uid", None)
        ):
            return owner.uid
    return None


def pod_execution_interval(
    pods: list[Any], job_uid: str
) -> tuple[datetime, datetime]:
    """Return the worker container's Kubernetes execution interval."""
    intervals = []
    for pod in pods:
        if _pod_job_uid(pod) != job_uid:
            continue
        statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
        for status in statuses:
            terminated = getattr(getattr(status, "state", None), "terminated", None)
            started = getattr(terminated, "started_at", None)
            finished = getattr(terminated, "finished_at", None)
            if started is not None and finished is not None:
                intervals.append((started, finished))
    if not intervals:
        raise MalformedJobError("Job has no terminated worker container interval")
    return min(start for start, _ in intervals), max(finish for _, finish in intervals)


def _worker_record(node: Any) -> dict[str, Any] | None:
    metadata = getattr(node, "metadata", None)
    labels = getattr(metadata, "labels", None) or {}
    if (
        "node-role.kubernetes.io/control-plane" in labels
        or "node-role.kubernetes.io/master" in labels
    ):
        return None
    uid = getattr(metadata, "uid", None)
    name = getattr(metadata, "name", None)
    if not uid or not name:
        raise MalformedJobError("worker Node is missing UID or name")
    status = getattr(node, "status", None)
    ready = any(
        getattr(condition, "type", None) == "Ready"
        and getattr(condition, "status", None) == "True"
        for condition in (getattr(status, "conditions", None) or [])
    )
    allocatable = getattr(status, "allocatable", None) or {}
    if allocatable.get("cpu") is None or allocatable.get("memory") is None:
        raise MalformedJobError(
            f"worker Node {name!r} is missing allocatable resources"
        )
    spec = getattr(node, "spec", None)
    return {
        "kubernetes_node_uid": uid,
        "node_name": name,
        "ready": ready,
        "schedulable": not bool(getattr(spec, "unschedulable", False)),
        "allocatable_cpu_count": parse_cpu_cores(allocatable["cpu"]),
        "allocatable_memory_mb": parse_memory_mb(allocatable["memory"]),
    }


def _state_job_record(job: Any, pods: list[Any]) -> tuple[str, dict[str, Any]]:
    metadata = getattr(job, "metadata", None)
    status = getattr(job, "status", None)
    uid = getattr(metadata, "uid", None)
    name = getattr(metadata, "name", None)
    namespace = getattr(metadata, "namespace", None)
    created = getattr(metadata, "creation_timestamp", None)
    if not all((uid, name, namespace, created)):
        raise MalformedJobError("non-terminal Job is missing identity or creation time")
    labels = getattr(metadata, "labels", None) or {}
    annotations = getattr(metadata, "annotations", None) or {}
    request_id = labels.get(LABEL_REQUEST_ID)
    run_id = annotations.get(ANNOTATION_RUN_ID)
    if not request_id or not run_id:
        raise MalformedJobError(f"non-terminal Job {name!r} is missing lineage")
    requested_cpu, requested_memory_mb = extract_resource_requests(job)
    owned_pods = sorted(
        (pod for pod in pods if _pod_job_uid(pod) == uid),
        key=lambda pod: (
            getattr(getattr(pod, "status", None), "phase", None)
            in ("Succeeded", "Failed"),
            getattr(getattr(pod, "metadata", None), "name", ""),
        ),
    )
    selected_pod = next(
        (
            pod
            for pod in owned_pods
            if getattr(getattr(pod, "status", None), "phase", None) == "Running"
        ),
        owned_pods[0] if owned_pods else None,
    )
    pod_phase = (
        getattr(getattr(selected_pod, "status", None), "phase", None)
        if selected_pod is not None
        else None
    )
    state = "active" if pod_phase == "Running" else "queued"
    if pod_phase in ("Succeeded", "Failed"):
        state = "finished"
    start_time = getattr(status, "start_time", None)
    execution_start = None
    for container in (
        getattr(getattr(selected_pod, "status", None), "container_statuses", None) or []
    ):
        if getattr(container, "name", None) == "classifier":
            running = getattr(getattr(container, "state", None), "running", None)
            execution_start = getattr(running, "started_at", None)
    record = {
        "kubernetes_job_uid": uid,
        "job_name": name,
        "namespace": namespace,
        "request_id": request_id,
        "run_id": run_id,
        "workload_run_id": annotations.get(ANNOTATION_WORKLOAD_RUN_ID, run_id),
        "endpoint_batch_id": annotations.get(ANNOTATION_ENDPOINT_BATCH_ID),
        "image_count": _required_int(annotations, ANNOTATION_IMAGE_COUNT),
        "payload_bytes": _required_int(annotations, ANNOTATION_PAYLOAD_BYTES),
        "inference_repetitions": _positive_int(
            annotations, ANNOTATION_INFERENCE_REPETITIONS
        ),
        "creation_time": utc_iso(created),
        "start_time": utc_iso(start_time) if start_time is not None else None,
        "execution_start_time": utc_iso(execution_start) if execution_start else None,
        "requested_cpu_count": requested_cpu,
        "requested_memory_mb": requested_memory_mb,
        "pod_name": (
            getattr(getattr(selected_pod, "metadata", None), "name", None)
            if selected_pod is not None
            else None
        ),
        "pod_phase": pod_phase,
        "node_name": (
            getattr(getattr(selected_pod, "spec", None), "node_name", None)
            if selected_pod is not None
            else None
        ),
    }
    return state, record


def build_cluster_state_record(
    jobs: list[Any],
    pods: list[Any],
    nodes: list[Any],
    *,
    run_id: str,
    namespace: str,
    label_selector: str,
    observed_at: datetime,
) -> dict[str, Any]:
    """Build queued/active pressure, excluding Pods awaiting Job finalization."""
    queued = []
    active = []
    for job in jobs:
        if terminal_status(job)[0] is not None:
            continue
        state, record = _state_job_record(job, pods)
        # A terminal Pod is neither queued nor executing. The independent Job
        # watcher still waits for Complete/Failed before recording its outcome.
        if state == "finished":
            continue
        (active if state == "active" else queued).append(record)
    workers = []
    for node in nodes:
        worker = _worker_record(node)
        if worker is not None:
            workers.append(worker)
    queued.sort(key=lambda item: (item["creation_time"], item["kubernetes_job_uid"]))
    active.sort(key=lambda item: (item["creation_time"], item["kubernetes_job_uid"]))
    workers.sort(key=lambda item: item["node_name"])
    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": "cluster_state",
        "timestamp": utc_iso(observed_at),
        "timestamp_unix_ns": int(observed_at.timestamp() * 1_000_000_000),
        "run_id": run_id,
        "source": {
            "namespace": namespace,
            "job_label_selector": label_selector,
        },
        "jobs": {"queued": queued, "active": active},
        "workers": workers,
        "counts": {
            "queued_jobs": len(queued),
            "active_jobs": len(active),
            "workers": len(workers),
            "ready_schedulable_workers": sum(
                worker["ready"] and worker["schedulable"] for worker in workers
            ),
        },
    }


def terminal_status(job: Any) -> tuple[str | None, datetime | None]:
    """Return the terminal status and its authoritative transition time."""
    status = getattr(job, "status", None)
    conditions = getattr(status, "conditions", None) or []
    for condition in conditions:
        if getattr(condition, "status", None) != "True":
            continue
        kind = getattr(condition, "type", None)
        if kind == "Complete":
            completion = getattr(status, "completion_time", None)
            return "Complete", completion or getattr(
                condition, "last_transition_time", None
            )
        if kind == "Failed":
            return "Failed", getattr(condition, "last_transition_time", None)
    return None, None


def _required_int(mapping: dict[str, str], key: str) -> int:
    try:
        value = int(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedJobError(f"Job annotation {key!r} must be an integer") from exc
    if value < 0:
        raise MalformedJobError(f"Job annotation {key!r} must be non-negative")
    return value


def _positive_int(mapping: dict[str, str], key: str, default: str = "1") -> int:
    value = _required_int({key: mapping.get(key, default)}, key)
    if value < 1:
        raise MalformedJobError(f"Job annotation {key!r} must be positive")
    return value


def build_fragments(
    snapshots: list[ResourceSnapshot],
    *,
    task_id: int,
    start_time: datetime,
    finish_time: datetime,
    cpu_count: int,
    cpu_frequency_mhz: int,
) -> list[dict[str, Any]]:
    """Convert ordered CPU observations into duration-covering fragments."""
    samples = sorted(
        (
            sample
            for sample in snapshots
            if start_time <= sample.capture_time <= finish_time
        ),
        key=lambda sample: sample.capture_time,
    )
    if not samples:
        return []

    total_ms = max(0, math.ceil((finish_time - start_time).total_seconds() * 1000))
    fragments: list[dict[str, Any]] = []
    previous_ms = 0
    for sample in samples:
        boundary_ms = min(
            total_ms,
            max(0, int((sample.capture_time - start_time).total_seconds() * 1000)),
        )
        duration_ms = boundary_ms - previous_ms
        if duration_ms > 0:
            fragments.append(
                _fragment(
                    task_id,
                    duration_ms,
                    cpu_count,
                    sample.cpu_usage_cores,
                    cpu_frequency_mhz,
                )
            )
        previous_ms = max(previous_ms, boundary_ms)

    tail_ms = total_ms - previous_ms
    if tail_ms > 0:
        fragments.append(
            _fragment(
                task_id,
                tail_ms,
                cpu_count,
                samples[-1].cpu_usage_cores,
                cpu_frequency_mhz,
            )
        )
    return fragments


def _fragment(
    task_id: int,
    duration_ms: int,
    cpu_count: int,
    cpu_usage_cores: float,
    cpu_frequency_mhz: int,
) -> dict[str, Any]:
    utilization = min(max(cpu_usage_cores, 0.0), float(cpu_count)) / cpu_count
    return {
        "id": task_id,
        "duration": duration_ms,
        "cpu_count": cpu_count,
        "cpu_usage": utilization * cpu_frequency_mhz,
    }


def build_workload_record(
    job: Any,
    *,
    task_id: int,
    snapshots: list[ResourceSnapshot],
    cpu_frequency_mhz: int,
    execution_start_time: datetime | None = None,
    execution_finish_time: datetime | None = None,
) -> dict[str, Any]:
    """Build one OpenDT-compatible task message plus Kubernetes provenance."""
    metadata = getattr(job, "metadata", None)
    status = getattr(job, "status", None)
    uid = getattr(metadata, "uid", None)
    name = getattr(metadata, "name", None)
    namespace = getattr(metadata, "namespace", None)
    submission_time = getattr(metadata, "creation_timestamp", None)
    start_time = getattr(status, "start_time", None)
    state, finish_time = terminal_status(job)
    if state != "Complete":
        raise MalformedJobError("Job is not successfully complete")
    missing = [
        field
        for field, value in (
            ("UID", uid),
            ("name", name),
            ("namespace", namespace),
            ("creation timestamp", submission_time),
            ("start timestamp", start_time),
            ("completion timestamp", finish_time),
        )
        if value is None
    ]
    if missing:
        raise MalformedJobError("Job is missing " + ", ".join(missing))
    if finish_time < start_time:
        raise MalformedJobError("Job completion precedes its start")
    execution_start_time = execution_start_time or start_time
    execution_finish_time = execution_finish_time or finish_time
    if execution_finish_time < execution_start_time:
        raise MalformedJobError("worker completion precedes its start")

    labels = getattr(metadata, "labels", None) or {}
    annotations = getattr(metadata, "annotations", None) or {}
    request_id = labels.get(LABEL_REQUEST_ID)
    run_id = annotations.get(ANNOTATION_RUN_ID)
    if not request_id or not run_id:
        raise MalformedJobError("Job is missing request or run lineage")
    image_count = _required_int(annotations, ANNOTATION_IMAGE_COUNT)
    payload_bytes = _required_int(annotations, ANNOTATION_PAYLOAD_BYTES)
    inference_repetitions = _positive_int(annotations, ANNOTATION_INFERENCE_REPETITIONS)
    cpu_count, memory_mb = extract_resource_capacity(job)
    duration_ms = math.ceil(
        (execution_finish_time - execution_start_time).total_seconds() * 1000
    )
    task_snapshots = [
        sample
        for sample in snapshots
        if execution_start_time <= sample.capture_time <= execution_finish_time
    ]
    fragments = build_fragments(
        task_snapshots,
        task_id=task_id,
        start_time=execution_start_time,
        finish_time=execution_finish_time,
        cpu_count=cpu_count,
        cpu_frequency_mhz=cpu_frequency_mhz,
    )
    sampling_quality = "sampled" if fragments else "degraded_no_samples"

    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": "task",
        "timestamp": utc_iso(submission_time),
        "task": {
            "id": task_id,
            "submission_time": utc_iso(submission_time),
            "duration": duration_ms,
            "cpu_count": cpu_count,
            "cpu_capacity": float(cpu_frequency_mhz),
            "mem_capacity": memory_mb,
            "fragments": fragments,
        },
        "source": {
            "kubernetes_job_uid": uid,
            "job_name": name,
            "namespace": namespace,
            "run_id": run_id,
            "workload_run_id": annotations.get(ANNOTATION_WORKLOAD_RUN_ID, run_id),
            "request_id": request_id,
            "endpoint_batch_id": annotations.get(ANNOTATION_ENDPOINT_BATCH_ID),
            "image_count": image_count,
            "payload_bytes": payload_bytes,
            "inference_repetitions": inference_repetitions,
            "inference_invocation_count": image_count * inference_repetitions,
            "start_time": utc_iso(start_time),
            "completion_time": utc_iso(finish_time),
            "execution_start_time": utc_iso(execution_start_time),
            "execution_completion_time": utc_iso(execution_finish_time),
            "terminal_status": state,
            "resource_sample_count": len(task_snapshots),
            "sampling_quality": sampling_quality,
        },
    }


class PrometheusClient:
    def __init__(self, base_url: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def query(self, promql: str, eval_time: datetime) -> list[dict[str, Any]]:
        query = urlencode({"query": promql, "time": str(eval_time.timestamp())})
        with urlopen(  # nosec: configured in-cluster Prometheus endpoint
            f"{self.base_url}/api/v1/query?{query}", timeout=self.timeout_seconds
        ) as response:
            payload = json.load(response)
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        data = payload.get("data") or {}
        if data.get("resultType") != "vector":
            raise RuntimeError("Prometheus query did not return an instant vector")
        return data.get("result") or []


class ResourceSampler:
    """Collect resource and cluster-state snapshots beside the Job watcher."""

    def __init__(
        self,
        *,
        batch_api: Any,
        core_api: Any,
        prometheus: PrometheusClient,
        namespace: str,
        label_selector: str,
        run_id: str,
        state_interval_seconds: float,
        resource_interval_seconds: float,
        snapshot_writer: JsonlEventWriter,
        state_writer: JsonlEventWriter,
        emit_diagnostic: Callable[[str, dict[str, Any]], None],
    ):
        self.batch_api = batch_api
        self.core_api = core_api
        self.prometheus = prometheus
        self.namespace = namespace
        self.label_selector = label_selector
        self.run_id = run_id
        self.state_interval_seconds = state_interval_seconds
        self.resource_interval_seconds = resource_interval_seconds
        self.snapshot_writer = snapshot_writer
        self.state_writer = state_writer
        self.emit_diagnostic = emit_diagnostic
        self._snapshots: dict[str, list[ResourceSnapshot]] = {}
        self._sample_keys: set[tuple[str, float]] = set()
        self._observed_uids: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="opendt-resource-sampler", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.state_interval_seconds + 1.0))

    def take_snapshots(self, job_uid: str) -> list[ResourceSnapshot]:
        with self._lock:
            return self._snapshots.pop(job_uid, [])

    def execution_interval(
        self, job_uid: str, request_id: str
    ) -> tuple[datetime, datetime]:
        pods = self.core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"{LABEL_REQUEST_ID}={request_id}",
        )
        return pod_execution_interval(pods.items, job_uid)

    def _run(self) -> None:
        next_state = time.monotonic()
        next_resource = next_state
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_state:
                collect_resources = now >= next_resource
                try:
                    self.collect_once(collect_resources=collect_resources)
                except Exception as exc:
                    self.emit_diagnostic("observer.sample_failed", {"error": str(exc)})
                while next_state <= now:
                    next_state += self.state_interval_seconds
                if collect_resources:
                    while next_resource <= now:
                        next_resource += self.resource_interval_seconds
            self._stop.wait(max(0.0, min(next_state, next_resource) - time.monotonic()))

    def observe_job(self, job: Any) -> None:
        """Record existence separately from successful completion and pressure."""
        metadata = getattr(job, "metadata", None)
        uid = getattr(metadata, "uid", None)
        created = getattr(metadata, "creation_timestamp", None)
        annotations = getattr(metadata, "annotations", None) or {}
        workload_run = annotations.get(ANNOTATION_WORKLOAD_RUN_ID) or annotations.get(
            ANNOTATION_RUN_ID
        )
        if not uid or not created or not workload_run:
            return
        with self._lock:
            if uid in self._observed_uids:
                return
            self.emit_diagnostic(
                "job.observed",
                {
                    "kubernetes_job_uid": uid,
                    "workload_run_id": workload_run,
                    "creation_time": utc_iso(created),
                },
            )
            self._observed_uids.add(uid)

    def collect_once(self, *, collect_resources: bool = True) -> None:
        try:
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace, label_selector=self.label_selector
            )
        except Exception as exc:
            self.emit_diagnostic(
                "cluster_state.capture_failed",
                {"stage": "list_jobs", "error": str(exc)},
            )
            return

        for job in jobs.items:
            self.observe_job(job)

        try:
            pods = self.core_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=self.label_selector
            )
        except Exception as exc:
            self.emit_diagnostic(
                "cluster_state.capture_failed",
                {"stage": "list_pods", "error": str(exc)},
            )
            return

        try:
            nodes = self.core_api.list_node()
            state_record = build_cluster_state_record(
                jobs.items,
                pods.items,
                nodes.items,
                run_id=self.run_id,
                namespace=self.namespace,
                label_selector=self.label_selector,
                observed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            self.emit_diagnostic(
                "cluster_state.capture_failed",
                {"stage": "build_snapshot", "error": str(exc)},
            )
        else:
            self.state_writer.emit(state_record)

        if not collect_resources:
            return

        job_uids = {}
        for job in jobs.items:
            name = getattr(job.metadata, "name", None)
            uid = getattr(job.metadata, "uid", None)
            if name and uid and terminal_status(job)[0] is None:
                job_uids[uid] = name
        if not job_uids:
            return
        observation_time = datetime.now(timezone.utc)
        pod_jobs = {}
        for pod in pods.items:
            pod_name = getattr(getattr(pod, "metadata", None), "name", None)
            job_uid = _pod_job_uid(pod)
            if pod_name and job_uid in job_uids:
                pod_jobs[pod_name] = (job_uid, job_uids[job_uid])
        if not pod_jobs:
            return
        escaped_namespace = self.namespace.replace("\\", "\\\\").replace('"', '\\"')
        container_selector = (
            f'namespace="{escaped_namespace}",pod!="",container!="",container!="POD"'
        )
        cpu_query = (
            "sum by (pod) ("
            f"rate(container_cpu_usage_seconds_total{{{container_selector}}}"
            f"[{CPU_RATE_WINDOW}]))"
        )
        memory_query = (
            "sum by (pod) ("
            f"container_memory_working_set_bytes{{{container_selector}}})"
        )
        sample_time_query = (
            "max by (pod) (timestamp("
            f"container_cpu_usage_seconds_total{{{container_selector}}}))"
        )
        merged: dict[str, dict[str, float]] = {}
        try:
            self._merge_vector(
                merged, self.prometheus.query(cpu_query, observation_time), "cpu"
            )
            self._merge_vector(
                merged,
                self.prometheus.query(memory_query, observation_time),
                "memory",
            )
            self._merge_vector(
                merged,
                self.prometheus.query(sample_time_query, observation_time),
                "sample_time",
            )
        except Exception as exc:
            self.emit_diagnostic("prometheus.sample_failed", {"error": str(exc)})
            return
        for pod_name, values in merged.items():
            job = pod_jobs.get(pod_name)
            sample_time = values.get("sample_time")
            if job is None:
                continue
            job_uid, job_name = job
            missing = [
                field
                for field in ("cpu", "memory", "sample_time")
                if field not in values
            ]
            if missing:
                self.emit_diagnostic(
                    "prometheus.sample_incomplete",
                    {
                        "kubernetes_job_uid": job_uid,
                        "job_name": job_name,
                        "pod_name": pod_name,
                        "missing_fields": missing,
                    },
                )
                continue
            sample_key = (job_uid, sample_time)
            with self._lock:
                if sample_key in self._sample_keys:
                    continue
                self._sample_keys.add(sample_key)
            snapshot = ResourceSnapshot(
                job_uid=job_uid,
                job_name=job_name,
                namespace=self.namespace,
                capture_time=datetime.fromtimestamp(sample_time, timezone.utc),
                cpu_usage_cores=values["cpu"],
                memory_usage_mb=values["memory"] / (1024 * 1024),
                observation_time=observation_time,
            )
            with self._lock:
                self._snapshots.setdefault(job_uid, []).append(snapshot)
            self.snapshot_writer.emit(snapshot.to_record())

    @staticmethod
    def _merge_vector(
        merged: dict[str, dict[str, float]],
        vector: list[dict[str, Any]],
        field: str,
    ) -> None:
        for series in vector:
            name = (series.get("metric") or {}).get("pod")
            sample = series.get("value") or []
            if not name or len(sample) != 2:
                continue
            merged.setdefault(name, {})[field] = float(sample[1])


class OpenDTObserver:
    """Fail-fast terminal Job watcher for one demo run."""

    def __init__(
        self,
        *,
        batch_api: Any,
        watch_factory: Callable[[], Any],
        sampler: ResourceSampler,
        workload_writer: JsonlEventWriter,
        diagnostic_writer: JsonlEventWriter,
        namespace: str,
        label_selector: str,
        run_id: str,
        cpu_frequency_mhz: int,
    ):
        self.batch_api = batch_api
        self.watch_factory = watch_factory
        self.sampler = sampler
        self.workload_writer = workload_writer
        self.diagnostic_writer = diagnostic_writer
        self.namespace = namespace
        self.label_selector = label_selector
        self.run_id = run_id
        self.cpu_frequency_mhz = cpu_frequency_mhz
        self._handled_uids: set[str] = set()
        self._next_task_id = 1

    def emit_diagnostic(self, event_type: str, details: dict[str, Any]) -> None:
        self.diagnostic_writer.emit(
            new_event(
                event_type,
                component="opendt-observer",
                run_id=self.run_id,
                request_id=details.get("request_id"),
                details=details,
            )
        )

    def handle_job(self, job: Any) -> bool:
        if hasattr(self.sampler, "observe_job"):
            self.sampler.observe_job(job)
        state, _ = terminal_status(job)
        if state is None:
            return False
        metadata = getattr(job, "metadata", None)
        uid = getattr(metadata, "uid", None)
        name = getattr(metadata, "name", None)
        if uid is not None and uid in self._handled_uids:
            return False
        if uid is not None:
            self._handled_uids.add(uid)
        if state == "Failed":
            self.emit_diagnostic(
                "job.failed", {"kubernetes_job_uid": uid, "job_name": name}
            )
            return False

        try:
            snapshots = self.sampler.take_snapshots(uid) if uid else []
            labels = getattr(getattr(job, "metadata", None), "labels", None) or {}
            request_id = labels.get(LABEL_REQUEST_ID)
            interval = None
            if uid and request_id and hasattr(self.sampler, "execution_interval"):
                interval = self.sampler.execution_interval(uid, request_id)
            record = build_workload_record(
                job,
                task_id=self._next_task_id,
                snapshots=snapshots,
                cpu_frequency_mhz=self.cpu_frequency_mhz,
                execution_start_time=interval[0] if interval else None,
                execution_finish_time=interval[1] if interval else None,
            )
        except (MalformedJobError, ArithmeticError) as exc:
            self.emit_diagnostic(
                "job.malformed",
                {
                    "kubernetes_job_uid": uid,
                    "job_name": name,
                    "error": str(exc),
                },
            )
            return False

        self.workload_writer.emit(record)
        self.emit_diagnostic(
            "task.emitted",
            {
                "kubernetes_job_uid": uid,
                "job_name": name,
                "request_id": record["source"]["request_id"],
                "task_id": self._next_task_id,
                "resource_sample_count": record["source"]["resource_sample_count"],
            },
        )
        self._next_task_id += 1
        return True

    def run(self) -> None:
        self.sampler.start()
        try:
            initial = self.batch_api.list_namespaced_job(
                namespace=self.namespace, label_selector=self.label_selector
            )
            for job in initial.items:
                self.handle_job(job)
            resource_version = getattr(initial.metadata, "resource_version", None)
            watcher = self.watch_factory()
            for event in watcher.stream(
                self.batch_api.list_namespaced_job,
                namespace=self.namespace,
                label_selector=self.label_selector,
                resource_version=resource_version,
                timeout_seconds=0,
            ):
                job = event.get("object")
                if job is not None:
                    self.handle_job(job)
            raise RuntimeError("Kubernetes Job watch ended unexpectedly")
        finally:
            self.sampler.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-dir", default=os.getenv("OPENDT_STATE_DIR", "/var/lib/opendt")
    )
    parser.add_argument("--namespace", default=os.getenv("JOB_NAMESPACE", "fns-demo"))
    parser.add_argument(
        "--prometheus-url",
        default=os.getenv(
            "PROMETHEUS_URL",
            "http://prometheus-k8s.monitoring.svc.cluster.local:9090",
        ),
    )
    parser.add_argument("--run-id", default=os.getenv("RUN_ID", "fns-v1-manual"))
    parser.add_argument(
        "--cpu-frequency-mhz",
        type=int,
        default=int(os.getenv("CPU_FREQUENCY_MHZ", "2400")),
    )
    parser.add_argument(
        "--resource-collection-interval-seconds",
        type=float,
        default=float(os.getenv("RESOURCE_COLLECTION_INTERVAL_SECONDS", "5")),
    )
    parser.add_argument(
        "--cluster-state-interval-seconds",
        type=float,
        default=float(os.getenv("CLUSTER_STATE_INTERVAL_SECONDS", "1")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.cpu_frequency_mhz <= 0:
        raise ValueError("CPU frequency must be positive")
    if args.resource_collection_interval_seconds <= 0:
        raise ValueError("resource collection interval must be positive")
    if args.cluster_state_interval_seconds <= 0:
        raise ValueError("cluster-state interval must be positive")

    config.load_incluster_config()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    workload_path = state_dir / "workload.jsonl"
    snapshot_path = state_dir / "resource-snapshots.jsonl"
    cluster_state_path = state_dir / "cluster-state.jsonl"
    diagnostic_path = state_dir / "observer-events.jsonl"
    for path in (
        workload_path,
        snapshot_path,
        cluster_state_path,
        diagnostic_path,
    ):
        path.touch(exist_ok=True)
    workload_writer = JsonlEventWriter(workload_path)
    snapshot_writer = JsonlEventWriter(snapshot_path)
    state_writer = JsonlEventWriter(cluster_state_path)
    diagnostic_writer = JsonlEventWriter(diagnostic_path)
    batch_api = client.BatchV1Api()
    core_api = client.CoreV1Api()
    label_selector = f"{LABEL_WORKLOAD}={WORKLOAD_LABEL_VALUE}"

    diagnostic = lambda event_type, details: diagnostic_writer.emit(
        new_event(
            event_type,
            component="opendt-observer",
            run_id=args.run_id,
            request_id=details.get("request_id"),
            details=details,
        )
    )
    sampler = ResourceSampler(
        batch_api=client.BatchV1Api(),
        core_api=core_api,
        prometheus=PrometheusClient(args.prometheus_url),
        namespace=args.namespace,
        label_selector=label_selector,
        run_id=args.run_id,
        state_interval_seconds=args.cluster_state_interval_seconds,
        resource_interval_seconds=args.resource_collection_interval_seconds,
        snapshot_writer=snapshot_writer,
        state_writer=state_writer,
        emit_diagnostic=diagnostic,
    )
    observer = OpenDTObserver(
        batch_api=batch_api,
        watch_factory=watch.Watch,
        sampler=sampler,
        workload_writer=workload_writer,
        diagnostic_writer=diagnostic_writer,
        namespace=args.namespace,
        label_selector=label_selector,
        run_id=args.run_id,
        cpu_frequency_mhz=args.cpu_frequency_mhz,
    )
    print(
        f"OpenDT observer watching {args.namespace} and writing to {state_dir}",
        flush=True,
    )
    observer.run()


if __name__ == "__main__":
    main()
