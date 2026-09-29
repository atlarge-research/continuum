"""Prepare bounded provisional OpenDC experiments from frozen forecast evidence."""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pyarrow.parquet as pq

from opendc_occupancy import apply_occupancy, calibrate_occupancy

from forecast_trace import (
    bounded_read,
    canonical,
    digest,
    iso,
    milliseconds,
    parquet_tasks,
    read_trace,
)
from opendc_inputs import (
    PROVISIONAL_CONTRACT,
    adapt_trace,
    experiment_config,
    file_hashes,
    write_json,
)
from simulation_input import build_simulation_inputs
from opendc_runtime import adapt_topology, fns_runtime, runtime_identity
from opendc_pinning import FNS_CONTRACT, PINNED_MODE, initial_assignments, initialization_metadata


SUITE_CONTRACT = "opendc-scenarios-v1"
SUPPORTED_INITIALIZATION = "provisional-trace"
INITIALIZATION_MODES = (SUPPORTED_INITIALIZATION, PINNED_MODE)


def _read_tasks(directory):
    """Reconstruct Task records from an exported Parquet partition.

    Args:
        directory (str or Path): Directory containing tasks and fragments tables.

    Returns:
        list[dict]: Ordered Task records with their ordered fragments.

    Raises:
        ValueError: Fragment identities do not match the Task table.
    """
    directory = Path(directory)
    tasks = pq.read_table(directory / "tasks.parquet").to_pylist()
    fragments = pq.read_table(directory / "fragments.parquet").to_pylist()
    by_id = {}
    for fragment in fragments:
        by_id.setdefault(fragment["id"], []).append(fragment)
    task_ids = {task["id"] for task in tasks}
    if any(fragment_id not in task_ids for fragment_id in by_id):
        raise ValueError("source Fragment has no matching Task")
    for task in tasks:
        task["fragments"] = by_id.get(task["id"], [])
    return tasks


def _validate_template(template, forecast, simulation, selection_trace):
    """Validate the frozen template signature and recorded provenance.

    Args:
        template (dict): Frozen template document.
        forecast (dict): Forecast summary.
        simulation (dict): Simulation manifest.
        selection_trace (Trace): Observer evidence visible at template selection.

    Raises:
        ValueError: The signature or provenance fields disagree.
    """
    signature = template.get("sha256")
    unsigned = {key: value for key, value in template.items() if key != "sha256"}
    if digest(unsigned) != signature:
        raise ValueError("template hash mismatch")
    if forecast.get("template_sha256") != signature:
        raise ValueError("forecast template provenance mismatch")
    if simulation.get("template_sha256") != signature:
        raise ValueError("simulation template provenance mismatch")
    if milliseconds(template["selection_cutoff"]) > simulation["cutoff_ms"]:
        raise ValueError("template was selected after the effective cutoff")
    record = template["record"]
    if record not in selection_trace.completed:
        raise ValueError("template is not a completed profile observable at selection")
    source, task = record["source"], record["task"]
    settings = forecast["settings"]
    if (
        template["workload_run_id"] != settings["run_id"]
        or source["workload_run_id"] != settings["run_id"]
        or source["image_count"] != settings.get("image_count", source["image_count"])
        or source.get("inference_repetitions", 1)
        != settings.get("inference_repetitions", source.get("inference_repetitions", 1))
        or source.get("resource_sample_count", 0) < 3
        or source.get("sampling_quality") != "sampled"
        or not task["fragments"]
        or task["cpu_count"] != 1
        or task["mem_capacity"] != 512
    ):
        raise ValueError("template is ineligible for the homogeneous measured workload")


def _validate_freshness(forecast, simulation, trace):
    """Validate snapshot freshness against the requested forecast cutoff.

    Args:
        forecast (dict): Forecast summary containing settings.
        simulation (dict): Ready schema-2 simulation manifest.
        trace (Trace): Trace reconstructed from frozen observer prefixes.

    Raises:
        ValueError: Cutoffs disagree or the latest state exceeds the allowed gap.
    """
    effective = simulation.get("cutoff_ms")
    if milliseconds(simulation.get("effective_cutoff", simulation["cutoff"])) != effective:
        raise ValueError("simulation effective cutoff mismatch")
    if milliseconds(forecast["cutoff"]) != effective:
        raise ValueError("forecast and simulation cutoffs differ")
    if simulation.get("requested_cutoff") != forecast.get("requested_cutoff"):
        raise ValueError("forecast and simulation requested cutoffs differ")
    requested_value = simulation.get("requested_cutoff", forecast.get("requested_cutoff"))
    requested = milliseconds(requested_value) if requested_value else effective
    if trace.state is None or not trace.states:
        raise ValueError("state missing at effective cutoff")
    latest = trace.states[-1][0]
    if latest != effective:
        raise ValueError("effective cutoff is not the latest frozen snapshot")
    maximum_gap = forecast.get("settings", {}).get("max_gap_seconds", 3.0)
    if not math.isfinite(maximum_gap) or maximum_gap <= 0:
        raise ValueError("invalid forecast max_gap_seconds")
    if requested < latest or requested - latest > maximum_gap * 1000:
        raise ValueError("state is stale at the requested cutoff")


def _rederive_inputs(forecast_dir, forecast, simulation, template, trace, initial, scenarios):
    """Rebuild schema-2 inputs and require exact state/profile completeness.

    Args:
        forecast_dir (Path): Frozen forecast output directory.
        forecast (dict): Ready forecast summary and settings.
        simulation (dict): Published schema-2 simulation manifest.
        template (dict): Validated frozen workload template.
        trace (Trace): Trace reconstructed from bounded observer evidence.
        initial (dict): Published initial state.
        scenarios (list[list[dict]]): Published normalized combined scenarios.

    Returns:
        dict: Reconstructed membership diagnostics from the frozen observer prefix.

    Raises:
        ValueError: Re-derived state, trims, futures, or lineage differ.
    """
    expected_count = forecast["settings"].get("scenarios")
    if expected_count <= 0 or len(simulation["scenarios"]) != expected_count:
        raise ValueError("simulation scenario count differs from ready forecast settings")
    future_scenarios = []
    for index, metadata in enumerate(simulation["scenarios"]):
        future = _read_tasks(Path(forecast_dir) / "scenarios" / f"{index:04d}")
        lineage = metadata["future_tasks"]
        if [task["id"] for task in future] != [row["task_id"] for row in lineage]:
            raise ValueError("forecast future source differs from simulation lineage")
        for task, row in zip(future, lineage):
            if task["submission_time"] != row["original_submission_ms"]:
                raise ValueError("forecast source arrival differs from future lineage")
            task["submission_time"] = row.get(
                "original_submission_time", iso(row["original_submission_ms"])
            )
        future_scenarios.append(future)
    settings = forecast["settings"]
    derived_manifest, derived_initial, derived_scenarios = build_simulation_inputs(
        trace,
        template,
        future_scenarios,
        SimpleNamespace(
            run_id=settings["run_id"],
            horizon_seconds=settings["horizon_seconds"],
            scenarios=len(future_scenarios),
            image_count=settings.get("image_count", template["record"]["source"]["image_count"]),
            inference_repetitions=settings.get(
                "inference_repetitions",
                template["record"]["source"].get("inference_repetitions", 1),
            ),
        ),
    )
    if derived_manifest["status"] != "ready":
        raise ValueError("frozen evidence no longer derives ready simulation inputs")
    if derived_initial != initial:
        raise ValueError("initial state or remaining profiles differ from frozen evidence")
    if derived_scenarios != scenarios:
        raise ValueError("combined scenarios differ from re-derived sampled futures")
    for key, value in derived_manifest.items():
        if key == "membership" and key not in simulation:
            # Historical schema-2 exports predate membership diagnostics. Their
            # executable state/profile comparisons remain mandatory; absence
            # of the new inventory does not establish complete membership.
            continue
        if simulation.get(key) != value:
            raise ValueError(f"simulation {key} differs from re-derived inputs")
    return derived_manifest["membership"]


def _load_evidence(forecast_dir, observer_dir):
    """Load frozen evidence and compare it with one complete reconstruction.

    The reconstruction checks initial state, profile trimming and scenario lineage
    together; separate partial reimplementations of those checks are unnecessary.

    Args:
        forecast_dir (str or Path): Ready forecast output.
        observer_dir (str or Path): Observer stream directory.

    Returns:
        tuple: Forecast, simulation, initial state, template, trace, scenarios, and boundaries.

    Raises:
        ValueError: Readiness, source hashes, freshness, or lineage validation fails.
    """
    forecast_dir = Path(forecast_dir)
    forecast = json.loads((forecast_dir / "forecast.json").read_text())
    simulation = json.loads((forecast_dir / "simulation/manifest.json").read_text())
    initial = json.loads((forecast_dir / "simulation/initial-state.json").read_text())
    template = json.loads((forecast_dir / "template.json").read_text())
    boundaries = json.loads((forecast_dir / "boundaries.json").read_text())
    if forecast.get("status") != "ready":
        raise ValueError("forecast is not ready")
    if forecast.get("simulation_inputs", {}).get("status") != "ready":
        raise ValueError("forecast simulation inputs are not ready")
    if simulation.get("schema_version") != 2 or simulation.get("status") != "ready":
        raise ValueError("expected ready schema-2 simulation inputs")
    if forecast.get("inputs") != boundaries or simulation.get("inputs") != boundaries:
        raise ValueError("forecast source-prefix provenance mismatch")
    rows, replayed_boundaries = bounded_read(observer_dir, boundaries)
    if replayed_boundaries != boundaries:
        raise ValueError("observer prefix replay mismatch")
    run_id = forecast.get("settings", {}).get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("forecast workload run ID is missing")
    trace = read_trace(rows, run_id, simulation["cutoff_ms"])
    _validate_freshness(forecast, simulation, trace)
    _validate_template(
        template,
        forecast,
        simulation,
        read_trace(rows, run_id, milliseconds(template["selection_cutoff"])),
    )
    if json.loads((forecast_dir / "state.json").read_text()) != trace.state:
        raise ValueError("saved state differs from frozen observer state")
    scenarios = [
        _read_tasks(forecast_dir / "simulation/scenarios" / f"{index:04d}")
        for index in range(len(simulation["scenarios"]))
    ]
    simulation["membership"] = _rederive_inputs(
        forecast_dir, forecast, simulation, template, trace, initial, scenarios
    )
    return forecast, simulation, initial, template, trace, scenarios, boundaries


def _assignment_evidence(trace, metadata):
    """Derive the first observed assignment without substituting other timestamps.

    Args:
        trace (Trace): Cutoff-filtered observer trace.
        metadata (dict): Initial Task metadata with Job and worker identity.

    Returns:
        dict: First-observation timestamp, basis, and censoring evidence.
    """
    uid = metadata.get("kubernetes_job_uid")
    node_name = metadata.get("node_name")
    if not node_name:
        return {
            "preserved_assignment": None,
            "first_assignment_observed_ms": None,
            "assignment_time_basis": None,
            "assignment_left_censored": False,
        }
    observations = []
    for timestamp, state in trace.states:
        for group in ("queued", "active"):
            for observed in state["jobs"][group]:
                if observed.get("kubernetes_job_uid") == uid:
                    observations.append((timestamp, observed.get("node_name")))
                    break
    assigned = [timestamp for timestamp, worker in observations if worker == node_name]
    first = min(assigned) if assigned else trace.cutoff
    earlier = [timestamp for timestamp, _worker in observations if timestamp < first]
    left_censored = not earlier
    return {
        "preserved_assignment": node_name,
        "first_assignment_observed_ms": first,
        "assignment_time_basis": "first_observed_assignment",
        "assignment_left_censored": left_censored,
        "assignment_observation_uncertainty": (
            "left-censored at first frozen observation"
            if left_censored
            else "assignment occurred after the prior observation and by this observation"
        ),
    }


def _enrich_backlog(initial, trace):
    """Add cohort, identity, and assignment-observation evidence to backlog records.

    Args:
        initial (dict): Validated schema-2 initial state.
        trace (Trace): Cutoff-filtered observer trace.

    Returns:
        tuple: Executable backlog records and model-exhaustion evidence.
    """
    tasks = []
    for item in initial.get("tasks", []):
        metadata = copy.deepcopy(item["metadata"])
        metadata.update(_assignment_evidence(trace, metadata))
        metadata.update(
            cohort="backlog",
            identity={
                "task_id": item["task"]["id"],
                "kubernetes_job_uid": metadata.get("kubernetes_job_uid"),
                "request_id": metadata.get("request_id"),
            },
        )
        tasks.append({"task": copy.deepcopy(item["task"]), "metadata": metadata})
    exhausted = []
    for item in initial.get("model_exhausted_jobs", []):
        copied = copy.deepcopy(item)
        copied["metadata"].update(_assignment_evidence(trace, copied["metadata"]))
        copied["metadata"].update(
            cohort="backlog",
            identity={
                "task_id": copied["task_id"],
                "kubernetes_job_uid": copied["metadata"].get("kubernetes_job_uid"),
                "request_id": copied["metadata"].get("request_id"),
            },
        )
        exhausted.append(copied)
    return tasks, exhausted


def _future_metadata(lineage):
    """Create case metadata for one sampled future Task.

    Args:
        lineage (dict): Schema-2 future Task lineage.

    Returns:
        dict: Case metadata preserving the original forecast timestamp and identity.
    """
    copied = copy.deepcopy(lineage)
    copied.update(
        cohort="future",
        phase="future",
        original_creation_ms=lineage.get("original_submission_ms"),
        preserved_assignment=None,
        identity={
            "task_id": lineage.get("task_id"),
            "template_job_uid": lineage.get("template_job_uid"),
            "template_request_id": lineage.get("template_request_id"),
        },
    )
    return copied


def release_backlog(trace, simulation, calibration):
    """Retain requests of observed finished classifiers until their Pods terminate.

    Args:
        trace (Trace): Current availability-bounded worker and Job snapshot.
        simulation (dict): Validated Job-to-task identities for the same cutoff.
        calibration (dict or None): Optional frozen lifecycle model.

    Returns:
        list[dict]: Pinned occupancy-only Tasks with the already observed classifier finish.

    Raises:
        ValueError: A held allocation lacks identity, timing or homogeneous request evidence.
    """
    if calibration is None:
        return []
    records = []
    resources = calibration["residual_resources"]
    for job in trace.state["jobs"].get("finished", []):
        if job.get("pod_phase") in ("Succeeded", "Failed") or job.get("job_terminal_status") in (
            "Complete",
            "Failed",
        ):
            continue
        uid = job.get("kubernetes_job_uid")
        if (
            not job.get("node_name")
            or uid not in simulation["job_ids"]
            or not job.get("execution_finish_time")
        ):
            raise ValueError("unreleased Pod lacks assignment, identity or classifier finish")
        finish = milliseconds(job["execution_finish_time"])
        creation = milliseconds(job["creation_time"])
        if (
            not creation <= finish <= trace.cutoff
            or job.get("requested_cpu_count") != resources["cpu_count"]
            or job.get("requested_memory_mb") != resources["mem_capacity"]
        ):
            raise ValueError("unreleased Pod timing or request differs from the calibrated model")
        duration = max(1000, calibration["release_ms"] - (trace.cutoff - finish))
        task_id = simulation["job_ids"][uid]
        metadata = {
            "cohort": "backlog",
            "phase": "release",
            "node_name": job["node_name"],
            "kubernetes_job_uid": uid,
            "original_creation_ms": creation,
            "identity": {
                "task_id": task_id,
                "kubernetes_job_uid": uid,
                "request_id": job.get("request_id"),
            },
            "release_observation": copy.deepcopy(job),
            "occupancy": {
                "release_only": True,
                "profile_exhausted": False,
                "startup_ms": 0,
                "release_ms": 0,
                "classifier_profile_ms": 0,
                "observed_classifier_finish_ms": finish,
                "release_basis": "remaining calibrated release with one-second still-held floor",
            },
        }
        metadata.update(_assignment_evidence(trace, metadata))
        task = {key: resources[key] for key in ("cpu_count", "cpu_capacity", "mem_capacity")}
        task.update(
            id=task_id,
            submission_time=0,
            duration=duration,
            fragments=[
                {
                    "id": task_id,
                    "duration": duration,
                    "cpu_count": resources["cpu_count"],
                    "cpu_usage": 0.0,
                }
            ],
        )
        records.append({"task": task, "metadata": metadata})
    return records


def _worker_records(worker_config, trace, template, backlog, exhausted):
    """Validate worker configuration and construct modeled worker records.

    Args:
        worker_config (dict): Configured observed and reserve workers.
        trace (Trace): Cutoff-filtered observer trace.
        template (dict): Frozen task template used for frequency defaults.
        backlog (list[dict]): Executable backlog records.
        exhausted (list[dict]): Model-exhausted Job evidence.

    Returns:
        tuple: Worker records by name and active worker names.

    Raises:
        ValueError: Configuration, active state, or admission evidence is unsupported.
    """
    if not isinstance(worker_config, dict) or not isinstance(worker_config.get("workers"), list):
        raise ValueError("worker_config must contain a workers list")
    configured = {}
    default_frequency = template["record"]["task"]["cpu_capacity"]
    for item in worker_config["workers"]:
        if not isinstance(item, dict) or not isinstance(item.get("node_name"), str):
            raise ValueError("each configured worker requires node_name")
        name = item["node_name"]
        if not name or name in configured:
            raise ValueError("configured worker names must be unique and nonempty")
        cores = item.get("configured_cores")
        if isinstance(cores, bool) or not isinstance(cores, int) or cores <= 1:
            raise ValueError("configured_cores must be an integer greater than one")
        for field in ("memory_mib",):
            value = item.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field} must be finite and positive")
        record = {
            "node_name": name,
            "configured_cores": cores,
            "modeled_cores": cores - 1,
            "configured_memory_mib": item["memory_mib"],
            "memory_mib": item["memory_mib"],
            "frequency_mhz": item.get("frequency_mhz", default_frequency),
            "idle_power_w": item.get("idle_power_w", 100),
            "max_power_w": item.get("max_power_w", 200),
        }
        for field in ("frequency_mhz", "idle_power_w", "max_power_w"):
            value = record[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field} must be finite and positive")
        if record["max_power_w"] < record["idle_power_w"]:
            raise ValueError("max_power_w must be at least idle_power_w")
        configured[name] = record

    observed = {worker["node_name"]: worker for worker in trace.state["workers"]}
    if any(not worker["ready"] for worker in observed.values()):
        raise ValueError("unready initial workers are unsupported")
    requested_active = worker_config.get("active_workers")
    active = sorted(observed) if requested_active is None else requested_active
    if (
        not isinstance(active, list)
        or not active
        or len(active) != len(set(active))
        or any(not isinstance(name, str) for name in active)
    ):
        raise ValueError("active_workers must be a nonempty list of unique names")
    if any(name not in observed or name not in configured for name in active):
        raise ValueError("active worker is absent from observed state or configuration")
    if any(not observed[name]["schedulable"] for name in active):
        raise ValueError("unschedulable active workers are unsupported")
    assigned = {
        item["metadata"].get("node_name")
        for item in backlog + exhausted
        if item["metadata"].get("node_name")
    }
    # Explicitly excluded Ready workers may be cordoned warm reserves, but no
    # observed live assignment may be reclassified as an initially empty reserve.
    assigned.update(
        job["node_name"]
        for group in ("queued", "active", "finished")
        for job in trace.state["jobs"].get(group, [])
        if job.get("node_name")
        and job.get("pod_phase") not in ("Succeeded", "Failed")
        and job.get("job_terminal_status") not in ("Complete", "Failed")
    )
    draining = worker_config.get("draining_workers", [])
    if (
        not isinstance(draining, list)
        or len(draining) > 1
        or any(not isinstance(name, str) for name in draining)
        or set(draining).intersection(active)
        or any(name not in observed or name not in configured for name in draining)
        or any(observed[name]["schedulable"] for name in draining)
    ):
        raise ValueError("draining_workers must identify at most one observed cordoned worker")
    if not assigned.issubset(set(active + draining)):
        raise ValueError("assigned worker is excluded from active state")
    minimum = worker_config.get("minimum_workers", 1)
    maximum = worker_config.get("maximum_workers", 3)
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or not 1 <= minimum <= maximum
        or not minimum <= len(active) <= maximum
    ):
        raise ValueError("active worker count must respect positive integral capacity bounds")
    for name in set(configured).intersection(observed):
        configured[name]["observed_allocatable_memory_mib"] = observed[name][
            "allocatable_memory_mb"
        ]
        configured[name]["memory_mib"] = math.floor(observed[name]["allocatable_memory_mb"])
    return configured, sorted(active)


def _down_worker(active, backlog, exhausted, *, preferred=None):
    """Choose one deterministic scale-down worker from assignment observations.

    Args:
        active (list[str]): Active worker names.
        backlog (list[dict]): Enriched executable backlog.
        exhausted (list[dict]): Enriched model-exhausted evidence.
        preferred (str or None): Prior winning target to resimulate while still accepting.

    Returns:
        str: Selected worker name; scores are always recomputed from the new state.
    """
    if preferred in active:
        return preferred
    assigned = {name: [] for name in active}
    for item in backlog + exhausted:
        metadata = item["metadata"]
        name = metadata.get("preserved_assignment")
        if name in assigned:
            assigned[name].append(metadata["first_assignment_observed_ms"])
    empty = sorted(name for name, timestamps in assigned.items() if not timestamps)
    if empty:
        return empty[0]
    return min(active, key=lambda name: (max(assigned[name]), name))


def _topology(workers):
    """Create an OpenDC topology retaining actual worker host names.

    Args:
        workers (list[dict]): Modeled worker records.

    Returns:
        dict: OpenDC SDK topology.
    """
    return adapt_topology(
        {
            "clusters": [
                {
                    "name": "provisional",
                    "hosts": [
                        {
                            "name": worker["node_name"],
                            "cpu": {
                                "coreCount": worker["modeled_cores"],
                                "coreSpeed": f'{worker["frequency_mhz"]} MHz',
                            },
                            "memory": {"size": f'{worker["memory_mib"]} MiB'},
                            "cpuPowerModel": {
                                "type": "linear",
                                "idlePower": f'{worker["idle_power_w"]} W',
                                "maxPower": f'{worker["max_power_w"]} W',
                            },
                        }
                        for worker in workers
                    ],
                    "powerSource": {"name": "grid", "maxPower": "10000 W"},
                }
            ]
        }
    )


def _case_tasks(candidate, selected_worker, source_tasks, backlog_metadata, future_lineage):
    """Partition one source scenario and attach preserved case metadata.

    Args:
        candidate (str): unchanged, up, or down.
        selected_worker (str or None): Worker omitted by a down candidate.
        source_tasks (list[dict]): Exact schema-2 source scenario Tasks.
        backlog_metadata (dict): Enriched metadata keyed by Task ID.
        future_lineage (list[dict]): Forecast lineage for sampled future Tasks.

    Returns:
        tuple: Included Task records, included metadata records, and omitted records.
    """
    future = {row["task_id"]: _future_metadata(row) for row in future_lineage}
    included = []
    omitted = []
    for task in source_tasks:
        metadata = copy.deepcopy(backlog_metadata.get(task["id"], future.get(task["id"])))
        if metadata is None:
            raise ValueError("Task has no backlog or future lineage metadata")
        record = {"task": copy.deepcopy(task), "metadata": metadata}
        if candidate == "scale-down" and metadata.get("preserved_assignment") == selected_worker:
            omitted.append(record)
        else:
            included.append(record)
    return [item["task"] for item in included], included, omitted


def _write_case(
    directory,
    candidate,
    scenario_index,
    workers,
    tasks,
    task_records,
    omitted,
    exhausted,
    simulation,
    initialization_mode,
    selected_worker,
    experiment_kind,
    draining_worker=None,
    occupancy_model=None,
):
    """Write one experiment and publish its ready case manifest last.

    Args:
        directory (Path): New case directory.
        candidate (str): unchanged, up, or down.
        scenario_index (int): Forecast scenario index.
        workers (list[dict]): Candidate worker records.
        tasks (list[dict]): Included exact source Task profiles.
        task_records (list[dict]): Included Task records with metadata.
        omitted (list[dict]): Down-candidate omitted Task inventory.
        exhausted (list[dict]): Model-exhausted Job evidence.
        simulation (dict): Source simulation manifest.
        initialization_mode (str): Provisional trace or explicitly requested FNS pinning.
        selected_worker (str or None): Down worker, when applicable.
        experiment_kind (str): Observed or explicitly synthetic experiment label.
        draining_worker (str or None): Existing cordon whose assigned work still drains.
        occupancy_model (dict or None): Frozen causal lifecycle and residual estimates.

    Returns:
        dict: Published case manifest.
    """
    pinned = initialization_mode == PINNED_MODE
    case = {
        "initialization_mode": initialization_mode,
        "candidate": candidate,
        "experiment_kind": experiment_kind,
        "scenario": scenario_index,
        "scope": "remaining_workers_only"
        if candidate == "scale-down" and not pinned
        else "complete",
        "selected_worker": selected_worker,
        "initial_cordoned_worker": draining_worker,
        "cutoff_ms": simulation["cutoff_ms"],
        "horizon_ms": simulation["horizon_ms"],
        "initial_membership": copy.deepcopy(simulation.get("membership")),
        "workers": workers,
        "tasks": task_records,
        "omitted_tasks": omitted,
        "model_exhausted_jobs": copy.deepcopy(exhausted),
        "assignment_time_basis": (
            "first observed node assignment in frozen pre-cutoff snapshots; "
            "observations may be left-censored"
        ),
    }
    if occupancy_model:
        case = apply_occupancy(case, occupancy_model)
        tasks = [item["task"] for item in case["tasks"]]
    assignments = initial_assignments(case) if pinned else None
    config = experiment_config()
    if pinned:
        case["initialization"] = initialization_metadata(assignments, case)
        cordon = draining_worker or (selected_worker if candidate == "scale-down" else None)
        config["cordonHosts"] = [[cordon] if cordon else []]
        config["exportModels"][0]["filesToExport"].append("datacenter")
    directory.mkdir(parents=True, exist_ok=False)
    parquet_tasks(tasks, directory / "source")
    adapt_trace(directory / "source", directory / "trace", assignments)
    write_json(directory / "topology.json", _topology(workers))
    write_json(directory / "experiment.json", config)
    write_json(directory / "case.json", case)
    manifest = {
        "contract": FNS_CONTRACT if pinned else PROVISIONAL_CONTRACT,
        "status": "ready",
        "initial_state": initialization_mode,
        **runtime_identity(),
        "sha256": file_hashes(directory, exclude=("manifest.json",)),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def prepare_occupancy_model(worker_config, forecast, template, observer_dir, boundaries):
    """Reconstruct optional lifecycle calibration solely at frozen profile selection.

    Args:
        worker_config (dict): Explicit optional occupancy_model contract name.
        forecast (dict): Forecast providing workload identity.
        template (dict): Selected classifier profile and causal selection cutoff.
        observer_dir (Path): Immutable observer-prefix source.
        boundaries (dict): Exact verified byte boundaries from this forecast.

    Returns:
        dict or None: Causal calibration, or the original classifier-only model.

    Raises:
        ValueError: The requested model is unknown or selection evidence is invalid.
    """
    contract = worker_config.get("occupancy_model")
    if contract is None:
        return None
    if contract != "causal-occupancy-v1":
        raise ValueError("unknown occupancy model")
    rows, _ = bounded_read(observer_dir, boundaries)
    trace = read_trace(
        rows, forecast["settings"]["run_id"], milliseconds(template["selection_cutoff"])
    )
    return calibrate_occupancy(trace, template)


def prepare_suite(
    forecast_dir,
    observer_dir,
    worker_config,
    output_dir,
    initialization_mode=SUPPORTED_INITIALIZATION,
):
    """Prepare unchanged, scale-up, and scale-down experiments from one forecast.

    Source evidence is verified at its saved byte boundaries and copied without
    mutation. Every available candidate uses the same sampled future for a
    scenario. Ready case and suite manifests are their respective commit markers.

    Args:
        forecast_dir (str or Path): Ready forecast output with schema-2 simulation inputs.
        observer_dir (str or Path): Original append-only observer stream directory.
        worker_config (dict): Observed/reserve worker configuration and optional active list.
        output_dir (str or Path): New suite destination.
        initialization_mode (str): ``provisional-trace`` or FNS ``pinned-trace``.

    Returns:
        dict: Ready suite manifest with relative experiment input paths.

    Raises:
        FileExistsError: The suite destination already exists.
        ValueError: Inputs are unready, stale, inconsistent, tampered, or unsupported.
    """
    if initialization_mode not in INITIALIZATION_MODES:
        raise ValueError("unsupported initialization mode")
    pinned = initialization_mode == PINNED_MODE
    if pinned and not fns_runtime():
        raise ValueError("pinned-trace requires the FNS runtime")
    output = Path(output_dir).resolve()
    forecast_dir, observer_dir = Path(forecast_dir).resolve(), Path(observer_dir).resolve()
    for source in (forecast_dir, observer_dir):
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("output and source evidence directories must be separate")
    source_hashes = file_hashes(forecast_dir)
    if output.exists():
        raise FileExistsError(output)
    forecast, simulation, initial, template, trace, scenarios, boundaries = _load_evidence(
        forecast_dir, observer_dir
    )
    backlog, exhausted = _enrich_backlog(initial, trace)
    configured, active = _worker_records(worker_config, trace, template, backlog, exhausted)
    occupancy_model = prepare_occupancy_model(
        worker_config, forecast, template, observer_dir, boundaries
    )
    releasing = release_backlog(trace, simulation, occupancy_model)
    backlog.extend(releasing)
    draining = worker_config.get("draining_workers", [])
    if draining and not pinned:
        raise ValueError("persistent draining requires pinned-trace initialization")
    experiment_kind = forecast.get("experiment_kind", "observed-replay")
    if not isinstance(experiment_kind, str) or not experiment_kind:
        raise ValueError("experiment_kind must be a nonempty string")

    occupied = sorted(active + draining)
    candidates = [("unchanged", occupied, None)]
    unavailable = []
    if len(active) >= worker_config.get("maximum_workers", 3):
        unavailable.append({"candidate": "scale-up", "reason": "maximum_worker_count"})
    else:
        reserves = sorted(set(configured) - set(occupied))
        if reserves:
            candidates.append(("scale-up", sorted(occupied + [reserves[0]]), reserves[0]))
        else:
            unavailable.append({"candidate": "scale-up", "reason": "no_configured_reserve"})
    if draining:
        unavailable.append({"candidate": "scale-down", "reason": "worker_already_draining"})
    elif occupancy_model and (exhausted or not simulation["membership"]["complete"]):
        unavailable.append({"candidate": "scale-down", "reason": "exhausted_or_unresolved_work"})
    elif len(active) <= worker_config.get("minimum_workers", 1):
        unavailable.append({"candidate": "scale-down", "reason": "minimum_worker_count"})
    else:
        selected = _down_worker(
            active, backlog, exhausted, preferred=worker_config.get("preferred_down_worker")
        )
        if pinned and any(
            item["metadata"].get("preserved_assignment") == selected for item in exhausted
        ):
            unavailable.append(
                {"candidate": "scale-down", "reason": "selected_worker_has_exhausted_work"}
            )
        else:
            remaining = active if pinned else [name for name in active if name != selected]
            candidates.append(("scale-down", remaining, selected))

    output.mkdir(parents=True)
    evidence = output / "source-evidence"
    evidence.mkdir()
    shutil.copytree(forecast_dir, evidence / "forecast")
    if file_hashes(evidence / "forecast") != source_hashes:
        raise ValueError("forecast evidence changed while copying")
    write_json(evidence / "observer-prefixes.json", boundaries)
    write_json(evidence / "forecast-file-sha256.json", source_hashes)

    backlog_metadata = {item["task"]["id"]: item["metadata"] for item in backlog}
    experiments = []
    for candidate, worker_names, selected_worker in candidates:
        workers = [copy.deepcopy(configured[name]) for name in worker_names]
        for scenario_index, source_tasks in enumerate(scenarios):
            source_tasks = source_tasks + [item["task"] for item in releasing]
            tasks, records, omitted = _case_tasks(
                "unchanged" if pinned else candidate,
                selected_worker,
                source_tasks,
                backlog_metadata,
                simulation["scenarios"][scenario_index]["future_tasks"],
            )
            relative = Path("experiments") / candidate / f"{scenario_index:04d}"
            _write_case(
                output / relative,
                candidate,
                scenario_index,
                workers,
                tasks,
                records,
                omitted,
                exhausted,
                simulation,
                initialization_mode,
                selected_worker,
                experiment_kind,
                draining[0] if draining else None,
                occupancy_model,
            )
            experiments.append(
                {
                    "candidate": candidate,
                    "scenario": scenario_index,
                    "input_dir": relative.as_posix(),
                }
            )
    manifest = {
        "contract": SUITE_CONTRACT,
        "status": "ready",
        "initialization_mode": initialization_mode,
        "experiment_kind": experiment_kind,
        "cutoff_ms": simulation["cutoff_ms"],
        "horizon_ms": simulation["horizon_ms"],
        "template_sha256": template["sha256"],
        "source_prefixes": boundaries,
        "initial_membership": copy.deepcopy(simulation["membership"]),
        "active_workers": active,
        "down_target_preference": worker_config.get("preferred_down_worker"),
        "draining_workers": draining,
        "experiments": experiments,
        "unavailable_candidates": unavailable,
        "sha256": file_hashes(output, exclude=("manifest.json",)),
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def parser():
    """Build the scenario-preparation command-line parser.

    Returns:
        argparse.ArgumentParser: Parser with the required ``prepare`` subcommand.
    """
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="prepare a provisional experiment suite")
    prepare.add_argument("--forecast-dir", type=Path, required=True)
    prepare.add_argument("--observer-dir", type=Path, required=True)
    prepare.add_argument(
        "--workers", type=Path, required=True, help="path to worker configuration JSON"
    )
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument(
        "--initialization-mode",
        choices=INITIALIZATION_MODES,
        required=True,
    )
    return result


def main():
    """Prepare one suite from command-line arguments and print its manifest."""
    args = parser().parse_args()
    manifest = prepare_suite(
        args.forecast_dir,
        args.observer_dir,
        json.loads(Path(args.workers).read_text(encoding="utf-8")),
        args.output_dir,
        args.initialization_mode,
    )
    sys.stdout.buffer.write(canonical(manifest))


if __name__ == "__main__":
    main()
