"""Evaluated arrivals cannot hide behind a timely warm-up or incomplete sender identities."""

import copy
from pathlib import Path
import unittest

import closed_loop_evidence
from demo_workflow import matrix_commands


def batch_events(index, offset, lag=0):
    """Build literal planned, started and received events for one sender batch.

    Args:
        index (int): Unique batch index.
        offset (int): Planned offset in seconds.
        lag (int): Dispatch lag in nanoseconds.

    Returns:
        list[dict]: Complete identity-linked sender events.
    """
    details = dict(
        endpoint_batch_id=f"batch-{index}",
        batch_index=index,
        planned_offset_ns=offset * 1_000_000_000,
    )
    return [
        dict(event_type=kind, details=dict(details, **extra))
        for kind, extra in (
            ("schedule.planned", {}),
            (
                "batch.send_started",
                dict(actual_send_offset_ns=offset * 1_000_000_000 + lag, schedule_lag_ns=lag),
            ),
            ("batch.receipt_received", {}),
        )
    ]


class SenderWindowTests(unittest.TestCase):
    """Check measured lag and exact identities in a half-open planned-arrival window."""

    def measure(self, events, start=5, end=10):
        """Call the production boundary while detecting the missing feature clearly.

        Args:
            events (list[dict]): Literal sender events.
            start (float): Inclusive planned start offset in seconds.
            end (float): Exclusive planned end offset in seconds.

        Returns:
            dict: Evaluated-window fidelity evidence.
        """
        self.assertTrue(
            hasattr(closed_loop_evidence, "sender_window_fidelity"),
            "evaluated-window fidelity is missing",
        )
        return closed_loop_evidence.sender_window_fidelity(
            events, start_offset_seconds=start, end_offset_seconds=end
        )

    def test_planned_window_includes_start_excludes_end_despite_late_dispatch(self):
        """Late actual dispatch remains in its planned evaluation cohort."""
        events = batch_events(0, 4) + batch_events(1, 5, 6_000_000_000) + batch_events(2, 10)
        result = self.measure(events)
        self.assertEqual(result["planned_count"], 1)
        self.assertEqual(result["on_time_count"], 0)
        self.assertEqual(result["schedule_lag_max_seconds"], 6)
        self.assertFalse(result["fidelity_passed"])

    def test_timely_warmup_cannot_hide_late_evaluated_arrival(self):
        """Twenty timely warm-up batches do not dilute one late evaluated arrival."""
        events = [row for index in range(20) for row in batch_events(index, 1)]
        events += batch_events(20, 6, 251_000_000)
        self.assertEqual(self.measure(events)["on_time_fraction"], 0)

    def test_missing_failed_duplicate_and_misreported_events_fail(self):
        """Incomplete identity coverage and inconsistent measured lag cannot pass."""
        original = batch_events(1, 6)
        cases = [
            original[:2],
            original + [original[1]],
            original + [dict(event_type="batch.send_failed", details=original[0]["details"])],
        ]
        misreported = copy.deepcopy(original)
        misreported[1]["details"]["actual_send_offset_ns"] += 1_000_000_000
        cases.append(misreported)
        for events in cases:
            with self.subTest(events=events):
                self.assertFalse(self.measure(events)["fidelity_passed"])

    def test_exact_tolerance_and_empty_or_invalid_window(self):
        """250ms is accepted; no evaluated arrivals cannot substantiate fidelity."""
        result = self.measure(batch_events(1, 6, 250_000_000))
        self.assertTrue(result["fidelity_passed"])
        self.assertEqual(result["successful_count"], 1)
        self.assertFalse(self.measure(batch_events(0, 1))["fidelity_passed"])
        for start, end in ((5, 5), (10, 5), (-1, 10), (True, 10), (5, float("inf"))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.measure([], start, end)

    def test_required_fidelity_is_explicit_in_sealed_commands_and_default_compatible(self):
        """Only explicitly opted-in future protocols request stronger acceptance."""
        protocol = dict(
            source_root="/frozen",
            continuum_config="/cluster.cfg",
            inventory="/inventory",
            experiment_config="/settings.json",
            native_image="native:pinned",
            run_prefix="fidelity",
            matrix=[dict(seed=1, arm="fixed")],
        )
        self.assertNotIn(
            "--require-evaluated-sender-fidelity",
            matrix_commands(protocol, Path("/new"))[0]["command"],
        )
        protocol["require_evaluated_sender_fidelity"] = True
        self.assertIn(
            "--require-evaluated-sender-fidelity",
            matrix_commands(protocol, Path("/new"))[0]["command"],
        )
        protocol["require_evaluated_sender_fidelity"] = "true"
        with self.assertRaises(ValueError):
            matrix_commands(protocol, Path("/new"))
