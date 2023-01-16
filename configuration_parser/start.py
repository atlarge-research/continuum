"""Parse the imput configuration"""

import configparser
import os
import sys


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

    option_check(
        parser,
        config,
        new,
        sec,
        "provider",
        str,
        lambda x: x in ["qemu", "terraform", "baremetal"],
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
        default=False,
    )

    # Only set detailed values if network_emulation = True
    if not new[sec]["network_emulation"]:
        return

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

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_cloud",
        str,
        lambda _: True,
        mandatory=new["infrastructure"]["cloud_nodes"] > 0,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_edge",
        str,
        lambda _: True,
        mandatory=new["infrastructure"]["edge_nodes"] > 0,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_endpoint",
        str,
        lambda _: True,
        mandatory=new["infrastructure"]["endpoint_nodes"] > 0,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_region",
        str,
        lambda _: True,
        mandatory=True,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_zone",
        str,
        lambda _: True,
        mandatory=True,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_project",
        str,
        lambda x: True,
        mandatory=True,
    )

    option_check(
        parser,
        config,
        new,
        sec,
        "gcp_credentials",
        str,
        os.path.expanduser,
        mandatory=True,
    )

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
    if new["mode"] == "cloud":
        default_cpu = new["infrastructure"]["cloud_cores"] - 0.5
        default_mem = new["infrastructure"]["cloud_memory"] - 0.5
    elif new["mode"] == "edge":
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

    option_check(
        parser,
        config,
        new,
        sec,
        "observability",
        bool,
        lambda x: x in [True, False],
        default=False,
    )


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
