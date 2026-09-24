"""Check optional report sections and comparable configuration summaries."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Test discovery does not install the image_batch sources as a package.
# pylint: disable=wrong-import-position
from reporting.assembly import write_report
from reporting.configuration import comparison_rows
from test_opendc_evaluate import comparison_cases

# pylint: enable=wrong-import-position


def validation_result():
    """Build literal measurements with a window missing from only one configuration.

    Returns:
        dict: Two configurations, three windows and one shared pair of usable windows.
    """
    groups, cases = [], []
    for horizon, count, errors, costs in (
        (30, 2, [1, 3, 99], [2, 4, 99]),
        (60, 3, [2, 4, 88], [5, 7, 88]),
    ):
        for index, (error, cost) in enumerate(zip(errors, costs)):
            window = {
                "coverage_complete": horizon == 30 or index < 2,
                "completion_curve_mae": error,
                "grid_seconds": [0, 60, 120],
                "observed_curve": [0, 1, 2],
                "responses": {"overall": {"median": {"absolute_error": index + 0.5}}},
            }
            groups.append(
                {
                    "arrival_source": "forecast",
                    "seed": 123,
                    "cutoff_index": index,
                    "cutoff_ms": 1000000 + index * 60000,
                    "horizon_seconds": horizon,
                    "scenarios": count,
                    "execution_seconds": cost,
                    "windows": {"120": window},
                    "arrivals": {
                        "observed_bins": [1] + [0] * 11,
                        "scenario_bins": [[1] + [0] * 11 for _ in range(count)],
                    },
                }
            )
            for scenario in range(count):
                cases.append(
                    {
                        "arrival_source": "forecast",
                        "seed": 123,
                        "cutoff_index": index,
                        "horizon_seconds": horizon,
                        "scenario": scenario,
                        "comparisons": {
                            "120": {"predicted_curve": [0, 1, 3], "target_seconds": 60}
                        },
                    }
                )
    return {
        "split": "validation",
        "run_id": "test-run",
        "period_seconds": 180,
        "groups": groups,
        "cases": cases,
    }


def action_result():
    """Return a complete illustrative action report using the evaluator's existing fixture.

    Returns:
        dict: Standalone saved action metrics.
    """
    return {
        "schema_version": "opendc-evaluation-v1",
        "batches": [{"label": "comparison", "path": "/not-needed-for-rendering"}],
        "cases": comparison_cases(),
    }


class ReportTests(unittest.TestCase):
    """Protect measured denominators, offline rendering and optional section composition."""

    def test_configuration_means_use_common_windows_even_for_cost(self):
        """A candidate's missing observations must exclude that window from all comparisons."""
        rows, cutoffs = comparison_rows(validation_result())
        self.assertEqual(cutoffs, [0, 1])
        self.assertEqual([r["means"]["completion_error"] for r in rows], [2.0, 3.0])
        self.assertEqual([r["means"]["response_error"] for r in rows], [1.0, 1.0])
        self.assertEqual([r["means"]["execution_seconds"] for r in rows], [3.0, 6.0])

    def test_seed_selection_does_not_mix_duplicate_starting_points(self):
        """Extra scenario seeds must not silently replace or double-count primary measurements."""
        result = validation_result()
        extra = copy.deepcopy(result["groups"])
        for group in extra:
            group["seed"] = 456
            group["execution_seconds"] = 100
        result["groups"].extend(extra)
        rows, _ = comparison_rows(result, seed=123)
        other, _ = comparison_rows(result, seed=456)
        self.assertEqual([r["means"]["execution_seconds"] for r in rows], [3.0, 6.0])
        self.assertEqual([r["means"]["execution_seconds"] for r in other], [100.0, 100.0])

    def test_offline_regeneration_preserves_nondefault_forecast_seed(self):
        """Saving all futures must retain the seed actually selected for rendering."""
        result = validation_result()
        extra = copy.deepcopy(result)
        for group in extra["groups"]:
            group["seed"] = 456
        for case in extra["cases"]:
            case["seed"] = 456
        result["groups"].extend(extra["groups"])
        result["cases"].extend(extra["cases"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps({"results": [result]}))
            first = write_report([source], root / "first", seed=456)
            saved = root / "first/metrics.json"
            repeated = write_report([saved], root / "second")
            self.assertEqual(first["validation"], repeated["validation"])
            overridden = write_report([saved], root / "third", seed=123)
            self.assertEqual(overridden["validation"][0]["forecast_seed"], 123)

    def test_missing_values_are_unavailable_instead_of_zero(self):
        """Missing response samples or execution measurements must not improve a mean."""
        result = validation_result()
        result["groups"][0]["execution_seconds"] = None
        result["groups"][0]["windows"]["120"]["responses"]["overall"]["median"][
            "absolute_error"
        ] = None
        rows, _ = comparison_rows(result)
        self.assertIsNone(rows[0]["means"]["response_error"])
        self.assertIsNone(rows[0]["means"]["execution_seconds"])
        self.assertEqual(rows[0]["means"]["completion_error"], 2.0)

    def test_optional_sections_render_without_original_experiment_files(self):
        """Saved action-only, validation-only and combined metrics produce the available pages."""
        payloads = [
            (action_result(), 2),
            ({"results": [validation_result()]}, 2),
            ({"results": [validation_result()], "action_report": action_result()}, 4),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (payload, expected_pages) in enumerate(payloads):
                with self.subTest(pages=expected_pages, index=index):
                    source = root / f"metrics-{index}.json"
                    source.write_text(json.dumps(payload))
                    before = source.read_bytes()
                    output = root / f"report-{index}"
                    write_report([source], output)
                    pdf = (output / "report.pdf").read_bytes()
                    self.assertEqual(len(re.findall(rb"/Type /Page\b", pdf)), expected_pages)
                    self.assertEqual(source.read_bytes(), before)
                    with self.assertRaises(FileExistsError):
                        write_report([source], output)

    def test_split_filter_excludes_other_run_evidence(self):
        """Selecting A must not silently include B in its metrics or produce B's pages."""
        selected = validation_result()
        other = copy.deepcopy(selected)
        other.update(split="held-out", run_id="other-run")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "metrics.json"
            source.write_text(json.dumps({"results": [selected, other]}))
            output = root / "report"
            audit = write_report([source], output, split="validation")
            self.assertEqual([r["run_id"] for r in audit["validation"]], ["test-run"])
            pdf = (output / "report.pdf").read_bytes()
            self.assertEqual(len(re.findall(rb"/Type /Page\b", pdf)), 2)


if __name__ == "__main__":
    unittest.main()
