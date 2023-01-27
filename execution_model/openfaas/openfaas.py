"""Install and manage OpenFaaS for serverless computing"""

import logging
import os
import sys

from infrastructure.ansible import ansible_check_output


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
