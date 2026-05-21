"""Unit tests for YAML I/O helpers."""

import tempfile
import unittest
from pathlib import Path

from input.configuration import yaml_io


class YamlIoTests(unittest.TestCase):
    def test_load_yaml_rejects_non_mapping(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "bad.yaml"
            path.write_text("- a\n- b\n", encoding="utf-8")
            with self.assertRaises(ValueError) as exc:
                yaml_io.load_yaml(path)
            self.assertIn("Expected top-level YAML mapping", str(exc.exception))

    def test_load_yaml_accepts_mapping(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "ok.yaml"
            path.write_text("a: 1\n", encoding="utf-8")
            self.assertEqual(yaml_io.load_yaml(path), {"a": 1})

    def test_sha256_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "file.txt"
            path.write_text("continuum\n", encoding="utf-8")
            digest_a = yaml_io.sha256(path)
            digest_b = yaml_io.sha256(path)
            self.assertEqual(digest_a, digest_b)
            self.assertEqual(len(digest_a), 64)

    def test_resolve_profile_path_prefers_experiment_relative_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            experiment = root / "exp.yaml"
            env_profile = root / "env.yaml"
            experiment.write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            env_profile.write_text("kind: ContinuumEnvironment\n", encoding="utf-8")

            resolved = yaml_io.resolve_profile_path(experiment, "environment", "env")
            self.assertEqual(resolved, env_profile)

    def test_resolve_profile_path_raises_for_missing_profile(self):
        with tempfile.TemporaryDirectory() as tempdir:
            experiment = Path(tempdir) / "exp.yaml"
            experiment.write_text("kind: ContinuumExperiment\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError) as exc:
                yaml_io.resolve_profile_path(experiment, "environment", "missing-profile")
            self.assertIn("Could not resolve environment profile reference", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
