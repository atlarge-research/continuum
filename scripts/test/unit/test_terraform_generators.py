"""Unit tests for Terraform string encoding and cloud generators."""

import copy
import tempfile
import unittest
from pathlib import Path

from infrastructure import terraform_utils
from infrastructure.aws import generate as aws_generate
from infrastructure.gcp import generate as gcp_generate


_HOSTILE_SUFFIX = (
    ' value with spaces "quoted" \\path\nline\rreturn\ttab'
    '\x01\x7f\x85 ${var.bad} %{ if true }'
)


def _semantic_value(label):
    return label + _HOSTILE_SUFFIX


def _encoded_value(label):
    return (
        '"'
        + label
        + ' value with spaces \\"quoted\\" \\\\path\\nline\\rreturn\\ttab'
        + '\\u0001\\u007f\\u0085 $${var.bad} %%{ if true }"'
    )


def _read_generated(root, name):
    return (root / name).read_text(encoding="utf-8")


class TerraformStringLiteralTests(unittest.TestCase):
    def test_encodes_hostile_semantic_string_exactly(self):
        self.assertEqual(
            terraform_utils.hcl_string_literal(_semantic_value("provider")),
            _encoded_value("provider"),
        )
        self.assertEqual(terraform_utils.hcl_string_literal('"legacy"'), '"\\"legacy\\""')
        self.assertEqual(terraform_utils.hcl_string_literal("café 雪"), '"café 雪"')

    def test_rejects_non_string_values(self):
        for value in (None, 1, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    TypeError,
                    "HCL string literal value must be a string",
                ):
                    terraform_utils.hcl_string_literal(value)


class AwsTerraformGeneratorTests(unittest.TestCase):
    def test_encodes_only_semantic_provider_string_slots(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            infrastructure = {
                "cloud_nodes": 2,
                "edge_nodes": 3,
                "endpoint_nodes": 4,
                "aws_region": _semantic_value("region"),
                "aws_access_keys": _semantic_value("access"),
                "aws_secret_access_keys": _semantic_value("secret"),
                "aws_zone": _semantic_value("zone"),
                "aws_ami": _semantic_value("ami"),
                "aws_cloud": _semantic_value("cloud-type"),
                "aws_edge": _semantic_value("edge-type"),
                "aws_endpoint": _semantic_value("endpoint-type"),
            }
            config = {
                "tmp_dir": str(root),
                "ssh_key": "/tmp/dummy-key",
                "infrastructure": infrastructure,
            }
            original = copy.deepcopy(config)

            aws_generate.start(config, [])

            self.assertEqual(config, original)
            header = _read_generated(root, "header.tf")
            self.assertIn("  region      = %s\n" % (_encoded_value("region"),), header)
            self.assertIn("  access_key  = %s\n" % (_encoded_value("access"),), header)
            self.assertIn("  secret_key  = %s\n" % (_encoded_value("secret"),), header)

            network = _read_generated(root, "network.tf")
            self.assertEqual(
                network.count("    availability_zone = %s" % (_encoded_value("zone"),)),
                3,
            )

            tiers = (
                ("cloud", 2, "cloud-type"),
                ("edge", 3, "edge-type"),
                ("endpoint", 4, "endpoint-type"),
            )
            for tier, count, instance_type in tiers:
                with self.subTest(tier=tier):
                    generated = _read_generated(root, "%s_vm.tf" % (tier,))
                    self.assertIn(
                        "    instance_type               = %s"
                        % (_encoded_value(instance_type),),
                        generated,
                    )
                    self.assertIn(
                        "    ami                         = %s" % (_encoded_value("ami"),),
                        generated,
                    )
                    self.assertIn("    count                       = %s" % (count,), generated)
                    self.assertIn(
                        "    key_name                    = aws_key_pair.public_ssh_key.key_name",
                        generated,
                    )
                    self.assertIn('        Name = "%s_${count.index}"' % (tier,), generated)
                    self.assertIn('        private_key = "${file("/tmp/dummy-key")}"', generated)


class GcpTerraformGeneratorTests(unittest.TestCase):
    def test_encodes_only_semantic_provider_string_slots(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            infrastructure = {
                "cloud_nodes": 2,
                "edge_nodes": 3,
                "endpoint_nodes": 4,
                "gcp_credentials": _semantic_value("credentials"),
                "gcp_project": _semantic_value("project"),
                "gcp_region": _semantic_value("region"),
                "gcp_zone": _semantic_value("zone"),
                "gcp_cloud": _semantic_value("cloud-type"),
                "gcp_edge": _semantic_value("edge-type"),
                "gcp_endpoint": _semantic_value("endpoint-type"),
            }
            config = {
                "tmp_dir": str(root),
                "ssh_key": "/tmp/dummy-key",
                "infrastructure": infrastructure,
            }
            original = copy.deepcopy(config)

            gcp_generate.start(config, [])

            self.assertEqual(config, original)
            header = _read_generated(root, "header.tf")
            self.assertIn(
                "  credentials = file(%s)\n" % (_encoded_value("credentials"),),
                header,
            )
            self.assertIn("  project     = %s\n" % (_encoded_value("project"),), header)
            self.assertIn("  region      = %s\n" % (_encoded_value("region"),), header)
            self.assertIn("  zone        = %s\n" % (_encoded_value("zone"),), header)

            tiers = (
                ("cloud", 2, "cloud-type"),
                ("edge", 3, "edge-type"),
                ("endpoint", 4, "endpoint-type"),
            )
            for tier, count, machine_type in tiers:
                with self.subTest(tier=tier):
                    generated = _read_generated(root, "%s_vm.tf" % (tier,))
                    self.assertIn(
                        "    machine_type = %s" % (_encoded_value(machine_type),),
                        generated,
                    )
                    self.assertIn("    count        = %s" % (count,), generated)
                    self.assertIn(
                        "        network    = google_compute_network.vpc_network.name",
                        generated,
                    )
                    self.assertIn('    name         = "%s${count.index}"' % (tier,), generated)
                    self.assertIn(
                        '        ssh-keys = "%s${count.index}:${file("/tmp/dummy-key.pub")}"'
                        % (tier,),
                        generated,
                    )


if __name__ == "__main__":
    unittest.main()
