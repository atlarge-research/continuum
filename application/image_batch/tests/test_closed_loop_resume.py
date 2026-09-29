"""Controller continuation respects the capture's declared response follow-up."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import closed_loop_resume


class ResumeTests(unittest.TestCase):
    """Exercise the continuation lifetime without replaying or mutating a capture."""

    def test_continuation_uses_saved_followup_with_legacy_default(self):
        """Shorter and longer saved windows replace the legacy ten-minute boundary."""
        # Each mock callback is consumed synchronously before the next subtest starts.
        # pylint: disable=cell-var-from-loop
        for followup, initial_time, expected_ticks in (
            (120, 1321, 0),
            (900, 1801, 1),
            (None, 1801, 0),
        ):
            with self.subTest(followup=followup), tempfile.TemporaryDirectory() as temporary:
                settings = {"period_seconds": 100, "cycles": 2, "warmup_cycles": 1}
                if followup is not None:
                    settings["followup_seconds"] = followup
                session = Mock(args=SimpleNamespace(**settings), output=Path(temporary))
                (session.output / "endpoint.jsonl").write_text(
                    json.dumps(
                        {
                            "event_type": "schedule.ready",
                            "details": {"schedule_start_timestamp": "1970-01-01T00:16:40+00:00"},
                        }
                    ),
                    encoding="utf-8",
                )
                session.observe.return_value = ([{}, {}], {"completed": 0, "failed": 0})
                loop = Mock(origin=None, args=session.args, session=session)
                discover = closed_loop_resume.Controller.discover_origin
                loop.discover_origin.side_effect = lambda: discover(loop)
                now = [initial_time]

                def advance(_seconds):
                    """Advance the controlled clock beyond the next possible deadline.

                    Args:
                        _seconds (float): Requested sleep, replaced by a deterministic advance.
                    """
                    now[0] += 1000

                with patch.object(
                    closed_loop_resume.argparse.ArgumentParser,
                    "parse_args",
                    return_value=SimpleNamespace(capture_output=Path("/preserved/capture")),
                ), patch.object(closed_loop_resume, "attach", return_value=session), patch.object(
                    closed_loop_resume, "Controller", return_value=loop
                ), patch.object(
                    closed_loop_resume.time, "time", side_effect=lambda: now[0]
                ), patch.object(
                    closed_loop_resume.time, "sleep", side_effect=advance
                ):
                    closed_loop_resume.main()
                self.assertEqual(loop.maybe_tick.call_count, expected_ticks)
                self.assertEqual(loop.origin, 1000)
                loop.prepare.assert_called_once_with(stage_runner=False)
                loop.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
