"""\
Use TC to control latency / throughput between VMs, and perform network benchmarks with netperf.
"""

import logging
import shlex
import sys


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
            ]
        )

        if float(latency_var) > 0.0:
            commands[-1] += ["%sms" % latency_var, "distribution", "normal"]

    return commands

def generate_mahimati_command(endpoint_ip, targets, uplink, downlink):
    """Start checked bidirectional access replay on an endpoint VM."""
    if not uplink or not downlink:
        return []
    return [[
        "sudo", "-n", "/usr/bin/python3", "/home/mahimahi/continuum_replay.py",
        "start", endpoint_ip, uplink, downlink, *targets,
    ]]


def mahimahi_values(config):
    """
        Set values used for for MahiMahi
        In case non-mahimahi preset is used, function returns None

    Args:
        config (dict): Parsed configuration

    Returns:
        2x list(str): Path to the MahiMahi traces
    """
    if config["infrastructure"]["wireless_network_preset"] == '4g_us_verizon_mahimahi':
        return ["/home/mahimahi/traces/Verizon-LTE-driving.up", "/home/mahimahi/traces/Verizon-LTE-driving.down",]
    
    elif config["infrastructure"]["wireless_network_preset"] == '5g_nl_kpn_mahimahi':
        return ["/home/mahimahi/traces/KPN_5G.up", "/home/mahimahi/traces/KPN_5G.down",]

    elif config["infrastructure"]["wireless_network_preset"] == 'lte_nl_kpn_mahimahi':
        return ["/home/mahimahi/traces/KPN_4G.up", "/home/mahimahi/traces/KPN_4G.down",]
    
    elif config["infrastructure"]["wireless_network_preset"] == '5g_obstacled_nl_kpn_mahimahi':
        return ["/home/mahimahi/traces/KPN_5G_low_band.up", "/home/mahimahi/traces/KPN_5G_low_band.down",]
    
    elif config["infrastructure"]["wireless_network_preset"] == 'evdo_us_verizon_mahimahi':
        return ["/home/mahimahi/traces/Verizon-EVDO-driving.up", "/home/mahimahi/traces/Verizon-EVDO-driving.down",]

    return [None, None]

def tc_values(config):
    """Set latency/throughput values to be used for tc

    The MahiMahi keys have the following format: standard_location_provider

    Args:
        config (dict): Parsed configuration

    Returns:
        5x list(int, int, int): TC network values to be used
    """
    # Default values
    cloud = [0, 0, 1000]  # Between cloud nodes (wired)
    edge = [7.5, 2.5, 1000]  # Between edge nodes (wired)
    cloud_edge = [7.5, 2.5, 1000]  # Between cloud and edge (wired)

    cloud_endpoint = [0, 0, 1000]  # Additional core path in replay mode
    edge_endpoint = [0, 0, 1000]

    if config["infrastructure"]["edge_location"] == "aws_vodafone_edge":
        edge_endpoint = [0.07, 0.01, 10000]
    elif config["infrastructure"]["edge_location"] == "base_edge":
        edge_endpoint = [0, 0, 1000]

    if config["infrastructure"]["cloud_location"] == "eu_central_1":
        cloud_endpoint = [3.125, 0.01, 10000]
    elif config["infrastructure"]["cloud_location"] == "us_east_1":
        cloud_endpoint = [45, 0.01, 10000]
    elif config["infrastructure"]["cloud_location"] == "eu_west_3":
        cloud_endpoint = [7.5, 0.01, 10000]

    # Set values based on 4g/5g preset (if the user didn't set anything, 4g is default)
    if config["infrastructure"]["wireless_network_preset"] == "4g":
        cloud_endpoint = [45, 5, 7.21]
        edge_endpoint = [7.5, 2.5, 7.21]
    elif config["infrastructure"]["wireless_network_preset"] == "5g":
        cloud_endpoint = [45, 5, 29.66]
        edge_endpoint = [7.5, 2.5, 29.66]

    # Overwrite with custom values
    if config["infrastructure"]["cloud_latency_avg"] != -1:
        cloud[0] = config["infrastructure"]["cloud_latency_avg"]
    if config["infrastructure"]["cloud_latency_var"] != -1:
        cloud[1] = config["infrastructure"]["cloud_latency_var"]
    if config["infrastructure"]["cloud_throughput"] != -1:
        cloud[2] = config["infrastructure"]["cloud_throughput"]
    if config["infrastructure"]["edge_latency_avg"] != -1:
        edge[0] = config["infrastructure"]["edge_latency_avg"]
    if config["infrastructure"]["edge_latency_var"] != -1:
        edge[1] = config["infrastructure"]["edge_latency_var"]
    if config["infrastructure"]["edge_throughput"] != -1:
        edge[2] = config["infrastructure"]["edge_throughput"]
    if config["infrastructure"]["cloud_edge_latency_avg"] != -1:
        cloud_edge[0] = config["infrastructure"]["cloud_edge_latency_avg"]
    if config["infrastructure"]["cloud_edge_latency_var"] != -1:
        cloud_edge[1] = config["infrastructure"]["cloud_edge_latency_var"]
    if config["infrastructure"]["cloud_edge_throughput"] != -1:
        cloud_edge[2] = config["infrastructure"]["cloud_edge_throughput"]
    if config["infrastructure"]["cloud_endpoint_latency_avg"] != -1:
        cloud_endpoint[0] = config["infrastructure"]["cloud_endpoint_latency_avg"]
    if config["infrastructure"]["cloud_endpoint_latency_var"] != -1:
        cloud_endpoint[1] = config["infrastructure"]["cloud_endpoint_latency_var"]
    if config["infrastructure"]["cloud_endpoint_throughput"] != -1:
        cloud_endpoint[2] = config["infrastructure"]["cloud_endpoint_throughput"]
    if config["infrastructure"]["edge_endpoint_latency_avg"] != -1:
        edge_endpoint[0] = config["infrastructure"]["edge_endpoint_latency_avg"]
    if config["infrastructure"]["edge_endpoint_latency_var"] != -1:
        edge_endpoint[1] = config["infrastructure"]["edge_endpoint_latency_var"]
    if config["infrastructure"]["edge_endpoint_throughput"] != -1:
        edge_endpoint[2] = config["infrastructure"]["edge_endpoint_throughput"]

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
    if uplink and config["infrastructure"]["provider"] != "qemu":
        raise ValueError("MahiMahi replay requires the verified QEMU VM layout")
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

        targets = config["control_ips_internal"] + config["cloud_ips_internal"] + config["edge_ips_internal"]
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

        # Quote once for the local shell; the remote shell must see set -e,
        # so a failed tc or replay setup cannot be hidden by later commands.
        script = "set -eu; " + "; ".join(shlex.join(com) for com in command)
        script += "; echo CONTINUUM_NETWORK_READY"
        logging.debug("Network commands for node %s: %s", ssh, script)
        commands_final.append(shlex.quote(script))
        sshs.append(ssh)

    if commands_final:
        results = machines[0].process(config, commands_final, shell=True, ssh=sshs)
        if len(results) != len(sshs):
            raise RuntimeError("Missing network setup results")
        for ssh, (output, error) in zip(sshs, results):
            if not any(line.strip() == "CONTINUUM_NETWORK_READY" for line in output):
                raise RuntimeError("Network setup failed on %s: %s" % (ssh, "".join(error + output)))
            if error:
                logging.warning("Network setup on %s: %s", ssh, "".join(error))


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
    for target_ip, command in zip(targets + targets, lat_commands + tp_commands):
        output, error = machine.process(config, command, ssh=ssh)[0]
        logging.info("From %s %s to %s %s: %s", source_name, ssh, target_name, target_ip, command)
        logging.info("\n%s", "".join(output))
        logging.info("\n%s", "".join(error))


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
