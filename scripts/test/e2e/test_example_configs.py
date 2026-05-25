"""Regression tests for shipped YAML experiment examples."""

# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access

import argparse
import unittest
from pathlib import Path
from unittest import mock

from input import input as input_module
from input.configuration import yaml_io, yaml_parser


class ExampleConfigTests(unittest.TestCase):
    class _FakeHostIpSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, _target):
            return None

        def getsockname(self):
            return ("127.0.0.1", 5000)

    def setUp(self):
        self._socket_patcher = mock.patch(
            "input.configuration.runtime_module_loader.socket_lib.socket",
            side_effect=lambda *_args, **_kwargs: self._FakeHostIpSocket(),
        )
        self._socket_patcher.start()

    def tearDown(self):
        self._socket_patcher.stop()

    def _repo_root(self):
        return Path(__file__).resolve().parents[3]

    def _repo_relative_yaml_paths(self, root, directory):
        return sorted(path.relative_to(root).as_posix() for path in directory.glob("**/*.yaml"))

    def test_shipped_experiment_examples_parse(self):
        root = self._repo_root()
        experiment_paths = sorted((root / "configs" / "experiments").glob("**/*.yaml"))

        self.assertTrue(experiment_paths, "expected shipped experiment examples")

        for experiment_path in experiment_paths:
            with self.subTest(experiment=str(experiment_path.relative_to(root))):
                parser = argparse.ArgumentParser(prog="example-config-test")
                cfg = input_module.start(parser, str(experiment_path))
                self.assertEqual(cfg["config_format"], "yaml")
                self.assertIn("normalized", cfg)
                self.assertIn("domains", cfg)
                self.assertIn("sources", cfg["normalized"])

    def test_configuration_reference_lists_shipped_yaml(self):
        root = self._repo_root()
        reference = (root / "docs" / "configuration_reference.md").read_text(encoding="utf-8")
        expected_paths = []
        expected_paths.extend(
            self._repo_relative_yaml_paths(root, root / "configs" / "experiments")
        )
        expected_paths.extend(
            self._repo_relative_yaml_paths(root, root / "configs" / "profiles")
        )

        missing = [path for path in expected_paths if "`%s`" % (path,) not in reference]

        self.assertEqual(missing, [])

    def test_benchmark_smoke_infra_opts_into_resume_prep(self):
        root = self._repo_root()
        experiment_path = (
            root
            / "configs"
            / "experiments"
            / "benchmark_smoke"
            / "01_infra_k8s_three_vm.yaml"
        )
        parser = argparse.ArgumentParser(prog="benchmark-smoke-infra-config-test")

        cfg = input_module.start(parser, str(experiment_path))

        self.assertTrue(cfg["domains"]["run"]["prepare_for_resume"])
        self.assertTrue(cfg["module"]["resource_manager"])

    def test_shipped_environment_profiles_validate(self):
        root = self._repo_root()
        profile_paths = sorted((root / "configs" / "profiles" / "environment").glob("*.yaml"))

        self.assertTrue(profile_paths, "expected shipped environment profiles")

        for profile_path in profile_paths:
            with self.subTest(profile=str(profile_path.relative_to(root))):
                payload = yaml_io.load_yaml(profile_path)
                yaml_parser._validate_environment(payload, profile_path)

    def test_shipped_software_profiles_validate(self):
        root = self._repo_root()
        profile_paths = sorted((root / "configs" / "profiles" / "software").glob("*.yaml"))

        self.assertTrue(profile_paths, "expected shipped software profiles")

        for profile_path in profile_paths:
            with self.subTest(profile=str(profile_path.relative_to(root))):
                payload = yaml_io.load_yaml(profile_path)
                yaml_parser._validate_software_profile(payload, profile_path)
