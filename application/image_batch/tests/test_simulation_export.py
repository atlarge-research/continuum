"""Public forecast CLI and reproducible simulation bundle contracts."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from forecast_trace import canonical, iso
from forecast_workload import main, parquet_tasks, run_once
from test_forecast_workload import BASE, fixture, save_rows, settings


def simulation_rows():
    rows = fixture()
    worker = {
        "node_name": "worker",
        "kubernetes_node_uid": "node-uid",
        "ready": True,
        "schedulable": False,
        "allocatable_cpu_count": 4.0,
        "allocatable_memory_mb": 8192.0,
    }
    job = {
        "kubernetes_job_uid": "queued",
        "workload_run_id": "test",
        "creation_time": iso(BASE + 30000),
        "execution_start_time": None,
        "execution_state": "waiting",
        "node_name": "worker",
        "pod_phase": "Pending",
        "requested_cpu_count": 1.0,
        "requested_memory_mb": 512.0,
        "image_count": 4,
        "inference_repetitions": 128,
    }
    for index, state in enumerate(rows["cluster-state.jsonl"]):
        state["workers"] = [copy.deepcopy(worker)]
        if index >= 30:
            state["jobs"]["queued"] = [copy.deepcopy(job)]
    return rows


class SimulationExportTests(unittest.TestCase):
    def test_export_aligns_all_inputs_and_preserves_forecast_only_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_rows(root / "audit", simulation_rows())
            summary, _ = run_once(
                root / "audit", root / "out", BASE + 40750, settings(), simulation_inputs=True
            )
            self.assertEqual(summary["cutoff"], iso(BASE + 40000))
            self.assertEqual(summary["requested_cutoff"], iso(BASE + 40750))
            bundle = root / "out/simulation"
            manifest = json.loads((bundle / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "ready")
            self.assertEqual(manifest["inputs"], summary["inputs"])
            self.assertIn("simulation_input.py", manifest["implementation_sha256"])
            initial = json.loads((bundle / "initial-state.json").read_text())
            self.assertFalse(initial["workers"][0]["schedulable"])
            for i in range(4):
                tasks = pq.read_table(
                    bundle / "scenarios" / f"{i:04d}" / "tasks.parquet"
                ).to_pylist()
                self.assertEqual(tasks[0]["submission_time"], 0)
                self.assertEqual(tasks[0]["duration"], 10000)
                future = pq.read_table(
                    root / "out/scenarios" / f"{i:04d}" / "tasks.parquet"
                ).to_pylist()
                self.assertEqual(len(tasks), len(future) + 1)
                self.assertEqual(
                    [t["submission_time"] for t in tasks[1:]],
                    [t["submission_time"] - BASE - 40000 for t in future],
                )
            self.assertTrue((root / "out/history/tasks.parquet").exists())

    def test_prefix_reproduction_and_future_evidence_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = simulation_rows()
            save_rows(root / "audit", rows)
            summary, _ = run_once(
                root / "audit", root / "a", BASE + 40750, settings(), simulation_inputs=True
            )
            with (root / "audit/observer-events.jsonl").open("ab") as stream:
                stream.write(
                    canonical(
                        {
                            "schema_version": 1,
                            "timestamp": iso(BASE + 90000),
                            "event_type": "observer.fatal",
                        }
                    )
                )
            run_once(
                root / "audit",
                root / "b",
                BASE + 40750,
                settings(),
                boundaries=summary["inputs"],
                simulation_inputs=True,
            )
            for path in (root / "a").rglob("*"):
                if path.is_file():
                    self.assertEqual(
                        path.read_bytes(), (root / "b" / path.relative_to(root / "a")).read_bytes()
                    )
            # Changing valid future state cannot leak into the selected snapshot.
            rows["cluster-state.jsonl"][-1]["workers"] = [{"bad_future": True}]
            save_rows(root / "changed", rows)
            run_once(root / "changed", root / "c", BASE + 40750, settings(), simulation_inputs=True)
            for name in (
                "initial-state.json",
                "scenarios/0000/tasks.parquet",
                "scenarios/0000/fragments.parquet",
            ):
                self.assertEqual(
                    (root / "a/simulation" / name).read_bytes(),
                    (root / "c/simulation" / name).read_bytes(),
                )

    def test_stale_state_does_not_become_fresh_by_moving_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_rows(root / "audit", simulation_rows())
            summary, _ = run_once(
                root / "audit", root / "out", BASE + 90000, settings(), simulation_inputs=True
            )
            self.assertEqual(summary["simulation_inputs"]["status"], "not_ready")
            self.assertIn("state_stale", summary["simulation_inputs"]["reasons"])
            self.assertFalse((root / "out/simulation/scenarios").exists())

    def test_default_mode_has_no_simulation_output_or_cutoff_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_rows(root / "audit", simulation_rows())
            summary, _ = run_once(root / "audit", root / "out", BASE + 40750, settings())
            self.assertEqual(summary["cutoff"], iso(BASE + 40750))
            self.assertNotIn("simulation_inputs", summary)
            self.assertFalse((root / "out/simulation").exists())

    def test_failed_bundle_write_cannot_leave_a_ready_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_rows(root / "audit", simulation_rows())

            def failing_write(tasks, directory):
                if "simulation" in Path(directory).parts:
                    raise OSError("disk full")
                return parquet_tasks(tasks, directory)

            with patch("forecast_workload.parquet_tasks", side_effect=failing_write):
                with self.assertRaisesRegex(OSError, "disk full"):
                    run_once(
                        root / "audit",
                        root / "out",
                        BASE + 40750,
                        settings(),
                        simulation_inputs=True,
                    )
            manifest = root / "out/simulation/manifest.json"
            self.assertFalse(manifest.exists())

    def invoke(self, root, extra):
        args = [
            "forecast_workload.py",
            "--observer-dir",
            str(root / "audit"),
            "--output-dir",
            str(root / "out"),
            "--run-id",
            "test",
            "--phase-origin",
            iso(BASE),
            "--period-seconds",
            "20",
            "--horizon-seconds",
            "20",
            "--scenarios",
            "2",
            "--simulation-inputs",
        ] + extra
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
            try:
                main()
            except SystemExit as exc:
                return exc.code, stdout.getvalue()
        return 0, stdout.getvalue()

    def test_cli_readiness_exit_codes(self):
        for invalid_state, expected in [(False, 0), (True, 2)]:
            with self.subTest(invalid_state=invalid_state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rows = simulation_rows()
                if invalid_state:
                    job = rows["cluster-state.jsonl"][40]["jobs"]["queued"].pop()
                    job.update(pod_phase="Running", execution_state="unknown")
                    rows["cluster-state.jsonl"][40]["jobs"]["active"] = [job]
                save_rows(root / "audit", rows)
                code, stdout = self.invoke(root, ["--cutoff", iso(BASE + 40750)])
                self.assertEqual(code, expected, stdout)
                if expected == 2:
                    self.assertEqual(json.loads(stdout)["simulation_inputs"]["status"], "not_ready")

    def test_removed_tail_option_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.invoke(
                Path(tmp), ["--cutoff", iso(BASE + 40750), "--overrun-remaining-seconds", "5"]
            )
            self.assertEqual(code, 2)

    def test_exhausted_running_job_is_exported_only_as_evidence(self):
        for elapsed in (9999, 10000, 10001):
            with self.subTest(elapsed=elapsed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rows = simulation_rows()
                state = rows["cluster-state.jsonl"][40]
                job = state["jobs"]["queued"].pop()
                job.update(
                    creation_time=iso(BASE + 29000),
                    pod_phase="Running",
                    execution_state="running",
                    execution_start_time=iso(BASE + 40000 - elapsed),
                )
                # Match the immutable arrival record used for identity/creation validation.
                for snapshot in rows["cluster-state.jsonl"]:
                    for queued in snapshot["jobs"]["queued"]:
                        queued["creation_time"] = job["creation_time"]
                state["jobs"]["active"] = [job]
                save_rows(root / "audit", rows)
                summary, _ = run_once(
                    root / "audit",
                    root / "out",
                    BASE + 40000,
                    settings(horizon_seconds=5),
                    simulation_inputs=True,
                )
                bundle = root / "out/simulation"
                manifest = json.loads((bundle / "manifest.json").read_text())
                self.assertEqual(manifest["status"], "ready", summary)
                initial = json.loads((bundle / "initial-state.json").read_text())
                job_id = manifest["job_ids"]["queued"]
                self.assertEqual(len(initial["model_exhausted_jobs"]), int(elapsed >= 10000))
                empty_scenarios = 0
                for scenario in manifest["scenarios"]:
                    path = f"scenarios/{scenario['index']:04d}"
                    tasks = pq.read_table(bundle / path / "tasks.parquet").to_pylist()
                    fragments = pq.read_table(bundle / path / "fragments.parquet").to_pylist()
                    self.assertEqual(any(t["id"] == job_id for t in tasks), elapsed < 10000)
                    self.assertEqual(any(f["id"] == job_id for f in fragments), elapsed < 10000)
                    self.assertTrue(all(t["duration"] > 0 for t in tasks))
                    self.assertTrue(all(f["duration"] > 0 for f in fragments))
                    empty_scenarios += int(not tasks)
                    for name in ("tasks", "fragments"):
                        schema = pq.read_schema(bundle / path / f"{name}.parquet")
                        self.assertTrue(all(not field.nullable for field in schema))
                        self.assertEqual(
                            schema, pq.read_schema(root / "out" / path / f"{name}.parquet")
                        )
                self.assertEqual(empty_scenarios > 0, elapsed >= 10000)
                # Opting into simulation inputs must not alter sampled arrivals/profiles.
                run_once(
                    root / "audit",
                    root / "forecast-only",
                    BASE + 40000,
                    settings(horizon_seconds=5),
                )
                for path in (root / "out/scenarios").rglob("*.parquet"):
                    relative = path.relative_to(root / "out")
                    self.assertEqual(
                        path.read_bytes(), (root / "forecast-only" / relative).read_bytes()
                    )

    def test_periodic_mode_exports_each_effective_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_rows(root / "audit", simulation_rows())
            with patch(
                "forecast_workload.time.time_ns",
                side_effect=[(BASE + 40750) * 1000000, (BASE + 50750) * 1000000],
            ), patch("forecast_workload.time.sleep"):
                code, stdout = self.invoke(root, ["--interval-seconds", "10", "--iterations", "2"])
            self.assertEqual(code, 0, stdout)
            for requested, effective in [(40750, 40000), (50750, 50000)]:
                manifest = json.loads(
                    (root / "out" / str(BASE + requested) / "simulation/manifest.json").read_text()
                )
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["effective_cutoff"], iso(BASE + effective))


if __name__ == "__main__":
    unittest.main()
