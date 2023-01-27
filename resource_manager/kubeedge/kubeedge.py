"""\
Setup KubeEdge on cloud/edge
"""

import logging
import os

from infrastructure import ansible


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
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/edge/install_mist.yml",
            ),
        ]

        ansible.check_output(machines[0].process(config, command)[0])
        return

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

    # Setup edge
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(config["infrastructure"]["base_path"], ".continuum/edge/install.yml"),
        ]
    )

    results = machines[0].process(config, commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))

    # Patch: Fix accessing KubeEdge logs from the cloud host
    # Only start after the normal installation has finished
    logging.info("Enable KubeEdge logging feature")
    commands = []
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/cloud/control_log.yml",
            ),
        ]
    )
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(config["infrastructure"]["base_path"], ".continuum/edge/log.yml"),
        ]
    )

    for command in commands:
        ansible.check_output(machines[0].process(config, command)[0])
