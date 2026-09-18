"""Pure conversion of a forecast cutoff into OpenDC simulation inputs."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math

from forecast_trace import iso, milliseconds, validate_task


INT64_MAX = 2**63 - 1
SIMULATION_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class _SimulationModel:
    """Validated cutoff and frozen workload shared by every scenario."""

    task: dict
    source: dict
    expected_source: dict
    cutoff: int
    horizon_ms: int


def _validate_profile(task, label):
    try:
        validate_task(task)
        task_id = task["id"]
        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise ValueError("invalid Task id")
        if not -(2**31) <= task_id <= 2**31 - 1:
            raise ValueError("Task id exceeds int32")
        if any(fragment.get("id") != task_id for fragment in task["fragments"]):
            raise ValueError("Fragment id differs from Task id")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "malformed {} physical profile: {}".format(label, exc)
        ) from exc


def _profile_signature(task):
    return {
        "duration": task["duration"],
        "cpu_count": task["cpu_count"],
        "cpu_capacity": task["cpu_capacity"],
        "mem_capacity": task["mem_capacity"],
        "fragments": [
            {
                key: copy.deepcopy(fragment[key])
                for key in ("duration", "cpu_count", "cpu_usage")
            }
            for fragment in task["fragments"]
        ],
    }


def _copy_profile(template_task, task_id, submission_time):
    task = copy.deepcopy(template_task)
    task["id"] = task_id
    task["submission_time"] = submission_time
    for fragment in task["fragments"]:
        fragment["id"] = task_id
    return task


def _trim_profile(template_task, task_id, elapsed_ms):
    # Exhaustion is a model assumption, not evidence of observed completion.
    # Do not emit zero-duration Tasks or Fragments to the simulator.
    if elapsed_ms >= template_task["duration"]:
        return None

    remaining = []
    consumed = elapsed_ms
    for fragment in template_task["fragments"]:
        if consumed >= fragment["duration"]:
            consumed -= fragment["duration"]
            continue
        copied = copy.deepcopy(fragment)
        copied["id"] = task_id
        copied["duration"] -= consumed
        consumed = 0
        remaining.append(copied)
    task = _copy_profile(template_task, task_id, 0)
    task["duration"] = sum(fragment["duration"] for fragment in remaining)
    task["fragments"] = remaining
    return task


def _diagnostic(code, message, *, severity="error", **context):
    return {"severity": severity, "code": code, "message": message, **context}


def _timestamp(value):
    try:
        return milliseconds(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid timestamp") from exc


def _terminal(job):
    return job.get("execution_state") == "terminated" or job.get("pod_phase") in (
        "Succeeded",
        "Failed",
    )


def _phase(job, group):
    execution_state = job.get("execution_state")
    node_name = job.get("node_name")
    pod_phase = job.get("pod_phase")
    if execution_state == "waiting":
        if group != "queued":
            return None, "execution_state_invalid"
        return ("startup" if node_name else "queued"), None
    if execution_state == "running":
        if group != "active":
            return None, "execution_state_invalid"
        return "running", None
    if (
        execution_state == "unknown"
        and group == "queued"
        and pod_phase in (None, "Pending")
    ):
        return ("startup" if node_name else "queued"), None
    if execution_state is not None:
        return None, "execution_state_unknown"

    # Backward compatibility for snapshots predating explicit classifier state.
    if group == "queued" and pod_phase in (None, "Pending"):
        return ("startup" if node_name else "queued"), None
    if group == "active" and pod_phase == "Running":
        if job.get("execution_start_time") is None:
            return None, "execution_start_missing"
        return "running", None
    return None, "execution_state_invalid"


def _simulation_model(trace, template, settings):
    if template is None or not isinstance(template, dict):
        raise ValueError("simulation input requires a frozen template")
    try:
        template_record = template["record"]
        template_task = template_record["task"]
        template_source = template_record["source"]
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed frozen template") from exc
    _validate_profile(template_task, "template")
    if not template_task["fragments"]:
        raise ValueError("template must contain at least one Fragment")

    cutoff = trace.cutoff
    if isinstance(cutoff, bool) or not isinstance(cutoff, int):
        raise ValueError("trace cutoff must be integral milliseconds")
    horizon_seconds = getattr(settings, "horizon_seconds", None)
    if (
        isinstance(horizon_seconds, bool)
        or not isinstance(horizon_seconds, int)
        or horizon_seconds <= 0
        or horizon_seconds > INT64_MAX // 1000
    ):
        raise ValueError("horizon_seconds must be a positive integer")
    horizon_ms = horizon_seconds * 1000
    if cutoff > INT64_MAX - horizon_ms:
        raise ValueError("forecast horizon exceeds int64 milliseconds")

    expected_source = {
        "workload_run_id": getattr(settings, "run_id", None),
        "image_count": getattr(settings, "image_count", None),
        "inference_repetitions": getattr(settings, "inference_repetitions", None),
    }
    for field, expected in expected_source.items():
        if template_source.get(field) != expected:
            raise ValueError("template {} does not match settings".format(field))

    return _SimulationModel(
        template_task, template_source, expected_source, cutoff, horizon_ms
    )


def _history_identities(trace, report):
    job_ids = {}
    try:
        ordered_arrivals = sorted(
            trace.arrivals,
            key=lambda uid: (trace.arrivals[uid]["creation_ms"], uid),
        )
        for index, uid in enumerate(ordered_arrivals, 1):
            creation_ms = trace.arrivals[uid]["creation_ms"]
            if (
                not uid
                or isinstance(creation_ms, bool)
                or not isinstance(creation_ms, int)
                or creation_ms > trace.cutoff
            ):
                report(
                    "arrival_invalid",
                    "arrival identity or creation time is invalid",
                    job_uid=uid,
                )
            job_ids[uid] = index
    except (KeyError, TypeError):
        report("arrival_invalid", "trace arrivals are malformed")

    completed = set()
    for record in trace.completed:
        try:
            completed.add(record["source"]["kubernetes_job_uid"])
        except (KeyError, TypeError):
            report(
                "completed_identity_invalid", "completed Task is missing its Job UID"
            )

    return job_ids, completed


def _snapshot(state, report):
    workers = []
    if state is None:
        report("state_missing", "cluster state is unavailable")
        groups = {"queued": [], "active": []}
    else:
        try:
            groups = state["jobs"]
            workers = copy.deepcopy(state["workers"])
            if not isinstance(groups.get("queued"), list) or not isinstance(
                groups.get("active"), list
            ):
                raise TypeError
        except (KeyError, TypeError):
            report("state_malformed", "cluster state jobs or workers are malformed")
            groups = {"queued": [], "active": []}
            workers = []

    return groups, workers


def _validate_workers(workers, report):
    worker_names = set()
    worker_uids = set()
    for worker in workers:
        try:
            name = worker["node_name"]
            uid = worker["kubernetes_node_uid"]
            cpu = worker["allocatable_cpu_count"]
            memory = worker["allocatable_memory_mb"]
            valid = (
                bool(name)
                and bool(uid)
                and name not in worker_names
                and uid not in worker_uids
                and isinstance(worker["ready"], bool)
                and isinstance(worker["schedulable"], bool)
                and not isinstance(cpu, bool)
                and isinstance(cpu, (int, float))
                and math.isfinite(cpu)
                and cpu > 0
                and not isinstance(memory, bool)
                and isinstance(memory, (int, float))
                and math.isfinite(memory)
                and memory > 0
            )
        except (KeyError, TypeError):
            valid = False
            name = worker.get("node_name") if isinstance(worker, dict) else None
            uid = (
                worker.get("kubernetes_node_uid") if isinstance(worker, dict) else None
            )
        if not valid:
            report(
                "worker_invalid",
                "worker identity or capacity is invalid",
                node_name=name,
            )
        if name:
            worker_names.add(name)
        if uid:
            worker_uids.add(uid)

    return worker_names


def _ordered_jobs(groups, arrivals):
    ordered_jobs = [
        (group, index, job)
        for group in ("queued", "active")
        for index, job in enumerate(groups.get(group, []))
    ]

    def job_order(entry):
        group, index, job = entry
        uid = job.get("kubernetes_job_uid") if isinstance(job, dict) else None
        arrival = arrivals.get(uid, {}) if uid else {}
        creation = arrival.get("creation_ms")
        if isinstance(creation, bool) or not isinstance(creation, int):
            creation = INT64_MAX
        return creation, uid or "", 0 if group == "queued" else 1, index

    ordered_jobs.sort(key=job_order)
    return ordered_jobs


def _valid_job_identity(job, job_ids, seen_jobs, report):
    if not isinstance(job, dict):
        report("job_state_malformed", "Job state is not an object")
        return False
    uid = job.get("kubernetes_job_uid")
    if not uid:
        report("job_identity_missing", "non-terminal Job has no UID")
        return False
    if uid in seen_jobs:
        report(
            "duplicate_job",
            "non-terminal Job occurs more than once in the snapshot",
            job_uid=uid,
        )
        return False
    seen_jobs.add(uid)
    if uid not in job_ids:
        report(
            "job_identity_missing",
            "non-terminal Job is absent from bounded arrivals",
            job_uid=uid,
        )
        return False

    return True


def _job_phase(job, group, report):
    uid = job["kubernetes_job_uid"]
    phase, problem = _phase(job, group)
    if problem:
        report(problem, "Job execution state cannot be simulated", job_uid=uid)
        return None
    if job.get("execution_finish_time") is not None:
        report(
            "execution_finish_invalid",
            "non-terminal Job has a classifier finish time",
            job_uid=uid,
        )
    if phase != "running" and job.get("execution_start_time") is not None:
        report(
            "execution_timing_invalid",
            "non-running Job has a classifier start time",
            job_uid=uid,
        )
    if phase == "running" and job.get("pod_phase") not in (None, "Running"):
        report(
            "execution_state_invalid",
            "running classifier has an incompatible Pod phase",
            job_uid=uid,
        )

    return phase


def _job_creation(job, arrival, cutoff, report):
    uid = job["kubernetes_job_uid"]
    creation_value = job.get("creation_time")
    try:
        creation_ms = _timestamp(creation_value)
    except ValueError:
        report("creation_time_invalid", "Job creation time is invalid", job_uid=uid)
        return None
    if creation_ms > cutoff:
        report(
            "creation_after_cutoff",
            "Job was created after the simulation cutoff",
            job_uid=uid,
        )
    if creation_ms != arrival["creation_ms"]:
        report(
            "creation_mismatch",
            "Job and arrival creation times differ",
            job_uid=uid,
        )

    return creation_ms


def _validate_job_workload(job, model, report):
    uid = job["kubernetes_job_uid"]
    for field, expected in model.expected_source.items():
        if job.get(field) != expected:
            report(
                "workload_mismatch",
                "Job {} differs from the frozen workload".format(field),
                job_uid=uid,
                field=field,
            )
    requested_cpu = job.get("requested_cpu_count")
    requested_memory = job.get("requested_memory_mb")
    if (
        isinstance(requested_cpu, bool)
        or not isinstance(requested_cpu, (int, float))
        or not math.isfinite(requested_cpu)
        or requested_cpu <= 0
        or requested_cpu != model.task["cpu_count"]
        or isinstance(requested_memory, bool)
        or not isinstance(requested_memory, (int, float))
        or not math.isfinite(requested_memory)
        or requested_memory <= 0
        or requested_memory != model.task["mem_capacity"]
    ):
        report(
            "resource_mismatch",
            "Job requests differ from the frozen workload",
            job_uid=uid,
        )


def _validate_assignment(job, phase, worker_names, report):
    uid = job["kubernetes_job_uid"]
    node_name = job.get("node_name")
    if phase in ("startup", "running") and not node_name:
        report("running_unassigned", "executing Job has no node", job_uid=uid)
    elif node_name and node_name not in worker_names:
        report(
            "worker_missing",
            "assigned worker is absent from the snapshot",
            job_uid=uid,
            node_name=node_name,
        )


def _elapsed_execution(job, creation_ms, cutoff, report):
    uid = job["kubernetes_job_uid"]
    execution_start = job.get("execution_start_time")
    if execution_start is None:
        report(
            "execution_start_missing",
            "running Job has no classifier start time",
            job_uid=uid,
        )
        return None
    try:
        execution_start_ms = _timestamp(execution_start)
    except ValueError:
        report(
            "execution_start_invalid",
            "classifier start time is invalid",
            job_uid=uid,
        )
        return None
    if not creation_ms <= execution_start_ms <= cutoff:
        report(
            "execution_timing_invalid",
            "classifier start lies outside creation and cutoff",
            job_uid=uid,
        )
        return None
    return cutoff - execution_start_ms


def _job_metadata(job, phase, creation_ms, queue_order, elapsed_ms):
    return {
        "kubernetes_job_uid": job["kubernetes_job_uid"],
        "request_id": job.get("request_id"),
        "run_id": job.get("run_id"),
        "workload_run_id": job.get("workload_run_id"),
        "endpoint_batch_id": job.get("endpoint_batch_id"),
        "original_creation_time": job.get("creation_time"),
        "original_creation_ms": creation_ms,
        "queue_order": queue_order,
        "node_name": job.get("node_name"),
        "requested_cpu_count": job.get("requested_cpu_count"),
        "requested_memory_mb": job.get("requested_memory_mb"),
        "phase": phase,
        "elapsed_ms": elapsed_ms,
        "execution_start_time": job.get("execution_start_time"),
    }


def _validated_job_metadata(job, group, queue_order, trace, model, worker_names, report):
    phase = _job_phase(job, group, report)
    if phase is None:
        return None
    uid = job["kubernetes_job_uid"]
    creation_ms = _job_creation(job, trace.arrivals[uid], model.cutoff, report)
    if creation_ms is None:
        return None
    _validate_job_workload(job, model, report)
    _validate_assignment(job, phase, worker_names, report)
    elapsed_ms = 0
    if phase == "running":
        elapsed_ms = _elapsed_execution(job, creation_ms, model.cutoff, report)
        if elapsed_ms is None:
            return None
    return _job_metadata(job, phase, creation_ms, queue_order, elapsed_ms)


def _remaining_task(template_task, task_id, metadata, report):
    if metadata["phase"] != "running":
        return _copy_profile(template_task, task_id, 0)
    task = _trim_profile(template_task, task_id, metadata["elapsed_ms"])
    if task is None:
        report(
            "running_profile_exhausted",
            "observed running Job reached or exceeded its frozen profile; "
            "zero remaining execution assumed, not observed completion",
            severity="warning",
            job_uid=metadata["kubernetes_job_uid"],
            elapsed_ms=metadata["elapsed_ms"],
            template_duration_ms=template_task["duration"],
            remaining_ms=0,
        )
    return task


def _build_backlog(trace, groups, job_ids, completed, worker_names, model, report):
    initial_tasks = []
    model_exhausted_jobs = []
    seen_jobs = set()
    queue_order = 0
    for group, _, job in _ordered_jobs(groups, trace.arrivals):
        if isinstance(job, dict) and (
            job.get("kubernetes_job_uid") in completed or _terminal(job)
        ):
            continue
        position = queue_order
        queue_order += 1
        if not _valid_job_identity(job, job_ids, seen_jobs, report):
            continue
        metadata = _validated_job_metadata(
            job, group, position, trace, model, worker_names, report
        )
        if metadata is None:
            continue
        task_id = job_ids[job["kubernetes_job_uid"]]
        task = _remaining_task(model.task, task_id, metadata, report)
        if task is None:
            model_exhausted_jobs.append({
                "task_id": task_id,
                "metadata": metadata,
                "template_duration_ms": model.task["duration"],
                "remaining_execution_ms": 0,
                "observed_completed": False,
            })
        else:
            initial_tasks.append({"task": task, "metadata": metadata})
    return initial_tasks, model_exhausted_jobs


def _validate_future_task(
    task, scenario_index, template_signature, historical_ids, seen_ids, report
):
    _validate_profile(task, "future Task")
    task_id = task["id"]
    if task_id < 1:
        report(
            "future_id_invalid",
            "future Task ID must be positive",
            scenario_index=scenario_index,
            task_id=task_id,
        )
    if task_id in historical_ids:
        report(
            "future_id_collision",
            "future Task ID collides with bounded history",
            scenario_index=scenario_index,
            task_id=task_id,
        )
    if task_id in seen_ids:
        report(
            "future_id_duplicate",
            "future Task ID is duplicated within a scenario",
            scenario_index=scenario_index,
            task_id=task_id,
        )
    seen_ids.add(task_id)
    if _profile_signature(task) != template_signature:
        report(
            "future_profile_mismatch",
            "future Task differs from the frozen profile",
            scenario_index=scenario_index,
            task_id=task_id,
        )


def _future_arrival(task, scenario_index, model, report):
    task_id = task["id"]
    try:
        arrival_ms = _timestamp(task["submission_time"])
    except ValueError:
        report(
            "future_timestamp_invalid",
            "future Task submission time is invalid",
            scenario_index=scenario_index,
            task_id=task_id,
        )
        return None
    if not model.cutoff <= arrival_ms < model.cutoff + model.horizon_ms:
        report(
            "future_outside_horizon",
            "future Task arrival lies outside [cutoff, cutoff+horizon)",
            scenario_index=scenario_index,
            task_id=task_id,
        )
    return arrival_ms


def _future_lineage(task, arrival_ms, template_source):
    return {
        "task_id": task["id"],
        "original_submission_time": task["submission_time"],
        "original_submission_ms": arrival_ms,
        "template_job_uid": template_source.get("kubernetes_job_uid"),
        "workload_run_id": template_source.get("workload_run_id"),
        "template_request_id": template_source.get("request_id"),
        "template_endpoint_batch_id": template_source.get("endpoint_batch_id"),
        "image_count": template_source.get("image_count"),
        "inference_repetitions": template_source.get("inference_repetitions"),
    }


def _normalize_scenario(tasks, scenario_index, model, historical_ids, report):
    if not isinstance(tasks, list):
        raise ValueError("each scenario must be a list")
    normalized = []
    lineage = []
    seen_ids = set()
    template_signature = _profile_signature(model.task)
    for task in tasks:
        _validate_future_task(
            task, scenario_index, template_signature, historical_ids, seen_ids, report
        )
        arrival_ms = _future_arrival(task, scenario_index, model, report)
        if arrival_ms is None:
            continue
        relative = copy.deepcopy(task)
        relative["submission_time"] = arrival_ms - model.cutoff
        normalized.append(relative)
        lineage.append(_future_lineage(task, arrival_ms, model.source))
    return normalized, {"index": scenario_index, "future_tasks": lineage}


def _normalize_scenarios(scenarios, configured_scenarios, model, job_ids, report):
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    if configured_scenarios is not None and len(scenarios) != configured_scenarios:
        report("scenario_count_mismatch", "forecast scenario count differs from settings")
    normalized_scenarios = []
    scenario_metadata = []
    historical_ids = set(job_ids.values())
    for index, tasks in enumerate(scenarios):
        normalized, metadata = _normalize_scenario(
            tasks, index, model, historical_ids, report
        )
        normalized_scenarios.append(normalized)
        scenario_metadata.append(metadata)
    return normalized_scenarios, scenario_metadata


def _manifest(cutoff, horizon_ms, job_ids, scenario_metadata, diagnostics):
    reasons = []
    for diagnostic in diagnostics:
        if diagnostic["severity"] == "error" and diagnostic["code"] not in reasons:
            reasons.append(diagnostic["code"])
    status = "not_ready" if reasons else "ready"
    return {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "status": status,
        "reasons": reasons,
        "diagnostics": diagnostics,
        "cutoff": iso(cutoff),
        "cutoff_ms": cutoff,
        "horizon_ms": horizon_ms,
        "job_ids": job_ids,
        "normalization": {
            "time_origin": "cutoff",
            "submission_time_unit": "milliseconds",
            "backlog_submission_time": "0 (present at cutoff; original creation retained in metadata)",
            "future_arrival_window": "[0, horizon_ms)",
            "running_remaining_profile": "fragments split at classifier elapsed time",
        },
        "remaining_execution_model": "max(0, template_duration_ms - elapsed_classifier_execution_ms)",
        "simulation_completion": {
            "arrival_horizon_ms": horizon_ms,
            "simulation_end": "complete all included executable work, including beyond the arrival horizon",
        },
        "evaluation_policy": {
            "status": "unresolved",
            "discuss_with": "OpenDC lead developer before scoring or SLO integration",
            "open_questions": [
                "Which time window contributes energy and throughput?",
                "How do unfinished Jobs affect performance and SLO evaluation?",
                "Are post-horizon arrivals needed for meaningful completion predictions?",
            ],
        },
        "scenarios": scenario_metadata,
    }


def build_simulation_inputs(trace, template, scenarios, settings):
    """Build shared initial state and combined traces from cutoff-filtered evidence.

    Input timestamps remain absolute evidence. Output Task ``submission_time``
    values are integral milliseconds relative to the cutoff.
    """
    model = _simulation_model(trace, template, settings)
    diagnostics = []

    def report(code, message, **context):
        diagnostics.append(_diagnostic(code, message, **context))

    job_ids, completed = _history_identities(trace, report)
    groups, workers = _snapshot(trace.state, report)
    worker_names = _validate_workers(workers, report)
    initial_tasks, exhausted_jobs = _build_backlog(
        trace, groups, job_ids, completed, worker_names, model, report
    )
    normalized_scenarios, scenario_metadata = _normalize_scenarios(
        scenarios, getattr(settings, "scenarios", None), model, job_ids, report
    )
    manifest = _manifest(
        model.cutoff, model.horizon_ms, job_ids, scenario_metadata, diagnostics
    )
    initial_state = {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "cutoff": iso(model.cutoff),
        "cutoff_ms": model.cutoff,
        "workers": workers,
        "tasks": initial_tasks,
        "model_exhausted_jobs": exhausted_jobs,
    }
    if manifest["status"] != "ready":
        return manifest, initial_state, []
    backlog = [item["task"] for item in initial_tasks]
    combined = [
        copy.deepcopy(backlog) + copy.deepcopy(future_tasks)
        for future_tasks in normalized_scenarios
    ]
    return manifest, initial_state, combined
