"""Process failures and resource measurements must remain observable."""
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_process import run_process, read_cgroup


class ProcessTests(unittest.TestCase):
    """Exercise real child processes and synthetic cgroup v1/v2 measurements."""

    def test_nonzero_exit_preserves_logs_and_resource_measurements(self):
        """Retain diagnostics and measured execution cost when the child exits with code 7."""
        with tempfile.TemporaryDirectory() as root:
            result = run_process(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('started'); print('failed', file=sys.stderr); sys.exit(7)",
                ],
                Path(root),
                5,
            )
            self.assertEqual(result["exit_code"], 7)
            self.assertFalse(result["timed_out"])
            self.assertEqual((Path(root) / "stdout.log").read_text(), "started\n")
            self.assertIn("failed", (Path(root) / "stderr.log").read_text())
            self.assertGreater(result["wall_seconds"], 0)
            self.assertGreater(result["max_rss_bytes"], 0)
            self.assertGreaterEqual(result["user_cpu_seconds"], 0)

    def test_timeout_terminates_process_group_including_term_ignoring_child(self):
        """Ensure a descendant ignoring SIGTERM cannot continue running after timeout."""
        with tempfile.TemporaryDirectory() as root:
            script = (
                "import subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); "
                "print(p.pid,flush=True); time.sleep(60)"
            )
            start = time.monotonic()
            result = run_process([sys.executable, "-c", script], Path(root), 0.5)
            self.assertTrue(result["timed_out"])
            self.assertIsNotNone(result["signal"])
            self.assertLess(time.monotonic() - start, 5)
            child_pid = int((Path(root) / "stdout.log").read_text())
            stat = Path(f"/proc/{child_pid}/stat")
            for _ in range(50):
                try:
                    state = stat.read_text(encoding="utf-8").split()[2]
                except (FileNotFoundError, ProcessLookupError):
                    # The child can disappear while procfs opens or reads its status.
                    break
                if state == "Z":
                    break
                time.sleep(0.02)
            else:
                self.fail("descendant survived timeout")

    def test_missing_executable_is_an_explicit_launch_failure(self):
        """Distinguish failure to launch from a child that ran and returned nonzero."""
        with tempfile.TemporaryDirectory() as root:
            result = run_process(["/missing/opendc-runner"], Path(root), 1)
            self.assertIsNone(result["exit_code"])
            self.assertIn("No such file", result["launch_error"])
            self.assertTrue((Path(root) / "stderr.log").exists())

    def test_cgroup_v2_reports_counters_and_missing_peak_explicitly(self):
        """Convert v2 CPU microseconds and retain missing peak memory as unavailable."""
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "cgroup.controllers").write_text("cpu memory")
            (directory / "cpu.stat").write_text("usage_usec 1200\nuser_usec 1000\nnr_throttled 2\n")
            (directory / "memory.current").write_text("12345")
            value = read_cgroup(directory)
            self.assertEqual(value["version"], 2)
            self.assertEqual(value["cpu_usage_seconds"], 0.0012)
            self.assertEqual(value["memory_current_bytes"], 12345)
            self.assertIsNone(value["memory_peak_bytes"])
            self.assertIn("memory.peak", value["unavailable"])

    def test_cgroup_v1_reports_peak_and_cpu_time(self):
        """Convert v1 CPU nanoseconds and read peak memory from its controller directory."""
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "cpuacct").mkdir()
            (directory / "memory").mkdir()
            (directory / "cpuacct/cpuacct.usage").write_text("2000000000")
            (directory / "memory/memory.max_usage_in_bytes").write_text("98765")
            value = read_cgroup(directory)
            self.assertEqual(value["version"], 1)
            self.assertEqual(value["cpu_usage_seconds"], 2)
            self.assertEqual(value["memory_peak_bytes"], 98765)


if __name__ == "__main__":
    unittest.main()
