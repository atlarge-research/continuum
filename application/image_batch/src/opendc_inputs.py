"""Controlled fixtures and explicit compatibility with the pinned OpenDC reader."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import time

import pyarrow as pa
import pyarrow.parquet as pq

from forecast_trace import canonical, parquet_tasks

VERSION = "master-7db7e1a2331fd"
COMMIT = "7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad"
SOURCE_ARCHIVE_SHA256 = "df798dae10c0ee3b1911fb01b0dbd25f06f5adb6e8495826dc8ad8b108f4f52d"
CONTRACT = "opendc-controlled-v2"
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
            tasks.append({
                "id": task_id, "submission_time": group["submission_ms"],
                "duration": sum(fragment[0] for fragment in group["fragments"]),
                "cpu_count": 1, "cpu_capacity": float(fixture["frequency_mhz"]),
                "mem_capacity": group["memory_mib"],
                "fragments": [
                    {"id": task_id, "duration": duration, "cpu_count": 1, "cpu_usage": float(usage)}
                    for duration, usage in group["fragments"]
                ],
            })
    return tasks


def topology_for(fixture):
    """Return SDK topology JSON with synthetic hosts and explicit resource units.

    The fixed linear power curves are test inputs, not calibrated worker power.

    Args:
        fixture (dict): Host count, cores, frequency and memory for the test topology.

    Returns:
        dict: OpenDC SDK topology with synthetic hosts and a grid power source.
    """
    return {"clusters": [{"name": "synthetic", "hosts": [
        {"name": f"test-host-{index}",
         "cpu": {"coreCount": fixture["cores_per_host"], "coreSpeed": f'{fixture["frequency_mhz"]} MHz'},
         "memory": {"size": f'{fixture["memory_mib_per_host"]} MiB'},
         "cpuPowerModel": {"type": "linear", "idlePower": "100 W", "maxPower": "200 W"}}
        for index in range(fixture["host_count"])
    ], "powerSource": {"name": "grid", "maxPower": "10000 W"}}]}


def experiment_config():
    """Return one seeded SDK experiment with CPU/RAM admission and 1 s exports.

    Input references are relative placeholders resolved before execution.

    Returns:
        dict: Single-run SDK configuration with seed zero and native table exports.
    """
    return {
        "name": "controlled", "runs": 1, "initialSeed": 0,
        "topologies": [{"importFrom": "topology.json"}],
        "workloads": [{"source": {"type": "named", "name": "trace"}, "type": "trace",
                       "sampleFraction": 1.0, "scalingPolicy": "NoDelay", "deferAll": False}],
        "allocationPolicies": [{"type": "filter", "filters": [
            {"type": "compute"}, {"type": "vcpu", "allocationRatio": 1.0},
            {"type": "ram", "allocationRatio": 1.0}], "weighers": [], "subsetSize": 1}],
        "failureModels": [{"type": "none"}], "checkpointModels": [None],
        "exportModels": [{"exportInterval": "1 s", "printFrequency": None,
                          "filesToExport": ["task", "host", "service", "powerSource"]}],
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
    tasks = tasks.set_column(names.index("mem_capacity"), pa.field("mem_capacity", pa.int64(), nullable=False),
                             pa.array([value * 1000 for value in memory], type=pa.int64()))
    timestamp = pa.timestamp("ms", tz="UTC")
    tasks = tasks.set_column(names.index("submission_time"), pa.field("submission_time", timestamp, nullable=False),
                             tasks["submission_time"].cast(timestamp))
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
        "contract": CONTRACT, "status": "ready", "fixture": fixture_name,
        "initial_state": "empty_synthetic", "opendc_version": VERSION,
        "opendc_commit": COMMIT, "opendc_source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "transformations": {"submission_time": "int64 milliseconds -> timestamp[ms, UTC], no time shift",
                            "mem_capacity": "exported MiB * 1000; pinned SDK ComputeWorkloadLoader divides by 1000",
                            "fragments": "byte-preserved; reader ignores extra cpu_count column"},
        "python_version": platform.python_version(), "pyarrow_version": pa.__version__,
        "preparation_seconds": time.monotonic() - started,
        "sha256": file_hashes(directory),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def verify_inputs(directory):
    """Return the manifest after checking a ready, unmodified controlled input.

    Require the pinned source version, exact fixture and matching artifact
    hashes. Live simulation bundles are deliberately unsupported.

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
    if (manifest.get("contract") != CONTRACT or manifest.get("status") != "ready"
            or manifest.get("fixture") not in ("controlled", "memory")
            or manifest.get("initial_state") != "empty_synthetic"):
        raise ValueError("expected a ready controlled experiment, not a live simulation bundle")
    if (manifest.get("opendc_commit") != COMMIT
            or manifest.get("opendc_source_archive_sha256") != SOURCE_ARCHIVE_SHA256):
        raise ValueError("controlled input version differs from the pinned runner")
    if file_hashes(directory, exclude=("manifest.json",)) != manifest.get("sha256"):
        raise ValueError("controlled input hash mismatch")
    fixture = json.loads((directory / "fixture.json").read_text())
    expected = json.loads((FIXTURE_ROOT / f'{manifest["fixture"]}.json').read_text())
    if fixture != expected:
        raise ValueError("controlled fixture was modified")
    return manifest
