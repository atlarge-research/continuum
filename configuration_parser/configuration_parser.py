"""Parse the imput configuration"""

import configparser
import os
import sys
import logging


def print_config(config):
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


def option_check(
    parser,
    config,
    new,
    section,
    option,
    intype,
    condition,
    mandatory,
    default,
):
    """Check if each config option is present, if the type is correct, and if the value is correct.

    Args:
        config (ConfigParser): ConfigParser object
        new (dict): Parsed configuration
        section (str): Section in the config file
        option (str): Option in a section of the config file
        intype (type): Option should be type
        condition (lambda): Option should have these values
        mandatory (bool): Is option mandatory
        default (bool): Default value if none is set
    """
    if config.has_option(section, option):
        # If option is empty, but not mandatory, remove option
        if config[section][option] == "":
            if mandatory:
                parser.error("Config: Missing option %s->%s" % (section, option))

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


def infrastructure(parser, config, new):
    """Parse config file, section infrastructure

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        new (dict): Parsed configuration for Continuum
    """
    sec = "infrastructure"
    if not config.has_section(sec):
        parser.error("Config: infrastructure section missing")
        sys.exit()

    new[sec] = {}

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["provider", str, lambda x: x in ["qemu", "terraform", "baremetal"], True, None],
        ["infra_only", bool, lambda x: x in [True, False], False, False],
        ["cloud_nodes", int, lambda x: x >= 0, False, 0],
        ["edge_nodes", int, lambda x: x >= 0, False, 0],
        ["endpoint_nodes", int, lambda x: x >= 0, False, 0],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

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
        default = None

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["cloud_cores", int, lambda x: x > 0, mandatory, default],
        ["cloud_memory", int, lambda x: x > 0, mandatory, default],
        ["cloud_quota", int, lambda x: 0.1 <= x <= 1.0, mandatory, default],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    mandatory = False
    default = 0
    if new[sec]["edge_nodes"] > 0:
        mandatory = True
        default = None

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["edge_cores", int, lambda x: x > 0, mandatory, default],
        ["edge_memory", int, lambda x: x > 0, mandatory, default],
        ["edge_quota", int, lambda x: 0.1 <= x <= 1.0, mandatory, default],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    mandatory = False
    default = 0
    if new[sec]["endpoint_nodes"] > 0:
        mandatory = True
        default = None

    l_prefixip = (
        lambda x: len(x.split(".")) == 2
        and int(x.split(".")[0]) > 0
        and int(x.split(".")[0]) < 255
        and int(x.split(".")[1]) > 0
        and int(x.split(".")[1]) < 255
    )

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["endpoint_cores", int, lambda x: x > 0, mandatory, default],
        ["endpoint_memory", int, lambda x: x > 0, mandatory, default],
        ["endpoint_quota", int, lambda x: 0.1 <= x <= 1.0, mandatory, default],
        ["cloud_read_speed", int, lambda x: x >= 0, False, 0],
        ["edge_read_speed", int, lambda x: x >= 0, False, 0],
        ["endpoint_read_speed", int, lambda x: x >= 0, False, 0],
        ["cloud_write_speed", int, lambda x: x >= 0, False, 0],
        ["edge_write_speed", int, lambda x: x >= 0, False, 0],
        ["endpoint_write_speed", int, lambda x: x >= 0, False, 0],
        ["cpu_pin", bool, lambda x: x in [True, False], False, False],
        ["external_physical_machines", list, lambda x: True, False, []],
        ["netperf", bool, lambda x: x in [True, False], False, False],
        ["base_path", str, os.path.expanduser, False, os.getenv("HOME")],
        ["prefixIP", str, l_prefixip, False, "192.168"],
        ["middleIP", int, lambda x: 0 < x < 255, False, "100"],
        ["middleIP_base", int, lambda x: 0 < x < 255, False, "90"],
        ["delete", bool, lambda x: x in [True, False], False, False],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    new[sec]["base_path"] = os.path.expanduser(new[sec]["base_path"])
    if new[sec]["base_path"][-1] == "/":
        new[sec]["base_path"] = new[sec]["base_path"][:-1]

    if new[sec]["middleIP"] == new[sec]["middleIP_base"]:
        parser.error("Config: middleIP == middleIP_base")


def infrastructure_network(parser, config, new):
    """Parse config file, section infrastructure, network part

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        new (dict): Parsed configuration for Continuum
    """
    sec = "infrastructure"
    if not config.has_section(sec):
        parser.error("Config: infrastructure section missing")
        sys.exit()

    option_check(
        parser,
        config,
        new,
        sec,
        "network_emulation",
        bool,
        lambda x: x in [True, False],
        False,
        False,
    )

    # Only set detailed values if network_emulation = True
    if not new[sec]["network_emulation"]:
        return

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["wireless_network_preset", str, lambda x: x in ["4g", "5g"], False, "4g"],
        ["cloud_latency_avg", float, lambda x: x >= 0.0, False, -1],
        ["cloud_latency_var", float, lambda x: x >= 0.0, False, -1],
        ["cloud_throughput", float, lambda x: x >= 1.0, False, -1],
        ["edge_latency_avg", float, lambda x: x >= 0.0, False, -1],
        ["edge_latency_var", float, lambda x: x >= 0.0, False, -1],
        ["edge_throughput", float, lambda x: x >= 1.0, False, -1],
        ["cloud_edge_latency_avg", float, lambda x: x >= 0.0, False, -1],
        ["cloud_edge_latency_var", float, lambda x: x >= 0.0, False, -1],
        ["cloud_edge_throughput", float, lambda x: x >= 1.0, False, -1],
        ["cloud_endpoint_latency_avg", float, lambda x: x >= 0.0, False, -1],
        ["cloud_endpoint_latency_var", float, lambda x: x >= 0.0, False, -1],
        ["cloud_endpoint_throughput", float, lambda x: x >= 1.0, False, -1],
        ["edge_endpoint_latency_avg", float, lambda x: x >= 0.0, False, -1],
        ["edge_endpoint_latency_var", float, lambda x: x >= 0.0, False, -1],
        ["edge_endpoint_throughput", float, lambda x: x >= 1.0, False, -1],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])


def infrastructure_terraform(parser, config, new):
    """Parse config file, section infrastructure, Terraform part

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        new (dict): Parsed configuration for Continuum
    """
    sec = "infrastructure"
    if not config.has_section(sec):
        parser.error("Config: infrastructure section missing")
        sys.exit()

    # Only set GCP values if Terraform is the provider
    if new["infrastructure"]["provider"] != "terraform":
        return

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["gcp_cloud", str, lambda _: True, new["infrastructure"]["cloud_nodes"] > 0, None],
        ["gcp_edge", str, lambda _: True, new["infrastructure"]["edge_nodes"] > 0, None],
        ["gcp_endpoint", str, lambda _: True, new["infrastructure"]["endpoint_nodes"] > 0, None],
        ["gcp_region", str, lambda _: True, True, None],
        ["gcp_zone", str, lambda _: True, True, None],
        ["gcp_project", str, lambda _: True, True, None],
        ["gcp_credentials", str, os.path.expanduser, True, None],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    if len(new[sec]["gcp_credentials"]) > 0 and new[sec]["gcp_credentials"][-1] == "/":
        new[sec]["gcp_credentials"] = new[sec]["base_pgcp_credentialsth"][:-1]


def benchmark(parser, config, new):
    """Parse config file, section benchmark

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        new (dict): Parsed configuration for Continuum
    """
    if new["infrastructure"]["infra_only"]:
        return

    sec = "benchmark"
    if not config.has_section(sec):
        parser.error("Config: benchmark section missing while infra_only=False")
        sys.exit()

    new[sec] = {}

    l_resource_manager = lambda x: x in [
        "kubernetes",
        "kubeedge",
        "mist",
        "none",
        "kubernetes-control",
    ]

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["resource_manager", str, l_resource_manager, True, None],
        ["resource_manager_only", bool, lambda x: x in [True, False], False, None],
        ["docker_pull", bool, lambda x: x in [True, False], False, None],
        ["application", str, lambda x: x in ["image_classification", "empty"], True, None],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    # Set default values first
    default_cpu = 0.0
    default_mem = 0.0
    if new["mode"] == "cloud":
        default_cpu = new["infrastructure"]["cloud_cores"] - 0.5
        default_mem = new["infrastructure"]["cloud_memory"] - 0.5
    elif new["mode"] == "edge":
        default_cpu = new["infrastructure"]["edge_cores"] - 0.5
        default_mem = new["infrastructure"]["edge_memory"] - 0.5

    ec = new["infrastructure"]["endpoint_cores"]
    em = new["infrastructure"]["endpoint_memory"]

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["application_worker_cpu", float, lambda x: x >= 0.1, False, default_cpu],
        ["application_worker_memory", float, lambda x: x >= 0.1, False, default_mem],
        ["application_endpoint_cpu", float, lambda x: x >= 0.1, False, ec],
        ["application_endpoint_memory", float, lambda x: x >= 0.1, False, em],
        ["applications_per_worker", int, lambda x: x >= 1, False, 1],
        ["cache_worker", bool, lambda x: x in [True, False], False, False],
        ["observability", bool, lambda x: x in [True, False], False, False],
    ]

    for s in settings:
        option_check(parser, config, new, sec, s[0], s[1], s[2], s[3], s[4])

    if new[sec]["application"] == "image_classification":
        option_check(parser, config, new, sec, "frequency", int, lambda x: x >= 1, True, None)
    elif new[sec]["application"] == "empty":
        option_check(parser, config, new, sec, "sleep_time", int, lambda x: x >= 1, True, False)


def execution_model(parser, config, new):
    """Parse config file, section execution_model

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        new (dict): Parsed configuration for Continuum
    """
    sec = "execution_model"
    if not config.has_section(sec):
        return

    new[sec] = {}
    option_check(parser, config, new, sec, "model", str, lambda x: x in ["openFaas"], True, None)

    if (
        config[sec]["model"] == "openFaas"
        and config["benchmark"]["resource_manager"] != "kubernetes"
    ):
        parser.error("Config: execution_model openFaas requires resource_manager Kubernetes")
        sys.exit()


def start(parser, arg):
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

    infrastructure(parser, config, new)
    infrastructure_network(parser, config, new)
    infrastructure_terraform(parser, config, new)
    benchmark(parser, config, new)
    execution_model(parser, config, new)

    return new
