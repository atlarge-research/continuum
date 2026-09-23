"""Provisional OpenDC scenario preparation from frozen forecast evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow.parquet as pq


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forecast_trace import STREAMS, bounded_read, canonical, digest, iso, parquet_tasks, read_trace
from opendc_inputs import file_hashes, verify_inputs
from opendc_scenarios import prepare_suite
from simulation_input import build_simulation_inputs


BASE = 1_800_000_000_000
CUTOFF = BASE + 20_000


class Settings:
    """Minimal simulation settings fixture."""

    run_id = "run-test"
    horizon_seconds = 20
    scenarios = 2
    image_count = 4
    inference_repetitions = 128


def profile(task_id, submission_time, durations=(2_000, 4_000)):
    """Return one literal workload profile.

    Args:
        task_id (int): Identity shared by task and fragments.
        submission_time (str): ISO arrival time.
        durations (tuple[int]): Fragment lengths in milliseconds.

    Returns:
        dict: Task with literal CPU and memory demands.
    """
    return {
        "id": task_id,
        "submission_time": submission_time,
        "duration": sum(durations),
        "cpu_count": 1,
        "cpu_capacity": 2400.0,
        "mem_capacity": 512,
        "fragments": [
            {
                "id": task_id,
                "duration": duration,
                "cpu_count": 1,
                "cpu_usage": usage,
            }
            for duration, usage in zip(durations, (800.0, 1800.0))
        ],
    }


def template():
    """Return a correctly signed frozen forecast template.

    Returns:
        dict: Template envelope used to build measured fixture evidence.
    """
    result = {
        "schema_version": 1,
        "selection_cutoff": iso(CUTOFF - 5_000),
        "workload_run_id": "run-test",
        "record": {
            "task": profile(0, iso(BASE)),
            "source": {
                "kubernetes_job_uid": "completed",
                "workload_run_id": "run-test",
                "request_id": "template-request",
                "endpoint_batch_id": "template-batch",
                "image_count": 4,
                "inference_repetitions": 128,
            },
        },
    }
    result["sha256"] = digest(result)
    return result


def worker(name, cores, memory):
    """Return one ready and schedulable observed worker.

    Args:
        name (str): Kubernetes node name.
        cores (int): Observed allocatable CPU count.
        memory (float): Observed allocatable memory in MiB.

    Returns:
        dict: Worker state snapshot.
    """
    return {
        "kubernetes_node_uid": "uid-" + name,
        "node_name": name,
        "ready": True,
        "schedulable": True,
        "allocatable_cpu_count": float(cores),
        "allocatable_memory_mb": float(memory),
    }


def job(uid, node_name, execution_state, execution_start=None):
    """Return a nonterminal observed Job.

    Args:
        uid (str): Job identity.
        node_name (str or None): Observed assignment.
        execution_state (str): Classifier lifecycle state.
        execution_start (int or None): Classifier start in epoch milliseconds.

    Returns:
        dict: Job snapshot with explicit timing and requests.
    """
    created = BASE + 1_000
    return {
        "kubernetes_job_uid": uid,
        "job_name": uid,
        "namespace": "default",
        "request_id": "request-" + uid,
        "run_id": "run-test",
        "workload_run_id": "run-test",
        "endpoint_batch_id": "batch",
        "image_count": 4,
        "payload_bytes": 10,
        "inference_repetitions": 128,
        "creation_time": iso(created),
        "start_time": iso(BASE + 2_000) if node_name else None,
        "execution_start_time": iso(execution_start) if execution_start is not None else None,
        "execution_finish_time": None,
        "execution_state": execution_state,
        "requested_cpu_count": 1.0,
        "requested_memory_mb": 512.0,
        "pod_name": uid + "-pod" if node_name else None,
        "pod_phase": "Running" if node_name else "Pending",
        "node_name": node_name,
    }


def observer_rows(worker_records=None):
    """Return frozen observations with distinct assignment observation times.

    Args:
        worker_records (list[dict] or None): Optional replacement worker snapshots.

    Returns:
        dict: Append-only stream names mapped to JSON records.
    """
    workers = worker_records or [worker("worker-a", 4, 8192), worker("worker-b", 8, 16384)]
    queued = job("queued", None, "waiting")
    running = job("running", "worker-a", "running", CUTOFF - 1_000)
    exhausted = job("exhausted", "worker-a", "running", CUTOFF - 7_000)
    worker_names = {item["node_name"] for item in workers}
    starting = job("starting", "worker-b" if "worker-b" in worker_names else "worker-a", "waiting")
    snapshots = []
    for timestamp, active, waiting in (
        (CUTOFF - 4_000, [], [queued]),
        (CUTOFF - 3_000, [running, exhausted], [queued]),
        (CUTOFF - 1_000, [running, exhausted], [queued, starting]),
        (CUTOFF, [running, exhausted], [queued, starting]),
    ):
        snapshots.append(
            {
                "schema_version": 1,
                "timestamp": iso(timestamp),
                "jobs": {"queued": copy.deepcopy(waiting), "active": copy.deepcopy(active)},
                "workers": copy.deepcopy(workers),
                "counts": {"queued_jobs": len(waiting), "active_jobs": len(active)},
            }
        )
    completed_at = BASE + 9_000
    completed_task = profile(0, iso(BASE + 1_000))
    return {
        "workload.jsonl": [
            {
                "schema_version": 1,
                "task": completed_task,
                "source": {
                    **template()["record"]["source"],
                    "completion_time": iso(completed_at),
                    "terminal_status": "Complete",
                    "resource_sample_count": 3,
                    "sampling_quality": "sampled",
                },
            }
        ],
        "cluster-state.jsonl": snapshots,
        "observer-events.jsonl": [
            {
                "schema_version": 1,
                "timestamp": iso(completed_at + 1),
                "event_type": "task.emitted",
                "details": {"kubernetes_job_uid": "completed"},
            }
        ],
        "resource-snapshots.jsonl": [],
    }


def save_rows(directory, rows):
    """Write observer rows in their append-only stream format.

    Args:
        directory (Path): New observer directory.
        rows (dict): Stream names mapped to records.
    """
    directory.mkdir()
    for name in STREAMS:
        (directory / name).write_bytes(b"".join(canonical(row) for row in rows[name]))


def make_forecast(root, *, workers=None, requested_cutoff=CUTOFF + 500):
    """Create a ready schema-2 forecast fixture without the forecasting dependencies.

    Args:
        root (Path): Existing temporary parent directory.
        workers (list[dict] or None): Replacement observed worker state.
        requested_cutoff (int): Requested cutoff in epoch milliseconds.

    Returns:
        tuple[Path, Path]: Forecast and observer directories.

    Raises:
        AssertionError: Fixture construction does not derive ready inputs.
    """
    observer = root / "observer"
    save_rows(observer, observer_rows(workers))
    rows, boundaries = bounded_read(observer)
    trace = read_trace(rows, "run-test", CUTOFF)
    frozen_template = template()
    frozen_template["record"] = copy.deepcopy(trace.completed[0])
    frozen_template.pop("sha256")
    frozen_template["sha256"] = digest(frozen_template)
    futures = [
        [profile(20, iso(CUTOFF + 100)), profile(21, iso(CUTOFF + 10_000))],
        [profile(20, iso(CUTOFF + 5_000))],
    ]
    simulation_manifest, initial, combined = build_simulation_inputs(
        trace, frozen_template, futures, Settings()
    )
    if simulation_manifest["status"] != "ready":
        raise AssertionError(simulation_manifest)
    simulation_manifest.update(
        requested_cutoff=iso(requested_cutoff),
        effective_cutoff=iso(CUTOFF),
        inputs=boundaries,
        template_sha256=frozen_template["sha256"],
    )

    forecast = root / "forecast"
    forecast.mkdir()
    (forecast / "simulation").mkdir()
    (forecast / "scenarios").mkdir()
    (forecast / "forecast.json").write_bytes(
        canonical(
            {
                "schema_version": 1,
                "status": "ready",
                "cutoff": iso(CUTOFF),
                "requested_cutoff": iso(requested_cutoff),
                "settings": {
                    "run_id": "run-test",
                    "horizon_seconds": 20,
                    "scenarios": 2,
                    "max_gap_seconds": 3.0,
                },
                "template_sha256": frozen_template["sha256"],
                "inputs": boundaries,
                "simulation_inputs": {"status": "ready", "reasons": [], "diagnostics": []},
            }
        )
    )
    (forecast / "boundaries.json").write_bytes(canonical(boundaries))
    (forecast / "template.json").write_bytes(canonical(frozen_template))
    (forecast / "state.json").write_bytes(canonical(trace.state))
    (forecast / "simulation/initial-state.json").write_bytes(canonical(initial))
    for index, (absolute, relative) in enumerate(zip(futures, combined)):
        parquet_tasks(absolute, forecast / "scenarios" / f"{index:04d}")
        parquet_tasks(relative, forecast / "simulation/scenarios" / f"{index:04d}")
    (forecast / "simulation/manifest.json").write_bytes(canonical(simulation_manifest))
    return forecast, observer


def configuration(names=("worker-a", "worker-b", "worker-c"), cores=(4, 8, 4)):
    """Return worker configuration with one reserve worker by default.

    Args:
        names (tuple[str]): Configured node names.
        cores (tuple[int]): Corresponding configured CPU counts.

    Returns:
        dict: Worker configuration accepted by preparation.
    """
    return {
        "workers": [
            {"node_name": name, "configured_cores": core, "memory_mib": 12288}
            for name, core in zip(names, cores)
        ]
    }


def read_tasks(directory):
    """Return task rows keyed by ID from one exported source trace.

    Args:
        directory (Path): Prepared experiment directory.

    Returns:
        dict: Source task rows indexed by task ID.
    """
    return {
        row["id"]: row
        for row in pq.read_table(Path(directory) / "source/tasks.parquet").to_pylist()
    }


class ScenarioPreparationTests(unittest.TestCase):
    """Protect evidence lineage, candidate partitioning and worker capacity."""

    def test_reconstructs_membership_for_old_bundles_without_changing_their_files(self):
        """Add causal diagnostics to new cases even when the frozen parent predates them."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            path = forecast / "simulation/manifest.json"
            old = json.loads(path.read_text())
            old.pop("membership", None)
            path.write_bytes(canonical(old))
            before = file_hashes(forecast)
            suite = prepare_suite(forecast, observer, configuration(), root / "suite")
            self.assertTrue(suite.get("initial_membership", {}).get("complete", False))
            for experiment in suite["experiments"]:
                case = json.loads(
                    (root / "suite" / experiment["input_dir"] / "case.json").read_text()
                )
                self.assertEqual(case["initial_membership"], suite["initial_membership"])
            self.assertEqual(file_hashes(forecast), before)

    def test_prepares_shared_futures_scale_candidates_and_down_partition(self):
        """Keep sampled futures identical and omitted work explicit across candidates."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)

            manifest = prepare_suite(forecast, observer, configuration(), root / "suite")

            self.assertEqual(manifest["contract"], "opendc-scenarios-v1")
            self.assertEqual(manifest["status"], "ready")
            self.assertEqual(
                {row["candidate"] for row in manifest["experiments"]},
                {"unchanged", "scale-up", "scale-down"},
            )
            self.assertEqual(len(manifest["experiments"]), 6)
            self.assertEqual(manifest["unavailable_candidates"], [])
            cases = {}
            for experiment in manifest["experiments"]:
                directory = root / "suite" / experiment["input_dir"]
                case = json.loads((directory / "case.json").read_text())
                cases[(experiment["candidate"], experiment["scenario"])] = (directory, case)
                case_manifest = json.loads((directory / "manifest.json").read_text())
                self.assertEqual(
                    case_manifest["sha256"], file_hashes(directory, exclude=("manifest.json",))
                )
                self.assertEqual(case_manifest["contract"], "opendc-provisional-v1")
                self.assertEqual(case_manifest["initial_state"], "provisional-trace")

            unchanged_tasks = read_tasks(cases[("unchanged", 0)][0])
            up_tasks = read_tasks(cases[("scale-up", 0)][0])
            down_tasks = read_tasks(cases[("scale-down", 0)][0])
            self.assertEqual(unchanged_tasks, up_tasks)
            self.assertEqual(unchanged_tasks[20], down_tasks[20])
            self.assertEqual(unchanged_tasks[21], down_tasks[21])
            down_case = cases[("scale-down", 0)][1]
            task_ids = {
                row["metadata"].get("kubernetes_job_uid"): row["task"]["id"]
                for row in cases[("unchanged", 0)][1]["tasks"]
                if row["metadata"]["cohort"] == "backlog"
            }
            self.assertNotIn(task_ids["running"], down_tasks)
            self.assertIn(task_ids["queued"], down_tasks)
            self.assertIn(task_ids["starting"], down_tasks)
            self.assertEqual(down_case["scope"], "remaining_workers_only")
            self.assertEqual(down_case["selected_worker"], "worker-a")
            self.assertEqual(
                [row["task"]["id"] for row in down_case["omitted_tasks"]],
                [task_ids["running"]],
            )
            exhausted = down_case["model_exhausted_jobs"][0]
            self.assertEqual(exhausted["metadata"]["kubernetes_job_uid"], "exhausted")
            self.assertEqual(exhausted["metadata"]["first_assignment_observed_ms"], CUTOFF - 3_000)
            self.assertEqual(
                exhausted["metadata"]["assignment_time_basis"], "first_observed_assignment"
            )
            self.assertEqual(
                [
                    (row["node_name"], row["modeled_cores"])
                    for row in cases[("scale-up", 0)][1]["workers"]
                ],
                [("worker-a", 3), ("worker-b", 7), ("worker-c", 3)],
            )
            self.assertEqual(cases[("unchanged", 0)][1]["workers"][0]["memory_mib"], 8192)
            self.assertEqual(cases[("scale-up", 0)][1]["workers"][2]["memory_mib"], 12288)
            self.assertEqual(cases[("scale-up", 0)][1]["workers"][2]["frequency_mhz"], 2400.0)
            self.assertEqual(
                (root / "suite/source-evidence/forecast/template.json").read_bytes(),
                (forecast / "template.json").read_bytes(),
            )

    def test_selection_uses_first_assignment_observation_including_starting_jobs(self):
        """Include starting work when deriving the oldest latest assignment."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            manifest = prepare_suite(forecast, observer, configuration(), root / "suite")
            down = next(row for row in manifest["experiments"] if row["candidate"] == "scale-down")
            case = json.loads((root / "suite" / down["input_dir"] / "case.json").read_text())

            self.assertEqual(case["selected_worker"], "worker-a")
            metadata = {
                row["metadata"]["kubernetes_job_uid"]: row["metadata"]
                for row in case["tasks"] + case["omitted_tasks"]
                if row["metadata"]["cohort"] == "backlog"
            }
            self.assertEqual(metadata["running"]["first_assignment_observed_ms"], CUTOFF - 3_000)
            self.assertEqual(metadata["starting"]["first_assignment_observed_ms"], CUTOFF - 1_000)
            self.assertNotEqual(metadata["running"]["first_assignment_observed_ms"], CUTOFF - 1_000)

    def test_rejects_unready_stale_tampered_and_incomplete_sources(self):
        """Reject invalid saved inputs before publishing a ready suite."""
        for problem in ("unready", "stale", "tampered", "missing-job"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                requested = CUTOFF + (4_000 if problem == "stale" else 500)
                forecast, observer = make_forecast(root, requested_cutoff=requested)
                if problem == "unready":
                    path = forecast / "simulation/manifest.json"
                    value = json.loads(path.read_text())
                    value["status"] = "not_ready"
                    path.write_bytes(canonical(value))
                elif problem == "tampered":
                    with (observer / "cluster-state.jsonl").open("r+b") as stream:
                        stream.seek(10)
                        byte = stream.read(1)
                        stream.seek(10)
                        stream.write(b"0" if byte != b"0" else b"1")
                elif problem == "missing-job":
                    path = forecast / "simulation/initial-state.json"
                    value = json.loads(path.read_text())
                    value["tasks"].pop()
                    path.write_bytes(canonical(value))
                with self.assertRaises(ValueError):
                    prepare_suite(forecast, observer, configuration(), root / "suite")

    def test_propagates_explicit_experiment_kind(self):
        """Carry explicit synthetic-state labels into every generated case."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            summary = json.loads((forecast / "forecast.json").read_text())
            summary["experiment_kind"] = "synthetic-state-measured-profile"
            (forecast / "forecast.json").write_bytes(canonical(summary))

            manifest = prepare_suite(forecast, observer, configuration(), root / "suite")

            self.assertEqual(manifest["experiment_kind"], "synthetic-state-measured-profile")
            first = root / "suite" / manifest["experiments"][0]["input_dir"] / "case.json"
            self.assertEqual(
                json.loads(first.read_text())["experiment_kind"],
                "synthetic-state-measured-profile",
            )

    def test_rejects_contradictory_boundaries_state_and_template(self):
        """Reject contradictory saved evidence even when local hashes agree."""
        for change in ("horizon", "requested", "state", "template", "ghost", "truncated-scenarios"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                forecast, observer = make_forecast(root)
                simulation_path = forecast / "simulation/manifest.json"
                manifest = json.loads(simulation_path.read_text())
                if change == "truncated-scenarios":
                    manifest["scenarios"] = manifest["scenarios"][:1]
                    simulation_path.write_bytes(canonical(manifest))
                elif change == "horizon":
                    manifest["horizon_ms"] = 999999
                    simulation_path.write_bytes(canonical(manifest))
                elif change == "requested":
                    manifest["requested_cutoff"] = iso(CUTOFF + 1000)
                    simulation_path.write_bytes(canonical(manifest))
                elif change == "state":
                    state_path = forecast / "state.json"
                    state = json.loads(state_path.read_text())
                    state["jobs"]["active"] = []
                    state_path.write_bytes(canonical(state))
                else:
                    path = forecast / "template.json"
                    frozen = json.loads(path.read_text())
                    old_hash = frozen.pop("sha256")
                    if change == "ghost":
                        frozen["record"]["source"]["kubernetes_job_uid"] = "ghost"
                    else:
                        frozen["record"]["source"]["sampling_quality"] = "unmeasured"
                    frozen["sha256"] = digest(frozen)
                    path.write_bytes(canonical(frozen))
                    for item in forecast.rglob("*.json"):
                        item.write_text(item.read_text().replace(old_hash, frozen["sha256"]))
                with self.assertRaises(ValueError):
                    prepare_suite(forecast, observer, configuration(), root / "suite")

    def test_rejects_overlapping_evidence_before_creating_output(self):
        """Prevent a destination from recursively copying or replacing its source."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            for output in (forecast / "suite", observer / "suite"):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    prepare_suite(forecast, observer, configuration(), output)
                self.assertFalse(output.exists())

    def test_inactive_observed_scale_up_uses_observed_memory(self):
        """Reserve membership does not replace captured allocatable memory."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observed = [
                worker("worker-a", 4, 8192),
                worker("worker-b", 8, 16384),
                worker("worker-c", 4, 7168.9),
            ]
            forecast, observer = make_forecast(root, workers=observed)
            config = configuration()
            config["active_workers"] = ["worker-a", "worker-b"]
            prepare_suite(forecast, observer, config, root / "suite")
            case = json.loads((root / "suite/experiments/scale-up/0000/case.json").read_text())
            reserve = next(w for w in case["workers"] if w["node_name"] == "worker-c")
            self.assertEqual(reserve["memory_mib"], 7168)

    def test_omitted_and_exhausted_inventory_cannot_share_an_identity(self):
        """Keep an omitted executable task distinct from exhausted observed work."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            prepare_suite(forecast, observer, configuration(), root / "suite")
            source = root / "suite/experiments/scale-down/0000"
            case = json.loads((source / "case.json").read_text())
            omitted = case["omitted_tasks"][0]
            case["model_exhausted_jobs"].append(
                {
                    "task_id": omitted["task"]["id"],
                    "metadata": omitted["metadata"],
                    "remaining_execution_ms": 0,
                    "observed_completed": False,
                }
            )
            (source / "case.json").write_bytes(canonical(case))
            manifest = json.loads((source / "manifest.json").read_text())
            manifest["sha256"] = file_hashes(source, exclude=("manifest.json",))
            (source / "manifest.json").write_bytes(canonical(manifest))
            with self.assertRaises(ValueError):
                verify_inputs(source)

    def test_worker_count_limits_and_cpu_reservation(self):
        """Enforce one-core reservation and the one-to-three worker range."""
        cases = [
            (("worker-a",), (4,), {"scale-down"}, {"unchanged", "scale-up"}),
            (
                ("worker-a", "worker-b", "worker-c"),
                (4, 8, 4),
                {"scale-up"},
                {"unchanged", "scale-down"},
            ),
        ]
        for names, cores, unavailable, available in cases:
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                observed = [worker(name, core, 8192) for name, core in zip(names, cores)]
                forecast, observer = make_forecast(root, workers=observed)
                config = configuration(names, cores)
                if len(names) == 1:
                    config["workers"].append(
                        {"node_name": "worker-z", "configured_cores": 8, "memory_mib": 8192}
                    )
                manifest = prepare_suite(forecast, observer, config, root / "suite")
                self.assertEqual(
                    {row["candidate"] for row in manifest["unavailable_candidates"]}, unavailable
                )
                self.assertEqual({row["candidate"] for row in manifest["experiments"]}, available)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer = make_forecast(root)
            invalid = configuration()
            invalid["workers"][0]["configured_cores"] = 1
            with self.assertRaisesRegex(ValueError, "configured_cores"):
                prepare_suite(forecast, observer, invalid, root / "suite")


if __name__ == "__main__":
    unittest.main()
