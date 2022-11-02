"""\
Setup Kubernetes on cloud
"""

import logging
import os
import sys

sys.path.append(os.path.abspath("../.."))

import main


def start(config, machines):
    """Setup Kubernetes on cloud VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start Kubernetes cluster on VMs")
    commands = []

    # Setup cloud controller
    command = [
        "ansible-playbook",
        "-i",
        config["home"] + "/.continuum/inventory_vms",
        config["home"] + "/.continuum/cloud/control_install.yml",
    ]
    commands.append(command)

    # Setup cloud worker
    command = [
        "ansible-playbook",
        "-i",
        config["home"] + "/.continuum/inventory_vms",
        config["home"] + "/.continuum/cloud/install.yml",
    ]
    commands.append(command)

    results = machines[0].process(commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]" % (" ".join(command)))
        main.ansible_check_output((output, error))
