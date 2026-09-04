"""Small, dependency-free event contract for demo lineage."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


SCHEMA_VERSION = 1


def new_event(
    event_type: str,
    *,
    component: str,
    run_id: str,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one event shared by endpoint, adapter, and worker."""
    timestamp_unix_ns = time.time_ns()
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.fromtimestamp(
            timestamp_unix_ns / 1_000_000_000, timezone.utc
        ).isoformat(),
        "timestamp_unix_ns": timestamp_unix_ns,
        "component": component,
        "run_id": run_id,
        "details": details or {},
    }
    if request_id is not None:
        event["request_id"] = request_id
    return event


class JsonlEventWriter:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()


def emit_stream(stream: TextIO, event: dict[str, Any]) -> None:
    """Emit a flush-safe JSON event to a component log stream."""
    print(
        json.dumps(event, separators=(",", ":"), sort_keys=True),
        file=stream,
        flush=True,
    )
