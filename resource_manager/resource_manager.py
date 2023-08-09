"""\
Select the correct resource manager, install required software and set them up.
"""

from .endpoint import endpoint


def start(config, machines):
    """Create and manage resource managers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Install software on cloud/edge nodes
    if config["module"]["resource_manager"]:
        config["module"]["resource_manager"].start(config, machines)

    # Start RM software on endpoints
    # Only when RM=none, otherwise it's a infra_only run and we don't do anything
    if config["infrastructure"]["endpoint_nodes"] and not config["infrastructure"]["infra_only"]:
        endpoint.start(config, machines)


def add_options(config):
    """[INTERFACE] Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object
    """
    return config["module"]["resource_manager"].add_options(config)


def verify_options(parser, config):
    """[INTERFACE] Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    config["module"]["resource_manager"].verify_options(parser, config)
