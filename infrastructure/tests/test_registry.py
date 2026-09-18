"""Regression coverage for Kubernetes image selection in the local registry."""

import unittest
from unittest.mock import Mock

from infrastructure.infrastructure import docker_registry


class RegistryTests(unittest.TestCase):
    """Exercise image-version validation without running Docker or contacting a registry."""

    def test_unsupported_kubernetes_version_fails_explicitly(self):
        """Reject unknown image mappings instead of reading undefined version variables."""
        for resource_manager in ("kubecontrol", "kube_kata"):
            with self.subTest(resource_manager=resource_manager):
                config = {
                    "images": {},
                    "registry": "localhost:5000",
                    "benchmark": {
                        "resource_manager": resource_manager,
                        "kube_version": "v1.99.0",
                        "docker_pull": True,
                    },
                }
                machine = Mock()
                machine.process.return_value = [(["registry available"], [])]
                with self.assertLogs(level="ERROR"), self.assertRaisesRegex(
                    ValueError, "Unsupported Kubernetes version: v1.99.0"
                ):
                    docker_registry(config, [machine])


if __name__ == "__main__":
    unittest.main()
