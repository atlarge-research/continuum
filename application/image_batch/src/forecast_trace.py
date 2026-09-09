"""Bounded observer evidence and explicit OpenDC Parquet serialization."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

STREAMS = (
    "workload.jsonl",
    "cluster-state.jsonl",
    "observer-events.jsonl",
    "resource-snapshots.jsonl",
)


def canonical(value):
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        + b"\n"
    )


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path, value):
    Path(path).write_bytes(canonical(value))


def milliseconds(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(
        timespec="milliseconds"
    )


def observed_milliseconds(value):
    """Round evidence availability upward, never across a cutoff into the past."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return milliseconds(value) + int(dt.microsecond % 1000 != 0)


def _invalid_constant(value):
    raise ValueError(f"non-finite JSON value: {value}")


def bounded_read(directory, boundaries=None):
    """Freeze all sizes before reading; an unfinished trailing line is ignored.

    A saved manifest reopens exactly the same prefixes even after later appends.
    The prefix hash includes any ignored trailing bytes.
    """
    directory = Path(directory)
    handles = {}
    manifest = {}
    rows = {}
    try:
        for name in STREAMS:
            handles[name] = (directory / name).open("rb")
        sizes = {
            name: os.fstat(handle.fileno()).st_size for name, handle in handles.items()
        }
        for name, handle in handles.items():
            limit = boundaries[name]["bytes"] if boundaries else sizes[name]
            if not isinstance(limit, int) or limit < 0 or limit > sizes[name]:
                raise ValueError(f"invalid/truncated input boundary: {name}")
            raw = handle.read(limit)
            if len(raw) != limit:
                raise ValueError(f"input shrank while reading: {name}")
            checksum = hashlib.sha256(raw).hexdigest()
            if boundaries and checksum != boundaries[name]["sha256"]:
                raise ValueError(f"input prefix changed: {name}")
            complete = raw[: raw.rfind(b"\n") + 1]
            manifest[name] = {
                "bytes": limit,
                "complete_bytes": len(complete),
                "sha256": checksum,
            }
            rows[name] = []
            for number, line in enumerate(complete.splitlines(), 1):
                try:
                    record = json.loads(line, parse_constant=_invalid_constant)
                    if (
                        not isinstance(record, dict)
                        or record.get("schema_version") != 1
                    ):
                        raise ValueError("expected schema_version 1 object")
                    rows[name].append(record)
                except (ValueError, UnicodeError) as exc:
                    raise ValueError(f"{name}:{number}: {exc}") from exc
    finally:
        for handle in handles.values():
            handle.close()
    return rows, manifest


@dataclass
class Trace:
    cutoff: int
    arrivals: dict
    completed: list
    states: list
    capture_failures: list
    state: dict | None


def _time(record):
    if "timestamp_unix_ns" in record:
        return (record["timestamp_unix_ns"] + 999_999) // 1_000_000
    return observed_milliseconds(record["timestamp"])


def validate_task(task):
    """Reject malformed physical values before Arrow can coerce them."""
    for key, minimum, maximum in (
        ("duration", 0, 2**63 - 1),
        ("cpu_count", 1, 2**31 - 1),
        ("mem_capacity", 1, 2**63 - 1),
    ):
        value = task[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"invalid Task {key}")
    capacity = task["cpu_capacity"]
    if (
        not isinstance(capacity, (int, float))
        or not math.isfinite(capacity)
        or capacity <= 0
    ):
        raise ValueError("invalid Task cpu_capacity")
    milliseconds(task["submission_time"])
    fragments = task["fragments"]
    for fragment in fragments:
        if type(fragment["duration"]) is not int or fragment["duration"] <= 0:
            raise ValueError("invalid Fragment duration")
        if fragment["cpu_count"] != task["cpu_count"]:
            raise ValueError("Fragment CPU count differs from Task")
        usage = fragment["cpu_usage"]
        if (
            not isinstance(usage, (int, float))
            or not math.isfinite(usage)
            or not 0 <= usage <= capacity
        ):
            raise ValueError("invalid Fragment cpu_usage")
    if (
        fragments
        and sum(fragment["duration"] for fragment in fragments) != task["duration"]
    ):
        raise ValueError("Fragments do not cover Task duration")


def read_trace(rows, run_id, cutoff):
    arrivals = {}
    emissions = {}
    failures = []

    def arrival(uid, run, created, seen):
        if run != run_id or seen > cutoff:
            return
        created = milliseconds(created)
        if not uid or created > seen:
            raise ValueError("invalid Job identity or creation after observation")
        previous = arrivals.get(uid)
        if previous and previous["creation_ms"] != created:
            raise ValueError(f"conflicting arrival: {uid}")
        arrivals[uid] = {
            "creation_ms": created,
            "first_seen_ms": min(seen, previous["first_seen_ms"] if previous else seen),
        }

    for row in rows["observer-events.jsonl"]:
        seen = _time(row)
        if seen > cutoff:
            continue
        details = row.get("details", {})
        kind = row["event_type"]
        if kind == "task.emitted":
            uid = details["kubernetes_job_uid"]
            emissions[uid] = min(seen, emissions.get(uid, seen))
        elif kind == "job.observed":
            arrival(
                details["kubernetes_job_uid"],
                details["workload_run_id"],
                details["creation_time"],
                seen,
            )
        elif kind in (
            "cluster_state.capture_failed",
            "observer.sample_failed",
            "observer.fatal",
        ):
            failures.append(seen)

    states_by_time = {}
    for row in rows["cluster-state.jsonl"]:
        seen = _time(row)
        if seen > cutoff:
            continue
        state = copy.deepcopy(row)
        for group in ("queued", "active"):
            kept = []
            for job in state["jobs"][group]:
                arrival(
                    job["kubernetes_job_uid"],
                    job["workload_run_id"],
                    job["creation_time"],
                    seen,
                )
                if job["workload_run_id"] == run_id and job.get("pod_phase") not in (
                    "Succeeded",
                    "Failed",
                ):
                    kept.append(job)
            state["jobs"][group] = kept
            state["counts"][f"{group}_jobs"] = len(kept)
        for worker in state["workers"]:
            for key in (
                "node_name",
                "ready",
                "schedulable",
                "allocatable_cpu_count",
                "allocatable_memory_mb",
            ):
                if key not in worker:
                    raise ValueError(f"incomplete worker state: {key}")
        if seen in states_by_time and states_by_time[seen] != state:
            raise ValueError("conflicting cluster snapshots")
        states_by_time[seen] = state

    completed = {}
    for row in rows["workload.jsonl"]:
        source = row["source"]
        uid = source["kubernetes_job_uid"]
        if source["workload_run_id"] != run_id or uid not in emissions:
            continue
        arrival(uid, run_id, row["task"]["submission_time"], emissions[uid])
        if observed_milliseconds(source["completion_time"]) > cutoff:
            continue
        if source["terminal_status"] != "Complete":
            raise ValueError("unsuccessful workload Task")
        validate_task(row["task"])
        task = copy.deepcopy(row)
        # Observer-local task IDs are not a durable identity.
        task["task"]["id"] = 0
        for fragment in task["task"]["fragments"]:
            fragment["id"] = 0
        if uid in completed and completed[uid] != task:
            raise ValueError(f"conflicting completed Job: {uid}")
        completed[uid] = task
    states = sorted(states_by_time.items())
    ordered = sorted(
        completed.values(),
        key=lambda r: (
            milliseconds(r["task"]["submission_time"]),
            r["source"]["kubernetes_job_uid"],
        ),
    )
    return Trace(
        cutoff, arrivals, ordered, states, failures, states[-1][1] if states else None
    )


def training_bins(trace, origin, bin_ms, gap_ms):
    """Only fully covered bins count; gaps are never imputed as zero demand."""
    intervals = []
    for (left, _), (right, _) in zip(trace.states, trace.states[1:]):
        if right - left <= gap_ms and not any(
            left <= failed <= right for failed in trace.capture_failures
        ):
            if intervals and intervals[-1][1] == left:
                intervals[-1][1] = right
            else:
                intervals.append([left, right])
    total = max(0, (trace.cutoff - origin) // bin_ms)
    counts = [0] * total
    for value in trace.arrivals.values():
        index = (value["creation_ms"] - origin) // bin_ms
        if 0 <= index < total:
            counts[index] += 1
    result = []
    cursor = 0
    for index in range(total):
        start = origin + index * bin_ms
        end = start + bin_ms
        while cursor < len(intervals) and intervals[cursor][1] < end:
            cursor += 1
        covered = (
            cursor < len(intervals)
            and intervals[cursor][0] <= start
            and end <= intervals[cursor][1]
        )
        result.append({"start_ms": start, "count": counts[index], "eligible": covered})
    return result


def parquet_tasks(tasks, directory):
    """Use the same required physical types for populated and empty tables."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    task_schema = pa.schema(
        [
            (n, t, False)
            for n, t in (
                ("id", pa.int32()),
                ("submission_time", pa.int64()),
                ("duration", pa.int64()),
                ("cpu_count", pa.int32()),
                ("cpu_capacity", pa.float64()),
                ("mem_capacity", pa.int64()),
            )
        ]
    )
    fragment_schema = pa.schema(
        [
            (n, t, False)
            for n, t in (
                ("id", pa.int32()),
                ("duration", pa.int64()),
                ("cpu_count", pa.int32()),
                ("cpu_usage", pa.float64()),
            )
        ]
    )
    task_rows, fragment_rows = [], []
    for task in tasks:
        row = {key: task[key] for key in task_schema.names}
        if isinstance(row["submission_time"], str):
            row["submission_time"] = milliseconds(row["submission_time"])
        task_rows.append(row)
        fragment_rows.extend(task["fragments"])
    for name, data, schema in (
        ("tasks", task_rows, task_schema),
        ("fragments", fragment_rows, fragment_schema),
    ):
        pq.write_table(
            pa.Table.from_pylist(data, schema=schema),
            directory / f"{name}.parquet",
            compression="NONE",
            version="2.6",
            use_dictionary=False,
        )
