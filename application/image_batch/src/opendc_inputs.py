"""Controlled fixtures and explicit compatibility with the pinned OpenDC reader."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import platform
import time

import pyarrow as pa
import pyarrow.parquet as pq

from forecast_trace import canonical, parquet_tasks
from opendc_runtime import (
    adapt_topology,
    fns_runtime,
    runtime_identity,
    topology_hosts,
    verify_runtime,
)

VERSION = "master-7db7e1a2331fd"
COMMIT = "7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad"
SOURCE_ARCHIVE_SHA256 = "df798dae10c0ee3b1911fb01b0dbd25f06f5adb6e8495826dc8ad8b108f4f52d"
CONTRACT = "opendc-controlled-v2"
PROVISIONAL_CONTRACT = "opendc-provisional-v1"
EXECUTION_CONTRACTS = (CONTRACT, PROVISIONAL_CONTRACT)
FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "opendc"


def write_json(path, value):
    """Write canonical JSON through a sibling temporary file and atomic rename.

    The parent directory must exist. Readers see the previous complete record
    or its replacement; an interrupted write may leave the temporary file.

    Args:
        path (str or Path): Destination file in an existing directory.
        value (object): JSON-serializable record to publish.
    """
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def file_hashes(directory, exclude=()):
    """Return relative POSIX file paths mapped to SHA-256 artifact digests.

    Args:
        directory (str or Path): Root to scan recursively.
        exclude (tuple): Relative file paths to omit, usually the manifest itself.

    Returns:
        dict[str, str]: Relative file paths mapped to SHA-256 digests.

    Raises:
        ValueError: A symlink is encountered, including at an excluded path.
    """
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in experiment artifacts: {path}")
        name = path.relative_to(directory).as_posix()
        if path.is_file() and name not in exclude:
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def fixture_tasks(fixture):
    """Expand synthetic task groups into Task/Fragment export records.

    Assign consecutive task IDs while preserving group and fragment order.
    Durations and arrivals are milliseconds, CPU demand is MHz, and memory
    remains MiB here; reader-specific conversions happen in adapt_trace.

    Args:
        fixture (dict): Synthetic task groups and their resource/profile settings.

    Returns:
        list[dict]: Task records with consecutive IDs and ordered Fragment records.
    """
    tasks = []
    for group in fixture["tasks"]:
        for _ in range(group["count"]):
            task_id = len(tasks)
            tasks.append(
                {
                    "id": task_id,
                    "submission_time": group["submission_ms"],
                    "duration": sum(fragment[0] for fragment in group["fragments"]),
                    "cpu_count": 1,
                    "cpu_capacity": float(fixture["frequency_mhz"]),
                    "mem_capacity": group["memory_mib"],
                    "fragments": [
                        {
                            "id": task_id,
                            "duration": duration,
                            "cpu_count": 1,
                            "cpu_usage": float(usage),
                        }
                        for duration, usage in group["fragments"]
                    ],
                }
            )
    return tasks


def topology_for(fixture):
    """Return SDK topology JSON with synthetic hosts and explicit resource units.

    The fixed linear power curves are test inputs, not calibrated worker power.

    Args:
        fixture (dict): Host count, cores, frequency and memory for the test topology.

    Returns:
        dict: OpenDC SDK topology with synthetic hosts and a grid power source.
    """
    return adapt_topology(
        {
            "clusters": [
                {
                    "name": "synthetic",
                    "hosts": [
                        {
                            "name": f"test-host-{index}",
                            "cpu": {
                                "coreCount": fixture["cores_per_host"],
                                "coreSpeed": f'{fixture["frequency_mhz"]} MHz',
                            },
                            "memory": {"size": f'{fixture["memory_mib_per_host"]} MiB'},
                            "cpuPowerModel": {
                                "type": "linear",
                                "idlePower": "100 W",
                                "maxPower": "200 W",
                            },
                        }
                        for index in range(fixture["host_count"])
                    ],
                    "powerSource": {"name": "grid", "maxPower": "10000 W"},
                }
            ]
        }
    )


def experiment_config():
    """Return one seeded SDK experiment with CPU/RAM admission and 1 s exports.

    Input references are relative placeholders resolved before execution.

    Returns:
        dict: Single-run SDK configuration with seed zero and native table exports.
    """
    return {
        "name": "controlled",
        "runs": 1,
        "initialSeed": 0,
        "topologies": [{"importFrom": "topology.json"}],
        "workloads": [
            {
                "source": {"type": "named", "name": "trace"},
                "type": "trace",
                "sampleFraction": 1.0,
                "scalingPolicy": "NoDelay",
                "deferAll": False,
            }
        ],
        "allocationPolicies": [
            {
                "type": "filter",
                "filters": [
                    {"type": "compute"},
                    {"type": "vcpu", "allocationRatio": 1.0},
                    {"type": "ram", "allocationRatio": 1.0},
                ],
                "weighers": [],
                "subsetSize": 1,
            }
        ],
        "failureModels": [{"type": "none"}],
        "checkpointModels": [None],
        "exportModels": [
            {
                "exportInterval": "1 s",
                "printFrequency": None,
                "filesToExport": ["task", "host", "service", "powerSource"],
            }
        ],
    }


def adapt_trace(source, destination):
    """Create simulator-facing Parquet copies for the pinned OpenDC reader.

    Multiply Task memory by 1,000 to compensate for the reader's division and
    annotate submission times as UTC milliseconds without shifting them.
    Preserve the original tables and copy Fragment bytes unchanged.

    Args:
        source (Path): Directory containing original Task and Fragment tables.
        destination (Path): New directory whose parent already exists.

    Raises:
        FileExistsError: The destination already exists.
        ValueError: Memory is nonpositive or would overflow int64 after scaling.
    """
    destination.mkdir()
    tasks = pq.read_table(source / "tasks.parquet")
    names = tasks.schema.names
    memory = tasks["mem_capacity"].to_pylist()
    if any(value <= 0 or value > (2**63 - 1) // 1000 for value in memory):
        raise ValueError("Task memory cannot be represented by the pinned reader")
    tasks = tasks.set_column(
        names.index("mem_capacity"),
        pa.field("mem_capacity", pa.int64(), nullable=False),
        pa.array([value * 1000 for value in memory], type=pa.int64()),
    )
    timestamp = pa.timestamp("ms", tz="UTC")
    tasks = tasks.set_column(
        names.index("submission_time"),
        pa.field("submission_time", timestamp, nullable=False),
        tasks["submission_time"].cast(timestamp),
    )
    if fns_runtime() and "host" not in tasks.schema.names:
        tasks = tasks.append_column(
            pa.field("host", pa.string(), nullable=True),
            pa.array([None] * tasks.num_rows, type=pa.string()),
        )
    pq.write_table(tasks, destination / "tasks.parquet", compression="NONE", use_dictionary=False)
    (destination / "fragments.parquet").write_bytes((source / "fragments.parquet").read_bytes())


def prepare(fixture_name, output_dir):
    """Write one controlled experiment and publish its ready manifest last.

    Failed preparation may leave partial files without a ready manifest.

    Args:
        fixture_name (str): Built-in fixture name: controlled or memory.
        output_dir (str or Path): New directory for inputs and provenance.

    Returns:
        dict: Manifest describing the fixture, transformations and input hashes.

    Raises:
        ValueError: The fixture name is unsupported.
        FileExistsError: The output directory already exists.
    """
    started = time.monotonic()
    identity = runtime_identity()
    if fixture_name not in ("controlled", "memory"):
        raise ValueError("only controlled or memory fixtures are supported")
    fixture = json.loads((FIXTURE_ROOT / f"{fixture_name}.json").read_text())
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "fixture.json", fixture)
    write_json(directory / "topology.json", topology_for(fixture))
    write_json(directory / "experiment.json", experiment_config())
    parquet_tasks(fixture_tasks(fixture), directory / "source")
    adapt_trace(directory / "source", directory / "trace")
    manifest = {
        "contract": CONTRACT,
        "status": "ready",
        "fixture": fixture_name,
        "initial_state": "empty_synthetic",
        **identity,
        "transformations": {
            "submission_time": "int64 milliseconds -> timestamp[ms, UTC], no time shift",
            "mem_capacity": "exported MiB * 1000; pinned SDK ComputeWorkloadLoader divides by 1000",
            "fragments": "byte-preserved; reader ignores extra cpu_count column",
        },
        "python_version": platform.python_version(),
        "pyarrow_version": pa.__version__,
        "preparation_seconds": time.monotonic() - started,
        "sha256": file_hashes(directory),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def verify_inputs(directory):
    """Return the manifest after checking a ready, unmodified prepared experiment.

    Require pinned source identity and matching artifact hashes. Raw schema-2
    bundles remain unsupported; explicit provisional preparation is required.

    Args:
        directory (str or Path): Prepared experiment containing manifest.json and input files.

    Returns:
        dict: Verified ready manifest for the pinned controlled experiment.

    Raises:
        ValueError: The contract, version, fixture or hashes do not match.
        OSError: A required input file cannot be read.
    """
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("contract") == PROVISIONAL_CONTRACT:
        return _verify_provisional(directory, manifest)
    if (
        manifest.get("contract") != CONTRACT
        or manifest.get("status") != "ready"
        or manifest.get("fixture") not in ("controlled", "memory")
        or manifest.get("initial_state") != "empty_synthetic"
    ):
        raise ValueError("expected a ready controlled experiment, not a live simulation bundle")
    verify_runtime(manifest)
    if file_hashes(directory, exclude=("manifest.json",)) != manifest.get("sha256"):
        raise ValueError("controlled input hash mismatch")
    fixture = json.loads((directory / "fixture.json").read_text())
    expected = json.loads((FIXTURE_ROOT / f'{manifest["fixture"]}.json').read_text())
    if fixture != expected:
        raise ValueError("controlled fixture was modified")
    return manifest


def _verify_provisional(directory, manifest):
    """Check an explicitly prepared replay and its resource/profile contract.

    Args:
        directory (Path): Prepared input directory.
        manifest (dict): Parsed manifest with hashes and pinned source identity.

    Returns:
        dict: Verified manifest, unchanged.

    Raises:
        ValueError: Initialization, topology, profile, lineage or hashes disagree.
    """
    if manifest.get("status") != "ready" or manifest.get("initial_state") != "provisional-trace":
        raise ValueError("expected ready provisional-trace inputs for the pinned runner")
    verify_runtime(manifest)
    if file_hashes(directory, exclude=("manifest.json",)) != manifest.get("sha256"):
        raise ValueError("provisional input hash mismatch")
    case = json.loads((directory / "case.json").read_text())
    if case.get("initialization_mode") != "provisional-trace":
        raise ValueError("fixed placement is unsupported; no implicit replay fallback")
    partial = case.get("candidate") == "scale-down"
    if case.get("scope") != ("remaining_workers_only" if partial else "complete"):
        raise ValueError("candidate scope does not describe partial scale-down")
    workers = case["workers"]
    names = [worker["node_name"] for worker in workers]
    if not 1 <= len(names) <= 3 or len(set(names)) != len(names):
        raise ValueError("expected one to three uniquely identified workers")
    hosts = topology_hosts(json.loads((directory / "topology.json").read_text()))
    if {host["name"] for host in hosts} != set(names) or len(hosts) != len(names):
        raise ValueError("topology worker identities differ from case")
    for worker in workers:
        configured = worker["configured_cores"]
        if (
            type(configured) is not int
            or configured <= 1
            or worker["modeled_cores"] != configured - 1
        ):
            raise ValueError("worker capacity must apply C - 1 exactly once")
        for key in ("memory_mib", "frequency_mhz", "idle_power_w", "max_power_w"):
            if not math.isfinite(worker[key]) or worker[key] <= 0:
                raise ValueError("invalid worker resources/power")
        if worker["max_power_w"] < worker["idle_power_w"]:
            raise ValueError("maximum power is below idle power")
        host = next(host for host in hosts if host["name"] == worker["node_name"])
        if (
            host["cpu"]["coreCount"] != worker["modeled_cores"]
            or float(host["cpu"]["coreSpeed"].removesuffix(" MHz")) != worker["frequency_mhz"]
            or float(host["memory"]["size"].removesuffix(" MiB")) != worker["memory_mib"]
            or float(host["cpuPowerModel"]["idlePower"].removesuffix(" W"))
            != worker["idle_power_w"]
            or float(host["cpuPowerModel"]["maxPower"].removesuffix(" W")) != worker["max_power_w"]
        ):
            raise ValueError("topology resource or power model differs from case")
    _verify_case_lineage(case)
    records = case["tasks"]
    tasks = [record["task"] for record in records]
    ids = {task["id"] for task in tasks}
    omitted = {record["task"]["id"] for record in case["omitted_tasks"]}
    exhausted = {record["task_id"] for record in case["model_exhausted_jobs"]}
    if len(ids) != len(tasks) or ids & (omitted | exhausted) or (omitted and not partial):
        raise ValueError("task identities overlap included, omitted or exhausted work")
    source = pq.read_table(directory / "source/tasks.parquet").to_pylist()
    fragments = pq.read_table(directory / "source/fragments.parquet").to_pylist()
    if source != [
        {key: value for key, value in task.items() if key != "fragments"} for task in tasks
    ]:
        raise ValueError("source task profiles differ from case")
    if fragments != [fragment for task in tasks for fragment in task["fragments"]]:
        raise ValueError("source fragments differ from case")
    for record in records:
        task = record["task"]
        if (
            task["cpu_count"] != 1
            or task["duration"] <= 0
            or task["submission_time"] < 0
            or task["duration"] != sum(fragment["duration"] for fragment in task["fragments"])
            or task["mem_capacity"] <= 0
        ):
            raise ValueError("invalid executable application profile")
        if not any(task["mem_capacity"] <= worker["memory_mib"] for worker in workers):
            raise ValueError("task cannot fit any modeled worker")
        for fragment in task["fragments"]:
            if (
                fragment["id"] != task["id"]
                or fragment["duration"] <= 0
                or fragment["cpu_count"] != 1
                or not math.isfinite(fragment["cpu_usage"])
                or not 0 <= fragment["cpu_usage"] <= task["cpu_capacity"]
            ):
                raise ValueError("invalid application fragment")
    adapted = pq.read_table(directory / "trace/tasks.parquet")
    original = pq.read_table(directory / "source/tasks.parquet")
    for name in original.schema.names:
        values = adapted[name]
        if name == "submission_time":
            values = values.cast(pa.int64())
        values = values.to_pylist()
        expected = original[name].to_pylist()
        if name == "mem_capacity":
            expected = [value * 1000 for value in expected]
        if values != expected:
            raise ValueError("adapted trace differs from source")
    if (directory / "trace/fragments.parquet").read_bytes() != (
        directory / "source/fragments.parquet"
    ).read_bytes():
        raise ValueError("adapted fragments differ from source")
    return manifest


def _verify_case_lineage(case):
    """Require cohort, original-arrival and assignment evidence for every identity.

    Args:
        case (dict): Prepared provisional case including omitted and exhausted work.

    Raises:
        ValueError: Metadata is missing, contradicts its cohort, or loses omitted work scope.
    """
    cutoff, horizon = case["cutoff_ms"], case["horizon_ms"]
    if type(cutoff) is not int or type(horizon) is not int or horizon <= 0:
        raise ValueError("case needs an integral cutoff and positive arrival horizon")
    if case["candidate"] not in ("unchanged", "scale-up", "scale-down"):
        raise ValueError("unknown candidate")
    if type(case["scenario"]) is not int or case["scenario"] < 0:
        raise ValueError("invalid scenario index")
    names = {worker["node_name"] for worker in case["workers"]}
    selected = case.get("selected_worker")
    partial = case["candidate"] == "scale-down"
    if partial and (not isinstance(selected, str) or not selected or selected in names):
        raise ValueError("scale-down must identify its excluded worker")
    seen = set()
    for group in ("tasks", "omitted_tasks", "model_exhausted_jobs"):
        for item in case[group]:
            task = item.get("task")
            task_id = task["id"] if task else item["task_id"]
            metadata = item.get("metadata", {})
            original = metadata.get("original_creation_ms")
            identity = metadata.get("identity", {})
            if task_id in seen or identity.get("task_id") != task_id or type(original) is not int:
                raise ValueError("missing or conflicting original-arrival/identity metadata")
            seen.add(task_id)
            cohort = metadata.get("cohort")
            if cohort == "future":
                if (
                    group != "tasks"
                    or metadata.get("phase") != "future"
                    or "preserved_assignment" not in metadata
                    or metadata["preserved_assignment"] is not None
                    or not identity.get("template_job_uid")
                    or original != cutoff + task["submission_time"]
                    or not 0 <= task["submission_time"] < horizon
                ):
                    raise ValueError("future lineage or arrival window is inconsistent")
            elif cohort == "backlog":
                phase = metadata.get("phase")
                node = metadata.get("node_name")
                if (
                    phase not in ("queued", "startup", "running")
                    or original > cutoff
                    or not metadata.get("kubernetes_job_uid")
                    or identity.get("kubernetes_job_uid") != metadata["kubernetes_job_uid"]
                    or "preserved_assignment" not in metadata
                    or metadata["preserved_assignment"] != node
                    or (phase == "queued" and node is not None)
                    or (phase in ("startup", "running") and not node)
                    or (task is not None and task["submission_time"] != 0)
                ):
                    raise ValueError(
                        "backlog phase, arrival or assignment metadata is inconsistent"
                    )
                if node is not None:
                    first = metadata.get("first_assignment_observed_ms")
                    if type(first) is not int or not original <= first <= cutoff:
                        raise ValueError("missing or invalid observed assignment time")
                if group == "omitted_tasks" and (not partial or node != selected):
                    raise ValueError("omitted task does not belong to the excluded worker")
                if group == "tasks" and node is not None and node not in names:
                    raise ValueError("included task belongs to an omitted or unknown worker")
                if group == "model_exhausted_jobs" and (
                    phase != "running"
                    or item.get("remaining_execution_ms") != 0
                    or item.get("observed_completed") is not False
                    or node not in names | ({selected} if partial else set())
                ):
                    raise ValueError("invalid exhausted-work evidence")
            else:
                raise ValueError("missing task cohort")
