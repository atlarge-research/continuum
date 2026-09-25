"""Validate controlled OpenDC output against independently specified behavior."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pyarrow.parquet as pq

from forecast_trace import canonical
from opendc_inputs import fixture_tasks
from opendc_pinning import PINNED_MODE, initial_assignments, cordoned_worker
from opendc_energy import datacenter_series, energy_tolerance


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
    _require(
        actual is not None and abs(actual - expected) <= tolerance,
        f"{description}: expected {expected} +/- {tolerance}, got {actual}",
    )


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
    _require(
        {row["task_id"] for row in rows} == {task["id"] for task in expected_tasks},
        "simulator task identities differ from the controlled input",
    )
    tolerance = fixture["expected"]["scheduler_tolerance_ms"]
    completed = []
    for task in expected_tasks:
        samples = [row for row in rows if row["task_id"] == task["id"]]
        terminal = [row for row in samples if row["task_state"] == "COMPLETED"]
        _require(len(terminal) == 1, f'task {task["id"]} needs exactly one completed record')
        record = terminal[0]
        _require(bool(record["host_name"]), f'task {task["id"]} has no placement')
        _require(
            record["mem_capacity"] == task["mem_capacity"],
            f'task {task["id"]} memory conversion failed',
        )
        _require(record["cpu_count"] == 1, "unexpected task CPU count")
        _near(record["submission_time"], task["submission_time"], 0, "submission time")
        _near(
            record["finish_time"] - record["schedule_time"],
            task["duration"],
            tolerance,
            "execution duration",
        )
        expected_start = (
            fixture["expected"]["last_start_ms"]
            if task["id"] == fixture["expected"]["last_task_id"]
            else 0
        )
        _near(record["schedule_time"], expected_start, tolerance, "schedule time")
        offset = 0
        for fragment in task["fragments"]:
            # Avoid interval edges; one-second exports can straddle a transition.
            middle = [
                row
                for row in samples
                if offset + 1000
                < row["timestamp"] - record["schedule_time"]
                < offset + fragment["duration"] - 1000
            ]
            _require(bool(middle), f'task {task["id"]} fragment has no interior telemetry')
            for row in middle:
                _near(row["cpu_demand"], fragment["cpu_usage"], 0.01, "fragment CPU demand")
                _near(row["cpu_usage"], fragment["cpu_usage"], 0.01, "fragment CPU supply")
            offset += fragment["duration"]
        completed.append(
            {
                key: record[key]
                for key in (
                    "task_id",
                    "submission_time",
                    "schedule_time",
                    "finish_time",
                    "host_name",
                    "mem_capacity",
                )
            }
        )
    last = completed[-1]
    _require(
        last["schedule_time"] >= max(task["finish_time"] for task in completed[:-1]),
        "queued task started before occupied capacity was released",
    )
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
    tables = {
        name: _read_table(raw / f"{name}.parquet")
        for name in ("task", "host", "service", "powerSource")
    }
    try:
        completed = _check_tasks(tables["task"], fixture)
        service = max(reversed(tables["service"]), key=lambda row: row["timestamp"])
        expected = fixture["expected"]
        _require(
            service["tasks_completed"] == expected["task_count"],
            "service completion count mismatch",
        )
        _require(service["tasks_total"] == expected["task_count"], "service total count mismatch")
        _require(
            service["tasks_pending"] == service["tasks_active"] == service["tasks_terminated"] == 0,
            "service still has unfinished or failed tasks",
        )
        _require(
            max(row["tasks_active"] for row in tables["service"]) == expected["concurrent_tasks"],
            "unexpected maximum task concurrency",
        )
        _require(
            any(row["tasks_pending"] > 0 for row in tables["service"]),
            "expected queued work was not observed",
        )
        host_names = {f"test-host-{index}" for index in range(fixture["host_count"])}
        _require(
            {row["host_name"] for row in tables["host"]} == host_names, "host identity mismatch"
        )
        for row in tables["host"]:
            _require(row["core_count"] == fixture["cores_per_host"], "host CPU capacity mismatch")
            _require(
                row["mem_capacity"] == fixture["memory_mib_per_host"],
                "host memory capacity mismatch",
            )
            _require(0 <= row["tasks_running"] <= fixture["cores_per_host"], "host overcommitted")
            _require(
                math.isfinite(row["energy_usage"]) and row["energy_usage"] >= 0,
                "invalid raw host energy",
            )
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError(f"incomplete simulator output: {exc}") from exc
    semantic = {
        name: sorted((_json_values(row) for row in rows), key=canonical)
        for name, rows in tables.items()
    }
    return {
        "status": "passed",
        "task_count": len(completed),
        "tasks": completed,
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "semantic_sha256": hashlib.sha256(canonical(semantic)).hexdigest(),
        "interpretation": (
            "controlled execution oracle; raw energy is not a scoring window "
            "or calibrated prediction"
        ),
    }


def validate_provisional_results(directory, case):
    """Validate represented-task lifecycle, admission and optional native pinning/cordon.

    Native lifecycle records, rather than process exit or telemetry snapshots,
    establish completed identities and CPU/memory admission. Provisional cases
    do not enforce placement; pinned cases additionally require the observed
    hosts at zero, no new cordon admissions and complete datacenter energy.
    Explicit occupancy estimates, when present, remain modeled assumptions. OpenDC starts
    its clock at the earliest submission; returned lifecycle times restore the
    cutoff-relative origin, while native submission times already use that origin.

    Args:
        directory (str or Path): Simulator output root.
        case (dict): Prepared case with included tasks, workers and explicit scope.

    Returns:
        dict: Validated completion records, scope, counts and semantic digest;
            pinned cases also expose cordon and aggregate-energy diagnostics.

    Raises:
        ValueError: Output is incomplete, nonfinite, inconsistent or overcommitted.
    """
    raw = Path(directory) / "controlled/raw-output/0/seed=0"
    tables = {}
    pinned = case.get("initialization_mode") == PINNED_MODE
    assignments = initial_assignments(case) if pinned else {}
    removed = cordoned_worker(case) if pinned else None
    try:
        for name in ("task", "host", "service", "powerSource"):
            table = pq.ParquetFile(raw / f"{name}.parquet").read()
            tables[name] = table.to_pylist()
        if pinned:
            tables["dataCenter"] = _read_table(raw / "dataCenter.parquet")
        expected = {item["task"]["id"]: item["task"] for item in case["tasks"]}
        hosts = {worker["node_name"]: worker for worker in case["workers"]}
        _require(
            {row["task_id"] for row in tables["task"]} == set(expected),
            "simulator task identities differ from included tasks",
        )
        origin = min(task["submission_time"] for task in expected.values())
        completed = []
        for task_id, task in expected.items():
            terminal = [
                row
                for row in tables["task"]
                if row["task_id"] == task_id and row["task_state"] == "COMPLETED"
            ]
            _require(len(terminal) == 1, f"task {task_id} needs exactly one completion")
            row = dict(terminal[0])
            if "timestamp_absolute" in row:
                _require(
                    row["timestamp_absolute"] - row["timestamp"] == origin,
                    "native time origin differs from earliest submission",
                )
            row["schedule_time"] += origin
            row["finish_time"] += origin
            _require(row["host_name"] in hosts, "completion references unknown host")
            _require(row["submission_time"] == task["submission_time"], "submission time differs")
            _require(
                all(
                    math.isfinite(row[key])
                    for key in ("schedule_time", "finish_time", "submission_time")
                ),
                "nonfinite task timing",
            )
            _require(
                row["finish_time"] >= row["schedule_time"] >= row["submission_time"],
                "invalid task lifecycle ordering",
            )
            _require(
                row["cpu_count"] == task["cpu_count"]
                and row["mem_capacity"] == task["mem_capacity"],
                "task requests differ",
            )
            _near(
                row["finish_time"] - row["schedule_time"],
                task["duration"],
                2,
                "remaining execution duration",
            )
            if task_id in assignments:
                _require(row["host_name"] == assignments[task_id], "pinned task changed host")
                _near(row["schedule_time"], 0, 2, "pinned initial start")
                _require(
                    all(
                        sample["host_name"] == assignments[task_id]
                        for sample in tables["task"]
                        if sample["task_id"] == task_id
                        and sample["task_state"] in ("RUNNING", "COMPLETED")
                    ),
                    "pinned task changed host during execution",
                )
            elif removed is not None:
                _require(
                    all(
                        sample["host_name"] != removed
                        for sample in tables["task"]
                        if sample["task_id"] == task_id
                        and sample["task_state"] in ("RUNNING", "COMPLETED")
                    ),
                    "cordoned host admitted unassigned work",
                )
            completed.append(
                {
                    key: row[key]
                    for key in (
                        "task_id",
                        "submission_time",
                        "schedule_time",
                        "finish_time",
                        "host_name",
                        "mem_capacity",
                        "cpu_count",
                    )
                }
            )
        for name, host in hosts.items():
            events = []
            for row in completed:
                if row["host_name"] == name:
                    events.extend(
                        [
                            (row["schedule_time"], 1, row["cpu_count"], row["mem_capacity"]),
                            (row["finish_time"], -1, -row["cpu_count"], -row["mem_capacity"]),
                        ]
                    )
            cpu = memory = 0
            for _, _, cpu_delta, memory_delta in sorted(events):
                cpu += cpu_delta
                memory += memory_delta
                _require(
                    0 <= cpu <= host["modeled_cores"] and 0 <= memory <= host["memory_mib"],
                    "worker CPU/memory admission exceeded",
                )
        _require(
            bool(tables["service"]) and bool(tables["host"]) and bool(tables["powerSource"]),
            "missing native resource records",
        )
        service = max(reversed(tables["service"]), key=lambda row: row["timestamp"])
        _require(
            service["tasks_total"] == service["tasks_completed"] == len(expected)
            and service["tasks_pending"]
            == service["tasks_active"]
            == service["tasks_terminated"]
            == 0,
            "service totals disagree with completed work",
        )
        empty_removed = removed is not None and removed not in assignments.values()
        expected_hosts = set(hosts) - ({removed} if empty_removed else set())
        _require(
            {row["host_name"] for row in tables["host"]} == expected_hosts, "host identity mismatch"
        )
        for row in tables["host"]:
            host = hosts[row["host_name"]]
            _require(
                row["core_count"] == host["modeled_cores"]
                and row["mem_capacity"] == host["memory_mib"],
                "host resources differ",
            )
            _require(
                math.isfinite(row["energy_usage"]) and row["energy_usage"] >= 0,
                "invalid worker energy",
            )
        end = max(row["finish_time"] for row in completed)
        for name in expected_hosts:
            samples = [row for row in tables["host"] if row["host_name"] == name]
            _require(
                all(math.isfinite(row["timestamp"]) and row["timestamp"] >= 0 for row in samples)
                and (name == removed or max(row["timestamp"] for row in samples) + origin >= end),
                "native host energy coverage ends before included completion",
            )
        energy = None
        cordon = None
        if pinned:
            _require(
                service["timestamp"] + origin >= end,
                "native service coverage ends before completion",
            )
            _require(
                service["hosts_up"] == len(hosts) - int(removed is not None),
                "cordoned host did not close or remaining host is unavailable",
            )
            series = datacenter_series(case, tables["dataCenter"], origin)["modeled-worker-pool"]
            _require(
                series["native_last_timestamp_ms"] >= end,
                "datacenter energy coverage ends before completion",
            )
            recorded = [
                max(rows, key=lambda row: row["timestamp"])["energy_usage"]
                for name in expected_hosts
                if (rows := [row for row in tables["host"] if row["host_name"] == name])
            ]
            native_total = max(tables["dataCenter"], key=lambda row: row["timestamp"])[
                "energy_usage"
            ]
            _require(
                native_total + energy_tolerance(native_total, *recorded) >= sum(recorded),
                "datacenter total omits recorded host energy",
            )
            energy = {
                "source": "native datacenter cumulative energy, including drained hosts",
                "final_datacenter_joules": series["samples"][-1][1],
                "last_timestamp_ms": series["native_last_timestamp_ms"],
                "accuracy": "uncalibrated worker power model",
            }
            if removed is not None:
                cordon = {
                    "host": removed,
                    "drain_finish_ms": max(
                        (r["finish_time"] for r in completed if r["host_name"] == removed),
                        default=0,
                    ),
                    "last_host_sample_ms": max(
                        (
                            r["timestamp"] + origin
                            for r in tables["host"]
                            if r["host_name"] == removed
                        ),
                        default=None,
                    ),
                    "new_admissions": 0,
                    "semantics": (
                        "native close after assigned executable work; "
                        "no measured physical power claim"
                    ),
                }
                _require(
                    cordon["last_host_sample_ms"] is None
                    or cordon["last_host_sample_ms"] <= cordon["drain_finish_ms"],
                    "cordoned host continued exporting after its drain boundary",
                )
        semantic = {
            name: sorted((_json_values(row) for row in rows), key=canonical)
            for name, rows in tables.items()
        }
        return {
            "status": "passed",
            "native_time_origin_ms": origin,
            "task_count": len(completed),
            "tasks": completed,
            "scope": case["scope"],
            "initialization_mode": case["initialization_mode"],
            "table_rows": {name: len(rows) for name, rows in tables.items()},
            "semantic_sha256": hashlib.sha256(canonical(semantic)).hexdigest(),
            "interpretation": (
                "validated represented-task pinning and explicit causal occupancy estimates; "
                "no claim of measured startup/residual accuracy"
                if pinned and case.get("occupancy_model")
                else "validated represented-task pinning; startup delay and exhausted occupancy "
                "remain unmodeled"
                if pinned
                else "provisional trace replay; placement/startup occupancy not restored"
            ),
            **({"energy": energy, "cordon": cordon} if pinned else {}),
        }
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError(f"incomplete provisional simulator output: {exc}") from exc
