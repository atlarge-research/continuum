"""Pure conversion from forecast evidence to simulator-ready inputs."""
from pathlib import Path
import copy
import sys
import unittest
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forecast_trace import Trace, iso, milliseconds
from simulation_input import build_simulation_inputs


BASE = milliseconds("2026-09-17T10:00:00Z")
CUTOFF = BASE + 10_000


def profile(task_id=0, submission_ms=BASE, durations=(1000, 2000, 3000)):
    usages = (600.0, 1200.0, 1800.0)
    return {
        "id": task_id,
        "submission_time": iso(submission_ms),
        "duration": sum(durations),
        "cpu_count": 1,
        "cpu_capacity": 2400.0,
        "mem_capacity": 512,
        "fragments": [
            {
                "id": task_id,
                "duration": duration,
                "cpu_count": 1,
                "cpu_usage": usages[index],
            }
            for index, duration in enumerate(durations)
        ],
    }


def template():
    return {
        "schema_version": 1,
        "workload_run_id": "run-test",
        "sha256": "frozen-template",
        "record": {
            "task": profile(),
            "source": {
                "kubernetes_job_uid": "template-job",
                "workload_run_id": "run-test",
                "request_id": "template-request",
                "endpoint_batch_id": "template-batch",
                "image_count": 4,
                "inference_repetitions": 128,
            },
        },
    }


def worker(name="worker-a", schedulable=True):
    return {
        "kubernetes_node_uid": "node-uid-" + name,
        "node_name": name,
        "ready": True,
        "schedulable": schedulable,
        "allocatable_cpu_count": 4.0,
        "allocatable_memory_mb": 8192,
    }


def state_job(
    uid,
    created_ms,
    *,
    node_name=None,
    pod_phase=None,
    execution_state=None,
    execution_start_ms=None,
):
    result = {
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
        "creation_time": iso(created_ms),
        "start_time": iso(created_ms + 100) if node_name else None,
        "execution_start_time": (
            iso(execution_start_ms) if execution_start_ms is not None else None
        ),
        "requested_cpu_count": 1.0,
        "requested_memory_mb": 512,
        "pod_name": uid + "-pod" if pod_phase else None,
        "pod_phase": pod_phase,
        "node_name": node_name,
    }
    if execution_state is not None:
        result.update(
            execution_state=execution_state,
            execution_finish_time=None,
        )
    return result


def settings(**overrides):
    values = {
        "run_id": "run-test",
        "horizon_seconds": 20,
        "scenarios": 1,
        "image_count": 4,
        "inference_repetitions": 128,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def trace_with_state(queued=None, active=None, arrivals=None, completed=None, workers=None):
    state = {
        "schema_version": 1,
        "timestamp": iso(CUTOFF),
        "jobs": {"queued": queued or [], "active": active or []},
        "workers": workers if workers is not None else [worker()],
    }
    return Trace(
        cutoff=CUTOFF,
        arrivals=arrivals or {},
        completed=completed or [],
        states=[(CUTOFF, state)],
        capture_failures=[],
        state=state,
    )


def future(task_id, arrival_ms):
    return profile(task_id=task_id, submission_ms=arrival_ms)


class SimulationInputTests(unittest.TestCase):
    def test_builds_shared_backlog_and_normalizes_each_scenario_without_mutation(self):
        queued = state_job("queued", BASE + 2000, pod_phase="Pending", execution_state="waiting")
        startup = state_job(
            "startup",
            BASE + 3000,
            node_name="worker-a",
            pod_phase="Running",
            execution_state="waiting",
        )
        running = state_job(
            "running",
            BASE + 4000,
            node_name="worker-a",
            pod_phase="Running",
            execution_state="running",
            execution_start_ms=CUTOFF - 1500,
        )
        completed_record = {
            "task": profile(),
            "source": {"kubernetes_job_uid": "completed"},
        }
        arrivals = {
            "completed": {"creation_ms": BASE + 1000},
            "queued": {"creation_ms": BASE + 2000},
            "startup": {"creation_ms": BASE + 3000},
            "running": {"creation_ms": BASE + 4000},
        }
        trace = trace_with_state(
            queued=[queued, startup],
            active=[running],
            arrivals=arrivals,
            completed=[completed_record],
            workers=[worker(), worker("worker-cordoned", schedulable=False)],
        )
        scenarios = [
            [future(5, CUTOFF), future(6, CUTOFF + 19_999)],
            [future(5, CUTOFF + 500)],
        ]
        before = copy.deepcopy((trace, scenarios, template()))

        manifest, initial, combined = build_simulation_inputs(
            trace, before[2], scenarios, settings(scenarios=2)
        )

        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(manifest["reasons"], [])
        self.assertEqual(manifest["cutoff"], iso(CUTOFF))
        self.assertEqual(manifest["horizon_ms"], 20_000)
        self.assertEqual(
            manifest["job_ids"],
            {"completed": 1, "queued": 2, "startup": 3, "running": 4},
        )
        self.assertEqual(initial["workers"], trace.state["workers"])
        self.assertFalse(initial["workers"][1]["schedulable"])
        self.assertEqual([item["task"]["id"] for item in initial["tasks"]], [2, 3, 4])
        self.assertEqual(
            [item["metadata"]["phase"] for item in initial["tasks"]],
            ["queued", "startup", "running"],
        )
        self.assertEqual(
            [item["metadata"]["queue_order"] for item in initial["tasks"]],
            [0, 1, 2],
        )
        self.assertEqual(
            [item["task"]["submission_time"] for item in initial["tasks"]],
            [0, 0, 0],
        )
        self.assertEqual(
            [item["metadata"]["original_creation_ms"] for item in initial["tasks"]],
            [BASE + 2000, BASE + 3000, BASE + 4000],
        )
        self.assertEqual(initial["tasks"][0]["task"]["duration"], 6000)
        self.assertEqual(initial["tasks"][1]["task"]["duration"], 6000)
        self.assertEqual(initial["tasks"][2]["metadata"]["elapsed_ms"], 1500)
        self.assertEqual(initial["tasks"][2]["task"]["duration"], 4500)
        self.assertEqual(
            initial["tasks"][2]["task"]["fragments"],
            [
                {"id": 4, "duration": 1500, "cpu_count": 1, "cpu_usage": 1200.0},
                {"id": 4, "duration": 3000, "cpu_count": 1, "cpu_usage": 1800.0},
            ],
        )
        backlog = [item["task"] for item in initial["tasks"]]
        self.assertEqual(combined[0][:3], backlog)
        self.assertEqual(combined[1][:3], backlog)
        self.assertEqual([task["submission_time"] for task in combined[0][3:]], [0, 19999])
        self.assertEqual([task["id"] for task in combined[1][3:]], [5])
        self.assertEqual(
            [row["task_id"] for row in manifest["scenarios"][0]["future_tasks"]],
            [5, 6],
        )
        self.assertEqual(
            manifest["scenarios"][0]["future_tasks"][0]["template_request_id"],
            "template-request",
        )
        self.assertNotIn("request_id", manifest["scenarios"][0]["future_tasks"][0])
        self.assertEqual(initial["tasks"][0]["metadata"]["request_id"], "request-queued")
        self.assertEqual(initial["tasks"][0]["metadata"]["run_id"], "run-test")
        self.assertEqual(initial["tasks"][0]["metadata"]["workload_run_id"], "run-test")
        self.assertEqual(initial["tasks"][0]["metadata"]["endpoint_batch_id"], "batch")
        self.assertEqual((trace, scenarios, before[2]), before)
        self.assertEqual(
            build_simulation_inputs(trace, before[2], scenarios, settings(scenarios=2)),
            (manifest, initial, combined),
        )

    def test_running_profile_trims_before_at_and_inside_fragment_boundaries(self):
        cases = {
            999: [(1, 600.0), (2000, 1200.0), (3000, 1800.0)],
            1000: [(2000, 1200.0), (3000, 1800.0)],
            2500: [(500, 1200.0), (3000, 1800.0)],
        }
        for elapsed, expected in cases.items():
            with self.subTest(elapsed=elapsed):
                running = state_job(
                    "running",
                    BASE + 1000,
                    node_name="worker-a",
                    pod_phase="Running",
                    execution_state="running",
                    execution_start_ms=CUTOFF - elapsed,
                )
                trace = trace_with_state(
                    active=[running],
                    arrivals={"running": {"creation_ms": BASE + 1000}},
                )
                manifest, initial, combined = build_simulation_inputs(
                    trace, template(), [[]], settings()
                )
                self.assertEqual(manifest["status"], "ready")
                fragments = initial["tasks"][0]["task"]["fragments"]
                self.assertEqual(
                    [(fragment["duration"], fragment["cpu_usage"]) for fragment in fragments],
                    expected,
                )
                self.assertEqual(combined[0][0], initial["tasks"][0]["task"])

    def test_seven_seconds_trimmed_from_five_and_ten_second_fragments(self):
        frozen = template()
        frozen["record"]["task"] = profile(durations=(5000, 10000))
        running = state_job(
            "running",
            BASE,
            node_name="worker-a",
            pod_phase="Running",
            execution_state="running",
            execution_start_ms=CUTOFF - 7000,
        )
        manifest, _, combined = build_simulation_inputs(
            trace_with_state(active=[running], arrivals={"running": {"creation_ms": BASE}}),
            frozen,
            [[]],
            settings(),
        )
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(combined[0][0]["duration"], 8000)
        self.assertEqual(
            combined[0][0]["fragments"],
            [{"id": 1, "duration": 8000, "cpu_count": 1, "cpu_usage": 1200.0}],
        )

    def test_profile_exhaustion_is_model_evidence_not_executable_or_completed(self):
        for elapsed in (5999, 6000, 6001, 7000):
            with self.subTest(elapsed=elapsed):
                running = state_job(
                    "running",
                    BASE + 1000,
                    node_name="worker-a",
                    pod_phase="Running",
                    execution_state="running",
                    execution_start_ms=CUTOFF - elapsed,
                )
                trace = trace_with_state(
                    active=[running],
                    arrivals={"running": {"creation_ms": BASE + 1000}},
                )
                original = copy.deepcopy(trace.state)
                manifest, initial, combined = build_simulation_inputs(
                    trace, template(), [[], []], settings(scenarios=2)
                )
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(trace.state, original)
                self.assertEqual(manifest["job_ids"]["running"], 1)
                if elapsed < 6000:
                    self.assertEqual(initial["model_exhausted_jobs"], [])
                    task = initial["tasks"][0]["task"]
                    self.assertEqual(task["duration"], 1)
                    self.assertEqual(
                        task["fragments"],
                        [{"id": 1, "duration": 1, "cpu_count": 1, "cpu_usage": 1800.0}],
                    )
                    self.assertEqual(combined, [[task], [task]])
                    continue
                self.assertEqual(initial["tasks"], [])
                self.assertEqual(combined, [[], []])
                evidence = initial["model_exhausted_jobs"][0]
                self.assertEqual(evidence["task_id"], 1)
                self.assertEqual(evidence["remaining_execution_ms"], 0)
                self.assertEqual(evidence["template_duration_ms"], 6000)
                self.assertFalse(evidence["observed_completed"])
                self.assertEqual(evidence["metadata"]["phase"], "running")
                self.assertEqual(evidence["metadata"]["node_name"], "worker-a")
                self.assertEqual(evidence["metadata"]["kubernetes_job_uid"], "running")
                self.assertEqual(evidence["metadata"]["original_creation_ms"], BASE + 1000)
                self.assertEqual(evidence["metadata"]["elapsed_ms"], elapsed)
                self.assertEqual(
                    evidence["metadata"]["execution_start_time"], running["execution_start_time"]
                )
                diagnostic = next(
                    d for d in manifest["diagnostics"] if d["code"] == "running_profile_exhausted"
                )
                self.assertEqual(diagnostic["remaining_ms"], 0)
                self.assertEqual(diagnostic["elapsed_ms"], elapsed)

    def test_simulation_completion_does_not_select_an_evaluation_policy(self):
        manifest, initial, _ = build_simulation_inputs(
            trace_with_state(), template(), [[]], settings()
        )
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(initial["schema_version"], 2)
        self.assertNotIn("drain_scoring", manifest)
        self.assertEqual(manifest["simulation_completion"]["arrival_horizon_ms"], 20000)
        self.assertEqual(manifest["evaluation_policy"]["status"], "unresolved")
        self.assertEqual(len(manifest["evaluation_policy"]["open_questions"]), 3)

    def test_completed_and_terminal_jobs_are_excluded_and_empty_is_ready(self):
        completed = state_job("completed", BASE + 1000)
        terminated = state_job(
            "terminated",
            BASE + 2000,
            node_name="worker-a",
            pod_phase="Running",
            execution_state="terminated",
            execution_start_ms=BASE + 3000,
        )
        terminated["execution_finish_time"] = iso(BASE + 4000)
        trace = trace_with_state(
            queued=[completed],
            active=[terminated],
            arrivals={
                "completed": {"creation_ms": BASE + 1000},
                "terminated": {"creation_ms": BASE + 2000},
            },
            completed=[{"task": profile(), "source": {"kubernetes_job_uid": "completed"}}],
        )
        manifest, initial, combined = build_simulation_inputs(trace, template(), [[]], settings())
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(initial["tasks"], [])
        self.assertEqual(combined, [[]])

    def test_legacy_pending_and_running_states_are_classified(self):
        pending = state_job("pending", BASE + 1000, pod_phase="Pending")
        startup = state_job("startup", BASE + 2000, node_name="worker-a", pod_phase="Pending")
        running = state_job(
            "running",
            BASE + 3000,
            node_name="worker-a",
            pod_phase="Running",
            execution_start_ms=CUTOFF - 500,
        )
        trace = trace_with_state(
            queued=[pending, startup],
            active=[running],
            arrivals={
                "pending": {"creation_ms": BASE + 1000},
                "startup": {"creation_ms": BASE + 2000},
                "running": {"creation_ms": BASE + 3000},
            },
        )
        manifest, initial, _ = build_simulation_inputs(trace, template(), [[]], settings())
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(
            [item["metadata"]["phase"] for item in initial["tasks"]],
            ["queued", "startup", "running"],
        )

    def test_explicit_unknown_is_inferred_only_for_queued_pending_work(self):
        no_pod = state_job("no-pod", BASE + 2000, execution_state="unknown")
        pending = state_job(
            "pending",
            BASE + 1000,
            node_name="worker-a",
            pod_phase="Pending",
            execution_state="unknown",
        )
        trace = trace_with_state(
            queued=[no_pod, pending],
            arrivals={
                "no-pod": {"creation_ms": BASE + 2000},
                "pending": {"creation_ms": BASE + 1000},
            },
        )

        manifest, initial, _ = build_simulation_inputs(trace, template(), [[]], settings())

        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(
            [item["metadata"]["kubernetes_job_uid"] for item in initial["tasks"]],
            ["pending", "no-pod"],
        )
        self.assertEqual([item["metadata"]["queue_order"] for item in initial["tasks"]], [0, 1])
        self.assertEqual(
            [item["metadata"]["phase"] for item in initial["tasks"]],
            ["startup", "queued"],
        )

    def test_contradictory_nonterminal_lifecycle_is_not_ready(self):
        waiting_started = state_job(
            "waiting-started",
            BASE + 1000,
            pod_phase="Pending",
            execution_state="waiting",
            execution_start_ms=CUTOFF - 100,
        )
        unknown_started = state_job(
            "unknown-started",
            BASE + 1000,
            pod_phase="Pending",
            execution_state="unknown",
            execution_start_ms=CUTOFF - 100,
        )
        running_pending = state_job(
            "running-pending",
            BASE + 1000,
            node_name="worker-a",
            pod_phase="Pending",
            execution_state="running",
            execution_start_ms=CUTOFF - 100,
        )
        cases = (
            (waiting_started, "queued", "execution_timing_invalid"),
            (unknown_started, "queued", "execution_timing_invalid"),
            (running_pending, "active", "execution_state_invalid"),
        )
        for job, group, expected in cases:
            with self.subTest(uid=job["kubernetes_job_uid"]):
                trace = trace_with_state(
                    **{group: [job]},
                    arrivals={job["kubernetes_job_uid"]: {"creation_ms": BASE + 1000}},
                )
                manifest, _, combined = build_simulation_inputs(trace, template(), [[]], settings())
                self.assertEqual(manifest["status"], "not_ready")
                self.assertIn(expected, manifest["reasons"])
                self.assertEqual(combined, [])

    def test_invalid_observer_state_is_not_ready_with_explicit_diagnostics(self):
        invalid_cases = {}
        invalid_cases["duplicate_job"] = trace_with_state(
            queued=[state_job("same", BASE + 1000)],
            active=[state_job("same", BASE + 1000)],
            arrivals={"same": {"creation_ms": BASE + 1000}},
        )
        invalid_cases["execution_state_unknown"] = trace_with_state(
            active=[
                state_job(
                    "unknown",
                    BASE + 1000,
                    node_name="worker-a",
                    pod_phase="Running",
                    execution_state="unknown",
                )
            ],
            arrivals={"unknown": {"creation_ms": BASE + 1000}},
        )
        invalid_cases["execution_start_missing"] = trace_with_state(
            active=[
                state_job(
                    "old-running",
                    BASE + 1000,
                    node_name="worker-a",
                    pod_phase="Running",
                )
            ],
            arrivals={"old-running": {"creation_ms": BASE + 1000}},
        )
        unassigned = state_job(
            "unassigned", BASE + 1000, pod_phase="Running", execution_state="running"
        )
        unassigned["execution_start_time"] = iso(CUTOFF - 100)
        invalid_cases["running_unassigned"] = trace_with_state(
            active=[unassigned],
            arrivals={"unassigned": {"creation_ms": BASE + 1000}},
        )
        missing_worker = state_job(
            "missing-worker",
            BASE + 1000,
            node_name="worker-missing",
            pod_phase="Running",
            execution_state="waiting",
        )
        invalid_cases["worker_missing"] = trace_with_state(
            queued=[missing_worker],
            arrivals={"missing-worker": {"creation_ms": BASE + 1000}},
        )
        future_creation = state_job("future", CUTOFF + 1)
        invalid_cases["creation_after_cutoff"] = trace_with_state(
            queued=[future_creation],
            arrivals={"future": {"creation_ms": CUTOFF + 1}},
        )
        mismatch = state_job("mismatch", BASE + 1000)
        mismatch["image_count"] = 5
        invalid_cases["workload_mismatch"] = trace_with_state(
            queued=[mismatch],
            arrivals={"mismatch": {"creation_ms": BASE + 1000}},
        )
        resource_mismatch = state_job("resources", BASE + 1000)
        resource_mismatch["requested_memory_mb"] = 1024
        invalid_cases["resource_mismatch"] = trace_with_state(
            queued=[resource_mismatch],
            arrivals={"resources": {"creation_ms": BASE + 1000}},
        )
        bad_timing = state_job(
            "timing",
            BASE + 1000,
            node_name="worker-a",
            pod_phase="Running",
            execution_state="running",
            execution_start_ms=CUTOFF + 1,
        )
        invalid_cases["execution_timing_invalid"] = trace_with_state(
            active=[bad_timing],
            arrivals={"timing": {"creation_ms": BASE + 1000}},
        )
        unexpected_finish = state_job("unfinished", BASE + 1000)
        unexpected_finish["execution_finish_time"] = iso(CUTOFF - 1)
        invalid_cases["execution_finish_invalid"] = trace_with_state(
            queued=[unexpected_finish],
            arrivals={"unfinished": {"creation_ms": BASE + 1000}},
        )

        for expected_code, trace in invalid_cases.items():
            with self.subTest(expected_code=expected_code):
                manifest, initial, combined = build_simulation_inputs(
                    trace, template(), [[]], settings()
                )
                self.assertEqual(manifest["status"], "not_ready")
                self.assertIn(expected_code, manifest["reasons"])
                self.assertIn(expected_code, [row["code"] for row in manifest["diagnostics"]])
                self.assertEqual(combined, [])
                self.assertEqual(initial["schema_version"], 2)

    def test_invalid_future_identity_window_and_profile_are_not_ready(self):
        trace = trace_with_state(arrivals={"historical": {"creation_ms": BASE + 1000}})
        cases = {
            "future_id_collision": [[future(1, CUTOFF)]],
            "future_id_duplicate": [[future(2, CUTOFF), future(2, CUTOFF + 1)]],
            "future_id_invalid": [[future(0, CUTOFF)]],
            "future_outside_horizon": [[future(2, CUTOFF + 20_000)]],
        }
        bad_profile = future(2, CUTOFF)
        bad_profile["mem_capacity"] = 1024
        cases["future_profile_mismatch"] = [[bad_profile]]
        for expected_code, scenarios in cases.items():
            with self.subTest(expected_code=expected_code):
                manifest, _, combined = build_simulation_inputs(
                    trace, template(), scenarios, settings()
                )
                self.assertEqual(manifest["status"], "not_ready")
                self.assertIn(expected_code, manifest["reasons"])
                self.assertEqual(combined, [])

    def test_future_arrival_window_does_not_clip_execution_duration(self):
        trace = trace_with_state()
        future_task = future(1, CUTOFF + 19_999)
        manifest, _, combined = build_simulation_inputs(
            trace, template(), [[future_task]], settings()
        )
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(combined[0][0]["submission_time"], 19_999)
        self.assertEqual(combined[0][0]["duration"], 6000)

    def test_malformed_template_physical_profile_raises_value_error(self):
        malformed = template()
        malformed["record"]["task"]["fragments"][0]["duration"] = 0
        with self.assertRaises(ValueError):
            build_simulation_inputs(trace_with_state(), malformed, [[]], settings())

    def test_fragment_ids_must_match_their_task_id(self):
        malformed = future(1, CUTOFF)
        malformed["fragments"][1]["id"] = 99
        with self.assertRaisesRegex(ValueError, "Fragment id"):
            build_simulation_inputs(trace_with_state(), template(), [[malformed]], settings())


if __name__ == "__main__":
    unittest.main()
