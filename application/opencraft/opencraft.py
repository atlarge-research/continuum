"""Manage the OpenCraft application"""


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    # TODO update container location
    # TODO all apps are assumed to be deployed as Kubernetes jobs, not anything else
    source = "redplanet00/kubeedge-applications"
    config["images"] = {
        "worker_client": "%s:empty" % (source),
        "worker_renderer": "%s:empty" % (source),
        "worker_server": "%s:empty" % (source),
        "worker_monitor": "%s:empty" % (source),
        "worker_scheduler": "%s:empty" % (source),
    }


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # TODO update app-specific parameters
    # TODO add the parameters to a config file
    # TODO update the launch_benchmark_kubernetes_*.yml files to pass the parameters to the app
    settings = [
        ["sleep_time", int, lambda x: x >= 1, True, False],
    ]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "opencraft":
        parser.error("ERROR: Application should be opencraft")
    elif config["benchmark"]["resource_manager"] != "kubernetes":
        parser.error("ERROR: Application opencraft requires resource_manager kubernetes")
    # TODO add parameter verifications with the app and options from add_options


def cache_worker(_config, _machines):
    """Set variables needed when launching the app for caching

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    # TODO update variables. Should be in line with add_options()
    app_vars = {
        "sleep_time": 15,
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
        "sleep_time": config["benchmark"]["sleep_time"],
    }
    return app_vars


def gather_worker_metrics(_machines, _config, worker_output, _starttime):
    """Gather metrics from cloud workers

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        starttime (datetime): Time that 'kubectl apply' is called to launche the benchmark

    Returns:
        list(dict): List of parsed output for each cloud workers
    """
    pass


def gather_endpoint_metrics(config, endpoint_output, container_names):
    """Gather metrics from endpoints
    NOT USED

    Args:
        config (dict): Parsed configuration
        endpoint_output (list(list(str))): Output of each endpoint container
        container_names (list(str)): Names of docker containers launched

    Returns:
        list(dict): List of parsed output for each endpoint
    """
    pass


def format_output(config, worker_metrics, endpoint_metrics, status=None):
    """Format processed output to provide useful insights

    Args:
        config (dict): Parsed configuration
        sub_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
    """
    pass
