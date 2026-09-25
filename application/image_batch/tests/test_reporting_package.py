"""Reporting commands run directly from their package modules."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "src"


class ReportingPackageTests(unittest.TestCase):
    """Exercise documented commands outside the repository working directory."""

    def test_modules_run_with_the_documented_source_path(self):
        """All report CLIs resolve their imports with src on PYTHONPATH."""
        with tempfile.TemporaryDirectory() as temporary:
            for module in ("analyzer", "assembly", "measured", "controlled"):
                with self.subTest(module=module):
                    result = subprocess.run(
                        [sys.executable, "-m", f"reporting.{module}", "--help"],
                        cwd=temporary,
                        env={**os.environ, "PYTHONPATH": str(SOURCE)},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
