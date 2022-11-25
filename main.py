"""\
Entry file for the benchmark.
Parse the config file, and continue from there on.

Check the documentation and help for more information.
"""

import argparse
import os.path
import sys
import logging
import os
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


def option_check(parser, config, new, section, option, intype, condition, mandatory=True):
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
    new = dict()

    sec = "infrastructure"
    if config.has_section(sec):
        new[sec] = dict()
        option_check(parser, config, new, sec, "provider", str, lambda x: x in ["qemu"])
        option_check(parser, config, new, sec, "infra_only", bool, lambda x: x in [True, False])
        option_check(parser, config, new, sec, "cloud_nodes", int, lambda x: x >= 0)
        option_check(parser, config, new, sec, "edge_nodes", int, lambda x: x >= 0)
        option_check(parser, config, new, sec, "endpoint_nodes", int, lambda x: x >= 0)

        # If no cloud nodes are given, it doesn't matter what their specifications are
        if new["infrastructure"]["cloud_nodes"] > 0:
            option_check(parser, config, new, sec, "cloud_cores", int, lambda x: x >= 2)
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_quota",
                float,
                lambda x: 0.1 <= x <= 1.0,
            )
        else:
            option_check(parser, config, new, sec, "cloud_cores", int, lambda x: x >= 0)
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_quota",
                float,
                lambda x: 0.0 <= x <= 1.0,
            )

        if new["infrastructure"]["edge_nodes"] > 0:
            option_check(parser, config, new, sec, "edge_cores", int, lambda x: x >= 1)
            option_check(parser, config, new, sec, "edge_quota", float, lambda x: 0.1 <= x <= 1.0)
        else:
            option_check(parser, config, new, sec, "edge_cores", int, lambda x: x >= 0)
            option_check(parser, config, new, sec, "edge_quota", float, lambda x: 0.0 <= x <= 1.0)

        if new["infrastructure"]["endpoint_nodes"] > 0:
            option_check(parser, config, new, sec, "endpoint_cores", int, lambda x: x >= 1)
            option_check(
                parser,
                config,
                new,
                sec,
                "endpoint_quota",
                float,
                lambda x: 0.1 <= x <= 1.0,
            )
        else:
            option_check(parser, config, new, sec, "endpoint_cores", int, lambda x: x >= 0)
            option_check(
                parser,
                config,
                new,
                sec,
                "endpoint_quota",
                float,
                lambda x: 0.0 <= x <= 1.0,
            )

        # Now set disk speed, first default values to 0
        new["infrastructure"]["cloud_read_speed"] = 0
        new["infrastructure"]["edge_read_speed"] = 0
        new["infrastructure"]["endpoint_read_speed"] = 0

        new["infrastructure"]["cloud_write_speed"] = 0
        new["infrastructure"]["edge_write_speed"] = 0
        new["infrastructure"]["endpoint_write_speed"] = 0

        option_check(
            parser, config, new, sec, "cloud_read_speed", int, lambda x: x >= 0, mandatory=False
        )
        option_check(
            parser, config, new, sec, "edge_read_speed", int, lambda x: x >= 0, mandatory=False
        )
        option_check(
            parser, config, new, sec, "endpoint_read_speed", int, lambda x: x >= 0, mandatory=False
        )

        option_check(
            parser, config, new, sec, "cloud_write_speed", int, lambda x: x >= 0, mandatory=False
        )
        option_check(
            parser, config, new, sec, "edge_write_speed", int, lambda x: x >= 0, mandatory=False
        )
        option_check(
            parser, config, new, sec, "endpoint_write_speed", int, lambda x: x >= 0, mandatory=False
        )

        option_check(parser, config, new, sec, "cpu_pin", bool, lambda x: x in [True, False])

        option_check(
            parser,
            config,
            new,
            sec,
            "network_emulation",
            bool,
            lambda x: x in [True, False],
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "wireless_network_preset",
            str,
            lambda x: x in ["4g", "5g"],
            mandatory=False,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_latency_avg",
            float,
            lambda x: x >= 5.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_latency_var",
            float,
            lambda x: x >= 0.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_throughput",
            float,
            lambda x: x >= 1.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_latency_avg",
            float,
            lambda x: x >= 5.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_latency_var",
            float,
            lambda x: x >= 0.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_throughput",
            float,
            lambda x: x >= 1.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_edge_latency_avg",
            float,
            lambda x: x >= 5.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_edge_latency_var",
            float,
            lambda x: x >= 0.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_edge_throughput",
            float,
            lambda x: x >= 1.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_endpoint_latency_avg",
            float,
            lambda x: x >= 5.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_endpoint_latency_var",
            float,
            lambda x: x >= 0.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "cloud_endpoint_throughput",
            float,
            lambda x: x >= 1.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_endpoint_latency_avg",
            float,
            lambda x: x >= 5.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_endpoint_latency_var",
            float,
            lambda x: x >= 0.0,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "edge_endpoint_throughput",
            float,
            lambda x: x >= 1.0,
            mandatory=False,
        )

        option_check(
            parser,
            config,
            new,
            sec,
            "external_physical_machines",
            list,
            lambda x: True,
            mandatory=False,
        )
        option_check(parser, config, new, sec, "netperf", bool, lambda x: x in [True, False])

        new["infrastructure"]["base_path"] = str(os.getenv("HOME"))
        option_check(
            parser,
            config,
            new,
            sec,
            "base_path",
            str,
            lambda x: os.path.expanduser(x),
            mandatory=False,
        )
        new["infrastructure"]["base_path"] = os.path.expanduser(new["infrastructure"]["base_path"])
        if new["infrastructure"]["base_path"][-1] == "/":
            new["infrastructure"]["base_path"] = config["infrastructure"]["base_path"][:-1]

        new["infrastructure"]["prefixIP"] = "192.168"
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
            mandatory=False,
        )

        new["infrastructure"]["middleIP"] = "100"
        option_check(
            parser, config, new, sec, "middleIP", int, lambda x: x > 0 and x < 255, mandatory=False
        )

        new["infrastructure"]["middleIP_base"] = "90"
        option_check(
            parser,
            config,
            new,
            sec,
            "middleIP_base",
            int,
            lambda x: x > 0 and x < 255,
            mandatory=False,
        )

        if new["infrastructure"]["middleIP"] == new["infrastructure"]["middleIP_base"]:
            parser.error("Config: middleIP == middleIP_base")
    else:
        parser.error("Config: infrastructure section missing")

    # Total number of nodes > 0
    cloud = new[sec]["cloud_nodes"]
    edge = new[sec]["edge_nodes"]
    endpoint = new[sec]["endpoint_nodes"]
    if cloud + edge + endpoint == 0:
        parser.error("Config: number of cloud+edge+endpoint nodes should be >= 1, not 0")

    # Check benchmark
    sec = "benchmark"
    if not new["infrastructure"]["infra_only"] and config.has_section(sec):
        new[sec] = dict()
        option_check(
            parser,
            config,
            new,
            sec,
            "resource_manager",
            str,
            lambda x: x in ["kubernetes", "kubeedge", "mist"],
            mandatory=False,
        )

        new["benchmark"]["resource_manager_only"] = False
        option_check(
            parser,
            config,
            new,
            sec,
            "resource_manager_only",
            bool,
            lambda x: x in [True, False],
            False,
        )

        option_check(parser, config, new, sec, "docker_pull", bool, lambda x: x in [True, False])
        option_check(parser, config, new, sec, "delete", bool, lambda x: x in [True, False])
        option_check(
            parser,
            config,
            new,
            sec,
            "application",
            str,
            lambda x: x in ["image_classification"],
        )
        option_check(parser, config, new, sec, "frequency", int, lambda x: x >= 1)

        # Set mode
        mode = "endpoint"
        if edge:
            mode = "edge"
        elif cloud:
            mode = "cloud"

        new["mode"] = mode

    sec = "execution_model"
    if config.has_section(sec):
        new[sec] = dict()
        option_check(parser, config, new, sec, "model", str, lambda x: x in ["openFaas"])

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
            config["images"] = [
                "redplanet00/kubeedge-applications:image_classification_subscriber",
                "redplanet00/kubeedge-applications:image_classification_publisher",
                "redplanet00/kubeedge-applications:image_classification_combined",
            ]

    # 100.100.100.100
    # Prefix .Mid.Post
    config["postfixIP_lower"] = 2
    config["postfixIP_upper"] = 252

    # Get Docker registry IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    except Exception as e:
        logging.error("Could not get host ip: %s" % (e))
        sys.exit()

    config["registry"] = host_ip + ":5000"


def shorten_filename(filename):
    f = os.path.split(filename)[1]
    return "%s~%s" % (f[:3], f[-16:]) if len(f) > 19 else f


def set_logging(args):
    """Enable logging to both stdout and file (BENCHMARK_FOLDER/logs)
    If the -v / --verbose option is used, stdout will report logging.DEBUG, otherwise only logging.INFO
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

    logging.info(
        "Logging has been enabled. Writing to stdout and file at %s/%s" % (log_dir, log_name)
    )

    s = []
    header = True
    for key, value in args.config.items():
        if type(value) is dict:
            s.append("[" + key + "]")
            for k, v in dict(args.config[key]).items():
                s.append("%-30s = %s" % (k, v))

            s.append("")
        else:
            if header:
                s.append("[constants]")
                header = False

            if type(value) is list:
                s.append("%-30s = %s" % (key, value[0]))
                if len(value) > 1:
                    for v in value[1:]:
                        s.append("%-30s   %s" % ("", v))
            else:
                s.append("%-30s = %s" % (key, value))

    logging.debug("\n" + "\n".join(s))


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    machines = infrastructure.start(args.config)
    print_ssh = True

    if not args.config["infrastructure"]["infra_only"]:
        resource_manager.start(args.config, machines)
        if "execution_model" in args.config:
            execution_model.start(args.config, machines)

        if not args.config["benchmark"]["resource_manager_only"]:
            benchmark.start(args.config, machines)

        if args.config["benchmark"]["delete"]:
            infrastructure.delete_vms(args.config, machines)
            print_ssh = False

    if print_ssh:
        s = []
        for ssh in args.config["cloud_ssh"] + args.config["edge_ssh"] + args.config["endpoint_ssh"]:
            s.append("ssh %s -i %s" % (ssh, args.config["ssh_key"]))

        logging.info("To access the VMs:\n\t" + "\n\t".join(s) + "\n")


if __name__ == "__main__":
    """Get input arguments, and validate those arguments"""
    parser = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500)
    )

    parser.add_argument(
        "config", type=lambda x: parse_config(parser, x), help="benchmark config file"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")

    args = parser.parse_args()

    # Set loggers
    add_constants(args.config)
    set_logging(args)

    main(args)
