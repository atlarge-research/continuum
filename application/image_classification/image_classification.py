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
