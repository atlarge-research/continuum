"""HTTP ingress that stores image batches and creates finite Jobs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from events import JsonlEventWriter, new_event
from job_submitter import JobRequest, KubernetesJobSubmitter, LocalJobSubmitter
from storage import (
    BatchStore,
    BatchValidationError,
    inspect_image_tar,
    validate_request_id,
)


class AdapterService:
    def __init__(
        self,
        *,
        store: BatchStore,
        events: JsonlEventWriter,
        submitter: Any,
        public_base_url: str,
        run_id: str,
        max_payload_bytes: int = 50 * 1024 * 1024,
        max_images: int = 64,
    ):
        self.store = store
        self.events = events
        self.submitter = submitter
        self.public_base_url = public_base_url.rstrip("/")
        self.run_id = run_id
        self.max_payload_bytes = max_payload_bytes
        self.max_images = max_images
        self._metrics_lock = threading.Lock()
        self._active_requests = 0
        self._peak_active_requests = 0
        self._request_count = 0
        self._measurements: dict[str, dict[str, int]] = {}

    def request_started(self) -> int:
        """Register an HTTP request and return the current concurrency."""
        with self._metrics_lock:
            self._request_count += 1
            self._active_requests += 1
            self._peak_active_requests = max(
                self._peak_active_requests, self._active_requests
            )
            return self._active_requests

    def request_finished(self, duration_ns: int) -> None:
        with self._metrics_lock:
            self._active_requests -= 1
        self.observe("http_request_duration_ns", duration_ns)

    def observe(self, name: str, value: int) -> None:
        """Record an aggregate count, total, and maximum for one measurement."""
        with self._metrics_lock:
            measurement = self._measurements.setdefault(
                name, {"count": 0, "total": 0, "max": 0}
            )
            measurement["count"] += 1
            measurement["total"] += value
            measurement["max"] = max(measurement["max"], value)

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._metrics_lock:
            measurements = {
                name: {
                    **values,
                    "average": values["total"] // values["count"],
                }
                for name, values in self._measurements.items()
            }
            return {
                "run_id": self.run_id,
                "requests_started": self._request_count,
                "active_requests": self._active_requests,
                "peak_active_requests": self._peak_active_requests,
                "measurements": measurements,
            }

    @staticmethod
    def job_name(request_id: str) -> str:
        return f"image-batch-{request_id[:12]}"

    def accept(
        self,
        payload: bytes,
        *,
        endpoint_batch_id: str | None = None,
        ingress_timings: dict[str, int] | None = None,
        active_requests: int = 1,
    ) -> tuple[dict[str, Any], int]:
        accept_started = time.monotonic_ns()
        accepted_at_unix_ns = time.time_ns()
        if not payload:
            raise BatchValidationError("empty request body")
        if len(payload) > self.max_payload_bytes:
            raise BatchValidationError("payload exceeds configured byte limit")

        request_id = uuid.uuid4().hex
        job_name = self.job_name(request_id)
        validation_started = time.monotonic_ns()
        with tempfile.NamedTemporaryFile(suffix=".tar") as temporary:
            temporary.write(payload)
            temporary.flush()
            image_names = inspect_image_tar(temporary.name, self.max_images)
        validation_duration_ns = time.monotonic_ns() - validation_started

        storage_started = time.monotonic_ns()
        self.store.create(
            request_id,
            payload,
            run_id=self.run_id,
            image_names=image_names,
            job_name=job_name,
            endpoint_batch_id=endpoint_batch_id,
            accepted_at_unix_ns=accepted_at_unix_ns,
        )
        storage_duration_ns = time.monotonic_ns() - storage_started
        common_details = {
            "job_name": job_name,
            "endpoint_batch_id": endpoint_batch_id,
            "payload_bytes": len(payload),
            "image_count": len(image_names),
            "active_requests": active_requests,
            "validation_duration_ns": validation_duration_ns,
            "storage_duration_ns": storage_duration_ns,
            **(ingress_timings or {}),
        }
        self.events.emit(
            new_event(
                "batch.accepted",
                component="adapter",
                run_id=self.run_id,
                request_id=request_id,
                details=common_details,
            )
        )

        request = JobRequest(
            request_id=request_id,
            run_id=self.run_id,
            job_name=job_name,
            payload_url=f"{self.public_base_url}/v1/batches/{request_id}/payload",
            result_url=f"{self.public_base_url}/v1/batches/{request_id}/result",
            payload_bytes=len(payload),
            image_count=len(image_names),
            endpoint_batch_id=endpoint_batch_id,
            adapter_accepted_at_unix_ns=accepted_at_unix_ns,
        )
        submission_started = time.monotonic_ns()
        try:
            self.submitter.submit(request)
        except Exception as exc:
            submission_duration_ns = time.monotonic_ns() - submission_started
            self.observe("job_submission_duration_ns", submission_duration_ns)
            self.store.update(request_id, status="submission_failed", error=str(exc))
            self.events.emit(
                new_event(
                    "job.submission_failed",
                    component="adapter",
                    run_id=self.run_id,
                    request_id=request_id,
                    details={
                        **common_details,
                        "job_submission_duration_ns": submission_duration_ns,
                        "error": str(exc),
                    },
                )
            )
            raise

        job_submitted_at_unix_ns = time.time_ns()
        submission_duration_ns = time.monotonic_ns() - submission_started
        accept_duration_ns = time.monotonic_ns() - accept_started
        timings = {
            **(ingress_timings or {}),
            "validation_duration_ns": validation_duration_ns,
            "storage_duration_ns": storage_duration_ns,
            "job_submission_duration_ns": submission_duration_ns,
            "adapter_accept_duration_ns": accept_duration_ns,
        }
        self.store.mark_submitted(
            request_id,
            timings=timings,
            submitted_at_unix_ns=job_submitted_at_unix_ns,
        )
        self.observe("batch_images", len(image_names))
        self.observe("batch_payload_bytes", len(payload))
        self.observe("validation_duration_ns", validation_duration_ns)
        self.observe("storage_create_duration_ns", storage_duration_ns)
        self.observe("job_submission_duration_ns", submission_duration_ns)
        self.observe("adapter_accept_duration_ns", accept_duration_ns)
        self.events.emit(
            new_event(
                "job.submitted",
                component="adapter",
                run_id=self.run_id,
                request_id=request_id,
                details={**common_details, **timings},
            )
        )
        receipt = {
            "request_id": request_id,
            "job_name": job_name,
            "status": "submitted",
        }
        return receipt, HTTPStatus.ACCEPTED

    def record_result(
        self,
        request_id: str,
        result: dict[str, Any],
        *,
        ingress_timings: dict[str, int] | None = None,
        active_requests: int = 1,
    ) -> dict[str, Any]:
        storage_started = time.monotonic_ns()
        metadata = self.store.record_result(request_id, result)
        storage_duration_ns = time.monotonic_ns() - storage_started
        timings = {
            **(ingress_timings or {}),
            "result_storage_duration_ns": storage_duration_ns,
        }
        for name, value in timings.items():
            self.observe(name, value)
        self.events.emit(
            new_event(
                "job.result_recorded",
                component="adapter",
                run_id=metadata["run_id"],
                request_id=request_id,
                details={
                    "job_name": metadata["job_name"],
                    "image_count": metadata["image_count"],
                    "endpoint_batch_id": metadata.get("endpoint_batch_id"),
                    "active_requests": active_requests,
                    **timings,
                    "worker_timings_ns": result.get("worker_timings_ns", {}),
                },
            )
        )
        return metadata


def make_handler(service: AdapterService):
    class AdapterHandler(BaseHTTPRequestHandler):
        server_version = "ContinuumImageBatchAdapter/1"

        def handle_one_request(self) -> None:
            started = time.monotonic_ns()
            self.active_requests = service.request_started()
            try:
                super().handle_one_request()
            finally:
                service.request_finished(time.monotonic_ns() - started)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def _parts(self) -> list[str]:
            return [part for part in urlsplit(self.path).path.split("/") if part]

        def do_GET(self) -> None:  # pylint: disable=invalid-name
            parts = self._parts()
            if parts == ["healthz"]:
                self._json(HTTPStatus.OK, {"status": "ok", "run_id": service.run_id})
                return
            if parts == ["v1", "metrics"]:
                self._json(HTTPStatus.OK, service.metrics_snapshot())
                return
            if len(parts) not in {3, 4} or parts[:2] != ["v1", "batches"]:
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                request_id = validate_request_id(parts[2])
                if len(parts) == 3:
                    self._json(HTTPStatus.OK, service.store.get(request_id))
                    return
                if parts[3] != "payload":
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                    return
                path = service.store.payload_path(request_id)
                if not path.is_file():
                    raise FileNotFoundError(request_id)
                read_started = time.monotonic_ns()
                body = path.read_bytes()
                storage_read_duration_ns = time.monotonic_ns() - read_started
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-tar")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                write_started = time.monotonic_ns()
                self.wfile.write(body)
                response_write_duration_ns = time.monotonic_ns() - write_started
                service.observe(
                    "payload_storage_read_duration_ns", storage_read_duration_ns
                )
                service.observe(
                    "payload_response_write_duration_ns", response_write_duration_ns
                )
                service.events.emit(
                    new_event(
                        "batch.payload_served",
                        component="adapter",
                        run_id=service.run_id,
                        request_id=request_id,
                        details={
                            "payload_bytes": len(body),
                            "active_requests": self.active_requests,
                            "storage_read_duration_ns": storage_read_duration_ns,
                            "response_write_duration_ns": response_write_duration_ns,
                        },
                    )
                )
            except (BatchValidationError, FileNotFoundError):
                self._error(HTTPStatus.NOT_FOUND, "unknown request ID")

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            if self._parts() != ["v1", "batches"]:
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            if self.headers.get_content_type() != "application/x-tar":
                self._error(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "expected application/x-tar"
                )
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
                return
            if content_length > service.max_payload_bytes:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload too large")
                return
            try:
                endpoint_batch_id = self.headers.get("X-Continuum-Batch-ID")
                if endpoint_batch_id is not None:
                    endpoint_batch_id = validate_request_id(endpoint_batch_id)
                read_started = time.monotonic_ns()
                payload = self.rfile.read(content_length)
                body_read_duration_ns = time.monotonic_ns() - read_started
                service.observe("batch_body_read_duration_ns", body_read_duration_ns)
                receipt, status = service.accept(
                    payload,
                    endpoint_batch_id=endpoint_batch_id,
                    ingress_timings={
                        "body_read_duration_ns": body_read_duration_ns,
                    },
                    active_requests=self.active_requests,
                )
                self._json(status, receipt)
            except BatchValidationError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:  # submission error is retained in cloud metadata
                self._error(
                    HTTPStatus.SERVICE_UNAVAILABLE, f"Job submission failed: {exc}"
                )

        def do_PUT(self) -> None:  # pylint: disable=invalid-name
            parts = self._parts()
            if (
                len(parts) != 4
                or parts[:2] != ["v1", "batches"]
                or parts[3] != "result"
            ):
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                request_id = validate_request_id(parts[2])
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 2 * 1024 * 1024:
                    raise ValueError("invalid result size")
                read_started = time.monotonic_ns()
                body = self.rfile.read(content_length)
                body_read_duration_ns = time.monotonic_ns() - read_started
                parse_started = time.monotonic_ns()
                result = json.loads(body)
                parse_duration_ns = time.monotonic_ns() - parse_started
                if (
                    not isinstance(result, dict)
                    or result.get("request_id") != request_id
                ):
                    raise ValueError("result request ID does not match path")
                metadata = service.record_result(
                    request_id,
                    result,
                    ingress_timings={
                        "result_body_read_duration_ns": body_read_duration_ns,
                        "result_parse_duration_ns": parse_duration_ns,
                    },
                    active_requests=self.active_requests,
                )
                self._json(
                    HTTPStatus.OK,
                    {"request_id": request_id, "status": metadata["status"]},
                )
            except FileNotFoundError:
                self._error(HTTPStatus.NOT_FOUND, "unknown request ID")
            except (BatchValidationError, ValueError, json.JSONDecodeError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"adapter http: {fmt % args}", flush=True)

    return AdapterHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("ADAPTER_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("ADAPTER_PORT", "8080"))
    )
    parser.add_argument("--data-dir", default=os.getenv("DATA_DIR", "/data"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID", "fns-v1-local"))
    parser.add_argument(
        "--submitter",
        choices=("local", "kubernetes"),
        default=os.getenv("SUBMITTER", "kubernetes"),
    )
    parser.add_argument("--public-base-url", default=os.getenv("PUBLIC_BASE_URL"))
    parser.add_argument("--namespace", default=os.getenv("JOB_NAMESPACE", "fns-demo"))
    parser.add_argument(
        "--worker-image",
        default=os.getenv("WORKER_IMAGE", "continuum/image-batch-worker:fns-v1"),
    )
    parser.add_argument(
        "--job-ttl-seconds", type=int, default=int(os.getenv("JOB_TTL_SECONDS", "3600"))
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    public_base_url = args.public_base_url or f"http://127.0.0.1:{args.port}"
    source_dir = Path(__file__).resolve().parent
    if args.submitter == "local":
        submitter = LocalJobSubmitter(source_dir / "worker.py")
    else:
        submitter = KubernetesJobSubmitter(
            namespace=args.namespace,
            worker_image=args.worker_image,
            ttl_seconds=args.job_ttl_seconds,
        )
    data_dir = Path(args.data_dir)
    service = AdapterService(
        store=BatchStore(data_dir),
        events=JsonlEventWriter(data_dir / "events.jsonl"),
        submitter=submitter,
        public_base_url=public_base_url,
        run_id=args.run_id,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))

    def request_shutdown(_signum: int, _frame: Any) -> None:
        # BaseServer.shutdown must run on a different thread than serve_forever.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    print(
        f"adapter listening on {args.host}:{args.port} as run {args.run_id}", flush=True
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("adapter stopped", flush=True)


if __name__ == "__main__":
    main()
