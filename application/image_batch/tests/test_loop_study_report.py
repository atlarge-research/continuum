"""Supplemental study pages preserve explicit data roles and offline evidence."""

import unittest

from reporting.loop_study import ranking_agreement, ranking_coverage, timeline_segments


class LoopStudyReportTests(unittest.TestCase):
    """Check independent-run aggregation and matched native/observed lifecycle timing."""

    def test_partial_diagnostic_retains_missing_prescribed_cutoffs(self):
        """A failure after the first tick cannot masquerade as a complete four-cutoff study."""
        run = dict(comparisons=[dict(tick=1)])
        self.assertEqual(ranking_coverage(run), dict(missing_ticks=[4, 7, 10], unavailable=3))
        run["comparisons"].append(dict(tick=1))
        with self.assertRaises(ValueError):
            ranking_coverage(run)

    def test_agreement_weights_runs_equally_and_excludes_missing_cutoffs(self):
        """One matching cutoff and three mismatches in another run means50%, not25%."""
        primary = dict(preferred="unchanged", scores=[dict(candidate="unchanged", valid=True)])
        matching = dict(primary=primary, alternate=dict(preferred="unchanged"))
        different = dict(primary=primary, alternate=dict(preferred="scale-down"))
        runs = [
            dict(seed=62, comparisons=[matching, dict(excluded="missing")]),
            dict(seed=63, comparisons=[different, different, different]),
        ]
        result = ranking_agreement(runs, "alternate")
        self.assertEqual(result["mean_run_fraction"], 0.5)
        self.assertEqual(result["scored_cutoffs"], [1, 3])

    def test_choice_coverage_uses_scored_cutoffs_and_valid_not_feasible_candidates(self):
        """Forced agreement and genuine choices stay distinguishable on the same denominator."""
        hold = dict(candidate="unchanged", valid=True, worst_late_fraction=0.0)
        down = dict(candidate="scale-down", valid=True, worst_late_fraction=0.8)
        invalid = dict(candidate="scale-up", valid=False)
        choice = dict(
            primary=dict(preferred="unchanged", scores=[hold, down, invalid]),
            alternate=dict(preferred="unchanged"),
        )
        forced = dict(
            primary=dict(preferred="unchanged", scores=[hold, invalid]),
            alternate=dict(preferred="unchanged"),
        )
        unscored = dict(choice, alternate=dict(preferred=None))
        runs = [
            dict(seed=62, comparisons=[forced, choice, unscored, dict(choice, excluded="bad")]),
            dict(seed=63, comparisons=[forced]),
        ]
        result = ranking_agreement(runs, "alternate")
        self.assertEqual(result["scored_cutoffs"], [2, 1])
        self.assertEqual(result["competing_candidate_cutoffs"], [1, 0])
        self.assertEqual(result["mean_run_fraction"], 1.0)

    def test_predicted_classifier_timeline_keeps_release_separate(self):
        """Native finish minus classifier duration gives start; release is a separate segment."""
        row = dict(
            uid="job",
            original_creation_ms=105000,
            predicted_finish_ms=150000,
            predicted_resource_release_ms=153000,
            modeled_duration_seconds=32,
            observed=dict(start_ms=120000, finish_ms=152000, job_finish_ms=155000),
        )
        result = timeline_segments(row, 100000)
        self.assertEqual(result["predicted"], [5, 18, 50, 53])
        self.assertEqual(result["observed"], [5, 20, 52, 55])
        row.pop("predicted_resource_release_ms")
        self.assertEqual(timeline_segments(row, 100000)["predicted"][-1], 50)


if __name__ == "__main__":
    unittest.main()
