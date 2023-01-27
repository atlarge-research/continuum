"""\
Setup Kubernetes on cloud
"""

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


def verify_options(config):
    """Verify the config from the module's requirements

    Args:
        config (ConfigParser): ConfigParser object
    """
    if (
        config["infrastructure"]["cloud_nodes"] < 2
        or config["infrastructure"]["edge_nodes"] != 0
        or config["infrastructure"]["endpoint_nodes"] < 1
    ):
        logging.error("ERROR: Kubernetes requires #clouds>=2, #edges=0, #endpoints>=1")
        sys.exit()
    elif (config["infrastructure"]["cloud_nodes"] - 1) % config["infrastructure"][
        "endpoint_nodes"
    ] != 0:
        logging.error("ERROR: Kubernetes requires (#clouds-1) %% #endpoints == 0 (-1 for control)")
        sys.exit()
    elif config["infrastructure"]["cloud_cores"] < 2:
        logging.warning(
            "WARNING: Kubernetes controlplane requires >= 2 cores to function optimally"
        )


def start(config, machines):
    """Setup Kubernetes on cloud VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start Kubernetes cluster on VMs")
    commands = []

    # Setup cloud controller
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/cloud/control_install.yml",
            ),
        ]
    )

    # Setup cloud worker
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(config["infrastructure"]["base_path"], ".continuum/cloud/install.yml"),
        ]
    )

    results = machines[0].process(config, commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))

    # Install observability packages (Prometheus, Grafana) if configured by the user
    if config["benchmark"]["observability"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/cloud/observability.yml",
            ),
        ]

        output, error = machines[0].process(config, command)[0]

        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))
