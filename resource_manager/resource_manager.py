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
    config["module"]["resource_manager"].start(config, machines)

    # Start RM software on endpoints
    if config["infrastructure"]["endpoint_nodes"]:
        endpoint.start(config, machines)
