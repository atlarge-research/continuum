"""Physical activation clocks and capacity costs remain separate from API acknowledgments."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from acquisition_evidence import acquisition_history, acquisition_audit, charge_acquisitions
from closed_loop_evidence import allocation, controller_outcomes
from forecast_trace import iso
from closed_loop_diagnostics import cycle_diagnostic
from reporting.closed_loop import acquisition_rows, acquisition_series
import test_closed_loop_guards as guard_fixtures


def records(observed=1007):
    """Return a delayed scale-up requested at1001 and due at1006.

    Args:
        observed (float or None): Availability confirmation; None retains an unfinished acquisition.

    Returns:
        list[dict]: Literal journal records with explicit lifecycle boundaries.
    """
    rows = [
        dict(event="cycle.begin", tick=1, started_at=1000),
        dict(
            event="cycle.proposal",
            tick=1,
            cutoff_seconds=1000,
            shadow=False,
            proposal={"action": "scale-up", "selected_worker": "w3"},
            before={},
        ),
        dict(
            event="activation.request",
            activation_id="a",
            selected_worker="w3",
            node_uid="uid-w3",
            requested_at_seconds=1001,
            ready_at_seconds=1006,
            acquisition_seconds=5,
            requested_application_cores=3,
        ),
        dict(
            event="cycle.end",
            tick=1,
            outcome="activation_requested",
            forecast_valid=True,
            elapsed_seconds=1,
            history={},
        ),
    ]
    if observed is not None:
        rows.extend(
            [
                dict(
                    event="activation.dispatch",
                    activation_id="a",
                    selected_worker="w3",
                    dispatched_at_seconds=1006,
                ),
                dict(
                    event="action.request",
                    action_id="api",
                    action="scale-up",
                    selected_worker="w3",
                    node_uid="uid-w3",
                ),
                dict(
                    event="action.result",
                    action_id="api",
                    status="acknowledged",
                    last_action_at=1006,
                ),
                dict(
                    event="activation.api_result",
                    activation_id="a",
                    action_id="api",
                    status="acknowledged",
                ),
                dict(
                    event="activation.result",
                    activation_id="a",
                    selected_worker="w3",
                    status="observed",
                    observed_at_seconds=observed,
                ),
            ]
        )
    for index, row in enumerate(rows):
        row["sequence"] = index
        row["recorded_at_ns"] = round((1000 + index / 10) * 1e9)
    return rows


class AcquisitionEvidenceTests(unittest.TestCase):
    """Hand-derived costs validate request-boundary integration and deduplication."""

    def states(self, accepting_from=1007):
        """Create eleven one-second snapshots with a controlled activation boundary.

        Args:
            accepting_from (float): First observer time admitting on the reserve.

        Returns:
            tuple[list[dict], dict]: Physical snapshots and configured three-worker capacity.
        """
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        states = []
        for at in range(1000, 1011):
            state = copy.deepcopy(fixture.snapshot)
            state["timestamp"] = state["collection"]["started_at"] = iso(at * 1000)
            state["workers"][2]["schedulable"] = at >= accepting_from
            states.append(state)
        return states, fixture.config

    def test_pending_cost_starts_at_request_and_is_not_double_counted_after_availability(self):
        """Base69 plus18 pending core-seconds yields87 across the ten-second window."""
        states, config = self.states()
        result = allocation(states, config, 1000, 1010, activation_records=records())
        self.assertEqual(result["accepting_draining_core_seconds_bounds"], [69, 69])
        self.assertEqual(result["pending_acquisition_core_seconds_bounds"], [18, 18])
        self.assertEqual(result["allocated_core_seconds_bounds"], [87, 87])
        self.assertEqual(result["allocated_application_core_seconds"], 87)

    def test_request_between_snapshots_is_integrated_at_exact_journal_time(self):
        """A1001.5 request charges16.5 pending core-seconds, without rounding to a sample."""
        states, config = self.states()
        rows = records()
        rows[2]["requested_at_seconds"] = 1001.5
        rows[2]["ready_at_seconds"] = 1006.5
        result = allocation(states, config, 1000, 1010, activation_records=rows)
        self.assertEqual(result["pending_acquisition_core_seconds_bounds"], [16.5, 16.5])
        self.assertEqual(result["allocated_core_seconds_bounds"], [85.5, 85.5])

    def test_observer_acceptance_before_poll_confirmation_does_not_duplicate_cost(self):
        """Observed accepting time counts once even if activation confirmation is later."""
        states, config = self.states(accepting_from=1006)
        result = allocation(states, config, 1000, 1010, activation_records=records(observed=1008))
        self.assertEqual(result["accepting_draining_core_seconds_bounds"], [72, 72])
        self.assertEqual(result["allocated_core_seconds_bounds"], [87, 87])

    def test_unfinished_acquisition_is_retained_and_charged_through_window(self):
        """An unresolved request is visible; it does not become free reserve capacity."""
        states, config = self.states(accepting_from=9999)
        result = allocation(states, config, 1000, 1010, activation_records=records(observed=None))
        self.assertEqual(result["allocated_core_seconds_bounds"], [87, 87])
        audit = acquisition_audit(records(observed=None))
        self.assertEqual(audit["unresolved_activation_ids"], ["a"])

    def test_gap_bounds_never_exceed_full_pool_and_retain_uncertainty(self):
        """Missing observations preserve conservative bounds while pending capacity exists."""
        states, config = self.states()
        states = [state for index, state in enumerate(states) if index not in (3, 4, 5)]
        result = allocation(states, config, 1000, 1010, activation_records=records())
        self.assertTrue(result["gaps"])
        self.assertIsNone(result["allocated_application_core_seconds"])
        self.assertLessEqual(result["allocated_core_seconds_bounds"][1], 90)

    def test_activation_observation_is_joined_to_original_forecast_action(self):
        """A later observed activation remains attributed to its selecting forecast cycle."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in records()))
            result = controller_outcomes(root, 1000, 1010, arm="forecast")
        self.assertEqual(result["observed_up"], 1)
        self.assertEqual(result["actions"][0]["tick"], 1)
        self.assertTrue(result["actions"][0]["observed"])
        self.assertEqual(result["actions"][0]["decision_source"], "forecast")
        self.assertEqual(result["acquisitions"][0]["request_to_observed_seconds"], 6)

    def test_lost_ack_availability_is_not_attributed_forecast_execution(self):
        """Physical availability closes charging without confirming an uncertain API intent."""
        rows = records()
        for row in rows:
            if row["event"] == "action.result":
                row.update(status="observed_applied", attribution="uncertain_after_reconciliation")
            if row["event"] == "activation.api_result":
                row["status"] = "uncertain_or_failed"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
            result = controller_outcomes(root, 1000, 1020, arm="forecast")
            cycle = root / "cycle-0001"
            (cycle / "forecast").mkdir(parents=True)
            (cycle / "forecast/forecast.json").write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "cutoff": iso(1000000),
                        "settings": {"horizon_seconds": 10},
                        "predictions": [],
                        "scenario_job_counts": [],
                    }
                )
            )
            diagnostic = cycle_diagnostic(cycle, result["cycles"][0], [], 1020000, 1030000)
        self.assertEqual(result["observed_up"], 0)
        self.assertFalse(result["actions"][0]["observed"])
        self.assertFalse(result["cycles"][0]["activation_observed"])
        self.assertEqual(result["acquisitions"][0]["status"], "observed")
        self.assertEqual(result["acquisitions"][0]["request_to_observed_seconds"], 6)
        self.assertIsNone(diagnostic["actual_candidate"])

    def test_failed_activation_does_not_capture_later_observed_scale_down(self):
        """A dispatch that fails before intent cannot steal a later unrelated action."""
        rows = records(observed=None)
        rows.extend(
            [
                {
                    "event": "activation.dispatch",
                    "activation_id": "a",
                    "dispatched_at_seconds": 1006,
                },
                {
                    "event": "activation.api_result",
                    "activation_id": "a",
                    "status": "uncertain_or_failed",
                },
                {
                    "event": "activation.result",
                    "activation_id": "a",
                    "status": "cancelled",
                    "recorded_at_ns": 1008000000000,
                },
                {"event": "cycle.begin", "tick": 2, "started_at": 1009},
                {
                    "event": "action.request",
                    "action_id": "down-later",
                    "action": "scale-down",
                    "selected_worker": "w1",
                },
                {"event": "action.result", "action_id": "down-later", "status": "acknowledged"},
                {
                    "event": "cycle.observed",
                    "action_observed": True,
                    "state": {"timestamp_seconds": 1010},
                },
            ]
        )
        self.assertNotIn("api_action_id", acquisition_history(rows)[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "journal.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
            result = controller_outcomes(root, 1000, 1020, arm="forecast")
        self.assertEqual(result["observed_down"], 1)
        self.assertNotIn("activation_id", result["actions"][0])

    def test_activation_link_requires_scale_up_on_its_original_worker(self):
        """An unrelated action cannot satisfy a pending dispatch association."""
        rows = records()
        rows[5].update(action="scale-down", selected_worker="w1")
        rows[7].pop("action_id")
        self.assertNotIn("api_action_id", acquisition_history(rows)[0])

    def test_early_or_duplicate_dispatch_is_an_observed_violation(self):
        """The audit checks the same minimum-delay boundary as physical actuation."""
        rows = records()
        rows[4]["dispatched_at_seconds"] = 1005.9
        audit = acquisition_audit(rows)
        self.assertTrue(audit["violations"])
        self.assertEqual(audit["early_dispatch_activation_ids"], ["a"])
        rows = records()
        rows.insert(5, copy.deepcopy(rows[4]))
        audit = acquisition_audit(rows)
        self.assertEqual(audit["duplicate_dispatch_activation_ids"], ["a"])

    def test_report_keeps_requested_due_and_observed_clocks_separate(self):
        """The report exposes delay and unresolved requests independently of service."""
        run = {
            "origin_seconds": 1000,
            "controller": {"acquisitions": acquisition_history(records())},
        }
        row = acquisition_rows(run)[0]
        self.assertEqual(row["requested"], 1)
        self.assertEqual(row["due"], 6)
        self.assertEqual(row["observed"], 7)
        self.assertEqual(row["latency"], 6)
        run["controller"]["acquisitions"] = acquisition_history(records(observed=None))
        self.assertIsNone(acquisition_rows(run)[0]["observed"])

    def test_capacity_plot_retains_unknown_intervals_and_zero_pending_fixed_capacity(self):
        """A fixed baseline has physical cores; missing snapshots never become a connecting line."""
        run = {
            "origin_seconds": 1000,
            "allocation": {
                "series": [
                    {"time": 1000, "valid": True, "allocated": 16},
                    {"time": 1005, "valid": True, "allocated": 16},
                    {"time": 1006, "valid": False},
                ]
            },
        }
        times, values = acquisition_series(run, "accepting_draining_cores")
        self.assertEqual(len(times), 4)
        self.assertEqual(values[0], 16)
        self.assertTrue(values[1] != values[1])
        self.assertTrue(values[-1] != values[-1])
        self.assertEqual(acquisition_series(run, "pending_application_cores")[1][0], 0)

    def test_uncertain_physical_component_never_plots_a_lower_bound_as_exact(self):
        """Frozen historical metrics also retain gaps for uncertain component capacity."""
        run = {
            "origin_seconds": 1000,
            "allocation": {
                "series": [
                    {
                        "time": 1002,
                        "valid": True,
                        "lower": 6,
                        "upper": 9,
                        "allocated": None,
                        "membership_complete": False,
                        "accepting_draining_cores": 6,
                        "pending_application_cores": 3,
                    }
                ]
            },
        }
        for field in ("accepting_draining_cores", "pending_application_cores"):
            values = acquisition_series(run, field)[1]
            self.assertTrue(values[0] != values[0])

    def test_new_evidence_retains_component_uncertainty(self):
        """Uncertain membership does not produce an exact physical or pending component."""
        base = {
            "start_seconds": 1000,
            "end_seconds": 1010,
            "gaps": ["uncertain"],
            "allocated_core_seconds_bounds": [60, 90],
            "series": [
                {
                    "time": 1002,
                    "valid": True,
                    "lower": 6,
                    "upper": 9,
                    "allocated": None,
                    "membership_complete": False,
                    "allocated_workers": ["w1", "w2"],
                }
            ],
        }
        result = charge_acquisitions(base, records(), 9)
        self.assertIsNone(result["series"][0]["accepting_draining_cores"])
        self.assertIsNone(result["series"][0]["pending_application_cores"])

    def test_zero_delay_history_is_empty_without_invented_activation(self):
        """Historical direct uncordon runs keep their original accounting semantics."""
        self.assertEqual(acquisition_history([]), [])
        self.assertFalse(acquisition_audit([])["violations"])


if __name__ == "__main__":
    unittest.main()
