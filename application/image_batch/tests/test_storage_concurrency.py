"""Unrelated durable batches progress independently while one batch stays serialized."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from storage import BatchStore


def create_batch(store, identity):
    """Create one literal batch without adapter or HTTP timing assumptions.

    Args:
        store (BatchStore): Temporary durable store.
        identity (str): Valid unique request identity.

    Returns:
        dict: Initial accepted metadata.
    """
    return store.create(identity, b"payload", run_id="test", image_names=["a.jpeg"], job_name="job")


class StoreConcurrencyTests(unittest.TestCase):
    """A blocked fsync/write for one request cannot serialize every other request."""

    def test_stalled_payload_does_not_block_an_unrelated_batch(self):
        """A second receipt can progress while another request's payload write is held."""
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            store = BatchStore(temporary)
            # Hold the durable write boundary while exercising real store locking.
            original = BatchStore._atomic_write  # pylint: disable=protected-access

            def write(path, content):
                """Hold only the first batch's payload, leaving actual durable writes intact.

                Args:
                    path (Path): Target batch file.
                    content (bytes): Exact original file bytes.
                """
                if path.parent.name == "a" * 32 and path.name == "payload.tar":
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError("test did not release first write")
                original(path, content)
                if path.parent.name == "b" * 32 and path.name == "metadata.json":
                    finished.set()

            with patch.object(BatchStore, "_atomic_write", side_effect=write), ThreadPoolExecutor(
                2
            ) as pool:
                first = pool.submit(create_batch, store, "a" * 32)
                self.assertTrue(entered.wait(1))
                second = pool.submit(create_batch, store, "b" * 32)
                try:
                    self.assertTrue(
                        finished.wait(0.5), "unrelated batch waits for global store lock"
                    )
                finally:
                    release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
            self.assertEqual(store.get("a" * 32)["status"], "accepted")
            self.assertEqual(store.get("b" * 32)["status"], "accepted")

    def test_stalled_metadata_update_does_not_block_an_unrelated_batch(self):
        """Slow updates also serialize only their own request rather than the whole store."""
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            store = BatchStore(temporary)
            for identity in ("a" * 32, "b" * 32):
                create_batch(store, identity)
            # Hold the durable write boundary while exercising real store locking.
            original = BatchStore._atomic_write  # pylint: disable=protected-access

            def write(path, content):
                """Hold one request's update and signal another completed durable update.

                Args:
                    path (Path): Metadata target.
                    content (bytes): Exact updated bytes.
                """
                if path.parent.name == "a" * 32:
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError("test did not release metadata write")
                original(path, content)
                if path.parent.name == "b" * 32:
                    finished.set()

            with patch.object(BatchStore, "_atomic_write", side_effect=write), ThreadPoolExecutor(
                2
            ) as pool:
                first = pool.submit(store.update, "a" * 32, note="first")
                self.assertTrue(entered.wait(1))
                second = pool.submit(store.update, "b" * 32, note="second")
                try:
                    self.assertTrue(
                        finished.wait(0.5), "unrelated update waits for global store lock"
                    )
                finally:
                    release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
            self.assertEqual(store.get("b" * 32)["note"], "second")

    def test_same_batch_submission_and_completion_do_not_lose_metadata(self):
        """A result waits for that batch's submission update, then retains terminal status."""
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            store = BatchStore(temporary)
            create_batch(store, "a" * 32)
            # Hold the durable write boundary while exercising real store locking.
            original = BatchStore._atomic_write  # pylint: disable=protected-access

            def write(path, content):
                """Hold the first submission metadata replacement to expose lost updates.

                Args:
                    path (Path): Target file.
                    content (bytes): Original replacement bytes.
                """
                if path.name == "metadata.json" and b'"submitted"' in content:
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError("test did not release submission write")
                original(path, content)
                if path.name == "result.json":
                    completed.set()

            with patch.object(BatchStore, "_atomic_write", side_effect=write), ThreadPoolExecutor(
                2
            ) as pool:
                first = pool.submit(store.mark_submitted, "a" * 32, submitted_at_unix_ns=456)
                self.assertTrue(entered.wait(1))
                second = pool.submit(store.record_result, "a" * 32, {"status": "ok"})
                try:
                    self.assertFalse(
                        completed.wait(0.1), "same batch result bypasses submission lock"
                    )
                finally:
                    release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
            metadata = store.get("a" * 32)
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["submitted_at_unix_ns"], 456)
            self.assertTrue(Path(metadata["result_path"]).is_file())
