"""\
Use TC to control latency / throughput between VMs, and perform network benchmarks with netperf.
"""

import logging
import sys


def generate_tc_commands(values, overhead, ips, disk):
    """Generate TC commands

    Args:
        values (list(float)): Avg latency, Var latency, throughput
        packets_overhead (int): Increase the buffer by x for safety
        ips (list(str)): List of ips to filter TC for
        disk (int): Qdisc to attach to

    Returns:
        list(str): List of TC commands
    """
    latency_avg = values[0]
    latency_var = values[1]
    throughput = values[2]

    commands = []

    if disk == 1:
        # Root disk
        commands.append(
            ["sudo", "tc", "qdisc", "add", "dev", "ens2", "root", "handle", "1:", "htb"]
        )

    # Set throughput
    commands.append(
        [
            "sudo",
            "tc",
            "class",
            "add",
            "dev",
            "ens2",
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
                "ens2",
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
                "ens2",
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


def tc_values(config):
    """Set latency/throughput values to be used for tc

    Args:
        config (dict): Parsed configuration

    Returns:
        5x list(int, int, int): TC network values to be used
    """
    # Default values
    cloud = [0, 0, 1000]  # Between cloud nodes (wired)
    edge = [7.5, 2.5, 1000]  # Between edge nodes (wired)
    cloud_edge = [7.5, 2.5, 1000]  # Between cloud and edge (wired)

    # Set values based on 4g/5g preset (if the user didn't set anything, 4g is default)
    if config["infrastructure"]["wireless_network_preset"] == "4g":
        cloud_endpoint = [45, 5, 7.21]
        edge_endpoint = [7.5, 2.5, 7.21]
    elif config["infrastructure"]["wireless_network_preset"] == "5g":
        cloud_endpoint = [45, 5, 29.66]
        edge_endpoint = [7.5, 2.5, 29.66]

    # Overwrite with custom values
    if "cloud_latency_avg" in config["infrastructure"]:
        cloud[0] = config["infrastructure"]["cloud_latency_avg"]
    if "cloud_latency_var" in config["infrastructure"]:
        cloud[1] = config["infrastructure"]["cloud_latency_var"]
    if "cloud_throughput" in config["infrastructure"]:
        cloud[2] = config["infrastructure"]["cloud_throughput"]
    if "edge_latency_avg" in config["infrastructure"]:
        edge[0] = config["infrastructure"]["edge_latency_avg"]
    if "edge_latency_var" in config["infrastructure"]:
        edge[1] = config["infrastructure"]["edge_latency_var"]
    if "edge_throughput" in config["infrastructure"]:
        edge[2] = config["infrastructure"]["edge_throughput"]
    if "cloud_edge_latency_avg" in config["infrastructure"]:
        cloud_edge[0] = config["infrastructure"]["cloud_edge_latency_avg"]
    if "cloud_edge_latency_var" in config["infrastructure"]:
        cloud_edge[1] = config["infrastructure"]["cloud_edge_latency_var"]
    if "cloud_edge_throughput" in config["infrastructure"]:
        cloud_edge[2] = config["infrastructure"]["cloud_edge_throughput"]
    if "cloud_endpoint_latency_avg" in config["infrastructure"]:
        cloud_endpoint[0] = config["infrastructure"]["cloud_endpoint_latency_avg"]
    if "cloud_endpoint_latency_var" in config["infrastructure"]:
        cloud_endpoint[1] = config["infrastructure"]["cloud_endpoint_latency_var"]
    if "cloud_endpoint_throughput" in config["infrastructure"]:
        cloud_endpoint[2] = config["infrastructure"]["cloud_endpoint_throughput"]
    if "edge_endpoint_latency_avg" in config["infrastructure"]:
        edge_endpoint[0] = config["infrastructure"]["edge_endpoint_latency_avg"]
    if "edge_endpoint_latency_var" in config["infrastructure"]:
        edge_endpoint[1] = config["infrastructure"]["edge_endpoint_latency_var"]
    if "edge_endpoint_throughput" in config["infrastructure"]:
        edge_endpoint[2] = config["infrastructure"]["edge_endpoint_throughput"]

    return cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint


def start(config, machines):
    """Set network latency/throughput between VMs to emulate edge continuum networking

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Add network latency between VMs")
    cloud, edge, cloud_edge, cloud_endpoint, edge_endpoint = tc_values(config)

    overhead = 2
    commands = []

    # For cloud nodes
    for ssh in config["cloud_ssh"]:
        command = []
        disk = 1

        # Between cloud and other cloud nodes
        targets = list(
            set(config["control_ips"] + config["cloud_ips"]) - set([ssh.split("@")[1]])
        )
        if targets != []:
            command += generate_tc_commands(cloud, overhead, targets, disk)
            disk += 1

        # Between cloud and edge nodes
        targets = config["edge_ips"]
        if targets != []:
            command += generate_tc_commands(cloud_edge, overhead, targets, disk)
            disk += 1

        # Between cloud and endpoint nodes
        targets = config["endpoint_ips"]
        if targets != []:
            command += generate_tc_commands(cloud_endpoint, overhead, targets, disk)

        commands.append(command)

    # For edge nodes
    for ssh in config["edge_ssh"]:
        command = []
        disk = 1

        # Between edge and other edge nodes
        targets = list(set(config["edge_ips"]) - set([ssh.split("@")[1]]))
        if targets != []:
            command += generate_tc_commands(edge, overhead, targets, disk)
            disk += 1

        # Between edge and cloud nodes
        targets = config["control_ips"] + config["cloud_ips"]
        if targets != []:
            command += generate_tc_commands(cloud_edge, overhead, targets, disk)
            disk += 1

        # Between edge and endpoint nodes
        targets = config["endpoint_ips"]
        if targets != []:
            command += generate_tc_commands(edge_endpoint, overhead, targets, disk)

        commands.append(command)

    # For endpoint nodes (no endpoint->endpoint connection possible)
    for ssh in config["endpoint_ssh"]:
        command = []
        disk = 1

        # Between endpoint and cloud nodes
        targets = config["control_ips"] + config["cloud_ips"]
        if targets != []:
            command += generate_tc_commands(cloud_endpoint, overhead, targets, disk)
            disk += 1

        # Between endpoint and edge nodes
        targets = config["edge_ips"]
        if targets != []:
            command += generate_tc_commands(edge_endpoint, overhead, targets, disk)

        commands.append(command)

    # Execute TC command in parallel
    processes = []
    for ssh, command in zip(
        config["cloud_ssh"] + config["edge_ssh"] + config["endpoint_ssh"], commands
    ):
        if command == []:
            processes.append(False)
            continue

        c = [" ".join(com) for com in command]
        logging.debug("TC commands for node: %s\n\t%s" % (ssh, "\n\t".join(c)))

        c = ";".join(c)
        c = '"' + c + '"'

        processes.append(
            machines[0].process(c, shell=True, output=False, ssh=True, ssh_target=ssh)
        )

    # Check output of TC commands
    logging.info("Check output from TC operations")
    for process in processes:
        if process == False:
            continue

        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]

        if error != []:
            logging.error("".join(error))
            sys.exit()
        elif output != []:
            logging.error("".join(output))
            sys.exit()


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
                "min_latency,mean_latency,max_latency,stddev_latency,transaction_rate,p50_latency,p90_latency,p99_latency",
            ]
        )

        tp_commands.append(["netperf", "-H", ip, "-t", "TCP_STREAM"])

    return lat_commands, tp_commands


def benchmark_output(
    machine, targets, lat_commands, tp_commands, ssh, source_name, target_name
):
    """Execute the netperf commands and log output

    Args:
        machine (Machine object): Machine object representing the main physical machines
        targets (list(str)): List of ips to target for netperf
        lat_commands (list(str)): Generated netperf latency commands
        tp_commands (list(str)): Generated netperf throughput commands
        ssh (str): name@ip of VM target to run netperf in
        source_name (str): Type of VM running netperf
        target_name (str): Type of VMs on the receiving side of netperf
    """
    for target_ip, command in zip(targets + targets, lat_commands + tp_commands):
        output, error = machine.process(command, ssh=True, ssh_target=ssh)
        logging.info(
            "From %s %s to %s %s: %s"
            % (source_name, ssh, target_name, target_ip, command)
        )
        logging.info("\n" + "".join(output))
        logging.info("\n" + "".join(error))


def benchmark(config, machines):
    """Benchmark network

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Benchmark network between VMs")

    # Start the netperf netserver on each machine
    for ssh in config["cloud_ssh"] + config["edge_ssh"] + config["endpoint_ssh"]:
        _, _ = machines[0].process(["netserver"], ssh=True, ssh_target=ssh)

    # Between cloud nodes
    for ssh in config["cloud_ssh"]:
        targets = list(
            set(config["control_ips"] + config["cloud_ips"]) - set([ssh.split("@")[1]])
        )
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "cloud"
        )

    # From cloud to edge
    for ssh in config["cloud_ssh"]:
        targets = config["edge_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "edge"
        )

    # From cloud to endpoint
    for ssh in config["cloud_ssh"]:
        targets = config["endpoint_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "cloud", "endpoint"
        )

    # Between edge nodes
    for ssh in config["edge_ssh"]:
        targets = list(set(config["edge_ips"]) - set([ssh.split("@")[1]]))
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "edge", "edge"
        )

    # From edge to cloud
    for ssh in config["edge_ssh"]:
        targets = config["control_ips"] + config["cloud_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "edge", "cloud"
        )

    # From edge to endpoint
    for ssh in config["edge_ssh"]:
        targets = config["endpoint_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "edge", "endpoint"
        )

    # From endpoint to cloud
    for ssh in config["endpoint_ssh"]:
        targets = config["control_ips"] + config["cloud_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "endpoint", "cloud"
        )

    # From endpoint to edge
    for ssh in config["endpoint_ssh"]:
        targets = config["edge_ips"]
        lat_commands, tp_commands = netperf_commands(targets)
        benchmark_output(
            machines[0], targets, lat_commands, tp_commands, ssh, "endpoint", "edge"
        )
