"""\
Parse the input DSL
"""

import os
from subprocess import Popen, PIPE
import json

from application import application
from input.configuration.configuration_parser import (
    add_constants,
    dynamic_import,
    add_options,
    verify_options,
)


def start(parser, file_path):
    """Parse DSL file, check valid input

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a DSL file

    Returns:
        config: Parsed DSL file as a config
    """
    with Popen(["ts-node", file_path], stdout=PIPE, stderr=PIPE) as process:
        stdout, stderr = process.communicate()

    if len(stderr):
        parser.error(stderr.decode("utf-8"))

    try:
        config = json.loads(stdout.decode("utf-8"))
    except ValueError:
        parser.error(
            "Invalid Configuration provided. Make sure only one configuration outputs at a time"
        )

    if isinstance(config, list):
        parser.error("Executing a list of configurations is not available yet")

    dynamic_import(parser, config)
    add_constants(parser, config)

    # Bit sketchy - we can't compare against the original input, we just use the output
    # TODO: Needs further testing to see if it actually catches all errors
    add_options(parser, config, config)

    verify_options(parser, config)

    if config["module"]["application"]:
        # Add the location of the application container image
        # Required here, for possible integration during infrastructure phase
        application.set_container_location(config)

    config["infrastructure"]["base_path"] = os.path.expanduser(
        config["infrastructure"]["base_path"]
    )

    return config
