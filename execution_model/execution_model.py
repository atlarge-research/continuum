"""Install a configured execution model on top of the infrastructure and resource manager"""


def start(config, machines):
    """Install execution model.
    Method selects a handler for every execution model there is.

    Args:
        config (dict): Parsed Configuration
        machines (List[Machine]): all physical machines available
    """
    config["module"]["execution_model"].start(config, machines)
