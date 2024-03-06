"""\
Manage applicaiton logic in the framework
Mostly used for calling specific application code
"""

import logging
import sys

from datetime import datetime

from resource_manager.kube_kata import kube_kata
from resource_manager.kubernetes import kubernetes
from resource_manager.endpoint import endpoint
from execution_model.openfaas import openfaas


def set_container_location(config):
    """[INTERFACE] Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    config["module"]["application"].set_container_location(config)


def add_options(config):
    """[INTERFACE] Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object
    """
    return config["module"]["application"].add_options(config)


def verify_options(parser, config):
    """[INTERFACE] Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    config["module"]["application"].verify_options(parser, config)


def start(config, machines):
    """[INTERFACE] Start the application with a certain deployment model

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    if config["infrastructure"]["provider"] == "baremetal":
        baremetal(config, machines)
    elif config["benchmark"]["resource_manager"] == "mist":
        mist(config, machines)
    elif config["module"]["execution_model"] and config["execution_model"]["model"] == "openfaas":
        serverless(config, machines)
    elif config["benchmark"]["resource_manager"] == "none":
        endpoint_only(config, machines)
    elif config["benchmark"]["resource_manager"] in ["kubernetes", "kubeedge"]:
        kube(config, machines)
    elif config["benchmark"]["resource_manager"] in ["kubecontrol", "kube_kata"]:
        kube_control(config, machines)
    else:
        logging.error("ERROR: Don't have a deployment for this resource manager / application")
        sys.exit()


def print_raw_output(config, worker_output, endpoint_output):
    """Print the raw output

    Args:
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        endpoint_output (list(list(str))): Output of each endpoint container
    """
    logging.debug("Print raw output from subscribers and publishers")
    if (config["mode"] == "cloud" or config["mode"] == "edge") and worker_output:
        logging.debug("------------------------------------")
        logging.debug("%s OUTPUT", config["mode"].upper())
        logging.debug("------------------------------------")
        for _, out in worker_output:
            for line in out:
                logging.debug(line)

            logging.debug("------------------------------------")

    if config["infrastructure"]["endpoint_nodes"]:
        logging.debug("------------------------------------")
        logging.debug("ENDPOINT OUTPUT")
        logging.debug("------------------------------------")
        for out in endpoint_output:
            for line in out:
                logging.debug(line)

            logging.debug("------------------------------------")


def to_datetime(s):
    """Parse a datetime string from docker logs to a Python datetime object

    Args:
        s (str): Docker datetime string

    Returns:
        datetime: Python datetime object
    """
    s = s.split(" ")[0]
    s = s.replace("T", " ")

    # This + and Z business changes often. Now we're using this
    # It was (for +): s = s.replace("+", "")
    if "+" in s:
        s = s.split("+")[0]
    elif "Z" in s:
        s = s.split("Z")[0]

    s = s[: s.find(".") + 7]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


def baremetal(config, machines):
    """Launch a mist computing deployment

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    container_names_work = kubernetes.start_worker(config, machines, app_vars)

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    endpoint.wait_endpoint_completion(config, machines, config["cloud_ssh"], container_names_work)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = kubernetes.get_worker_output(config, machines, container_names_work)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def mist(config, machines):
    """Launch a mist computing deployment

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    container_names_work = kubernetes.start_worker(config, machines, app_vars)

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    endpoint.wait_endpoint_completion(config, machines, config["edge_ssh"], container_names_work)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = kubernetes.get_worker_output(config, machines, container_names_work)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def serverless(config, machines):
    """Launch a serverless deployment using Kubernetes + OpenFaaS

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    openfaas.start_worker(config, machines)

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)

    # Parse output into dicts, and print result
    print_raw_output(config, None, endpoint_output)
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, None, endpoint_metrics)


def endpoint_only(config, machines):
    """Launch a deployment with only endpoint machines / apps

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)

    # Parse output into dicts, and print result
    print_raw_output(config, None, endpoint_output)
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, None, endpoint_metrics)


def kube(config, machines):
    """Launch a K8 deployment, benchmarking K8's applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Cache the worker to prevent loading
    if config["benchmark"]["cache_worker"]:
        app_vars = config["module"]["application"].cache_worker(config, machines)
        kubernetes.cache_worker(config, machines, app_vars)

    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    kubernetes.start_worker(config, machines, app_vars)

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    kubernetes.wait_worker_completion(config, machines)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = kubernetes.get_worker_output(config, machines)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def kube_control(config, machines):
    """Launch a K8 deployment, benchmarking K8's controlplane instead of applications running on it

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the resource utilization metrics
    kubernetes.start_resource_metrics(config, machines)

    # Cache the worker to prevent loading
    if config["benchmark"]["cache_worker"]:
        app_vars = config["module"]["application"].cache_worker(config, machines)
        kubernetes.cache_worker(config, machines, app_vars)

    if config["benchmark"]["application"] == "mem_usage":
        config["module"]["application"].get_mem_usage(config, machines, kubernetes)

    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    starttime, kubectl_out, status = kubernetes.start_worker(
        config, machines, app_vars, get_starttime=True
    )

    # Wait for benchmark to finish
    kubernetes.wait_worker_completion(config, machines)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")

    worker_output = kubernetes.get_worker_output(config, machines)
    worker_description = kubernetes.get_worker_output(config, machines, get_description=True)

    control_output, endtime = kubernetes.get_control_output(config, machines, starttime, status)

    resource_output = kubernetes.get_resource_output(config, machines, starttime, endtime)

    # Add kubectl output
    node = config["cloud_ssh"][0].split("@")[0]
    control_output[node]["kubectl"] = kubectl_out

    if "runtime" in config["benchmark"] and "kata" in config["benchmark"]["runtime"]:
        if config["benchmark"]["application"] == "empty_kata":
            kata_ts = kube_kata.get_kata_timestamps(config, worker_output)
            config["module"]["application"].format_output(
                config,
                None,
                status=status,
                control=control_output,
                starttime=starttime,
                worker_output=worker_output,
                worker_description=worker_description,
                resource_output=resource_output,
                endtime=float(endtime - starttime),
                kata_ts=kata_ts,
            )
        elif config["benchmark"]["application"] == "stress":
            stress_dur = kube_kata.get_deployment_duration(config, machines)
            logging.info("Total stress duration: %s", stress_dur)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, [])

    config["module"]["application"].format_output(
        config,
        None,
        status=status,
        control=control_output,
        starttime=starttime,
        worker_output=worker_output,
        worker_description=worker_description,
        resource_output=resource_output,
        endtime=float(endtime - starttime),
    )
