"""Overrun observer sampling must leave a wait for terminal evidence finalization."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from opendt_observer import ResourceSampler
from test_opendt_observer import FakeBatchApi, FakeCoreApi, FakePrometheus, RecordingWriter


class ObserverScheduleTests(unittest.TestCase):
    """Exercise the real scheduler with deterministic slow-collection clocks."""

    def test_overrun_sampling_waits_until_the_next_future_state_tick(self):
        """A2.5second collection on a1second cadence must not immediately retake its lock."""
        sampler = ResourceSampler(
            batch_api=FakeBatchApi([]),
            core_api=FakeCoreApi(),
            prometheus=FakePrometheus(),
            namespace="fns-test",
            label_selector="workload=image-batch",
            run_id="test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=RecordingWriter(),
            state_writer=RecordingWriter(),
            emit_diagnostic=lambda *_args: None,
        )
        clock = dict(now=10.0, stopped=False)
        waits = []

        def collect(*, collect_resources):
            """Advance a real collection past multiple nominal state ticks.

            Args:
                collect_resources (bool): Whether resource collection was due.
            """
            self.assertTrue(collect_resources)
            clock["now"] += 2.5

        def wait(seconds):
            """Record the scheduler pause and terminate the deterministic loop.

            Args:
                seconds (float): Time offered to terminal-record finalization.
            """
            waits.append(seconds)
            clock["stopped"] = True

        sampler._stop = SimpleNamespace(  # pylint: disable=protected-access
            is_set=lambda: clock["stopped"], wait=wait
        )
        with patch(
            "opendt_observer.time.monotonic", side_effect=lambda: clock["now"]
        ), patch.object(sampler, "collect_once", side_effect=collect):
            sampler._run()  # pylint: disable=protected-access
        self.assertEqual(waits, [0.5])


if __name__ == "__main__":
    unittest.main()
