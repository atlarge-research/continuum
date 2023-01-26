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

import configuration_parser.start as configuration_parser
import infrastructure.start as infrastructure
import resource_manager.start as resource_manager
import benchmark.start as benchmark
import execution_model.start as execution_model

# pylint: disable=unused-import
from infrastructure.qemu import start as qemu_vm
from infrastructure.terraform import start as terraform_vm

# pylint: enable=unused-import


def ansible_check_output(out):
    """Check if an Ansible Playbook succeeded or failed
    Shared by all files launching Ansible playbooks

    Args:
        output (list(str), list(str)): List of process stdout and stderr
    """
    output, error = out

    # Print summary of executioo times
    summary = False
    lines = [""]
    for line in output:
        if summary:
            lines.append(line.rstrip())

        if "==========" in line:
            summary = True

    if lines != [""]:
        logging.debug("\n".join(lines))

    # Check if executino was succesful
    if error != []:
        logging.error("".join(error))
        sys.exit()
    elif any("FAILED!" in out for out in output):
        logging.error("".join(output))
        sys.exit()


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


def add_constants(config):
    """Add some constants to the config dict

    Args:
        config (dict): Parsed configuration
    """
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))
    config["username"] = getpass.getuser()
    config["ssh_key"] = os.path.join(config["home"], ".ssh/id_rsa_continuum")

    source = "redplanet00/kubeedge-applications"
    if not config["infrastructure"]["infra_only"]:
        if config["benchmark"]["application"] == "image_classification":
            if "execution_model" in config and config["execution_model"]["model"] == "openFaas":
                config["images"] = {
                    "worker": "%s:image_classification_subscriber_serverless" % (source),
                    "endpoint": "%s:image_classification_publisher_serverless" % (source),
                    "combined": "%s:image_classification_combined" % (source),
                }
            else:
                config["images"] = {
                    "worker": "%s:image_classification_subscriber" % (source),
                    "endpoint": "%s:image_classification_publisher" % (source),
                    "combined": "%s:image_classification_combined" % (source),
                }
        elif config["benchmark"]["application"] == "empty":
            config["images"] = {"worker": "%s:empty" % (source)}

    # 100.100.100.100
    # Prefix .Mid.Post
    config["postfixIP_lower"] = 2
    config["postfixIP_upper"] = 252

    # Get Docker registry IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    except socket.gaierror as e:
        logging.error("Could not get host ip with error: %s", e)
        sys.exit()

    config["registry"] = host_ip + ":5000"


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

    s = []
    header = True
    for key, value in args.config.items():
        if isinstance(value, dict):
            s.append("[" + key + "]")
            category = dict(args.config[key])
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


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    machines = infrastructure.start(args.config)

    if not args.config["infrastructure"]["infra_only"]:
        # The baremetal provider doesn't install anything - it only deploys and benchmarks apps
        if not args.config["infrastructure"]["provider"] == "baremetal":
            resource_manager.start(args.config, machines)
            if "execution_model" in args.config:
                execution_model.start(args.config, machines)

        if not args.config["benchmark"]["resource_manager_only"]:
            benchmark.start(args.config, machines)

    if args.config["infrastructure"]["delete"]:
        vm = globals()["%s_vm" % (args.config["infrastructure"]["provider"])]
        vm.delete_vms(args.config, machines)
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
    add_constants(arguments.config)
    set_logging(arguments)

    main(arguments)
