"""Install and manage OpenFaaS for serverless computing"""

import logging
import os
import sys

from infrastructure.ansible import ansible_check_output


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return []


def verify_options(config):
    """Verify the config from the module's requirements

    Args:
        config (dict): Parsed Configuration
    """
    if config["execution_model"]["model"] != "openFaas":
        logging.error("ERROR: Execution model should be openFaas")
        sys.exit()
    elif config["benchmark"]["resource_manager"] != "kubernetes":
        logging.error("ERROR: Execution_model openFaas requires resource_manager Kubernetes")
        sys.exit()


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

    ansible_check_output(machines[0].process(config, command)[0])
