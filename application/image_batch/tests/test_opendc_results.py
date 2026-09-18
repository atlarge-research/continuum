"""Reject plausible-looking outputs with missing tasks or wrong scheduling."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import FIXTURE_ROOT
from opendc_results import validate_results


def memory_output(directory, early=False, missing=False):
    """Write minimal native tables for two tasks serialized by memory admission.

    Args:
        directory (Path): Root under which the native output hierarchy is created.
        early (bool): Introduce an invalid early start for the second task.
        missing (bool): Omit the second task while service totals still claim success.
    """
    raw = directory / "controlled/raw-output/0/seed=0"
    raw.mkdir(parents=True)
    tasks = [
        {"task_id": 0, "timestamp": 2000, "submission_time": 0, "schedule_time": 1,
         "finish_time": 0, "host_name": "test-host-0", "mem_capacity": 384, "cpu_count": 1,
         "cpu_demand": 2400.0, "cpu_usage": 2400.0},
        {"task_id": 0, "timestamp": 10001, "submission_time": 0, "schedule_time": 1,
         "finish_time": 10001, "host_name": "test-host-0", "mem_capacity": 384, "cpu_count": 1,
         "cpu_demand": 0.0, "cpu_usage": 0.0},
        {"task_id": 1, "timestamp": 12000, "submission_time": 1000, "schedule_time": 10002,
         "finish_time": 0, "host_name": "test-host-0", "mem_capacity": 384, "cpu_count": 1,
         "cpu_demand": 2400.0, "cpu_usage": 2400.0},
        {"task_id": 1, "timestamp": 15002, "submission_time": 1000, "schedule_time": 10002,
         "finish_time": 15002, "host_name": "test-host-0", "mem_capacity": 384, "cpu_count": 1,
         "cpu_demand": 0.0, "cpu_usage": 0.0},
    ]
    for row in tasks:
        row["task_state"] = "COMPLETED" if row["finish_time"] > 0 else "RUNNING"
    if early:
        for row in tasks[2:]:
            row["schedule_time"] = 1001
            if row["finish_time"] > 0:
                row["finish_time"] = 6001
    if missing:
        tasks = tasks[:2]
    pq.write_table(pa.Table.from_pylist(tasks), raw / "task.parquet")
    pq.write_table(pa.Table.from_pylist([
        {"timestamp": 2000, "tasks_total": 2, "tasks_active": 1, "tasks_pending": 1, "tasks_completed": 0, "tasks_terminated": 0},
        {"timestamp": 15002, "tasks_total": 2, "tasks_active": 0, "tasks_pending": 0, "tasks_completed": 2, "tasks_terminated": 0},
    ]), raw / "service.parquet")
    pq.write_table(pa.Table.from_pylist([
        {"timestamp": 2000, "host_name": "test-host-0", "core_count": 2, "mem_capacity": 512,
         "tasks_running": 1, "cpu_usage": 2400.0, "energy_usage": 150.0},
    ]), raw / "host.parquet")
    pq.write_table(pa.Table.from_pylist([{"timestamp": 2000, "power_draw": 150.0}]), raw / "powerSource.parquet")


class ResultTests(unittest.TestCase):
    """Check the output oracle against plausible but incomplete or invalid records."""

    def setUp(self):
        """Load the independent expected behavior of the built-in memory fixture."""
        self.fixture = json.loads((FIXTURE_ROOT / "memory.json").read_text())

    def test_reads_native_tables_and_checks_memory_serialization(self):
        """Accept complete serialized-task output and return a semantic comparison digest."""
        with tempfile.TemporaryDirectory() as root:
            memory_output(Path(root))
            result = validate_results(Path(root), self.fixture)
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["tasks"][-1]["schedule_time"], 10002)
            self.assertIn("semantic_sha256", result)

    def test_cpu_sufficient_but_memory_overcommit_is_rejected(self):
        """Reject early admission even though the host has a spare CPU core."""
        with tempfile.TemporaryDirectory() as root:
            memory_output(Path(root), early=True)
            with self.assertRaises(ValueError):
                validate_results(Path(root), self.fixture)

    def test_incomplete_output_is_not_success_even_when_service_reports_complete(self):
        """Require task completion evidence instead of trusting service totals alone."""
        with tempfile.TemporaryDirectory() as root:
            memory_output(Path(root), missing=True)
            with self.assertRaisesRegex(ValueError, "task"):
                validate_results(Path(root), self.fixture)

    def test_missing_or_corrupt_parquet_is_rejected(self):
        """Reject an unreadable Task table instead of returning a successful result."""
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            memory_output(directory)
            path = directory / "controlled/raw-output/0/seed=0/task.parquet"
            path.write_bytes(b"not parquet")
            with self.assertRaises(ValueError):
                validate_results(directory, self.fixture)
