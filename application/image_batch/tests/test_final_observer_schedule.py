"""Overrun sampling must yield for finalization without adding a full idle tick."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from opendt_observer import ResourceSampler
from test_opendt_observer import FakeBatchApi, FakeCoreApi, FakePrometheus, RecordingWriter


class ObserverScheduleTests(unittest.TestCase):
    """Exercise actual sampling with deterministic collection and completion clocks."""

    def sampling_waits(self, collection_seconds):
        """Record the wait following one bounded simulated collection.

        Args:
            collection_seconds (float): Duration of the collection operation.

        Returns:
            list[float]: Wait durations offered to terminal-profile finalization.
        """
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
            """Advance the real collection beyond its simulated start.

            Args:
                collect_resources (bool): Whether resource collection was due.
            """
            self.assertTrue(collect_resources)
            clock["now"] += collection_seconds

        def wait(seconds):
            """Record the pause and terminate the deterministic scheduler loop.

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
        return waits

    def test_overrun_yields_without_waiting_for_another_full_grid_tick(self):
        """Small and large overruns offer a positive bounded finalization window."""
        for duration in (1.067, 2.5):
            with self.subTest(collection_seconds=duration):
                waits = self.sampling_waits(duration)
                self.assertEqual(len(waits), 1)
                self.assertAlmostEqual(waits[0], 0.05)

    def test_on_time_collection_keeps_the_normal_state_cadence(self):
        """A collection finishing before its next tick retains ordinary cadence."""
        waits = self.sampling_waits(0.4)
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.6)


if __name__ == "__main__":
    unittest.main()
