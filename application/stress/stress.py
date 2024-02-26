"""Manage the stress application"""

from ..empty.empty import print_resources
from ..empty.plot import plot_resources


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    config["images"] = {"worker": "ansk/empty:stress"}


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [
        ["stress_app_timeout", int, lambda x: x >= 1, True, False],
    ]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "stress":
        parser.error("ERROR: Application should be stress")
    elif config["benchmark"]["resource_manager"] != "kubecontrol":
        parser.error("ERROR: Application stress requires resource_manager kubecontrol")


def cache_worker(_config, _machines):
    """Set variables needed when launching the app for caching

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    app_vars = {
        "stress_app_timeout": 10,
    }
    return app_vars


def start_worker(config, _machines):
    """Set variables needed when launching the app on workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    app_vars = {
        "stress_app_timeout": config["benchmark"]["stress_app_timeout"],
    }
    return app_vars


def format_output(
    config,
    _worker_metrics,
    status=None,
    control=None,
    _starttime=None,
    _worker_output=None,
    _worker_description=None,
    resource_output=None,
    endtime=None,
    _kata_ts=None,
):
    """Format processed output to provide useful insights (empty)

    Args:
        config (dict): Parsed configuration
        worker_metrics (list(dict)): Metrics per worker node
        status (list(list(str)), optional): Status of started Kubernetes pods over time
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_output (list(list(str)), optional): Output of each container ran on the edge
        worker_description (list(list(str)), optional): Extensive description of each container
        endtime (str, optional): Timestamp of the slowest deployed pod
    """
    # Plot the status of each pod over time
    if status is not None:
        if control is not None:
            df_resources = print_resources(config, resource_output)
            plot_resources(df_resources, config["timestamp"], xmax=endtime)
