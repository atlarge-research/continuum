"""The direct runner must preserve exports while adapting the pinned reader."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import prepare, verify_inputs


class InputTests(unittest.TestCase):
    """Check controlled-input conversion, fixture integrity and overwrite refusal."""

    def test_controlled_exports_preserve_profiles_and_convert_memory(self):
        """Check IDs, fragment order and timestamp values survive the memory-unit adapter."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "inputs"
            prepare("controlled", target)
            source = pq.read_table(target / "source/tasks.parquet")
            native = pq.read_table(target / "trace/tasks.parquet")
            self.assertEqual(source.num_rows, 13)
            self.assertEqual(source["mem_capacity"].to_pylist(), [512] * 13)
            self.assertEqual(native["mem_capacity"].to_pylist(), [512000] * 13)
            self.assertEqual(
                native["submission_time"].cast(pa.int64()).to_pylist(), [0] * 12 + [1000]
            )
            self.assertEqual(
                native.schema.field("submission_time").type, pa.timestamp("ms", tz="UTC")
            )
            fragments = pq.read_table(target / "trace/fragments.parquet").to_pylist()
            self.assertEqual(
                fragments[:2],
                [
                    {"id": 0, "duration": 5000, "cpu_count": 1, "cpu_usage": 2400.0},
                    {"id": 0, "duration": 5000, "cpu_count": 1, "cpu_usage": 1200.0},
                ],
            )
            self.assertEqual(fragments[-1]["id"], 12)
            self.assertEqual(verify_inputs(target)["fixture"], "controlled")

    def test_memory_fixture_has_enough_cpu_but_not_memory_for_both(self):
        """Ensure RAM, rather than CPU count, is the admission constraint in this fixture."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "inputs"
            prepare("memory", target)
            tasks = pq.read_table(target / "trace/tasks.parquet").to_pylist()
            topology = json.loads((target / "topology.json").read_text())
            host = topology["clusters"][0]["hosts"][0]
            self.assertEqual(host["cpu"]["coreCount"], 2)
            self.assertEqual(host["memory"]["size"], "512 MiB")
            self.assertEqual([t["mem_capacity"] for t in tasks], [384000, 384000])

    def test_inputs_for_another_source_commit_are_rejected(self):
        """Reject a ready-looking input prepared for a different upstream revision."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "inputs"
            manifest = prepare("controlled", target)
            manifest["opendc_commit"] = "ac6a11f2eb9e415b9f8782424d975adbd0d2ddd9"
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "version"):
                verify_inputs(target)

    def test_overwrite_and_changed_input_are_rejected(self):
        """Protect an existing experiment and detect later changes to its trace files."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "inputs"
            prepare("controlled", target)
            before = (target / "manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare("controlled", target)
            self.assertEqual((target / "manifest.json").read_bytes(), before)
            (target / "trace/fragments.parquet").write_bytes(b"broken parquet")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_inputs(target)

    def test_simulation_bundle_cannot_be_used_as_controlled_input(self):
        """Keep live-state bundles outside the controlled execution contract."""
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "manifest.json").write_text(
                json.dumps({"schema_version": 2, "status": "ready"})
            )
            with self.assertRaisesRegex(ValueError, "controlled"):
                verify_inputs(Path(root))


if __name__ == "__main__":
    unittest.main()
