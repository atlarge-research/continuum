"""Unit tests for canonical resume contract metadata."""

import argparse
import unittest
from pathlib import Path
from unittest import mock

from input import input as input_module
from input.configuration import resume_contract


class ResumeContractTests(unittest.TestCase):
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
        return Path(__file__).resolve().parents[2]

    def _parse_config(self, relative_path):
        parser = argparse.ArgumentParser(prog="resume-contract-test")
        return input_module.start(parser, str(self._repo_root() / relative_path))

    def test_benchmark_smoke_contract_is_stable_across_resume_phase_configs(self):
        config_paths = [
            "configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml",
            "configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml",
            "configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml",
        ]

        sections = [
            resume_contract.build_persisted_resume_contract(self._parse_config(path))
            for path in config_paths
        ]

        self.assertEqual(len({section["hash"] for section in sections}), 1)
        details = sections[0]["details"]
        self.assertNotIn("benchmark", details)
        self.assertEqual(details["provider"]["name"], "qemu")
        self.assertEqual(details["software"]["resource_manager"], "kubernetes")

    def test_contract_hash_changes_on_real_topology_drift(self):
        config = self._parse_config(
            "configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml"
        )
        original = resume_contract.build_persisted_resume_contract(config)["hash"]

        config["normalized"]["infrastructure"]["clusters"][0]["resources"]["vms"]["count"] = 3
        changed = resume_contract.build_persisted_resume_contract(config)["hash"]

        self.assertNotEqual(original, changed)

    def test_provider_base_path_and_delete_intent_are_excluded(self):
        config = self._parse_config(
            "configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml"
        )
        original = resume_contract.build_persisted_resume_contract(config)["hash"]

        provider_config = config["normalized"]["provider"]["config"]
        provider_config["base_path"] = "/tmp/different"
        provider_config["delete_on_exit"] = not provider_config["delete_on_exit"]
        changed = resume_contract.build_persisted_resume_contract(config)["hash"]

        self.assertEqual(original, changed)


if __name__ == "__main__":
    unittest.main()
