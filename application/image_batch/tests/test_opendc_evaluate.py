"""Check offline evaluation semantics against hand-calculated evidence."""
import copy
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_evaluate import (  # pylint: disable=C0413
    _resources,
    _draw_band,
    _finish_axes,
    _prepare_comparisons,
    display_comparison,
    _validate_analytical_empty,
    analyze_case,
    aggregate_actions,
    load_batch,
    render_pdf,
    main,
)
from opendc_inputs import file_hashes  # pylint: disable=C0413


def evaluation_case(tasks=True):
    """Return a compact provisional case with exact expected timings.

    Args:
        tasks (bool): Include the three-task response-time fixture.

    Returns:
        dict: Case metadata accepted by the evaluator.
    """
    items = []
    if tasks:
        items = [
            {
                "task": {"id": 1, "submission_time": 0},
                "metadata": {"cohort": "backlog", "original_creation_ms": 997000},
            },
            {
                "task": {"id": 2, "submission_time": 4000},
                "metadata": {"cohort": "future", "original_creation_ms": 1004000},
            },
            {
                "task": {"id": 3, "submission_time": 7000},
                "metadata": {"cohort": "future", "original_creation_ms": 1007000},
            },
        ]
    return {
        "candidate": "unchanged",
        "scenario": 7,
        "scope": "complete",
        "cutoff_ms": 1000000,
        "horizon_ms": 10000 if tasks else 5000,
        "tasks": items,
        "workers": [{"node_name": "worker-0", "idle_power_w": 10}],
        "omitted_tasks": [{"id": 80}, {"id": 81}],
        "model_exhausted_jobs": [{"id": 90}, {"id": 91}, {"id": 92}],
    }


def completions():
    """Return exact terminal records for the response fixture.

    Returns:
        list[dict]: Three completion records in simulator-relative milliseconds.
    """
    return [
        {"task_id": 1, "finish_time": 2000},
        {"task_id": 2, "finish_time": 8000},
        {"task_id": 3, "finish_time": 9000},
    ]


def comparison_cases(count=3):
    """Create independent literal curves on unequal time grids.

    Args:
        count (int): Number of matched futures for each action.

    Returns:
        list[dict]: Evaluated cases with literal curves and response samples.
    """
    cases = []
    for action in ("unchanged", "scale-up", "scale-down"):
        for index in range(count):
            case = analyze_case(evaluation_case(tasks=False), [], [], analytical_empty=True)
            case.update(
                candidate=action,
                scenario=index,
                scope=("remaining_workers_only" if action == "scale-down" else "complete"),
                batch_label="comparison",
                experiment_kind="synthetic-test",
            )
            case["included_idle_power_w"] = 10
            times, energy, completed = [
                ([0, 2, 4], [0, 20, 40], [0, 1, 2]),
                ([0, 4, 6], [0, 80, 120], [0, 1, 2]),
                ([0, 2, 6], [0, 60, 180], [0, 3, 4]),
            ][index % 3]
            case["curves"] = {
                "time_seconds": times,
                "energy_joules": energy,
                "completed_tasks": completed,
                "unfinished_tasks": [0, 1, 0],
            }
            samples = [[1, 3], [10] * 10, [20, 40]][index % 3]
            case["windows"]["cohort_through_completion"]["cohorts"]["future"][
                "response_samples_seconds"
            ] = samples
            cases.append(case)
    return cases


class EvaluationTests(unittest.TestCase):
    """Protect the two interpretation windows and immutable evidence checks."""

    def test_release_occupancy_is_separate_from_classifier_response(self):
        """Observed classifier completion and predicted slot release have distinct endpoints."""
        case = evaluation_case()
        case["tasks"] = case["tasks"][:1]
        case["tasks"][0]["metadata"].update(
            phase="release",
            occupancy={
                "release_only": True,
                "observed_classifier_finish_ms": 999000,
                "release_ms": 0,
                "classifier_profile_ms": 0,
            },
        )
        series = {
            "worker-0": {
                "samples": [(0, 0), (20000, 200)],
                "idle_power_w": 10,
                "native_last_timestamp_ms": 20000,
            }
        }
        with patch("opendc_evaluate._energy_series", return_value=series):
            result = analyze_case(case, [{"task_id": 1, "finish_time": 1000}], [])
        cohort = result["windows"]["cohort_through_completion"]["cohorts"]["backlog"]
        self.assertEqual(cohort["response_seconds"]["mean"], 2)
        self.assertEqual(result["lifecycles"][0]["resource_release_response_seconds"], 4)
        self.assertEqual(result["boundaries"]["last_resource_release_seconds"], 1)

    def test_saved_metrics_render_without_loading_original_experiments(self):
        """Allow report-only changes with unavailable raw evidence and preserve the reference."""
        report = {
            "schema_version": "opendc-evaluation-v1",
            "batches": [{"label": "comparison", "path": "/unavailable/batch"}],
            "cases": comparison_cases(),
            "presentation": {"reference_batch": "comparison"},
        }
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "metrics.json"
            source.write_text(json.dumps(report))
            output = Path(root) / "report"
            with patch(
                "opendc_evaluate.evaluate_batches", side_effect=AssertionError("raw reload")
            ):
                self.assertEqual(
                    main(["--metrics-file", str(source), "--output-dir", str(output)]), 0
                )
            self.assertEqual((output / "report.pdf").read_bytes()[:4], b"%PDF")
            rendered = json.loads((output / "metrics.json").read_text())
            self.assertEqual(rendered["cases"], report["cases"])
            self.assertEqual(rendered["presentation"]["reference_batch"], "comparison")
            self.assertNotIn("reference_summary", rendered)

    def test_axis_limits_are_even_ticks_and_cover_all_shared_data(self):
        """Round limits outward without clipping a larger alternative or changing curves."""
        figure, axes = plt.subplots(1, 2, sharey=True)
        try:
            axes[0].plot([0, 198], [0, 63])
            axes[1].plot([0, 198], [0, 73])
            for axis in axes:
                _finish_axes(axis)
                for limits, ticks in (
                    (axis.get_xlim(), axis.get_xticks()),
                    (axis.get_ylim(), axis.get_yticks()),
                ):
                    self.assertEqual(limits, (ticks[0], ticks[-1]))
                    self.assertEqual(limits[0], 0)
                    spacing = ticks[1] - ticks[0]
                    for first, second in zip(ticks, ticks[1:]):
                        self.assertAlmostEqual(second - first, spacing)
                self.assertGreaterEqual(axis.get_xlim()[1], 198)
                self.assertGreaterEqual(axis.get_ylim()[1], 73)
            self.assertEqual(axes[0].get_ylim(), axes[1].get_ylim())
            self.assertEqual(list(axes[0].lines[0].get_xdata()), [0, 198])
        finally:
            plt.close(figure)

    def test_display_smoothing_preserves_exact_metrics_and_orders_the_band(self):
        """Smooth only the plotted distribution, on a regular grid with nonnegative counts."""
        cases = comparison_cases()
        before = copy.deepcopy(cases)
        exact = aggregate_actions(cases)
        exact_before = copy.deepcopy(exact)
        smooth = display_comparison(cases, exact, smoothing_seconds=0.5)
        self.assertEqual(cases, before)
        self.assertEqual(exact, exact_before)
        self.assertEqual(smooth["time_seconds"][0], 0)
        self.assertEqual(smooth["time_seconds"][-1], 6)
        self.assertNotEqual(
            smooth["actions"]["unchanged"]["curves"]["completed_tasks"],
            exact["actions"]["unchanged"]["curves"]["completed_tasks"],
        )
        for action in smooth["actions"].values():
            for metric in ("completed_tasks", "unfinished_tasks"):
                band = action["curves"][metric]
                for lower, median, upper in zip(band["minimum"], band["median"], band["maximum"]):
                    self.assertTrue(0 <= lower <= median <= upper <= 4)
            completed = action["curves"]["completed_tasks"]["median"]
            self.assertTrue(all(a <= b for a, b in zip(completed, completed[1:])))
            self.assertTrue(any(0 < value < 1 for value in completed))
        with self.assertRaises(ValueError):
            display_comparison(cases, exact, smoothing_seconds=0)

    def test_outlined_bands_use_exact_horizontal_limits(self):
        """Expose both range boundaries and prevent automatic horizontal padding."""
        figure, axis = plt.subplots()
        try:
            _draw_band(
                axis,
                [0, 10],
                {"minimum": [0, 1], "median": [0, 2], "maximum": [0, 3]},
                "unchanged",
                "complete",
            )
            self.assertEqual(axis.get_xlim(), (0, 10))
            self.assertEqual(len(axis.lines), 3)
            self.assertEqual(sorted(line.get_ydata()[-1] for line in axis.lines), [1, 2, 3])
        finally:
            plt.close(figure)

    def test_reference_input_is_selected_explicitly_without_ranking_actions(self):
        """Respect the reference batch rather than file order or simulated performance."""
        first = comparison_cases()
        second = copy.deepcopy(first)
        for case in second:
            case["batch_label"] = "second"
        report = {
            "batches": [
                {"label": "comparison", "path": "/first"},
                {"label": "second", "path": "/second"},
            ],
            "cases": first + second,
        }
        ordered, _ = _prepare_comparisons(report, Path("/second"))
        self.assertEqual([entry[0]["label"] for entry in ordered], ["second", "comparison"])
        with self.assertRaises(ValueError):
            _prepare_comparisons(report, Path("/absent"))

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.pdf"
            original_cases = copy.deepcopy(report["cases"])
            render_pdf(report, path, Path("/second"))
            self.assertEqual(path.read_bytes()[:4], b"%PDF")
            self.assertEqual(len(re.findall(rb"/Type /Page\b", path.read_bytes())), 2)
            self.assertEqual(
                report["action_comparisons"][0],
                {"batch_label": "second", **aggregate_actions(second)},
            )
            self.assertEqual(report["presentation"]["reference_batch"], "second")
            self.assertEqual(report["cases"], original_cases)

    def test_action_bands_align_times_without_inventing_early_completions(self):
        """Catch pooling curves, linear count interpolation, or freezing ended-host energy."""
        result = aggregate_actions(comparison_cases())
        self.assertEqual(result["time_seconds"], [0, 2, 4, 6])
        action = result["actions"]["unchanged"]
        self.assertEqual(action["curves"]["energy_joules"]["median"], [0, 40, 80, 120])
        self.assertEqual(action["curves"]["energy_joules"]["minimum"], [0, 20, 40, 60])
        self.assertEqual(action["curves"]["energy_joules"]["maximum"], [0, 60, 120, 180])
        self.assertEqual(action["curves"]["completed_tasks"]["minimum"], [0, 0, 1, 2])
        self.assertEqual(action["curves"]["completed_tasks"]["median"], [0, 1, 2, 2])
        self.assertEqual(result["actions"]["scale-down"]["scope"], "remaining_workers_only")

    def test_response_bands_give_each_scenario_equal_weight(self):
        """Catch pooling Jobs across scenarios with unequal numbers of completions."""
        result = aggregate_actions(comparison_cases())
        response = result["actions"]["unchanged"]["responses"]["future"]
        self.assertEqual(response["median"][50], 10)
        self.assertEqual(response["minimum"][50], 2)
        self.assertEqual(response["maximum"][50], 30)
        self.assertEqual(response["median"][100], 10)
        self.assertIsNone(result["actions"]["unchanged"]["responses"]["backlog"])

    def test_overall_response_combines_jobs_within_each_scenario(self):
        """Do not average cohort percentiles or pool Jobs across unequal-sized futures."""
        cases = comparison_cases()
        for case in cases:
            cohorts = case["windows"]["cohort_through_completion"]["cohorts"]
            cohorts["backlog"]["response_samples_seconds"] = [100]
        result = aggregate_actions(cases)
        # Per-future combined medians: 3, 10, 40; each future still has equal weight.
        overall = result["actions"]["unchanged"]["responses"]["all"]
        self.assertEqual(overall["median"][50], 10)
        self.assertEqual(overall["minimum"][50], 3)
        self.assertEqual(overall["maximum"][50], 40)
        self.assertEqual(overall["maximum"][-1], 100)
        empty_backlog = aggregate_actions(comparison_cases())["actions"]["unchanged"]
        self.assertEqual(empty_backlog["responses"]["all"], empty_backlog["responses"]["future"])

    def test_twenty_scenarios_use_all_samples_and_preserve_even_sample_median(self):
        """Catch assumptions that there are exactly three sampled futures."""
        cases = comparison_cases(20)
        for case in cases:
            case["curves"]["time_seconds"] = [0, 2]
            case["curves"]["energy_joules"] = [0, case["scenario"] * 10]
            case["curves"]["completed_tasks"] = [0, 0]
            case["curves"]["unfinished_tasks"] = [0, 0]
        result = aggregate_actions(cases)
        self.assertEqual(result["scenario_count"], 20)
        band = result["actions"]["scale-up"]["curves"]["energy_joules"]
        self.assertEqual(
            (band["minimum"][-1], band["median"][-1], band["maximum"][-1]), (0, 95, 190)
        )

    def test_action_comparison_rejects_unmatched_scenarios_or_boundaries(self):
        """Do not silently compare different futures, duplicate cases or cutoffs."""
        cases = comparison_cases()
        for invalid in (cases[:-1], cases + [copy.deepcopy(cases[0])]):
            with self.assertRaises(ValueError):
                aggregate_actions(invalid)
        cases[-1]["boundaries"]["evaluation_seconds"] = 99
        with self.assertRaises(ValueError):
            aggregate_actions(cases)

    def test_windows_use_original_wait_and_separate_future_inventory(self):
        """Catch lost backlog wait, post-E unfinished counts, and energy endpoint errors."""
        metrics = analyze_case(
            evaluation_case(),
            completions(),
            [
                {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
                {"host_name": "worker-0", "timestamp": 4000, "energy_usage": 40.0},
                {"host_name": "worker-0", "timestamp": 8000, "energy_usage": 120.0},
                {"host_name": "worker-0", "timestamp": 9000, "energy_usage": 130.0},
            ],
            evaluation_seconds=5,
        )

        fixed = metrics["windows"]["fixed_window"]
        self.assertEqual(fixed["tasks"], {"completed": 1, "unfinished": 1, "not_yet_arrived": 1})
        self.assertEqual(fixed["energy_joules"], 60.0)
        self.assertEqual(fixed["cohorts"]["backlog"]["response_seconds"]["p50"], 5.0)
        self.assertEqual(fixed["cohorts"]["future"]["response_seconds"]["samples"], 0)
        self.assertTrue(fixed["response_statistics_censored"])

        follow = metrics["windows"]["cohort_through_completion"]
        self.assertEqual(follow["tasks"], {"completed": 3, "unfinished": 0})
        self.assertEqual(follow["end_seconds"], 10.0)
        self.assertEqual(follow["energy_joules"], 140.0)
        self.assertEqual(follow["cohorts"]["future"]["response_seconds"]["p50"], 3.0)
        self.assertEqual(metrics["inventory"]["omitted_tasks"], 2)
        self.assertEqual(metrics["inventory"]["model_exhausted_jobs"], 3)

    def test_empty_case_extends_native_energy_at_configured_idle_power(self):
        """Catch treating an empty workload as zero energy after native output ends."""
        metrics = analyze_case(
            evaluation_case(tasks=False),
            [],
            [
                {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
                {"host_name": "worker-0", "timestamp": 2000, "energy_usage": 20.0},
            ],
            evaluation_seconds=None,
        )

        self.assertEqual(metrics["windows"]["fixed_window"]["energy_joules"], 50.0)
        self.assertEqual(metrics["windows"]["cohort_through_completion"]["energy_joules"], 50.0)
        self.assertEqual(metrics["windows"]["fixed_window"]["tasks"]["completed"], 0)

    def test_delayed_native_origin_includes_analytical_pre_arrival_idle(self):
        """Catch treating OpenDC's first-arrival clock origin as the scenario cutoff."""
        case = evaluation_case(tasks=False)
        case["horizon_ms"] = 8000
        case["tasks"] = [
            {
                "task": {"id": 4, "submission_time": 5000},
                "metadata": {"cohort": "future", "original_creation_ms": 1005000},
            }
        ]
        metrics = analyze_case(
            case,
            [{"task_id": 4, "finish_time": 7000}],
            [
                {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
                {"host_name": "worker-0", "timestamp": 2000, "energy_usage": 20.0},
            ],
            evaluation_seconds=4,
            native_time_origin_ms=5000,
        )

        fixed = metrics["windows"]["fixed_window"]
        self.assertEqual(fixed["energy_joules"], 40.0)
        self.assertEqual(fixed["tasks"], {"completed": 0, "unfinished": 0, "not_yet_arrived": 1})
        self.assertEqual(metrics["windows"]["cohort_through_completion"]["energy_joules"], 80.0)
        self.assertEqual(metrics["boundaries"]["native_time_origin_seconds"], 5.0)

    def test_analytical_empty_case_uses_idle_only_without_native_tables(self):
        """Catch requiring fabricated OpenDC output for an explicitly analytical empty case."""
        metrics = analyze_case(
            evaluation_case(tasks=False),
            [],
            [],
            evaluation_seconds=None,
            analytical_empty=True,
        )

        self.assertEqual(metrics["windows"]["fixed_window"]["energy_joules"], 50.0)
        self.assertEqual(metrics["energy_evidence_kind"], "analytical_idle_only_no_opendc_process")

    def test_conflicting_duplicate_host_energy_is_rejected(self):
        """Catch ambiguous cumulative readings instead of silently choosing one."""
        rows = [
            {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
            {"host_name": "worker-0", "timestamp": 2000, "energy_usage": 20.0},
            {"host_name": "worker-0", "timestamp": 2000, "energy_usage": 21.0},
        ]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            analyze_case(evaluation_case(tasks=False), [], rows, evaluation_seconds=5)

    def test_native_host_energy_must_cover_latest_completion(self):
        """Catch replacing native energy with idle power while a task is still running."""
        rows = [
            {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
            {"host_name": "worker-0", "timestamp": 8000, "energy_usage": 120.0},
        ]
        with self.assertRaisesRegex(ValueError, "completion"):
            analyze_case(evaluation_case(), completions(), rows, evaluation_seconds=5)

    def test_each_included_host_needs_its_own_native_energy_samples(self):
        """Catch treating an absent included host as a zero-energy baseline."""
        case = evaluation_case(tasks=False)
        case["workers"].append({"node_name": "worker-1", "idle_power_w": 10})
        rows = [
            {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
            {"host_name": "worker-0", "timestamp": 2000, "energy_usage": 20.0},
        ]
        with self.assertRaisesRegex(ValueError, "worker-1"):
            analyze_case(case, [], rows, evaluation_seconds=5)

    def test_batch_inventory_must_exactly_match_suite_inventory(self):
        """Catch missing, extra, and duplicate experiments under a success label."""
        suite = [
            {"candidate": "unchanged", "scenario": 0, "input_dir": "suite/a"},
            {"candidate": "scale-down", "scenario": 0, "input_dir": "suite/b"},
        ]
        completed = [{**item, "status": "succeeded", "validated": True} for item in suite]
        variants = {
            "missing": completed[:1],
            "extra": completed
            + [
                {
                    "candidate": "unchanged",
                    "scenario": 1,
                    "input_dir": "suite/c",
                    "status": "succeeded",
                    "validated": True,
                }
            ],
            "duplicate": [completed[0], completed[0]],
        }
        with tempfile.TemporaryDirectory() as root:
            batch_dir = Path(root)
            (batch_dir / "evidence.txt").write_text("immutable")
            record = {
                "contract": "opendc-batch-v1",
                "status": "succeeded",
                "remaining_experiments": 0,
                "suite_manifest": {"experiments": suite},
                "experiments": completed,
                "sha256": file_hashes(batch_dir, exclude=("batch.json",)),
            }
            (batch_dir / "batch.json").write_text(json.dumps(record))
            self.assertEqual(load_batch(batch_dir)[1]["experiments"], completed)
            for name, experiments in variants.items():
                with self.subTest(name=name):
                    record["experiments"] = experiments
                    (batch_dir / "batch.json").write_text(json.dumps(record))
                    with self.assertRaisesRegex(ValueError, "inventory"):
                        load_batch(batch_dir)

            record["experiments"] = completed
            record["remaining_experiments"] = 1
            (batch_dir / "batch.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "remaining"):
                load_batch(batch_dir)

    def test_analytical_empty_requires_no_process_contract_and_no_native_output(self):
        """Catch relabeling conventional or stale simulator evidence as analytical empty."""
        process = {
            "execution_kind": "analytical_empty",
            "launched": False,
            "exit_code": 0,
            "timed_out": False,
            "received_signal": None,
            "launch_error": None,
            "wall_seconds": 0,
            "cpu_total_seconds": 0,
            "peak_rss_bytes": 0,
        }
        case = evaluation_case(tasks=False)
        with tempfile.TemporaryDirectory() as root:
            run_dir = Path(root)
            _validate_analytical_empty(run_dir, {"process": process}, case)
            (run_dir / "resources.json").write_text(json.dumps(process))
            resources, _ = _resources(run_dir, {"process": process})
            self.assertEqual(resources["actual_cgroup_cpu_seconds"], 0.0)
            self.assertEqual(resources["actual_max_rss_bytes"], 0.0)

            for field, invalid in (
                ("execution_kind", "native"),
                ("launched", True),
                ("launched", 0),
                ("exit_code", 1),
            ):
                with self.subTest(field=field):
                    changed = {**process, field: invalid}
                    with self.assertRaisesRegex(ValueError, "process"):
                        _validate_analytical_empty(run_dir, {"process": changed}, case)

            (run_dir / "simulator").mkdir()
            with self.assertRaisesRegex(ValueError, "native simulator"):
                _validate_analytical_empty(run_dir, {"process": process}, case)

    def test_failed_and_tampered_batches_are_rejected(self):
        """Catch evaluating failed or mutated evidence as if it were successful."""
        with tempfile.TemporaryDirectory() as root:
            batch_dir = Path(root)
            (batch_dir / "evidence.txt").write_text("original")
            record = {
                "contract": "opendc-batch-v1",
                "status": "failed",
                "experiments": [],
                "sha256": file_hashes(batch_dir, exclude=("batch.json",)),
            }
            (batch_dir / "batch.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "succeeded"):
                load_batch(batch_dir)

            record["status"] = "succeeded"
            record["experiments"] = [{"status": "succeeded", "validated": True}]
            (batch_dir / "batch.json").write_text(json.dumps(record))
            (batch_dir / "evidence.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "hash"):
                load_batch(batch_dir)

    def test_pdf_smoke_has_pdf_signature(self):
        """Catch report rendering failures at the artifact boundary."""
        case_metrics = analyze_case(
            evaluation_case(),
            completions(),
            [
                {"host_name": "worker-0", "timestamp": 0, "energy_usage": 0.0},
                {"host_name": "worker-0", "timestamp": 8000, "energy_usage": 120.0},
                {"host_name": "worker-0", "timestamp": 9000, "energy_usage": 130.0},
            ],
            evaluation_seconds=5,
        )
        report = {
            "schema_version": "opendc-evaluation-v1",
            "interpretation": {
                "fixed_window": (
                    "Released tasks observed through E; response samples are completions."
                ),
                "cohort_through_completion": (
                    "Backlog and arrivals before H followed to completion."
                ),
            },
            "batches": [{"label": "batch-1", "path": "/evidence/batch-1", "cases": 1}],
            "cases": [
                {
                    **case_metrics,
                    "batch_label": "batch-1",
                    "experiment_kind": "response-fixture",
                    "candidate": "unchanged",
                    "scenario": 7,
                    "scope": "complete",
                    "resources": {},
                    "missing_components": [],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.pdf"
            render_pdf(report, path)
            self.assertEqual(path.read_bytes()[:4], b"%PDF")


if __name__ == "__main__":
    unittest.main()
