"""\
Setup KubeEdge on cloud/edge
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import logging
import os

from infrastructure import ansible


def add_options(config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # Mist doesn't have cache worker, only KubeEdge
    settings = None
    if config["benchmark"]["resource_manager"] == "kubeedge":
        settings = [["cache_worker", bool, lambda x: x in [True, False], False, False]]

    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    # TODO Split KubeEdge and Mist into two providers
    if config["benchmark"]["resource_manager"] == "kubeedge" and (
        config["infrastructure"]["cloud_nodes"] != 1
        or config["infrastructure"]["edge_nodes"] == 0
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: KubeEdge requires #clouds=1, #edges>=1, #endpoints>=0")
    elif config["benchmark"]["resource_manager"] == "mist" and (
        config["infrastructure"]["cloud_nodes"] != 0
        or config["infrastructure"]["edge_nodes"] == 0
        or config["infrastructure"]["endpoint_nodes"] == 0
    ):
        # Mist, shares KubeEdge code for now
        parser.error("ERROR: Mist requires #clouds==0, #edges>=1, #endpoints>=1")

    if config["infrastructure"]["endpoint_nodes"] % config["infrastructure"]["edge_nodes"] != 0:
        parser.error("ERROR: KubeEdge requires #edges %% #endpoints == 0")


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
