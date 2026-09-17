"""Runtime routing contracts, without changing the test host's network."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "qemu/infrastructure/continuum_replay.py"


class ReplayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "checked replay launcher is not installed")
        spec = importlib.util.spec_from_file_location("continuum_replay", SCRIPT)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    def test_scoped_rules_preserve_direction_and_have_exact_undo(self):
        pairs = self.runtime.routing_commands(
            "192.168.210.6", ["192.168.210.3"], "mm-link-123"
        )
        additions = [add for add, _undo in pairs]
        self.assertIn(
            ["ip", "route", "add", "192.168.210.3/32", "via", "10.0.0.2"], additions
        )
        self.assertIn(
            [
                "iptables",
                "-w",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                "192.168.210.6",
                "-d",
                "192.168.210.3",
                "-o",
                "mm-link-123",
                "-m",
                "comment",
                "--comment",
                "continuum-mahimahi",
                "-j",
                "MASQUERADE",
            ],
            additions,
        )
        self.assertIn(
            [
                "iptables",
                "-w",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                "10.0.0.2",
                "-d",
                "192.168.210.3",
                "-o",
                "ens2",
                "-m",
                "comment",
                "--comment",
                "continuum-mahimahi",
                "-j",
                "MASQUERADE",
            ],
            additions,
        )
        for add, undo in pairs:
            self.assertNotIn("-F", add)
            self.assertNotIn("flush", add)
            self.assertNotIn("flush", undo)
            if add[0] == "iptables":
                self.assertEqual(
                    undo, ["-D" if token in ("-A", "-I") else token for token in add]
                )

    def test_failed_install_rolls_back_partial_routes_and_nat(self):
        calls = []

        def run(command, check=True):
            calls.append(command)
            if command == ["broken"]:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            self.runtime, "run", run
        ):
            state = {"undo": []}
            with self.assertRaises(subprocess.CalledProcessError):
                self.runtime.apply_routing(
                    [(["first"], ["undo-first"]), (["broken"], ["undo-broken"])],
                    state,
                    Path(temporary) / "state.json",
                )
            self.assertEqual(calls, [["first"], ["broken"], ["undo-first"]])

    def test_trace_validation_rejects_empty_negative_and_reversed_schedules(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace"
            for data in ("", "-1\n2\n", "2\n1\n", "1.5\n", "0\n"):
                path.write_text(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    self.runtime.validate_trace(path)
            path.write_text("0\n1\n1\n10\n")
            result = self.runtime.validate_trace(path)
            self.assertEqual((result["packets"], result["duration_ms"]), (4, 10))

    def test_readiness_failure_does_not_report_started(self):
        def run(command, check=True):
            return subprocess.CompletedProcess(command, 3, "", "")

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            self.runtime, "run", run
        ):
            with self.assertRaisesRegex(RuntimeError, "exited"):
                self.runtime.wait_ready(Path(temporary), timeout=0.01)

    def test_cleanup_ignores_absent_rule_but_retains_permission_failures(self):
        def run(command, check=True):
            message = (
                "RTNETLINK answers: No such process"
                if command == ["absent"]
                else "Operation not permitted"
            )
            return subprocess.CompletedProcess(command, 2, "", message)

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            self.runtime, "run", run
        ):
            state = {"undo": [["absent"], ["denied"]]}
            failed = self.runtime.undo_routing(state, Path(temporary) / "state.json")
            self.assertEqual(failed, [["denied"]])

    def test_layout_mismatch_fails_before_any_network_mutation(self):
        commands = []

        def run(command, check=True):
            commands.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                '[{"ifname":"eth0","addr_info":[{"local":"192.168.210.6","prefixlen":16}]}]',
                "",
            )

        with patch.object(self.runtime, "run", run):
            with self.assertRaisesRegex(RuntimeError, "VM layout differs"):
                self.runtime.preflight("192.168.210.6", ["192.168.210.3"])
        self.assertEqual(commands, [["ip", "-j", "-4", "address", "show"]])

    def test_cleanup_of_collected_service_and_real_stop_failure_are_distinct(self):
        for load_state in ("not-found", "loaded"):

            def run(command, check=True):
                output = load_state if "show" in command else ""
                return subprocess.CompletedProcess(command, 1, output, "stop failed")

            with self.subTest(load_state=load_state), patch.object(
                self.runtime, "run", run
            ):
                if load_state == "not-found":
                    self.runtime.stop_service()
                else:
                    with self.assertRaisesRegex(RuntimeError, "could not stop"):
                        self.runtime.stop_service()
