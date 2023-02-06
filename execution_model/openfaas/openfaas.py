"""Install and manage OpenFaaS for serverless computing"""

import logging
import os
import sys

from infrastructure import ansible


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return []


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (dict): Parsed Configuration
    """
    if config["execution_model"]["model"] != "openFaas":
        parser.error("ERROR: Execution model should be openFaas")
    elif config["benchmark"]["resource_manager"] != "kubernetes":
        parser.error("ERROR: Execution_model openFaas requires resource_manager Kubernetes")
    elif "cache_worker" in config["benchmark"] and config["benchmark"]["cache_worker"] == "True":
        parser.error("ERROR: OpenFaaS app does not support application caching")
    elif (
        application in config["benchmark"]
        and config["benchmark"]["application"] != "image_classification"
    ):
        parser.error("ERROR: Serverless OpenFaaS only works with the image_classification app")


def start(config, machines):
    """Install execution model OpenFaaS by executing an Ansible Playbook

    Args:
        config (dict): Parsed Configuration
        machines (List[Machine]): all physical machines available
    """
    if config["benchmark"]["resource_manager"] != "kubernetes":
        logging.error(
            "FAILED! OpenFaaS only runs with Kubernetes, but %s was installed",
            config["benchmark"]["resource_manager"],
        )
        sys.exit()

    logging.info("Installing OpenFaaS")

    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/execution_model/openFaas.yml",
        ),
    ]

    ansible.check_output(machines[0].process(config, command)[0])


def start_worker(config, machines):
    """Start the serverless function on OpenFaaS

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Deploy serverless functions on %s", config["mode"])

    # Global variables for each applications
    memory = min(1000, int(config["benchmark"]["application_worker_memory"] * 1000))
    cpu = min(1, config["benchmark"]["application_worker_cpu"])

    global_vars = {
        "app_name": config["benchmark"]["application"].split("_")[0],
        "image": os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        "memory_req": memory,
        "cpu_req": cpu,
        "cpu_threads": max(1, cpu),
    }

    # Merge the two var dicts
    all_vars = {**global_vars}

    # Parse to string
    vars_str = ""
    for k, v in all_vars.items():
        vars_str += str(k) + "=" + str(v) + " "

    # Launch applications on cloud/edge
    command = 'ansible-playbook -i %s --extra-vars "%s" %s' % (
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        vars_str[:-1],
        os.path.join(config["infrastructure"]["base_path"], ".continuum/launch_benchmark.yml"),
    )

    ansible.check_output(machines[0].process(config, command, shell=True)[0])
    logging.info("Deployed %s serverless application", config["mode"])
