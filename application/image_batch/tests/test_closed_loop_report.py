"""Physical loop reports keep independent runs, matched plans and allocation uncertainty."""

import importlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from reporting.assembly import write_report


class ClosedLoopReportTests(unittest.TestCase):
    """Hand-computed paired savings reject unrelated plans and unknown cheap totals."""

    def test_paired_savings_use_bounds_and_matching_plans(self):
        """An incomplete allocation interval cannot be treated as a measured saving."""
        self.assertIsNotNone(importlib.util.find_spec("reporting.closed_loop"))
        module = importlib.import_module("reporting.closed_loop")
        common = dict(
            role="heldout",
            seed=62,
            arrival_plan_sha256="same",
            accepted_capture=True,
            origin_seconds=0,
            admission="fifo",
            evaluation_start_seconds=1000,
            arrival_end_seconds=1120,
            config=dict(workers=[dict(configured_cores=4)]),
        )
        fixed = dict(common, arm="fixed", allocation=dict(allocated_core_seconds_bounds=[360, 360]))
        loop = dict(
            common, arm="forecast", allocation=dict(allocated_core_seconds_bounds=[240, 360])
        )
        bounds = module.paired_savings([fixed, loop])[0]["saving_bounds"]
        self.assertEqual(bounds[0], 0)
        self.assertAlmostEqual(bounds[1], 1 / 3)
        loop["evaluation_start_seconds"] += 120
        loop["arrival_end_seconds"] += 120
        self.assertEqual(module.paired_savings([fixed, loop]), [])
        loop["evaluation_start_seconds"] -= 120
        loop["arrival_end_seconds"] -= 120
        loop["admission"] = "scheduler"
        self.assertEqual(module.paired_savings([fixed, loop]), [])
        loop["admission"] = "fifo"
        loop["arrival_plan_sha256"] = "different"
        self.assertEqual(module.paired_savings([fixed, loop]), [])

    def test_combined_report_redraws_without_capture_directory(self):
        """Saved closed-loop payload is sufficient for every page and stays separate from pilots."""
        run = dict(
            role="pilot",
            seed=61,
            arm="forecast",
            run_id="pilot",
            accepted_capture=True,
            acceptance_issues=[],
            arrival_plan_sha256="same",
            capture="/absent/source",
            origin_seconds=0,
            evaluation_start_seconds=720,
            arrival_end_seconds=1440,
            invocation=dict(period_seconds=240),
            config=dict(workers=[dict(configured_cores=4)]),
            allocation=dict(allocated_core_seconds_bounds=[2000, 2160], series=[], gaps=[]),
            responses=dict(
                jobs=2,
                completed=1,
                deadline_fraction=0.5,
                failed_uids=[],
                censored_uids=["x"],
                completed_response_p95_seconds=30,
                completed_responses_seconds=[30],
            ),
            controller=dict(
                cycles=[],
                observed_down=0,
                observed_up=0,
                longest_consecutive_valid_cycles=0,
                within30_native_fraction=None,
            ),
            forecast_diagnostics=[],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(
                json.dumps(dict(schema_version="opendc-closed-loop-evidence-v1", runs=[run]))
            )
            first = write_report([source], root / "first")
            source.unlink()
            second = write_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(first["closed_loop"], second["closed_loop"])
            self.assertEqual(first["closed_loop"]["heldout_runs"], 0)
            self.assertEqual(first["section_order"][0], "closed-loop-physical")
            self.assertGreater((root / "second/report.pdf").stat().st_size, 1000)

    def test_observation_timeline_breaks_at_missing_intervals(self):
        """Two valid endpoints cannot imply a known capacity or queue during a long gap."""
        module = importlib.import_module("reporting.closed_loop")
        series = [
            dict(time=1, valid=True, allocated=6, queue=2, membership_complete=True),
            dict(time=10, valid=True, allocated=3, queue=0, membership_complete=True),
        ]
        for field in ("allocated", "queue"):
            _, values = module.observed_series(series, 0, field)
            self.assertTrue(any(math.isnan(value) for value in values))
