"""Unit tests for QEMU configuration generation."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from infrastructure.qemu import generate


class QemuGeneratorTests(unittest.TestCase):
    def test_memory_gib_to_kib_rounds_up_only_when_needed(self):
        cases = (
            (0.5, 524288),
            (1.5, 1572864),
            (2.0, 2097152),
            (0.1, 104858),
            (1 / 1048576, 1),
            (104857 / 1048576, 104857),
        )

        for memory_gib, expected_kib in cases:
            with self.subTest(memory_gib=memory_gib):
                self.assertEqual(generate._memory_gib_to_kib(memory_gib), expected_kib)

    def test_generated_domain_xml_uses_integer_kib_memory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            ssh_key = root / "id_rsa"
            ssh_key.with_suffix(".pub").write_text("ssh-rsa test-key\n", encoding="utf-8")
            config = {
                "tmp_dir": str(root),
                "ssh_key": str(ssh_key),
                "domains": {
                    "software": {
                        "modules": [
                            {"id": "none-main", "type": "none", "config": {}}
                        ]
                    }
                },
                "infrastructure": {
                    "base_path": str(root),
                    "cloud_cores": 1,
                    "edge_cores": 1,
                    "endpoint_cores": 1,
                    "cloud_memory": 0.1,
                    "edge_memory": 0.2,
                    "endpoint_memory": 0.3,
                    "cloud_quota": 1.0,
                    "edge_quota": 1.0,
                    "endpoint_quota": 1.0,
                    "cloud_read_speed": 0,
                    "cloud_write_speed": 0,
                    "edge_read_speed": 0,
                    "edge_write_speed": 0,
                    "endpoint_read_speed": 0,
                    "endpoint_write_speed": 0,
                    "cpu_pin": False,
                },
            }
            machine = SimpleNamespace(
                process=mock.Mock(return_value=[(["1\n"], [])]),
                cloud_controller_ips=["192.168.1.2"],
                cloud_ips=[],
                cloud_controller_names=["cloud0"],
                cloud_names=[],
                edge_ips=["192.168.1.3"],
                edge_names=["edge0"],
                endpoint_ips=["192.168.1.4"],
                endpoint_names=["endpoint0"],
                base_ips=[],
                base_names=[],
            )

            with mock.patch.object(
                generate,
                "_bridge_runtime_overrides",
                return_value=("virbr0", "192.168.1.1"),
            ):
                generate.start(config, [machine])

            expected = {
                "cloud0": 104858,
                "edge0": 209716,
                "endpoint0": 314573,
            }
            for name, memory_kib in expected.items():
                with self.subTest(name=name):
                    xml = (root / ("domain_%s.xml" % name)).read_text(encoding="utf-8")
                    self.assertIn("<memory>%s</memory>" % memory_kib, xml)


if __name__ == "__main__":
    unittest.main()
