"""\
Select the correct resource manager, install required software and set them up.
"""

import settings


def start():
    """Create and manage resource managers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Install software on all layers, one by one
    for packages in settings.get_packages():
        for package in packages:
            package["interface"].start()


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


def finish():
    """Execute code or print information to users at the end of a Continuum run"""
    for packages in settings.get_packages():
        for package in packages:
            package["interface"].finish()
