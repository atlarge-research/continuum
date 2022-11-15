"""\
Setup endpoints
"""

import logging
import os
import sys

sys.path.append(os.path.abspath("../.."))

import main


def start(config, machines):
    """Setup endpoint VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start setting up endpoint VMs")

    command = [
        "ansible-playbook",
        "-i",
        config["infrastructure"]["base_path"] + "/.continuum/inventory_vms",
        config["infrastructure"]["base_path"] + "/.continuum/endpoint/install.yml",
    ]
    main.ansible_check_output(machines[0].process(command))
