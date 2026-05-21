"""Unit tests for experiment profile composition helpers."""

import tempfile
import unittest
from pathlib import Path

import yaml

from input.configuration import profile_composition


class ProfileCompositionTests(unittest.TestCase):
    def test_compose_from_experiment_resolves_and_validates_profiles(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            env_path = root / "env.yaml"
            sw_path = root / "sw.yaml"
            exp_path = root / "exp.yaml"

            env_payload = {
                "schema_version": 1,
                "kind": "ContinuumEnvironment",
                "provider": {"name": "qemu", "config": {}},
            }
            sw_payload = {
                "schema_version": 1,
                "kind": "ContinuumSoftware",
                "software": {"modules": []},
            }
            exp_payload = {
                "schema_version": 1,
                "kind": "ContinuumExperiment",
                "use": {"environment": "env", "software": "sw"},
            }

            env_path.write_text(yaml.safe_dump(env_payload), encoding="utf-8")
            sw_path.write_text(yaml.safe_dump(sw_payload), encoding="utf-8")
            exp_path.write_text(yaml.safe_dump(exp_payload), encoding="utf-8")

            seen = {"env": 0, "sw": 0}

            def validate_env(payload, path):
                self.assertEqual(path, env_path)
                self.assertEqual(payload["kind"], "ContinuumEnvironment")
                seen["env"] += 1

            def validate_sw(payload, path):
                self.assertEqual(path, sw_path)
                self.assertEqual(payload["kind"], "ContinuumSoftware")
                seen["sw"] += 1

            environment, software, sources = profile_composition.compose_from_experiment(
                exp_path,
                exp_payload,
                validate_env,
                validate_sw,
            )
            self.assertEqual(environment["kind"], "ContinuumEnvironment")
            self.assertEqual(software["kind"], "ContinuumSoftware")
            self.assertEqual(sources["experiment"], str(exp_path))
            self.assertEqual(sources["environment_profile"], str(env_path))
            self.assertEqual(sources["software_profile"], str(sw_path))
            self.assertEqual(seen, {"env": 1, "sw": 1})


if __name__ == "__main__":
    unittest.main()
