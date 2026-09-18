"""Runtime routing contracts, without changing the test host's network."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "qemu/infrastructure/continuum_replay.py"


class ReplayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "checked replay launcher is not installed")
        spec = importlib.util.spec_from_file_location("continuum_replay", SCRIPT)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    @contextmanager
    def launcher(self):
        """Real files/lifecycle with VM commands replaced at the process boundary."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            runtime = root / "run"
            runtime.mkdir()
            marker = root / (".installed-" + self.runtime.REVISION + "-" + self.runtime.PATCH_ID)
            marker.write_text(self.runtime.REVISION)
            trace = root / "trace"
            trace.write_text("1\n10\n")
            commands = []

            def run(command, check=True):
                commands.append(command)
                code = 3 if command[:2] == ["systemctl", "is-active"] else 0
                return subprocess.CompletedProcess(command, code, "", "")

            stack.enter_context(patch.object(self.runtime, "RUNTIME", runtime))
            stack.enter_context(patch.object(self.runtime, "BUILD", root))
            stack.enter_context(patch.object(self.runtime, "run", run))
            stack.enter_context(patch.object(self.runtime, "preflight"))
            stack.enter_context(patch.object(self.runtime, "wait_ready"))
            stack.enter_context(patch.object(self.runtime, "check"))
            stack.enter_context(
                patch.object(
                    self.runtime,
                    "read_json",
                    return_value=[{"dev": "mm-test", "prefsrc": self.runtime.OUTER}],
                )
            )
            stack.enter_context(patch.dict(os.environ, {"SUDO_UID": "1000"}))
            stack.enter_context(
                patch.object(
                    self.runtime.pwd,
                    "getpwuid",
                    return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name="endpoint"),
                )
            )
            yield runtime / "state.json", trace, commands

    def test_start_keeps_identity_without_packet_logs(self):
        with self.launcher() as (path, trace, commands):
            self.runtime.start("192.168.210.6", ["192.168.210.3"], trace, trace, path)
            launch = next(c for c in commands if c[0] == "systemd-run")
            self.assertFalse(any(c.startswith(("--uplink-log", "--downlink-log")) for c in launch))
            self.assertEqual(list(path.parent.glob("logs-*")), [])
            state = json.loads(path.read_text())
            self.assertNotIn("logs", state)
            self.assertEqual(state["revision"], self.runtime.REVISION)
            self.assertEqual(state["status"], "ready")
            self.assertEqual(
                state["traces"][0],
                {
                    "path": str(trace),
                    "sha256": hashlib.sha256(b"1\n10\n").hexdigest(),
                    "packets": 2,
                    "duration_ms": 10,
                },
            )

    def test_stop_retains_recovery_state_when_service_shutdown_fails(self):
        with self.launcher() as (path, _trace, commands):
            state = {"undo": [["undo-route"]]}
            self.runtime.save_state(path, state)
            original_run = self.runtime.run

            def run(command, check=True):
                if command[:2] == ["systemctl", "stop"]:
                    return subprocess.CompletedProcess(command, 1, "", "denied")
                if command[:2] == ["systemctl", "show"]:
                    return subprocess.CompletedProcess(command, 0, "loaded", "")
                return original_run(command, check)

            with patch.object(self.runtime, "run", run):
                with self.assertRaisesRegex(RuntimeError, "service shutdown.*denied.*retained"):
                    self.runtime.stop(state, path)
            self.assertIn(["undo-route"], commands)
            self.assertEqual(json.loads(path.read_text())["undo"], [])
            self.runtime.stop(json.loads(path.read_text()), path)
            self.assertFalse(path.exists())

    def test_stop_attempts_service_shutdown_after_state_write_failure_and_can_retry(
        self,
    ):
        for error in (errno.ENOSPC, errno.EACCES):
            with self.subTest(error=error), self.launcher() as (path, _trace, commands):
                state = {
                    "undo": [["undo-route"]],
                    "logs": str(path.parent / "old-logs"),
                }
                historical = Path(state["logs"])
                historical.mkdir()
                (historical / "uplink.log").write_text("retained evidence\n")
                self.runtime.save_state(path, state)
                with patch.object(
                    self.runtime,
                    "save_state",
                    side_effect=OSError(error, os.strerror(error)),
                ):
                    with self.assertRaisesRegex(RuntimeError, "retained"):
                        self.runtime.stop(state, path)
                self.assertIn(["undo-route"], commands)
                self.assertIn(["systemctl", "stop", self.runtime.UNIT], commands)
                self.assertEqual(json.loads(path.read_text())["undo"], [["undo-route"]])
                self.runtime.stop(json.loads(path.read_text()), path)
                self.assertFalse(path.exists())
                self.assertEqual((historical / "uplink.log").read_text(), "retained evidence\n")

    def test_cleanup_continues_after_command_launch_failure(self):
        with self.launcher() as (path, _trace, commands):
            state = {"undo": [["other-rule"], ["missing-command"]]}
            self.runtime.save_state(path, state)
            original_run = self.runtime.run

            def run(command, check=True):
                if command == ["missing-command"]:
                    raise FileNotFoundError("missing-command")
                return original_run(command, check)

            with patch.object(self.runtime, "run", run):
                with self.assertRaisesRegex(RuntimeError, "retained"):
                    self.runtime.stop(state, path)
            self.assertIn(["other-rule"], commands)
            self.assertIn(["systemctl", "stop", self.runtime.UNIT], commands)
            self.assertEqual(json.loads(path.read_text())["undo"], [["missing-command"]])
            self.runtime.stop(json.loads(path.read_text()), path)
            self.assertFalse(path.exists())

    def test_startup_rollback_stops_service_when_state_storage_fills(self):
        with self.launcher() as (path, trace, commands):
            save = self.runtime.save_state

            def save_until_ready(path, state):
                if state.get("status") == "ready":
                    raise OSError(errno.ENOSPC, "No space left on device")
                save(path, state)

            with patch.object(self.runtime, "save_state", save_until_ready):
                with self.assertRaisesRegex(RuntimeError, "No space left on device"):
                    self.runtime.start("192.168.210.6", ["192.168.210.3"], trace, trace, path)
            self.assertIn(["systemctl", "stop", self.runtime.UNIT], commands)
            persisted = json.loads(path.read_text())
            self.assertTrue(persisted["undo"])
            for command in persisted["undo"]:
                self.assertIn(command, commands)
            self.runtime.stop(persisted, path)
            self.assertFalse(path.exists())

    def test_scoped_rules_preserve_direction_and_have_exact_undo(self):
        pairs = self.runtime.routing_commands("192.168.210.6", ["192.168.210.3"], "mm-link-123")
        additions = [add for add, _undo in pairs]
        self.assertIn(["ip", "route", "add", "192.168.210.3/32", "via", "10.0.0.2"], additions)
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
                self.assertEqual(undo, ["-D" if token in ("-A", "-I") else token for token in add])

    def test_failed_install_rolls_back_partial_routes_and_nat(self):
        calls = []

        def run(command, check=True):
            calls.append(command)
            if command == ["broken"]:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runtime, "run", run):
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

        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runtime, "run", run):
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

        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runtime, "run", run):
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

            with self.subTest(load_state=load_state), patch.object(self.runtime, "run", run):
                if load_state == "not-found":
                    self.runtime.stop_service()
                else:
                    with self.assertRaisesRegex(RuntimeError, "could not stop"):
                        self.runtime.stop_service()
