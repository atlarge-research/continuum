#!/usr/bin/env python3
"""Checked lifecycle for the pinned replay implementation on Continuum QEMU VMs."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import time


BUILD_IDENTITY = json.loads(Path(__file__).with_name("mahimahi-build.json").read_text())
REVISION = BUILD_IDENTITY["mahimahi_revision"]
PATCH_ID = BUILD_IDENTITY["mahimahi_patch_id"]
BUILD = Path("/home/mahimahi")
RUNTIME = Path("/run/continuum-mahimahi")
UNIT = "continuum-mahimahi.service"
# QEMU image and pinned MahiMahi layout contract, checked before routing changes.
# Actual endpoint and cloud/edge addresses are supplied for each experiment.
OUTER = "10.0.0.1"
INNER = "10.0.0.2"
INTERFACE = "ens2"
CORE = ipaddress.IPv4Network("192.168.0.0/16")
TABLE = "200"
PRIORITY = "20000"
COMMENT = "continuum-mahimahi"


def run(command, check=True):
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, command, result.stdout, result.stderr
        )
    return result


def read_json(command):
    return json.loads(run(command).stdout)


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def validate_trace(path):
    digest = hashlib.sha256()
    count, previous = 0, -1
    with Path(path).open("rb") as stream:
        for line in stream:
            digest.update(line)
            text = line.strip()
            if not text.isdigit():
                raise ValueError(
                    f"invalid trace timestamp in {path} at line {count + 1}"
                )
            value = int(text)
            if value < previous:
                raise ValueError(
                    f"trace timestamps decrease in {path} at line {count + 1}"
                )
            previous, count = value, count + 1
    if not count or previous <= 0:
        raise ValueError(f"empty or zero-duration trace: {path}")
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "packets": count,
        "duration_ms": previous,
    }


def preflight(endpoint, targets):
    if ipaddress.IPv4Address(endpoint) not in CORE:
        raise ValueError(f"expected endpoint on {CORE}: {endpoint}")
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("provide distinct cloud/edge targets")
    for target in targets:
        if ipaddress.IPv4Address(target) not in CORE or target == endpoint:
            raise ValueError(f"target is not another VM on {CORE}: {target}")
    addresses = read_json(["ip", "-j", "-4", "address", "show"])
    expected = any(
        link["ifname"] == INTERFACE
        and address["local"] == endpoint
        and address["prefixlen"] == 16
        for link in addresses
        for address in link.get("addr_info", [])
    )
    if not expected:
        raise RuntimeError(
            f"VM layout differs: expected {endpoint}/16 on {INTERFACE}; no routing changed"
        )
    if any(
        a["local"] in (OUTER, INNER)
        for link in addresses
        for a in link.get("addr_info", [])
    ):
        raise RuntimeError("MahiMahi namespace addresses are already occupied")
    routes = read_json(["ip", "-N", "-j", "-4", "route", "show", "table", "all"])
    for route in routes:
        destination = route.get("dst", "default")
        if str(route.get("table")) == TABLE:
            raise RuntimeError("policy table 200 is already in use")
        if destination != "default":
            network = ipaddress.IPv4Network(destination, strict=False)
            if (
                ipaddress.IPv4Address(OUTER) in network
                or ipaddress.IPv4Address(INNER) in network
            ):
                raise RuntimeError("routes already cover MahiMahi namespace addresses")
            if network.prefixlen == 32 and str(network.network_address) in targets:
                raise RuntimeError(f"target already has a host route: {destination}")
    rules = read_json(["ip", "-N", "-j", "-4", "rule", "show"])
    if any(
        str(r.get("table")) == TABLE or str(r.get("priority")) == PRIORITY
        for r in rules
    ):
        raise RuntimeError("replay policy table or rule priority is already in use")
    if run(["sysctl", "-n", "net.ipv4.ip_forward"]).stdout.strip() != "1":
        raise RuntimeError("IPv4 forwarding is disabled")
    reverse_filters = [
        int(run(["sysctl", "-n", f"net.ipv4.conf.{name}.rp_filter"]).stdout)
        for name in ("all", INTERFACE)
    ]
    if max(reverse_filters) == 1:
        raise RuntimeError(
            "strict reverse-path filtering conflicts with replay host routes"
        )
    for table in ("nat", "filter"):
        if COMMENT in run(["iptables", "-t", table, "-S"]).stdout:
            raise RuntimeError(
                "orphaned Continuum replay rules; inspect before restarting"
            )


def routing_commands(endpoint, targets, tun):
    """Pairs of additions and exact inverses; never flush another owner's state."""
    pairs = [
        (
            ["ip", "route", "add", str(CORE), "dev", INTERFACE, "table", TABLE],
            ["ip", "route", "del", str(CORE), "dev", INTERFACE, "table", TABLE],
        ),
        (
            [
                "ip",
                "rule",
                "add",
                "priority",
                PRIORITY,
                "from",
                INNER + "/32",
                "table",
                TABLE,
            ],
            [
                "ip",
                "rule",
                "del",
                "priority",
                PRIORITY,
                "from",
                INNER + "/32",
                "table",
                TABLE,
            ],
        ),
    ]
    for target in targets:
        # Fresh Docker installations set FORWARD to DROP. Permit only this
        # experiment's namespace traffic, without changing Docker's policy.
        for incoming, outgoing, source, destination in (
            (INTERFACE, tun, target, INNER),
            (tun, INTERFACE, INNER, target),
        ):
            rule = [
                "FORWARD",
                "-i",
                incoming,
                "-o",
                outgoing,
                "-s",
                source,
                "-d",
                destination,
                "-m",
                "comment",
                "--comment",
                COMMENT,
                "-j",
                "ACCEPT",
            ]
            pairs.append(
                (
                    ["iptables", "-w", "-I"] + rule,
                    ["iptables", "-w", "-D"] + rule,
                )
            )
        for chain, match, action in (
            (
                "PREROUTING",
                ["-i", INTERFACE, "-s", target, "-d", endpoint],
                ["DNAT", "--to-destination", INNER],
            ),
            # Endpoint-originated traffic crosses the downlink TUN once on its
            # way into the namespace. Source .1 bypasses that extra crossing.
            ("POSTROUTING", ["-s", endpoint, "-d", target, "-o", tun], ["MASQUERADE"]),
            # On physical egress, restore the endpoint's externally visible IP.
            (
                "POSTROUTING",
                ["-s", INNER, "-d", target, "-o", INTERFACE],
                ["MASQUERADE"],
            ),
        ):
            rule = (
                [chain] + match + ["-m", "comment", "--comment", COMMENT, "-j"] + action
            )
            pairs.append(
                (
                    ["iptables", "-w", "-t", "nat", "-A"] + rule,
                    ["iptables", "-w", "-t", "nat", "-D"] + rule,
                )
            )
    for target in targets:
        pairs.append(
            (
                ["ip", "route", "add", target + "/32", "via", INNER],
                ["ip", "route", "del", target + "/32", "via", INNER],
            )
        )
    return pairs


def undo_routing(state, path):
    failed = []
    for command in reversed(state["undo"]):
        result = run(command, check=False)
        absent = any(
            message in result.stderr
            for message in (
                "No such process",
                "No such file or directory",
                "Bad rule (does a matching rule exist",
            )
        )
        if result.returncode and not absent:
            failed.insert(0, command)
    state["undo"] = failed
    save_state(path, state)
    return failed


def apply_routing(pairs, state, path):
    try:
        for command, undo in pairs:
            # Record before the mutation so an interrupted start can be cleaned.
            state["undo"].append(undo)
            save_state(path, state)
            try:
                run(command)
            except subprocess.CalledProcessError:
                # A failed add did not acquire ownership of an existing rule.
                state["undo"].pop()
                save_state(path, state)
                raise
    except Exception:
        undo_routing(state, path)
        raise


def wait_ready(directory, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run(["systemctl", "is-active", "--quiet", UNIT], check=False).returncode:
            raise RuntimeError(
                "MahiMahi exited before readiness; inspect journalctl -u " + UNIT
            )
        if (directory / "namespace-ready").exists():
            return
        time.sleep(0.1)
    raise RuntimeError("MahiMahi namespace readiness timed out")


def check(state):
    if run(["systemctl", "is-active", "--quiet", UNIT], check=False).returncode:
        raise RuntimeError("MahiMahi service is not active")
    if not (RUNTIME / "namespace-ready").exists():
        raise RuntimeError("MahiMahi namespace is not ready")
    for command in state["undo"]:
        if command[0] == "iptables":
            run(["-C" if item == "-D" else item for item in command])
    for target in state["targets"]:
        outward = read_json(["ip", "-j", "route", "get", target])[0]
        returned = read_json(
            ["ip", "-j", "route", "get", target, "from", INNER, "iif", state["tun"]]
        )[0]
        if outward.get("gateway") != INNER or returned.get("dev") != INTERFACE:
            raise RuntimeError(f"replay policy routing mismatch for {target}")


def namespace_setup():
    addresses = read_json(["ip", "-j", "-4", "address", "show", "dev", "ingress"])
    if not any(
        a["local"] == INNER for link in addresses for a in link.get("addr_info", [])
    ):
        raise RuntimeError("unexpected MahiMahi inner address; expected 10.0.0.2")
    run(
        [
            "iptables",
            "-w",
            "-t",
            "nat",
            "-A",
            "PREROUTING",
            "-d",
            INNER,
            "-j",
            "DNAT",
            "--to-destination",
            OUTER,
        ]
    )
    run(
        [
            "iptables",
            "-w",
            "-t",
            "nat",
            "-A",
            "POSTROUTING",
            "-o",
            "ingress",
            "-j",
            "MASQUERADE",
        ]
    )
    (RUNTIME / "namespace-ready").write_text("ready\n")
    while True:
        signal.pause()


def stop_service():
    result = run(["systemctl", "stop", UNIT], check=False)
    if result.returncode:
        loaded = run(
            ["systemctl", "show", "--property=LoadState", "--value", UNIT], check=False
        )
        if loaded.stdout.strip() != "not-found":
            raise RuntimeError("could not stop replay service: " + result.stderr)


def stop(state, path):
    if undo_routing(state, path):
        raise RuntimeError(
            "some replay rules could not be removed; retained state.json for inspection"
        )
    stop_service()
    path.unlink()
    (RUNTIME / "namespace-ready").unlink(missing_ok=True)


def start(endpoint, targets, uplink, downlink, path):
    if (
        path.exists()
        or run(["systemctl", "is-active", "--quiet", UNIT], check=False).returncode == 0
    ):
        raise RuntimeError(
            "replay already started or needs cleanup; use the stop subcommand first"
        )
    preflight(endpoint, targets)
    if (
        BUILD / (".installed-" + REVISION + "-" + PATCH_ID)
    ).read_text().strip() != REVISION:
        raise RuntimeError("pinned MahiMahi installation marker is missing or differs")
    user = pwd.getpwuid(int(os.environ["SUDO_UID"]))
    if user.pw_uid == 0:
        raise RuntimeError("invoke start through sudo from the endpoint VM user")
    traces = [validate_trace(Path(p).resolve(strict=True)) for p in (uplink, downlink)]
    logs = RUNTIME / ("logs-" + str(time.time_ns()))
    logs.mkdir(mode=0o755)
    os.chown(logs, user.pw_uid, user.pw_gid)
    (RUNTIME / "namespace-ready").unlink(missing_ok=True)
    state = {
        "revision": REVISION,
        "patch": PATCH_ID,
        "endpoint": endpoint,
        "targets": targets,
        "traces": traces,
        "logs": str(logs),
        "undo": [],
    }
    save_state(path, state)
    try:
        run(
            [
                "systemd-run",
                "--quiet",
                "--collect",
                "--unit=" + UNIT,
                "--uid=" + user.pw_name,
                "--gid=" + str(user.pw_gid),
                "--property=Type=exec",
                "--property=KillMode=mixed",
                "--property=TimeoutStopSec=10",
                "/usr/bin/env",
                "SRC_TO_IGNORE=" + OUTER,
                "DEST_TO_IGNORE=" + OUTER,
                "/usr/local/bin/mm-link",
                "--uplink-log=" + str(logs / "uplink.log"),
                "--downlink-log=" + str(logs / "downlink.log"),
                traces[0]["path"],
                traces[1]["path"],
                "--",
                "sudo",
                "-n",
                "/usr/bin/python3",
                str(BUILD / "continuum_replay.py"),
                "namespace",
            ]
        )
        wait_ready(RUNTIME)
        link = read_json(["ip", "-j", "route", "get", INNER])[0]
        state["tun"] = link["dev"]
        if link.get("prefsrc") != OUTER:
            raise RuntimeError("unexpected MahiMahi outer address; expected 10.0.0.1")
        apply_routing(routing_commands(endpoint, targets, state["tun"]), state, path)
        check(state)
        state["status"] = "ready"
        save_state(path, state)
    except Exception:
        # Retain state if cleanup needs inspection, and never claim readiness.
        if not undo_routing(state, path):
            stop_service()
            path.unlink(missing_ok=True)
            (RUNTIME / "namespace-ready").unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    launch = sub.add_parser("start")
    launch.add_argument("endpoint")
    launch.add_argument("uplink")
    launch.add_argument("downlink")
    launch.add_argument("targets", nargs="+")
    for name in ("stop", "check", "namespace"):
        sub.add_parser(name)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run through sudo on the endpoint VM")
    if args.action == "namespace":
        namespace_setup()
        return
    RUNTIME.mkdir(mode=0o755, exist_ok=True)
    path = RUNTIME / "state.json"
    with (RUNTIME / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "start":
            start(args.endpoint, args.targets, args.uplink, args.downlink, path)
        elif args.action == "stop":
            stop(json.loads(path.read_text()), path)
        else:
            check(json.loads(path.read_text()))
    print("CONTINUUM_REPLAY_" + args.action.upper() + "_OK")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Replay failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr, file=sys.stderr)
        sys.exit(1)
