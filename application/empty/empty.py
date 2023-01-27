"""Manage the empty application"""

import logging
import sys

from configuration_parser import configuration_parser


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    source = "redplanet00/kubeedge-applications"
    config["images"] = {"worker": "%s:empty" % (source)}


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [["sleep_time", int, lambda x: x >= 1, True, False]]
    return settings


def verify_options(config):
    """Verify the config from the module's requirements

    Args:
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "empty":
        logging.error("ERROR: Application should be empty")
        sys.exit()
    elif config["benchmark"]["resource_manager"] != "kubernetes_control":
        logging.error("ERROR: Application empty requires resource_manager Kubernetes_control")
        sys.exit()
