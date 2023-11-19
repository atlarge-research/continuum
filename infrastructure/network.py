"""\
Use TC to control latency/throughput between machines.
Additionally, use netperf to perform network benchmarks between machines if desired.

TODO - move netperf to /software as its own package
"""

import logging
import sys

import settings


def _generate_tc_commands(values, ips, disk, provider_name):
    """Generate TC commands

    Args:
        values (list(float)): Average latency, latency variance, throughput
        ips (list(str)): List of ips to filter TC for
        disk (int): qdisc to attach to
        provider_name (str): Name of the provider of the source machine

    Returns:
        list(str): List of TC commands
    """
    if all(value == -1 for value in values):
        return []

    if not ips:
        logging.error("ERROR: Trying to emulate a link to a non-existent target layer")
        sys.exit()

    lat_avg = values[0]
    lat_var = values[1]
    through = values[2]

    network = "ens2"
    if provider_name == "gcp":
        network = "ens4"

    commands = []

    if disk == 1:
        # Root disk
        command = f"sudo tc qdisc add dev {network} root handle 1: htb"
        commands.append(command.split(" "))

    # Set throughput
    if through != -1:
        command = (
            f"sudo tc class add dev {network} parent 1: classid 1:{disk} htb rate {through}mbit"
        )
        commands.append(command.split(" "))

    # Filter for specific IPs
    for ip in ips:
        command = (
            f"sudo tc filter add dev {network} parent 1: protocol ip prio {disk} u32 flowid "
            f"1:{disk} match ip dst {ip}"
        )
        commands.append(command.split(" "))

    # Set latency
    if lat_avg != -1:
        command = (
            f"sudo tc qdisc add dev {network} parent 1:{disk} handle i0:{disk} netem delay "
            f"{lat_avg}ms {lat_var}ms distribution normal"
        )
        commands.append(command.split(" "))

    return commands


def _get_tc_values(layer):
    """Get latency/throughput values to be used for tc

    Sources:
    - For 4G/5G: https://www.ericsson.com/en/blog/2022/8/who-cares-about-latency-in-5g
    - For edge: https://dl.acm.org/doi/pdf/10.1145/3422604.3425943
    - For cloud: No latency, 10Gbps networks are faster than what we need

    Args:
        layer (dict): Part of the config describing the layer that wants network emulation

    Returns:
        dict: TC emulation values per link between and inside layers ([lat_avg, lat_var, tp])
    """
    # Dict saving all network emulation values, including some default values
    # [latency_average (ms), latency_variance (ms), throughput (mbit)]
    # Values are from X to Y (e.g., 'cloud_edge')
    # Or, in case only X is mentioned, values are between X machines (e.g., 'cloud')
    values = {
        "cloud": [],  # Assume datacenter-grade wired
        "cloud_edge": [],  # Assume wired (consumer hardware)
        "cloud_endpoint": [],  # cloud_edge + edge_endpoint ideally
        "edge_cloud": [],  # Assume wired (consumer hardware)
        "edge": [],  # Assume wired (over network backbone)
        "edge_endpoint": [],  # Assume wireless
        "endpoint_cloud": [],  # cloud_edge + edge_endpoint ideally
        "endpoint_edge": [],  # Assume wireless
        "endpoint": [],  # endpoint_edge + endpoint_edge, assuming no interconnect
    }

    # Fill with -1 values as default
    for key in values:
        values[key] = [-1, -1, -1]

    # Set values based on 4g/5g preset (work symmetrical)
    # Source: https://www.ericsson.com/en/blog/2022/8/who-cares-about-latency-in-5g
    if "preset" in layer["infrastructure"]["network"]:
        # DESIGN DECISION: These values are only used when preset is activated
        values["cloud"] = [0, 0, 10000]
        values["cloud_edge"] = [10.0, 2.5, 1000]
        values["edge_cloud"] = values["cloud_edge"]
        values["edge"] = values["edge_cloud"]

        if layer["infrastructure"]["network"]["preset"] == "4g":
            values["edge_endpoint"] = [30.0, 5, 7.21]
        elif layer["infrastructure"]["network"]["preset"] == "5g":
            values["edge_endpoint"] = [15, 2.5, 29.66]

        values["endpoint_edge"] = values["edge_endpoint"]

        values["endpoint"] = [
            values["edge_endpoint"][0] * 2,
            values["edge_endpoint"][1],
            values["edge_endpoint"][2],
        ]

        values["cloud_endpoint"] = [
            values["cloud_edge"][0] + values["edge_endpoint"][0],
            max(values["cloud_edge"][1], values["edge_endpoint"][1]),
            min(values["cloud_edge"][2], values["edge_endpoint"][2]),
        ]
        values["endpoint_cloud"] = values["cloud_endpoint"]

    # Use custom values, overwrite preset if required
    # Later we will ignore anything with -1 as value
    if "link" in layer["infrastructure"]["network"]:
        source = layer["name"]
        for link in layer["infrastructure"]["network"]["link"]:
            dest = link["destination"]

            link_name = f"{source}_{dest}"
            if source == dest:
                link_name = source

            # If custom value is not -1, overwrite what's already there
            if link["latency_avg"] != -1:
                values[link_name][0] = link["latency_avg"]
            if link["latency_var"] != -1:
                values[link_name][1] = link["latency_var"]
            if link["throughput"] != -1:
                values[link_name][2] = link["throughput"]

    return values


def start(layer):
    """Set network latency/throughput between VMs to emulate edge continuum networking

    Args:
        layer (dict): Part of the config describing the layer that wants network emulation
    """
    logging.info("Add network latency between VMs")
    values = _get_tc_values(layer)

    provider = settings.get_providers(layer_name=layer["name"])[0]

    commands = []
    disk = 1
    for key in values:
        # Determine source and target of link
        if "_" in key:
            source = key.split("_")[0]
            target = key.split("_")[0]
        else:
            # E.g., key = 'cloud'
            source = key
            target = key

        # Only use links originating from this layer
        if source != layer["name"]:
            continue

        # Get the SSh address of targets
        target_ips = settings.get_ips(layer_name=target, internal=True)
        commands += _generate_tc_commands(values[key], target_ips, disk, provider["name"])
        disk += 1  # Each link on a specific machine should be in a new disk

    # Append the TC into one big command per machine
    commands_final = []
    machines = []
    for machine, command in zip(settings.get_machines(layer_name=layer["name"]), commands):
        if not command:
            continue

        c = [" ".join(com) for com in command]
        logging.debug("TC commands for node: %s\n\t%s", machine.name, "\n\t".join(c))

        c = ";".join(c)
        c = '"' + c + '"'

        commands_final.append(c)
        machines.append(machine)

    # Execute TC command in parallel
    if commands_final:
        results = settings.process(commands_final, shell=True, ssh=machines)

        # Check output of TC commands
        logging.info("Check output from TC operations")
        for output, error in results:
            if error:
                logging.error("".join(error))
                sys.exit()
            elif output:
                logging.error("".join(output))
                sys.exit()


def _netperf_commands(target_ips):
    """Generate latency or throughput commands for netperf

    Args:
        target_ips (list(str)): List of ips to use netperf to

    Returns:
        list(str): List of netperf commands
    """
    lat_commands = []
    tp_commands = []
    for ip in target_ips:
        command = (
            f"netperf -H {ip} -t TCP_RR -- -O min_latency,mean_latency,max_latency,stddev_latency,"
            f"transaction_rate,p50_latency,p90_latency,p99_latency"
        )
        lat_commands.append(command.split(" "))
        tp_commands.append(["netperf", "-H", ip, "-t", "TCP_STREAM"])

    return lat_commands, tp_commands


def _benchmark_output(target_ips, lat_commands, tp_commands, machine, target_layer):
    """Execute the netperf commands and log output

    Args:
        target_ips (list(str)): List of ips to target for netperf
        lat_commands (list(str)): Generated netperf latency commands
        tp_commands (list(str)): Generated netperf throughput commands
        machine (Machine): machine object of the source machine we're executing on
        target_layer (str): Name of the layer on which the targets are on of the benchmark
    """
    for target_ip, command in zip(target_ips + target_ips, lat_commands + tp_commands):
        output, error = settings.process(command, ssh=machine)[0]
        logging.info(f"From {machine['name']} to {target_layer} ({target_ip}): {command}")
        logging.info("\n%s", "".join(output))
        logging.info("\n%s", "".join(error))


def benchmark():
    """Benchmark network between provisioned machines with netperf"""
    logging.info("Benchmark network between VMs")

    # Start the netperf netserver on each machine
    for machine in settings.get_machines():
        settings.process([["netserver"]], ssh=machine)

    # For each machine, perform evaluate its network to all other machines on all other layers,
    for machine in settings.get_machines():
        for layer in settings.get_layers():
            target_ips = settings.get_ips(layer_name=layer["name"], internal=True)
            if machine.ip_internal in target_ips:
                target_ips.remove(machine.ip_internal)

            lat_commands, tp_commands = _netperf_commands(target_ips)
            _benchmark_output(target_ips, lat_commands, tp_commands, machine, layer["name"])
