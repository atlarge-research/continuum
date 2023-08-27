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
from execution_model import execution_model
from infrastructure import infrastructure
from resource_manager import resource_manager

# pylint: disable-next=redefined-builtin
from input import input


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

    Returns:
        (timestamp): Timestamp of the log file, used for all saved files
    """
    # Log to file parameters
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())

    if args.config["infrastructure"]["infra_only"]:
        log_name = "%s_infra_only.log" % (t)
    elif args.config["benchmark"]["resource_manager_only"]:
        log_name = "%s_%s_%s.log" % (
            t,
            args.config["mode"],
            args.config["benchmark"]["resource_manager"],
        )
    else:
        log_name = "%s_%s_%s_%s.log" % (
            t,
            args.config["mode"],
            args.config["benchmark"]["resource_manager"],
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
    return t


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    machines = infrastructure.start(args.config)

    resource_manager.start(args.config, machines)

    if args.config["module"]["execution_model"]:
        execution_model.start(args.config, machines)

    if args.config["module"]["application"]:
        application.start(args.config, machines)

    if args.config["infrastructure"]["delete"]:
        infrastructure.delete_vms(args.config, machines)
        logging.info("Finished\n")
    else:
        s = []
        for ssh in args.config["cloud_ssh"] + args.config["edge_ssh"] + args.config["endpoint_ssh"]:
            s.append("ssh %s -i %s" % (ssh, args.config["ssh_key"]))

        logging.info("To access the VMs:\n\t%s\n", "\n\t".join(s))

        if "benchmark" in args.config and args.config["benchmark"]["observability"]:
            logging.info(
                "To access Grafana: ssh -L 3000:%s:3000 %s -i %s",
                args.config["cloud_ips"][0],
                args.config["cloud_ssh"][0],
                args.config["ssh_key"],
            )
            logging.info(
                "To access Prometheus: ssh -L 9090:%s:9090 %s -i %s",
                args.config["cloud_ips"][0],
                args.config["cloud_ssh"][0],
                args.config["ssh_key"],
            )


if __name__ == "__main__":
    # Get input arguments, and validate those arguments
    parser_obj = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500)
    )

    parser_obj.add_argument(
        "config",
        type=lambda x: input.start(parser_obj, x),
        help="benchmark config file",
    )
    parser_obj.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")

    arguments = parser_obj.parse_args()

    timestamp = set_logging(arguments)
    arguments.config["timestamp"] = timestamp

    input.print_input(arguments.config)

    main(arguments)
