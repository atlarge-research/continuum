"""Manage the empty application"""

import logging
import sys
import copy
import numpy as np
import pandas as pd

from datetime import datetime

from resource_manager.kubernetes import kubernetes
from resource_manager import docker
from application import application


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    source = "redplanet00/kubeedge-applications"
    config["images"] = {"worker": "%s:empty" % (source)}


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [["sleep_time", int, lambda x: x >= 1, True, False]]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "empty":
        parser.error("ERROR: Application should be empty")
    elif config["benchmark"]["resource_manager"] != "kubernetes_control":
        parser.error("ERROR: Application empty requires resource_manager Kubernetes_control")


def baremetal(config, machines):
    """Launch a baremetal deployment, without any virtualized infrastructure, docker-only

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.error("[ERROR] Application empty only supports kube-control, not baremetal")
    sys.exit()


def mist(config, machines):
    """Launch a mist computing deployment, with edge and endpoint machines, without any RM

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.error("[ERROR] Application empty only supports kube-control, not mist")
    sys.exit()


def serverless(config, machines):
    """Launch a serverless deployment, using for example OpenFaaS

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.error("[ERROR] Application empty only supports kube-control, not serverless")
    sys.exit()


def endpoint_only(config, machines):
    """Launch a deployment with only endpoints, and no offloading between devices or RMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.error("[ERROR] Application empty only supports kube-control, not endpoint-only")
    sys.exit()


def kube(config, machines):
    """Launch a K8/kubeedge deployment, with possibly many cloud or edge workers, and endpoint users

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.error("[ERROR] Application empty only supports kube-control, not Kubernetes/KubeEdge")
    sys.exit()


def kube_control(config, machines):
    """Launch a K8 deployment, benchmarking K8's controlplane instead of applications running on it

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Cache the worker to prevent loading
    if config["benchmark"]["cache_worker"]:
        cache_worker(config, machines)

    # Start the worker
    starttime = start_worker(config, machines)

    # Start the endpoint
    container_names = start_endpoint(config, machines)
    wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    wait_worker_completion(config, machines)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = get_endpoint_output(config, machines, container_names)
    worker_output = get_worker_output(config, machines)

    # Parse output into dicts, and print result
    application.print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = gather_worker_metrics(machines, config, worker_output, starttime)
    endpoint_metrics = gather_endpoint_metrics(config, endpoint_output, container_names)
    format_output(config, worker_metrics, endpoint_metrics)


# -------------------------------------------------------------------------------------------------
def cache_worker(config, machines):
    """Start Kube applications for caching, so the real app doesn't need to load images

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    app_vars = {
        "sleep_time": 30,
    }
    kubernetes.cache_worker(config, machines, app_vars)


def start_worker(config, machines):
    """Start the MQTT subscriber application on cloud / edge workers.
    Submit the job request to the cloud controller, which automatically starts it on the cluster.
    Every cloud / edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (datetime): Invocation time of the kubectl apply command that launches the benchmark
    """
    app_vars = {
        "sleep_time": config["benchmark"]["sleep_time"],
    }
    return kubernetes.start_worker(config, machines, app_vars, get_starttime=True)


def start_endpoint(config, machines):
    """Start running the endpoint containers using Docker.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    return kubernetes.start_endpoint(config, machines)


def wait_endpoint_completion(config, machines, sshs, container_names):
    """Wait for all containers to be finished running the benchmark on endpoints
    OR for all mist containers, which also use docker so this function can be reused

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        sshs (list(str)): SSH addresses to edge or endpoint VMs
        container_names (list(str)): Names of docker containers launched
    """
    return kubernetes.wait_endpoint_completion(config, machines, sshs, container_names)


def wait_worker_completion(config, machines):
    """Wait for all containers to be finished running the benchmark on cloud/edge workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    return kubernetes.wait_worker_completion(config, machines)


def get_endpoint_output(config, machines, container_names, use_ssh=True):
    """Get the output of endpoint docker containers.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched
        use_ssh (bool, optional): SSH into a container or not (for bare-metal). Defaults to True

    Returns:
        list(list(str)): Output of each endpoint container
    """
    return docker.get_endpoint_output(config, machines, container_names, use_ssh=use_ssh)


def get_worker_output(config, machines, command):
    """Get the output of worker cloud / edge applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        command (list(str)): Command to execute to get output for a specific application

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    logging.info("Gather output from subscribers")

    # Get list of pods
    command = [
        "kubectl",
        "get",
        "pods",
        "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase",
        "--sort-by=.spec.nodeName",
    ]
    output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

    if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
        logging.error("".join(error))
        sys.exit()

    # Gather commands to get logs
    commands = []
    for line in output[1:]:
        container = line.split(" ")[0]

        command = "\"sudo su -c 'cd /var/log && grep -ri %s &> output-%s.txt'\"" % (
            container,
            container,
        )
        machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])

        command = ["kubectl", "get", "pod", container, "-o", "yaml"]
        commands.append(command)

    # Get the logs
    results = machines[0].process(config, commands, ssh=config["cloud_ssh"][0])

    # Get the output
    worker_output = []
    for i, (output, error) in enumerate(results):
        if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
            logging.error("Container %i: %s", i, "".join(error))
            sys.exit()

        output = [line.rstrip() for line in output]
        worker_output.append(output)

    return worker_output


def gather_worker_metrics(machines, config, worker_output, starttime):
    """Gather metrics from cloud or edge workers for the empty app

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        starttime (datetime): Time that 'kubectl apply' is called to launche the benchmark

    Returns:
        list(dict): List of parsed output for each cloud or edge worker
    """
    logging.info("Gather metrics with start time: %s", str(starttime))

    worker_set = {
        "total_time": None,  # Total scheduling time
    }

    worker_metrics = []
    for _ in range(len(worker_output)):
        worker_metrics.append(copy.deepcopy(worker_set))

    commands = []
    sshs = []

    # Parse output and build new commands to get final data with
    for i, out in enumerate(worker_output):
        container_id = 0
        nodename = 0

        for line in out:
            if "nodeName" in line:
                nodename = line.split("nodeName: ")[1]
            elif "containerID" in line:
                container_id = line.split("://")[1]
                break

        if container_id == 0 or nodename == 0:
            logging.error("Could not find containerID for pod or scheduled node")
            sys.exit()

        # Get output from the worker node using journalctl, to get millisecond timing
        command = """sudo journalctl -u containerd -o short-precise | \
grep \'StartContainer for \\\\\"%s\\\\\" returns successfully'""" % (
            container_id
        )
        commands.append(command)

        for machine in machines:
            if nodename in machine.cloud_names + machine.edge_names:
                if nodename in machine.cloud_names:
                    i = machine.cloud_names.index(nodename)
                    ip = machine.cloud_ips[i]
                elif nodename in machine.edge_names:
                    i = machine.edge_names.index(nodename)
                    ip = machine.edge_ips[i]

                ssh = "%s@%s" % (nodename, ip)
                sshs.append(ssh)
                break

    # Given the commands and the ssh address to execute it at, execute all commands
    results = machines[0].process(config, commands, shell=True, ssh=sshs, retryonoutput=True)

    # Parse the final output to get the total execution time
    for i, (command, (output, error)) in enumerate(zip(commands, results)):
        if not output:
            logging.error("No output for pod %i and command [%s]", i, command)
            sys.exit()
        if len(output) > 1:
            logging.error(
                "Incorrect output for pod %i and command [%s]: %s", i, command, "".join(output)
            )
            sys.exit()
        elif error and not all("[CONTINUUM]" in l for l in error):
            logging.error("Error for pod %i and command [%s]: %s", i, command, "".join(error))
            sys.exit()

        # Now parse the line to datetime with milliseconds
        dt = output[0].split('time="')[1].split("+")[0]
        dt = dt.replace("T", " ")
        dt = dt[:-3]
        dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
        end_time = datetime.timestamp(dt)

        worker_metrics[i]["total_time"] = end_time - starttime

    return sorted(worker_metrics, key=lambda x: x["total_time"])


def gather_endpoint_metrics(config, endpoint_output, container_names):
    """Gather metrics from endpoints

    Args:
        config (dict): Parsed configuration
        endpoint_output (list(list(str))): Output of each endpoint container
        container_names (list(str)): Names of docker containers launched

    Returns:
        list(dict): List of parsed output for each endpoint
    """
    endpoint_metrics = []
    endpoint_set = {
        "worker_id": None,  # To which worker is this endpoint connected
        "total_time": None,  # Total runtime of the endpoint
        "proc_avg": None,  # Average procesing time per data element
        "data_avg": None,  # Average generated data size
        "latency_avg": None,  # Average end-to-end latency
        "latency_stdev": None,  # Stdev latency
    }

    # Use 5th-90th percentile for average
    lower_percentile = 0.05
    upper_percentile = 0.90

    for out, container_name in zip(endpoint_output, container_names):
        logging.info("Parse output from endpoint %s", container_name)
        endpoint_metrics.append(copy.deepcopy(endpoint_set))

        # Get timestamp from first and last line
        start_time = application.to_datetime_image(out[0])
        end_time = application.to_datetime_image(out[-1])

        endpoint_metrics[-1]["total_time"] = round((end_time - start_time).total_seconds(), 2)
        endpoint_metrics[-1]["data_avg"] = 0.0

        if config["mode"] == "cloud":
            name = container_name.split("_")[0]
            endpoint_metrics[-1]["worker_id"] = int(name[5:])
        elif config["mode"] == "edge":
            name = container_name.split("_")[0]
            endpoint_metrics[-1]["worker_id"] = int(name[4:])
        elif config["mode"] == "endpoint":
            endpoint_metrics[-1]["worker_id"] = int(container_name[8:])

        # Parse line by line to get preparation, preprocessing and processing times
        processing = []
        latency = []
        data_size = []
        for line in out:
            if any(
                word in line
                for word in [
                    "Preparation and preprocessing",
                    "Preparation, preprocessing and processing",
                    "Sending data",
                    "Latency",
                ]
            ):
                try:
                    unit = line[line.find("(") + 1 : line.find(")")]
                    number = int(line.rstrip().split(":")[-1])
                except ValueError as e:
                    logging.warning("Got an error while parsing line: %s. Exception: %s", line, e)
                    continue

                units = ["ns", "bytes"]
                if number < 0:
                    logging.warning("Time/Size < 0 should not be possible: %i", number)
                    continue

                if unit not in units:
                    logging.warning("Unit should be one of [%s], got %s", ",".join(units), unit)
                    continue

                if "Preparation, preprocessing and processing" in line:
                    processing.append(round(number / 10**6, 4))
                elif "Preparation and preprocessing" in line:
                    processing.append(round(number / 10**6, 4))
                elif "Latency" in line:
                    latency.append(round(number / 10**6, 4))
                elif "Sending data" in line:
                    data_size.append(round(number / 10**3, 4))

        processing.sort()
        latency.sort()

        logging.info(
            "Get percentile values between %i - %i", lower_percentile * 100, upper_percentile * 100
        )

        processing_perc = processing[
            int(len(processing) * lower_percentile) : int(len(processing) * upper_percentile)
        ]
        latency_perc = latency[
            int(len(latency) * lower_percentile) : int(len(latency) * upper_percentile)
        ]

        # endpoint_metrics[-1]["proc_avg"] = round(np.mean(processing_perc), 2)
        # endpoint_metrics[-1]["latency_avg"] = round(np.mean(latency_perc), 2)
        # endpoint_metrics[-1]["latency_stdev"] = round(np.std(latency_perc), 2)
        endpoint_metrics[-1]["proc_avg"] = round(np.median(processing_perc), 2)
        endpoint_metrics[-1]["latency_avg"] = round(np.median(latency_perc), 2)
        endpoint_metrics[-1]["latency_stdev"] = round(np.std(latency_perc), 2)

        if data_size:
            # endpoint_metrics[-1]["data_avg"] = round(np.mean(data_size), 2)
            endpoint_metrics[-1]["data_avg"] = round(np.median(data_size), 2)

    endpoint_metrics = sorted(endpoint_metrics, key=lambda x: x["worker_id"])

    return endpoint_metrics


def format_output(config, worker_metrics):
    """Format processed output to provide useful insights (empty)

    Args:
        config (dict): Parsed configuration
        sub_metrics (list(dict)): Metrics per worker node
    """
    logging.info("------------------------------------")
    logging.info("%s OUTPUT", config["mode"].upper())
    logging.info("------------------------------------")
    df = pd.DataFrame(worker_metrics)
    df.rename(
        columns={
            "total_time": "total_time (ms)",
        },
        inplace=True,
    )
    df_no_indices = df.to_string(index=False)
    logging.info("\n%s", df_no_indices)

    # Print ouput in csv format
    logging.debug("Output in csv format\n%s", repr(df.to_csv()))
