"""Unit tests for endpoint runtime config wiring helpers."""

import unittest
from unittest import mock

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

    def _completion(self, outputs, names=None, targets=None, duration=30):
        """Poll external status observations with a virtual clock and actual completion code."""
        config = self._config()
        config["infrastructure"]["provider"] = "qemu"
        config["domains"]["benchmark"]["pipeline"][0]["config"]["duration"] = duration
        machine = mock.Mock()
        machine.process.side_effect = outputs
        clock = [0]
        pauses = []

        def sleep(seconds):
            pauses.append(seconds)
            clock[0] += seconds

        with mock.patch.object(endpoint.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(endpoint.time, "sleep", side_effect=sleep):
            endpoint.wait_endpoint_completion(
                config, [machine], ["endpoint@192.0.2.1"] if targets is None else targets,
                ["endpoint0"] if names is None else names,
            )
        return machine, clock[0], pauses

    def test_completion_rejects_similarly_named_unrelated_container(self):
        """endpoint00 cannot satisfy a wait for endpoint0."""
        with self.assertRaises((SystemExit, RuntimeError)):
            self._completion([[(["abc: Exited (0) 5 seconds ago endpoint00"], [])]])

    def test_completion_rejects_mismatched_target_cardinality_before_query(self):
        """Zip truncation must not turn a missing target into successful completion."""
        for names, targets in ((["endpoint0"], []), ([], ["endpoint@192.0.2.1"])):
            with self.subTest(names=names, targets=targets):
                with self.assertRaises(ValueError):
                    self._completion([], names=names, targets=targets)

    def test_completion_empty_selection_succeeds_without_query(self):
        """A legitimately empty selection needs no status commands."""
        machine, elapsed, pauses = self._completion([], names=[], targets=[])
        self.assertEqual(machine.process.call_count, 0)
        self.assertEqual(elapsed, 0)
        self.assertEqual(pauses, [])

    def test_completion_waits_for_exact_container_success(self):
        """The selected publisher can run and later exit zero despite unrelated rows."""
        machine, _elapsed, _pauses = self._completion([
            [(["abc: Up 5 seconds endpoint0", "def: Exited (0) 2 seconds ago endpoint00"], [])],
            [(["abc: Exited (0) 1 second ago endpoint0"], [])],
        ])
        self.assertEqual(machine.process.call_count, 2)
        self.assertTrue(all(0 < call.kwargs["timeout_seconds"] <= 10
                            for call in machine.process.call_args_list))

    def test_completion_rejects_missing_malformed_nonzero_and_transport_errors(self):
        """Unrelated output, malformed status and real failures cannot become success."""
        for output, error in ((["abc: Exited (2) 1 second ago endpoint0"], []),
                              (["endpoint0"], []),
                              (["abc: Paused endpoint0"], []),
                              (["abc: Exited (0) endpoint00"], []),
                              ([], ["Permission denied"])):
            with self.subTest(output=output, error=error):
                with self.assertRaises((SystemExit, RuntimeError)):
                    self._completion([[(output, error)]])

    def test_completion_forever_running_uses_one_shared_deadline(self):
        """A second endpoint receives only the budget left by the first endpoint."""
        clock = [0]
        config = self._config()
        config["infrastructure"]["provider"] = "qemu"
        machine = mock.Mock()
        budgets = []

        def query(_config, _command, **options):
            budgets.append(options["timeout_seconds"])
            if len(budgets) == 1:
                clock[0] = 899
                return [(["abc: Exited (0) 1 second ago endpoint0"], [])]
            clock[0] += options["timeout_seconds"]
            return [(["def: Up 1 second endpoint1"], [])]

        machine.process.side_effect = query

        def pause(seconds):
            clock[0] += seconds

        with mock.patch.object(endpoint.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(endpoint.time, "sleep", side_effect=pause):
            with self.assertRaisesRegex(RuntimeError, "endpoint1.*900"):
                endpoint.wait_endpoint_completion(config, [machine], ["one@host", "two@host"],
                                                  ["endpoint0", "endpoint1"])
        self.assertEqual(budgets, [10, 1])

    def test_completion_transient_and_empty_retries_do_not_reset_deadline(self):
        """Retries and intermittent valid status consume, rather than renew, the budget."""
        clock = [0]
        config = self._config()
        config["infrastructure"]["provider"] = "qemu"
        machine = mock.Mock()
        responses = iter([([], ["Connection reset by peer"]), ([], []),
                          (["abc: Up 1 second endpoint0"], [])] * 100)

        def query(*_args, **_kwargs):
            clock[0] += 100
            return [next(responses)]

        machine.process.side_effect = query

        def pause(seconds):
            clock[0] += seconds

        with mock.patch.object(endpoint.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(endpoint.time, "sleep", side_effect=pause):
            with self.assertRaisesRegex(RuntimeError, "endpoint0.*9[0-9][0-9]"):
                endpoint.wait_endpoint_completion(config, [machine], ["one@host"], ["endpoint0"])
        self.assertLess(machine.process.call_count, 10)

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
