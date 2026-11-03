"""Bound fresh-guest key discovery without changing shared process execution."""

from pathlib import Path
import subprocess
import tempfile
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


if __name__ == "__main__":
    unittest.main()
