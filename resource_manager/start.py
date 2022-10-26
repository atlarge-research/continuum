"""\
Select the correct resource manager, install required software and set them up.
"""

def start(config, machines):
    """Create and manage resource managers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    from .endpoint import start as endpoint

    if "resource_manager" in config["benchmark"]:
        if config["benchmark"]["resource_manager"] in ["kubeedge", "mist"]:
            from .kubeedge import start
        elif config["benchmark"]["resource_manager"] == "kubernetes":
            from .kubernetes import start

    # Install RM software on cloud/edge nodes
    if config["mode"] == "cloud" or config["mode"] == "edge":
        start.start(config, machines)

    if config["infrastructure"]["endpoint_nodes"]:
        # Start RM software on endpoints
        endpoint.start(config, machines)
