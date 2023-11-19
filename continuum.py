"""\
Entry file for the benchmark.
Parse the config file, and continue from there on.

Check the documentation and help for more information.
"""

import argparse
import logging
import os
import os.path
import sys
import time

import settings

# pylint: disable-next=redefined-builtin
from infrastructure import infrastructure
from input_parser import input_parser
from software import software
from workload import workload

sys.path.append(os.path.abspath(".."))


def _make_wide(formatter, w=120, h=36):
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


def _set_logging(args):
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

    if settings.config["infrastructure"]["infra_only"]:
        log_name = "%s_infra_only.log" % t
    elif settings.config["benchmark"]["resource_manager_only"]:
        log_name = "%s_%s_%s.log" % (
            t,
            settings.config["mode"],
            settings.config["benchmark"]["resource_manager"],
        )
    else:
        log_name = "%s_%s_%s_%s.log" % (
            t,
            settings.config["mode"],
            settings.config["benchmark"]["resource_manager"],
            settings.config["benchmark"]["application"],
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
    # noinspection SpellCheckingInspection
    logging.basicConfig(
        format="[%(asctime)s %(pathname)s:%(lineno)s - %(funcName)s() ] %(message)s",
        level=logging.DEBUG,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[file_handler, stdout_handler],
    )

    logging.info("Logging has been enabled. Writing to stdout and file %s/%s", log_dir, log_name)
    return t


def _main():
    """Main control function of the framework"""
    infrastructure.start()
    if settings.get_packages():
        software.start()
    if settings.get_benchmark():
        workload.start()

    # Post execution hooks (if providers/packages/benchmark has something to say)
    infrastructure.finish()
    if settings.get_packages():
        software.finish()
    if settings.get_benchmark():
        workload.finish()

    if settings.config["delete"]:
        for provider in settings.get_providers(flat=True):
            provider["interface"].delete_vms()

        logging.info("Finished - deleted all resources\n")
    else:
        pass
    # else:
    #     s = []
    #     for layer in settings.get_layers():
    #         key = settings.get_ssh_keys(layer_name=layer)[0]
    #         for ssh in settings.get_sshs(layer_name=layer):
    #             s.append("ssh %s -i %s" % (ssh, key))

    #     logging.info("To access the VMs:\n\t%s\n", "\n\t".join(s))

    #     if settings.get_benchmark() and
    #     if "benchmark" in settings.config and settings.config["benchmark"]["observability"]:
    #         logging.info(
    #             "To access Grafana: ssh -L 3000:%s:3000 %s -i %s",
    #             settings.config["cloud_ips"][0],
    #             settings.config["cloud_ssh"][0],
    #             settings.config["ssh_key"],
    #         )
    #         logging.info(
    #             "To access Prometheus: ssh -L 9090:%s:9090 %s -i %s",
    #             settings.config["cloud_ips"][0],
    #             settings.config["cloud_ssh"][0],
    #             settings.config["ssh_key"],
    #         )


if __name__ == "__main__":
    # Get input arguments, and validate those arguments
    # noinspection PyTypeChecker
    parser_obj = argparse.ArgumentParser(
        formatter_class=_make_wide(argparse.HelpFormatter, w=120, h=500)
    )
    parser_obj.add_argument(
        "config",
        type=lambda x: input_parser.start(parser_obj, x),
        help="benchmark config file",
    )
    parser_obj.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    arguments = parser_obj.parse_args()

    timestamp = _set_logging(arguments)
    settings.config["timestamp"] = timestamp

    input_parser.print_input()

    _main()
