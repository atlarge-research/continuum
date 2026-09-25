"""Measured-report payloads preserve captured evidence for offline composition."""
import json
import math
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# pylint: disable=wrong-import-position
from reporting.measured import (
    prepare_measured,
    measured_groups,
    _snapshot_occupancy,
    _covered_series,
)
from reporting.forecast_evidence import prepare_forecasts
from reporting.assembly import write_report
from analyze_run_core import analyze
from test_analyze_run import fixture
from forecast_workload import run_once
from forecast_trace import iso
from test_forecast_workload import fixture as forecast_fixture, save_rows, settings, BASE
from test_opendc_report import action_result

# pylint: enable=wrong-import-position


class ObservedReportTests(unittest.TestCase):
    """Retain all plotted measurements and keep unlike arrival plans separate."""

    def test_snapshot_categories_and_cordon_capacity_are_causal(self):
        """Assigned startup and running state remain separate; cordon removes admission capacity."""
        records, evidence = fixture()
        states = evidence["cluster-state"]
        states[2]["jobs"]["active"][0]["execution_state"] = "running"
        states[2]["jobs"]["queued"][0]["execution_state"] = "waiting"
        states[2]["workers"][0]["schedulable"] = False
        report = analyze(records, evidence, "run-a", 10)
        _snapshot_occupancy(
            report, states, {"workers": [{"node_name": "worker-1", "configured_cores": 4}]}
        )
        point = next(p for p in report["pressure"] if p["time_seconds"] == 2)
        self.assertEqual(
            (
                point["snapshot_running_jobs"],
                point["startup_jobs"],
                point["unclassified_assigned_jobs"],
            ),
            (1, 1, 0),
        )
        self.assertEqual(point["modeled_admission_cpu"], 0)
        self.assertEqual(report["pressure"][0]["modeled_admission_cpu"], 3)

    def test_plot_series_breaks_at_capture_gaps_and_missing_samples(self):
        """Plots cannot connect missing state intervals or incomplete CPU sums."""
        points = [{"time_seconds": t, "value": v} for t, v in ((0, 1), (1, None), (7, 3))]
        times, values = _covered_series(points, "value")
        self.assertEqual(times[-1], 7)
        self.assertEqual(len(times), 4)
        self.assertTrue(all(math.isnan(value) for value in values[1:3]))

    def test_prepare_payload_reuses_analysis_and_survives_source_removal(self):
        """Saved numerical evidence retains CPU coverage, lifecycle and exact provenance."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records, evidence = fixture()
            endpoint = root / "endpoint.jsonl"
            endpoint.write_text("\n".join(json.dumps(row) for row in records) + "\n")
            for name, rows in evidence.items():
                (root / (name + ".jsonl")).write_text(
                    "".join(json.dumps(row) + "\n" for row in rows)
                )
            before = endpoint.read_bytes()
            payload = prepare_measured([endpoint], root)
            self.assertEqual(payload["schema_version"], "opendc-measured-evidence-v1")
            self.assertEqual(payload["runs"][0]["summary"]["completed_jobs"], 2)
            self.assertEqual(len(payload["runs"][0]["jobs"]), 2)
            self.assertIn("cpu_coverage_complete", payload["runs"][0]["pressure"][0])
            self.assertTrue(
                any(p["unclassified_assigned_jobs"] > 0 for p in payload["runs"][0]["pressure"])
            )
            self.assertTrue(
                all(p["snapshot_running_jobs"] == 0 for p in payload["runs"][0]["pressure"])
            )
            implementation = payload["provenance"]["implementation"]
            self.assertIn("reporting/measured.py", implementation)
            self.assertIn("reporting/analyzer.py", implementation)
            for relative, digest in implementation.items():
                source = Path(__file__).resolve().parents[1] / "src" / relative
                self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(len(payload["provenance"]["inputs"]), 5)
            self.assertEqual(endpoint.read_bytes(), before)
            round_trip = json.loads(json.dumps(payload, allow_nan=False))
            endpoint.unlink()
            self.assertEqual(measured_groups(round_trip), [[0]])

    def test_different_plans_never_share_batch_index_alignment(self):
        """Different seeds form separate groups even when their batch counts match."""
        reports = [
            {
                "arrivals": [{"batch_index": 0, "planned_seconds": value}],
                "summary": {"run_id": str(index)},
            }
            for index, value in enumerate((0, 1, 0))
        ]
        self.assertEqual(measured_groups({"runs": reports}), [[0, 2], [1]])

    def test_measured_only_report_regenerates_from_saved_numerical_payload(self):
        """Real execution pages must not depend on simulator results or live input files."""
        records, evidence = fixture()
        payload = {
            "schema_version": "opendc-measured-evidence-v1",
            "max_sample_age_seconds": 10,
            "runs": [analyze(records, evidence, "run-a", 10)],
            "context": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "measured.json"
            source.write_text(json.dumps(payload, allow_nan=False))
            audit = write_report([source], root / "first")
            self.assertEqual(audit["section_order"], ["measured"])
            self.assertEqual(
                len(re.findall(rb"/Type /Page\b", (root / "first/report.pdf").read_bytes())), 2
            )
            source.unlink()
            repeated = write_report([root / "first/metrics.json"], root / "second")
            self.assertEqual(repeated["measured"], audit["measured"])

    def test_forecast_only_and_combined_reports_retain_section_order(self):
        """Arrival accuracy renders alone or between measured and action evidence."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_rows(root / "observer", forecast_fixture())
            run_once(root / "observer", root / "forecasts", BASE + 60000, settings())
            forecasts = prepare_forecasts(root / "forecasts", root / "observer", iso(BASE + 80000))
            source = root / "forecast.json"
            source.write_text(json.dumps(forecasts))
            standalone = write_report([source], root / "forecast-only")
            self.assertEqual(standalone["section_order"], ["arrival-forecast"])
            exported = root / "forecast-only/arrival-forecast-00"
            self.assertEqual(json.loads((exported / "forecast-report.json").read_text()), forecasts)
            self.assertTrue(
                (exported / "forecast-scores.csv").read_text().startswith("forecast_cutoff,")
            )
            records, evidence = fixture()
            combined = {
                "results": [],
                "forecast_reports": [forecasts],
                "action_reports": [action_result()],
                "measured_reports": [
                    {
                        "schema_version": "opendc-measured-evidence-v1",
                        "max_sample_age_seconds": 10,
                        "context": {},
                        "runs": [analyze(records, evidence, "run-a", 10)],
                    }
                ],
            }
            source = root / "combined.json"
            source.write_text(json.dumps(combined))
            audit = write_report([source], root / "combined")
            self.assertEqual(audit["section_order"], ["measured", "arrival-forecast", "actions"])
            self.assertEqual(
                len(re.findall(rb"/Type /Page\b", (root / "combined/report.pdf").read_bytes())), 6
            )


if __name__ == "__main__":
    unittest.main()
