"""Cutoff, observation coverage, and fixed-workload forecast contracts."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate_forecasts import evaluate
from forecast_trace import (
    STREAMS,
    bounded_read,
    canonical,
    iso,
    milliseconds,
    parquet_tasks,
    read_trace,
    training_bins,
)
from forecast_workload import (
    Settings,
    forecast,
    run_once,
    select_template,
)
from endpoint import build_periodic_schedule

BASE = milliseconds("2026-09-07T10:00:00Z")


def fixture():
    rows = {name: [] for name in STREAMS}
    for second in range(81):
        rows["cluster-state.jsonl"].append(
            {
                "schema_version": 1,
                "timestamp": iso(BASE + second * 1000),
                "jobs": {"queued": [], "active": []},
                "workers": [],
                "counts": {"queued_jobs": 0, "active_jobs": 0},
            }
        )
    for index, duration in enumerate((5000, 10000, 15000)):
        created = BASE + 1000 + index * 5000
        completion = created + duration + 2000
        uid = f"job-{index}"
        rows["observer-events.jsonl"].extend(
            [
                {
                    "schema_version": 1,
                    "timestamp": iso(created + 100),
                    "event_type": "job.observed",
                    "details": {
                        "kubernetes_job_uid": uid,
                        "workload_run_id": "test",
                        "creation_time": iso(created),
                    },
                },
                {
                    "schema_version": 1,
                    "timestamp": iso(completion + 100),
                    "event_type": "task.emitted",
                    "details": {"kubernetes_job_uid": uid},
                },
            ]
        )
        rows["workload.jsonl"].append(
            {
                "schema_version": 1,
                "task": {
                    "id": index,
                    "submission_time": iso(created),
                    "duration": duration,
                    "cpu_count": 1,
                    "cpu_capacity": 2400.0,
                    "mem_capacity": 512,
                    "fragments": [
                        {
                            "id": index,
                            "duration": duration,
                            "cpu_count": 1,
                            "cpu_usage": 1800.0,
                        }
                    ],
                },
                "source": {
                    "kubernetes_job_uid": uid,
                    "workload_run_id": "test",
                    "completion_time": iso(completion),
                    "terminal_status": "Complete",
                    "image_count": 4,
                    "inference_repetitions": 128,
                    "resource_sample_count": 3,
                    "sampling_quality": "sampled",
                },
            }
        )
    return rows


def settings(**kwargs):
    return replace(
        Settings(
            run_id="test",
            origin_ms=BASE,
            period_seconds=20,
            horizon_seconds=20,
            scenarios=4,
        ),
        **kwargs,
    )


def save_rows(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    for name, records in rows.items():
        (root / name).write_bytes(b"".join(canonical(row) for row in records))


class ForecastTests(unittest.TestCase):
    def test_more_cycles_extend_the_run_preserving_the_period_and_existing_arrivals(self):
        common = dict(period_seconds=120, minimum_rate_per_second=0.2, peak_rate_per_second=1.0)
        old = build_periodic_schedule(**common, generator=random.Random(42))
        self.assertEqual(
            old,
            build_periodic_schedule(**common, arrival_cycles=1, generator=random.Random(42)),
        )
        multi = build_periodic_schedule(**common, arrival_cycles=2, generator=random.Random(42))
        first = [a for a in multi if a.planned_offset_ns < 120_000_000_000]
        second = [
            a.planned_offset_ns - 120_000_000_000
            for a in multi
            if a.planned_offset_ns >= 120_000_000_000
        ]
        self.assertEqual(first, old)
        self.assertTrue(second)
        self.assertLess(multi[-1].planned_offset_ns, 240_000_000_000)
        self.assertNotEqual([a.planned_offset_ns for a in first], second)
        self.assertEqual(
            multi,
            build_periodic_schedule(**common, arrival_cycles=2, generator=random.Random(42)),
        )
        with self.assertRaises(ValueError):
            build_periodic_schedule(**common, arrival_cycles=0, generator=random.Random(42))

    def test_bounded_prefix_survives_appends_and_ignores_partial_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root, fixture())
            path = root / "workload.jsonl"
            with path.open("ab") as f:
                f.write(b'{"schema_version":1')
            before, manifest = bounded_read(root)
            with path.open("ab") as f:
                f.write(b"}\n")
            after, replay = bounded_read(root, manifest)
            self.assertEqual(before, after)
            self.assertEqual(manifest, replay)
            path.write_bytes(b"bad\n")
            with self.assertRaises(ValueError):
                bounded_read(root, manifest)

    def test_malformed_complete_line_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root, fixture())
            (root / "workload.jsonl").write_bytes(b'{"schema_version":1,}\n')
            with self.assertRaisesRegex(ValueError, "workload.jsonl:1"):
                bounded_read(root)

    def test_arrivals_accumulate_and_wait_for_first_observation(self):
        rows = fixture()
        rows["observer-events.jsonl"][0]["timestamp"] = iso(BASE + 60000)
        rows["observer-events.jsonl"] = [
            r for r in rows["observer-events.jsonl"] if r["event_type"] != "task.emitted"
        ]
        trace = read_trace(rows, "test", BASE + 40000)
        self.assertNotIn("job-0", trace.arrivals)
        self.assertEqual(len(trace.arrivals), 2)
        self.assertEqual(trace.completed, [])
        trace = read_trace(rows, "test", BASE + 60000)
        self.assertEqual(trace.arrivals["job-0"]["creation_ms"], BASE + 1000)

    def test_old_snapshots_supply_arrivals_and_terminal_correction(self):
        """Recover terminal evidence from old pressure lists without restoring it to backlog."""
        rows = fixture()
        job = {
            "kubernetes_job_uid": "pending-terminal",
            "workload_run_id": "test",
            "creation_time": iso(BASE),
            "pod_phase": "Succeeded",
        }
        rows["cluster-state.jsonl"][1]["jobs"]["queued"] = [job]
        trace = read_trace(rows, "test", BASE + 1000)
        self.assertIn("pending-terminal", trace.arrivals)
        self.assertEqual(trace.state["jobs"]["queued"], [])
        self.assertEqual(
            trace.observed_outcomes["pending-terminal"]["evidence_observed_ms"], BASE + 1000
        )

    def test_finished_inventory_is_causal_and_does_not_create_a_training_profile(self):
        """Retain classifier completion evidence before profile emission without future leakage."""
        rows = fixture()
        job = {
            "kubernetes_job_uid": "finished-before-emission",
            "workload_run_id": "test",
            "creation_time": iso(BASE),
            "pod_phase": "Running",
            "execution_state": "terminated",
            "execution_finish_time": iso(BASE + 500),
            "node_name": "worker-a",
        }
        rows["cluster-state.jsonl"][1]["jobs"]["finished"] = [job]
        before = read_trace(rows, "test", BASE + 999)
        self.assertNotIn(job["kubernetes_job_uid"], before.arrivals)
        after = read_trace(rows, "test", BASE + 1000)
        self.assertIn(job["kubernetes_job_uid"], after.arrivals)
        self.assertIn(job["kubernetes_job_uid"], after.observed_outcomes)
        self.assertEqual(after.completed, [])

    def test_completion_and_emission_are_both_required(self):
        rows = fixture()
        trace = read_trace(rows, "test", BASE + 18000)
        self.assertEqual(len(trace.completed), 1)  # second completion=18s, emission=18.1s
        rows["workload.jsonl"][0]["source"]["completion_time"] = iso(BASE + 70000)
        self.assertEqual(len(read_trace(rows, "test", BASE + 18000).completed), 0)

    def test_submillisecond_availability_does_not_leak_across_cutoff(self):
        rows = fixture()
        event = rows["observer-events.jsonl"][0]
        event["timestamp_unix_ns"] = (BASE + 40000) * 1_000_000 + 1
        rows["observer-events.jsonl"] = [
            r for r in rows["observer-events.jsonl"] if r["event_type"] != "task.emitted"
        ]
        self.assertNotIn("job-0", read_trace(rows, "test", BASE + 40000).arrivals)
        self.assertIn("job-0", read_trace(rows, "test", BASE + 40001).arrivals)

    def test_duplicate_identity_conflicts_rejected(self):
        rows = fixture()
        rows["workload.jsonl"].append(copy.deepcopy(rows["workload.jsonl"][0]))
        self.assertEqual(len(read_trace(rows, "test", BASE + 40000).completed), 3)
        rows["workload.jsonl"][-1]["task"]["duration"] += 1
        rows["workload.jsonl"][-1]["task"]["fragments"][0]["duration"] += 1
        with self.assertRaisesRegex(ValueError, "conflicting completed"):
            read_trace(rows, "test", BASE + 40000)

    def test_zero_missing_partial_bins_and_configurable_gap(self):
        rows = fixture()
        rows["cluster-state.jsonl"] = [
            r
            for r in rows["cluster-state.jsonl"]
            if milliseconds(r["timestamp"]) not in (BASE + 21000, BASE + 22000, BASE + 23000)
        ]
        trace = read_trace(rows, "test", BASE + 42000)
        summary, _, _, bins = forecast(trace, settings())
        self.assertEqual(summary["status"], "not_ready")
        self.assertIn("history_insufficient", summary["reasons"])
        self.assertEqual(summary["history"]["eligible_bins"], 7)
        self.assertEqual(summary["history"]["excluded_bins"], 1)
        self.assertEqual(summary["history"]["incomplete_bins"], 1)
        self.assertTrue(any(b["eligible"] and b["count"] == 0 for b in bins))
        self.assertEqual(forecast(trace, settings(max_gap_seconds=4))[0]["status"], "ready")
        # A third elapsed period supplies the missing phase's second usable bin.
        self.assertEqual(
            forecast(read_trace(rows, "test", BASE + 60000), settings())[0]["status"],
            "ready",
        )

    def test_recorded_collection_failure_excludes_bin_even_with_small_gap(self):
        rows = fixture()
        rows["observer-events.jsonl"].append(
            {
                "timestamp": iso(BASE + 22000),
                "event_type": "cluster_state.capture_failed",
            }
        )
        bins = training_bins(read_trace(rows, "test", BASE + 40000), BASE, 5000, 3000)
        self.assertFalse(bins[4]["eligible"])

    def test_template_is_median_whole_profile_and_frozen(self):
        trace = read_trace(fixture(), "test", BASE + 40000)
        template = select_template(trace, settings())
        self.assertEqual(template["record"]["source"]["kubernetes_job_uid"], "job-1")
        summary, selected, scenarios, _ = forecast(trace, settings(), template)
        self.assertEqual(selected, template)
        self.assertEqual(summary["status"], "ready")
        for tasks in scenarios:
            for task in tasks:
                self.assertEqual(task["duration"], 10000)
                self.assertEqual(task["fragments"][0]["duration"], 10000)
                self.assertEqual(task["fragments"][0]["id"], task["id"])

    def test_future_data_isolation_includes_template_selection_cutoff(self):
        rows = fixture()
        cutoff = BASE + 40000
        before = forecast(read_trace(rows, "test", cutoff), settings())
        changed = copy.deepcopy(rows)
        changed["observer-events.jsonl"].append(
            {
                "event_type": "job.observed",
                "timestamp": iso(BASE + 60000),
                "details": {
                    "workload_run_id": "test",
                    "creation_time": iso(BASE + 500),
                    "kubernetes_job_uid": "late",
                },
            }
        )
        changed["cluster-state.jsonl"][-1]["workers"] = [
            {"invalid": "future state must not be read"}
        ]
        self.assertEqual(before, forecast(read_trace(changed, "test", cutoff), settings()))
        later = select_template(read_trace(rows, "test", BASE + 60000), settings())
        self.assertEqual(later["record"], before[1]["record"])
        result = forecast(read_trace(rows, "test", cutoff), settings(), later)
        self.assertEqual(result[0]["reasons"], ["template_after_cutoff"])
        self.assertEqual(result[2], [])

    def test_not_ready_fit_failure_and_zero_scenarios_are_distinct(self):
        trace = read_trace(fixture(), "test", BASE + 40000)
        template = select_template(trace, settings())
        with patch(
            "forecast_workload.PoissonRegressor.fit",
            side_effect=ValueError("fit error"),
        ):
            self.assertEqual(forecast(trace, settings(), template)[0]["status"], "fit_failed")
        trace.arrivals = {}
        summary, _, scenarios, _ = forecast(trace, settings(), template)
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(scenarios, [[], [], [], []])
        trace.completed = []
        self.assertIn("template_unavailable", forecast(trace, settings())[0]["reasons"])
        trace.state = None
        self.assertIn("state_missing", forecast(trace, settings(), template)[0]["reasons"])
        trace.state = {}
        trace.cutoff += 4000
        self.assertIn("state_stale", forecast(trace, settings(), template)[0]["reasons"])

    def test_parquet_empty_and_full_have_identical_required_schema(self):
        task = fixture()["workload.jsonl"][0]["task"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parquet_tasks([], root / "empty")
            parquet_tasks([task], root / "full")
            for name in ("tasks", "fragments"):
                empty = pq.read_schema(root / "empty" / f"{name}.parquet")
                self.assertEqual(empty, pq.read_schema(root / "full" / f"{name}.parquet"))
                self.assertTrue(all(not field.nullable for field in empty))
                self.assertEqual(str(empty.field("id").type), "int32")

    def test_evaluation_counts_later_arrivals_and_excludes_experiment_shutdown(self):
        rows = fixture()
        rows["observer-events.jsonl"].append(
            {
                "schema_version": 1,
                "timestamp": iso(BASE + 42001),
                "event_type": "job.observed",
                "details": {
                    "kubernetes_job_uid": "future-job",
                    "workload_run_id": "test",
                    "creation_time": iso(BASE + 42000),
                },
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root / "inputs", rows)
            run_once(root / "inputs", root / "forecast", BASE + 40000, settings())
            result = evaluate(root / "inputs", root / "forecast", until=iso(BASE + 50000))
            self.assertEqual(result["scored_bins"], 2)
            self.assertEqual(result["uncovered_or_future_bins"], 2)
            self.assertEqual(result["scores"][0]["observed_count"], 1)
            self.assertEqual(result["scores"][1]["observed_count"], 0)

    def test_evaluation_uses_late_evidence_but_excludes_arrivals_at_or_after_end(self):
        rows = fixture()
        # These events even arrive after the final state snapshot at 80s.
        for index, created in enumerate((74900, 75000, 75100)):
            rows["observer-events.jsonl"].append(
                {
                    "schema_version": 1,
                    "timestamp": iso(BASE + 81000),
                    "event_type": "job.observed",
                    "details": {
                        "kubernetes_job_uid": f"late-{index}",
                        "workload_run_id": "test",
                        "creation_time": iso(BASE + created),
                    },
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root / "inputs", rows)
            run_once(root / "inputs", root / "forecast", BASE + 65000, settings())
            result = evaluate(root / "inputs", root / "forecast", until=iso(BASE + 75000))
            self.assertEqual(result["evaluation_cutoff_ms"], BASE + 75000)
            self.assertEqual(
                [(s["bin_start_ms"] - BASE, s["observed_count"]) for s in result["scores"]],
                [(65000, 0), (70000, 1)],
            )
            self.assertEqual(result["uncovered_or_future_bins"], 2)
            self.assertEqual(len(result["cycles"]), 3)
            self.assertEqual(result["gap_sensitivity"][0]["eligible_bins"], 15)

    def test_evaluation_brackets_unaligned_end_and_retains_missing_coverage(self):
        for coverage in ("covered", "gap", "capture_failure", "no_following_state"):
            with self.subTest(coverage=coverage), tempfile.TemporaryDirectory() as temporary:
                rows = fixture()
                for row in rows["cluster-state.jsonl"]:
                    row["timestamp"] = iso(milliseconds(row["timestamp"]) + 100)
                if coverage == "gap":
                    rows["cluster-state.jsonl"] = [
                        r
                        for r in rows["cluster-state.jsonl"]
                        if not BASE + 71100 <= milliseconds(r["timestamp"]) <= BASE + 74100
                    ]
                elif coverage == "capture_failure":
                    rows["observer-events.jsonl"].append(
                        {
                            "schema_version": 1,
                            "timestamp": iso(BASE + 74500),
                            "event_type": "cluster_state.capture_failed",
                            "details": {},
                        }
                    )
                elif coverage == "no_following_state":
                    rows["cluster-state.jsonl"] = [
                        r
                        for r in rows["cluster-state.jsonl"]
                        if milliseconds(r["timestamp"]) < BASE + 75000
                    ]
                root = Path(temporary)
                save_rows(root / "inputs", rows)
                run_once(root / "inputs", root / "forecast", BASE + 65000, settings())
                result = evaluate(root / "inputs", root / "forecast", until=iso(BASE + 75000))
                self.assertEqual(
                    [s["bin_start_ms"] - BASE for s in result["scores"]],
                    [65000, 70000] if coverage == "covered" else [65000],
                )
                # The bin ending at 75s is partial if the experiment ends at 74.9s.
                partial = evaluate(root / "inputs", root / "forecast", until=iso(BASE + 74900))
                self.assertEqual([s["bin_start_ms"] - BASE for s in partial["scores"]], [65000])

    def test_complete_artifacts_reproduce_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root / "inputs", fixture())
            run_once(root / "inputs", root / "one", BASE + 40000, settings())
            boundaries = json.loads((root / "one" / "boundaries.json").read_text())
            run_once(
                root / "inputs",
                root / "two",
                BASE + 40000,
                settings(),
                boundaries=boundaries,
            )
            first = {
                str(p.relative_to(root / "one")): p.read_bytes()
                for p in (root / "one").rglob("*")
                if p.is_file()
            }
            second = {
                str(p.relative_to(root / "two")): p.read_bytes()
                for p in (root / "two").rglob("*")
                if p.is_file()
            }
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
