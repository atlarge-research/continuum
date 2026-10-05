"""Tests for campaign transitions and launch budget safety."""
import unittest
import fcntl
import tempfile
import json
import os
import subprocess
from unittest.mock import patch
from pathlib import Path
from demo_lifetime import PhaseFailure
from application.image_batch.scripts.demo_campaign import (
    next_requests,
    require_launch,
    drive_campaign,
    execute_capture,
    main,
)


def result(candidate, arm, *, seed=72001, service=True, qualified=False):
    """Construct an independently specified completed-capture decision record.

    Args:
        candidate (str): Workload configuration.
        arm (str): Captured policy.
        seed (int): Workload identity.
        service (bool): Original-creation service gate.
        qualified (bool): Matched case meets savings/control gates.

    Returns:
        dict: Decision record consumed by the supervisor.
    """
    return dict(
        candidate=candidate, arm=arm, seed=seed, service_passed=service, qualified=qualified
    )


class CampaignTests(unittest.TestCase):
    """Protect whole-trio completion, selection and unchanged closure reserves."""

    def test_initial_selection_keeps_a_complete_trio(self):
        """A new campaign reserves all three policies."""
        self.assertEqual(
            next_requests([]),
            [("A", "fixed", 72001), ("A", "forecast", 72001), ("A", "reactive", 72001)],
        )

    def test_failed_static_selects_complete_alternative(self):
        """A failing static reference never disappears behind an isolated forecast."""
        self.assertEqual(
            next_requests([result("A", "fixed", service=False)]),
            [("B", "fixed", 72001), ("B", "forecast", 72001), ("B", "reactive", 72001)],
        )

    def test_failed_forecast_selects_complete_alternative(self):
        """Missing savings or observed control selects the only declared alternative."""
        rows = [result("A", "fixed"), result("A", "forecast", qualified=False)]
        self.assertEqual(
            next_requests(rows),
            [("B", "fixed", 72001), ("B", "forecast", 72001), ("B", "reactive", 72001)],
        )

    def test_positive_pair_measures_reactive_before_confirmation(self):
        """Static savings cannot hide a cheaper adequate reactive policy."""
        rows = [result("A", "fixed"), result("A", "forecast", qualified=True)]
        self.assertEqual(next_requests(rows), [("A", "reactive", 72001)])

    def test_positive_trio_confirms_forecast_and_static(self):
        """Confirmation reverses policy order on a separate workload seed."""
        rows = [
            result("A", "fixed"),
            result("A", "forecast", qualified=True),
            result("A", "reactive", qualified=True),
        ]
        self.assertEqual(next_requests(rows), [("A", "forecast", 72002), ("A", "fixed", 72002)])

    def test_cheaper_reactive_preserves_trio_and_tests_only_alternative_pair(self):
        """A failed superiority gate does not authorize another unbudgeted trio."""
        rows = [
            result("A", "fixed"),
            result("A", "forecast", qualified=True),
            result("A", "reactive", qualified=False),
        ]
        self.assertEqual(next_requests(rows), [("B", "fixed", 72001), ("B", "forecast", 72001)])

    def test_alternative_trio_finishes_despite_disappointing_service(self):
        """A valid unfavorable alternative is still delivered as a whole set."""
        rows = [result("A", "fixed", service=False), result("B", "fixed", service=False)]
        self.assertEqual(next_requests(rows), [("B", "forecast", 72001), ("B", "reactive", 72001)])

    def test_complete_confirmation_stops(self):
        """There is no sixth capture after the declared five."""
        rows = [
            result("A", "fixed"),
            result("A", "forecast", qualified=True),
            result("A", "reactive", qualified=True),
            result("A", "forecast", seed=72002),
            result("A", "fixed", seed=72002),
        ]
        self.assertEqual(next_requests(rows), [])

    def test_budget_retains_full_workflow_and_remaining_policies(self):
        """A plausible short capture cannot replace the full 4200-second bound."""
        with self.assertRaises(ValueError):
            require_launch(1000, 13959, 3, 0)
        require_launch(1000, 13960, 3, 0)

    def test_capture_limit_prevents_sixth_attempt(self):
        """Failed attempts also consume the five-capture allowance."""
        with self.assertRaises(ValueError):
            require_launch(1000, 99999, 1, 5)

    def test_future_and_invalid_counts_rejected(self):
        """Negative remaining counts cannot bypass protected deadlines."""
        with self.assertRaises(ValueError):
            require_launch(1000, 99999, -1, 0)


class CaptureCommandTests(unittest.TestCase):
    """Exercise the supervisor command against the real, side-effect-free CLI parser."""

    def test_capture_command_is_accepted_by_workflow_cli(self):
        """An invalid matrix subcommand fails before any physical campaign can launch."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "operations").mkdir()
            worktree = Path(__file__).resolve().parents[3]
            (root / "checkpoint.json").write_text(json.dumps(dict(worktree=str(worktree))))
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [str(worktree / "application/image_batch/src"), str(worktree)]
                ),
                "MPLCONFIGDIR": str(root / "mpl-cache"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            def validate_command(command, _log, **options):
                """Run CLI help in place of the slow external physical workflow.

                Args:
                    command (list): Actual command emitted by the supervisor.
                    _log (Path): Unused physical log destination.
                    options (dict): Real command environment and working directory.

                Raises:
                    EOFError: CLI validation completed; do not continue physical analysis.
                """
                parsed = subprocess.run(
                    command[:4] + ["--help"],
                    cwd=options["cwd"],
                    env=options["environment"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
                raise EOFError("CLI validated without launching a workload")

            with patch("application.image_batch.scripts.demo_campaign.run_phase", validate_command):
                with self.assertRaises(EOFError):
                    execute_capture(root, ("A", "fixed", 72001), 1, environment)


class DurableCampaignTests(unittest.TestCase):
    """Verify automatic progression and persisted ownership before physical callbacks."""

    def test_capture_results_advance_without_chat_turn(self):
        """The supervisor saves each result before launching the next request."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(
                json.dumps(dict(closure_at_seconds=99999, records=[], attempts=0))
            )
            snapshots = []

            def capture(request, _attempt):
                saved = json.loads((root / "checkpoint.json").read_text())
                snapshots.append(
                    (saved["attempts"], len(saved["records"]), saved["active_request"])
                )
                candidate, arm, seed = request
                return result(candidate, arm, seed=seed, qualified=True)

            drive_campaign(root, capture, now=lambda: 1000)
            saved = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(len(saved["records"]), 5)
            self.assertEqual(saved["status"], "captures_complete")
            self.assertIsNone(saved["active_request"])
            self.assertEqual(snapshots[1], (2, 1, ["A", "forecast", 72001]))
            self.assertEqual(snapshots[-1], (5, 4, ["A", "fixed", 72002]))

    def test_expired_budget_launches_nothing(self):
        """The protected window is enforced before recording a new physical attempt."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(
                json.dumps(dict(closure_at_seconds=13959, records=[], attempts=0))
            )

            def capture(_request, _attempt):
                self.fail("capture launched after budget expiry")

            with self.assertRaises(ValueError):
                drive_campaign(root, capture, now=lambda: 1000)
            saved = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(saved["attempts"], 0)

    def test_inflight_checkpoint_requires_reconciliation(self):
        """An interrupted attempt is not silently duplicated on restart."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(
                json.dumps(
                    dict(
                        closure_at_seconds=99999,
                        records=[],
                        attempts=1,
                        active_request=["A", "fixed", 72001],
                    )
                )
            )
            with self.assertRaises(ValueError):
                drive_campaign(root, lambda _r, _a: self.fail("duplicate launch"), now=lambda: 1000)

    def test_wrong_capture_identity_stops(self):
        """An unrelated successful capture cannot advance this campaign."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(
                json.dumps(dict(closure_at_seconds=99999, records=[], attempts=0))
            )
            with self.assertRaises(ValueError):
                drive_campaign(root, lambda _r, _a: result("B", "fixed"), now=lambda: 1000)
            saved = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(saved["status"], "capture_failed")
            self.assertEqual(saved["records"], [])


class SupervisorOwnershipTests(unittest.TestCase):
    """Reject unowned restarts before any physical restoration side effect."""

    def run_main(self, root):
        """Invoke the real CLI against a controlled campaign directory.

        Args:
            root (Path): Temporary evidence root with a complete checkpoint.
        """
        with patch("sys.argv", ["demo_campaign", "--campaign-dir", str(root)]):
            main()

    def state(self, root, **extra):
        """Write a new checkpoint without external infrastructure dependencies.

        Args:
            root (Path): Temporary campaign root.
            extra (dict): Ownership or failure fields for this test.
        """
        (root / "operations").mkdir()
        (root / "checkpoint.json").write_text(
            json.dumps(
                dict(worktree=str(root), records=[], attempts=0, closure_at_seconds=1e20, **extra)
            )
        )

    def test_unreconciled_cli_does_not_restore_or_write_checkpoint(self):
        """An inflight restart must leave the actual owner's state untouched."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.state(root, active_request=["A", "fixed", 72001])
            original = (root / "checkpoint.json").read_bytes()

            def restoration(_root, _environment):
                """Record a prohibited or owned physical closure side effect.

                Args:
                    _root (Path): Campaign directory supplied by the real CLI.
                    _environment (dict): Operational environment supplied by the real CLI.
                """
                (root / "physical-restoration").touch()

            with patch(
                "application.image_batch.scripts.demo_campaign.restore_original", restoration
            ):
                with self.assertRaises(ValueError):
                    self.run_main(root)
            self.assertFalse((root / "physical-restoration").exists())
            self.assertEqual((root / "checkpoint.json").read_bytes(), original)

    def test_existing_owner_rejects_cli_before_lifecycle(self):
        """A competing supervisor is rejected even between captures."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.state(root)
            with (root / "operations/supervisor.lock").open("a") as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)

                def mutation(*_args, **_kwargs):
                    """Record a prohibited lifecycle side effect under competing ownership.

                    Args:
                        _args (tuple): CLI lifecycle arguments.
                        _kwargs (dict): CLI lifecycle options.
                    """
                    (root / "physical-side-effect").touch()

                with patch(
                    "application.image_batch.scripts.demo_campaign.drive_campaign", mutation
                ), patch(
                    "application.image_batch.scripts.demo_campaign.restore_original", mutation
                ):
                    with self.assertRaises(ValueError):
                        self.run_main(root)
            self.assertFalse((root / "physical-side-effect").exists())

    def test_ownership_is_held_through_restoration(self):
        """Closure cannot overlap a second supervisor after capture completion."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.state(root)

            def restoration(_root, _environment):
                """Record a prohibited or owned physical closure side effect.

                Args:
                    _root (Path): Campaign directory supplied by the real CLI.
                    _environment (dict): Operational environment supplied by the real CLI.
                """
                with (root / "operations/supervisor.lock").open("a") as contender:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                (root / "closed-under-ownership").touch()

            with patch(
                "application.image_batch.scripts.demo_campaign.drive_campaign", return_value=[]
            ), patch("application.image_batch.scripts.demo_campaign.restore_original", restoration):
                self.run_main(root)
            self.assertTrue((root / "closed-under-ownership").exists())

    def test_uncertain_group_does_not_initiate_restoration(self):
        """Failure preserves resources when physical process termination is unverified."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.state(root)

            def restoration(_root, _environment):
                """Record a prohibited or owned physical closure side effect.

                Args:
                    _root (Path): Campaign directory supplied by the real CLI.
                    _environment (dict): Operational environment supplied by the real CLI.
                """
                (root / "physical-restoration").touch()

            with patch(
                "application.image_batch.scripts.demo_campaign.execute_capture",
                side_effect=PhaseFailure("unverified termination", group_stopped=False),
            ), patch("application.image_batch.scripts.demo_campaign.restore_original", restoration):
                with self.assertRaises(PhaseFailure):
                    self.run_main(root)
            self.assertFalse((root / "physical-restoration").exists())
            saved = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(saved["status"], "capture_failed")
            self.assertEqual(saved["active_request"], ["A", "fixed", 72001])


if __name__ == "__main__":
    unittest.main()
