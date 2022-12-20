"""Create infrastructure by applying a Terraform configuration"""

import os
import sys
import logging


def delete_vms(config, machines):
    """Delete the VMs created by Continuum: Always at the start of a run the delete old VMs,
    and possilby at the end if the run if configured by the user.

    Terraform destroy only works if the old configs are still around,
    and destroy hasn't been called before on these configs.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start deleting VMs")
    path = os.path.join(config["infrastructure"]["base_path"], ".continuum/images")
    command = ["terraform", "-chdir=%s" % (path), "destroy", "--auto-approve"]
    output, error = machines[0].process(config, command)[0]

    if error:
        logging.warning("Could not destroy old configuration: %s", "".join(error))
    elif not any("Destroy complete!" in out for out in output):
        logging.warning("Could not destroy the old Terraform configuration: %s", "".join(output))


def set_ip_names(_config, machines, nodes_per_machine):
    """Set amount of cloud / edge / endpoints nodes per machine, and their usernames.
    For Terraform with GCP, there is only 1 machine.
    The IPs are set by GCP, and we only know them after the VMs are started, contrary to QEMU.
    We will set the IPs later.
    The naming scheme is bound to what Terraform can do.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node
    """
    logging.info("Set the names of all VMs for each physical machine")

    if len(machines) > 1 or len(nodes_per_machine) > 1:
        logging.error("ERROR: Terraform only uses 1 machine")
        sys.exit()

    if nodes_per_machine[0]["cloud"] > 0:
        machines[0].cloud_controller = 1
        machines[0].cloud_controller_names.append("cloud0")

        machines[0].clouds = 0
        for i in range(1, nodes_per_machine[0]["cloud"]):
            machines[0].clouds += 1
            machines[0].cloud_names.append("cloud%i" % (i))

    machines[0].edges = 0
    for i in range(nodes_per_machine[0]["edge"]):
        machines[0].edges += 1
        machines[0].edge_names.append("cloud%i" % (i))

    machines[0].endpoints = 0
    for i in range(nodes_per_machine[0]["endpoint"]):
        machines[0].endpoints += 1
        machines[0].endpoint_names.append("cloud%i" % (i))


def start(config, machines):
    """Create and launch QEMU cloud and edge VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start VM creation using QEMU")

    # Init, format, and validate
    path = os.path.join(config["base_path"], ".continuum/images")
    commands = [
        ["terraform", "-chdir=%s" % (path), "init"],
        ["terraform", "-chdir=%s" % (path), "fmt"],
        ["terraform", "-chdir=%s" % (path), "validate"],
    ]

    results = machines[0].process(config, commands)
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error:
            logging.error("ERROR: %s", "".join(error))
            sys.exit()
        elif "init" in command and not any(
            "Terraform has been successfully initialized!" in out for out in output
        ):
            logging.error("ERROR on init: %s", "".join(output))
            sys.exit()
        elif "validate" in command and not any(
            "Success! The configuration is valid." in out for out in output
        ):
            logging.error("ERROR on validate: %s", "".join(output))
            sys.exit()

    # Finally, apply the configuration
    command = ["terraform", "apply", "--auto-validate"]
    output, error = machines[0].process(config, command)[0]

    if error:
        logging.error("Could not apply Terraform configuration: %s", "".join(error))
        sys.exit()
    elif not any("Apply complete!" in out for out in output):
        logging.warning("Could not apply Terraform configuration:: %s", "".join(output))
