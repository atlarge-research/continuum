"""Unit tests for endpoint runtime config wiring helpers."""

import unittest

from resource_manager.endpoint import endpoint


class _FakeMachine:
    def __init__(self):
        self.commands = []
        self.shell_values = []
        self.cloud_controller = 0

    def process(self, _config, commands, ssh=None, shell=False):
        del ssh
        self.shell_values.append(shell)
        if isinstance(commands, list) and commands and isinstance(commands[0], list):
            self.commands.extend(commands)
            return [(["started"], []) for _ in commands]
        self.commands.append(commands)
        return [(["started"], [])]


class EndpointRuntimeTests(unittest.TestCase):
    def _config(self):
        return {
            "mode": "endpoint",
            "endpoint_ssh": ["endpoint0@10.0.0.4"],
            "registry": "127.0.0.1:5000",
            "images": {"combined": "unused:combined-image"},
            "infrastructure": {
                "cloud_nodes": 1,
                "edge_nodes": 0,
                "endpoint_nodes": 1,
                "endpoint_cores": 8,
                "endpoint_memory": 16,
            },
            "domains": {
                "benchmark": {
                    "pipeline": [
                        {
                            "id": "stage-1",
                            "type": "image_classification",
                            "assign_to": {"match": {"cluster": "endpoint-1"}},
                            "config": {
                                "frequency": 2,
                                "duration": 120,
                                "application_endpoint_cpu": 0.5,
                                "application_endpoint_memory": 1.5,
                            },
                        }
                    ]
                },
                "software": {
                    "modules": [
                        {
                            "id": "orchestrator",
                            "type": "kubernetes",
                            "assign_to": {"match": {"cluster": "cloud-1"}},
                            "config": {},
                        }
                    ]
                },
            },
        }

    def test_benchmark_env_is_pipeline_driven(self):
        cfg = self._config()
        self.assertEqual(endpoint._benchmark_env(cfg), ["FREQUENCY=2", "DURATION=120"])

    def test_benchmark_env_missing_pipeline_fails_fast(self):
        cfg = {
            "domains": {
                "benchmark": {"pipeline": []},
            }
        }
        with self.assertRaises(ValueError):
            endpoint._benchmark_env(cfg)

    def test_start_endpoint_default_uses_benchmark_endpoint_resources(self):
        cfg = self._config()
        machine = _FakeMachine()
        endpoint.start_endpoint_default(cfg, [machine])
        self.assertTrue(machine.commands)
        self.assertEqual(machine.commands[0], ["docker", "container", "rm", "--force", "endpoint0"])
        run_cmd = machine.commands[1]
        self.assertIn("--cpus=0.5", run_cmd)
        self.assertIn("--memory=1.5g", run_cmd)
        self.assertIn("--env", run_cmd)
        self.assertIn("CPU_THREADS=1", run_cmd)
        self.assertNotIn("--env CPU_THREADS=1", run_cmd)
        self.assertIn("127.0.0.1:5000/combined-image", run_cmd)
        self.assertFalse(machine.shell_values[-1])

    def test_start_endpoint_default_uses_verified_pinned_publisher_image(self):
        cfg = self._config()
        local_name = "text_translation_publisher_en-nl-8aad73b-r1"
        immutable_ref = "127.0.0.1:5000/%s@sha256:%s" % (local_name, "a" * 64)
        cfg["images"]["combined"] = "continuum:%s" % (local_name,)
        cfg["verified_runtime_image_refs"] = {local_name: immutable_ref}
        machine = _FakeMachine()

        endpoint.start_endpoint_default(cfg, [machine])

        self.assertIn(immutable_ref, machine.commands[1])

    def test_start_endpoint_baremetal_uses_verified_pinned_publisher_image(self):
        cfg = self._config()
        local_name = "text_translation_publisher_en-nl-8aad73b-r1"
        immutable_ref = "127.0.0.1:5000/%s@sha256:%s" % (local_name, "a" * 64)
        cfg["images"] = {"endpoint": "continuum:%s" % (local_name,)}
        cfg["verified_runtime_image_refs"] = {local_name: immutable_ref}
        machine = _FakeMachine()

        endpoint.start_endpoint_baremetal(cfg, [machine])

        self.assertIn(immutable_ref, machine.commands[1])

    def test_openfaas_endpoint_start_uses_shell_safe_ssh_command(self):
        cfg = self._config()
        cfg["mode"] = "cloud"
        cfg["cloud_ips_internal"] = ["10.0.0.10"]
        cfg["edge_ips_internal"] = []
        cfg["control_ips"] = ["10.0.0.9"]
        cfg["images"] = {"endpoint": "unused:image_classification_publisher_serverless"}
        cfg["domains"]["software"]["modules"].append(
            {
                "id": "openfaas",
                "type": "openfaas",
                "assign_to": {"match": {"cluster": "cloud-1"}},
                "config": {},
            }
        )

        machine = _FakeMachine()
        endpoint.start_endpoint_default(cfg, [machine])

        self.assertTrue(machine.shell_values[-1])
        run_cmd = machine.commands[1]
        self.assertIn("sh", run_cmd)
        self.assertIn(endpoint._SERVERLESS_PUBLISHER_RESPONSE_PATCH, run_cmd)


if __name__ == "__main__":
    unittest.main()
