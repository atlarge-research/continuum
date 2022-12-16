"""\
Select the correct resource manager, install required software and set them up.
"""

from .kubeedge import start as edge
from .kubernetes import start as cloud
from .endpoint import start as endpoint


def start(config, machines):
    """Create and manage resource managers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Install RM software on cloud/edge nodes
    if "resource_manager" in config["benchmark"]:
        if config["benchmark"]["resource_manager"] in ["kubeedge", "mist"]:
            edge.start(config, machines)
        elif config["benchmark"]["resource_manager"] == "kubernetes":
            cloud.start(config, machines)

    # Start RM software on endpoints
    if config["infrastructure"]["endpoint_nodes"]:
        endpoint.start(config, machines)
