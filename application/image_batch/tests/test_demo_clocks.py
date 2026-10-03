"""A retained guest cannot silently start a timed experiment with a stale clock."""

import unittest
from unittest.mock import patch

from demo_clocks import clock_alignment


class ClockTests(unittest.TestCase):
    """Preflight uses transport bounds rather than assuming an instantaneous SSH call."""

    def settings(self):
        """Provide a minimal two-guest inventory.

        Returns:
            dict: Explicit SSH identities and key used by the deployment resolver.
        """
        return {
            "ssh_key": "/key",
            "inventory_hosts": [
                {"ansible_user": "controller", "ansible_host": "192.0.2.2"},
                {"ansible_user": "endpoint", "ansible_host": "192.0.2.3"},
            ],
        }

    def test_old_saved_clock_fails_before_workload_generation(self):
        """An eight-hour clock lag invalidates every temporal controller contract."""
        with patch("demo_clocks.time.time", side_effect=[1000, 1001]), patch(
            "demo_clocks.ssh", return_value=b"0.0\n"
        ), self.assertRaisesRegex(ValueError, "clock"):
            clock_alignment(self.settings())

    def test_all_guests_are_checked_with_bounded_ssh_uncertainty(self):
        """A guest timestamp inside its measured transport bracket is accepted."""
        with patch("demo_clocks.time.time", side_effect=[1000, 1001, 1002, 1003]), patch(
            "demo_clocks.ssh", side_effect=[b"1000.5\n", b"1002.5\n"]
        ) as transport:
            result = clock_alignment(self.settings())
        self.assertEqual(len(result["guests"]), 2)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result["guests"][0]["offset_seconds_bounds"], [-0.5, 0.5])

    def test_wide_transport_bracket_retries_once_without_accepting_uncertainty(self):
        """A slow SSH handshake does not imply clock skew; one fresh bounded read can prove it."""
        with patch(
            "demo_clocks.time.time", side_effect=[1000, 1003, 1004, 1004.2, 1005, 1005.2]
        ), patch("demo_clocks.ssh", side_effect=[b"1002.9", b"1004.1", b"1005.1"]):
            result = clock_alignment(self.settings())
        self.assertEqual(len(result["guests"][0]["attempts"]), 2)
        self.assertLess(max(abs(v) for v in result["guests"][0]["offset_seconds_bounds"]), 0.2)

    def test_future_or_nonfinite_guest_clock_is_not_accepted(self):
        """Clock validity includes malformed and future timestamps."""
        for value in (b"1010\n", b"nan\n", b"not-a-clock\n"):
            with self.subTest(value=value), patch(
                "demo_clocks.time.time", side_effect=[1000, 1001]
            ), patch("demo_clocks.ssh", return_value=value), self.assertRaises(ValueError):
                clock_alignment(self.settings())


if __name__ == "__main__":
    unittest.main()
