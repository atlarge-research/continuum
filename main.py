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

import infrastructure.start as infrastructure
import resource_manager.start as resource_manager
import benchmark.start as benchmark


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
    parser, config, new, section, option, intype, condition, mandatory=True
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
                "Config: Invalid type for option %s->%s, expected %s"
                % (section, option, intype)
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
        option_check(
            parser, config, new, sec, "infra_only", bool, lambda x: x in [True, False]
        )
        option_check(parser, config, new, sec, "cloud_nodes", int, lambda x: x >= 0)
        option_check(parser, config, new, sec, "edge_nodes", int, lambda x: x >= 0)
        option_check(parser, config, new, sec, "endpoint_nodes", int, lambda x: x >= 0)

        if new[sec]["cloud_nodes"] > 0:
            option_check(parser, config, new, sec, "cloud_cores", int, lambda x: x >= 2)
            new[sec]["cloud_memory"] = new[sec]["cloud_cores"]
            option_check(
                parser,
                config,
                new,
                sec,
                "cloud_memory",
                int,
                lambda x: x >= 1,
                mandatory=False,
            )
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
            new[sec]["cloud_cores"] = 0
            new[sec]["cloud_memory"] = 0
            new[sec]["cloud_quota"] = 0.0

        if new[sec]["edge_nodes"] > 0:
            option_check(parser, config, new, sec, "edge_cores", int, lambda x: x >= 1)
            new[sec]["edge_memory"] = new[sec]["edge_cores"]
            option_check(
                parser,
                config,
                new,
                sec,
                "edge_memory",
                int,
                lambda x: x >= 1,
                mandatory=False,
            )
            option_check(
                parser, config, new, sec, "edge_quota", float, lambda x: 0.1 <= x <= 1.0
            )
        else:
            new[sec]["edge_cores"] = 0
            new[sec]["edge_memory"] = 0
            new[sec]["edge_quota"] = 0.0

        if new[sec]["endpoint_nodes"] > 0:
            option_check(
                parser, config, new, sec, "endpoint_cores", int, lambda x: x >= 1
            )
            new[sec]["endpoint_memory"] = new[sec]["endpoint_cores"]
            option_check(
                parser,
                config,
                new,
                sec,
                "endpoint_memory",
                int,
                lambda x: x >= 1,
                mandatory=False,
            )
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
            new[sec]["endpoint_cores"] = 0
            new[sec]["endpoint_memory"] = 0
            new[sec]["endpoint_quota"] = 0.0

        option_check(
            parser, config, new, sec, "cpu_pin", bool, lambda x: x in [True, False]
        )

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
        option_check(
            parser, config, new, sec, "netperf", bool, lambda x: x in [True, False]
        )
    else:
        parser.error("Config: infrastructure section missing")

    # Total number of nodes > 0
    cloud = new[sec]["cloud_nodes"]
    edge = new[sec]["edge_nodes"]
    endpoint = new[sec]["endpoint_nodes"]
    if cloud + edge + endpoint == 0:
        parser.error(
            "Config: number of cloud+edge+endpoint nodes should be >= 1, not 0"
        )

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
        option_check(
            parser, config, new, sec, "docker_pull", bool, lambda x: x in [True, False]
        )
        option_check(
            parser, config, new, sec, "delete", bool, lambda x: x in [True, False]
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application",
            str,
            lambda x: x in ["image_classification", "empty"],
        )

        # Set default values first
        new["benchmark"]["application_worker_cpu"] = float(
            new["infrastructure"]["cloud_cores"] - 0.5
        )
        new["benchmark"]["application_worker_memory"] = float(
            new["infrastructure"]["cloud_cores"] - 0.5
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application_worker_cpu",
            float,
            lambda x: x >= 0.1,
            mandatory=False,
        )
        option_check(
            parser,
            config,
            new,
            sec,
            "application_worker_memory",
            float,
            lambda x: x >= 0.1,
            mandatory=False,
        )

        if new["infrastructure"]["endpoint_nodes"] > 0:
            new["benchmark"]["application_endpoint_cpu"] = float(
                new["infrastructure"]["endpoint_cores"]
            )
            new["benchmark"]["application_endpoint_memory"] = float(
                new["infrastructure"]["endpoint_cores"]
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "application_endpoint_cpu",
                float,
                lambda x: x >= 0.1,
                mandatory=False,
            )
            option_check(
                parser,
                config,
                new,
                sec,
                "application_endpoint_memory",
                float,
                lambda x: x >= 0.1,
                mandatory=False,
            )

        new["benchmark"]["applications_per_worker"] = 1
        option_check(
            parser,
            config,
            new,
            sec,
            "applications_per_worker",
            int,
            lambda x: x >= 1,
            mandatory=False,
        )

        if new["benchmark"]["application"] == "image_classification":
            option_check(parser, config, new, sec, "frequency", int, lambda x: x >= 1)
        elif new["benchmark"]["application"] == "empty":
            option_check(parser, config, new, sec, "sleep_time", int, lambda x: x >= 1)

        # Set mode
        mode = "endpoint"
        if edge:
            mode = "edge"
        elif cloud:
            mode = "cloud"

        new["mode"] = mode

        # Check if mode and resource manager overlaps
        if "resource_manager" in new[sec]:
            if mode == "cloud" and not (
                new["benchmark"]["resource_manager"] in ["kubernetes"]
            ):
                parser.error("Config: Cloud-mode requires Kubernetes")
            elif mode == "edge" and not (
                new["benchmark"]["resource_manager"] in ["kubeedge", "mist"]
            ):
                parser.error("Config: Edge-mode requires KubeEdge or Mist")
        elif mode != "endpoint":
            parser.error("Config: Endpoint-only mode doesnt require resource managers")

        # Extended checks: Number of nodes should match deployment mode
        # For image_classification app
        if new["benchmark"]["application"] == "image_classification":
            if mode == "cloud" and (
                cloud < 2 or edge != 0 or endpoint == 0 or endpoint % (cloud - 1) != 0
            ):
                parser.error(
                    "Config: For image_classification + cloud benchmark, #clouds>1, #edges=0, #endpoints>0, and (#clouds-1) % #endpoints=0"
                )
            elif (
                mode == "edge"
                and new["benchmark"]["resource_manager"] == "kubeedge"
                and (cloud != 1 or edge == 0 or endpoint == 0 or endpoint % edge != 0)
            ):
                parser.error(
                    "Config: For image_classification + edge benchmark with KubeEdge, #clouds=1, #edges>0, #endpoints>0, and #edges % #endpoints=0"
                )
            elif (
                mode == "edge"
                and new["benchmark"]["resource_manager"] == "mist"
                and (cloud != 0 or edge == 0 or endpoint == 0 or endpoint % edge != 0)
            ):
                parser.error(
                    "Config: For image_classification + mist benchmarks, #clouds=0, #edges>0, #endpoints>0, and #edges % #endpoints=0"
                )
            elif mode == "endpoint" and (cloud != 0 or edge != 0 or endpoint == 0):
                parser.error(
                    "Config: For image_classification + endpoint benchmark, #clouds=0, #edges=0, and #endpoints>0"
                )
        elif new["benchmark"]["application"] == "empty":
            if mode != "cloud":
                parser.error(
                    "Config: For empty application, only cloud mode is supproted, #clouds>2, #edges=0, #endpoints=0"
                )
            elif cloud < 2 or edge != 0 or endpoint != 0:
                parser.error(
                    "Config: For empty + cloud benchmark, #clouds>2, #edges=0, #endpoints=0"
                )
    elif new["infrastructure"]["infra_only"] and config.has_section(sec):
        parser.error("Config: benchmark section is present but infra_only=True")

    return new


def add_constants(config):
    """Add some constants to the config dict

    Args:
        config (dict): Parsed configuration
    """
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))

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
    config["prefixIP"] = "192.168"
    config["middleIP"] = 100
    config["postfixIP_lower"] = 2
    config["postfixIP_upper"] = 252

    # Different IP range for base images
    config["middleIP_base"] = 90

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
        "Logging has been enabled. Writing to stdout and file at %s/%s"
        % (log_dir, log_name)
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
        benchmark.start(args.config, machines)

        if args.config["benchmark"]["delete"]:
            infrastructure.delete_vms(machines)
            print_ssh = False

    if print_ssh:
        s = []
        for ssh in (
            args.config["cloud_ssh"]
            + args.config["edge_ssh"]
            + args.config["endpoint_ssh"]
        ):
            s.append("ssh %s -i %s/.ssh/id_rsa_benchmark" % (ssh, args.config["home"]))

        logging.info("To access the VMs:\n\t" + "\n\t".join(s) + "\n")


if __name__ == "__main__":
    """Get input arguments, and validate those arguments"""
    parser = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500)
    )

    parser.add_argument(
        "config", type=lambda x: parse_config(parser, x), help="benchmark config file"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="increase verbosity level"
    )

    args = parser.parse_args()

    # Set loggers
    add_constants(args.config)
    set_logging(args)

    main(args)
