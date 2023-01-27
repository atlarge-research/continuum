"""Manage the image_classification application"""

import logging
import sys


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


def verify_options(config):
    """Verify the config from the module's requirements

    Args:
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "image_classification":
        logging.error("ERROR: Application should be image_classification")
        sys.exit()
