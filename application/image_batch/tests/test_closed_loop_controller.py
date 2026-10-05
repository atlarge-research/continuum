"""Controller action durability and shadow-phase safety regressions."""

import importlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from closed_loop_journal import Journal
import test_closed_loop_guards as guard_fixtures
from opendc_scenarios import _down_worker


class ControllerTests(unittest.TestCase):
    """Physical changes must follow a durable guarded intent and require live mode."""

    def setUp(self):
        """Reuse realistic fresh observer inventory from guard regressions."""
        fixture = guard_fixtures.GuardTests()
        fixture.setUp()
        self.config = fixture.config
        self.snapshot = fixture.snapshot
        self.view = fixture.view()
        self.node = {
            "metadata": {"name": "w1", "uid": "uid-w1", "resourceVersion": "42"},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }

    def module(self):
        """Load the production controller.

        Returns:
            module: Controller implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("closed_loop_controller"))
        return importlib.import_module("closed_loop_controller")

    def test_intent_is_durable_before_uid_and_resource_version_guarded_patch(self):
        """An API call is issued only after its exact target and intent can be recovered."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")
            calls = []

            def api(*args):
                pending = journal.pending_action()
                self.assertEqual(pending["selected_worker"], "w1")
                patch_value = json.loads(args[-1])
                self.assertEqual(
                    patch_value[:2],
                    [
                        {"op": "test", "path": "/metadata/uid", "value": "uid-w1"},
                        {"op": "test", "path": "/metadata/resourceVersion", "value": "42"},
                    ],
                )
                calls.append(patch_value)
                return b"{}"

            session = type(
                "Session", (), {"get": lambda _, *args: self.node, "kubectl": staticmethod(api)}
            )()
            with patch.object(module.time, "time", return_value=1002):
                result = module.actuate(
                    session,
                    journal,
                    self.view,
                    self.view,
                    {"action": "scale-down", "selected_worker": "w1"},
                    self.config,
                    cutoff_seconds=1000,
                )
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["status"], "acknowledged")
            self.assertIsNone(journal.pending_action())
            self.assertEqual(journal.history()["last_action_at"], 1002)
            journal.close()

    def test_uncertain_api_outcome_stays_pending_and_cannot_be_reissued(self):
        """A lost API reply requires observation; a second request is forbidden."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")

            def fail(*_args):
                raise RuntimeError("lost API acknowledgement")

            session = type(
                "Session", (), {"get": lambda _, *args: self.node, "kubectl": staticmethod(fail)}
            )()
            proposal = {"action": "scale-down", "selected_worker": "w1"}
            with patch.object(module.time, "time", return_value=1002):
                with self.assertRaisesRegex(RuntimeError, "acknowledgement"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        proposal,
                        self.config,
                        cutoff_seconds=1000,
                    )
                self.assertIsNotNone(journal.pending_action())
                with self.assertRaisesRegex(ValueError, "unresolved"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        proposal,
                        self.config,
                        cutoff_seconds=1000,
                    )
            journal.close()

    def test_first_valid_forecast_can_act_after_workload_warmup(self):
        """A complete first decision is not consumed by an extra controller shadow phase."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            loop = object.__new__(module.Controller)
            loop.output = Path(temporary)
            loop.journal = Journal(loop.output / "journal.jsonl")
            loop.tick_number, loop.shadow, loop.history = 0, 0, {}
            loop.args = Mock(control_arm="forecast")
            loop.config, loop.session = self.config, Mock()
            loop.fresh = Mock(return_value=self.view)
            loop.recover = Mock()
            scores = [
                {
                    "candidate": name,
                    "selected_worker": worker,
                    "scenarios": [
                        {
                            "complete": True,
                            "cohort_size": 0,
                            "responses_seconds": [],
                            "allocated_core_seconds": cost,
                        }
                        for _ in range(3)
                    ],
                }
                for name, worker, cost in [("unchanged", None, 100), ("scale-down", "w1", 99)]
            ]
            loop.predict = Mock(return_value=(self.view, scores, 1000))
            with patch.object(module.time, "time", return_value=1001), patch.object(
                module, "actuate", return_value=dict(last_action_at=1000)
            ), patch.object(module.time, "monotonic", side_effect=[0, 0, 0, 4]):
                loop.cycle()
            ended = loop.journal.records[-1]
            proposal = next(row for row in loop.journal.records if row["event"] == "cycle.proposal")
            self.assertEqual(proposal.get("scoring_age_seconds"), 1)
            self.assertEqual(ended["outcome"], "acknowledged")
            loop.journal.close()

    def test_final_node_read_rejects_readiness_loss(self):
        """A worker becoming unready before dispatch vetoes the pending capacity change."""
        module = self.module()
        self.node["status"]["conditions"][0]["status"] = "False"
        session = Mock()
        session.get.return_value = self.node
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "journal.jsonl")
            with patch.object(module.time, "time", return_value=1002):
                with self.assertRaisesRegex(ValueError, "Ready"):
                    module.actuate(
                        session,
                        journal,
                        self.view,
                        self.view,
                        {"action": "scale-down", "selected_worker": "w1"},
                        self.config,
                        cutoff_seconds=1000,
                    )
            session.kubectl.assert_not_called()
            journal.close()

    def test_state_failure_resets_reactive_history_and_timeout_ends_cycle(self):
        """Recovery continues after transport timeout without credit for invalid observations."""
        module = self.module()
        for failure in (ValueError("stale"), subprocess.TimeoutExpired("ssh", 3)):
            with self.subTest(
                failure=type(failure).__name__
            ), tempfile.TemporaryDirectory() as temporary:
                loop = object.__new__(module.Controller)
                loop.output = Path(temporary)
                loop.journal = Journal(loop.output / "journal.jsonl")
                loop.tick_number, loop.history = 0, {"reactive_observation": {"tick_id": 1}}
                loop.fresh = Mock(side_effect=failure)
                loop.cycle()
                self.assertNotIn("reactive_observation", loop.history)
                self.assertEqual(loop.journal.records[-1]["event"], "cycle.end")
                self.assertEqual(loop.journal.records[-1]["outcome"], "vetoed_or_failed")
                loop.journal.close()

    def test_forecast_observations_feed_independent_fallback_history(self):
        """A failed second forecast can use the first scheduled empty observation."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            loop = object.__new__(module.Controller)
            loop.output = Path(temporary)
            loop.journal = Journal(loop.output / "journal.jsonl")
            loop.tick_number, loop.shadow, loop.history = 0, 2, {}
            loop.args = Mock(control_arm="forecast")
            loop.config, loop.session = self.config, Mock()
            loop.fresh = Mock(return_value=self.view)
            loop.recover = Mock()
            scores = [
                {
                    "candidate": "unchanged",
                    "selected_worker": None,
                    "scenarios": [
                        {
                            "complete": True,
                            "cohort_size": 0,
                            "responses_seconds": [],
                            "allocated_core_seconds": 100,
                        }
                        for _ in range(3)
                    ],
                }
            ]
            loop.predict = Mock(
                side_effect=[(self.view, scores, 1000), ValueError("forecast missing")]
            )
            with patch.object(module.time, "time", return_value=1001), patch.object(
                module, "actuate", return_value=dict(last_action_at=1000)
            ), patch.object(module.time, "monotonic", side_effect=[0, 0, 0, 4]):
                loop.cycle()
                loop.cycle()
            proposals = [
                r["proposal"] for r in loop.journal.records if r["event"] == "cycle.proposal"
            ]
            self.assertEqual([p["action"] for p in proposals], ["unchanged", "scale-down"])
            self.assertEqual(
                len([r for r in loop.journal.records if r["event"] == "fallback.invoked"]), 1
            )
            loop.journal.close()

    def test_first_tick_fallback_hold_is_counted(self):
        """Fallback metrics include holds when current demand prevents safe down."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            loop = object.__new__(module.Controller)
            loop.output = Path(temporary)
            loop.journal = Journal(loop.output / "journal.jsonl")
            loop.tick_number, loop.shadow, loop.history = 0, 2, {}
            loop.args = Mock(control_arm="forecast")
            loop.config, loop.session = self.config, Mock()
            self.snapshot["jobs"]["queued"] = [
                guard_fixtures.GuardTests().job(str(i)) for i in range(3)
            ]
            hold_view = module.snapshot_view(self.snapshot, self.config, now_seconds=1001)
            loop.fresh = Mock(return_value=hold_view)
            loop.recover = Mock()
            loop.predict = Mock(side_effect=ValueError("forecast missing"))
            with patch.object(module.time, "time", return_value=1001):
                loop.cycle()
            proposals = [
                r["proposal"] for r in loop.journal.records if r["event"] == "cycle.proposal"
            ]
            self.assertEqual(proposals[0]["action"], "unchanged")
            self.assertEqual(
                len([r for r in loop.journal.records if r["event"] == "fallback.invoked"]), 1
            )
            loop.journal.close()

    def test_restart_skips_orphaned_cycle_directory(self):
        """A crash after directory creation cannot cause evidence overwrite or endless failure."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = Journal(root / "journal.jsonl")
            journal.append("cycle.begin", tick=2)
            (root / "cycle-0003").mkdir()
            self.assertEqual(module.last_tick(journal, root), 3)
            journal.close()

    def test_down_candidate_uses_last_predicted_release_not_oldest_assignment(self):
        """The oldest assigned worker can have the longest remaining drain."""
        backlog = [
            {
                "task": {"duration": duration},
                "metadata": {
                    "preserved_assignment": name,
                    "first_assignment_observed_ms": assigned,
                },
            }
            for name, duration, assigned in [("w1", 10000, 1), ("w2", 2000, 2)]
        ]
        self.assertEqual(_down_worker(["w1", "w2"], backlog, []), "w2")
        self.assertEqual(_down_worker(["w1", "w2", "w3"], backlog, []), "w3")
        backlog.append({"task": {"duration": 15000}, "metadata": {"preserved_assignment": "w2"}})
        self.assertEqual(_down_worker(["w1", "w2"], backlog, []), "w1")

    def test_initial_freshness_is_measured_at_collection_before_forecast_computation(self):
        """Ten seconds of valid computation ages the decision, not its collection precondition."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loop = object.__new__(module.Controller)
            loop.journal = Mock(records=[])
            loop.session = Mock(namespace="test")
            loop.session.namespace = "test"
            loop.args = Mock(period_seconds=120, warmup_cycles=1, native_image="test")
            loop.origin, loop.tick_number = 900, 1
            loop.template, loop.config, loop.history = {"saved": True}, self.config, {}
            loop.cluster = {}

            def forecast(_prefix, destination, _cutoff, _settings, _template, **_kwargs):
                destination.mkdir()
                (destination / "state.json").write_text(json.dumps(self.snapshot))
                return (
                    {
                        "status": "ready",
                        "simulation_inputs": {"status": "ready"},
                        "cutoff": self.snapshot["timestamp"],
                    },
                    loop.template,
                )

            with patch.object(module.time, "time", side_effect=[1001, 1010]), patch.object(
                module, "run_once", side_effect=forecast
            ), patch.object(module, "prepare_suite"), patch.object(
                module, "run_control_plane_suite", return_value=root
            ), patch.object(
                module, "load_scores", return_value=([], {})
            ):
                before, _, cutoff = loop.predict(root)
            self.assertEqual(before["timestamp_seconds"], 1000)
            self.assertEqual(cutoff, 1000)

    def test_incomplete_membership_gets_one_preserved_preparation_retry(self):
        """A new complete prefix may recover a list race without simulating an incomplete one."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loop = object.__new__(module.Controller)
            loop.session = Mock(namespace="test")
            loop.session.namespace = "test"
            loop.args = Mock(period_seconds=480, warmup_cycles=2, native_image="test")
            loop.origin, loop.tick_number = 900, 1
            loop.output = root
            loop.journal = Journal(root / "journal.jsonl")
            loop.template, loop.config, loop.cluster = {"saved": True}, self.config, {}
            loop.history = {"reactive_observation": {"eligible_workers": ["w1"]}}
            attempts = []

            def forecast(_prefix, destination, _cutoff, _settings, _template, **_kwargs):
                snapshot = json.loads(json.dumps(self.snapshot))
                if not attempts:
                    snapshot["collection"]["missing_job_uids"] = ["new-job"]
                attempts.append(snapshot)
                destination.mkdir()
                (destination / "state.json").write_text(json.dumps(snapshot))
                return (
                    {
                        "status": "ready",
                        "simulation_inputs": {"status": "ready"},
                        "cutoff": snapshot["timestamp"],
                    },
                    loop.template,
                )

            with patch.object(module.time, "time", return_value=1001), patch.object(
                module.time, "sleep"
            ), patch.object(module, "run_once", side_effect=forecast), patch.object(
                module, "prepare_suite"
            ), patch.object(
                module, "run_control_plane_suite", return_value=root
            ) as native, patch.object(
                module, "load_scores", return_value=([], {})
            ):
                before, _, _ = loop.predict(root)
            self.assertEqual(before["timestamp_seconds"], 1000)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(native.call_count, 1)
            self.assertNotIn("reactive_observation", loop.history)
            rejected = json.loads((root / "rejected-preparation/forecast/state.json").read_text())
            self.assertEqual(rejected["collection"]["missing_job_uids"], ["new-job"])
            self.assertEqual([row["event"] for row in loop.journal.records], ["observation.retry"])
            loop.journal.close()

    def test_recollection_is_bounded_and_does_not_retry_other_failures(self):
        """Persistent missing membership fails after two attempts; native errors get one."""
        module = self.module()
        for error, expected_calls in (
            (module.IncompleteMembership("missing"), 2),
            (RuntimeError("native failed"), 1),
        ):
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                loop = object.__new__(module.Controller)
                loop.journal = Journal(root / "journal.jsonl")
                loop.history, loop.tick_number = {}, 1
                with patch.object(
                    loop, "_predict_once", side_effect=error
                ) as predict, patch.object(module.time, "sleep"), self.assertRaises(type(error)):
                    loop.predict(root)
                self.assertEqual(predict.call_count, expected_calls)
                loop.journal.close()

    def test_prediction_uses_configured_horizon_scenarios_and_runtime_budgets(self):
        """The prepared future and native scoring use the frozen experiment settings."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loop = object.__new__(module.Controller)
            loop.journal = Mock(records=[])
            loop.session = Mock(namespace="test")
            loop.session.namespace = "test"
            loop.args = Mock(period_seconds=480, warmup_cycles=2, native_image="test")
            loop.origin, loop.tick_number = 900, 7
            loop.template, loop.history, loop.cluster = {"saved": True}, {}, {}
            loop.config = {
                **self.config,
                "horizon_seconds": 300,
                "scenarios": 5,
                "scenario_seed": 123,
                "native_timeout_seconds": 55,
                "allocation_seconds": 300,
            }

            def forecast(_prefix, destination, _cutoff, settings, _template, **_kwargs):
                self.assertEqual(
                    (settings.horizon_seconds, settings.scenarios, settings.seed), (300, 5, 130)
                )
                destination.mkdir()
                (destination / "state.json").write_text(json.dumps(self.snapshot))
                return (
                    {
                        "status": "ready",
                        "simulation_inputs": {"status": "ready"},
                        "cutoff": self.snapshot["timestamp"],
                    },
                    loop.template,
                )

            def native(_suite, _output, _image, _cluster, _name, *, timeout_seconds):
                self.assertEqual(timeout_seconds, 55)
                return root

            def scores(_batch, *, scenarios, allocation_seconds):
                self.assertEqual((scenarios, allocation_seconds), (5, 300))
                return [], {}

            with patch.object(module.time, "time", return_value=1001), patch.object(
                module, "run_once", side_effect=forecast
            ), patch.object(module, "prepare_suite"), patch.object(
                module, "run_control_plane_suite", side_effect=native
            ), patch.object(
                module, "load_scores", side_effect=scores
            ):
                loop.predict(root)
            self.assertTrue((root / "stage-timing.json").exists())

    def test_replacement_node_does_not_confirm_the_original_action(self):
        """A matching cordon flag on a new UID is not observation of the requested worker."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            loop = object.__new__(module.Controller)
            loop.output = Path(temporary)
            loop.journal = Journal(loop.output / "journal.jsonl")
            loop.tick_number, loop.shadow, loop.history = 0, 2, {}
            loop.args = Mock(control_arm="reactive")
            loop.config, loop.session = self.config, Mock()
            replacement = json.loads(json.dumps(self.view))
            replacement["timestamp_seconds"] = 1003
            replacement["nodes"]["w1"].update(uid="replacement", accepting=False)
            loop.fresh = Mock(side_effect=[self.view, self.view, replacement, replacement])
            loop.recover = Mock()
            proposal = dict(action="scale-down", selected_worker="w1", state={})
            with patch.object(module, "reactive_action", return_value=proposal), patch.object(
                module, "actuate", return_value=dict(last_action_at=1002)
            ), patch.object(module.time, "time", return_value=1003), patch.object(
                module.time, "monotonic", side_effect=[0, 0, 0, 4]
            ):
                loop.cycle()
            observed = [r for r in loop.journal.records if r["event"] == "cycle.observed"]
            self.assertFalse(observed[-1]["action_observed"])
            loop.journal.close()
