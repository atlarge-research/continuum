"""Timeout recovery stops only an inspected owned sender and preserves failed captures."""

import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


class RecoveryTests(unittest.TestCase):
    """Check exact container ownership before bounded recovery mutations."""

    def module(self):
        """Load the capture timeout recovery implementation.

        Returns:
            module: Recovery implementation.
        """
        self.assertIsNotNone(importlib.util.find_spec("demo_recovery"))
        return importlib.import_module("demo_recovery")

    def test_sender_stop_uses_verified_id_and_preserves_incomplete_namespace(self):
        """Persist identity before stop and retain observer evidence without namespace deletion."""
        # Each mock callback is consumed synchronously before the next subtest starts.
        # pylint: disable=cell-var-from-loop
        module = self.module()
        for owned, log_timeout in ((True, False), (True, True), (False, False)):
            with self.subTest(
                owned=owned, log_timeout=log_timeout
            ), tempfile.TemporaryDirectory() as temporary:
                capture = Path(temporary) / "fns-test"
                capture.mkdir()
                invocation = {
                    "namespace": "fns-test",
                    "output": str(capture),
                    "endpoint": "owner@endpoint",
                    "controller": "owner@controller",
                    "ssh_key": "/key",
                    "endpoint_image": "sender:pinned",
                }
                (capture / "invocation.json").write_text(json.dumps(invocation))
                pod = {"metadata": {"name": "observer", "uid": "pod-original"}}
                (capture / "pod-start.json").write_text(json.dumps(pod))
                identifier = "a" * 64
                container = {
                    "Id": identifier,
                    "Config": {"Image": "sender:pinned", "Cmd": ["--run-id", "fns-test"]},
                    "Mounts": [
                        {
                            "Source": "/tmp/fns-test" if owned else "/someone-else",
                            "Destination": "/review",
                        }
                    ],
                }
                commands = []

                def remote(_host, _key, command, **_kwargs):
                    """Emulate the Docker API boundary while observing durable stop intent.

                    Args:
                        _host (str): Recorded endpoint destination.
                        _key (str): Recorded SSH identity.
                        command (list[str]): Quoted Docker argument vector.
                        **_kwargs (dict): Bounded remote execution options.

                    Returns:
                        bytes: Exact inventory, inspection or log output for this operation.
                    """
                    commands.append(command)
                    if "inspect" in command:
                        return json.dumps([container]).encode()
                    if "logs" in command:
                        if log_timeout:
                            raise subprocess.TimeoutExpired(command, 30)
                        return b"preserved sender log"
                    if "stop" in command:
                        self.assertEqual(command[-1], identifier)
                        report = json.loads(
                            (capture / "timeout-recovery/recovery.json").read_text()
                        )
                        self.assertEqual(report["endpoint_container_id"], identifier)
                        self.assertEqual(report["endpoint_status"], "stop_requested")
                        return identifier.encode()
                    return b"" if any("stop" in row for row in commands) else identifier.encode()

                session = Mock()
                session.get.return_value = pod
                with patch.object(module, "ssh", side_effect=remote), patch.object(
                    module, "CaptureSession", return_value=session
                ):
                    result = module.recover_capture(capture)
                self.assertEqual(result["endpoint_stopped"], owned)
                self.assertEqual(any("stop" in row for row in commands), owned)
                self.assertFalse(result["restoration_complete"])
                session.restore.assert_not_called()
                self.assertFalse((capture / "cleanup.json").exists())
                if owned:
                    session.archive_observer.assert_called_once()
                    if log_timeout:
                        self.assertTrue(result["errors"])
                    else:
                        self.assertEqual(
                            (capture / "timeout-recovery/endpoint.log").read_text(),
                            "preserved sender log",
                        )

    def test_missing_identity_is_recorded_without_remote_mutation(self):
        """A timeout before invocation persistence cannot invent capture ownership."""
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary, patch.object(module, "ssh") as remote:
            capture = Path(temporary) / "capture"
            result = module.recover_capture(capture)
            self.assertFalse(result["endpoint_stopped"])
            self.assertFalse(result["restoration_complete"])
            self.assertTrue(result["errors"])
            remote.assert_not_called()
            self.assertTrue((capture / "timeout-recovery/recovery.json").exists())


if __name__ == "__main__":
    unittest.main()
