"""Bound fresh-guest key discovery without changing shared process execution."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from infrastructure import infrastructure


class SshDiscoveryTests(unittest.TestCase):
    """Use a virtual clock to exercise the complete discovery budget."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.tempdir.cleanup)
        self.hosts = Path(self.tempdir.name) / "ssh directory" / "known hosts"
        self.config = {"ssh_known_hosts_file": str(self.hosts), "home": self.tempdir.name}
        self.machine = mock.Mock()
        self.machine.process.side_effect = lambda _config, command, **_kwargs: (
            [([], [])] if isinstance(command, list)
            else [([], ["# 192.0.2.1:22 SSH-2.0-test"])]
        )
        self.now = 0.0
        self.timeouts = []
        self.probes = []
        self.behavior = lambda _ip: (0, "192.0.2.1 ssh-ed25519 AAAATEST\n", "")
        for patcher in (
            mock.patch("infrastructure.infrastructure.time.monotonic",
                       side_effect=lambda: self.now),
            mock.patch("infrastructure.infrastructure.time.sleep", side_effect=self._sleep),
            mock.patch("subprocess.run", side_effect=self._scan),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _sleep(self, seconds):
        self.now += seconds
        self.assertLessEqual(self.now, 600)

    def _scan(self, command, **kwargs):
        self.probes.append(command[-1])
        self.timeouts.append(kwargs["timeout"])
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(kwargs["timeout"], min(5, 600 - self.now))
        result = self.behavior(command[-1])
        if isinstance(result, Exception):
            self.now += kwargs["timeout"]
            raise result
        return subprocess.CompletedProcess(command, *result)

    def _discover(self, addresses=None):
        infrastructure.add_ssh(self.config, [self.machine], base=addresses or ["192.0.2.1"])

    def test_delayed_success_appends_keys_only_and_preserves_existing_keys(self):
        """A refused probe then valid keys succeeds without copying banner text."""
        self.hosts.parent.mkdir()
        self.hosts.write_text("existing host key\n", encoding="utf-8")
        results = iter([(1, "", "Connection refused"),
                        (0, "# banner\n192.0.2.1 ssh-ed25519 AAAATEST\n", "# banner")])
        self.behavior = lambda _ip: next(results)
        self._discover()
        self.assertEqual(self.probes, ["192.0.2.1", "192.0.2.1"])
        self.assertEqual(self.hosts.read_text(),
                         "existing host key\n192.0.2.1 ssh-ed25519 AAAATEST\n")
        self.machine.process.assert_called_once_with(
            self.config, ["ssh-keygen", "-f", str(self.hosts), "-R", "192.0.2.1"]
        )

    def test_unreachable_guest_exhausts_budget_with_original_error(self):
        """Failure identifies address, elapsed time and last stderr."""
        self.behavior = lambda _ip: (1, "", "Connection refused")
        with self.assertRaisesRegex(RuntimeError, "192.0.2.1.*600.*Connection refused"):
            self._discover()
        self.assertEqual(self.now, 600)
        self.assertEqual(self.hosts.read_text(), "")

    def test_banner_only_does_not_satisfy_discovery(self):
        """A listening server may emit a banner without returning host keys."""
        self.behavior = lambda _ip: (0, "# 192.0.2.1:22 SSH-2.0-test\n", "# banner")
        with self.assertRaisesRegex(RuntimeError, "192.0.2.1.*600"):
            self._discover()
        self.assertEqual(self.hosts.read_text(), "")

    def test_hung_keyscan_has_real_subprocess_timeout(self):
        """A process that never finishes cannot consume an unbounded wait."""
        self.behavior = lambda _ip: subprocess.TimeoutExpired("ssh-keyscan", 5)
        with self.assertRaisesRegex(RuntimeError, "192.0.2.1.*600.*timed out"):
            self._discover()
        self.assertTrue(self.timeouts)
        self.assertEqual(self.now, 600)

    def test_multiple_guests_share_deadline_and_cap_last_probe(self):
        """The second guest receives only the remaining invocation budget."""
        def scan(ip):
            if ip == "192.0.2.1":
                self.now = 598
                return (0, "192.0.2.1 ssh-ed25519 AAAATEST\n", "")
            return subprocess.TimeoutExpired("ssh-keyscan", 2)
        self.behavior = scan
        with self.assertRaisesRegex(RuntimeError, "192.0.2.2.*600"):
            self._discover(["192.0.2.1", "192.0.2.2"])
        self.assertEqual(self.timeouts, [5, 2])
        self.assertEqual(self.now, 600)

    def test_nonzero_scan_cannot_publish_partial_keys(self):
        """Failed scans remain errors even when they emitted a partial key."""
        self.behavior = lambda _ip: (1, "192.0.2.1 ssh-ed25519 AAAATEST\n", "scan failed")
        with self.assertRaisesRegex(RuntimeError, "scan failed"):
            self._discover()
        self.assertEqual(self.hosts.read_text(), "")

    def test_key_removal_error_preserves_existing_failure_semantics(self):
        """Known-host cleanup still aborts before discovery on a real error."""
        self.machine.process.return_value = [([], ["Permission denied"])]
        self.machine.process.side_effect = None
        with self.assertRaises(SystemExit):
            self._discover()
        self.assertEqual(self.probes, [])


class SshDiscoveryProcessTests(unittest.TestCase):
    """Verify discovery at the actual subprocess boundary with disposable executables."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.known_hosts = self.root / "known hosts"
        self.config = {"home": str(self.root), "ssh_known_hosts_file": str(self.known_hosts)}
        self.machine = mock.Mock()
        self.machine.process.return_value = [([], [])]
        self.scan = self.root / "ssh-keyscan"
        self.pid_file = self.root / "scan.pid"
        self.started = time.monotonic()
        self.real_monotonic = time.monotonic
        self.clock_calls = 0

    def _short_budget(self):
        self.clock_calls += 1
        if self.clock_calls == 1:
            return 0
        return 599.7 + self.real_monotonic() - self.started

    def _install_scan(self, source):
        self.scan.write_text("#!" + sys.executable + "\n" + source, encoding="utf-8")
        self.scan.chmod(0o700)
        path = str(self.root) + os.pathsep + os.environ["PATH"]
        patcher = mock.patch.dict(os.environ, {"PATH": path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_real_sleeping_keyscan_is_killed_and_reaped(self):
        """A real hung keyscan cannot outlive the remaining shared discovery budget."""
        self._install_scan(
            "import os,time\nfrom pathlib import Path\n"
            "Path(%r).write_text(str(os.getpid()))\ntime.sleep(20)\n" % str(self.pid_file)
        )
        with mock.patch.object(infrastructure.time, "monotonic", side_effect=self._short_budget):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                infrastructure.add_ssh(self.config, [self.machine], base=["192.0.2.1"])
        self.assertLess(self.real_monotonic() - self.started, 4)
        with self.assertRaises(ChildProcessError):
            os.waitpid(int(self.pid_file.read_text()), os.WNOHANG)
        self.assertEqual(self.known_hosts.read_text(), "")

    def test_real_banner_only_output_exhausts_without_publishing_a_key(self):
        """An actual banner-emitting executable does not satisfy discovery."""
        self._install_scan("print('# 192.0.2.1:22 SSH-2.0-test')\n")
        with mock.patch.object(infrastructure.time, "monotonic", side_effect=self._short_budget):
            with self.assertRaisesRegex(RuntimeError, "No host keys returned"):
                infrastructure.add_ssh(self.config, [self.machine], base=["192.0.2.1"])
        self.assertEqual(self.known_hosts.read_text(), "")

    def test_real_delayed_key_success_publishes_a_generated_host_key(self):
        """A refused scan followed by an actual generated public key succeeds."""
        key = self.root / "fixture-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                       check=True, capture_output=True, timeout=5)
        public = " ".join(key.with_suffix(".pub").read_text().split()[:2])
        attempts = self.root / "attempted"
        self._install_scan(
            "import sys\nfrom pathlib import Path\n"
            "marker=Path(%r)\n"
            "if not marker.exists():\n    marker.touch()\n    sys.exit(1)\n"
            "print(%r)\n" % (str(attempts), "192.0.2.1 " + public)
        )
        real_sleep = time.sleep
        with mock.patch.object(infrastructure.time, "sleep",
                               side_effect=lambda seconds: real_sleep(min(seconds, 0.01))):
            infrastructure.add_ssh(self.config, [self.machine], base=["192.0.2.1"])
        self.assertTrue(attempts.exists())
        self.assertEqual(self.known_hosts.read_text(), "192.0.2.1 " + public + "\n")


if __name__ == "__main__":
    unittest.main()
