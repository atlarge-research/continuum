"""\
Setup KubeEdge on cloud/edge
"""

import logging

import os
import sys

sys.path.append(os.path.abspath("../.."))

import main


def start(config, machines):
    """Setup KubeEdge on cloud/edge VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start KubeEdge cluster on VMs")

    # Mist computing also makes use of this file, but only needs install.yml
    if config["benchmark"]["resource_manager"] == "mist":
        command = [
            "ansible-playbook",
            "-i",
            config["home"] + "/.continuum/inventory_vms",
            config["home"] + "/.continuum/edge/install_mist.yml",
        ]

        output, error = machines[0].process(command)[0]
        main.ansible_check_output((output, error))
        return

    commands = []

    # Setup cloud controller
    command = [
        "ansible-playbook",
        "-i",
        config["home"] + "/.continuum/inventory_vms",
        config["home"] + "/.continuum/cloud/control_install.yml",
    ]
    commands.append(command)

    # Setup edge
    command = [
        "ansible-playbook",
        "-i",
        config["home"] + "/.continuum/inventory_vms",
        config["home"] + "/.continuum/edge/install.yml",
    ]
    commands.append(command)

    results = machines[0].process(commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]" % (" ".join(command)))
        main.ansible_check_output((output, error))

    # Patch: Fix accessing KubeEdge logs from the cloud host
    logging.info("Enable KubeEdge logging feature")
    commands = []
    commands.append(
        [
            "ansible-playbook",
            "-i",
            config["home"] + "/.continuum/inventory_vms",
            config["home"] + "/.continuum/cloud/control_log.yml",
        ]
    )
    commands.append(
        [
            "ansible-playbook",
            "-i",
            config["home"] + "/.continuum/inventory_vms",
            config["home"] + "/.continuum/edge/log.yml",
        ]
    )

    # Wait for the cloud to finish before starting the edge
    for command in commands:
        main.ansible_check_output(machines[0].process(command)[0])
