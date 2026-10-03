"""Resolve an existing Continuum deployment without provisioning or network discovery."""

import configparser
import hashlib
import math
from pathlib import Path
import shlex

from infrastructure.network import generate_mahimati_command, mahimahi_values


EXPERIMENT_DEFAULTS = {
    "period_seconds": 600,
    "cycles": 4,
    "warmup_cycles": 2,
    "minimum_rate": 0.02,
    "peak_rate": 0.18,
    "cadence_seconds": 90,
    "horizon_seconds": 180,
    "scenarios": 3,
    "scenario_seed": 20260929,
    "decision_age_seconds": 60.0,
    "native_timeout_seconds": 45.0,
    "deadline_seconds": 120.0,
    "deadline_fraction": 0.95,
    "allocation_seconds": 180.0,
    "followup_seconds": 600,
    "reactive_up_threshold": 0.9,
    "reactive_down_threshold": 0.7,
    "residual_margin_seconds": 3.0,
    "acquisition_seconds": 0.0,
}


def read_inventory(path):
    """Read the INI inventory emitted by Continuum's Ansible integration.

    Args:
        path (Path): Generated inventory_vms file.

    Returns:
        tuple[dict, dict]: Global variables and ordered host groups with explicit attributes.

    Raises:
        ValueError: An inventory entry is malformed or duplicates a host within a group.
    """
    groups, variables, section = {}, {}, None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        if section == "all:vars":
            key, separator, value = tokens[0].partition("=")
            if not separator or len(tokens) != 1:
                raise ValueError("malformed inventory variable")
            variables[key] = value
        elif section and ":" not in section:
            hosts = groups.setdefault(section, [])
            if any(host["name"] == tokens[0] for host in hosts):
                raise ValueError("duplicate inventory host")
            attrs = {"name": tokens[0]}
            for token in tokens[1:]:
                key, separator, value = token.partition("=")
                if not separator:
                    raise ValueError("malformed inventory host attribute")
                attrs[key] = value
            hosts.append(attrs)
    return variables, groups


def resolve_deployment(config_path, inventory_path=None):
    """Resolve the supported homogeneous QEMU cloud demo from configuration and inventory.

    Node naming follows Continuum's QEMU cloud-init convention. Live preflight
    verifies these identities before any mutation; no address is inferred from
    the current user's name, home directory or a developer's old experiment.

    Args:
        config_path (str or Path): Continuum .cfg used to provision the existing cluster.
        inventory_path (str or Path or None): Inventory override; otherwise base_path/.continuum.

    Returns:
        dict: JSON-serializable deployment settings and source hashes.

    Raises:
        ValueError: Configuration and inventory disagree or the topology is unsupported.
        OSError: Required configuration or inventory cannot be read.
    """
    config_path = Path(config_path).resolve()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(config_path.read_text(encoding="utf-8"))
    infra = parser["infrastructure"]
    if infra.get("provider") != "qemu":
        raise ValueError("demo resolver currently supports the Continuum QEMU inventory")
    inventory_path = (
        Path(inventory_path)
        if inventory_path
        else Path(infra["base_path"]) / ".continuum/inventory_vms"
    ).resolve()
    variables, groups = read_inventory(inventory_path)
    controllers, workers, endpoints = (
        groups.get(name, []) for name in ("cloudcontroller", "clouds", "endpoints")
    )
    if (
        len(controllers) != 1
        or len(endpoints) != 1
        or not workers
        or len(workers) + 1 != infra.getint("cloud_nodes")
        or infra.getint("endpoint_nodes") != 1
    ):
        raise ValueError("inventory must match one control plane, workers and one endpoint")
    hosts = controllers + workers + endpoints
    if any(not host.get(key) for host in hosts for key in ("ansible_host", "ansible_user")):
        raise ValueError("inventory requires explicit SSH users and addresses")
    names = [host["name"].replace("_", "") for host in hosts]
    addresses = [host["ansible_host"] for host in hosts]
    if len(set(names)) != len(names) or len(set(addresses)) != len(addresses):
        raise ValueError("inventory node names and addresses must be unique")
    key = variables.get("ansible_ssh_private_key_file")
    if not key or not Path(key).is_absolute():
        raise ValueError("inventory must contain an absolute SSH key path")
    cores, memory = infra.getint("cloud_cores"), infra.getfloat("cloud_memory")
    if cores < 2 or not math.isfinite(memory) or memory <= 0:
        raise ValueError("configured worker resources are invalid")
    controller, endpoint = controllers[0], endpoints[0]
    uplink, downlink = mahimahi_values({"infrastructure": dict(infra)})
    replay = []
    if infra.getboolean("network_emulation", fallback=False) and uplink:
        replay = generate_mahimati_command(
            endpoint["ansible_host"], addresses[:-1], uplink, downlink
        )[0]
    return {
        "controller": f'{controller["ansible_user"]}@{controller["ansible_host"]}',
        "endpoint": f'{endpoint["ansible_user"]}@{endpoint["ansible_host"]}',
        "ssh_key": key,
        "control_node": controller["name"].replace("_", ""),
        "workers": [host["name"].replace("_", "") for host in workers],
        "worker_cores": cores,
        "worker_memory_mib": round(memory * 1024),
        "adapter_address": workers[0]["ansible_host"],
        "endpoint_ip": endpoint["ansible_host"],
        "replay_command": replay,
        "network_preset": infra.get("wireless_network_preset", ""),
        "inventory_hosts": hosts,
        "deployment_sources": {
            "config": str(config_path),
            "inventory": str(inventory_path),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        },
    }


def validate_live_inventory(nodes, settings):
    """Verify configured node identities, readiness and addresses before mutation.

    Args:
        nodes (dict): Complete live Kubernetes Node list.
        settings (dict): Resolved deployment settings.

    Raises:
        ValueError: A configured node is missing, unready or belongs to another address pool.
    """
    observed = {node["metadata"]["name"]: node for node in nodes["items"]}
    expected_names = set(settings["workers"] + [settings["control_node"]])
    if not expected_names.issubset(observed):
        raise ValueError("configured nodes are missing from live inventory")
    for host in settings["inventory_hosts"]:
        name = host["name"].replace("_", "")
        if name not in expected_names:
            continue
        node = observed[name]
        addresses = {
            item["address"] for item in node["status"]["addresses"] if item["type"] == "InternalIP"
        }
        if host["ansible_host"] not in addresses:
            raise ValueError("live node address differs from the Continuum inventory")
        if not node["metadata"].get("uid") or not any(
            row["type"] == "Ready" and row["status"] == "True"
            for row in node["status"].get("conditions", [])
        ):
            raise ValueError("configured node is unready or lacks an identity")


def validate_experiment(values):
    """Reject malformed experiment settings before any remote operation.

    Args:
        values (dict): Complete resolved experiment settings.

    Raises:
        ValueError: Timing, rates, policy fractions or cycle geometry are invalid.
    """
    # Exact integers reject bools and fractional counts at the external boundary.
    # pylint: disable=unidiomatic-typecheck,too-many-boolean-expressions
    integers = (
        "period_seconds",
        "cycles",
        "warmup_cycles",
        "cadence_seconds",
        "horizon_seconds",
        "scenarios",
        "followup_seconds",
    )
    if any(type(values[key]) is not int or values[key] < 1 for key in integers):
        raise ValueError("experiment counts and timing must be positive integers")
    for key in EXPERIMENT_DEFAULTS:
        value = values[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"nonfinite or nonnumeric experiment setting: {key}")
    if (
        values["warmup_cycles"] >= values["cycles"]
        or values["period_seconds"] % 5
        or values["horizon_seconds"] % 5
        or not 0 <= values["minimum_rate"] <= values["peak_rate"]
        or values["peak_rate"] <= 0
        or not 0 < values["reactive_down_threshold"] < values["reactive_up_threshold"]
        or not 0 < values["deadline_fraction"] <= 1
        or values["acquisition_seconds"] < 0
        or values["scenario_seed"] < 0
        or type(values["scenario_seed"]) is not int
        or any(
            values[key] <= 0
            for key in (
                "decision_age_seconds",
                "native_timeout_seconds",
                "deadline_seconds",
                "allocation_seconds",
                "residual_margin_seconds",
            )
        )
    ):
        raise ValueError("invalid experiment timing, rates, policy fractions or warmup")
