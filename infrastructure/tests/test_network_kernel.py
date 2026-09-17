"""Opt-in Linux tests: run only inside a disposable network namespace.

FNS_PARENT_NETNS=$(readlink /proc/self/ns/net) FNS_NETWORK_NAMESPACE=1 unshare --user --map-root-user --net \
    python -m unittest discover -s infrastructure/tests -p test_network_kernel.py -v
"""
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

from infrastructure.network import generate_tc_commands, tc_values
from test_network import config


def run(*command):
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(
    os.environ.get("FNS_NETWORK_NAMESPACE") == "1",
    "requires isolated network namespace",
)
class KernelNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Refuse an ordinary host network namespace, even with the opt-in set.
        if (
            not os.environ.get("FNS_PARENT_NETNS")
            or os.readlink("/proc/self/ns/net") == os.environ["FNS_PARENT_NETNS"]
        ):
            raise RuntimeError("run inside unshare --user --map-root-user --net")

    def setUp(self):
        run("ip", "link", "add", "ens2", "type", "dummy")
        run("ip", "link", "set", "ens2", "up")

    def tearDown(self):
        run("ip", "link", "del", "ens2")

    def test_kernel_accepts_all_profiles_with_classes_filters_and_delays(self):
        for preset in (
            "4g",
            "5g",
            "4g_us_verizon_mahimahi",
            "evdo_us_verizon_mahimahi",
            "5g_nl_kpn_mahimahi",
            "lte_nl_kpn_mahimahi",
            "5g_obstacled_nl_kpn_mahimahi",
        ):
            with self.subTest(preset=preset):
                cfg = config(preset)
                for disk, values in enumerate(tc_values(cfg), 1):
                    for command in generate_tc_commands(
                        cfg, values, [f"192.168.210.{disk}"], disk
                    ):
                        run(*command[1:])  # already root inside this user namespace
                # The VM-era iproute2 emits text for classes, and invalid JSON
                # for u32 filters, even with -j. Inspect their stable handles.
                classes = run("tc", "class", "show", "dev", "ens2")
                self.assertEqual(
                    set(re.findall(r"class htb (1:[1-5]) ", classes)),
                    {"1:1", "1:2", "1:3", "1:4", "1:5"},
                )
                qdiscs = json.loads(run("tc", "-j", "qdisc", "show", "dev", "ens2"))
                self.assertEqual(sum(q["kind"] == "netem" for q in qdiscs), 4)
                filters = run("tc", "filter", "show", "dev", "ens2", "parent", "1:")
                self.assertEqual(
                    set(re.findall(r"flowid (1:[1-5]) ", filters)),
                    {"1:1", "1:2", "1:3", "1:4", "1:5"},
                )
                run("tc", "qdisc", "del", "dev", "ens2", "root")

    def test_real_routing_and_cleanup_preserve_other_nat_rules(self):
        self.check_routing_and_cleanup("192.168.210.6", "192.168.210.3")

    def test_routing_accepts_other_vm_addresses_in_the_qemu_subnet(self):
        self.check_routing_and_cleanup("192.168.104.42", "192.168.105.17")

    def check_routing_and_cleanup(self, endpoint, target):
        # These are isolated fixtures, not addresses of live Continuum VMs.
        spec = importlib.util.spec_from_file_location(
            "replay",
            Path(__file__).resolve().parents[1]
            / "qemu/infrastructure/continuum_replay.py",
        )
        replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay)
        run("ip", "address", "add", endpoint + "/16", "dev", "ens2")
        run("ip", "link", "add", "mm-test", "type", "dummy")
        try:
            run(
                "ip", "address", "add", "10.0.0.1", "peer", "10.0.0.2", "dev", "mm-test"
            )
            run("ip", "link", "set", "mm-test", "up")
            run(
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                "172.17.0.0/16",
                "-j",
                "MASQUERADE",
            )
            before = run("iptables", "-t", "nat", "-S")
            # Docker on a freshly built endpoint uses DROP for forwarding.
            run("iptables", "-P", "FORWARD", "DROP")
            filter_before = run("iptables", "-S")
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "state.json"
                state = {"undo": []}
                replay.apply_routing(
                    replay.routing_commands(endpoint, [target], "mm-test"),
                    state,
                    path,
                )
                rules = run("iptables", "-S", "FORWARD").splitlines()
                self.assertIn("-P FORWARD DROP", rules)
                self.assertEqual(sum("continuum-mahimahi" in rule for rule in rules), 2)
                forward = json.loads(run("ip", "-j", "route", "get", target))[0]
                returned = json.loads(
                    run(
                        "ip",
                        "-j",
                        "route",
                        "get",
                        target,
                        "from",
                        "10.0.0.2",
                        "iif",
                        "mm-test",
                    )
                )[0]
                self.assertEqual(forward["gateway"], "10.0.0.2")
                self.assertEqual(returned["dev"], "ens2")
                self.assertEqual(replay.undo_routing(state, path), [])
                self.assertEqual(run("iptables", "-t", "nat", "-S"), before)
                self.assertEqual(run("iptables", "-S"), filter_before)
                self.assertEqual(replay.undo_routing(state, path), [])
        finally:
            run("ip", "link", "del", "mm-test")
