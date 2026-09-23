"""The direct runner must preserve exports while adapting the pinned reader."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import prepare, verify_inputs


class InputTests(unittest.TestCase):
    """Check controlled-input conversion, fixture integrity and overwrite refusal."""

    def test_fns_runtime_preserves_source_and_emits_datacenter_and_nullable_hosts(self):
        """Adapt the new SDK while keeping original memory, timing and source schema intact."""
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "fns-demo"}
        ):
            target = Path(root) / "inputs"
            manifest = prepare("memory", target)
            topology = json.loads((target / "topology.json").read_text())
            self.assertIn("datacenters", topology)
            datacenter = topology["datacenters"][0]
            self.assertIn("powerSource", datacenter)
            self.assertNotIn("powerSource", datacenter["clusters"][0])
            self.assertEqual(datacenter["clusters"][0]["hosts"][0]["cpu"]["coreCount"], 2)
            native = pq.read_table(target / "trace/tasks.parquet")
            source = pq.read_table(target / "source/tasks.parquet")
            self.assertEqual(native["host"].to_pylist(), [None, None])
            self.assertNotIn("host", source.schema.names)
            self.assertEqual(native["mem_capacity"].to_pylist(), [384000, 384000])
            self.assertEqual(source["mem_capacity"].to_pylist(), [384, 384])
            self.assertEqual(manifest["opendc_commit"], "cf10c06eb73c7e60e1076e376922b1201caf12d1")
            self.assertEqual(manifest["example_commit"], "41aaa9e20a4e299329924454316e6c91eb39f42f")
            self.assertFalse(manifest["developer_binary_equivalence_verified"])
            self.assertEqual(verify_inputs(target)["opendc_commit"], manifest["opendc_commit"])

    def test_fns_runner_rejects_legacy_inputs_even_when_hashes_are_valid(self):
        """Never launch inputs prepared for the other engine revision."""
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "inputs"
            prepare("memory", target)
            with mock.patch.dict(os.environ, {"OPENDC_RUNTIME": "fns-demo"}):
                with self.assertRaisesRegex(ValueError, "version"):
                    verify_inputs(target)

    def test_unknown_runtime_is_rejected_before_preparation(self):
        """A misspelled runtime must not silently select the legacy engine."""
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
            os.environ, {"OPENDC_RUNTIME": "unrecognized"}
        ):
            with self.assertRaisesRegex(ValueError, "runtime"):
                prepare("memory", Path(root) / "inputs")

    def test_container_revision_cannot_be_overridden_by_runtime_selection(self):
        """Reject selection of the new input contract inside a preserved engine image."""
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
            os.environ,
            {
                "OPENDC_RUNTIME": "fns-demo",
                "OPENDC_BUILD_COMMIT": "7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad",
            },
        ):
            with self.assertRaisesRegex(ValueError, "build revision"):
                prepare("memory", Path(root) / "inputs")
            self.assertFalse((Path(root) / "inputs").exists())

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
