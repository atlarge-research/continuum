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
import configparser
import socket
import getpass

import infrastructure.start as infrastructure
import resource_manager.start as resource_manager
import benchmark.start as benchmark
import execution_model.start as execution_model


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


def option_check(
    parser,
    config,
    new,
    section,
    option,
    intype,
    condition,
    mandatory=False,
    default="default",
):
    """Check if each config option is present, if the type is correct, and if the value is correct.

    Args:
        config (ConfigParser): ConfigParser object
        new (dict): Parsed configuration
        section (str): Section in the config file
        option (str): Option in a section of the config file
        intype (type): Option should be type
        condition (lambda): Option should have these values
        mandatory (bool, optional): Is option mandatory. Defaults to True.
    """
    if config.has_option(section, option):
        # If option is empty, but not mandatory, remove option
        if config[section][option] == "":
            if mandatory:
                parser.error("Config: Missing option %s->%s" % (section, option))
            elif default != "default":
                # Set default value if the user didnt set any
                new[section][option] = intype(default)

            return

        # Check type
        try:
            if intype == int:
                val = config[section].getint(option)
            elif intype == float:
                val = config[section].getfloat(option)
            elif intype == bool:
                val = config[section].getboolean(option)
            elif intype == str:
                val = config[section][option]
            elif intype == list:
                val = config[section][option].split(",")
                val = [s for s in val if s.strip()]
                if val == []:
                    return
            else:
                parser.error("Config: Invalid type %s" % (intype))
        except ValueError:
            parser.error(
                "Config: Invalid type for option %s->%s, expected %s" % (section, option, intype)
            )

        # Check value
        if not condition(val):
            parser.error("Config: Invalid value for option %s->%s" % (section, option))

        new[section][option] = val
    elif mandatory:
        parser.error("Config: Missing option %s->%s" % (section, option))
    else:
        # Set default value if the user didnt set any
        new[section][option] = intype(default)


def parse_config(parser, arg):
    """Parse config file, check valid input

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a config file

    Returns:
        configParser: Parsed config file
    """
    if not (os.path.exists(arg) and os.path.isfile(arg)):
        parser.error("The given config file does not exist: %s" % (arg))

    config = configparser.ConfigParser()
    config.read(arg)

    # Parsed values will be saved in a dict because ConfigParser can only hold strings
    new = {}

    sec = "infrastructure"
    if config.has_section(sec):
        new[sec] = {}
        option_check(
            parser,
            config,
            new,
            sec,
            "provider",
            str,
            lambda x: x in ["qemu"],
            mandatory=True,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "infra_only",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

        option_check(parser, config, new, sec, "cloud_nodes", int, lambda x: x >= 0, default=0)
        option_check(parser, config, new, sec, "edge_nodes", int, lambda x: x >= 0, default=0)
        option_check(parser, config, new, sec, "endpoint_nodes", int, lambda x: x >= 0, default=0)

        if new[sec]["cloud_nodes"] + new[sec]["edge_nodes"] + new[sec]["endpoint_nodes"] == 0:
            parser.error("Config: cloud_nodes + edge_nodes + endpoint_nodes should be > 0")

        # Set mode
        mode = "endpoint"
        if new[sec]["edge_nodes"]:
            mode = "edge"
        elif new[sec]["cloud_nodes"]:
            mode = "cloud"

        new["mode"] = mode

        # Set specs of VMs
        mandatory = False
        default = 0
        if new[sec]["cloud_nodes"] > 0:
            mandatory = True
            default = "default"

        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_cores",
            int,
            lambda x: x >= 2,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_memory",
            int,
            lambda x: x >= 1,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_quota",
            float,
            lambda x: 0.1 <= x <= 1.0,
            mandatory=mandatory,
            default=default,
        )

        mandatory = False
        default = 0
        if new[sec]["edge_nodes"] > 0:
            mandatory = True
            default = "default"

        option_check(
            parser,
            config,
            new,
            sec,
            "edge_cores",
            int,
            lambda x: x >= 1,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_memory",
            int,
            lambda x: x >= 1,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_quota",
            float,
            lambda x: 0.1 <= x <= 1.0,
            mandatory=mandatory,
            default=default,
        )

        mandatory = False
        default = 0
        if new[sec]["endpoint_nodes"] > 0:
            mandatory = True
            default = "default"

        option_check(
            parser,
            config,
            new,
            sec,
            "endpoint_cores",
            int,
            lambda x: x >= 1,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "endpoint_memory",
            int,
            lambda x: x >= 1,
            mandatory=mandatory,
            default=default,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "endpoint_quota",
            float,
            lambda x: 0.1 <= x <= 1.0,
            mandatory=mandatory,
            default=default,
        )

        # Now set disk speed
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_read_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_read_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "endpoint_read_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_write_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_write_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "endpoint_write_speed",
            int,
            lambda x: x >= 0,
            default=0,
        )

        # Pin VM cores in physical CPU cores
        option_check(
            parser,
            config,
            new,
            sec,
            "cpu_pin",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

        # Set network info
        option_check(
            parser,
            config,
            new,
            sec,
            "network_emulation",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

        # Only set detailed values if network_emulation = True
        if new[sec]["network_emulation"]:
            option_check(
                parser,
                config,
                new,
                sec,
                "wireless_network_preset",
                str,
                lambda x: x in ["4g", "5g"],
                default="4g",
            )

            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_latency_avg",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_latency_var",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_throughput",
                float,
                lambda x: x >= 1.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_latency_avg",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_latency_var",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_throughput",
                float,
                lambda x: x >= 1.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_edge_latency_avg",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_edge_latency_var",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_edge_throughput",
                float,
                lambda x: x >= 1.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_endpoint_latency_avg",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_endpoint_latency_var",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_endpoint_throughput",
                float,
                lambda x: x >= 1.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_endpoint_latency_avg",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_endpoint_latency_var",
                float,
                lambda x: x >= 0.0,
                default=-1,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_endpoint_throughput",
                float,
                lambda x: x >= 1.0,
                default=-1,
            )

        # Use multiple physical machines for the framework
        option_check(
            parser,
            config,
            new,
            sec,
            "external_physical_machines",
            list,
            lambda x: True,
            default=[],
        )

        # Benchmark the network between the VMs
        option_check(
            parser,
            config,
            new,
            sec,
            "netperf",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

        # Set the location where the continuum framework files are stored, including VMs
        option_check(
            parser,
            config,
            new,
            sec,
            "base_path",
            str,
            os.path.expanduser,
            default=os.getenv("HOME"),
        )

        new[sec]["base_path"] = os.path.expanduser(new[sec]["base_path"])
        if new[sec]["base_path"][-1] == "/":
            new[sec]["base_path"] = new[sec]["base_path"][:-1]

        # Set default IP range of created VMs
        option_check(
            parser,
            config,
            new,
            sec,
            "prefixIP",
            str,
            lambda x: len(x.split(".")) == 2
            and int(x.split(".")[0]) > 0
            and int(x.split(".")[0]) < 255
            and int(x.split(".")[1]) > 0
            and int(x.split(".")[1]) < 255,
            default="192.168",
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "middleIP",
            int,
            lambda x: 0 < x < 255,
            default="100",
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "middleIP_base",
            int,
            lambda x: 0 < x < 255,
            default="90",
        )

        if new[sec]["middleIP"] == new[sec]["middleIP_base"]:
            parser.error("Config: middleIP == middleIP_base")

        option_check(
            parser,
            config,
            new,
            sec,
            "delete",
            bool,
            lambda x: x in [True, False],
            default=False,
        )
    else:
        parser.error("Config: infrastructure section missing")

    # Check benchmark
    sec = "benchmark"
    if not new["infrastructure"]["infra_only"] and config.has_section(sec):
        new[sec] = {}
        option_check(
            parser,
            config,
            new,
            sec,
            "resource_manager",
            str,
            lambda x: x in ["kubernetes", "kubeedge", "mist", "none", "kubernetes-control"],
            mandatory=True,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "resource_manager_only",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "docker_pull",
            bool,
            lambda x: x in [True, False],
            default=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application",
            str,
            lambda x: x in ["image_classification", "empty"],
            mandatory=True,
        )

        # Set default values first
        default_cpu = 0.0
        default_mem = 0.0
        if mode == "cloud":
            default_cpu = new["infrastructure"]["cloud_cores"] - 0.5
            default_mem = new["infrastructure"]["cloud_memory"] - 0.5
        elif mode == "edge":
            default_cpu = new["infrastructure"]["edge_cores"] - 0.5
            default_mem = new["infrastructure"]["edge_memory"] - 0.5

        # Set specs of applications
        option_check(
            parser,
            config,
            new,
            sec,
            "application_worker_cpu",
            float,
            lambda x: x >= 0.1,
            default=default_cpu,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application_worker_memory",
            float,
            lambda x: x >= 0.1,
            default=default_mem,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "application_endpoint_cpu",
            float,
            lambda x: x >= 0.1,
            default=new["infrastructure"]["endpoint_cores"],
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application_endpoint_memory",
            float,
            lambda x: x >= 0.1,
            default=new["infrastructure"]["endpoint_memory"],
        )

        # Number of applications per worker
        option_check(
            parser,
            config,
            new,
            sec,
            "applications_per_worker",
            int,
            lambda x: x >= 1,
            default=1,
        )

        if new[sec]["application"] == "image_classification":
            option_check(
                parser,
                config,
                new,
                sec,
                "frequency",
                int,
                lambda x: x >= 1,
                mandatory=True,
            )
        elif new[sec]["application"] == "empty":
            option_check(
                parser,
                config,
                new,
                sec,
                "sleep_time",
                int,
                lambda x: x >= 1,
                mandatory=True,
            )

        option_check(
            parser,
            config,
            new,
            sec,
            "cache_worker",
            bool,
            lambda x: x in [True, False],
            default=False,
        )

    sec = "execution_model"
    if config.has_section(sec):
        new[sec] = {}
        option_check(
            parser,
            config,
            new,
            sec,
            "model",
            str,
            lambda x: x in ["openFaas"],
            mandatory=True,
        )

    return new


def add_constants(config):
    """Add some constants to the config dict

    Args:
        config (dict): Parsed configuration
    """
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))
    config["username"] = getpass.getuser()
    config["ssh_key"] = os.path.join(config["home"], ".ssh/id_rsa_benchmark")

    if not config["infrastructure"]["infra_only"]:
        if config["benchmark"]["application"] == "image_classification":
            config["images"] = {
                "worker": "redplanet00/kubeedge-applications:image_classification_subscriber",
                "endpoint": "redplanet00/kubeedge-applications:image_classification_publisher",
                "combined": "redplanet00/kubeedge-applications:image_classification_combined",
            }
        elif config["benchmark"]["application"] == "empty":
            config["images"] = {"worker": "redplanet00/kubeedge-applications:empty"}

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
        resource_manager.start(args.config, machines)
        if "execution_model" in args.config:
            execution_model.start(args.config, machines)

        if not args.config["benchmark"]["resource_manager_only"]:
            benchmark.start(args.config, machines)

    if args.config["infrastructure"]["delete"]:
        infrastructure.delete_vms(args.config, machines)
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
        type=lambda x: parse_config(parser_obj, x),
        help="benchmark config file",
    )
    parser_obj.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")

    arguments = parser_obj.parse_args()

    # Set loggers
    add_constants(arguments.config)
    set_logging(arguments)

    main(arguments)
