"""Native acquisition occupancy never becomes application service evidence."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from opendc_acquisition import (
    apply_acquisition,
    application_tasks,
    native_cordons,
    validate_acquisition_results,
)
from closed_loop_runner import score_cases
from opendc_energy import datacenter_series
from opendc_inputs import verify_inputs
from opendc_native_batch import plan_suite
from opendc_scenarios import prepare_suite
import test_opendc_scenarios as scenario_fixtures
import test_closed_loop_runner as runner_fixtures


class AcquisitionModelTests(unittest.TestCase):
    """Common synthetic reservations preserve paired real sampled cohorts."""

    def case(self, action="unchanged"):
        """Return one complete score fixture with a separate reserve worker.

        Args:
            action (str): Capacity alternative to represent.

        Returns:
            dict: Pinned case with real workload identity and explicit resources.
        """
        case = copy.deepcopy(runner_fixtures.RunnerScoreTests().rows()[0]["case"])
        case["tasks"][0]["metadata"]["cohort"] = "backlog"
        case.update(
            candidate=action,
            initialization_mode="pinned-trace",
            selected_worker="w3"
            if action == "scale-up"
            else "w2"
            if action == "scale-down"
            else None,
        )
        for worker in case["workers"]:
            worker.update(memory_mib=8192, frequency_mhz=2400)
        return case

    def contract(self):
        """Declare a sixty-second empty reserve acquisition.

        Returns:
            dict: Full topology, physical accepting workers and immutable lead time.
        """
        workers = self.case()["workers"] + [
            {"node_name": "w3", "modeled_cores": 3, "memory_mib": 8192, "frequency_mhz": 2400}
        ]
        return {
            "acquisition_seconds": 60.0,
            "workers": workers,
            "active_workers": ["w1", "w2"],
            "pending_acquisitions": [],
            "first_synthetic_task_id": 10,
        }

    def test_reserve_occupancy_is_common_and_pinned_until_sixty_seconds(self):
        """Each reserve slot is blocked identically across candidate alternatives."""
        cases = [
            apply_acquisition(self.case(action), self.contract())
            for action in ("unchanged", "scale-up", "scale-down")
        ]
        self.assertEqual(cases[0]["tasks"], cases[1]["tasks"])
        self.assertEqual(cases[1]["tasks"], cases[2]["tasks"])
        blockers = [r for r in cases[0]["tasks"] if r["metadata"]["cohort"] == "infrastructure"]
        self.assertEqual(len(blockers), 3)
        self.assertTrue(all(r["task"]["duration"] == 60000 for r in blockers))
        self.assertTrue(all(r["metadata"]["preserved_assignment"] == "w3" for r in blockers))
        self.assertEqual(native_cordons(cases[0]), ["w3"])
        self.assertEqual(native_cordons(cases[1]), [])
        self.assertEqual(native_cordons(cases[2]), ["w2", "w3"])
        self.assertEqual(len(application_tasks(cases[0])), 1)

    def test_pending_remaining_delay_uses_original_due_clock(self):
        """A previously requested worker uses remaining time, never another full delay."""
        contract = self.contract()
        contract["pending_acquisitions"] = [{"selected_worker": "w3", "ready_at_seconds": 125}]
        case = apply_acquisition(self.case(), contract)
        self.assertEqual(native_cordons(case), [])
        blockers = [r for r in case["tasks"] if r["metadata"]["cohort"] == "infrastructure"]
        self.assertTrue(all(r["task"]["duration"] == 25000 for r in blockers))
        self.assertEqual(case["acquisition"]["allocated_workers"], ["w1", "w2", "w3"])

    def test_zero_delay_keeps_original_case_contract(self):
        """Historical warm-reserve cases and analytical empties remain unchanged."""
        original = self.case()
        result = apply_acquisition(original, {**self.contract(), "acquisition_seconds": 0})
        self.assertEqual(result, original)
        self.assertNotIn("acquisition", result)

    def test_infrastructure_is_excluded_from_service_and_reserve_allocation(self):
        """Real responses stay paired while newly requested capacity costs the full window."""
        rows = []
        for action in ("unchanged", "scale-up", "scale-down"):
            for scenario in range(3):
                case = self.case(action)
                case["scenario"] = scenario
                modeled = apply_acquisition(case, self.contract())
                completed = [{"task_id": 1, "finish_time": 30000, "host_name": "w2"}]
                completed.extend(
                    {"task_id": r["task"]["id"], "finish_time": 60000, "host_name": "w3"}
                    for r in modeled["tasks"]
                    if r["metadata"]["cohort"] == "infrastructure"
                )
                rows.append(
                    {"case": modeled, "validation": {"status": "passed", "tasks": completed}}
                )
        scores = {r["candidate"]: r for r in score_cases(rows, scenarios=3)}
        for result in scores.values():
            self.assertEqual(result["scenarios"][0]["responses_seconds"], [50])
            self.assertEqual(result["scenarios"][0]["cohort_size"], 1)
        self.assertEqual(scores["unchanged"]["scenarios"][0]["allocated_core_seconds"], 720)
        self.assertEqual(scores["scale-up"]["scenarios"][0]["allocated_core_seconds"], 1080)
        self.assertEqual(scores["scale-down"]["scenarios"][0]["allocated_core_seconds"], 450)

    def test_delayed_suite_retains_one_native_cartesian_process(self):
        """The real preparation validates synthetic lineage without splitting native batches."""
        rows = scenario_fixtures.observer_rows()
        for state in rows["cluster-state.jsonl"]:
            state["jobs"]["active"] = [
                j for j in state["jobs"]["active"] if j["kubernetes_job_uid"] != "exhausted"
            ]
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ), patch("test_opendc_scenarios.observer_rows", return_value=rows):
            root = Path(temporary)
            forecast, observer = scenario_fixtures.make_forecast(root)
            config = {**scenario_fixtures.configuration(), "acquisition_seconds": 60.0}
            suite = root / "suite"
            manifest = prepare_suite(forecast, observer, config, suite, "pinned-trace")
            plan = plan_suite(suite)
            self.assertEqual(plan["actions"], ["unchanged", "scale-up", "scale-down"])
            self.assertEqual(len(plan["experiment"]["workloads"]), 2)
            for entry in manifest["experiments"]:
                directory = suite / entry["input_dir"]
                verify_inputs(directory)
                case = json.loads((directory / "case.json").read_text())
                self.assertIn("acquisition", case)
                self.assertEqual(len(case["workers"]), 3)

    def test_native_application_admission_before_availability_is_rejected(self):
        """Completion validation checks the actual native placement clock."""
        case = apply_acquisition(self.case("scale-up"), self.contract())
        with self.assertRaisesRegex(ValueError, "acquisition"):
            validate_acquisition_results(
                case, [{"task_id": 1, "host_name": "w3", "schedule_time": 59999}], {}
            )
        validate_acquisition_results(
            case, [{"task_id": 1, "host_name": "w3", "schedule_time": 60000}], {}
        )
        held = apply_acquisition(self.case(), self.contract())
        with self.assertRaisesRegex(ValueError, "cordon"):
            validate_acquisition_results(
                held, [{"task_id": 1, "host_name": "w3", "schedule_time": 61000}], {}
            )

    def test_datacenter_bounds_allow_unrequested_reserve_closure(self):
        """Closed reserves do not contribute the full-window idle-power lower bound."""
        settings = self.contract()
        for worker in settings["workers"]:
            worker.update(idle_power_w=50, max_power_w=100)
        case = apply_acquisition(self.case(), settings)
        rows = [
            {"timestamp": 0, "data_center_name": "provisional", "energy_usage": 0},
            {"timestamp": 120000, "data_center_name": "provisional", "energy_usage": 13000},
        ]
        result = datacenter_series(case, rows, 0)["modeled-worker-pool"]
        self.assertEqual(result["idle_power_w"], 100)

    def test_delay_and_synthetic_identity_are_validated(self):
        """Invalid delays and collisions cannot silently mutate the modeled cohort."""
        for change in (
            {"acquisition_seconds": -1},
            {"acquisition_seconds": True},
            {"first_synthetic_task_id": 1},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                apply_acquisition(self.case(), {**self.contract(), **change})


if __name__ == "__main__":
    unittest.main()
