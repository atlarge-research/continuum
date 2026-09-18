"""Static traffic-control command contracts; no host networking is changed."""
import unittest
import shlex
import subprocess

from infrastructure.network import (
    generate_tc_commands,
    generate_mahimati_command,
    mahimahi_values,
    start,
    tc_values,
)


def config(preset="4g", provider="qemu", **overrides):
    values = {
        f"{link}_{field}": -1
        for link in ("cloud", "edge", "cloud_edge", "cloud_endpoint", "edge_endpoint")
        for field in ("latency_avg", "latency_var", "throughput")
    }
    values.update(
        provider=provider,
        wireless_network_preset=preset,
        cloud_location="eu_central_1",
        edge_location="aws_vodafone_edge",
    )
    values.update(overrides)
    return {"infrastructure": values}


class StaticNetworkTests(unittest.TestCase):
    def test_static_classes_precede_references_and_preserve_rates_and_delays(self):
        for preset, rate in (("4g", 7.21), ("5g", 29.66)):
            for provider, interface in (("qemu", "ens2"), ("gcp", "ens4")):
                with self.subTest(preset=preset, provider=provider):
                    cfg = config(preset, provider)
                    profiles = tc_values(cfg)
                    self.assertEqual([p[2] for p in profiles], [1000, 1000, 1000, rate, rate])
                    commands = []
                    for disk, profile in enumerate(profiles, 1):
                        commands.extend(
                            generate_tc_commands(cfg, profile, ["10.0.0.2", "10.0.0.3"], disk)
                        )
                    self.assertEqual(
                        commands[0],
                        [
                            "sudo",
                            "tc",
                            "qdisc",
                            "add",
                            "dev",
                            interface,
                            "root",
                            "handle",
                            "1:",
                            "htb",
                        ],
                    )
                    self.assertEqual(sum("root" in c for c in commands), 1)
                    for disk, profile in enumerate(profiles, 1):
                        classid = f"1:{disk}"
                        expected = [
                            "sudo",
                            "tc",
                            "class",
                            "add",
                            "dev",
                            interface,
                            "parent",
                            "1:",
                            "classid",
                            classid,
                            "htb",
                            "rate",
                            f"{profile[2]}mbit",
                        ]
                        created = commands.index(expected)
                        filters = [
                            c
                            for c in commands
                            if "flowid" in c and c[c.index("flowid") + 1] == classid
                        ]
                        self.assertEqual(len(filters), 2)
                        for command in filters:
                            self.assertGreater(commands.index(command), created)
                        children = [
                            c
                            for c in commands
                            if "netem" in c and c[c.index("parent") + 1] == classid
                        ]
                        self.assertEqual(len(children), int(profile[0] > 0))
                        for command in children:
                            self.assertGreater(commands.index(command), created)
                            self.assertEqual(
                                command[-4:],
                                [
                                    f"{profile[0]}ms",
                                    f"{profile[1]}ms",
                                    "distribution",
                                    "normal",
                                ],
                            )

    def test_manual_overrides_reach_static_classes_and_netem(self):
        for preset in ("4g", "5g"):
            cfg = config(
                preset,
                cloud_endpoint_throughput=12.34,
                edge_endpoint_throughput=56.78,
                cloud_endpoint_latency_avg=9,
                cloud_endpoint_latency_var=2,
            )
            profiles = tc_values(cfg)
            self.assertEqual(profiles[3], [9, 2, 12.34])
            self.assertEqual(profiles[4][2], 56.78)
            for profile in profiles[3:]:
                commands = generate_tc_commands(cfg, profile, ["10.0.0.2"], 1)
                self.assertEqual(commands[1][-2:], ["rate", f"{profile[2]}mbit"])
                self.assertEqual(commands[-1][-4:-2], [f"{profile[0]}ms", f"{profile[1]}ms"])

    def test_replay_keeps_static_core_classes_and_delays(self):
        cfg = config("5g_nl_kpn_mahimahi")
        commands = generate_tc_commands(cfg, [3.125, 0.01, 10000], ["10.0.0.2"], 1)
        self.assertTrue(any("class" in c and "10000mbit" in c for c in commands))
        self.assertTrue(any("netem" in c for c in commands))

    def test_all_trace_pairs_have_core_defaults_without_locations(self):
        for preset, filename in (
            ("4g_us_verizon_mahimahi", "Verizon-LTE-driving"),
            ("evdo_us_verizon_mahimahi", "Verizon-EVDO-driving"),
            ("5g_nl_kpn_mahimahi", "KPN_5G"),
            ("lte_nl_kpn_mahimahi", "KPN_4G"),
            ("5g_obstacled_nl_kpn_mahimahi", "KPN_5G_low_band"),
        ):
            with self.subTest(preset=preset):
                cfg = config(preset, cloud_location="", edge_location="")
                self.assertEqual(tc_values(cfg)[3:], ([0, 0, 1000], [0, 0, 1000]))
                self.assertEqual(
                    mahimahi_values(cfg),
                    [
                        f"/home/mahimahi/traces/{filename}.up",
                        f"/home/mahimahi/traces/{filename}.down",
                    ],
                )

    def test_replay_core_manual_overrides_do_not_change_trace_selection(self):
        cfg = config(
            "5g_nl_kpn_mahimahi",
            cloud_endpoint_throughput=42,
            cloud_endpoint_latency_avg=5,
            cloud_endpoint_latency_var=0,
        )
        self.assertEqual(tc_values(cfg)[3], [5, 0, 42])
        self.assertTrue(mahimahi_values(cfg)[0].endswith("KPN_5G.up"))

    def test_fixed_delay_does_not_request_a_zero_width_distribution(self):
        commands = generate_tc_commands(config(), [5, 0, 1000], ["192.168.210.3"], 1)
        self.assertEqual(commands[-1][-3:], ["netem", "delay", "5ms"])

    def test_replay_start_uses_checked_launcher_with_every_target(self):
        targets = ["192.168.210.2", "192.168.210.3", "192.168.210.4"]
        commands = generate_mahimati_command("192.168.210.6", targets, "/a.up", "/a.down")
        self.assertEqual(
            commands,
            [
                [
                    "sudo",
                    "-n",
                    "/usr/bin/python3",
                    "/home/mahimahi/continuum_replay.py",
                    "start",
                    "192.168.210.6",
                    "/a.up",
                    "/a.down",
                    *targets,
                ]
            ],
        )
        self.assertEqual(generate_mahimati_command("192.168.210.6", targets, None, None), [])

    def test_topologies_apply_core_rules_everywhere_and_replay_only_at_endpoint(self):
        for clouds, edges in (
            (["192.168.210.3", "192.168.210.4", "192.168.210.5"], []),
            ([], ["192.168.210.3", "192.168.210.4"]),
        ):
            cfg = config("5g_nl_kpn_mahimahi")
            groups = {
                "control": ["192.168.210.2"],
                "cloud": clouds,
                "edge": edges,
                "endpoint": ["192.168.210.6"],
            }
            for tier, ips in groups.items():
                cfg[tier + "_ips_internal"] = ips
                if tier != "control":
                    cfg[tier + "_ssh"] = ["vm@" + ip for ip in ips]
            cfg["cloud_ssh"].insert(0, "vm@192.168.210.2")
            calls = []

            class Machine:
                def process(self, _config, command, **kwargs):
                    calls.extend(zip(kwargs["ssh"], command))
                    return [(["CONTINUUM_NETWORK_READY\n"], []) for _ in command]

            start(cfg, [Machine()])
            for ssh, script in calls:
                self.assertIn(" class add ", script)
                self.assertIn("10000mbit" if ssh == "vm@192.168.210.6" else "1000mbit", script)
                self.assertEqual("continuum_replay.py" in script, ssh == "vm@192.168.210.6")
            endpoint = shlex.split(calls[-1][1])[0]
            for target in groups["control"] + clouds + edges:
                self.assertIn(target, endpoint)

    def test_tc_failure_cannot_be_hidden_by_a_later_successful_command(self):
        cfg = config()
        for tier in ("control", "edge"):
            cfg[tier + "_ips_internal"] = []
        cfg.update(
            cloud_ips_internal=["192.168.210.2"],
            endpoint_ips_internal=["192.168.210.6"],
            cloud_ssh=["vm@192.168.210.2"],
            edge_ssh=[],
            endpoint_ssh=["vm@192.168.210.6"],
        )

        class Machine:
            def process(self, _config, command, **_kwargs):
                results = []
                for script in command:
                    # Execute the actual generated shell flow; tc itself is the
                    # external boundary. A failing class must stop later work.
                    body = shlex.split(script)[0]
                    body = "sudo() { return 1; }; " + body
                    result = subprocess.run(
                        ["bash", "-c", body], capture_output=True, text=True, check=False
                    )
                    results.append((result.stdout.splitlines(), result.stderr.splitlines()))
                return results

        with self.assertRaises(RuntimeError):
            start(cfg, [Machine()])


if __name__ == "__main__":
    unittest.main()
