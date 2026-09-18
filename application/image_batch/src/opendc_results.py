"""Validate controlled OpenDC output against independently specified behavior."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pyarrow.parquet as pq

from forecast_trace import canonical
from opendc_inputs import fixture_tasks


def _require(condition, message):
    """Raise ValueError with a diagnostic when an output requirement is unmet.

    Args:
        condition (bool): Whether the output requirement is satisfied.
        message (str): Diagnostic to include if the requirement fails.

    Raises:
        ValueError: The condition is false.
    """
    if not condition:
        raise ValueError(message)


def _near(actual, expected, tolerance, description):
    """Require a present numeric value within the inclusive absolute tolerance.

    Args:
        actual (int, float or None): Observed value to check.
        expected (int or float): Required value in the same units.
        tolerance (int or float): Maximum allowed absolute difference.
        description (str): Field or behavior named in a failure diagnostic.

    Raises:
        ValueError: The observed value is missing or outside tolerance.
    """
    _require(actual is not None and abs(actual - expected) <= tolerance,
             f"{description}: expected {expected} +/- {tolerance}, got {actual}")


def _read_table(path):
    """Return rows from a nonempty Parquet file or raise a diagnostic ValueError.

    Args:
        path (Path): Required native Parquet output file.

    Returns:
        list[dict]: Nonempty table rows as native Python values.

    Raises:
        ValueError: The file cannot be read as Parquet or contains no rows.
    """
    try:
        table = pq.ParquetFile(path).read()
    except (OSError, ValueError) as exc:
        raise ValueError(f"unreadable simulator output {path.name}: {exc}") from exc
    _require(table.num_rows > 0, f"empty simulator output: {path.name}")
    return table.to_pylist()


def _json_values(value):
    """Recursively encode nonfinite floats for deterministic JSON comparison.

    Args:
        value (object): Scalar, list or dictionary from native table rows.

    Returns:
        object: JSON-compatible values with explicit markers for nonfinite floats.
    """
    # Some unused upstream columns contain NaN (e.g. no GPU); preserve that fact.
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_values(item) for item in value]
    return value


def _check_tasks(rows, fixture):
    """Validate task lifecycle and fragment samples; return completion summaries.

    Match identities and memory values to the fixture, check execution and
    queue timing with its millisecond tolerance, and check demand/supply away
    from fragment boundaries. These expectations apply only to built-in fixtures.

    Args:
        rows (list[dict]): Native task telemetry and completion records.
        fixture (dict): Built-in task profiles and expected timing behavior.

    Returns:
        list[dict]: One completion summary per expected task, in fixture order.

    Raises:
        ValueError: Task identities, resources, lifecycle or fragment demand do not match.
    """
    expected_tasks = fixture_tasks(fixture)
    _require({row["task_id"] for row in rows} == {task["id"] for task in expected_tasks},
             "simulator task identities differ from the controlled input")
    tolerance = fixture["expected"]["scheduler_tolerance_ms"]
    completed = []
    for task in expected_tasks:
        samples = [row for row in rows if row["task_id"] == task["id"]]
        terminal = [row for row in samples if row["task_state"] == "COMPLETED"]
        _require(len(terminal) == 1, f'task {task["id"]} needs exactly one completed record')
        record = terminal[0]
        _require(bool(record["host_name"]), f'task {task["id"]} has no placement')
        _require(record["mem_capacity"] == task["mem_capacity"], f'task {task["id"]} memory conversion failed')
        _require(record["cpu_count"] == 1, "unexpected task CPU count")
        _near(record["submission_time"], task["submission_time"], 0, "submission time")
        _near(record["finish_time"] - record["schedule_time"], task["duration"], tolerance, "execution duration")
        expected_start = fixture["expected"]["last_start_ms"] if task["id"] == fixture["expected"]["last_task_id"] else 0
        _near(record["schedule_time"], expected_start, tolerance, "schedule time")
        offset = 0
        for fragment in task["fragments"]:
            # Avoid interval edges; one-second exports can straddle a transition.
            middle = [row for row in samples if
                      offset + 1000 < row["timestamp"] - record["schedule_time"] < offset + fragment["duration"] - 1000]
            _require(bool(middle), f'task {task["id"]} fragment has no interior telemetry')
            for row in middle:
                _near(row["cpu_demand"], fragment["cpu_usage"], 0.01, "fragment CPU demand")
                _near(row["cpu_usage"], fragment["cpu_usage"], 0.01, "fragment CPU supply")
            offset += fragment["duration"]
        completed.append({key: record[key] for key in
                          ("task_id", "submission_time", "schedule_time", "finish_time", "host_name", "mem_capacity")})
    last = completed[-1]
    _require(last["schedule_time"] >= max(task["finish_time"] for task in completed[:-1]),
             "queued task started before occupied capacity was released")
    _near(last["finish_time"], fixture["expected"]["last_finish_ms"], tolerance, "final completion")
    return completed


def validate_results(directory, fixture):
    """Validate the four native tables against a controlled experiment's oracle.

    Raw energy is checked for validity, not interpreted as a scoring window.

    Args:
        directory (str or Path): OpenDC output root above controlled/raw-output.
        fixture (dict): Built-in task, topology and expected-behavior definition.

    Returns:
        dict: Passed status, task summaries, table row counts and a semantic
            digest of all native records for repeatability comparisons.

    Raises:
        ValueError: Required output is unreadable, empty, incomplete or fails
            the fixture's lifecycle, capacity, queueing or resource checks.
    """
    directory = Path(directory)
    raw = directory / "controlled" / "raw-output" / "0" / "seed=0"
    tables = {name: _read_table(raw / f"{name}.parquet") for name in ("task", "host", "service", "powerSource")}
    try:
        completed = _check_tasks(tables["task"], fixture)
        service = max(tables["service"], key=lambda row: row["timestamp"])
        expected = fixture["expected"]
        _require(service["tasks_completed"] == expected["task_count"], "service completion count mismatch")
        _require(service["tasks_total"] == expected["task_count"], "service total count mismatch")
        _require(service["tasks_pending"] == service["tasks_active"] == service["tasks_terminated"] == 0,
                 "service still has unfinished or failed tasks")
        _require(max(row["tasks_active"] for row in tables["service"]) == expected["concurrent_tasks"],
                 "unexpected maximum task concurrency")
        _require(any(row["tasks_pending"] > 0 for row in tables["service"]), "expected queued work was not observed")
        host_names = {f"test-host-{index}" for index in range(fixture["host_count"])}
        _require({row["host_name"] for row in tables["host"]} == host_names, "host identity mismatch")
        for row in tables["host"]:
            _require(row["core_count"] == fixture["cores_per_host"], "host CPU capacity mismatch")
            _require(row["mem_capacity"] == fixture["memory_mib_per_host"], "host memory capacity mismatch")
            _require(0 <= row["tasks_running"] <= fixture["cores_per_host"], "host overcommitted")
            _require(math.isfinite(row["energy_usage"]) and row["energy_usage"] >= 0, "invalid raw host energy")
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError(f"incomplete simulator output: {exc}") from exc
    semantic = {name: sorted((_json_values(row) for row in rows), key=canonical) for name, rows in tables.items()}
    return {"status": "passed", "task_count": len(completed), "tasks": completed,
            "table_rows": {name: len(rows) for name, rows in tables.items()},
            "semantic_sha256": hashlib.sha256(canonical(semantic)).hexdigest(),
            "interpretation": "controlled execution oracle; raw energy is not a scoring window or calibrated prediction"}
