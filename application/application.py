"""\
Manage applicaiton logic in the framework
Mostly used for calling specific application code
"""

import logging


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


def baremetal(config, machines):
    # Deploy cloud/edge workers
    if config["mode"] == "cloud" or config["mode"] == "edge":
        containers_worker = start_worker_baremetal(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint_baremetal(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)

    if config["mode"] == "cloud" or config["mode"] == "edge":
        wait_endpoint_completion(config, machines, config["cloud_ssh"], containers_worker)


def mist(config, machines):
    if config["mode"] == "cloud" or config["mode"] == "edge":
        containers_worker = start_worker_mist(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)

    if config["mode"] == "cloud" or config["mode"] == "edge":
        wait_endpoint_completion(config, machines, config["edge_ssh"], containers_worker)


def serverless(config, machines):
    if config["mode"] == "cloud" or config["mode"] == "edge":
        start_worker_serverless(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)


def endpoint_only(config, machines):
    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)


def kube(config, machines):
    if config["mode"] == "cloud" or config["mode"] == "edge":
        if config["benchmark"]["cache_worker"]:
            cache_worker(config, machines)

        start_worker(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)


def kube_control(config, machines):
    if config["mode"] == "cloud" or config["mode"] == "edge":
        if config["benchmark"]["cache_worker"]:
            cache_worker(config, machines)

        starttime = start_worker(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        container_endpoint = start_endpoint(config, machines)
        wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_endpoint)


def start(config, machines):
    # Determine deployment options:
    # TODO: Move this to RM code, or for the non-RM deployments to application specific(?)
    if config["infrastructure"]["provider"] == "baremetal":
        baremetal(config, machines)
    elif config["benchmark"]["resource_manager"] == "mist":
        mist(config, machines)
    elif config["module"]["execution_model"] and config["execution_model"]["model"] == "openFaas":
        serverless(config, machines)
    elif config["benchmark"]["resource_manager"] == "none":
        endpoint_only(config, machines)
    elif config["benchmark"]["resource_manager"] in ["kubernetes", "kubeedge"]:
        kube(config, machines)
    elif config["benchmark"]["resource_manager"] == "kubernetes_control":
        kube_control(config, machines)
    else:
        logging.error("ERROR: Don't have a deployment for this resource manager / application")

    # Start the worker
    # Start the endpoint
    # Wait for the endpoint to finish
    # Wait for the worker to finish
    # Get output
    # Process output

    # Determine what application we're deploying
    config["module"]["application"].start(config, machines)
