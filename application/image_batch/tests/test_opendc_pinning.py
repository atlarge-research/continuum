"""FNS initialization preserves assignments, admission and complete modeled drain work."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import pyarrow.parquet as pq
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Test discovery supplies the shared frozen-observation fixtures.
# pylint: disable=wrong-import-position
from opendc_inputs import file_hashes, verify_inputs
from opendc_pinning import initial_assignments
from opendc_scenarios import prepare_suite, _write_case
from opendc_run import execute
from test_opendc_scenarios import configuration, make_forecast, observer_rows, worker

# pylint: enable=wrong-import-position


class PinnedInputTests(unittest.TestCase):
    """Reject native precondition violations before invoking the upstream engine."""

    def test_pinned_native_order_restores_only_executable_assignments(self):
        """Reorder native rows without changing source profiles or allocating exhausted work."""
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            before = file_hashes(forecast)
            suite = prepare_suite(
                forecast, observer, configuration(), root / "suite", "pinned-trace"
            )
            self.assertEqual(
                {entry["candidate"] for entry in suite["experiments"]}, {"unchanged", "scale-up"}
            )
            self.assertEqual(
                suite["unavailable_candidates"],
                [{"candidate": "scale-down", "reason": "selected_worker_has_exhausted_work"}],
            )
            for entry in suite["experiments"]:
                path = root / "suite" / entry["input_dir"]
                self.assertEqual(verify_inputs(path)["contract"], "opendc-fns-v1")
                case = json.loads((path / "case.json").read_text())
                native = pq.read_table(path / "trace/tasks.parquet").to_pylist()
                by_id = {item["task"]["id"]: item for item in case["tasks"]}
                self.assertEqual([row["host"] for row in native[:2]], ["worker-a", "worker-b"])
                self.assertTrue(all(row["host"] is None for row in native[2:]))
                for row in native[:2]:
                    self.assertEqual(row["host"], by_id[row["id"]]["metadata"]["node_name"])
                self.assertFalse(case["initialization"]["startup_delay_restored"])
                self.assertFalse(case["initialization"]["exhausted_occupancy_restored"])
                self.assertEqual(len(case["model_exhausted_jobs"]), 1)
                self.assertFalse(
                    {r["id"] for r in native} & {r["task_id"] for r in case["model_exhausted_jobs"]}
                )
            self.assertEqual(file_hashes(forecast), before)

    def test_cordon_keeps_removed_worker_and_all_its_executable_work(self):
        """A complete modeled drain neither omits nor migrates the selected worker's tasks."""
        rows = observer_rows()
        for state in rows["cluster-state.jsonl"]:
            state["jobs"]["active"] = [
                job for job in state["jobs"]["active"] if job["kubernetes_job_uid"] != "exhausted"
            ]
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ), mock.patch("test_opendc_scenarios.observer_rows", return_value=rows):
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            suite = prepare_suite(
                forecast, observer, configuration(), root / "suite", "pinned-trace"
            )
            down = next(
                entry for entry in suite["experiments"] if entry["candidate"] == "scale-down"
            )
            path = root / "suite" / down["input_dir"]
            case = json.loads((path / "case.json").read_text())
            experiment = json.loads((path / "experiment.json").read_text())
            self.assertEqual(case["scope"], "complete")
            self.assertEqual(case["omitted_tasks"], [])
            self.assertEqual({w["node_name"] for w in case["workers"]}, {"worker-a", "worker-b"})
            self.assertEqual(experiment["cordonHosts"], [["worker-a"]])
            self.assertTrue(
                any(r["metadata"].get("node_name") == "worker-a" for r in case["tasks"])
            )
            verify_inputs(path)

    def test_pinning_requires_named_host_memory_even_when_another_host_has_room(self):
        """Upstream's pinned-host override must never bypass our host-specific admission."""
        rows = observer_rows([worker("worker-a", 4, 256), worker("worker-b", 8, 16384)])
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ), mock.patch("test_opendc_scenarios.observer_rows", return_value=rows):
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            with self.assertRaisesRegex(ValueError, "initial.*capacity"):
                prepare_suite(forecast, observer, configuration(), root / "suite", "pinned-trace")

    def test_initial_cpu_capacity_is_aggregate_not_per_task(self):
        """Two individually fitting pins cannot both reserve the same single modeled core."""
        case = {
            "workers": [{"node_name": "a", "modeled_cores": 1, "memory_mib": 1024}],
            "candidate": "unchanged",
            "tasks": [
                {
                    "task": {
                        "id": task_id,
                        "submission_time": 0,
                        "cpu_count": 1,
                        "mem_capacity": 256,
                    },
                    "metadata": {
                        "preserved_assignment": "a",
                        "cohort": "backlog",
                        "phase": "running",
                    },
                }
                for task_id in range(2)
            ],
        }
        with self.assertRaisesRegex(ValueError, "initial pinned capacity"):
            initial_assignments(case)

    def test_future_work_must_fit_a_worker_remaining_after_cordon(self):
        """A future cannot use the large cordoned host to pass admission checks."""
        case = {
            "workers": [
                {"node_name": "a", "modeled_cores": 1, "memory_mib": 1024},
                {"node_name": "b", "modeled_cores": 1, "memory_mib": 256},
            ],
            "candidate": "scale-down",
            "selected_worker": "a",
            "omitted_tasks": [],
            "model_exhausted_jobs": [],
            "tasks": [
                {
                    "task": {"id": 1, "submission_time": 1000, "cpu_count": 1, "mem_capacity": 512},
                    "metadata": {"cohort": "future"},
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "remaining.*capacity"):
            initial_assignments(case)

    def test_rehashed_placement_and_order_tampering_are_rejected(self):
        """Artifact hashes cannot substitute for the required native assignment semantics."""
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            suite = prepare_suite(
                forecast, observer, configuration(), root / "suite", "pinned-trace"
            )
            path = root / "suite" / suite["experiments"][0]["input_dir"]
            table = pq.read_table(path / "trace/tasks.parquet")
            table = table.take(pa.array(list(reversed(range(table.num_rows)))))
            pq.write_table(table, path / "trace/tasks.parquet")
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["sha256"] = file_hashes(path, exclude=("manifest.json",))
            (path / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "(initial host|adapted trace)"):
                verify_inputs(path)

    def test_empty_pinned_case_remains_analytical_without_invented_tasks(self):
        """An empty cohort has no native process, including when an empty worker is cordoned."""
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            root = Path(temporary)
            workers = [
                {
                    "node_name": name,
                    "configured_cores": 2,
                    "modeled_cores": 1,
                    "memory_mib": 512,
                    "frequency_mhz": 2400,
                    "idle_power_w": 100,
                    "max_power_w": 200,
                }
                for name in ("a", "b")
            ]
            _write_case(
                root / "inputs",
                "scale-down",
                0,
                workers,
                [],
                [],
                [],
                [],
                {"cutoff_ms": 100000, "horizon_ms": 10000},
                "pinned-trace",
                "a",
                "synthetic",
            )
            self.assertEqual(execute(root / "inputs", root / "run", runner="/must-not-launch"), 0)
            result = json.loads((root / "run/execution.json").read_text())
            self.assertFalse(result["process"]["launched"])
            self.assertEqual(result["validation"]["tasks"], [])


if __name__ == "__main__":
    unittest.main()
