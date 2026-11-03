"""Real-process regressions for opt-in single-command execution budgets."""

import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from infrastructure import machine as machine_module


class MachineDeadlineTests(unittest.TestCase):
    """Exercise real local children while keeping default execution compatible."""

    def setUp(self):
        self.machine = machine_module.Machine("local", True)
        self.tempdir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def _python(self, source, **kwargs):
        return self.machine.process({}, [sys.executable, "-u", "-c", source], **kwargs)

    def test_timeout_preserves_partial_output_and_reaps_child(self):
        """A sleeping command returns its output and an explicit failure promptly."""
        started = time.monotonic()
        output, error = self._python(
            "import os,time,sys; print(os.getpid()); print('before hang'); "
            "print('original error',file=sys.stderr); time.sleep(20)", timeout_seconds=0.2
        )[0]
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn("before hang", output)
        self.assertIn("original error", error)
        self.assertIn("timed out", " ".join(error).lower())
        with self.assertRaises(ChildProcessError):
            os.waitpid(int(output[0]), os.WNOHANG)

    def test_descendant_holding_pipes_is_terminated(self):
        """An exited leader cannot leave a sleeping grandchild holding capture pipes."""
        pid_file = self.root / "descendant.pid"
        source = (
            "import subprocess,sys; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
            "open(sys.argv[1],'w').write(str(p.pid)); print('leader finished')"
        )
        started = time.monotonic()
        result = self.machine.process(
            {}, [sys.executable, "-u", "-c", source, str(pid_file)], timeout_seconds=0.3
        )
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn("timed out", " ".join(result[0][1]).lower())
        pid = int(pid_file.read_text())
        status = Path("/proc/%d/stat" % pid)
        if status.exists():
            self.assertEqual(status.read_text(encoding="utf-8").split()[2], "Z")

    def test_success_and_nonzero_preserve_result_shape(self):
        """Bounded mode retains ordinary stdout/stderr and nonzero diagnostics."""
        self.assertEqual(self._python("print('ok')", timeout_seconds=2), [[["ok"], []]])
        output, error = self._python(
            "import sys; print('partial'); print('real failure',file=sys.stderr); sys.exit(7)",
            timeout_seconds=2,
        )[0]
        self.assertEqual(output, ["partial"])
        self.assertIn("real failure", error)
        self.assertIn("non-zero return code 7", " ".join(error))

    def test_invalid_and_unsupported_calls_fail_before_launch(self):
        """A budget is finite/positive and applies to exactly one waited command."""
        cases = [
            ([], {}),
            (["true"], {"wait": False}),
            ([["true"], ["true"]], {}),
            (["true"], {"ssh": ["one@192.0.2.1", "two@192.0.2.2"]}),
        ]
        for command, options in cases:
            with self.subTest(command=command, options=options), \
                    mock.patch("infrastructure.machine.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    self.machine.process({"ssh_key": "unused"}, command,
                                         timeout_seconds=1, **options)
                launch.assert_not_called()
        for budget in (0, -1, math.inf, math.nan, True, "1"):
            with self.subTest(budget=budget), \
                    mock.patch("infrastructure.machine.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    self._python("pass", timeout_seconds=budget)
                launch.assert_not_called()

    def test_bounded_ssh_failure_does_not_retry_or_repair_host_keys(self):
        """Read-only diagnostic calls cannot enter unbounded key-repair paths."""
        fake_ssh = self.root / "ssh"
        fake_ssh.write_text(
            "#!" + sys.executable + "\nimport sys\n"
            "print('REMOTE HOST IDENTIFICATION HAS CHANGED!',file=sys.stderr)\n"
            "sys.exit(255)\n", encoding="utf-8"
        )
        fake_ssh.chmod(0o700)
        path = str(self.root) + os.pathsep + os.environ["PATH"]
        with mock.patch.dict(os.environ, {"PATH": path}), \
                mock.patch("infrastructure.machine._repair_known_hosts") as repair, \
                mock.patch("infrastructure.machine.time.sleep") as sleep:
            result = self.machine.process({"ssh_key": "unused"}, ["true"],
                                          ssh="user@192.0.2.1", timeout_seconds=2)
        self.assertIn("IDENTIFICATION HAS CHANGED", " ".join(result[0][1]))
        repair.assert_not_called()
        sleep.assert_not_called()

    def test_cancellation_terminates_and_reaps_started_child(self):
        """Cancellation remains cancellation after bounded cleanup of the child."""
        original_popen = subprocess.Popen
        children = []

        def launch(*args, **kwargs):
            process = original_popen(*args, **kwargs)  # pylint: disable=consider-using-with
            children.append(process)
            communicate = process.communicate
            first = True

            def interrupted(*call_args, **call_kwargs):
                nonlocal first
                if first:
                    first = False
                    raise KeyboardInterrupt
                return communicate(*call_args, **call_kwargs)

            process.communicate = interrupted
            return process

        with mock.patch("infrastructure.machine.subprocess.Popen", side_effect=launch):
            with self.assertRaises(KeyboardInterrupt):
                self._python("import time; time.sleep(20)", timeout_seconds=1)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)

    def test_default_mode_retains_background_and_success_behavior(self):
        """Callers without a timeout retain their existing execution contract."""
        self.assertEqual(self._python("print('default')"), [[["default"], []]])
        self.assertEqual(self._python("pass", wait=False), [])

    def test_escaped_descendant_reports_cleanup_failure_without_unbounded_wait(self):
        """A descendant outside the owned session cannot make pipe cleanup hang forever."""
        pid_file = self.root / "escaped.pid"
        source = (
            "import os,sys,time\n"
            "pid=os.fork()\n"
            "if pid == 0:\n"
            "    os.setsid()\n"
            "    open(sys.argv[1],'w').write(str(os.getpid()))\n"
            "    time.sleep(20)\n"
            "else:\n"
            "    time.sleep(0.05)\n"
        )
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, "capture pipes did not close"):
                self.machine.process({}, [sys.executable, "-c", source, str(pid_file)],
                                     timeout_seconds=0.3)
            self.assertLess(time.monotonic() - started, 4)
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
