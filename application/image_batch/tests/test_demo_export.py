"""Behavioral checks for portable, whole-scenario demo evidence."""
import json
import tempfile
import unittest
import shutil
import hashlib
from pathlib import Path

from application.image_batch.scripts.demo_export import response_plot, case_metadata, export_bundle


def payload(*, passed=True, arms=("fixed", "forecast", "reactive")):
    """Construct a small, hand-specified accepted analysis case.

    Args:
        passed (bool): Independently derived matched-case qualification.
        arms (tuple): Policies present in this case.

    Returns:
        dict: Portable analysis fixture retaining all original-creation responses.
    """
    runs = []
    summaries = []
    for arm in arms:
        runs.append(
            dict(
                arm=arm,
                seed=72001,
                accepted_capture=True,
                source_hashes={"controller.py": "abc"},
                arrival_plan_sha256="arrival",
                sender_evaluated_window=dict(fidelity_passed=True),
                evaluation_start_seconds=100,
                origin_seconds=0,
                arrival_end_seconds=940,
                responses=dict(
                    jobs=3,
                    cohort=[
                        dict(
                            uid="fast",
                            creation_ms=100000,
                            job_finish_ms=120000,
                            finish_ms=115000,
                            status="Complete",
                        ),
                        dict(
                            uid="late",
                            creation_ms=101000,
                            job_finish_ms=141000 if passed else 251000,
                            finish_ms=130000 if passed else 240000,
                            status="Complete",
                        ),
                        dict(
                            uid="unfinished",
                            creation_ms=102000,
                            job_finish_ms=142000 if passed else None,
                            finish_ms=132000 if passed else None,
                            status="Complete" if passed else "Pending",
                        ),
                    ],
                ),
                allocation=dict(series=[dict(time=100, lower=20, upper=20)]),
                arrival_plan=[dict(planned_offset_ns=100000000000)],
                controller=dict(actions=[], cycles=[]),
            )
        )
        summaries.append(
            dict(
                arm=arm,
                seed=72001,
                jobs=3,
                deadline_fraction=1 if passed else 1 / 3,
                observed_forecast_actions=int(arm == "forecast"),
            )
        )
    return dict(
        runs=runs,
        summary=summaries,
        seed_verdicts=[dict(seed=72001, passed=passed)],
        primary=False,
        ready=False,
        control_examples=[],
    )


class PortableDemoTests(unittest.TestCase):
    """Protect selection transparency and the original evaluated denominator."""

    def test_cdf_retains_late_and_unfinished_jobs_in_denominator(self):
        """A censored job cannot make the completion CDF reach one."""
        plotted = response_plot(payload(passed=False)["runs"][0])
        self.assertEqual(
            plotted["completion_cdf"],
            [dict(seconds=20, fraction=1 / 3), dict(seconds=150, fraction=2 / 3)],
        )
        self.assertEqual([row["within_deadline"] for row in plotted["jobs"]], [True, False, False])
        self.assertEqual(plotted["jobs"][0]["response_seconds"], 20)
        self.assertEqual(plotted["jobs"][0]["classifier_response_seconds"], 15)

    def test_positive_pair_is_not_a_demo_ready_trio(self):
        """A qualifying pair cannot imply a reactive comparison was measured."""
        case = case_metadata("A", 72001, payload(arms=("fixed", "forecast")))
        self.assertFalse(case["complete_trio"])
        self.assertFalse(case["demo_ready"])
        self.assertFalse(case["heldout_validated"])

    def test_unmatched_sources_are_rejected(self):
        """A visually favorable trio cannot pair distinct controller source bytes."""
        data = payload()
        data["runs"][2]["source_hashes"] = {"controller.py": "different"}
        with self.assertRaises(ValueError):
            case_metadata("A", 72001, data)

    def test_export_selects_whole_case_and_preserves_unfavorable_attempts(self):
        """Only a complete case is selected; previous unfavorable runs remain portable."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = []
            for candidate, passed in [("A", False), ("B", True)]:
                analysis = root / candidate
                analysis.mkdir()
                data = payload(
                    passed=passed,
                    arms=("fixed", "forecast")
                    if candidate == "A"
                    else ("fixed", "forecast", "reactive"),
                )
                (analysis / "metrics.json").write_text(json.dumps(data))
                for run in data["runs"]:
                    records.append(
                        dict(
                            candidate=candidate, arm=run["arm"], seed=72001, analysis=str(analysis)
                        )
                    )
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text(
                json.dumps(
                    dict(records=records, attempts=5, status="restored", source_commit="frozen")
                )
            )
            output = root / "bundle"
            export_bundle(checkpoint, output)
            index = json.loads((output / "index.json").read_text())
            self.assertEqual(index["selected_case"], "b-s72001")
            self.assertEqual(len(index["attempts"]), 5)
            self.assertEqual([case["demo_ready"] for case in index["cases"]], [False, True])
            self.assertFalse(index["heldout_validated"])
            selected = json.loads((output / "cases/b-s72001.json").read_text())
            self.assertEqual(
                {run["arm"] for run in selected["runs"]}, {"fixed", "forecast", "reactive"}
            )
            self.assertFalse(selected["ready"])
            self.assertTrue((output / "plots/b-s72001-forecast.json").is_file())
            self.assertEqual(
                len(json.loads((output / "cases/a-s72001.json").read_text())["runs"]), 2
            )

    def test_failed_physical_attempt_remains_inspectable_offline(self):
        """Unavailable original paths must not hide failed attempts or diagnostics."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence"
            evidence.mkdir()
            analysis = evidence / "analysis"
            analysis.mkdir()
            (analysis / "metrics.json").write_text(json.dumps(payload(arms=("fixed", "forecast"))))
            failure = evidence / "failure.json"
            failure.write_text(json.dumps(dict(error="HTTP503 and reset", may_continue=False)))
            reconciliation = evidence / "reconciliation.json"
            reconciliation.write_text(json.dumps(dict(accepted_capture=False, physical_attempt=3)))
            records = [
                dict(candidate="A", arm=arm, seed=72001, analysis=str(analysis))
                for arm in ("fixed", "forecast")
            ]
            checkpoint = evidence / "checkpoint.json"
            checkpoint.write_text(
                json.dumps(
                    dict(
                        records=records,
                        attempts=3,
                        status="restored",
                        failed_attempts=[
                            dict(
                                attempt=3,
                                candidate="B",
                                arm="fixed",
                                seed=72001,
                                accepted_capture=False,
                                failure=str(failure),
                                reconciliation=str(reconciliation),
                            )
                        ],
                    )
                )
            )
            output = root / "bundle"
            export_bundle(checkpoint, output)
            shutil.rmtree(evidence)
            index = json.loads((output / "index.json").read_text())
            self.assertEqual(len(index["attempts"]), 3)
            self.assertEqual([row["attempt"] for row in index["attempts"]], [1, 2, 3])
            failed = index["attempts"][2]
            self.assertEqual(failed["status"], "failed")
            self.assertFalse(failed["accepted_capture"])
            relative = failed["failure_evidence"]["failure"]
            self.assertFalse(Path(relative).is_absolute())
            self.assertEqual(
                json.loads((output / relative).read_text())["error"], "HTTP503 and reset"
            )
            hashes = json.loads((output / "sha256.json").read_text())
            self.assertEqual(
                hashes[relative], hashlib.sha256((output / relative).read_bytes()).hexdigest()
            )
            self.assertIsNone(index["selected_case"])


if __name__ == "__main__":
    unittest.main()
