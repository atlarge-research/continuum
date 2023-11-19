"""\
Parse the input configuration
Handle everything on initializing the config
"""

import copy
import getpass
import importlib
import os
import socket

import yaml
from schema import And, Optional, Schema, SchemaError

import settings


def _get_module_interfaces(parser):
    """Continuum has 3 types of modules:
    - Infrastructure providers (e.g., qemu, gcp, aws)
    - Software packages (e.g., kubernetes, kubeedge, openfaas)
    - Workload benchmarks (e.g., image_classification, empty)

    Each of these module types has a base class which functions as an interface between Continuum
    and the modules of that specific type. Continuum expects the modules to implement the interface.
    Example: Infrastructure provider QEMU implements the "Infrastructure" base class / interface

    We load all interfaces here and use them later to load every module's schema.
    These schemas will then be used to verify the user's input YML.

    Args:
        parser (ArgumentParser): Argparse object

    Returns:
        dict: All module class objects supported by Continuum
    """
    objects = {
        "infrastructure": {},
        "software": {},
        "workload": {},
    }

    for key in objects:
        dirs = list(os.walk(f"./{key}"))[0][1]
        dirs = [d for d in dirs if d[0] != "_"]

        for module_name in dirs:
            mod_name = f"{key}.{module_name}.main"
            try:
                module = importlib.import_module(mod_name)
                objects[key][module_name] = module.Module()
            except ModuleNotFoundError as _:
                parser.error(f"Could not import module {mod_name}")
            except AttributeError as _:
                parser.error(f"Could not find class Module() in module {mod_name}")
            except Exception as e:
                parser.error(f"Import error for module {mod_name} - {e}")

    return objects


def _get_module_schemas(objects):
    """Gather configuration validation schemas for all modules

    Args:
        objects (dict): Objects of all module classes supported by Continuum

    Returns:
        dict(Schema): Schemas for each module type and module
    """
    module_schemas = {
        "provider_init": {},
        "infrastructure": {},
        "software": {},
        "workload": {},
    }

    for key in objects:
        schema_list1 = {}
        schema_list2 = {}
        for module_name, obj in objects[key].items():
            schema = obj.add_options()

            # Infrastructure has 2 parts in the config: provider_init and infrastructure
            # Software and workload only have 1 part
            if key == "infrastructure":
                schema_list2[Optional(module_name)] = schema[0]
                schema_list1[Optional(module_name)] = schema[1]
            else:
                schema_list1[Optional(module_name)] = schema

        module_schemas[key] = schema_list1
        if key == "infrastructure":
            module_schemas["provider_init"] = schema_list2

    return module_schemas


def _get_schema(module_schemas):
    """Build the full schema, including schemas from modules, to validate the input YML config with

    Args:
        module_schemas (dict): Similar to modules dict, but now with schemas per module

    Returns:
        Schema: Full schema to validate YML configuration against
    """
    # Add storage and network emulation
    module_schemas["infrastructure"][Optional("storage")] = {
        Optional("read", default=-1): And(int, lambda x: x >= 0),
        Optional("write", default=-1): And(int, lambda x: x >= 0),
    }
    module_schemas["infrastructure"][Optional("network")] = (
        {
            Optional("preset"): And(str, lambda x: x in ["4g", "5g"]),
            Optional("link"): [
                {
                    "destination": And(str, lambda x: x in ["cloud", "edge", "endpoint"]),
                    Optional("latency_avg", default=-1): And(float, lambda x: x >= 0.0),
                    Optional("latency_var", default=-1): And(float, lambda x: x >= 0.0),
                    Optional("throughput", default=-1): And(float, lambda x: x >= 1.0),
                }
            ],
        },
    )

    return Schema(
        {
            Optional("base_path", default=os.getenv("HOME")): And(str, lambda x: os.path.isdir(x)),
            Optional("delete", default=False): And(bool, lambda x: x in [True, False]),
            Optional("docker_pull", default=False): And(bool, lambda x: x in [True, False]),
            Optional("netperf", default=False): And(bool, lambda x: x in [True, False]),
            Optional("provider_init", default={}): module_schemas["provider_init"],
            "layer": [
                {
                    "infrastructure": module_schemas["infrastructure"],
                    "software": module_schemas["software"],
                }
            ],
            Optional("benchmark"): module_schemas["workload"],
        }
    )


def _fix_provider_init(parser, config, scheme):
    """The following YML file from a user is valid - note that provider_init is missing!
    ---
    layer:
      - name: cloud
        infrastructure:
          qemu:
            nodes: 2
            ...

    The problem is that we need a provider_init entry for QEMU but can't make it mandatory by
    default because we don't know which provider a user is going to use. We need the QEMU entry
    in provider_init to be filled for Continuum to run successfully.

    So, in this function, we check if the infrastructure provider of every layer already has an
    entry in provider_init, and if not, make an empty one. Then, we verify the updated YML file
    again, which can result in two things:
    1. The verification fails because QEMU has some mandatory parameters in provider_init that
       don't have a default value, and need user input (but user input was missing!)
    2. The entire QEMU entry in provider_init gets set to default values and we continue running

    For the successful case 2, the output might look something like this:
    ---
    provider_init:
        qemu:
            cpu_pin: true
            ...
    layer:
      - name: cloud
        infrastructure:
          qemu:
            nodes: 2
            ...

    Note that there now is a provider_init part, with QEMU and its default values.

    Args:
        parser (ArgumentParser): Argparse object
        scheme (Schema): Schema to validate with
        config (dict): Parsed configuration
    """
    # Get all providers used in the config
    providers = []
    for layer in config["layer"]:
        providers += settings.get_layer_provider(layer["name"])["name"]

    providers = list(set(providers))

    # Check if there is an entry for each provider, otherwise make an empty one
    # At this point, "provider_init" itself is guaranteed to exist because we made it with an
    # empty dict in the first schema validation run if it didn't already exist
    for provider in providers:
        if provider not in config["provider_init"]:
            config["provider_init"][provider] = {}

    # Validate with updated provider_init
    try:
        scheme.validate(config)
    except SchemaError as e:
        parser.error(f"Invalid configuration: \n{e}")


def _set_modules(parser, config, objects):
    """Add the module interfaces of the modules we will actually use in the Continuum execution
    to the config. These will later be used by Continuum's core code to interface with the modules.

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration
        objects (dict): Objects of all module classes supported by Continuum
    """
    # First, for infrastructure and software which are per-layer
    for layer in config["layer"]:
        for key in objects:
            if key == "benchmark":
                break

            # There should be at exactly 1 infrastructure provider per layer
            if key == "infrastructure" and len(layer[key]) != 1:
                parser.error(
                    "ERROR: There should be 1 infrastructure provider per layer - found %s"
                    % (", ".join(objects[key]))
                )

            # The software keyword should only exist if there are actually software packages
            if key == "software" and len(layer[key]) == 0:
                parser.error(
                    "ERROR: Software keyword is defined but no software packages are found"
                )

            for module_name in objects[key]:
                if module_name in layer[key]:
                    # Deepcopy because multiple layers can use the same provider or package
                    # We don't want to share these interfaces, so deepcopy
                    # Example: layer["infrastructure"]["qemu"]["name"] = ...
                    layer[key][module_name]["name"] = module_name
                    layer[key][module_name]["interface"] = copy.deepcopy(objects[key][module_name])

    # Second, for the benchmark
    for key in objects:
        if key != "benchmark" or "benchmark" not in config:
            continue

        if len(config[key]) == 0:
            parser.error("ERROR: Benchmark keyword is defined but no workload benchmarks are found")

        if len(config[key]) > 1:
            parser.error(
                "ERROR: Only 1 benchmark at a time is permitted, found: %s",
                ", ".join(config["benchmark"]),
            )

        for module_name in objects[key]:
            if module_name in config["benchmark"]:
                config[key][module_name]["name"] = module_name
                config[key][module_name]["interface"] = objects[key][module_name]


def _add_constants(parser, config):
    """Add some constants to the config dict

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration
    """
    config["username"] = getpass.getuser()
    config["home"] = str(os.getenv("HOME"))

    # Get the base folder of the Continuum repo
    base = str(os.path.dirname(os.path.realpath(__file__)))
    base = base.rsplit("/", 2)[0]  # We're nested 2 deep currently, remove that
    config["base"] = base

    # -----------------------------------------------------------------------------------
    # TODO (low priority)
    #  - This is provider specific - move this somehow to provider code

    # Add SSH key for each provider
    # AWS requires .pem or .ppk
    # For all other providers we use regular .pub ssh keys
    for provider in config["provider_init"]:
        key = os.path.join(config["home"], ".ssh/id_rsa_continuum")
        if provider == "aws":
            key = os.path.join(config["home"], ".ssh/id_rsa_continuum.pem")

        config["provider_init"][provider]["ssh_key"] = key

    # Set range of IP/8 (___.___.___.XXX)
    # We support 250 machines per /8
    if "qemu" in config["provider_init"]:
        # Upper and lower bounds
        config["provider_init"]["qemu"]["postfixIP_min"] = 2
        config["provider_init"]["qemu"]["postfixIP_max"] = 252

        # Current index (for accounting)
        config["provider_init"]["qemu"]["postfixIP"] = 2
        config["provider_init"]["qemu"]["postfixIP_base"] = 2

    # -----------------------------------------------------------------------------------
    # TODO (low priority)
    #  - don't make this mandatory (we want as little dependencies as possible)

    # Set Docker registry IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
        config["registry"] = str(host_ip) + ":5000"
    except socket.gaierror as e:
        parser.error("Could not get host ip with error: %s", e)


def _cross_validate(parser, config):
    """Do extra validation on the input configuration (modules will validate themselves later)
    This includes any and all checks you can think of, so we know that the configuration passed
    to Continuum's core code is valid and as expected.

    Some of these checks may be redundant, but better be safe than sorry

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration for Continuum
    """
    # Check if some basic keys exist and we have an expected number of modules
    if "provider_init" not in config:
        parser.error("ERROR: Missing provider_init in config")
    if len(config["provider_init"]) == 0:
        parser.error("ERROR: Missing providers in provider_init in config")
    if "layer" not in config:
        parser.error("ERROR: Missing layer in config")
    if len(config["layer"]) == 0:
        parser.error("ERROR: No layers defined")
    if len(config["layer"]) > 3:
        parser.error("ERROR: Continuum only supports 3 layers at most")

    # Check for duplicated modules
    layer_names = [layer["name"] for layer in config["layer"]]
    if len(layer_names) != len(set(layer_names)):
        parser.error("ERROR: Duplicate layer names are not allowed: %s" % (", ".join(layer_names)))

    # Check if layer names can only be cloud, edge, and endpoint
    for layer_name in layer_names:
        if layer_name not in ["cloud", "edge", "endpoint"]:
            parser.error(
                "ERROR: Layer names can only be cloud/edge/endpoint, we found: %s"
                % (", ".join(layer_names))
            )

    # Check that there is only 1 infrastructure provider per layer and not too many softw. packages
    packages = list(os.walk("./software"))[0][1]
    packages = [d for d in packages if d[0] != "_"]
    for layer in config["layer"]:
        if "infrastructure" not in layer:
            parser.error("ERROR: Infrastructure should be defined in each layer")

        if layer["infrastructure"] != 1:
            parser.error("ERROR: Should have exactly 1 infrastructure provider per layer")

        if "software" in layer and len(layer["software"]) > len(packages):
            parser.error(
                "ERROR: Software packages incorrect, should be a mix of: %s" % (", ".join(packages))
            )

    # Check if there only is 1 benchmark
    if "benchmark" in config:
        if len(config["benchmark"]) == 0:
            parser.error("ERROR: Benchmark defined but without entry")
        if len(config["benchmark"]) > 1:
            parser.error("ERROR: Only 1 benchmark entry can be defined")


def _validate_emulation(parser, config):
    for layer in config["layer"]:
        # Get provider - needed to verify if provider supports network / storage emulation
        provider = settings.get_layer_provider(layer["name"])

        # Verify storage emulation
        if "storage" in layer["infrastructure"]:
            storage = layer["infrastructure"]["storage"]
            if storage["read"] == -1 and storage["write"] == -1:
                del storage
            elif not provider["interface"].supports_storage_emulation():
                parser.error(
                    f"ERROR: Provider {provider['name']} in layer {layer['name']} "
                    f"does not support storage emulation"
                )

        # Verify network emulation
        if "network" in layer["infrastructure"]:
            network = layer["infrastructure"]["network"]

            if len(network) == 0:
                parser.error("ERROR: QEMU network definition is empty")

            if "link" in network:
                if len(network["link"]) == 0:
                    parser.error("ERROR: Network per-link emulation defined without links")

                for link in network["link"]:
                    if list(link.keys()) == ["destination"]:
                        parser.error(
                            "ERROR: For per-link network emulation, "
                            "need at least latency or throughput defined"
                        )

                    if (link["latency_avg"] == -1 and link["latency_var"] >= 0.0) or (
                        link["latency_avg"] >= 0.0 and link["latency_var"] == -1
                    ):
                        parser.error(
                            "ERROR: For per-link network latency emulation, "
                            "both avg and var defined with a value >= 0.0"
                        )

            if not provider["interface"].supports_network_emulation():
                parser.error(
                    f"ERROR: Provider {provider['name']} in layer {layer['name']} "
                    f"does not support network emulation"
                )


def _cross_validate_module(parser, config):
    """Let every module do its own validation

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed configuration
    """
    for layer in config["layer"]:
        provider_name = list(layer["infrastructure"].keys())[0]
        layer["infrastructure"][provider_name]["interface"].verify_options(parser)

        if "software" in layer:
            for package_name in layer["software"]:
                layer["software"][package_name]["interface"].verify_options(parser)

    if "benchmark" in config:
        benchmark_name = list(config["benchmark"].keys())[0]
        config["benchmark"][benchmark_name]["interface"].verify_options(parser)


def start(parser, arg):
    """Parse config file, check valid input

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a config file

    Returns:
        configParser: Parsed config file
    """
    with open(arg, "r") as config_file:
        config = yaml.safe_load(config_file)

        objects = _get_module_interfaces(parser)
        module_schemas = _get_module_schemas(objects)
        scheme = _get_schema(module_schemas)
        print(f"Parsing schema: \n{scheme}")

        try:
            scheme.validate(config)
        except SchemaError as e:
            parser.error(f"Invalid configuration: \n{e}")

        _fix_provider_init(parser, config, module_schemas)
        _set_modules(parser, config, objects)
        _add_constants(parser, config)

        # From now on, we make the config a global variable in settings.py which each file in the
        # Continuum framework imports for convenience. We won't change the config file anymore in
        # this file so there shouldn't be any name clashing problems
        settings.config = config

        _cross_validate(parser, config)
        _validate_emulation(parser, config)
        _cross_validate_module(parser, config)

        # Gather container images required for software and benchmark
        # These will be pulled into a local registry and base images
        config["images"] = {}
        for package in settings.get_packages(flat=True):
            config["images"] += package["interface"].get_image_location()

        benchmark = settings.get_benchmark()
        if benchmark:
            config["images"] += benchmark["interface"].get_image_location()
