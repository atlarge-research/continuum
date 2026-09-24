"""Standalone arrival pages preserve captured duration and truthful evidence labels."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.text import Text

# Direct unittest discovery follows the repository's local source import convention.
# pylint: disable=wrong-import-position
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import reporting.forecast_evidence as forecast_report
from forecast_trace import iso
from forecast_workload import run_once
from reporting.arrivals import render_arrivals
from reporting.topics import arrival_summary
from test_forecast_workload import BASE, fixture, save_rows, settings


class CapturedPdf(PdfPages):
    """Write a real PDF while retaining its figures for evidence assertions.

    Args:
        filename (Path): Destination PDF.
    """

    def __init__(self, filename):
        super().__init__(filename)
        self.figures = []

    def savefig(self, figure=None, **kwargs):
        """Save and retain the rendered figure.

        Args:
            figure (Figure): Rendered page.
            **kwargs (dict): PDF save options.
        """
        self.figures.append(figure)
        super().savefig(figure, **kwargs)


def figure_text(figure):
    """Collect rendered labels, including table cells.

    Args:
        figure (Figure): Rendered page.

    Returns:
        str: All visible text joined for semantic assertions.
    """
    return "\n".join(artist.get_text() for artist in figure.findobj() if isinstance(artist, Text))


class StandaloneArrivalTests(unittest.TestCase):
    """Exercise standalone reports with actual forecast and PDF generation."""

    def setUp(self):
        """Prepare one captured twenty-second forecast with no study assignment."""
        # unittest cleanup retains the fixture through the whole test, including failures.
        self.temporary = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        save_rows(self.root / "inputs", fixture())
        run_once(self.root / "inputs", self.root / "forecast", BASE + 60000, settings())
        self.report = forecast_report.prepare_forecasts(
            self.root / "forecast", self.root / "inputs", iso(BASE + 80000)
        )
        self.roles = {"test": {"split": "unassigned", "workload_seed": None}}

    def test_standalone_axes_follow_captured_end_and_forecast_horizon(self):
        """Avoid clipping captured runs or extending a twenty-second horizon to sixty."""
        with CapturedPdf(self.root / "report.pdf") as pdf:
            render_arrivals(
                pdf, self.report, arrival_summary([self.report], self.roles), self.roles, {}
            )
        self.assertEqual(pdf.figures[0].axes[0].get_xlim(), (0, 80))
        self.assertEqual(pdf.figures[0].axes[1].get_xlim(), (0, 20))
        self.assertTrue(all(0 <= tick <= 20 for tick in pdf.figures[0].axes[1].get_xticks()))

    def test_standalone_labels_do_not_claim_a_study_role_or_seed(self):
        """A captured run is not evidence of independent study selection or holdout."""
        with CapturedPdf(self.root / "report.pdf") as pdf:
            render_arrivals(
                pdf, self.report, arrival_summary([self.report], self.roles), self.roles, {}
            )
        for figure in pdf.figures:
            text = figure_text(figure).lower()
            for misleading in (
                "held-out",
                "held out",
                "selection",
                "seed none",
                "campaign",
                "at 60 s",
            ):
                self.assertNotIn(misleading, text)
        self.assertIn("test", figure_text(pdf.figures[0]))
        self.assertTrue(any(axis.lines for axis in pdf.figures[1].axes))

    def test_missing_eligible_examples_render_an_unavailability_note(self):
        """Reports without complete illustrative horizons still produce readable pages."""
        report = copy.deepcopy(self.report)
        report["example_cutoffs"] = []
        report["cumulative_examples"] = {}
        with CapturedPdf(self.root / "report.pdf") as pdf:
            render_arrivals(pdf, report, arrival_summary([report], self.roles), self.roles, {})
        self.assertIn("no eligible", figure_text(pdf.figures[0]).lower())

    def test_export_preserves_numerical_evidence_without_rendering(self):
        """The export-only API retains lead times and both model scores."""
        self.assertTrue(callable(getattr(forecast_report, "export_forecasts", None)))
        forecast_report.export_forecasts(self.report, self.root)
        self.assertEqual(json.loads((self.root / "forecast-report.json").read_text()), self.report)
        self.assertEqual(
            json.loads((self.root / "forecast-evaluation.json").read_text()),
            self.report["evaluation"],
        )
        self.assertEqual(
            json.loads((self.root / "forecast-horizon-scores.json").read_text()),
            self.report["horizon_scores"],
        )
        with (self.root / "forecast-scores.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 8)
        self.assertEqual(
            [float(row["lead_end_seconds"]) for row in rows], [5, 5, 10, 10, 15, 15, 20, 20]
        )
        self.assertEqual({row["model"] for row in rows}, {"cyclic", "constant"})


if __name__ == "__main__":
    unittest.main()
