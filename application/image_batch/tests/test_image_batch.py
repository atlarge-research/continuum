from __future__ import annotations

import json
import random
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from adapter import AdapterService, make_handler  # noqa: E402
from endpoint import build_batch, resolve_batch_size_range, select_images  # noqa: E402
from events import JsonlEventWriter, new_event  # noqa: E402
from job_submitter import JobRequest, build_job_manifest  # noqa: E402
from storage import BatchStore, BatchValidationError, inspect_image_tar  # noqa: E402
from resource_manager.kubernetes import kubernetes  # noqa: E402
from infrastructure import infrastructure  # noqa: E402


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

    def test_events_have_correlatable_wall_clock_timestamp(self):
        event = new_event("test", component="test", run_id="run-test")
        self.assertIsInstance(event["timestamp_unix_ns"], int)
        self.assertGreater(event["timestamp_unix_ns"], 0)

    def test_mahimahi_copy_is_gated_by_network_configuration(self):
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
        self.assertEqual(len(machine.commands), 2)
        self.assertIn("cp -r mahimahi/.", machine.commands[1])
        self.assertTrue(infrastructure.mahimahi_enabled(config))

    def test_resource_manager_only_allows_one_endpoint_and_two_workers(self):
        config = {
            "infrastructure": {"cloud_nodes": 3, "edge_nodes": 0, "endpoint_nodes": 1},
            "benchmark": {"resource_manager_only": True},
        }
        kubernetes.verify_options(RaisingParser(), config)

        config["benchmark"]["resource_manager_only"] = False
        with self.assertRaises(ValueError):
            kubernetes.verify_options(RaisingParser(), config)

    def test_batch_validation_and_manifest_contract(self):
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
                endpoint_batch_id="b" * 32,
                adapter_accepted_at_unix_ns=123456,
            )
            manifest = build_job_manifest(
                request,
                namespace="fns-demo",
                worker_image="worker@sha256:abc",
                ttl_seconds=3600,
            )
            self.assertEqual(manifest["kind"], "Job")
            self.assertEqual(manifest["spec"]["backoffLimit"], 0)
            self.assertEqual(manifest["spec"]["ttlSecondsAfterFinished"], 3600)
            self.assertEqual(
                manifest["metadata"]["labels"]["continuum.atlarge.nl/request-id"],
                request.request_id,
            )
            self.assertEqual(
                manifest["metadata"]["annotations"][
                    "continuum.atlarge.nl/endpoint-batch-id"
                ],
                "b" * 32,
            )
            environment = {
                item["name"]: item["value"]
                for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            }
            self.assertEqual(environment["ADAPTER_ACCEPTED_AT_UNIX_NS"], "123456")

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
            self.assertEqual(
                metadata["adapter_timings_ns"]["job_submission_duration_ns"], 123
            )

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
                    },
                )
                with urlopen(request) as response:
                    self.assertEqual(response.status, 202)
                    receipt = json.load(response)
                self.assertEqual(set(receipt), {"request_id", "job_name", "status"})
                self.assertEqual(len(submitter.requests), 1)

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
                self.assertIn(
                    "job_submission_duration_ns", metadata["adapter_timings_ns"]
                )
                self.assertNotIn("outputs", metadata)

                with urlopen(f"{base_url}/v1/metrics") as response:
                    metrics = json.load(response)
                self.assertGreaterEqual(metrics["peak_active_requests"], 1)
                self.assertEqual(metrics["measurements"]["batch_images"]["total"], 1)

                event_types = {
                    json.loads(line)["event_type"]
                    for line in (root / "data" / "events.jsonl")
                    .read_text()
                    .splitlines()
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
