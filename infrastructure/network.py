"""\
Use TC to control latency / throughput between VMs, and perform network benchmarks with netperf.
"""

import json
import logging
import os
import sys
import time


def _is_transient_tc_error(lines):
    """Return true when TC error looks transient (e.g., temporary SSH issues).

    Args:
        lines (list(str)): List of lines to check for transient errors

    Returns:
        bool: True if the error looks transient, False otherwise
    """
    if not lines:
        return False
    combined = " ".join(lines).lower()
    patterns = [
        "timeout, server",
        "not responding",
        "connection timed out",
        "connection reset by peer",
        "broken pipe",
    ]
    return any(pattern in combined for pattern in patterns)


def next_configured_ip(config, middle_ip, postfix_ip):
    """Advance to the next IP address within the configured postfix window. The window is set to
    2-252. In practice, this means you would have to use >250 VMs to reach the upper bound. We
    still keep this function for satefy.

    Args:
        config (dict): Parsed configuration with postfix bounds.
        middle_ip (int): Middle octet value.
        postfix_ip (int): Last octet value.

    Returns:
        tuple[int, int]: Updated middle and postfix octets.
    """
    postfix_ip += 1
    if postfix_ip == config["postfixIP_upper"]:
        middle_ip += 1
        postfix_ip = config["postfixIP_lower"]

    return middle_ip, postfix_ip


def generate_tc_commands(config, values, ips, disk):
    """Generate TC commands

    Args:
        config (dict): Parsed configuration
        values (list(float)): Avg latency, Var latency, throughput
        ips (list(str)): List of ips to filter TC for
        disk (int): Qdisc to attach to

    Returns:
        list(str): List of TC commands
    """
    latency_avg = values[0]
    latency_var = values[1]
    throughput = values[2]

    network = "ens2"
    if config["infrastructure"]["provider"] == "gcp":
        network = "ens4"

    commands = []

    if disk == 1:
        # Root disk
        commands.append(
            ["sudo", "tc", "qdisc", "add", "dev", network, "root", "handle", "1:", "htb"]
        )

    # Define a class for this disk so flowid 1:disk actually exists.
    # The throughput component of the profile (or manual override) is used as the rate.
    commands.append(
        [
            "sudo",
            "tc",
            "class",
            "add",
            "dev",
            network,
            "parent",
            "1:",
            "classid",
            "1:%i" % (disk),
            "htb",
            "rate",
            "%smbit" % (throughput),
        ]
    )

    # Filter for specific IPs
    for ip in ips:
        commands.append(
            [
                "sudo",
                "tc",
                "filter",
                "add",
                "dev",
                network,
                "parent",
                "1:",
                "protocol",
                "ip",
                "prio",
                str(disk),
                "u32",
                "flowid",
                "1:%i" % (disk),
                "match",
                "ip",
                "dst",
                ip,
            ]
        )

    # Set latency
    if float(latency_avg) > 0.0:
        commands.append(
            [
                "sudo",
                "tc",
                "qdisc",
                "add",
                "dev",
                network,
                "parent",
                "1:%i" % (disk),
                "handle",
                "%i0:" % (disk),
                "netem",
                "delay",
                "%sms" % (latency_avg),
                "%sms" % (latency_var),
                "distribution",
                "normal",
            ]
        )

    return commands


def generate_mahimati_command(endpoint_ip, targets, uplink, downlink):
    """Generate Mahimati command
    Executing this command puts application into containerized Mahimati shell.
    Every command executed with the shell will have throughput and latecies
    corresponding to the provided trace and progation delay

    Args:
        config (dict): Parsed configuration
        propagation_delay (int): Propagation delay on the link measured in ms
        trace (str): Saturate-formatted trace file

    Returns:
        str: mahimati command
    """
    # the path for verizon let's say is /home/mahimahi/traces/Verizon-LTE-driving.up
    if not uplink or not downlink:
        return [[]]

    commands = []
    target_args = " ".join(targets)

    commands.append(["export", "SRC_TO_IGNORE=10.0.0.1"])

    commands.append(["export", "DEST_TO_IGNORE=10.0.0.1"])

    commands.append(
        [
            "(",
            "mm-link",
            f"--uplink-log=uplink.log",
            f"--downlink-log=downlink.log",
            uplink,
            downlink,
            "sudo",
            f"/home/mahimahi/setup_container.sh {endpoint_ip} {target_args}",
            ">output_mahi.txt",
            "2>&1",
            "&",
            ")",
        ]
    )

    commands.append(["sleep", "10"])

    commands.append(
        [
            "(",
            "sudo",
            f"/home/mahimahi/setup_traffic.sh {endpoint_ip} {target_args}",
            ">output_reroute.txt",
            "2>&1",
            "&",
            ")",
        ]
    )

    return commands


def mahimahi_values(config):
    """
        Set values used for for MahiMahi
        In case non-mahimahi preset is used, function returns None

    Args:
        config (dict): Parsed configuration

    Returns:
        2x list(str): Path to the MahiMahi traces
    """
    if config["infrastructure"]["wireless_network_preset"] == "4g_us_verizon_mahimahi":
        return [
            "/home/mahimahi/traces/Verizon-LTE-driving.up",
            "/home/mahimahi/traces/Verizon-LTE-driving.down",
        ]

    elif config["infrastructure"]["wireless_network_preset"] == "5g_nl_kpn_mahimahi":
        return [
            "/home/mahimahi/traces/KPN_5G.up",
            "/home/mahimahi/traces/KPN_5G.down",
        ]

    elif config["infrastructure"]["wireless_network_preset"] == "lte_nl_kpn_mahimahi":
        return [
            "/home/mahimahi/traces/KPN_4G.up",
            "/home/mahimahi/traces/KPN_4G.down",
        ]

    elif config["infrastructure"]["wireless_network_preset"] == "5g_obstacled_nl_kpn_mahimahi":
        return [
            "/home/mahimahi/traces/KPN_5G_low_band.up",
            "/home/mahimahi/traces/KPN_5G_low_band.down",
        ]

    elif config["infrastructure"]["wireless_network_preset"] == "evdo_us_verizon_mahimahi":
        return [
            "/home/mahimahi/traces/Verizon-EVDO-driving.up",
            "/home/mahimahi/traces/Verizon-EVDO-driving.down",
        ]

    return [None, None]


def tc_values(config):
    """Set latency/throughput values to be used for tc

    The MahiMahi keys have the following format: standard_location_provider

    Args:
        config (dict): Parsed configuration

    Returns:
        5x list(int, int, int): TC network values to be used
    """
    infrastructure = config.get("infrastructure", {})
    wireless_preset = infrastructure.get("wireless_network_preset", "")
    edge_location = infrastructure.get("edge_location", "")
    cloud_location = infrastructure.get("cloud_location", "")

    # Default values
    cloud = [0, 0, 1000]  # Between cloud nodes (wired)
    edge = [7.5, 2.5, 1000]  # Between edge nodes (wired)
    cloud_edge = [7.5, 2.5, 1000]  # Between cloud and edge (wired)
    cloud_endpoint = [0, 0, 1000]  # Between cloud and endpoint (default wired)
    edge_endpoint = [0, 0, 1000]  # Between edge and endpoint (default wired)

    if (
        wireless_preset == "4g_us_verizon_mahimahi"
        or wireless_preset == "evdo_us_verizon_mahimahi"
        or wireless_preset == "5g_nl_kpn_mahimahi"
    ):
        cloud_endpoint = [0, 0, 1000]
        edge_endpoint = [0, 0, 1000]

    if edge_location == "aws_vodafone_edge":
        edge_endpoint = [0.07, 0.01, 10000]
    elif edge_location == "base_edge":
        edge_endpoint = [0, 0, 1000]

    if cloud_location == "eu_central_1":
        cloud_endpoint = [3.125, 0.01, 10000]
    elif cloud_location == "us_east_1":
        cloud_endpoint = [45, 0.01, 10000]
    elif cloud_location == "eu_west_3":
        cloud_endpoint = [7.5, 0.01, 10000]

    # Set values based on 4g/5g preset (if the user didn't set anything, 4g is default)
    if wireless_preset == "4g":
        cloud_endpoint = [45, 5, 7.21]
        edge_endpoint = [7.5, 2.5, 7.21]
    elif wireless_preset == "5g":
        cloud_endpoint = [45, 5, 29.66]
        edge_endpoint = [7.5, 2.5, 29.66]

    # Overwrite with custom values
    if infrastructure.get("cloud_latency_avg", -1) != -1:
        cloud[0] = infrastructure["cloud_latency_avg"]
    if infrastructure.get("cloud_latency_var", -1) != -1:
        cloud[1] = infrastructure["cloud_latency_var"]
    if infrastructure.get("cloud_throughput", -1) != -1:
        cloud[2] = infrastructure["cloud_throughput"]
    if infrastructure.get("edge_latency_avg", -1) != -1:
        edge[0] = infrastructure["edge_latency_avg"]
    if infrastructure.get("edge_latency_var", -1) != -1:
        edge[1] = infrastructure["edge_latency_var"]
    if infrastructure.get("edge_throughput", -1) != -1:
        edge[2] = infrastructure["edge_throughput"]
    if infrastructure.get("cloud_edge_latency_avg", -1) != -1:
        cloud_edge[0] = infrastructure["cloud_edge_latency_avg"]
    if infrastructure.get("cloud_edge_latency_var", -1) != -1:
        cloud_edge[1] = infrastructure["cloud_edge_latency_var"]
    if infrastructure.get("cloud_edge_throughput", -1) != -1:
        cloud_edge[2] = infrastructure["cloud_edge_throughput"]
    if infrastructure.get("cloud_endpoint_latency_avg", -1) != -1:
        cloud_endpoint[0] = infrastructure["cloud_endpoint_latency_avg"]
    if infrastructure.get("cloud_endpoint_latency_var", -1) != -1:
        cloud_endpoint[1] = infrastructure["cloud_endpoint_latency_var"]
    if infrastructure.get("cloud_endpoint_throughput", -1) != -1:
        cloud_endpoint[2] = infrastructure["cloud_endpoint_throughput"]
    if infrastructure.get("edge_endpoint_latency_avg", -1) != -1:
        edge_endpoint[0] = infrastructure["edge_endpoint_latency_avg"]
    if infrastructure.get("edge_endpoint_latency_var", -1) != -1:
        edge_endpoint[1] = infrastructure["edge_endpoint_latency_var"]
    if infrastructure.get("edge_endpoint_throughput", -1) != -1:
        edge_endpoint[2] = infrastructure["edge_endpoint_throughput"]

    return cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint


def start(config, machines):
    """Set network latency/throughput between VMs to emulate edge continuum networking

    Whenever the network emulation is set to MahiMahi (name should end with _mahimahi),
    mobile network emulation is a responsibility of MahiMahi and the core network emulation
    is the responsibility of tc.

    Otherwise tc performs end-to-end network emulation

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Add network latency between VMs")
    uplink, downlink = mahimahi_values(config)
    cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint = tc_values(config)

    commands = []

    # For cloud nodes
    for ip in config["control_ips_internal"] + config["cloud_ips_internal"]:
        command = []
        disk = 1

        # Between cloud controller and all cloud workers
        targets = list(
            set(config["control_ips_internal"] + config["cloud_ips_internal"]) - set([ip])
        )
        if targets:
            command += generate_tc_commands(config, cloud, targets, disk)
            disk += 1

        # Between cloud and edge nodes
        targets = config["edge_ips_internal"]
        if targets:
            command += generate_tc_commands(config, cloud_edge, targets, disk)
            disk += 1

        # Between cloud and endpoint nodes
        targets = config["endpoint_ips_internal"]
        if targets:
            command += generate_tc_commands(config, cloud_endpoint, targets, disk)

        commands.append(command)

    # For edge nodes
    for ip in config["edge_ips_internal"]:
        command = []
        disk = 1

        # Between edge and other edge nodes
        targets = list(set(config["edge_ips_internal"]) - set([ip]))
        if targets:
            command += generate_tc_commands(config, edge, targets, disk)
            disk += 1

        # Between edge and cloud nodes
        targets = config["control_ips_internal"] + config["cloud_ips_internal"]
        if targets:
            command += generate_tc_commands(config, cloud_edge, targets, disk)
            disk += 1

        # Between edge and endpoint nodes
        targets = config["endpoint_ips_internal"]
        if targets:
            command += generate_tc_commands(config, edge_endpoint, targets, disk)

        commands.append(command)

    # For endpoint nodes (no endpoint->endpoint connection possible)
    for endpoint_ip in config["endpoint_ips_internal"]:
        command = []
        disk = 1

        # Between endpoint and cloud nodes
        targets = config["control_ips_internal"] + config["cloud_ips_internal"]
        if targets:
            command += generate_tc_commands(config, cloud_endpoint, targets, disk)
            disk += 1

        # Between endpoint and edge nodes
        targets = config["edge_ips_internal"]
        if targets:
            command += generate_tc_commands(config, edge_endpoint, targets, disk)

        targets = (
            config["control_ips_internal"]
            + config["cloud_ips_internal"]
            + config["edge_ips_internal"]
        )
        if targets:
            command += generate_mahimati_command(endpoint_ip, targets, uplink, downlink)

        commands.append(command)

    # Generate all TC commands and the ssh addresses where they need to be executed
    commands_final = []
    sshs = []

    for ssh, command in zip(
        config["cloud_ssh"] + config["edge_ssh"] + config["endpoint_ssh"], commands
    ):
        if not command:
            continue

        c = [" ".join(com) for com in command]
        logging.debug("TC commands for node: %s\n\t%s", ssh, "\n\t".join(c))

        c = ";".join(c)

        commands_final.append(c)
        sshs.append(ssh)

    # Execute TC command in parallel
    if commands_final:
        MAX_RETRIES = 2
        RETRY_DELAY = 3
        base_commands = list(commands_final)
        base_sshs = list(sshs)
        pending_indices = list(range(len(base_commands)))
        attempt = 0

        while True:
            pending_commands = [base_commands[i] for i in pending_indices]
            pending_sshs = [base_sshs[i] for i in pending_indices]
            results = machines[0].process(config, pending_commands, shell=True, ssh=pending_sshs)

            # Check output of TC commands
            logging.info("Check output from TC operations")
            transient_failures = []
            for idx, (output, error) in enumerate(results):
                lines = (error or []) + (output or [])
                if error or output:
                    if _is_transient_tc_error(lines) and attempt < MAX_RETRIES:
                        transient_failures.append(pending_indices[idx])
                        continue
                    if error:
                        logging.error("".join(error))
                    if output:
                        logging.error("".join(output))
                    sys.exit(1)

            if not transient_failures:
                break

            attempt += 1
            pending_indices = transient_failures
            logging.warning(
                "Transient TC error detected, retrying %i node(s) in %ss (attempt %i/%i)",
                len(pending_indices),
                RETRY_DELAY,
                attempt,
                MAX_RETRIES,
            )
            time.sleep(RETRY_DELAY)


def netperf_commands(target_ips):
    """Generate latency or throughput commands for netperf

    Args:
        target_ips (list(str)): List of ips to use netperf to

    Returns:
        list(str): List of netperf commands
    """
    lat_commands = []
    tp_commands = []
    for ip in target_ips:
        lat_commands.append(
            [
                "netperf",
                "-H",
                ip,
                "-t",
                "TCP_RR",
                "--",
                "-O",
                "min_latency,mean_latency,max_latency,stddev_latency,\
transaction_rate,p50_latency,p90_latency,p99_latency",
            ]
        )

        tp_commands.append(["netperf", "-H", ip, "-t", "TCP_STREAM"])

    return lat_commands, tp_commands


def expected_profile_values(config, source_name, target_name):
    """Return expected latency/throughput values for a source/target pair.

    Args:
        config (dict): Parsed configuration.
        source_name (str): Logical source tier name.
        target_name (str): Logical target tier name.

    Returns:
        tuple[float, float] | tuple[None, None]: Expected latency in ms and throughput in mbit.
    """
    cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint = tc_values(config)
    pair = frozenset((str(source_name), str(target_name)))

    mapping = {
        frozenset(("cloud", "cloud")): cloud,
        frozenset(("edge", "edge")): edge,
        frozenset(("cloud", "edge")): cloud_edge,
        frozenset(("cloud", "endpoint")): cloud_endpoint,
        frozenset(("edge", "endpoint")): edge_endpoint,
    }
    values = mapping.get(pair)
    if values is None:
        return None, None
    return float(values[0]), float(values[2])


def benchmark_output(
    config, machine, targets, lat_commands, tp_commands, ssh, source_name, target_name
):
    """Execute the netperf commands and log output

    Args:
        config (dict): Parsed configuration
        machine (Machine object): Machine object representing the main physical machines
        targets (list(str)): List of ips to target for netperf
        lat_commands (list(str)): Generated netperf latency commands
        tp_commands (list(str)): Generated netperf throughput commands
        ssh (str): name@ip of VM target to run netperf in
        source_name (str): Type of VM running netperf
        target_name (str): Type of VMs on the receiving side of netperf
    """
    # Prepare path for optional structured netperf results (NDJSON)
    base_dir = config["base"]
    results_dir = os.path.join(base_dir, "logs", "network_validation")
    os.makedirs(results_dir, exist_ok=True)
    ts = config["timestamp"]
    results_path = os.path.join(results_dir, f"netperf_results_{ts}.ndjson")

    all_targets = targets + targets
    all_commands = lat_commands + tp_commands

    for idx, (target_ip, command) in enumerate(zip(all_targets, all_commands)):
        output, error = machine.process(config, command, ssh=ssh)[0]
        logging.info("From %s %s to %s %s: %s", source_name, ssh, target_name, target_ip, command)
        logging.info("\n%s", "".join(output))
        logging.info("\n%s", "".join(error))

        # Write one NDJSON entry per netperf invocation for later validation
        direction = "latency" if idx < len(targets) else "throughput"
        expected_latency_ms, expected_throughput_mbps = expected_profile_values(
            config, source_name, target_name
        )
        entry = {
            "timestamp": ts,
            "source": source_name,
            "target": target_name,
            "source_ssh": ssh,
            "target_ip": target_ip,
            "direction": direction,
            "command": command,
            "output": "".join(output),
            "error": "".join(error),
            "expected_latency_ms": expected_latency_ms,
            "expected_throughput_mbps": expected_throughput_mbps,
        }
        try:
            with open(results_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            # Non-fatal; structured validation data is best-effort
            pass


def benchmark(config, machines):
    """Benchmark network

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Benchmark network between VMs")

    # Start the netperf netserver on each machine
    for ssh in config["cloud_ssh"] + config["edge_ssh"] + config["endpoint_ssh"]:
        _, _ = machines[0].process(config, ["netserver"], ssh=ssh)[0]

    # From cloud to cloud
    for ip, ssh in zip(
        config["control_ips_internal"] + config["cloud_ips_internal"], config["cloud_ssh"]
    ):
        targets = list(
            set(config["control_ips_internal"] + config["cloud_ips_internal"]) - set([ip])
        )
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "cloud"
        )

    # From cloud to edge
    for ssh in config["cloud_ssh"]:
        targets = config["edge_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "edge"
        )

    # From cloud to endpoint
    for ssh in config["cloud_ssh"]:
        targets = config["endpoint_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "endpoint"
        )

    # Between edge nodes
    for ip, ssh in zip(config["edge_ips_internal"], config["edge_ssh"]):
        targets = list(set(config["edge_ips_internal"]) - set([ip]))
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "edge", "edge"
        )

    # From edge to cloud
    for ssh in config["edge_ssh"]:
        targets = config["control_ips_internal"] + config["cloud_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "edge", "cloud"
        )

    # From edge to endpoint
    for ssh in config["edge_ssh"]:
        targets = config["endpoint_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "edge", "endpoint"
        )

    # From endpoint to cloud
    for ssh in config["endpoint_ssh"]:
        targets = config["control_ips_internal"] + config["cloud_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "endpoint", "cloud"
        )

    # From endpoint to edge
    for ssh in config["endpoint_ssh"]:
        targets = config["edge_ips_internal"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            config, machines[0], targets, lat_commands, tp_commands, ssh, "endpoint", "edge"
        )
