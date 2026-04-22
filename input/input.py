"""\
Handle any kind of input, such as configuration files or DSLs
"""

import logging
import os

from .configuration import yaml_parser


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
    """Parse a YAML experiment config file.

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a config file

    Returns:
        configParser: Parsed config file
    """
    if not (os.path.exists(arg) and os.path.isfile(arg)):
        parser.error("The given config file does not exist: %s" % (arg))

    _, file_extension = os.path.splitext(arg)
    if file_extension in (".yaml", ".yml"):
        return yaml_parser.start(parser, arg)

    if file_extension in (".cfg", ".ts"):
        return parser.error(
            "ERROR: Legacy input formats are no longer supported. "
            "Use YAML experiment configs (.yaml/.yml). Got %s" % (file_extension)
        )
    return parser.error(
        "ERROR: Only extensions .yaml/.yml are supported, not %s" % (file_extension)
    )
