"""Durable intents survive interruption without authorizing duplicate API requests."""

import importlib
from pathlib import Path
import tempfile
import unittest


class JournalTests(unittest.TestCase):
    """Recovery distinguishes an unacknowledged intent from a completed cycle."""

    def journal(self, path):
        """Open the production journal with an exclusive process lock.

        Args:
            path (Path): Journal path inside a temporary evidence directory.

        Returns:
            Journal: Locked append-only action history.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_journal"))
        return importlib.import_module("closed_loop_journal").Journal(path)

    def test_pending_intent_survives_restart_until_observation_resolves_it(self):
        """A timed-out API call is never assumed to have failed or blindly retried."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.jsonl"
            journal = self.journal(path)
            journal.append(
                "action.request",
                action_id="one",
                action="scale-up",
                selected_worker="w3",
                node_uid="uid-w3",
            )
            journal.close()
            resumed = self.journal(path)
            self.assertEqual(resumed.pending_action()["action_id"], "one")
            resumed.append(
                "action.result", action_id="one", outcome="observed_applied", last_action_at=1000
            )
            self.assertIsNone(resumed.pending_action())
            self.assertEqual(resumed.history()["last_action_at"], 1000)
            resumed.close()

    def test_truncated_tail_is_preserved_before_safe_resume(self):
        """A partial acknowledgment cannot conceal the preceding durable intent."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.jsonl"
            journal = self.journal(path)
            journal.append("action.request", action_id="one")
            journal.close()
            with path.open("ab") as stream:
                stream.write(b'{"event":"action.result"')
            original = path.read_bytes()
            resumed = self.journal(path)
            self.assertEqual(resumed.pending_action()["action_id"], "one")
            archives = list(Path(temporary).glob("journal-before-recovery-*.jsonl"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0].read_bytes(), original)
            resumed.close()

    def test_second_process_cannot_open_the_same_controller_journal(self):
        """Exclusive locking protects resumed sessions as well as first launches."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.jsonl"
            journal = self.journal(path)
            with self.assertRaises(BlockingIOError):
                self.journal(path)
            journal.close()


if __name__ == "__main__":
    unittest.main()
