"""Hindsight coverage retains missing predeclared cutoffs without replacing them."""

from pathlib import Path
import tempfile
import unittest

import demo_hindsight


class HindsightTests(unittest.TestCase):
    """Check the explicit unavailable evidence boundary without running native cases."""

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
