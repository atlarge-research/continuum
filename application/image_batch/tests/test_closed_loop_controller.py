"""Controller action durability and shadow-phase safety regressions."""

import importlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from closed_loop_journal import Journal
from test_closed_loop_guards import GuardTests


class ControllerTests(unittest.TestCase):
    """Physical changes must follow a durable guarded intent and require live mode."""

    def setUp(self):
        """Reuse realistic fresh observer inventory from guard regressions."""
        fixture = GuardTests()
        fixture.setUp()
        self.config = fixture.config
        self.view = fixture.view()
        self.node = {
            "metadata": {"name": "w1", "uid": "uid-w1", "resourceVersion": "42"},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }

    def module(self):
        """Load the production controller.

        Returns:
            module: Controller implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_controller"))
        return importlib.import_module("closed_loop_controller")

    def test_intent_is_durable_before_uid_and_resource_version_guarded_patch(self):
        """An API call is issued only after its exact target and intent can be recovered."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")
            calls = []

            def api(*args):
                pending = journal.pending_action()
                self.assertEqual(pending["selected_worker"], "w1")
                patch_value = json.loads(args[-1])
                self.assertEqual(
                    patch_value[:2],
                    [
                        {"op": "test", "path": "/metadata/uid", "value": "uid-w1"},
                        {"op": "test", "path": "/metadata/resourceVersion", "value": "42"},
                    ],
                )
                calls.append(patch_value)
                return b"{}"

            session = type(
                "Session", (), {"get": lambda _, *args: self.node, "kubectl": staticmethod(api)}
            )()
            with patch.object(module.time, "time", return_value=1002):
                result = module.actuate(
                    session,
                    journal,
                    self.view,
                    self.view,
                    {"action": "scale-down", "selected_worker": "w1"},
                    self.config,
                    cutoff_seconds=1000,
                )
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["status"], "acknowledged")
            self.assertIsNone(journal.pending_action())
            self.assertEqual(journal.history()["last_action_at"], 1002)
            journal.close()

    def test_uncertain_api_outcome_stays_pending_and_cannot_be_reissued(self):
        """A lost API reply requires observation; a second request is forbidden."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")

            def fail(*_args):
                raise RuntimeError("lost API acknowledgement")

            session = type(
                "Session", (), {"get": lambda _, *args: self.node, "kubectl": staticmethod(fail)}
            )()
            proposal = {"action": "scale-down", "selected_worker": "w1"}
            with patch.object(module.time, "time", return_value=1002):
                with self.assertRaisesRegex(RuntimeError, "acknowledgement"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        proposal,
                        self.config,
                        cutoff_seconds=1000,
                    )
                self.assertIsNotNone(journal.pending_action())
                with self.assertRaisesRegex(ValueError, "unresolved"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        proposal,
                        self.config,
                        cutoff_seconds=1000,
                    )
            journal.close()

    def test_shadow_requires_two_consecutive_valid_cycles(self):
        """Invalid forecasts reset readiness and cannot consume the safety shadow phase."""
        module = self.module()
        self.assertEqual(module.shadow_progress(0, True), (1, True))
        self.assertEqual(module.shadow_progress(1, False), (0, True))
        self.assertEqual(module.shadow_progress(1, True), (2, True))
        self.assertEqual(module.shadow_progress(2, True), (2, False))

    def test_final_node_read_rejects_readiness_loss(self):
        """A worker becoming unready before dispatch vetoes the pending capacity change."""
        module = self.module()
        self.node["status"]["conditions"][0]["status"] = "False"
        session = Mock()
        session.get.return_value = self.node
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")
            with patch.object(module.time, "time", return_value=1002):
                with self.assertRaisesRegex(ValueError, "Ready"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        {"action": "scale-down", "selected_worker": "w1"},
                        self.config,
                        cutoff_seconds=1000,
                    )
            session.kubectl.assert_not_called()
            journal.close()

    def test_state_failure_resets_shadow_and_timeout_ends_cycle(self):
        """Recovery continues after transport timeout without credit for broken shadow streaks."""
        module = self.module()
        for failure in (ValueError("stale"), subprocess.TimeoutExpired("ssh", 3)):
            with self.subTest(
                failure=type(failure).__name__
            ), tempfile.TemporaryDirectory() as temporary:
                loop = object.__new__(module.Controller)
                loop.output = Path(temporary)
                loop.journal = Journal(loop.output / "journal.jsonl")
                loop.tick_number, loop.shadow, loop.history = 0, 1, {}
                loop.fresh = Mock(side_effect=failure)
                loop.cycle()
                self.assertEqual(loop.shadow, 0)
                self.assertEqual(loop.journal.records[-1]["event"], "cycle.end")
                self.assertEqual(loop.journal.records[-1]["outcome"], "vetoed_or_failed")
                loop.journal.close()

    def test_restart_skips_orphaned_cycle_directory(self):
        """A crash after directory creation cannot cause evidence overwrite or endless failure."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = Journal(root / "journal.jsonl")
            journal.append("cycle.begin", tick=2)
            (root / "cycle-0003").mkdir()
            self.assertEqual(module.last_tick(journal, root), 3)
            journal.close()
