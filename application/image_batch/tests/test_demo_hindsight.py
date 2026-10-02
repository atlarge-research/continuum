"""Hindsight coverage retains missing predeclared cutoffs without replacing them."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import demo_hindsight
from demo_tuning import NativeCleanupError


class HindsightTests(unittest.TestCase):
    """Check the explicit unavailable evidence boundary without running native cases."""

    def test_unverified_cleanup_stops_remaining_cutoffs_with_explicit_coverage(self):
        """A possibly running container must prevent another diagnostic launch."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture, output = root / "capture", root / "out"
            capture.mkdir()
            (capture / "cleanup.json").write_text(
                json.dumps(
                    {
                        "namespace_removed": True,
                        "network_restored": True,
                        "original_deployment_preserved": True,
                    }
                )
            )
            protocol = {
                "hindsight_ticks": [1, 4, 7, 10],
                "closure_at_seconds": 1e15,
                "native_image": "image:pinned",
            }
            commands = [{"arm": "forecast", "output": str(capture)}]
            with patch.object(
                demo_hindsight, "verify_protocol", return_value=protocol
            ), patch.object(demo_hindsight, "matrix_commands", return_value=commands), patch.object(
                demo_hindsight,
                "evaluate_cycle",
                side_effect=NativeCleanupError("owned container absence unverified"),
            ) as evaluate:
                with self.assertRaises(NativeCleanupError):
                    demo_hindsight.run_diagnostics(root / "protocol.json", root, output)
            self.assertEqual(evaluate.call_count, 1)
            saved = json.loads((output / "summary.json").read_text())
            rows = saved["runs"][0]["comparisons"]
            self.assertEqual([row["tick"] for row in rows], [1, 4, 7, 10])
            self.assertTrue(all(row.get("excluded") for row in rows))
            self.assertIn("unverified", saved["fatal_cleanup_error"])

    def test_missing_original_cycle_is_retained_as_excluded(self):
        """A missing cutoff is evidence of missing coverage, not a reason to choose another."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = demo_hindsight.evaluate_cycle(root, 7, root / "out", "image:pinned")
            self.assertEqual(result["tick"], 7)
            self.assertIn("excluded", result)
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
