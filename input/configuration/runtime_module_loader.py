"""Runtime module loading and constant wiring helpers."""

import getpass
import importlib
import os
import socket as socket_lib
import sys

from input.configuration import config_access


def _needs_local_registry(config):
    """Return whether runtime constants must include the local registry endpoint."""
    if not config_access.infra_only(config):
        return True
    return bool(config.get("module", {}).get("resource_manager"))


def dynamic_import(parser, config):
    """Find implementation modules for provider, orchestrator, and application."""
    sys.path.append(os.path.abspath(".."))

    config["module"] = {
        "provider": False,
        "resource_manager": False,
        "application": False,
    }

    dirs = list(os.walk("./infrastructure"))[0][1]
    dirs = [d for d in dirs if d[0] != "_"]
    if config["infrastructure"]["provider"] in dirs:
        config["module"]["provider"] = importlib.import_module(
            "infrastructure.%s.%s" % ((config["infrastructure"]["provider"],) * 2)
        )
    else:
        parser.error(
            "ERROR: Given provider %s does not have an implementation"
            % (config["infrastructure"]["provider"],)
        )

    try:
        orchestrator_name = config_access.orchestrator_name(config)
    except ValueError as exc:
        if not config_access.infra_only(config):
            parser.error("ERROR: %s" % (exc,))
        orchestrator_name = None

    if orchestrator_name and orchestrator_name != "none":
        dirs = list(os.walk("./resource_manager"))[0][1]
        dirs = [d for d in dirs if d[0] != "_"]
        if orchestrator_name in dirs:
            config["module"]["resource_manager"] = importlib.import_module(
                "resource_manager.%s.%s" % ((orchestrator_name,) * 2)
            )
        elif orchestrator_name == "mist":
            config["module"]["resource_manager"] = importlib.import_module(
                "resource_manager.%s.%s" % (("kubeedge",) * 2)
            )
        else:
            parser.error(
                "ERROR: Given resource manager %s does not have an implementation"
                % (orchestrator_name,)
            )

    if config_access.runs_application(config):
        application_name = config_access.benchmark_primary_stage_type(config)
        dirs = list(os.walk("./application"))[0][1]
        dirs = [d for d in dirs if d[0] != "_"]
        if application_name in dirs:
            config["module"]["application"] = importlib.import_module(
                "application.%s.%s" % ((application_name,) * 2)
            )
            config["module"]["application"].set_container_location(config)


def add_constants(parser, config, socket_module=socket_lib):
    """Add runtime constants to the config dict."""
    config["home"] = str(os.getenv("HOME"))
    config["base"] = str(os.path.dirname(os.path.realpath(__file__)))
    config["base"] = config["base"].rsplit("/", 2)[0]
    config["username"] = getpass.getuser()
    base_path = config.get("infrastructure", {}).get("base_path", config["home"])
    base_path = os.path.expanduser(base_path)
    config["ssh_key"] = os.path.join(base_path, ".continuum", "ssh", "id_rsa_continuum")
    config["ssh_known_hosts_file"] = os.path.join(base_path, ".continuum", "ssh", "known_hosts")
    config["postfixIP_lower"] = 2
    config["postfixIP_upper"] = 252

    if _needs_local_registry(config):
        try:
            with socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                host_ip = sock.getsockname()[0]
        except (socket_module.gaierror, OSError) as e:
            parser.error("Could not get host ip with error: %s" % (e,))

        config["registry"] = host_ip + ":5000"
