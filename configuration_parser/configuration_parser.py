"""\
Parse the imput configuration
Handle everything on initializing the config
"""

import configparser
import os
import sys
import logging
import socket
import getpass
import importlib

from application import application
from execution_model import execution_model
from infrastructure import infrastructure
from resource_manager import resource_manager


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


def dynamic_import(parser, config):
    """Perform magic and dynamic imports to solve project dependencies
    Find an implementation for every used project component:
    - Infrastructure provider
    - Resource manager
    - Execution model
    - Application

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration
    """
    sys.path.append(os.path.abspath(".."))

    config["module"] = {
        "provider": False,
        "resource_manager": False,
        "execution_model": False,
        "application": False,
    }

    # Check if infrastructure provider directory exists
    dirs = list(os.walk("./infrastructure"))[0][1]
    dirs = [d for d in dirs if d[0] != "_"]
    if config["infrastructure"]["provider"] in dirs:
        config["module"]["provider"] = importlib.import_module(
            "infrastructure.%s.%s" % ((config["infrastructure"]["provider"],) * 2)
        )
    else:
        parser.error(
            "ERROR: Given provider %s does not have an implementation",
            config["infrastructure"]["provider"],
        )

    if not config["infrastructure"]["infra_only"]:
        # Check if resource manager directory exists
        # Not all RM have modules (e.g., mist, none)
        dirs = list(os.walk("./resource_manager"))[0][1]
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

        # Now for execution model
        if "execution_model" in config:
            # Check if resource manager directory exists
            dirs = list(os.walk("./execution_model"))[0][1]
            dirs = [d for d in dirs if d[0] != "_"]
            if config["execution_model"]["model"] in dirs:
                config["module"]["execution_model"] = importlib.import_module(
                    "execution_model.%s.%s" % ((config["execution_model"]["model"],) * 2)
                )
            else:
                parser.error(
                    "ERROR: Given execution model %s does not have an implementation",
                    config["execution_model"]["model"],
                )

        # Now for applications
        if not config["benchmark"]["resource_manager_only"]:
            # Check if infrastructure provider directory exists
            dirs = list(os.walk("./application"))[0][1]
            dirs = [d for d in dirs if d[0] != "_"]
            if config["benchmark"]["application"] in dirs:
                config["module"]["application"] = importlib.import_module(
                    "application.%s.%s" % ((config["benchmark"]["application"],) * 2)
                )
            else:
                parser.error(
                    "ERROR: Application %s does not exist",
                    config["benchmark"]["application"],
                )


def add_constants(parser, config):
    """Add some constants to the config dict

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration
    """
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))
    config["base"] = config["base"].rsplit("/", 1)[0]  # We're nested 1 deep currently, remove that
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
            parser.error("Could not get host ip with error: %s", e)

        config["registry"] = host_ip + ":5000"


def option_check(
    parser,
    input_config,
    config,
    section,
    option,
    intype,
    condition,
    mandatory,
    default,
):
    """Check if each config option is present, if the type is correct, and if the value is correct.

    Args:
        parser (ArgumentParser): Argparse object
        input_config (ConfigParser): ConfigParser object
        config (dict): Parsed configuration
        section (str): Section in the config file
        option (str): Option in a section of the config file
        intype (type): Option should be type
        condition (lambda): Option should have these values
        mandatory (bool): Is option mandatory
        default (bool): Default value if none is set
    """
    if input_config.has_option(section, option):
        # If option is empty, but not mandatory, remove option
        if input_config[section][option] == "":
            if mandatory:
                parser.error("Config: Missing option %s->%s" % (section, option))

            # Set default value if the user didnt set any
            config[section][option] = intype(default)

            return

        # Check type
        try:
            if intype == int:
                val = input_config[section].getint(option)
            elif intype == float:
                val = input_config[section].getfloat(option)
            elif intype == bool:
                val = input_config[section].getboolean(option)
            elif intype == str:
                val = input_config[section][option]
            elif intype == list:
                val = input_config[section][option].split(",")
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

        config[section][option] = val
    elif mandatory:
        parser.error("Config: Missing option %s->%s" % (section, option))
    else:
        # Set default value if the user didnt set any
        config[section][option] = intype(default)


def parse_infrastructure(parser, input_config, config):
    """Parse config file, section infrastructure

    Args:
        parser (ArgumentParser): Argparse object
        input_config (configparser obj): Parsed configuration from the configparser library
        config (dict): Parsed configuration for Continuum
    """
    sec = "infrastructure"
    if not input_config.has_section(sec):
        parser.error("Config: infrastructure section missing")

    config[sec] = {}

    # Get a list of all providers
    providers = list(os.walk("./infrastructure"))[0][1]
    providers = [d for d in providers if d[0] != "_"]

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["provider", str, lambda x: x in providers, True, None],
        ["infra_only", bool, lambda x: x in [True, False], False, False],
        ["cloud_nodes", int, lambda x: x >= 0, False, 0],
        ["edge_nodes", int, lambda x: x >= 0, False, 0],
        ["endpoint_nodes", int, lambda x: x >= 0, False, 0],
    ]

    for s in settings:
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])

    if config[sec]["cloud_nodes"] + config[sec]["edge_nodes"] + config[sec]["endpoint_nodes"] == 0:
        parser.error("Config: cloud_nodes + edge_nodes + endpoint_nodes should be > 0")

    # Set mode
    mode = "endpoint"
    if config[sec]["edge_nodes"]:
        mode = "edge"
    elif config[sec]["cloud_nodes"]:
        mode = "cloud"

    config["mode"] = mode

    # Set specs of VMs
    mandatory = False
    default = 0
    if config[sec]["cloud_nodes"] > 0:
        mandatory = True
        default = None

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["cloud_cores", int, lambda x: x > 0, mandatory, default],
        ["cloud_memory", int, lambda x: x > 0, mandatory, default],
        ["cloud_quota", float, lambda x: 0.1 <= x <= 1.0, mandatory, default],
    ]

    for s in settings:
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])

    mandatory = False
    default = 0
    if config[sec]["edge_nodes"] > 0:
        mandatory = True
        default = None

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["edge_cores", int, lambda x: x > 0, mandatory, default],
        ["edge_memory", int, lambda x: x > 0, mandatory, default],
        ["edge_quota", float, lambda x: 0.1 <= x <= 1.0, mandatory, default],
    ]

    for s in settings:
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])

    mandatory = False
    default = 0
    if config[sec]["endpoint_nodes"] > 0:
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
        ["endpoint_quota", float, lambda x: 0.1 <= x <= 1.0, mandatory, default],
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
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])

    config[sec]["base_path"] = os.path.expanduser(config[sec]["base_path"])
    if config[sec]["base_path"][-1] == "/":
        config[sec]["base_path"] = config[sec]["base_path"][:-1]

    if config[sec]["middleIP"] == config[sec]["middleIP_base"]:
        parser.error("Config: middleIP == middleIP_base")


def parse_infrastructure_network(parser, input_config, config):
    """Parse config file, section infrastructure, network part

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        config (dict): Parsed configuration for Continuum
    """
    sec = "infrastructure"
    if not input_config.has_section(sec):
        parser.error("Config: infrastructure section missing")

    option_check(
        parser,
        input_config,
        config,
        sec,
        "network_emulation",
        bool,
        lambda x: x in [True, False],
        False,
        False,
    )

    # Only set detailed values if network_emulation = True
    if not config[sec]["network_emulation"]:
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
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])


def parse_benchmark(parser, input_config, config):
    """Parse config file, section benchmark

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        config (dict): Parsed configuration for Continuum
    """
    if config["infrastructure"]["infra_only"]:
        return

    sec = "benchmark"
    if not input_config.has_section(sec):
        parser.error("Config: benchmark section missing while infra_only=False")

    config[sec] = {}

    # Get a list of all resource managers
    # TODO: Make mist a provider - and scrap none
    rms = list(os.walk("./resource_manager"))[0][1]
    rms = [d for d in rms if d[0] != "_"]
    rms.append("mist")
    rms.append("none")
    if "endpoint" in rms:
        rms.remove("endpoint")

    # Get a list of all apps
    apps = list(os.walk("./application"))[0][1]
    apps = [d for d in apps if d[0] != "_"]

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["resource_manager", str, lambda x: x in rms, True, None],
        ["resource_manager_only", bool, lambda x: x in [True, False], False, None],
        ["docker_pull", bool, lambda x: x in [True, False], False, None],
        ["application", str, lambda x: x in apps, True, None],
    ]

    for s in settings:
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])

    # Set default values first
    default_cpu = 0.0
    default_mem = 0.0
    if config["mode"] == "cloud":
        default_cpu = config["infrastructure"]["cloud_cores"] - 0.5
        default_mem = config["infrastructure"]["cloud_memory"] - 0.5
    elif config["mode"] == "edge":
        default_cpu = config["infrastructure"]["edge_cores"] - 0.5
        default_mem = config["infrastructure"]["edge_memory"] - 0.5

    ec = config["infrastructure"]["endpoint_cores"]
    em = config["infrastructure"]["endpoint_memory"]

    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["application_worker_cpu", float, lambda x: x >= 0.1, False, default_cpu],
        ["application_worker_memory", float, lambda x: x >= 0.1, False, default_mem],
        ["application_endpoint_cpu", float, lambda x: x >= 0.1, False, ec],
        ["application_endpoint_memory", float, lambda x: x >= 0.1, False, em],
        ["applications_per_worker", int, lambda x: x >= 1, False, 1],
        ["observability", bool, lambda x: x in [True, False], False, False],
    ]

    for s in settings:
        option_check(parser, input_config, config, sec, s[0], s[1], s[2], s[3], s[4])


def parse_execution_model(parser, input_config, config):
    """Parse config file, section execution_model

    Args:
        parser (ArgumentParser): Argparse object
        config (configparser obj): Parsed configuration from the configparser library
        config (dict): Parsed configuration for Continuum
    """
    sec = "execution_model"
    if not input_config.has_section(sec):
        return

    # Get a list of all execution models
    models = list(os.walk("./execution_model"))[0][1]
    models = [d for d in models if d[0] != "_"]

    config[sec] = {}
    option_check(parser, input_config, config, sec, "model", str, lambda x: x in models, True, None)


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

    input_config = configparser.ConfigParser()
    input_config.read(arg)

    # Parsed values will be saved in a dict because ConfigParser can only hold strings
    config = {}

    # Parse the input config
    parse_infrastructure(parser, input_config, config)
    parse_infrastructure_network(parser, input_config, config)
    parse_benchmark(parser, input_config, config)
    parse_execution_model(parser, input_config, config)

    # Add stuff based on the parsed config
    dynamic_import(parser, config)
    add_constants(parser, config)

    # Add and verify options for each module
    add_options(parser, input_config, config)
    verify_options(parser, config)

    if config["module"]["application"]:
        # Add the location of the application container image
        # Required here, for possible integration during infrastructure phase
        application.set_container_location(config)

    return config


def add_options(parser, input_config, config):
    """Add config options for a particular module

    Args:
        parser (ArgumentParser): Argparse object
        input_config (configparser obj): Parsed configuration from the configparser library
        config (dict): Parsed configuration for Continuum
    """
    settings = []

    # Get the options from each module
    if config["module"]["application"]:
        setting = application.add_options(config)
        for s in setting:
            s.append("benchmark")
        settings.append(setting)
    if config["module"]["execution_model"]:
        setting = execution_model.add_options(config)
        for s in setting:
            s.append("execution_model")
        settings.append(setting)
    if config["module"]["provider"]:
        setting = infrastructure.add_options(config)
        for s in setting:
            s.append("infrastructure")
        settings.append(setting)
    if config["module"]["resource_manager"]:
        setting = resource_manager.add_options(config)
        for s in setting:
            s.append("benchmark")
        settings.append(setting)

    # Parse / verify the options, and add to config
    for per_module_settings in settings:
        for s in per_module_settings:
            option_check(parser, input_config, config, s[5], s[0], s[1], s[2], s[3], s[4])


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration for Continuum
    """
    # Get the options from each module
    if config["module"]["application"]:
        application.verify_options(parser, config)
    if config["module"]["execution_model"]:
        execution_model.verify_options(parser, config)
    if config["module"]["provider"]:
        infrastructure.verify_options(parser, config)
    if config["module"]["resource_manager"]:
        resource_manager.verify_options(parser, config)
