"""\
Handle any kind of input, such as configuration files or DSLs
"""

import os
import logging

from .configuration import configuration_parser
from .dsl import dsl_parser


def print_input(config):
    """Print the current configuration

    Args:
        config (ConfigParser): ConfigParser object
    """
    logging.debug("Current config:")
    s = []
    header = True
    for key, value in config.items():
        if isinstance(value, dict):
            s.append("[" + key + "]")
            category = dict(config[key])
            for k, v in category.items():
                s.append("%-30s = %s" % (k, v))

            s.append("")
        else:
            if header:
                s.append("[constants]")
                header = False

            if isinstance(value, list):
                s.append("%-30s = %s" % (key, value[0]))
                if len(value) > 1:
                    for v in value[1:]:
                        s.append("%-30s   %s" % ("", v))
            else:
                s.append("%-30s = %s" % (key, value))

    logging.debug("\n%s", "\n".join(s))


def start(parser, arg):
    """Parse a config or typescript file

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a config file

    Returns:
        configParser: Parsed config file
    """
    if not (os.path.exists(arg) and os.path.isfile(arg)):
        parser.error("The given config file does not exist: %s" % (arg))

    _, file_extension = os.path.splitext(arg)
    if file_extension == ".cfg":
        return configuration_parser.start(parser, arg)

    if file_extension == ".ts":
        return dsl_parser.start(parser, arg)

    return parser.error("ERROR: Only extentions .cfg and .ts are supported, not %s", file_extension)
