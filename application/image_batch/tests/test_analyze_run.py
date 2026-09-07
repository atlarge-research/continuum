"""Small hand-calculated evidence fixtures, separate from the runtime observer."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import copy
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analyze_run import analyze, compact_alignment, main, range_series, read_jsonl


BASE = 1_780_000_000


def stamp(offset):
    return datetime.fromtimestamp(BASE + offset, timezone.utc).isoformat()


def fixture():
    def event(kind, details, **extra):
        return dict(
            schema_version=1,
            run_id="run-a",
            component="endpoint",
            event_type=kind,
            details=details,
            **extra,
        )

    ready = dict(
        planned_count=2,
        schedule_start_timestamp_unix_ns=BASE * 10**9,
        schedule_start_timestamp=stamp(0),
        profile={"duration_seconds": 5},
    )
    records = [event("schedule.ready", ready)]
    tasks, samples = [], []
    entries = []
    for i in range(2):
        planned = i * 10**9
        timing = dict(
            batch_index=i,
            endpoint_batch_id=f"batch-{i}",
            planned_offset_ns=planned,
            planned_timestamp_unix_ns=BASE * 10**9 + planned,
        )
        records.append(event("schedule.planned", timing.copy()))
        timing.update(
            actual_send_offset_ns=planned + 1_000_000,
            schedule_lag_ns=1_000_000,
            actual_send_timestamp_unix_ns=BASE * 10**9 + planned + 1_000_000,
        )
        records.append(event("batch.send_started", timing.copy()))
        records.append(
            event(
                "batch.receipt_received", dict(timing, job_name=f"job-{i}"), request_id=f"req-{i}"
            )
        )
        source = dict(
            kubernetes_job_uid=f"uid-{i}",
            job_name=f"job-{i}",
            request_id=f"req-{i}",
            endpoint_batch_id=f"batch-{i}",
            workload_run_id="run-a",
            terminal_status="Complete",
            execution_start_time=stamp(2 + i),
            execution_completion_time=stamp(8 + i),
            completion_time=stamp(10 + i),
            resource_sample_count=2 - i,
        )
        tasks.append(
            dict(
                schema_version=1,
                source=source,
                task=dict(submission_time=stamp(1 + i), duration=6000),
            )
        )
        entries.append(
            dict(
                kubernetes_job_uid=f"uid-{i}",
                job_name=f"job-{i}",
                request_id=f"req-{i}",
                endpoint_batch_id=f"batch-{i}",
                workload_run_id="run-a",
                creation_time=stamp(1 + i),
                node_name="worker-1",
                requested_cpu_count=0.5,
            )
        )
    records.append(
        event(
            "schedule.summary",
            dict(
                planned_count=2,
                attempted_count=2,
                successful_count=2,
                failed_count=0,
                on_time_count=2,
                fidelity_tolerance_ns=250_000_000,
                fidelity_required_fraction=0.95,
                fidelity_passed=True,
            ),
        )
    )
    for uid, t, cpu in [("uid-0", 3, 0.75), ("uid-0", 6, 0.5), ("uid-1", 5, 0.25)]:
        samples.append(
            dict(
                schema_version=1,
                job_uid=uid,
                job_name=uid.replace("uid", "job"),
                capture_time=stamp(t),
                observation_time=stamp(t + 1),
                cpu_usage_cores=cpu,
                memory_usage_mb=64,
            )
        )
    states = []
    for t in range(14):
        queued = [copy.deepcopy(entries[i]) for i in range(2) if 1 + i <= t < 2 + i]
        active = [copy.deepcopy(entries[i]) for i in range(2) if 2 + i <= t < 10 + i]
        states.append(
            dict(
                schema_version=1,
                timestamp=stamp(t),
                message_type="cluster_state",
                jobs=dict(queued=queued, active=active),
                counts=dict(queued_jobs=len(queued), active_jobs=len(active), workers=1),
                workers=[
                    dict(
                        node_name="worker-1", allocatable_cpu_count=4, ready=True, schedulable=True
                    )
                ],
            )
        )
    return records, {
        "workload": tasks,
        "resource-snapshots": samples,
        "cluster-state": states,
        "observer-events": [],
    }


class RunAnalysisTests(unittest.TestCase):
    def test_hand_calculated_timing_capacity_and_coverage(self):
        records, evidence = fixture()
        result = analyze(records, evidence, "run-a", 2)
        s = result["summary"]
        self.assertEqual(s["queue_seconds"]["median"], 1)
        self.assertEqual(s["execution_seconds"]["median"], 6)
        self.assertEqual(s["fidelity"]["lag_ms"]["max"], 1)
        self.assertEqual(s["coverage"]["min"], 1)
        self.assertEqual(s["coverage"]["median"], 1.5)
        self.assertEqual(s["coverage"]["at_least_2_percent"], 50)
        self.assertEqual(s["coverage"]["at_least_3_percent"], 0)
        self.assertEqual(s["pressure_peaks"]["active_requested_cpu"], 1)
        self.assertEqual(result["jobs"][0]["worker"], "worker-1")
        self.assertEqual(result["pressure"][0]["allocatable_worker_cpu"], 4)

    def test_cpu_missing_partial_expired_and_finished_are_distinct(self):
        records, evidence = fixture()
        points = {p["time_seconds"]: p for p in analyze(records, evidence, "run-a", 2)["pressure"]}
        self.assertIsNone(points[2]["observed_workload_cpu"])
        self.assertEqual(points[3]["observed_workload_cpu"], 0.75)  # Not clamped to .5 CPU request.
        self.assertFalse(points[3]["cpu_coverage_complete"])
        self.assertEqual(points[5]["observed_workload_cpu"], 1)
        self.assertTrue(points[5]["cpu_coverage_complete"])
        self.assertIsNone(
            points[8]["observed_workload_cpu"]
        )  # uid-0 finished; uid-1 sample expired.
        self.assertEqual(points[9]["observed_workload_cpu"], 0)  # No executing containers.

    def test_mixed_run_filtering_uses_workload_lineage(self):
        records, evidence = fixture()
        other = copy.deepcopy(evidence["workload"][0])
        other["source"].update(
            workload_run_id="other", request_id="other", kubernetes_job_uid="other"
        )
        evidence["workload"].append(other)
        self.assertEqual(analyze(records, evidence, "run-a", 10)["summary"]["completed_jobs"], 2)

    def test_inconsistent_and_legacy_evidence_is_rejected(self):
        for mutation, message in [
            (
                lambda r, e: e["workload"].append(copy.deepcopy(e["workload"][0])),
                "duplicate Job UID",
            ),
            (
                lambda r, e: e["workload"][0]["source"].pop("execution_start_time"),
                "missing worker execution",
            ),
            (
                lambda r, e: e["workload"][0]["source"].pop("workload_run_id"),
                "workload_run_id missing",
            ),
            (
                lambda r, e: e["workload"][0]["source"].update(execution_completion_time=stamp(0)),
                "lifecycle",
            ),
            (lambda r, e: e["resource-snapshots"].pop(), "samples .* disagree"),
            (
                lambda r, e: e["resource-snapshots"].append(
                    copy.deepcopy(e["resource-snapshots"][0])
                ),
                "duplicate Job resource",
            ),
            (
                lambda r, e: e["resource-snapshots"][0].update(cpu_usage_cores=float("nan")),
                "invalid nonnegative",
            ),
            (
                lambda r, e: e["workload"][0]["source"].update(endpoint_batch_id="wrong"),
                "lineage disagrees",
            ),
            (
                lambda r, e: e["cluster-state"][2]["counts"].update(active_jobs=20),
                "counts disagree",
            ),
            (lambda r, e: r[-1]["details"].update(attempted_count=1), "summary counts disagree"),
            (lambda r, e: r[2]["details"].update(schedule_lag_ns=0), "start/lag timestamps"),
        ]:
            with self.subTest(message=message):
                records, evidence = fixture()
                mutation(records, evidence)
                with self.assertRaisesRegex(ValueError, message):
                    analyze(records, evidence, "run-a", 10)

    def test_incomplete_run_is_reported_without_inventing_duration(self):
        records, evidence = fixture()
        evidence["workload"].pop()
        records.pop()  # Endpoint summary not captured.
        result = analyze(records, evidence, "run-a", 10)
        self.assertEqual(result["summary"]["completed_jobs"], 1)
        self.assertEqual(result["summary"]["unresolved_accepted_jobs"], 1)
        self.assertTrue(any("Missing schedule.summary" in w for w in result["summary"]["warnings"]))
        self.assertTrue(any(p["unresolved_active_jobs"] for p in result["pressure"]))

    def test_zero_samples_and_missing_worker_remain_visible(self):
        records, evidence = fixture()
        evidence["resource-snapshots"] = []
        for task in evidence["workload"]:
            task["source"]["resource_sample_count"] = 0
        for state in evidence["cluster-state"]:
            for group in state["jobs"].values():
                for job in group:
                    job["node_name"] = None
        result = analyze(records, evidence, "run-a", 10)
        self.assertEqual(result["summary"]["coverage"]["histogram"], {0: 2})
        self.assertTrue(any("Worker assignment" in w for w in result["summary"]["warnings"]))
        self.assertTrue(
            all(
                p["observed_workload_cpu"] is None
                for p in result["pressure"]
                if p["executing_jobs"]
            )
        )

    def test_state_gaps_and_collection_failures_are_reported(self):
        records, evidence = fixture()
        evidence["cluster-state"] = evidence["cluster-state"][::4]
        evidence["observer-events"] = [
            dict(
                timestamp=stamp(4),
                event_type="prometheus.sample_failed",
                details={"error": "timeout"},
            )
        ]
        result = analyze(records, evidence, "run-a", 10)
        self.assertTrue(result["gaps"])
        self.assertEqual(result["summary"]["diagnostics"]["prometheus.sample_failed"], 1)

    def test_historical_terminal_pods_are_excluded_without_rewriting_evidence(self):
        records, evidence = fixture()
        baseline = analyze(records, evidence, "run-a", 10)
        state = evidence["cluster-state"][9]
        for entry in state["jobs"]["active"]:
            entry["pod_phase"] = "Succeeded"
        state["jobs"]["queued"] = [state["jobs"]["active"].pop(0)]
        state["counts"].update(queued_jobs=1, active_jobs=1)
        original = copy.deepcopy(evidence)
        result = analyze(records, evidence, "run-a", 10)
        point = next(p for p in result["pressure"] if p["time_seconds"] == 9)
        self.assertEqual(point["queued_jobs"], 0)
        self.assertEqual(point["active_jobs"], 0)
        self.assertEqual(point["active_requested_cpu"], 0)
        self.assertEqual(
            result["summary"]["pressure_corrections"],
            {
                "excluded_terminal_pod_observations": 2,
                "affected_jobs": 2,
            },
        )
        self.assertEqual(evidence, original)
        self.assertEqual(result["summary"]["warnings"], baseline["summary"]["warnings"])
        self.assertEqual(result["summary"]["completed_jobs"], 2)
        # A corrected capture yields identical pressure without applying a correction.
        state["jobs"] = dict(queued=[], active=[])
        state["counts"].update(queued_jobs=0, active_jobs=0)
        corrected = analyze(records, evidence, "run-a", 10)
        self.assertEqual(corrected["pressure"], result["pressure"])
        self.assertEqual(corrected["summary"]["pressure_corrections"]["affected_jobs"], 0)

    def test_jsonl_errors_include_file_and_line_and_accept_log_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "endpoint.jsonl"
            path.write_text('2026-09-05T21:00:00Z {"schema_version":1}\n')
            self.assertEqual(read_jsonl(path), [{"schema_version": 1}])
            for value in ['{"schema_version":1}', "not JSON\n", '{"schema_version":99}\n']:
                path.write_text(value)
                with self.assertRaisesRegex(ValueError, "endpoint.jsonl:1"):
                    read_jsonl(path)

    def test_cli_generates_real_artifacts_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records, evidence = fixture()
            for name, rows in {"endpoint": records, **evidence}.items():
                (root / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            args = [
                "--endpoint-log",
                str(root / "endpoint.jsonl"),
                "--observer-dir",
                str(root),
                "--output-dir",
                str(root / "report"),
            ]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(args), 0)
                self.assertNotIn("UserWarning", errors.getvalue())
                self.assertEqual(main(args), 2)
            self.assertTrue((root / "report/report.pdf").read_bytes().startswith(b"%PDF"))
            self.assertTrue((root / "report/pressure.png").read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(len(list((root / "report").glob("*.png"))), 6)
            summary = json.loads((root / "report/summary.json").read_text())
            self.assertEqual(len(summary["provenance"]["inputs"]), 5)
            (root / "workload.jsonl").unlink()
            args[-1] = str(root / "missing")
            with redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(args), 2)
            self.assertIn("workload.jsonl", errors.getvalue())
            self.assertFalse((root / "missing").exists())


class ComparisonTests(unittest.TestCase):
    def reports(self):
        records, evidence = fixture()
        first = analyze(records, evidence, "run-a", 10)
        return [first, copy.deepcopy(first), copy.deepcopy(first)]

    def test_matching_plans_are_required(self):
        reports = self.reports()
        reports[1]["arrivals"][0]["planned_seconds"] += 0.1
        with self.assertRaisesRegex(ValueError, "matching batch indices and planned offsets"):
            compact_alignment(reports)

    def test_common_grid_does_not_bridge_missing_captures(self):
        reports = self.reports()
        reports[1]["pressure"] = [
            p for p in reports[1]["pressure"] if p["time_seconds"] not in (3, 4, 5, 6)
        ]
        reports[2]["pressure"] = reports[2]["pressure"][:-2]
        grid, aligned, _ = compact_alignment(reports)
        self.assertEqual(grid[-1], reports[2]["pressure"][-1]["time_seconds"])
        self.assertIsNone(aligned[1][grid.index(6)])
        median, low, high = range_series(aligned, "active_jobs")
        self.assertTrue(math.isnan(median[grid.index(6)]))
        self.assertTrue(math.isnan(low[grid.index(6)]))
        self.assertTrue(math.isnan(high[grid.index(6)]))

    def test_observed_range_is_not_a_confidence_interval(self):
        aligned = [[{"value": value}] for value in (1, 3, 8)]
        self.assertEqual(range_series(aligned, "value"), ([3], [1], [8]))

    def test_representative_is_first_complete_run(self):
        reports = self.reports()
        reports[0]["summary"]["completed_jobs"] = 1
        _, _, representative = compact_alignment(reports)
        self.assertEqual(representative, 1)
        for report in reports:
            report["summary"]["completed_jobs"] = 0
        with self.assertRaisesRegex(ValueError, "at least one complete run"):
            compact_alignment(reports)


if __name__ == "__main__":
    unittest.main()
