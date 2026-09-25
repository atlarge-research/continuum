"""Locked, fsynced controller intents and recovery of uncertain API outcomes."""

import copy
import fcntl
import json
import os
from pathlib import Path
import time
import uuid


class Journal:
    """Own an exclusive controller journal until explicitly closed.

    Args:
        path (Path): Append-only JSONL path within the run's evidence directory.

    Raises:
        BlockingIOError: Another controller process owns the same journal.
        ValueError: A complete journal record is malformed or its sequence is inconsistent.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.stream = self.path.open("a+b")
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.stream.seek(0)
            original = self.stream.read()
            complete = original
            if original and not original.endswith(b"\n"):
                preserved = self.path.with_name(f"journal-before-recovery-{uuid.uuid4().hex}.jsonl")
                with preserved.open("xb") as archive:
                    archive.write(original)
                    archive.flush()
                    os.fsync(archive.fileno())
                complete = original[: original.rfind(b"\n") + 1]
                self.stream.seek(0)
                self.stream.truncate(len(complete))
                self.stream.flush()
                os.fsync(self.stream.fileno())
            self.records = [json.loads(line) for line in complete.splitlines()]
            if any(record.get("sequence") != index for index, record in enumerate(self.records)):
                raise ValueError("journal sequence is inconsistent")
            self.stream.seek(0, os.SEEK_END)
        except Exception:
            self.stream.close()
            raise

    def append(self, event, **payload):
        """Publish one complete durable record before the caller performs dependent I/O.

        Args:
            event (str): Event type, such as action.request or action.result.
            payload (dict): JSON-compatible audit fields without nonfinite measurements.

        Returns:
            dict: The exact appended record, including sequence and availability timestamp.
        """
        record = {
            **copy.deepcopy(payload),
            "event": event,
            "sequence": len(self.records),
            "recorded_at_ns": time.time_ns(),
        }
        data = (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode()
        self.stream.write(data)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.records.append(record)
        return record

    def pending_action(self):
        """Find the single durable API intent without a recorded terminal observation.

        Returns:
            dict or None: Unresolved intent to reconcile against fresh state, never retry.

        Raises:
            ValueError: The journal contains multiple unresolved action intents.
        """
        finished = {
            record["action_id"] for record in self.records if record["event"] == "action.result"
        }
        pending = [
            record
            for record in self.records
            if record["event"] == "action.request" and record["action_id"] not in finished
        ]
        if len(pending) > 1:
            raise ValueError("multiple unresolved action intents")
        return copy.deepcopy(pending[0]) if pending else None

    def history(self):
        """Rebuild proposal history and cooldown even when the final cycle record is absent.

        Returns:
            dict: Last recorded proposal state and acknowledged/reconciled action time.
        """
        history = {}
        for record in self.records:
            if record["event"] == "cycle.end":
                history = copy.deepcopy(record["history"])
            elif record["event"] == "action.result" and record.get("last_action_at") is not None:
                history["last_action_at"] = record["last_action_at"]
        return history

    def close(self):
        """Release exclusive ownership after all dependent controller work stops."""
        self.stream.close()
