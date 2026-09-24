"""Reporting remains usable through the package and existing command paths."""
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))


class ReportingPackageTests(unittest.TestCase):
    """Exercise public commands independently of the repository working directory."""

    def test_package_exposes_the_existing_report_operations(self):
        """Library consumers use the same implementations as the command wrappers."""
        assembly = importlib.import_module("reporting.assembly")
        wrapper = importlib.import_module("opendc_report")
        self.assertIs(wrapper.write_report, assembly.write_report)
        self.assertIs(wrapper.render_report, assembly.render_report)

    def test_controlled_wrapper_preserves_public_evidence_helpers(self):
        """Existing analysis scripts can still use the controlled report helpers."""
        implementation = importlib.import_module("reporting.controlled")
        wrapper = importlib.import_module("opendc_report_controlled")
        for name in ("SCHEMA", "action_reference", "lifecycle_rows"):
            with self.subTest(export=name):
                self.assertIs(getattr(wrapper, name), getattr(implementation, name))

    def test_existing_commands_work_from_an_unrelated_directory(self):
        """Script invocation finds the package without extra PYTHONPATH setup."""
        with tempfile.TemporaryDirectory() as temporary:
            for name in (
                "analyze_run.py",
                "opendc_report.py",
                "opendc_report_observed.py",
                "opendc_report_controlled.py",
            ):
                with self.subTest(command=name):
                    result = subprocess.run(
                        [sys.executable, str(SOURCE / name), "--help"],
                        cwd=temporary,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
