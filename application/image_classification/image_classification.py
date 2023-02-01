"""Manage the image_classification application"""


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    source = "redplanet00/kubeedge-applications"
    if "execution_model" in config and config["execution_model"]["model"] == "openFaas":
        # Serverless applications
        # Has no combined - does not make sense
        config["images"] = {
            "worker": "%s:image_classification_subscriber_serverless" % (source),
            "endpoint": "%s:image_classification_publisher_serverless" % (source),
        }
    else:
        # Container applications
        config["images"] = {
            "worker": "%s:image_classification_subscriber" % (source),
            "endpoint": "%s:image_classification_publisher" % (source),
            "combined": "%s:image_classification_combined" % (source),
        }


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [["frequency", int, lambda x: x >= 1, True, None]]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "image_classification":
        parser.error("ERROR: Application should be image_classification")


def baremetal(config, machines):
    """Launch a baremetal deployment, without any virtualized infrastructure, docker-only

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass
    # get_endpoint_output(config, machines, container_names, use_ssh=False)


def mist(config, machines):
    """Launch a mist computing deployment, with edge and endpoint machines, without any RM

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass


def serverless(config, machines):
    """Launch a serverless deployment, using for example OpenFaaS

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass


def endpoint_only(config, machines):
    """Launch a deployment with only endpoints, and no offloading between devices or RMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass


def kube(config, machines):
    """Launch a K8/kubeedge deployment, with possibly many cloud or edge workers, and endpoint users

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass


def kube_control(config, machines):
    """Launch a K8 deployment, benchmarking K8's controlplane instead of applications running on it

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    pass
