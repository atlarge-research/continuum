"""\
Setup endpoints
"""

import logging
import os
import sys

# pylint: disable=wrong-import-position

sys.path.append(os.path.abspath("../.."))
import main

# pylint: enable=wrong-import-position


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
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(config["infrastructure"]["base_path"], ".continuum/endpoint/install.yml"),
    ]
    main.ansible_check_output(machines[0].process(config, command)[0])
