"""Decision time offsets preserve original pending clocks and truthful allocation cost."""

import copy
import json
from pathlib import Path
import unittest

from closed_loop_runner import score_cases
from demo_configuration import EXPERIMENT_DEFAULTS, validate_experiment
from demo_workflow import matrix_commands
from opendc_acquisition import apply_acquisition
import test_opendc_acquisition as acquisition_fixtures


class DiagnosticTimingTests(unittest.TestCase):
    """Model computation before requesting capacity, without restarting an existing request."""

    def contract(self):
        """Add declared model-only offsets to the existing physical sixty-second fixture.

        Returns:
            dict: Shared worker configuration with a 60-second request and 30-second margin.
        """
        return dict(
            acquisition_fixtures.AcquisitionModelTests().contract(),
            modeled_request_delay_seconds=60,
            modeled_admission_margin_seconds=30,
        )

    def test_new_reserve_is_available_after_request_delay_acquisition_and_margin(self):
        """All alternatives block the same reserve until cutoff plus 150 seconds."""
        fixtures = acquisition_fixtures.AcquisitionModelTests()
        cases = [
            apply_acquisition(fixtures.case(action), self.contract())
            for action in ("unchanged", "scale-up", "scale-down")
        ]
        self.assertEqual(cases[0]["acquisition"]["available_after_ms"]["w3"], 150000)
        self.assertEqual(cases[0]["tasks"], cases[1]["tasks"])
        self.assertEqual(cases[1]["tasks"], cases[2]["tasks"])

    def test_pending_request_uses_original_due_clock_and_margin_without_request_delay(self):
        """A pending worker due at125 from cutoff100 becomes available after55 seconds."""
        contract = self.contract()
        contract["pending_acquisitions"] = [dict(selected_worker="w3", ready_at_seconds=125)]
        before = copy.deepcopy(contract)
        case = apply_acquisition(acquisition_fixtures.AcquisitionModelTests().case(), contract)
        self.assertEqual(case["acquisition"]["available_after_ms"]["w3"], 55000)
        self.assertEqual(contract, before)

    def test_model_offsets_are_validated_even_with_zero_physical_acquisition(self):
        """Negative, boolean and nonfinite offsets cannot silently fall back to legacy timing."""
        for key in ("modeled_request_delay_seconds", "modeled_admission_margin_seconds"):
            for value in (-1, True, float("nan"), float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    apply_acquisition(
                        acquisition_fixtures.AcquisitionModelTests().case(),
                        dict(self.contract(), acquisition_seconds=0, **{key: value}),
                    )
                settings = dict(EXPERIMENT_DEFAULTS, **{key: value})
                with self.assertRaises(ValueError):
                    validate_experiment(settings)

    def test_new_reserve_cost_starts_after_request_offset_existing_capacity_stays_charged(self):
        """With120sec window, two existing3-core hosts cost720 and a new one only180 more."""
        fixtures = acquisition_fixtures.AcquisitionModelTests()
        rows = []
        for action in ("unchanged", "scale-up"):
            case = apply_acquisition(fixtures.case(action), self.contract())
            completed = [dict(task_id=1, finish_time=30000, host_name="w2")]
            completed += [
                dict(task_id=row["task"]["id"], finish_time=150000, host_name="w3")
                for row in case["tasks"]
                if row["metadata"]["cohort"] == "infrastructure"
            ]
            rows.append(dict(case=case, validation=dict(status="passed", tasks=completed)))
        scores = {row["candidate"]: row for row in score_cases(rows, scenarios=1)}
        self.assertEqual(scores["unchanged"]["scenarios"][0]["allocated_core_seconds"], 720)
        self.assertEqual(scores["scale-up"]["scenarios"][0]["allocated_core_seconds"], 900)
        self.assertEqual(scores["scale-up"]["scenarios"][0]["cohort_size"], 1)

    def test_partial_override_materializes_one_common_complete_allocation_declaration(self):
        """A fixed-only override must retain the shared four-worker initial dynamic pool."""
        protocol = dict(
            source_root="/frozen",
            continuum_config="/cluster.cfg",
            inventory="/inventory",
            experiment_config="/settings.json",
            native_image="native:pinned",
            run_prefix="partial",
            matrix=[dict(seed=1, arm=arm) for arm in ("fixed", "reactive", "forecast")],
            worker_bounds=dict(active_workers=4, minimum_workers=2, maximum_workers=6),
            arm_active_workers=dict(fixed=5),
        )
        for row in matrix_commands(protocol, Path("/new")):
            command = row["command"]
            self.assertEqual(
                json.loads(command[command.index("--arm-active-workers") + 1]),
                dict(fixed=5, reactive=4, forecast=4),
            )

    def test_fixed5_and_dynamic4_are_sealed_without_changing_common_worker_bounds(self):
        """A fixed comparator can admit on five while both dynamic policies start on four."""
        protocol = dict(
            source_root="/frozen",
            continuum_config="/cluster.cfg",
            inventory="/inventory",
            experiment_config="/settings.json",
            native_image="native:pinned",
            run_prefix="initial",
            matrix=[dict(seed=1, arm=arm) for arm in ("fixed", "reactive", "forecast")],
            worker_bounds=dict(active_workers=4, minimum_workers=2, maximum_workers=6),
            arm_active_workers=dict(fixed=5, reactive=4, forecast=4),
        )
        for row, expected in zip(matrix_commands(protocol, Path("/new")), ("5", "4", "4")):
            command = row["command"]
            self.assertEqual(command[command.index("--active-workers") + 1], expected)
            self.assertIn("--arm-active-workers", command)
        for mapping in (dict(fixed=True), dict(fixed=7), dict(unknown=5), dict(fixed=1), ["fixed"]):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                matrix_commands(dict(protocol, arm_active_workers=mapping), Path("/new"))
