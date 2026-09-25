"""Regression coverage for finite image batches and their Continuum configuration."""

from __future__ import annotations

import configparser
import io
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from adapter import AdapterService, make_handler  # noqa: E402
import endpoint  # noqa: E402
from configure_cadvisor_scrape import cadvisor_endpoint, patch_operations  # noqa: E402
from endpoint import (  # noqa: E402
    FIDELITY_TOLERANCE_NS,
    PreparedBatch,
    SendResult,
    SenderMeasurements,
    build_batch,
    build_constant_schedule,
    build_periodic_schedule,
    build_schedule_summary,
    emit_planned_schedule,
    execute_schedule,
    prepare_batches,
    resolve_batch_size_range,
    select_images,
)
from events import JsonlEventWriter, new_event  # noqa: E402
from job_submitter import JobRequest, build_job_manifest  # noqa: E402
from storage import BatchStore, BatchValidationError, inspect_image_tar  # noqa: E402
from worker import classify_checksum  # noqa: E402
from resource_manager.kubernetes import kubernetes  # noqa: E402
from infrastructure import infrastructure  # noqa: E402
from infrastructure.qemu import generate as qemu_generate  # noqa: E402


class RecordingSubmitter:
    def __init__(self):
        self.requests: list[JobRequest] = []

    def submit(self, request: JobRequest) -> None:
        self.requests.append(request)


class RaisingParser:
    def error(self, message: str) -> None:
        raise ValueError(message)


class RecordingMachine:
    is_local = True

    def __init__(self):
        self.commands = []

    def process(self, _config, commands, shell=False):
        self.commands = commands
        self.shell = shell
        return [([], []) for _ in commands]


class ImageBatchTests(unittest.TestCase):
    def test_cadvisor_setup_targets_one_endpoint_and_is_idempotent(self):
        monitor = {
            "spec": {
                "endpoints": [
                    {"path": "/metrics", "interval": "30s"},
                    {"path": "/metrics/cadvisor", "interval": "30s"},
                ]
            }
        }
        operations = patch_operations(monitor)
        self.assertEqual(
            {operation["path"] for operation in operations},
            {"/spec/endpoints/1/interval", "/spec/endpoints/1/scrapeTimeout"},
        )
        self.assertEqual(monitor["spec"]["endpoints"][0]["interval"], "30s")
        configured = {
            "spec": {
                "endpoints": [
                    {
                        "path": "/metrics/cadvisor",
                        "interval": "5s",
                        "scrapeTimeout": "1s",
                    }
                ]
            }
        }
        self.assertEqual(patch_operations(configured), [])
        with self.assertRaises(RuntimeError):
            cadvisor_endpoint({"spec": {"endpoints": []}})
        with self.assertRaises(RuntimeError):
            cadvisor_endpoint({"spec": {"endpoints": [{"path": "/metrics/cadvisor"}] * 2}})

    def test_checksum_repetition_preserves_one_output_per_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "one.jpg"
            image.write_bytes(b"content")
            with mock.patch("worker.hashlib.sha256", wraps=__import__("hashlib").sha256) as digest:
                output = classify_checksum([image], repetitions=3)
        self.assertEqual(len(output), 1)
        self.assertEqual(digest.call_count, 3)

    def test_fns_demo_topology_uses_eighteen_pinned_vcpus(self):
        config = configparser.ConfigParser()
        config.read(SOURCE.parents[2] / "configuration" / "fns_demo_v1.cfg")
        infrastructure_config = config["infrastructure"]
        cloud_nodes = infrastructure_config.getint("cloud_nodes")
        cloud_cores = infrastructure_config.getint("cloud_cores")
        endpoint_nodes = infrastructure_config.getint("endpoint_nodes")
        endpoint_cores = infrastructure_config.getint("endpoint_cores")

        self.assertEqual(cloud_nodes, 4)
        self.assertEqual(endpoint_nodes, 1)
        self.assertTrue(infrastructure_config.getboolean("cpu_pin"))
        self.assertEqual(cloud_nodes * cloud_cores + endpoint_nodes * endpoint_cores, 18)

    def test_qemu_topology_generates_unique_cpu_pins_zero_through_seventeen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".tmp").mkdir()
            ssh_key = root / "id_test"
            ssh_key.with_suffix(".pub").write_text("ssh-ed25519 test")
            config = {
                "ssh_key": str(ssh_key),
                "infrastructure": {
                    "cloud_cores": 4,
                    "edge_cores": 1,
                    "endpoint_cores": 2,
                    "cloud_memory": 16,
                    "edge_memory": 1,
                    "endpoint_memory": 4,
                    "cloud_quota": 1.0,
                    "edge_quota": 1.0,
                    "endpoint_quota": 1.0,
                    "cloud_read_speed": 0,
                    "cloud_write_speed": 0,
                    "edge_read_speed": 0,
                    "edge_write_speed": 0,
                    "endpoint_read_speed": 0,
                    "endpoint_write_speed": 0,
                    "cpu_pin": True,
                    "base_path": "/tmp/continuum-test",
                },
            }
            machine = SimpleNamespace(
                cloud_controller_ips=["192.0.2.10"],
                cloud_ips=["192.0.2.11", "192.0.2.12", "192.0.2.13"],
                cloud_controller_names=["cloud0"],
                cloud_names=["cloud1", "cloud2", "cloud3"],
                edge_ips=[],
                edge_names=[],
                endpoint_ips=["192.0.2.20"],
                endpoint_names=["endpoint0"],
                base_ips=[],
                base_names=[],
                process=lambda *_args, **_kwargs: [(["default via 192.168.122.1 dev br0"], [])],
            )
            old_cwd = os.getcwd()
            old_find_bridge = qemu_generate.find_bridge
            try:
                os.chdir(root)
                qemu_generate.find_bridge = lambda *_args: 1
                qemu_generate.start(config, [machine])
            finally:
                qemu_generate.find_bridge = old_find_bridge
                os.chdir(old_cwd)

            pins = []
            for name in ("cloud0", "cloud1", "cloud2", "cloud3", "endpoint0"):
                xml = (root / ".tmp" / f"domain_{name}.xml").read_text()
                pins.extend(
                    int(value) for value in re.findall(r'<vcpupin vcpu="\d+" cpuset="(\d+)"/>', xml)
                )
            self.assertEqual(pins, list(range(18)))

    def test_seeded_image_selection_varies_and_is_reproducible(self):
        images = [Path(f"image-{index}.jpg") for index in range(5)]
        first = random.Random(17)
        second = random.Random(17)
        first_selection = [select_images(images, size, first) for size in (2, 5, 7)]
        second_selection = [select_images(images, size, second) for size in (2, 5, 7)]
        self.assertEqual(first_selection, second_selection)
        self.assertEqual([len(value) for value in first_selection], [2, 5, 7])
        self.assertEqual(len(set(first_selection[1])), 5)

    def test_fixed_and_variable_batch_size_options(self):
        self.assertEqual(
            resolve_batch_size_range(
                SimpleNamespace(batch_size=None, batch_size_min=2, batch_size_max=10)
            ),
            (2, 10),
        )
        self.assertEqual(
            resolve_batch_size_range(
                SimpleNamespace(batch_size=4, batch_size_min=None, batch_size_max=None)
            ),
            (4, 4),
        )
        with self.assertRaises(SystemExit):
            resolve_batch_size_range(
                SimpleNamespace(batch_size=4, batch_size_min=2, batch_size_max=10)
            )

    def test_periodic_schedule_is_seeded_ordered_and_low_peak_low(self):
        first = build_periodic_schedule(
            period_seconds=40,
            minimum_rate_per_second=20,
            peak_rate_per_second=100,
            generator=random.Random(42),
        )
        second = build_periodic_schedule(
            period_seconds=40,
            minimum_rate_per_second=20,
            peak_rate_per_second=100,
            generator=random.Random(42),
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [item.planned_offset_ns for item in first],
            sorted(item.planned_offset_ns for item in first),
        )
        edge_rates = [
            item.expected_rate_per_second
            for item in first
            if item.planned_offset_ns < 10_000_000_000 or item.planned_offset_ns >= 30_000_000_000
        ]
        middle_rates = [
            item.expected_rate_per_second
            for item in first
            if 15_000_000_000 <= item.planned_offset_ns < 25_000_000_000
        ]
        self.assertGreater(sum(middle_rates) / len(middle_rates), sum(edge_rates) / len(edge_rates))
        self.assertLess(first[-1].planned_offset_ns, 40_000_000_000)
        self.assertTrue(all(20 <= item.expected_rate_per_second <= 100 for item in first))

    def test_period_and_cycles_cli_and_environment(self):
        base_args = ["endpoint", "--adapter-url", "http://unused"]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", base_args):
            args = endpoint.parse_args()
            self.assertEqual((args.period_seconds, args.arrival_cycles), (60, 1))
        environment = {"ARRIVAL_PERIOD_SECONDS": "120", "ARRIVAL_CYCLES": "6"}
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            sys, "argv", base_args
        ):
            args = endpoint.parse_args()
            self.assertEqual((args.period_seconds, args.arrival_cycles), (120, 6))
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            sys, "argv", base_args + ["--period-seconds", "30", "--arrival-cycles", "2"]
        ):
            args = endpoint.parse_args()
            self.assertEqual((args.period_seconds, args.arrival_cycles), (30, 2))
        for extra_args, environment in [
            (["--duration-seconds", "720"], {}),
            ([], {"SCHEDULE_DURATION_SECONDS": "720"}),
        ]:
            with self.subTest(extra_args=extra_args, environment=environment), mock.patch.dict(
                os.environ, environment, clear=True
            ), mock.patch.object(sys, "argv", base_args + extra_args), mock.patch.object(
                sys, "stderr", io.StringIO()
            ):
                with self.assertRaises(SystemExit) as error:
                    endpoint.parse_args()
                self.assertEqual(error.exception.code, 2)

    def test_periodic_main_records_and_waits_for_all_cycles(self):
        emitted = []
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "image.jpg").write_bytes(b"checksum test image")
            args = [
                "endpoint",
                "--adapter-url",
                "http://unused",
                "--images",
                temporary,
                "--arrival-pattern",
                "periodic",
                "--period-seconds",
                "120",
                "--arrival-cycles",
                "6",
                "--minimum-rate",
                "0.02",
                "--peak-rate",
                "0.30",
                "--random-seed",
                "44",
            ]
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                sys, "argv", args
            ), mock.patch("endpoint.ThreadSafeEmitter", return_value=emitted.append), mock.patch(
                "endpoint.execute_schedule", return_value=([], None)
            ) as execute, mock.patch(
                "endpoint.build_schedule_summary", return_value={"failed_count": 0}
            ), mock.patch(
                "endpoint.time.monotonic_ns", side_effect=[0, 0, 7_000_000_000]
            ), mock.patch(
                "endpoint.time.sleep"
            ) as sleep:
                endpoint.main()
            ready = next(e["details"] for e in emitted if e["event_type"] == "schedule.ready")
            self.assertEqual(
                ready["profile"],
                {
                    "period_seconds": 120,
                    "arrival_cycles": 6,
                    "duration_seconds": 720,
                    "minimum_rate_per_second": 0.02,
                    "peak_rate_per_second": 0.30,
                },
            )
            self.assertEqual(ready["planned_count"], 141)
            prepared = execute.call_args.args[0]
            self.assertGreater(prepared[-1].arrival.planned_offset_ns, 600_000_000_000)
            self.assertLess(prepared[-1].arrival.planned_offset_ns, 720_000_000_000)
            # Start is at t=2 s; return at t=7 s leaves 715 s of the 720 s run.
            sleep.assert_called_once_with(715)

    def test_schedule_validation_and_fixed_payload_preparation(self):
        self.assertEqual(
            [item.planned_offset_ns for item in build_constant_schedule(3, 0.5)],
            [0, 500_000_000, 1_000_000_000],
        )
        with self.assertRaises(ValueError):
            build_periodic_schedule(
                period_seconds=0,
                minimum_rate_per_second=1,
                peak_rate_per_second=2,
                generator=random.Random(1),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = [root / f"{index}.jpg" for index in range(3)]
            for index, image in enumerate(images):
                image.write_bytes(f"jpeg-{index}".encode())
            arrivals = build_constant_schedule(4, 1)
            first = prepare_batches(arrivals, images, 4, 4, random.Random(7))
            second = prepare_batches(arrivals, images, 4, 4, random.Random(7))

        self.assertTrue(all(batch.image_count == 4 for batch in first))
        self.assertNotEqual(
            [batch.endpoint_batch_id for batch in first],
            [batch.endpoint_batch_id for batch in second],
        )
        self.assertEqual([batch.payload for batch in first], [batch.payload for batch in second])

    def test_open_loop_releases_second_request_while_first_is_blocked(self):
        arrivals = build_constant_schedule(2, 0.01)
        prepared = [
            PreparedBatch(arrival, f"batch-{index}", b"payload", 4, 1)
            for index, arrival in enumerate(arrivals)
        ]
        second_started = threading.Event()
        events = []

        def fake_send(_url, _payload, batch_id, workload_run_id):
            self.assertEqual(workload_run_id, "run-test")
            if batch_id == "batch-0":
                if not second_started.wait(timeout=1):
                    raise AssertionError("second request was coupled to first response")
            else:
                second_started.set()
            return {"request_id": f"request-{batch_id}", "job_name": batch_id}

        start = time.monotonic_ns() + 10_000_000
        results, measurements = execute_schedule(
            prepared,
            adapter_url="http://adapter",
            run_id="run-test",
            max_concurrency=2,
            start_monotonic_ns=start,
            start_wall_ns=time.time_ns() + 10_000_000,
            emit=events.append,
            send=fake_send,
        )

        self.assertTrue(all(result.successful for result in results))
        self.assertEqual(measurements.peak_active, 2)
        self.assertEqual(measurements.peak_queue_depth, 0)
        self.assertEqual(
            [event["event_type"] for event in events].count("batch.send_started"),
            2,
        )

    def test_open_loop_attempts_full_schedule_after_request_failure(self):
        arrivals = build_constant_schedule(3, 0)
        prepared = [
            PreparedBatch(arrival, f"batch-{index}", b"payload", 4, 1)
            for index, arrival in enumerate(arrivals)
        ]
        attempted = []
        events = []

        def partly_failing_send(_url, _payload, batch_id, _workload_run_id):
            attempted.append(batch_id)
            if batch_id == "batch-1":
                raise RuntimeError("deliberate failure")
            return {"request_id": f"request-{batch_id}", "job_name": batch_id}

        now = time.monotonic_ns()
        results, _ = execute_schedule(
            prepared,
            adapter_url="http://adapter",
            run_id="run-test",
            max_concurrency=2,
            start_monotonic_ns=now,
            start_wall_ns=time.time_ns(),
            emit=events.append,
            send=partly_failing_send,
        )

        self.assertEqual(set(attempted), {"batch-0", "batch-1", "batch-2"})
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(not result.successful for result in results), 1)
        self.assertEqual(
            [event["event_type"] for event in events].count("batch.send_failed"),
            1,
        )

    def test_planned_events_and_schedule_fidelity_summary(self):
        arrivals = build_constant_schedule(20, 1)
        prepared = [
            PreparedBatch(arrival, f"batch-{index}", b"payload", 4, 1)
            for index, arrival in enumerate(arrivals)
        ]
        events = []
        emit_planned_schedule(
            prepared, run_id="run-test", start_wall_ns=1_000_000_000, emit=events.append
        )
        self.assertEqual(len(events), 20)
        self.assertTrue(all(event["event_type"] == "schedule.planned" for event in events))
        self.assertEqual(events[3]["details"]["endpoint_batch_id"], "batch-3")

        results = [
            SendResult(
                arrival,
                f"batch-{index}",
                arrival.planned_offset_ns + lag,
                lag,
                True,
            )
            for index, (arrival, lag) in enumerate(
                zip(arrivals, [FIDELITY_TOLERANCE_NS] * 19 + [FIDELITY_TOLERANCE_NS + 1])
            )
        ]
        summary = build_schedule_summary(
            arrivals,
            results,
            measurements=SenderMeasurements(),
        )
        self.assertTrue(summary["fidelity_passed"])
        self.assertEqual(summary["on_time_fraction"], 0.95)
        missing = build_schedule_summary(
            arrivals,
            results[:-1],
            measurements=SenderMeasurements(),
        )
        self.assertFalse(missing["fidelity_passed"])

    def test_events_have_correlatable_wall_clock_timestamp(self):
        event = new_event("test", component="test", run_id="run-test")
        self.assertIsInstance(event["timestamp_unix_ns"], int)
        self.assertGreater(event["timestamp_unix_ns"], 0)

    def test_mahimahi_selection_does_not_require_a_vendored_source_directory(self):
        machine = RecordingMachine()
        config = {
            "infrastructure": {
                "base_path": "/tmp/continuum-test",
                "network_emulation": False,
            }
        }
        infrastructure.create_continuum_dir(config, [machine])
        self.assertEqual(len(machine.commands), 1)
        self.assertNotIn("mahimahi", machine.commands[0])
        self.assertFalse(infrastructure.mahimahi_enabled(config))

        config["infrastructure"].update(
            network_emulation=True,
            wireless_network_preset="5g_nl_kpn_mahimahi",
        )
        infrastructure.create_continuum_dir(config, [machine])
        self.assertEqual(len(machine.commands), 1)
        self.assertNotIn("cp -r mahimahi/.", machine.commands[0])
        self.assertTrue(infrastructure.mahimahi_enabled(config))

    def test_resource_manager_only_allows_one_endpoint_and_three_workers(self):
        config = {
            "infrastructure": {"cloud_nodes": 4, "edge_nodes": 0, "endpoint_nodes": 1},
            "benchmark": {"resource_manager_only": True},
        }
        kubernetes.verify_options(RaisingParser(), config)

        config["benchmark"]["resource_manager_only"] = False
        with self.assertRaises(ValueError):
            kubernetes.verify_options(RaisingParser(), config)

    def test_batch_validation_and_manifest_contract(self):
        """Preserve batch validation, lineage and worker affinity across scheduler profiles."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a.JPEG"
            second = root / "b.jpg"
            first.write_bytes(b"first-jpeg")
            second.write_bytes(b"second-jpeg")
            payload = build_batch([first, second])
            tar_path = root / "batch.tar"
            tar_path.write_bytes(payload)
            self.assertEqual(len(inspect_image_tar(tar_path, max_images=2)), 2)

            request = JobRequest(
                request_id="a" * 32,
                run_id="run-1",
                job_name="image-batch-aaaaaaaaaaaa",
                payload_url="http://adapter/payload",
                result_url="http://adapter/result",
                payload_bytes=len(payload),
                image_count=2,
                workload_run_id="workload-1",
                endpoint_batch_id="b" * 32,
                adapter_accepted_at_unix_ns=123456,
                inference_repetitions=8,
            )
            manifest = build_job_manifest(
                request,
                namespace="fns-demo",
                worker_image="worker@sha256:abc",
                ttl_seconds=3600,
            )
            suspended = build_job_manifest(
                request,
                namespace="fns-demo",
                worker_image="worker:v1",
                ttl_seconds=3600,
                suspend=True,
            )
            self.assertTrue(suspended["spec"]["suspend"])
            self.assertFalse(manifest["spec"]["suspend"])
            self.assertEqual(manifest["kind"], "Job")
            self.assertEqual(manifest["spec"]["backoffLimit"], 0)
            self.assertEqual(manifest["spec"]["ttlSecondsAfterFinished"], 3600)
            self.assertEqual(
                manifest["spec"]["template"]["spec"]["schedulerName"], "default-scheduler"
            )
            packed = build_job_manifest(
                request,
                namespace="fns-demo",
                worker_image="worker@sha256:abc",
                ttl_seconds=3600,
                scheduler_name="fns-packing",
            )["spec"]["template"]["spec"]
            self.assertEqual(packed["schedulerName"], "fns-packing")
            self.assertNotIn("nodeName", packed)
            self.assertNotIn("tolerations", packed)
            self.assertEqual(packed["affinity"], manifest["spec"]["template"]["spec"]["affinity"])
            self.assertEqual(
                manifest["metadata"]["labels"]["continuum.atlarge.nl/request-id"],
                request.request_id,
            )
            self.assertEqual(
                manifest["metadata"]["annotations"]["continuum.atlarge.nl/endpoint-batch-id"],
                "b" * 32,
            )
            environment = {
                item["name"]: item["value"]
                for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            }
            self.assertEqual(environment["ADAPTER_ACCEPTED_AT_UNIX_NS"], "123456")
            self.assertEqual(environment["WORKLOAD_RUN_ID"], "workload-1")
            self.assertEqual(environment["INFERENCE_REPETITIONS"], "8")
            self.assertEqual(
                manifest["metadata"]["annotations"]["continuum.atlarge.nl/inference-repetitions"],
                "8",
            )

    def test_rejects_non_image_tar(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.tar"
            path.write_bytes(b"not a tar")
            with self.assertRaises(BatchValidationError):
                inspect_image_tar(path, max_images=2)

    def test_completed_state_is_not_overwritten_by_submission_race(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sample.JPEG"
            image.write_bytes(b"jpeg-payload")
            payload = build_batch([image])
            store = BatchStore(root / "data")
            request_id = "a" * 32
            store.create(
                request_id,
                payload,
                run_id="run-test",
                image_names=["sample.JPEG"],
                job_name="image-batch-aaaaaaaaaaaa",
            )
            store.record_result(request_id, {"request_id": request_id})
            metadata = store.mark_submitted(
                request_id,
                timings={"job_submission_duration_ns": 123},
                submitted_at_unix_ns=456,
            )
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["submitted_at_unix_ns"], 456)
            self.assertEqual(metadata["adapter_timings_ns"]["job_submission_duration_ns"], 123)

    def test_http_receipt_payload_and_cloud_side_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sample.JPEG"
            image.write_bytes(b"jpeg-payload")
            payload = build_batch([image])
            submitter = RecordingSubmitter()
            service = AdapterService(
                store=BatchStore(root / "data"),
                events=JsonlEventWriter(root / "data" / "events.jsonl"),
                submitter=submitter,
                public_base_url="http://127.0.0.1",
                run_id="run-test",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                request = Request(
                    f"{base_url}/v1/batches",
                    data=payload,
                    method="POST",
                    headers={
                        "Content-Type": "application/x-tar",
                        "X-Continuum-Batch-ID": "b" * 32,
                        "X-Continuum-Workload-Run-ID": "workload-1",
                    },
                )
                with urlopen(request) as response:
                    self.assertEqual(response.status, 202)
                    receipt = json.load(response)
                self.assertEqual(set(receipt), {"request_id", "job_name", "status"})
                self.assertEqual(len(submitter.requests), 1)
                self.assertEqual(submitter.requests[0].workload_run_id, "workload-1")

                request_id = receipt["request_id"]
                with urlopen(f"{base_url}/v1/batches/{request_id}/payload") as response:
                    self.assertEqual(response.read(), payload)

                result = {
                    "request_id": request_id,
                    "outputs": [{"label": "cloud-only"}],
                }
                result_request = Request(
                    f"{base_url}/v1/batches/{request_id}/result",
                    data=json.dumps(result).encode(),
                    method="PUT",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(result_request) as response:
                    self.assertEqual(json.load(response)["status"], "completed")

                with urlopen(f"{base_url}/v1/batches/{request_id}") as response:
                    metadata = json.load(response)
                self.assertEqual(metadata["status"], "completed")
                self.assertEqual(metadata["endpoint_batch_id"], "b" * 32)
                self.assertIn("job_submission_duration_ns", metadata["adapter_timings_ns"])
                self.assertNotIn("outputs", metadata)

                with urlopen(f"{base_url}/v1/metrics") as response:
                    metrics = json.load(response)
                self.assertGreaterEqual(metrics["peak_active_requests"], 1)
                self.assertEqual(metrics["measurements"]["batch_images"]["total"], 1)

                event_types = {
                    json.loads(line)["event_type"]
                    for line in (root / "data" / "events.jsonl").read_text().splitlines()
                }
                self.assertEqual(
                    event_types,
                    {
                        "batch.accepted",
                        "batch.payload_served",
                        "job.submitted",
                        "job.result_recorded",
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
