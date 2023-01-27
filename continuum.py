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

from application import application
from benchmark import benchmark
from configuration_parser import configuration_parser
from execution_model import execution_model
from infrastructure import infrastructure
from resource_manager import resource_manager


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


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    # TODO: Integrate this into add_options?
    if args.config["module"]["application"]:
        application.set_container_location(arguments.config)

    # TODO: Integrate this into the configuration_parser.py workflow
    configuration_parser.print_config(args.config)

    machines = infrastructure.start(args.config)

    if args.config["module"]["resource_manager"]:
        resource_manager.start(args.config, machines)

    if args.config["module"]["execution_model"]:
        execution_model.start(args.config, machines)

    if (
        not args.config["infrastructure"]["infra_only"]
        and not args.config["benchmark"]["resource_manager_only"]
    ):
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
