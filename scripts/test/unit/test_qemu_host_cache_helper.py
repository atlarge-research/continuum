"""Focused tests for the standalone QEMU host cache helper."""

import base64
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from infrastructure.qemu import host_cache_helper
from infrastructure.qemu import qemu as qemu_module


class QemuHostCacheHelperTests(unittest.TestCase):
    def test_controller_loads_exact_helper_source_and_shared_protocol(self):
        helper_source = pathlib.Path(host_cache_helper.__file__).read_text(encoding="utf-8")

        self.assertEqual(qemu_module._HOST_CACHE_HELPER_SOURCE, helper_source)
        self.assertEqual(qemu_module._CACHE_PROTOCOL, host_cache_helper.PROTOCOL)

    def test_check_returns_exact_metadata_bytes_and_invalid_reasons(self):
        with tempfile.TemporaryDirectory() as tempdir:
            image_path = pathlib.Path(tempdir) / "base.qcow2"
            metadata_path = pathlib.Path(tempdir) / "base.meta.json"
            metadata = b'{"schema_version":1}\n'
            image_path.write_bytes(b"qcow2")
            metadata_path.write_bytes(metadata)

            self.assertEqual(
                host_cache_helper.check(str(image_path), str(metadata_path)),
                {
                    "status": "ok",
                    "metadata_b64": base64.b64encode(metadata).decode("ascii"),
                },
            )

            image_path.unlink()
            self.assertEqual(
                host_cache_helper.check(str(image_path), str(metadata_path)),
                {"status": "invalid", "reason": "image missing"},
            )
            image_path.write_bytes(b"qcow2")
            metadata_path.unlink()
            self.assertEqual(
                host_cache_helper.check(str(image_path), str(metadata_path)),
                {"status": "invalid", "reason": "metadata missing"},
            )

        with mock.patch.object(host_cache_helper, "readable", return_value="unreadable"):
            self.assertEqual(
                host_cache_helper.check("image", "metadata"),
                {"status": "invalid", "reason": "image unreadable"},
            )
        with mock.patch.object(host_cache_helper, "readable", return_value=None):
            with mock.patch("builtins.open", side_effect=PermissionError("denied")):
                self.assertEqual(
                    host_cache_helper.check("image", "metadata"),
                    {"status": "invalid", "reason": "metadata unreadable"},
                )

    def test_cleanup_preserves_exact_order_and_fsyncs_each_removed_parent(self):
        paths = ["ready", "image", "cloud-init", "user-data"]
        events = []

        def unlink(path):
            events.append(("unlink", path))

        def fsync_parent(path):
            events.append(("fsync", path))

        with mock.patch.object(host_cache_helper.os, "unlink", side_effect=unlink):
            with mock.patch.object(
                host_cache_helper, "_fsync_parent", side_effect=fsync_parent
            ):
                host_cache_helper.remove_paths(paths)

        self.assertEqual(
            events,
            [
                ("unlink", "ready"),
                ("fsync", "ready"),
                ("unlink", "image"),
                ("fsync", "image"),
                ("unlink", "cloud-init"),
                ("fsync", "cloud-init"),
                ("unlink", "user-data"),
                ("fsync", "user-data"),
            ],
        )

    def test_successful_unlink_opens_fsyncs_and_closes_parent_directory(self):
        events = []

        with mock.patch.object(
            host_cache_helper.os,
            "unlink",
            side_effect=lambda path: events.append(("unlink", path)),
        ):
            with mock.patch.object(
                host_cache_helper.os,
                "open",
                side_effect=lambda path, flags: events.append(("open", path, flags)) or 17,
            ):
                with mock.patch.object(
                    host_cache_helper.os,
                    "fsync",
                    side_effect=lambda descriptor: events.append(("fsync", descriptor)),
                ):
                    with mock.patch.object(
                        host_cache_helper.os,
                        "close",
                        side_effect=lambda descriptor: events.append(("close", descriptor)),
                    ):
                        removed = host_cache_helper._durable_unlink("cache/ready")

        self.assertTrue(removed)
        self.assertEqual(
            events,
            [
                ("unlink", "cache/ready"),
                ("open", "cache", host_cache_helper.os.O_RDONLY),
                ("fsync", 17),
                ("close", 17),
            ],
        )

    def test_missing_path_is_benign_without_directory_durability_work(self):
        with mock.patch.object(
            host_cache_helper.os, "unlink", side_effect=FileNotFoundError
        ):
            with mock.patch.object(host_cache_helper.os, "open") as open_mock:
                self.assertFalse(host_cache_helper._durable_unlink("already-absent"))
        open_mock.assert_not_called()

    def test_directory_open_fsync_and_close_failures_propagate(self):
        failures = ("open", "fsync", "close")
        for failure in failures:
            with self.subTest(failure=failure):
                open_side_effect = OSError("open failed") if failure == "open" else None
                fsync_side_effect = OSError("fsync failed") if failure == "fsync" else None
                close_side_effect = OSError("close failed") if failure == "close" else None
                with mock.patch.object(host_cache_helper.os, "unlink"):
                    with mock.patch.object(
                        host_cache_helper.os,
                        "open",
                        return_value=19,
                        side_effect=open_side_effect,
                    ):
                        with mock.patch.object(
                            host_cache_helper.os, "fsync", side_effect=fsync_side_effect
                        ):
                            with mock.patch.object(
                                host_cache_helper.os, "close", side_effect=close_side_effect
                            ):
                                with self.assertRaisesRegex(OSError, "%s failed" % (failure,)):
                                    host_cache_helper._durable_unlink("cache/ready")

    def test_failed_operation_emits_no_success_response(self):
        stdout = io.StringIO()
        with mock.patch.object(
            host_cache_helper, "remove_paths", side_effect=OSError("fsync failed")
        ):
            with contextlib.redirect_stdout(stdout):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    host_cache_helper.main(["helper", "invalidate", "ready"])
        self.assertEqual(stdout.getvalue(), "")

    def test_publish_success_is_atomic_and_durable(self):
        payload = b'{"schema_version":1,"status":"ready"}\n'
        with tempfile.TemporaryDirectory() as tempdir:
            metadata_path = pathlib.Path(tempdir) / "ready.meta.json"

            host_cache_helper.publish(
                str(metadata_path), base64.b64encode(payload).decode("ascii")
            )

            self.assertEqual(metadata_path.read_bytes(), payload)
            self.assertEqual(list(pathlib.Path(tempdir).glob("*.tmp")), [])

    def test_publish_failures_remove_temporary_and_final_markers(self):
        stages = (
            "write",
            "short-write",
            "flush",
            "file-fsync",
            "replace",
            "directory-fsync",
        )
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tempdir:
                metadata_path = pathlib.Path(tempdir) / "ready.meta.json"
                encoded = base64.b64encode(b"ready metadata").decode("ascii")
                real_fdopen = host_cache_helper.os.fdopen
                real_fsync = host_cache_helper.os.fsync
                real_replace = host_cache_helper.os.replace

                class FaultyFile:
                    def __init__(self, filep):
                        self.filep = filep

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return self.filep.__exit__(*args)

                    def write(self, payload):
                        if stage == "write":
                            raise OSError("injected write failure")
                        written = self.filep.write(payload)
                        return written - 1 if stage == "short-write" else written

                    def flush(self):
                        if stage == "flush":
                            raise OSError("injected flush failure")
                        return self.filep.flush()

                    def fileno(self):
                        return self.filep.fileno()

                fsync_calls = []

                def failing_fsync(descriptor):
                    fsync_calls.append(descriptor)
                    if stage == "file-fsync" and len(fsync_calls) == 1:
                        raise OSError("injected file fsync failure")
                    if stage == "directory-fsync" and len(fsync_calls) == 2:
                        raise OSError("injected directory fsync failure")
                    return real_fsync(descriptor)

                def wrapped_fdopen(*args, **kwargs):
                    return FaultyFile(real_fdopen(*args, **kwargs))

                def failing_replace(source, destination):
                    if stage == "replace":
                        raise OSError("injected replace failure")
                    return real_replace(source, destination)

                with mock.patch.object(
                    host_cache_helper.os, "fdopen", side_effect=wrapped_fdopen
                ):
                    with mock.patch.object(
                        host_cache_helper.os, "fsync", side_effect=failing_fsync
                    ):
                        with mock.patch.object(
                            host_cache_helper.os, "replace", side_effect=failing_replace
                        ):
                            with self.assertRaises(OSError):
                                host_cache_helper.publish(str(metadata_path), encoded)

                self.assertFalse(metadata_path.exists())
                self.assertEqual(list(pathlib.Path(tempdir).glob("*.tmp")), [])

    def test_main_dispatches_cli_argv_and_emits_only_after_success(self):
        response = {"status": "ok", "metadata_b64": "e30="}
        cases = (
            ("check", ["image", "metadata"]),
            ("cleanup", ["metadata", "image", "cloud-init", "user-data"]),
            ("invalidate", ["metadata"]),
            ("publish", ["metadata", "payload"]),
        )
        for operation, arguments in cases:
            with self.subTest(operation=operation):
                with mock.patch.object(host_cache_helper, "check", return_value=response) as check:
                    with mock.patch.object(host_cache_helper, "remove_paths") as remove_paths:
                        with mock.patch.object(host_cache_helper, "publish") as publish:
                            with mock.patch.object(host_cache_helper, "_emit") as emit:
                                host_cache_helper.main(["helper", operation] + arguments)

                if operation == "check":
                    check.assert_called_once_with("image", "metadata")
                    emit.assert_called_once_with(response)
                elif operation in ("cleanup", "invalidate"):
                    remove_paths.assert_called_once_with(arguments)
                    emit.assert_called_once_with({"status": "ok"})
                else:
                    publish.assert_called_once_with("metadata", "payload")
                    emit.assert_called_once_with({"status": "ok"})

    def test_main_emits_one_machine_readable_protocol_response(self):
        stdout = io.StringIO()
        with mock.patch.object(
            host_cache_helper,
            "check",
            return_value={"status": "invalid", "reason": "image missing"},
        ):
            with contextlib.redirect_stdout(stdout):
                host_cache_helper.main(["helper", "check", "image", "metadata"])

        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            json.loads(lines[0]),
            {
                "protocol": host_cache_helper.PROTOCOL,
                "reason": "image missing",
                "status": "invalid",
            },
        )


if __name__ == "__main__":
    unittest.main()
