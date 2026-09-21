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
    COMMIT,
    PROVISIONAL_CONTRACT,
    SOURCE_ARCHIVE_SHA256,
    VERSION,
    adapt_trace,
    experiment_config,
    file_hashes,
    write_json,
)
from simulation_input import build_simulation_inputs


SUITE_CONTRACT = "opendc-scenarios-v1"
SUPPORTED_INITIALIZATION = "provisional-trace"


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
        if simulation.get(key) != value:
            raise ValueError(f"simulation {key} differs from re-derived inputs")


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
    _rederive_inputs(forecast_dir, forecast, simulation, template, trace, initial, scenarios)
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
    if any(not worker["ready"] or not worker["schedulable"] for worker in observed.values()):
        raise ValueError("unschedulable or unready initial workers are unsupported")
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
    assigned = {
        item["metadata"].get("node_name")
        for item in backlog + exhausted
        if item["metadata"].get("node_name")
    }
    if not assigned.issubset(set(active)):
        raise ValueError("assigned worker is excluded from active state")
    if not 1 <= len(active) <= 3:
        raise ValueError("active worker count must be between one and three")
    for name in set(configured).intersection(observed):
        configured[name]["observed_allocatable_memory_mib"] = observed[name][
            "allocatable_memory_mb"
        ]
        configured[name]["memory_mib"] = math.floor(observed[name]["allocatable_memory_mb"])
    return configured, sorted(active)


def _down_worker(active, backlog, exhausted):
    """Choose one deterministic scale-down worker from assignment observations.

    Args:
        active (list[str]): Active worker names.
        backlog (list[dict]): Enriched executable backlog.
        exhausted (list[dict]): Enriched model-exhausted evidence.

    Returns:
        str: Selected worker name.
    """
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
    return {
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
        initialization_mode (str): Required provisional initialization mode.
        selected_worker (str or None): Down worker, when applicable.
        experiment_kind (str): Observed or explicitly synthetic experiment label.

    Returns:
        dict: Published case manifest.
    """
    directory.mkdir(parents=True, exist_ok=False)
    parquet_tasks(tasks, directory / "source")
    adapt_trace(directory / "source", directory / "trace")
    write_json(directory / "topology.json", _topology(workers))
    write_json(directory / "experiment.json", experiment_config())
    case = {
        "initialization_mode": initialization_mode,
        "candidate": candidate,
        "experiment_kind": experiment_kind,
        "scenario": scenario_index,
        "scope": "remaining_workers_only" if candidate == "scale-down" else "complete",
        "selected_worker": selected_worker,
        "cutoff_ms": simulation["cutoff_ms"],
        "horizon_ms": simulation["horizon_ms"],
        "workers": workers,
        "tasks": task_records,
        "omitted_tasks": omitted,
        "model_exhausted_jobs": copy.deepcopy(exhausted),
        "assignment_time_basis": (
            "first observed node assignment in frozen pre-cutoff snapshots; "
            "observations may be left-censored"
        ),
    }
    write_json(directory / "case.json", case)
    manifest = {
        "contract": PROVISIONAL_CONTRACT,
        "status": "ready",
        "initial_state": initialization_mode,
        "opendc_version": VERSION,
        "opendc_commit": COMMIT,
        "opendc_source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "sha256": file_hashes(directory, exclude=("manifest.json",)),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


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
        initialization_mode (str): Must be ``provisional-trace``.

    Returns:
        dict: Ready suite manifest with relative experiment input paths.

    Raises:
        FileExistsError: The suite destination already exists.
        ValueError: Inputs are unready, stale, inconsistent, tampered, or unsupported.
    """
    if initialization_mode != SUPPORTED_INITIALIZATION:
        raise ValueError("only provisional-trace initialization is supported")
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
    experiment_kind = forecast.get("experiment_kind", "observed-replay")
    if not isinstance(experiment_kind, str) or not experiment_kind:
        raise ValueError("experiment_kind must be a nonempty string")

    candidates = [("unchanged", active, None)]
    unavailable = []
    if len(active) >= 3:
        unavailable.append({"candidate": "scale-up", "reason": "maximum_worker_count"})
    else:
        reserves = sorted(set(configured) - set(active))
        if reserves:
            candidates.append(("scale-up", sorted(active + [reserves[0]]), None))
        else:
            unavailable.append({"candidate": "scale-up", "reason": "no_configured_reserve"})
    if len(active) <= 1:
        unavailable.append({"candidate": "scale-down", "reason": "minimum_worker_count"})
    else:
        selected = _down_worker(active, backlog, exhausted)
        candidates.append(("scale-down", [name for name in active if name != selected], selected))

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
            tasks, records, omitted = _case_tasks(
                candidate,
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
        "active_workers": active,
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
        choices=(SUPPORTED_INITIALIZATION,),
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
