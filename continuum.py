"""\
Entry file for the benchmark.
Parse the config file, and continue from there on.

Check the documentation and help for more information.
"""

import argparse
import os
import os.path
import sys
import logging
import time
import socket
import getpass
import importlib

from configuration_parser import configuration_parser
from infrastructure import infrastructure
from resource_manager import resource_manager
from benchmark import benchmark
from execution_model import execution_model


def make_wide(formatter, w=120, h=36):
    """Return a wider HelpFormatter

    Args:
        formatter (HelpFormatter): Format class for Python Argparse
        w (int, optional): Width of Argparse output. Defaults to 120.
        h (int, optional): Max help positions for Argparse output. Defaults to 36.

    Returns:
        formatter: Format class for Python Argparse, possibly with updated output sizes
    """
    try:
        kwargs = {"width": w, "max_help_position": h}
        formatter(None, **kwargs)
        return lambda prog: formatter(prog, **kwargs)
    except TypeError:
        print("Argparse help formatter failed, falling back.")
        return formatter


def set_logging(args):
    """Enable logging to both stdout and file (BENCHMARK_FOLDER/logs)
    If -v/--verbose is used, stdout will report logging.DEBUG, otherwise only logging.INFO
    The file will always use logging.DEBUG (which is the bigger scope)

    Args:
        args (Namespace): Argparse object
    """
    # Log to file parameters
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())

    if args.config["infrastructure"]["infra_only"]:
        log_name = "%s_infra_only.log" % (t)
    else:
        log_name = "%s_%s_%s.log" % (
            t,
            args.config["mode"],
            args.config["benchmark"]["application"],
        )

    file_handler = logging.FileHandler(log_dir + "/" + log_name)
    file_handler.setLevel(logging.DEBUG)

    # Log to stdout parameters
    stdout_handler = logging.StreamHandler(sys.stdout)
    if args.verbose:
        stdout_handler.setLevel(logging.DEBUG)
    else:
        stdout_handler.setLevel(logging.INFO)

    # Set parameters
    logging.basicConfig(
        format="[%(asctime)s %(pathname)s:%(lineno)s - %(funcName)s() ] %(message)s",
        level=logging.DEBUG,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[file_handler, stdout_handler],
    )

    logging.info("Logging has been enabled. Writing to stdout and file %s/%s", log_dir, log_name)


def dynamic_import(config):
    """Perform magic and dynamic imports to solve project dependencies
    Find an implementation for every used project component:
    - Infrastructure provider
    - Resource manager
    - Execution model
    - Application

    Args:
        config (dict): Parsed configuration
    """
    sys.path.append(os.path.abspath("."))

    config["module"] = {
        "provider": False,
        "resource_manager": False,
        "execution_model": False,
        "application": False,
    }

    # Check if infrastructure provider directory exists
    dirs = [d for d in os.walk("infrastructure")][0][1]
    dirs = [d for d in dirs if d[0] != "_"]
    if config["infrastructure"]["provider"] in dirs:
        config["module"]["provider"] = importlib.import_module(
            "infrastructure.%s.%s" % ((config["infrastructure"]["provider"],) * 2)
        )
    else:
        logging.error(
            "ERROR: Given provider %s does not have an implementation",
            config["infrastructure"]["provider"],
        )
        sys.exit()

    if not config["infrastructure"]["infra_only"]:
        # Check if resource manager directory exists
        # Not all RM have modules (e.g., mist, none)
        dirs = [d for d in os.walk("resource_manager")][0][1]
        dirs = [d for d in dirs if d[0] != "_"]
        if config["benchmark"]["resource_manager"] in dirs:
            config["module"]["resource_manager"] = importlib.import_module(
                "resource_manager.%s.%s" % ((config["benchmark"]["resource_manager"],) * 2)
            )
        elif config["benchmark"]["resource_manager"] == "mist":
            # Mist provider uses KubeEdge
            # TODO: Make a separate Mist provider
            #       Mist already has its own Ansible file, should be easy
            config["module"]["resource_manager"] = importlib.import_module(
                "resource_manager.%s.%s" % (("kubeedge",) * 2)
            )

        if "execution_model" in config:
            # Check if resource manager directory exists
            dirs = [d for d in os.walk("execution_model")][0][1]
            dirs = [d for d in dirs if d[0] != "_"]
            if config["execution_model"]["model"] in dirs:
                config["module"]["execution_model"] = importlib.import_module(
                    "execution_model.%s.%s" % ((config["execution_model"]["model"],) * 2)
                )
            else:
                logging.error(
                    "ERROR: Given execution model %s does not have an implementation",
                    config["execution_model"]["model"],
                )
                sys.exit()

        # Check if infrastructure provider directory exists
        dirs = [d for d in os.walk("application")][0][1]
        dirs = [d for d in dirs if d[0] != "_"]
        if config["benchmark"]["application"] in dirs:
            config["module"]["application"] = importlib.import_module(
                "application.%s.%s" % ((config["benchmark"]["application"],) * 2)
            )
        else:
            logging.error(
                "ERROR: Given application %s does not have an implementation",
                config["benchmark"]["application"],
            )
            sys.exit()


def add_constants(config):
    """Add some constants to the config dict

    Args:
        config (dict): Parsed configuration
    """
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))
    config["username"] = getpass.getuser()
    config["ssh_key"] = os.path.join(config["home"], ".ssh/id_rsa_continuum")

    # 100.100.100.100
    # Prefix .Mid.Post
    config["postfixIP_lower"] = 2
    config["postfixIP_upper"] = 252

    # Get Docker registry IP
    if not config["infrastructure"]["infra_only"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]
        except socket.gaierror as e:
            logging.error("Could not get host ip with error: %s", e)
            sys.exit()

        config["registry"] = host_ip + ":5000"


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    dynamic_import(arguments.config)

    add_constants(arguments.config)
    benchmark.set_container_location(arguments.config)
    configuration_parser.print_config(args.config)

    machines = infrastructure.start(args.config)

    if not args.config["infrastructure"]["infra_only"]:
        if args.config["module"]["resource_manager"]:
            resource_manager.start(args.config, machines)

        if args.config["module"]["execution_model"]:
            execution_model.start(args.config, machines)

        if not args.config["benchmark"]["resource_manager_only"]:
            benchmark.start(args.config, machines)

    if args.config["infrastructure"]["delete"]:
        infrastructure.delete_vms(args.config, machines)
        logging.info("Finished\n")
    else:
        s = []
        for ssh in args.config["cloud_ssh"] + args.config["edge_ssh"] + args.config["endpoint_ssh"]:
            s.append("ssh %s -i %s" % (ssh, args.config["ssh_key"]))

        logging.info("To access the VMs:\n\t%s\n", "\n\t".join(s))


if __name__ == "__main__":
    # Get input arguments, and validate those arguments
    parser_obj = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500)
    )

    parser_obj.add_argument(
        "config",
        type=lambda x: configuration_parser.start(parser_obj, x),
        help="benchmark config file",
    )
    parser_obj.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")

    arguments = parser_obj.parse_args()

    # Set loggers
    set_logging(arguments)

    main(arguments)
