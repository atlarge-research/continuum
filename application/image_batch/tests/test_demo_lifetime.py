"""Bound orchestration phases and retain evidence when a child exceeds its deadline."""

import importlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


class LifetimeTests(unittest.TestCase):
    """Verify process ownership and deadline behavior at the operating-system boundary."""

    def module(self):
        """Load the bounded phase supervisor.

        Returns:
            module: Phase lifetime implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("demo_lifetime"))
        return importlib.import_module("demo_lifetime")

    def test_timeout_record_precedes_group_stop_and_retains_unverified_descendants(self):
        """A dead leader cannot hide a surviving descendant or erase the timeout record."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "capture.log"
            process = Mock(pid=43210)
            process.wait.side_effect = [subprocess.TimeoutExpired(["capture"], 10), 0, 0]
            observed_signals = []

            def signal_group(group, number):
                """Observe the durable record before any stop signal.

                Args:
                    group (int): Dedicated process-group identifier.
                    number (int): Signal number, including zero for the final existence check.
                """
                self.assertEqual(group, process.pid)
                status = json.loads(log.with_suffix(".status.json").read_text())
                self.assertEqual(status["status"], "timeout")
                self.assertEqual(status["process_group"], process.pid)
                observed_signals.append(number)

            with patch.object(
                module.subprocess, "Popen", return_value=process
            ) as launch, patch.object(module.os, "killpg", side_effect=signal_group), patch.object(
                module, "STOP_SECONDS", 0.01
            ):
                with self.assertRaises(module.PhaseFailure) as error:
                    module.run_phase(["capture"], log, timeout_seconds=10)
            self.assertFalse(error.exception.group_stopped)
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
            self.assertEqual(
                [number for number in observed_signals if number],
                [signal.SIGTERM, signal.SIGKILL],
            )
            self.assertIn(0, observed_signals)
            status = json.loads(log.with_suffix(".status.json").read_text())
            self.assertFalse(status["process_group_stopped"])
            self.assertEqual(status["command"], ["capture"])

    def test_verified_timeout_and_nonzero_exit_remain_failures(self):
        """A stopped group permits recovery, never a next successful matrix step."""
        module = self.module()
        for first_wait in (subprocess.TimeoutExpired(["capture"], 10), 7):
            with self.subTest(
                first_wait=type(first_wait).__name__
            ), tempfile.TemporaryDirectory() as temporary:
                log = Path(temporary) / "capture.log"
                process = Mock(pid=43210)
                process.wait.side_effect = [first_wait, 0, 0]
                with patch.object(module.subprocess, "Popen", return_value=process), patch.object(
                    module.os, "killpg", side_effect=ProcessLookupError
                ):
                    with self.assertRaises(module.PhaseFailure) as error:
                        module.run_phase(["capture"], log, timeout_seconds=10)
                self.assertTrue(error.exception.group_stopped)
                status = json.loads(log.with_suffix(".status.json").read_text())
                self.assertIn(status["status"], ("timeout", "failed"))
                self.assertTrue(status["process_group_stopped"])

    def test_success_requires_process_group_absence(self):
        """Unexpected descendants after a successful leader are stopped and reported."""
        module = self.module()
        for remaining in (False, True):
            with self.subTest(remaining=remaining), tempfile.TemporaryDirectory() as temporary:
                log = Path(temporary) / "capture.log"
                process = Mock(pid=43210)
                process.wait.return_value = 0
                effect = None if remaining else ProcessLookupError
                with patch.object(module.subprocess, "Popen", return_value=process), patch.object(
                    module.os, "killpg", side_effect=effect
                ), patch.object(module, "STOP_SECONDS", 0.01):
                    if remaining:
                        with self.assertRaises(module.PhaseFailure):
                            module.run_phase(["capture"], log, timeout_seconds=10)
                    else:
                        module.run_phase(["capture"], log, timeout_seconds=10)
                status = json.loads(log.with_suffix(".status.json").read_text())
                self.assertEqual(
                    status["status"], "descendants_remain" if remaining else "complete"
                )

    def test_real_timeout_stops_and_reaps_owned_descendant(self):
        """A real dedicated group is stopped, including a child reaped by its leader."""
        module = self.module()
        program = """import signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(_number, _frame):
    child.wait(timeout=2)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print(child.pid, flush=True)
time.sleep(60)
"""
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "capture.log"
            with self.assertRaises(module.PhaseFailure) as error:
                module.run_phase([sys.executable, "-c", program], log, timeout_seconds=0.5)
            self.assertTrue(error.exception.group_stopped)
            child_pid = int(log.read_text(encoding="utf-8").strip())
            with self.assertRaises(ProcessLookupError):
                module.os.kill(child_pid, 0)
            status = json.loads(log.with_suffix(".status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "timeout")
            self.assertTrue(status["process_group_stopped"])

    def test_leader_exit_waits_for_descendant_group_disappearance(self):
        """An already-exited leader does not shorten the group's reserved TERM grace."""
        module = self.module()
        process = Mock(pid=43210)
        process.wait.return_value = 0
        with patch.object(module.os, "killpg") as send, patch.object(
            module, "group_exists", side_effect=[True, False]
        ), patch.object(module.time, "sleep") as pause:
            stopped, attempts = module.stop_group(process)
        self.assertTrue(stopped)
        self.assertEqual(len(attempts), 1)
        send.assert_called_once_with(process.pid, signal.SIGTERM)
        pause.assert_called_once()


if __name__ == "__main__":
    unittest.main()
