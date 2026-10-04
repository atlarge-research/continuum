"""Distributed API timestamps must not precede their producer's actual evidence clock."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from events import new_event
from forecast_trace import read_trace

import opendt_observer


class ObserverClockTests(unittest.TestCase):
    """Small clock differences wait conservatively; large or unstable skew fails closed."""

    def boundary(self, seconds):
        """Build an explicit API timestamp.

        Args:
            seconds (float): UTC epoch seconds.

        Returns:
            datetime: A timezone-aware API timestamp.
        """
        return datetime.fromtimestamp(seconds, timezone.utc)

    def test_25ms_clock_difference_waits_before_emission(self):
        """The reproduced25ms ordering defect delays evidence instead of weakening readers."""
        with patch("opendt_observer.time.time", side_effect=[1000.975, 1001.001]), patch(
            "opendt_observer.time.monotonic", return_value=10
        ), patch("opendt_observer.time.sleep") as sleep:
            opendt_observer.await_api_clock(self.boundary(1001))
        self.assertAlmostEqual(sleep.call_args.args[0], 0.025)

    def test_past_creation_does_not_sleep(self):
        """Aligned API history retains its existing immediate observation behavior."""
        with patch("opendt_observer.time.time", return_value=1001), patch(
            "opendt_observer.time.sleep"
        ) as sleep:
            opendt_observer.await_api_clock(self.boundary(1000), None)
        sleep.assert_not_called()

    def test_large_skew_is_rejected_without_waiting(self):
        """A restored stale clock cannot block the observer for hours."""
        with patch("opendt_observer.time.time", return_value=1000), patch(
            "opendt_observer.time.sleep"
        ) as sleep, self.assertRaisesRegex(ValueError, "clock"):
            opendt_observer.await_api_clock(self.boundary(1003))
        sleep.assert_not_called()

    def test_clock_step_back_is_bounded(self):
        """A wall-clock correction during a wait retains a monotonic termination bound."""
        with patch("opendt_observer.time.time", side_effect=[1000.975, 999]), patch(
            "opendt_observer.time.monotonic", side_effect=[10, 10, 12]
        ), patch("opendt_observer.time.sleep"), self.assertRaisesRegex(ValueError, "clock"):
            opendt_observer.await_api_clock(self.boundary(1001))

    def test_completion_boundary_is_also_respected(self):
        """A successful profile waits for its latest API or execution boundary."""
        with patch("opendt_observer.time.time", side_effect=[1001.98, 1002.001]), patch(
            "opendt_observer.time.monotonic", return_value=10
        ), patch("opendt_observer.time.sleep") as sleep:
            opendt_observer.await_api_clock(self.boundary(1000), self.boundary(1002))
        self.assertAlmostEqual(sleep.call_args.args[0], 0.02)

    def test_sampler_emission_remains_strictly_readable_at_its_actual_clock(self):
        """Reproduce the raw arrival failure through production emission and strict reading."""
        clock = {"now": 1000.975}
        records = []

        def advance(seconds):
            """Advance the controlled producer clock while simulating bounded waiting.

            Args:
                seconds (float): Actual requested wait duration.
            """
            clock["now"] += seconds

        def emit(kind, details):
            """Record the production event with its unchanged event-schema clock.

            Args:
                kind (str): Observer diagnostic event type.
                details (dict): Original Job identity and API creation time.
            """
            records.append(
                new_event(kind, component="observer", run_id="clock-test", details=details)
            )

        sampler = opendt_observer.ResourceSampler(
            batch_api=None,
            core_api=None,
            prometheus=None,
            namespace="clock-test",
            label_selector="",
            run_id="clock-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=None,
            state_writer=None,
            emit_diagnostic=emit,
        )
        job = SimpleNamespace(
            metadata=SimpleNamespace(
                uid="clock-job",
                creation_timestamp=self.boundary(1001),
                annotations={opendt_observer.ANNOTATION_WORKLOAD_RUN_ID: "clock-test"},
            )
        )
        with patch("opendt_observer.time.time", side_effect=lambda: clock["now"]), patch(
            "opendt_observer.time.monotonic", return_value=10
        ), patch("opendt_observer.time.sleep", side_effect=advance), patch(
            "events.time.time_ns", side_effect=lambda: round(clock["now"] * 1e9)
        ):
            sampler.observe_job(job)
        rows = {
            "observer-events.jsonl": records,
            "cluster-state.jsonl": [],
            "resource-snapshots.jsonl": [],
            "workload.jsonl": [],
        }
        trace = read_trace(rows, "clock-test", 1001000)
        self.assertEqual(trace.arrivals["clock-job"]["first_seen_ms"], 1001000)
        self.assertEqual(read_trace(rows, "clock-test", 1000999).arrivals, {})


if __name__ == "__main__":
    unittest.main()
