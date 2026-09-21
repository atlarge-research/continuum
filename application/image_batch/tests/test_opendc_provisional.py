"""Provisional inputs require honest scope and native completion/admission evidence."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import shutil
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import (
    file_hashes,
    fixture_tasks,
    prepare,
    verify_inputs,
    write_json,
    adapt_trace,
)
from forecast_trace import parquet_tasks
from opendc_kubernetes import job_manifest, main as kubernetes_main
from opendc_run import execute
import opendc_results
from job_submitter import JobRequest, build_job_manifest
from test_opendc_results import memory_output


def provisional_input(directory):
    """Prepare a hand-auditable two-task provisional case from the memory fixture.

    Args:
        directory (Path): New input directory.

    Returns:
        dict: Case with one two-core modeled worker and two serialized tasks.
    """
    manifest = prepare("memory", directory)
    fixture = json.loads((directory / "fixture.json").read_text())
    case = {
        "initialization_mode": "provisional-trace",
        "candidate": "unchanged",
        "scenario": 0,
        "scope": "complete",
        "cutoff_ms": 100000,
        "horizon_ms": 10000,
        "workers": [
            {
                "node_name": "test-host-0",
                "configured_cores": 3,
                "modeled_cores": 2,
                "memory_mib": 512,
                "frequency_mhz": 2400,
                "idle_power_w": 100,
                "max_power_w": 200,
            }
        ],
        "tasks": [
            {
                "task": task,
                "metadata": {
                    "cohort": "future",
                    "phase": "future",
                    "preserved_assignment": None,
                    "identity": {"task_id": task["id"], "template_job_uid": "synthetic-template"},
                    "original_creation_ms": 100000 + task["submission_time"],
                },
            }
            for task in fixture_tasks(fixture)
        ],
        "omitted_tasks": [],
        "model_exhausted_jobs": [],
    }
    write_json(directory / "case.json", case)
    manifest.update(contract="opendc-provisional-v1", initial_state="provisional-trace")
    manifest["sha256"] = file_hashes(directory, exclude=("manifest.json",))
    write_json(directory / "manifest.json", manifest)
    return case


def provisional_output(directory, early=False, missing=False):
    """Write a native fixture whose host telemetry covers task completion.

    Args:
        directory (Path): Simulator output root to create.
        early (bool): Introduce invalid memory overlap.
        missing (bool): Omit a required completion.
    """
    memory_output(directory, early=early, missing=missing)
    path = directory / "controlled/raw-output/0/seed=0/host.parquet"
    rows = pq.read_table(path).to_pylist()
    rows.append({**rows[0], "timestamp": 15002, "energy_usage": 1800.0})
    pq.write_table(pa.Table.from_pylist(rows), path)


class ProvisionalTests(unittest.TestCase):
    """Catch implicit fallback, false success and missing placement restrictions."""

    def test_prepared_provisional_contract_is_accepted(self):
        """Accept a distinct explicit provisional contract while retaining original tables."""
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "inputs"
            provisional_input(source)
            self.assertEqual(verify_inputs(source)["initial_state"], "provisional-trace")

    def test_fixed_initialization_is_never_silently_approximated(self):
        """Reject requested fixed placement even with internally refreshed hashes."""
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "inputs"
            provisional_input(source)
            manifest = json.loads((source / "manifest.json").read_text())
            manifest["initial_state"] = "fixed-placement"
            write_json(source / "manifest.json", manifest)
            with self.assertRaises(ValueError):
                verify_inputs(source)

    def test_successful_process_still_needs_provisional_native_output(self):
        """A prepared replay launches, but process success alone fails validation."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            provisional_input(root / "inputs")
            runner = root / "runner"
            runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runner.chmod(0o755)
            self.assertEqual(execute(root / "inputs", root / "output", 5, str(runner)), 1)
            record = json.loads((root / "output/execution.json").read_text())
            self.assertEqual(record["contract"], "opendc-provisional-v1")
            self.assertEqual(record["validation"]["status"], "failed")

    def test_native_completion_requires_all_tasks_and_memory_admission(self):
        """Reject missing records and overlapping tasks exceeding worker memory."""
        for early, missing, valid in [
            (False, False, True),
            (True, False, False),
            (False, True, False),
        ]:
            with self.subTest(early=early, missing=missing), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                case = provisional_input(root / "inputs")
                provisional_output(root / "output", early=early, missing=missing)
                if valid:
                    result = opendc_results.validate_provisional_results(root / "output", case)
                    self.assertEqual(result["task_count"], 2)
                    self.assertEqual(result["scope"], "complete")
                else:
                    with self.assertRaises(ValueError):
                        opendc_results.validate_provisional_results(root / "output", case)

    def test_control_plane_runner_keeps_scheduler_and_narrow_toleration(self):
        """The runner can target the tainted control plane without bypassing admission."""
        job = job_manifest(
            "test",
            "runner",
            "continuum/opendc:test",
            "cloudcontrollermatthijs",
            "/var/tmp/fns-opendc-test",
            control_plane=True,
        )
        pod = job["spec"]["template"]["spec"]
        self.assertNotIn("nodeName", pod)
        self.assertEqual(
            pod["tolerations"],
            [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ],
        )

    def test_classifier_excludes_both_control_plane_labels(self):
        """Application jobs must remain worker-only even if taints change."""
        request = JobRequest("r", "run", "job", "http://a/p", "http://a/r", 100, 4)
        pod = build_job_manifest(request, namespace="test", worker_image="w:v1", ttl_seconds=60)[
            "spec"
        ]["template"]["spec"]
        terms = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][
            "nodeSelectorTerms"
        ]
        self.assertEqual(len(terms), 1)
        self.assertEqual(
            {item["key"] for item in terms[0]["matchExpressions"]},
            {"node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"},
        )
        self.assertTrue(
            all(item["operator"] == "DoesNotExist" for item in terms[0]["matchExpressions"])
        )
        self.assertFalse(pod.get("tolerations"))

    def test_final_service_sample_wins_at_duplicate_timestamp(self):
        """A pre-completion sample must not hide a later terminal sample at the same instant."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            case = provisional_input(root / "inputs")
            provisional_output(root / "output")
            path = root / "output/controlled/raw-output/0/seed=0/service.parquet"
            rows = pq.read_table(path).to_pylist()
            rows.insert(-1, {**rows[-1], "tasks_active": 1, "tasks_completed": 1})
            pq.write_table(pa.Table.from_pylist(rows), path)
            self.assertEqual(
                opendc_results.validate_provisional_results(root / "output", case)["status"],
                "passed",
            )

    def test_missing_original_arrival_metadata_is_rejected(self):
        """Executable traces without response-time lineage cannot be prepared inputs."""
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "inputs"
            case = provisional_input(source)
            del case["tasks"][0]["metadata"]["original_creation_ms"]
            write_json(source / "case.json", case)
            manifest = json.loads((source / "manifest.json").read_text())
            manifest["sha256"] = file_hashes(source, exclude=("manifest.json",))
            write_json(source / "manifest.json", manifest)
            with self.assertRaises(ValueError):
                verify_inputs(source)

    def test_manifest_cli_default_can_schedule_on_control_plane(self):
        """Default node selection must carry the matching retained taint toleration."""
        output = io.StringIO()
        with redirect_stdout(output):
            status = kubernetes_main(
                [
                    "manifest",
                    "--namespace",
                    "test",
                    "--job",
                    "test",
                    "--image",
                    "test:v1",
                    "--remote-dir",
                    "/var/tmp/fns-opendc-test",
                ]
            )
        self.assertEqual(status, 0)
        pod = json.loads(output.getvalue())["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "cloudcontrollermatthijs")
        self.assertEqual(pod["tolerations"][0]["key"], "node-role.kubernetes.io/control-plane")

    def test_delayed_first_arrival_restores_cutoff_relative_completion(self):
        """Normalize native execution times without shifting source submission times."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            case = provisional_input(root / "inputs")
            for item in case["tasks"]:
                item["task"]["submission_time"] += 5000
                item["metadata"]["original_creation_ms"] += 5000
            provisional_output(root / "output")
            path = root / "output/controlled/raw-output/0/seed=0/task.parquet"
            rows = pq.read_table(path).to_pylist()
            for row in rows:
                row["submission_time"] += 5000
                row["timestamp_absolute"] = row["timestamp"] + 5000
            pq.write_table(pa.Table.from_pylist(rows), path)
            result = opendc_results.validate_provisional_results(root / "output", case)
            self.assertEqual(result["native_time_origin_ms"], 5000)
            self.assertEqual(result["tasks"][0]["schedule_time"], 5001)
            self.assertEqual(result["tasks"][1]["finish_time"], 20002)

    def test_empty_trace_has_explicit_analytical_idle_result(self):
        """Zero included work needs no fake task or invocation of unsupported native input."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "inputs"
            case = provisional_input(source)
            case["tasks"] = []
            write_json(source / "case.json", case)
            shutil.rmtree(source / "source")
            shutil.rmtree(source / "trace")
            parquet_tasks([], source / "source")
            adapt_trace(source / "source", source / "trace")
            manifest = json.loads((source / "manifest.json").read_text())
            manifest["sha256"] = file_hashes(source, exclude=("manifest.json",))
            write_json(source / "manifest.json", manifest)
            self.assertEqual(execute(source, root / "result", runner="/not/a/real/program"), 0)
            record = json.loads((root / "result/execution.json").read_text())
            self.assertEqual(record["validation"]["kind"], "analytical_empty")
            self.assertFalse(record["process"]["launched"])
            self.assertFalse((root / "result/simulator").exists())

    def test_truncated_host_energy_cannot_be_idle_extended_during_execution(self):
        """Require native host coverage through the final included completion."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            case = provisional_input(root / "input")
            memory_output(root / "output")
            with self.assertRaisesRegex(ValueError, "coverage"):
                opendc_results.validate_provisional_results(root / "output", case)
