"""Native staging cleanup refuses live work and preserves exact bytes first."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import demo_cleanup


class CleanupTests(unittest.TestCase):
    """Exercise cleanup ordering at the SSH boundary without remote mutation."""

    def test_live_namespace_blocks_archive_and_removal(self):
        """A live namespace must not lose native files even after an old cleanup record."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invocation.json").write_text(
                json.dumps(
                    {
                        "namespace": "fns-test",
                        "controller": "host",
                        "ssh_key": "key",
                        "control_node": "node",
                    }
                )
            )
            (root / "cleanup.json").write_text('{"namespace_removed": true}')
            with patch.object(demo_cleanup, "ssh", return_value=b'{"metadata": {}}') as remote:
                with self.assertRaisesRegex(ValueError, "namespace"):
                    demo_cleanup.cleanup_native(root)
            self.assertEqual(remote.call_count, 1)

    def check_archive(self, matching):
        """Exercise exact-byte archival with either matching or mismatching hashes.

        Args:
            matching (bool): Whether the remote hash agrees with the preserved bytes.
        """
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as stream:
            item = tarfile.TarInfo("result.txt")
            item.size = 4
            stream.addfile(item, io.BytesIO(b"data"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invocation.json").write_text(
                json.dumps(
                    {
                        "namespace": "fns-test",
                        "controller": "host",
                        "ssh_key": "key",
                        "control_node": "node",
                    }
                )
            )
            (root / "cleanup.json").write_text('{"namespace_removed": true}')
            digest = hashlib.sha256(b"data").hexdigest() if matching else "wrong"
            hashes = json.dumps({"result.txt": digest}).encode()
            replies = [
                b"",
                b"node\n",
                b'["/var/tmp/fns-opendc-fns-test-native-0001"]',
                hashes,
                archive.getvalue(),
                hashes,
            ]
            if matching:
                replies.extend([b"", b"[]"])
            with patch.object(demo_cleanup, "ssh", side_effect=replies) as remote:
                if matching:
                    result = demo_cleanup.cleanup_native(root)
                    self.assertTrue(result["verified_absent"])
                else:
                    with self.assertRaisesRegex(ValueError, "hash"):
                        demo_cleanup.cleanup_native(root)
            self.assertEqual(any("rm" in call.args[2] for call in remote.call_args_list), matching)
            self.assertTrue((root / "native-cleanup/native-0001/artifacts.tar").exists())

    def test_archive_hash_mismatch_prevents_removal(self):
        """Incomplete local evidence cannot authorize deleting remote artifacts."""
        self.check_archive(False)

    def test_verified_archive_is_retained_before_removal(self):
        """Successful cleanup keeps the archive and confirms no owned directories remain."""
        self.check_archive(True)


if __name__ == "__main__":
    unittest.main()
