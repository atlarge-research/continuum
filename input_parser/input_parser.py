"""\
Handle any kind of input, such as configuration files or DSLs
"""

import os
import logging
import yaml

import settings

from .configuration import configuration_parser

# from .dsl import dsl_parser


def print_input():
    """Print the current configuration"""
    logging.debug("Configuration:")
    logging.debug("\n%s", yaml.dump(settings.config))


def start(parser, arg):
    """Parse a config or typescript file

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a config file

    Returns:
        configParser: Parsed config file
    """
    if not (os.path.exists(arg) and os.path.isfile(arg)):
        parser.error(f"The given config file does not exist: {arg}")

    _, file_extension = os.path.splitext(arg)
    if file_extension == ".yml":
        return configuration_parser.start(parser, arg)

    # if file_extension == ".ts":
    #     return dsl_parser.start(parser, arg)

    return parser.error("ERROR: Only extension .yml is supported, not %s", file_extension)
