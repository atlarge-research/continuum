"""Physical loop reports keep independent runs, matched plans and allocation uncertainty."""

import importlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import matplotlib.pyplot as plt

from reporting.assembly import write_report


class ClosedLoopReportTests(unittest.TestCase):
    """Hand-computed paired savings reject unrelated plans and unknown cheap totals."""

    def test_response_cdf_weights_seeds_equally_and_retains_missing_outcomes(self):
        """Large cohorts cannot dominate, and failed/censored Jobs cannot raise the CDF."""
        module = importlib.import_module("reporting.closed_loop")
        result = module.response_cdf(
            [
                {"seed": 1, "responses": {"jobs": 10, "completed_responses_seconds": [60] * 9}},
                {"seed": 2, "responses": {"jobs": 2, "completed_responses_seconds": [120]}},
            ]
        )
        self.assertEqual(result["seconds"], [0.0, 60.0, 120.0])
        self.assertEqual(result["mean_percent"], [0.0, 45.0, 70.0])
        self.assertEqual(result["lower_percent"], [0.0, 0.0, 50.0])
        self.assertEqual(result["upper_percent"], [0.0, 90.0, 90.0])
        self.assertIsNone(result["all_job_p95_seconds"])

    def test_response_cdf_reports_a_reachable_95_percent_intersection(self):
        """The percentile crossing belongs to the all-Job curve, not completed-only times."""
        module = importlib.import_module("reporting.closed_loop")
        result = module.response_cdf(
            [
                {"seed": 1, "responses": {"jobs": 20, "completed_responses_seconds": [50] * 19}},
            ]
        )
        self.assertEqual(result["all_job_p95_seconds"], 50)
        self.assertEqual(result["mean_percent"][-1], 95)

    def test_actual_arrival_bins_are_nonoverlapping_with_cycle_totals(self):
        """Boundary arrivals enter exactly one bin and the common arrival end is excluded."""
        module = importlib.import_module("reporting.closed_loop")
        run = {
            "evaluation_start_seconds": 1000,
            "arrival_end_seconds": 1120,
            "invocation": {"period_seconds": 60},
            "responses": {
                "cohort": [
                    {"creation_ms": at * 1000}
                    for at in (999, 1000, 1029.9, 1030, 1059.9, 1060, 1119.9, 1120)
                ]
            },
        }
        result = module.arrival_bins(run)
        self.assertEqual(result["counts"], [2, 2, 1, 1])
        self.assertEqual(result["cycle_totals"], [4, 2])
        self.assertEqual(result["edges_seconds"], [0, 30, 60, 90, 120])

    def test_action_timeline_separates_cancellation_request_and_observation(self):
        """Cancelled proposals have no API request; uncertain requests are not observed actions."""
        module = importlib.import_module("reporting.closed_loop")
        run = dict(
            arm="forecast",
            controller=dict(
                cycles=[
                    dict(
                        tick=1,
                        forecast_valid=True,
                        proposal_seconds=10,
                        outcome_recorded_seconds=12,
                        outcome="vetoed_or_failed",
                        proposal=dict(action="scale-down"),
                        actions=[],
                    ),
                    dict(
                        tick=2,
                        forecast_valid=True,
                        proposal_seconds=20,
                        outcome="acknowledged",
                        proposal=dict(action="scale-up"),
                        actions=[dict(action="scale-up")],
                    ),
                ],
                actions=[
                    dict(
                        tick=2,
                        action="scale-up",
                        recorded_at_ns=22_000_000_000,
                        observation_seconds=25,
                        observed=True,
                        result=dict(status="acknowledged"),
                    ),
                    dict(
                        tick=3,
                        action="scale-down",
                        recorded_at_ns=30_000_000_000,
                        observation_seconds=32,
                        observed=True,
                        result=dict(status="uncertain"),
                    ),
                ],
            ),
        )
        rows = module.action_timeline(run)
        self.assertEqual(
            [(row["stage"], row["seconds"]) for row in rows],
            [
                ("Proposed", 10),
                ("Cancelled before API", 12),
                ("Proposed", 20),
                ("API requested", 22),
                ("Observed", 25),
                ("API requested", 30),
            ],
        )

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

    def test_current_report_uses_available_seed_and_configured_timing(self):
        """A fresh evaluation seed must show diagnostics with its own horizon and budget."""
        module = importlib.import_module("reporting.closed_loop")
        run = dict(
            role="heldout",
            seed=107,
            arm="forecast",
            run_id="fresh-107",
            accepted_capture=True,
            invocation={"horizon_seconds": 300, "decision_age_seconds": 55},
            controller={"actions": []},
        )
        with mock.patch.object(module, "_outcomes"), mock.patch.object(
            module, "_timelines"
        ), mock.patch.object(module, "_forecast_observation_page") as rendered:
            result = module.render_pages(None, [{"runs": [run]}])
        self.assertEqual(result.get("diagnostic_runs"), ["fresh-107"])
        self.assertEqual(rendered.call_args.args[1]["seed"], 107)

    def test_pairing_rejects_deployment_changes_but_allows_policy_settings(self):
        """A matching arrival hash cannot conceal a different replay/network deployment."""
        module = importlib.import_module("reporting.closed_loop")
        common = dict(
            role="heldout",
            seed=107,
            arrival_plan_sha256="same",
            accepted_capture=True,
            origin_seconds=0,
            admission="fifo",
            evaluation_start_seconds=1000,
            arrival_end_seconds=1120,
            config={"workers": []},
            comparison_settings={"network_preset": "wired"},
        )
        fixed = dict(common, arm="fixed", allocation={"allocated_core_seconds_bounds": [100, 100]})
        forecast = dict(
            common,
            arm="forecast",
            allocation={"allocated_core_seconds_bounds": [80, 80]},
            invocation={"horizon_seconds": 300},
        )
        self.assertEqual(len(module.paired_savings([fixed, forecast])), 1)
        forecast["comparison_settings"] = {"network_preset": "5g"}
        self.assertEqual(module.paired_savings([fixed, forecast]), [])

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

    def test_action_evidence_distinguishes_fallback_and_uncertain_execution(self):
        """A physical up is not forecast-selected when fallback supplied its proposal."""
        module = importlib.import_module("reporting.closed_loop")
        run = dict(
            arm="forecast",
            controller=dict(
                cycles=[
                    dict(tick=9, forecast_valid=True, proposal={}),
                    dict(tick=11, forecast_valid=False, proposal=dict(fallback=True)),
                ],
                actions=[
                    dict(
                        tick=9,
                        action="scale-down",
                        observed=True,
                        recorded_at_ns=1_000_000_000,
                        result=dict(status="acknowledged"),
                    ),
                    dict(
                        tick=11,
                        action="scale-up",
                        observed=True,
                        recorded_at_ns=2_000_000_000,
                        result=dict(status="acknowledged"),
                    ),
                    dict(
                        tick=12,
                        action="scale-down",
                        observed=None,
                        recorded_at_ns=3_000_000_000,
                        result=dict(status="uncertain"),
                    ),
                ],
            ),
        )
        rows = module.action_evidence(run)
        self.assertEqual([r["source"] for r in rows], ["Forecast", "Reactive fallback", "Unknown"])
        self.assertEqual([r["confirmed"] for r in rows], [True, True, False])
        self.assertEqual([r["request_seconds"] for r in rows], [1, 2, 3])
        run["controller"]["actions"][0]["result"]["status"] = "uncertain"
        self.assertFalse(module.action_evidence(run)[0]["confirmed"])

    def test_reactive_action_page_does_not_imply_missing_native_metrics(self):
        """A baseline action page identifies native forecasts as inapplicable."""
        module = importlib.import_module("reporting.closed_loop")
        run = dict(
            seed=7,
            arm="reactive",
            evaluation_start_seconds=0,
            arrival_end_seconds=120,
            allocation=dict(series=[]),
            controller=dict(
                cycles=[],
                actions=[dict(action="scale-down", recorded_at_ns=1_000_000_000)],
            ),
        )
        with mock.patch("reporting.closed_loop.finish") as saved:
            # Inspect the internal renderer without expanding the public report API.
            module._action_evidence_page(None, run)  # pylint: disable=protected-access
        figure = saved.call_args.args[1]
        try:
            self.assertTrue(
                any("Not applicable" in text.get_text() for text in figure.axes[3].texts)
            )
            self.assertIsNone(figure.axes[3].get_legend())
        finally:
            plt.close(figure)

    def test_many_actions_fit_above_notes_without_losing_confirmation_counts(self):
        """Repeated scaling stays readable while uncertain and fallback requests remain counted."""
        module = importlib.import_module("reporting.closed_loop")
        run = dict(
            seed=107,
            arm="forecast",
            evaluation_start_seconds=0,
            arrival_end_seconds=120,
            allocation=dict(series=[]),
            controller=dict(
                cycles=[
                    dict(tick=i, forecast_valid=i < 8, proposal=dict(fallback=8 <= i < 10))
                    for i in range(12)
                ],
                actions=[
                    dict(
                        tick=i,
                        action="scale-down" if i % 2 == 0 else "scale-up",
                        recorded_at_ns=(i + 1) * 10_000_000_000,
                        observed=i < 9 and i != 6,
                        result=dict(status="acknowledged" if i < 9 and i != 6 else "uncertain"),
                    )
                    for i in range(12)
                ],
            ),
        )
        with mock.patch("reporting.closed_loop.finish") as saved:
            module._action_evidence_page(None, run)  # pylint: disable=protected-access
        figure = saved.call_args.args[1]
        try:
            figure.canvas.draw()
            table = figure.axes[2].tables[0]
            bounds = table.get_window_extent(figure.canvas.get_renderer())
            self.assertGreaterEqual(bounds.y0, 0.15 * figure.bbox.height)
            cells = table.get_celld()
            rows = {
                cells[row, 0]
                .get_text()
                .get_text(): [cells[row, column].get_text().get_text() for column in (1, 2)]
                for row in sorted({row for row, _ in cells if row > 0})
            }
            self.assertEqual(
                rows,
                {
                    "Forecast": ["3/4", "4/4"],
                    "Reactive fallback": ["1/1", "0/1"],
                    "Unknown": ["0/1", "0/1"],
                },
            )
        finally:
            plt.close(figure)
