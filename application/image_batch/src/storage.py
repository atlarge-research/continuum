"""Durable-enough version-1 storage for accepted batches and results."""

from __future__ import annotations

import json
import os
import re
import tarfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
JPEG_SUFFIXES = {".jpg", ".jpeg"}


class BatchValidationError(ValueError):
    """Raised when a submitted payload violates the batch contract."""


def validate_request_id(request_id: str) -> str:
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise BatchValidationError("invalid request ID")
    return request_id


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise BatchValidationError("invalid workload run ID")
    return run_id


def inspect_image_tar(path: str | Path, max_images: int) -> list[str]:
    """Validate an uncompressed image tar and return its member names."""
    names: list[str] = []
    try:
        with tarfile.open(path, mode="r:") as archive:
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise BatchValidationError("tar contains an unsafe path")
                if not member.isfile():
                    raise BatchValidationError("tar may contain regular files only")
                if member_path.suffix.lower() not in JPEG_SUFFIXES:
                    raise BatchValidationError("tar may contain JPEG files only")
                if member.size <= 0:
                    raise BatchValidationError("image files must not be empty")
                names.append(member.name)
                if len(names) > max_images:
                    raise BatchValidationError(f"batch exceeds {max_images} images")
    except tarfile.TarError as exc:
        raise BatchValidationError("payload is not an uncompressed tar") from exc
    if not names:
        raise BatchValidationError("batch contains no JPEG images")
    return names


class BatchStore:
    """File-backed metadata with atomic replacement and in-process per-request serialization.

    Locks are retained for the lifetime of this single adapter, matching persistent batches.
    Independent requests can flush concurrently; writes for one request remain ordered.
    """

    def __init__(self, data_dir: str | Path):
        """Create the store and its request-lock registry.

        Args:
            data_dir (str or Path): Persistent adapter data directory.
        """
        self.data_dir = Path(data_dir)
        self.batches_dir = self.data_dir / "batches"
        self.batches_dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._request_locks = {}

    def _batch_dir(self, request_id: str) -> Path:
        return self.batches_dir / validate_request_id(request_id)

    def _request_lock(self, request_id: str):
        """Return the stable lock protecting all writes for one validated request.

        Args:
            request_id (str): Batch identifier containing 32 lowercase hexadecimal characters.

        Returns:
            threading.Lock: In-process lock retained while this store exists.

        Raises:
            BatchValidationError: The request identifier is invalid.
        """
        validate_request_id(request_id)
        with self._locks_guard:
            if request_id not in self._request_locks:
                self._request_locks[request_id] = threading.Lock()
            return self._request_locks[request_id]

    def payload_path(self, request_id: str) -> Path:
        return self._batch_dir(request_id) / "payload.tar"

    def result_path(self, request_id: str) -> Path:
        return self._batch_dir(request_id) / "result.json"

    def create(
        self,
        request_id: str,
        payload: bytes,
        *,
        run_id: str,
        workload_run_id: str | None = None,
        image_names: list[str],
        job_name: str,
        endpoint_batch_id: str | None = None,
        accepted_at_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Persist a new payload and its acceptance metadata before returning a receipt.

        Args:
            request_id (str): Valid unique batch identifier.
            payload (bytes): Exact uploaded archive bytes.
            run_id (str): Adapter capture identity.
            workload_run_id (str or None): Sender identity, defaulting to run_id.
            image_names (list[str]): Validated archive member names.
            job_name (str): Assigned Kubernetes Job name.
            endpoint_batch_id (str or None): Sender batch identity.
            accepted_at_unix_ns (int or None): Acceptance time, defaulting to the current clock.

        Returns:
            dict[str, Any]: Durably written initial metadata.

        Raises:
            BatchValidationError: The request identifier is invalid.
            FileExistsError: This request already has a batch directory.
            OSError: A payload or metadata write fails.
        """
        batch_dir = self._batch_dir(request_id)
        accepted_at_unix_ns = accepted_at_unix_ns or time.time_ns()
        with self._request_lock(request_id):
            batch_dir.mkdir(parents=False, exist_ok=False)
            self._atomic_write(batch_dir / "payload.tar", payload)
            metadata = {
                "schema_version": 1,
                "request_id": request_id,
                "run_id": run_id,
                "workload_run_id": workload_run_id or run_id,
                "job_name": job_name,
                "endpoint_batch_id": endpoint_batch_id,
                "status": "accepted",
                "accepted_at": datetime.fromtimestamp(
                    accepted_at_unix_ns / 1_000_000_000, timezone.utc
                ).isoformat(),
                "accepted_at_unix_ns": accepted_at_unix_ns,
                "payload_bytes": len(payload),
                "image_count": len(image_names),
                "image_names": image_names,
            }
            self._write_json(batch_dir / "metadata.json", metadata)
            return metadata

    def get(self, request_id: str) -> dict[str, Any]:
        path = self._batch_dir(request_id) / "metadata.json"
        if not path.is_file():
            raise FileNotFoundError(request_id)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def update(self, request_id: str, **changes: Any) -> dict[str, Any]:
        """Apply metadata changes without losing another update for the same request.

        Args:
            request_id (str): Valid batch identifier.
            **changes (Any): Metadata fields to replace.

        Returns:
            dict[str, Any]: Updated metadata after its atomic replacement.

        Raises:
            BatchValidationError: The identifier is invalid.
            FileNotFoundError: No accepted metadata exists for the request.
            OSError: The metadata write fails.
        """
        with self._request_lock(request_id):
            metadata = self.get(request_id)
            metadata.update(changes)
            self._write_json(self._batch_dir(request_id) / "metadata.json", metadata)
            return metadata

    def mark_submitted(
        self,
        request_id: str,
        *,
        timings: dict[str, int] | None = None,
        submitted_at_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Mark submission without overwriting a concurrent terminal result.

        Args:
            request_id (str): Valid batch identifier.
            timings (dict[str, int] or None): Adapter stage durations in nanoseconds.
            submitted_at_unix_ns (int or None): Submission time, defaulting to the current clock.

        Returns:
            dict[str, Any]: Metadata retaining completed status if already terminal.

        Raises:
            BatchValidationError: The identifier is invalid.
            FileNotFoundError: No accepted metadata exists for the request.
            OSError: The metadata write fails.
        """
        submitted_at_unix_ns = submitted_at_unix_ns or time.time_ns()
        with self._request_lock(request_id):
            metadata = self.get(request_id)
            metadata["submitted_at"] = datetime.fromtimestamp(
                submitted_at_unix_ns / 1_000_000_000, timezone.utc
            ).isoformat()
            metadata["submitted_at_unix_ns"] = submitted_at_unix_ns
            if timings is not None:
                metadata["adapter_timings_ns"] = timings
            if metadata["status"] != "completed":
                metadata["status"] = "submitted"
            self._write_json(self._batch_dir(request_id) / "metadata.json", metadata)
            return metadata

    def record_result(self, request_id: str, result: dict[str, Any]) -> dict[str, Any]:
        """Persist a result and mark its batch completed under the same request lock.

        Args:
            request_id (str): Valid batch identifier.
            result (dict[str, Any]): Worker result to persist unchanged.

        Returns:
            dict[str, Any]: Completed metadata, including the durable result path.

        Raises:
            BatchValidationError: The identifier is invalid.
            FileNotFoundError: No accepted metadata exists for the request.
            OSError: A result or metadata write fails.
        """
        completed_at_unix_ns = time.time_ns()
        with self._request_lock(request_id):
            batch_dir = self._batch_dir(request_id)
            if not (batch_dir / "metadata.json").is_file():
                raise FileNotFoundError(request_id)
            self._write_json(batch_dir / "result.json", result)
            with (batch_dir / "metadata.json").open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            metadata.update(
                status="completed",
                completed_at=datetime.fromtimestamp(
                    completed_at_unix_ns / 1_000_000_000, timezone.utc
                ).isoformat(),
                completed_at_unix_ns=completed_at_unix_ns,
                result_path=str(batch_dir / "result.json"),
            )
            self._write_json(batch_dir / "metadata.json", metadata)
            return metadata

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)

    @classmethod
    def _write_json(cls, path: Path, value: dict[str, Any]) -> None:
        cls._atomic_write(
            path,
            (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
