"""Physical allocation and deadline metrics retain gaps and unfinished Jobs."""

import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from forecast_trace import iso
import test_closed_loop_guards as guard_fixtures


class EvidenceTests(unittest.TestCase):
    """Hand-computed traces separate accepting/draining allocation from powered capacity."""

    def module(self):
        """Load production evidence calculations.

        Returns:
            module: Closed-loop metrics implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_evidence"))
        return importlib.import_module("closed_loop_evidence")

    def test_draining_costs_until_release_and_reserves_stay_powered(self):
        """Cordon at3s and completion at5s yield45core-seconds, not39 or90."""
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        states = []
        for second in range(11):
            state = copy.deepcopy(fixture.snapshot)
            state["timestamp"] = iso((1000 + second) * 1000)
            state["collection"]["started_at"] = state["timestamp"]
            state["workers"][1]["schedulable"] = second < 3
            if second < 5:
                state["jobs"]["active"] = [fixture.job(node="w2")]
            states.append(state)
        result = self.module().allocation(states, fixture.config, 1000, 1010)
        self.assertEqual(result["allocated_application_core_seconds"], 45)
        self.assertEqual(result["powered_worker_seconds"], 30)
        self.assertEqual(result["covered_seconds"], 10)
        self.assertEqual(result["gaps"], [])

    def test_state_gap_does_not_become_zero_allocation_or_a_cheap_winner(self):
        """A five-second unknown interval suppresses the complete allocation total."""
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        states = []
        for second in [0, 1, 2, 7, 8, 9, 10]:
            state = copy.deepcopy(fixture.snapshot)
            state["timestamp"] = iso((1000 + second) * 1000)
            state["collection"]["started_at"] = state["timestamp"]
            states.append(state)
        result = self.module().allocation(states, fixture.config, 1000, 1010)
        self.assertIsNone(result["allocated_application_core_seconds"])
        self.assertEqual(result["covered_seconds"], 5)
        self.assertTrue(result["gaps"])

    def test_deadline_uses_job_completion_and_retains_censoring(self):
        """Fast classifier exit cannot hide late resource release or missing terminal outcomes."""
        rows = [
            dict(
                uid="a",
                creation_ms=1000000,
                finish_ms=1100000,
                job_finish_ms=1121000,
                status="Complete",
            ),
            dict(
                uid="b",
                creation_ms=1001000,
                finish_ms=1050000,
                job_finish_ms=1051000,
                status="Complete",
            ),
            dict(
                uid="c",
                creation_ms=1002000,
                finish_ms=None,
                job_finish_ms=None,
                status="unfinished",
            ),
            dict(
                uid="warmup",
                creation_ms=999000,
                finish_ms=1010000,
                job_finish_ms=1011000,
                status="Complete",
            ),
        ]
        result = self.module().responses(rows, 1000000, 1060000)
        self.assertEqual(result["jobs"], 3)
        self.assertEqual(result["deadline_met"], 1)
        self.assertEqual(result["deadline_fraction"], 1 / 3)
        self.assertEqual(result["censored_uids"], ["c"])
        self.assertEqual(result["warmup_backlog_uids"], ["warmup"])
        self.assertEqual(result["completed_responses_seconds"], [121, 50])

    def test_missing_job_membership_does_not_obscure_a_fully_accepting_pool(self):
        """All powered workers accepting means allocation is known even during a Job-list race."""
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        states = []
        for second in range(3):
            state = copy.deepcopy(fixture.snapshot)
            state["timestamp"] = iso((1000 + second) * 1000)
            state["collection"]["started_at"] = state["timestamp"]
            state["collection"]["missing_job_uids"] = ["new-job"]
            for worker in state["workers"]:
                worker["schedulable"] = True
            states.append(state)
        result = self.module().allocation(states, fixture.config, 1000, 1002)
        self.assertEqual(result["allocated_application_core_seconds"], 18)
        self.assertEqual(result["allocated_core_seconds_bounds"], [18, 18])
        self.assertEqual(result["incomplete_membership_snapshots"], 3)

    def test_reconciled_result_remains_attached_to_its_original_intent(self):
        """An action acknowledged after restart is not lost or attributed to a second request."""
        records = [
            dict(event="cycle.begin", tick=1, started_at=1000),
            dict(event="action.request", action_id="a", action="scale-down"),
            dict(event="cycle.end", tick=1, outcome="vetoed_or_failed", forecast_valid=False),
            dict(event="cycle.begin", tick=2, started_at=1060),
            dict(event="action.result", action_id="a", status="observed_applied"),
            dict(event="cycle.end", tick=2, outcome="held", forecast_valid=True),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in records))
            result = self.module().controller_outcomes(root, 1000, 1120)
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["result"]["status"], "observed_applied")
        self.assertEqual(result["actions"][0]["tick"], 1)
        self.assertEqual(result["observed_down"], 0)

    def test_skipped_cadence_breaks_consecutive_valid_cycles(self):
        """Three valid outputs with a skipped decision between them are not a three-cycle streak."""
        records = []
        for tick, started in [(1, 1000), (2, 1120), (3, 1180)]:
            records.extend(
                [
                    dict(event="cycle.begin", tick=tick, started_at=started),
                    dict(event="cycle.end", tick=tick, outcome="held", forecast_valid=True),
                ]
            )
            if tick == 1:
                records.append(dict(event="cycle.skipped", count=1))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in records))
            result = self.module().controller_outcomes(root, 1000, 1240)
        self.assertEqual(result["longest_consecutive_valid_cycles"], 2)

    def test_job_failed_before_evaluation_is_not_live_warmup_backlog(self):
        """Failure observed before the scoring boundary is a terminal outcome."""
        result = self.module().responses(
            [
                dict(
                    uid="failed",
                    creation_ms=900000,
                    job_finish_ms=None,
                    failure_observed_ms=990000,
                    status="Failed",
                )
            ],
            1000000,
            1060000,
        )
        self.assertEqual(result["warmup_backlog_uids"], [])

    def test_followup_boundary_censors_late_completion_but_keeps_earlier_terminal_time(self):
        """Observer drain must not extend the declared ten-minute follow-up."""
        rows = [
            dict(uid="early", creation_ms=1000000, job_finish_ms=1100000, status="Complete"),
            dict(uid="late", creation_ms=1001000, job_finish_ms=1700000, status="Complete"),
            dict(
                uid="failed-late",
                creation_ms=1002000,
                job_finish_ms=None,
                failure_observed_ms=1700000,
                status="Failed",
            ),
        ]
        result = self.module().responses(rows, 1000000, 1060000, followup_end_ms=1660000)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["censored_uids"], ["late", "failed-late"])
        self.assertEqual(result["failed_uids"], [])
        self.assertEqual(result["cohort"][1]["status"], "unfinished")

    def test_sender_inventory_requires_per_request_evidence_and_matching_job(self):
        """Summary counts alone cannot validate a truncated or mismatched arrival stream."""
        summary = dict(
            planned_count=1,
            attempted_count=1,
            successful_count=1,
            failed_count=0,
            on_time_count=1,
            on_time_fraction=1,
        )
        details = dict(
            endpoint_batch_id="batch",
            batch_index=0,
            planned_offset_ns=1,
            image_count=4,
            payload_bytes=100,
            schedule_lag_ns=2,
        )
        events = [
            dict(
                event_type=kind,
                run_id="run",
                request_id="req",
                details={**details, "job_name": "job"},
            )
            for kind in ("schedule.planned", "batch.send_started", "batch.receipt_received")
        ]
        jobs = [
            dict(
                metadata=dict(
                    name="job",
                    annotations={"continuum.atlarge.nl/endpoint-batch-id": "batch"},
                    labels={"continuum.atlarge.nl/request-id": "req"},
                )
            )
        ]
        module = self.module()
        self.assertEqual(module.sender_inventory(events, jobs, summary, "run"), [])
        self.assertTrue(module.sender_inventory([], jobs, summary, "run"))
        bad = copy.deepcopy(events)
        bad[-1]["request_id"] = "wrong"
        self.assertTrue(module.sender_inventory(bad, jobs, summary, "run"))
        self.assertTrue(module.sender_inventory(events + [events[0]], jobs, summary, "run"))
