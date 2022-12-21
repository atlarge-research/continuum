"""Create infrastructure by applying a Terraform configuration"""

import os
import sys
import logging

# pylint: disable=wrong-import-position

sys.path.append(os.path.abspath("../.."))
import main

# pylint: enable=wrong-import-position


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

    if error and not any("Error: Inconsistent dependency lock file" in line for line in error):
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
        machines[0].edge_names.append("edge%i" % (i))

    machines[0].endpoints = 0
    for i in range(nodes_per_machine[0]["endpoint"]):
        machines[0].endpoints += 1
        machines[0].endpoint_names.append("endpoint%i" % (i))


def set_ips(machines, output):
    """Set internal and external IPs of VMs based on output from Terraform.
    GCP sets IPs dynamically with the current configuration, so we can only get the IPs
    after the VMs have been started

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        output (list(str)): Output from the terraform apply command as list
    """
    offset_between_categories = 4

    # Search where the output part starts in the terraform apply command
    line_nr = 100000000
    for i, line in enumerate(output):
        if "Outputs:" in line:
            line_nr = i + offset_between_categories

    # cloud_ip_external
    # cloud_ip_internal
    # endpoint ex
    # endpoint in

    # Cloud external
    for i in range(machines[0].cloud_controller):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_controller_ips.append(ip)
        line_nr += 1

    for i in range(machines[0].clouds):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_ips.append(ip)
        line_nr += 1

        if i == machines[0].clouds - 1:
            line_nr += offset_between_categories

    # Cloud internal
    for i in range(machines[0].cloud_controller):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_controller_ips_internal.append(ip)
        line_nr += 1

    for i in range(machines[0].clouds):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_ips_internal.append(ip)
        line_nr += 1

        if i == machines[0].clouds - 1:
            line_nr += offset_between_categories

    # Edge external
    for i in range(machines[0].edges):
        ip = output[line_nr].split('"')[1]
        machines[0].edge_ips.append(ip)
        line_nr += 1

        if i == machines[0].edges - 1:
            line_nr += offset_between_categories

    # Edge internal
    for i in range(machines[0].edges):
        ip = output[line_nr].split('"')[1]
        machines[0].edge_ips_internal.append(ip)
        line_nr += 1

        if i == machines[0].edges - 1:
            line_nr += offset_between_categories

    # Endpoint external
    for i in range(machines[0].endpoints):
        ip = output[line_nr].split('"')[1]
        machines[0].endpoint_ips.append(ip)
        line_nr += 1

        if i == machines[0].endpoints - 1:
            line_nr += offset_between_categories

    # Endpoint internal
    for i in range(machines[0].endpoints):
        ip = output[line_nr].split('"')[1]
        machines[0].endpoint_ips_internal.append(ip)
        line_nr += 1

        if i == machines[0].endpoints - 1:
            line_nr += offset_between_categories


def copy(config, machines):
    """Copy Infrastructure files to all machines

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start copying infrastructure files to all nodes")

    # Now copy the files over
    for machine in machines:
        if machine.is_local:
            dest = os.path.join(config["infrastructure"]["base_path"], ".continuum/")
            dest_image = os.path.join(dest, "images/")
        else:
            dest = machine.name + ":%s/.continuum" % (config["infrastructure"]["base_path"])
            dest_image = dest + "/images"

        out = []

        tf_files = ["header", "network", "outputs"]

        if config["infrastructure"]["cloud_nodes"] > 0:
            tf_files.append("cloud_vm")
        if config["infrastructure"]["edge_nodes"] > 0:
            tf_files.append("edge_vm")
        if config["infrastructure"]["endpoint_nodes"] > 0:
            tf_files.append("endpoint_vm")

        # Copy terraform files
        for tf in tf_files:
            out.append(
                machine.copy_files(
                    config,
                    os.path.join(config["base"], ".tmp", "%s.tf" % (tf)),
                    dest_image,
                )
            )

        # Copy Ansible files for infrastructure (such as netperf installs)
        path = os.path.join(
            config["base"],
            "infrastructure",
            config["infrastructure"]["provider"],
            "infrastructure",
        )
        out.append(machine.copy_files(config, path, dest, recursive=True))

        for output, error in out:
            if error:
                logging.error("".join(error))
                sys.exit()
            elif output:
                logging.error("".join(output))
                sys.exit()


def start(config, machines):
    """Create and launch GCP VMs using Terraform

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start VM creation using Terraform with GCP")

    # Init, format, and validate
    path = os.path.join(config["infrastructure"]["base_path"], ".continuum/images")
    commands = [
        ["terraform", "-chdir=%s" % (path), "init"],
        ["terraform", "-chdir=%s" % (path), "fmt"],
        ["terraform", "-chdir=%s" % (path), "validate"],
        ["terraform", "-chdir=%s" % (path), "apply", "--auto-approve"],
    ]

    for command in commands:
        output, error = machines[0].process(config, command)[0]

        if error:
            logging.error("ERROR: %s", "".join(error))
            sys.exit()
        elif "init" in command and not any(
            "Terraform has been successfully initialized!" in out for out in output
        ):
            logging.error("ERROR on init: %s", "".join(output))
            sys.exit()
        elif "validate" in command and not any(
            "The configuration is valid." in out for out in output
        ):
            logging.error("ERROR on validate: %s", "".join(output))
            sys.exit()
        elif "apply" in command and not any("Apply complete!" in out for out in output):
            logging.error("ERROR: Could not apply Terraform configuration: %s", "".join(output))
            sys.exit()

    set_ips(machines, output)


def netperf(config, machines):
    """Install NetPerf on Terraform.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Install NetPerf on Terraform")
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/infrastructure/netperf.yml",
        ),
    ]
    main.ansible_check_output(machines[0].process(config, command)[0])
