"""Create infrastructure for GCP by applying a Terraform configuration"""

import logging
import os
import sys

from input.configuration import config_access
from infrastructure import ansible, image_registry, infrastructure
from infrastructure import machine as m
from resource_manager import plans as rm_plans

from . import generate


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


def add_options(config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [
        # Option | Type | Condition | Mandatory | Default
        ["gcp_cloud", str, lambda _: True, config["infrastructure"]["cloud_nodes"] > 0, None],
        ["gcp_edge", str, lambda _: True, config["infrastructure"]["edge_nodes"] > 0, None],
        ["gcp_endpoint", str, lambda _: True, config["infrastructure"]["endpoint_nodes"] > 0, None],
        ["gcp_region", str, lambda _: True, True, None],
        ["gcp_zone", str, lambda _: True, True, None],
        ["gcp_project", str, lambda _: True, True, None],
        ["gcp_credentials", str, os.path.expanduser, True, None],
    ]

    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["infrastructure"]["provider"] != "gcp":
        parser.error("ERROR: Infrastructure provider should be gcp")

    sec = "infrastructure"
    if len(config[sec]["gcp_credentials"]) > 0 and config[sec]["gcp_credentials"][-1] == "/":
        config[sec]["gcp_credentials"] = config[sec]["base_pgcp_credentialsth"][:-1]


def set_ip_names(_config, machines, nodes_per_machine):
    """Set amount of cloud / edge / endpoints nodes per machine, and their usernames.
    For GCP with Terraform, there is only 1 machine.
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
        logging.error("ERROR: GCP/Terraform only uses 1 machine")
        sys.exit(1)

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

    machines[0].base_names = (
        machines[0].cloud_controller_names
        + machines[0].cloud_names
        + machines[0].edge_names
        + machines[0].endpoint_names
    )


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
    apply_complete = False
    for i, line in enumerate(output):
        if "Apply complete!" in line:
            apply_complete = True

        if apply_complete and "Outputs:" in line:
            line_nr = i + offset_between_categories
            break

    # Cloud external
    for i in range(machines[0].cloud_controller):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_controller_ips.append(ip)
        line_nr += 1

    for i in range(machines[0].clouds):
        ip = output[line_nr].split('"')[1]
        machines[0].cloud_ips.append(ip)
        line_nr += 1

    if machines[0].cloud_controller + machines[0].clouds > 0:
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

    if machines[0].cloud_controller + machines[0].clouds > 0:
        line_nr += offset_between_categories

    # Edge external
    for i in range(machines[0].edges):
        ip = output[line_nr].split('"')[1]
        machines[0].edge_ips.append(ip)
        line_nr += 1

    if machines[0].edges > 0:
        line_nr += offset_between_categories

    # Edge internal
    for i in range(machines[0].edges):
        ip = output[line_nr].split('"')[1]
        machines[0].edge_ips_internal.append(ip)
        line_nr += 1

    if machines[0].edges > 0:
        line_nr += offset_between_categories

    # Endpoint external
    for i in range(machines[0].endpoints):
        ip = output[line_nr].split('"')[1]
        machines[0].endpoint_ips.append(ip)
        line_nr += 1

    if machines[0].endpoints > 0:
        line_nr += offset_between_categories

    # Endpoint internal
    for i in range(machines[0].endpoints):
        ip = output[line_nr].split('"')[1]
        machines[0].endpoint_ips_internal.append(ip)
        line_nr += 1

    machines[0].base_ips = (
        machines[0].cloud_controller_ips
        + machines[0].cloud_ips
        + machines[0].edge_ips
        + machines[0].endpoint_ips
    )


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
                    os.path.join(
                        config.get("tmp_dir", os.path.join(config["base"], ".tmp")),
                        "%s.tf" % (tf),
                    ),
                    dest_image,
                )
            )

        for output, error in out:
            if error:
                logging.error("".join(error))
                sys.exit(1)
            elif output:
                logging.error("".join(output))
                sys.exit(1)


def netperf_install(config, machines, runner=None):
    """Install NetPerf on GCP with Terraform.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        runner (AnsibleRunner, optional): Shared runner instance for playbook execution.
    """
    if runner is None:
        runner = ansible.AnsibleRunner(config, machines)

    logging.info("Install NetPerf on GCP with Terraform")
    runner.run_playbook(
        "playbooks/infrastructure/netperf.yml",
        inventory="vms",
    )


def set_timezone(config, machines):
    """Sync the timezone of the host machine with the timzones of the VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Get host timezone
    command = ["ls", "-alh", "/etc/localtime"]
    output, error = machines[0].process(config, command)[0]

    if not output or "/etc/localtime" not in output[0]:
        logging.error("Could not get host timezone: %s", "".join(output))
        sys.exit(1)
    elif error:
        logging.error("Could not get host timezone: %s", "".join(error))
        sys.exit(1)

    timezone = output[0].split("-> ")[1].strip()

    # Fix timezone on every base vm
    command = ["sudo", "ln", "-sf", timezone, "/etc/localtime"]
    sshs = []

    for ip, name in zip(machines[0].base_ips, machines[0].base_names):
        ssh = "%s@%s" % (name, ip)
        sshs.append(ssh)

    results = machines[0].process(config, command, ssh=sshs)

    for output, error in results:
        if output:
            logging.error("Could not set VM timezone: %s", "".join(output))
            sys.exit(1)
        elif error:
            logging.error("Could not set VM timezone: %s", "".join(error))
            sys.exit(1)


def base_install(config, machines, runner=None):
    """Install Software on the VMs, without user configuration still

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        runner (AnsibleRunner, optional): Shared runner instance for playbook execution.
    """
    if runner is None:
        runner = ansible.AnsibleRunner(config, machines)

    logging.info("Install software in the VMs")
    if not config_access.infra_only(config):
        playbooks = rm_plans.build_base_image_playbooks(config, machines[0].base_names)
        if playbooks:
            runner.run_playbooks(playbooks, inventory="vms")

    # Install netperf (only if netperf=True)
    if config["infrastructure"]["netperf"]:
        netperf_install(config, machines, runner=runner)

    # Install docker containers if required by prefetch image requirements
    if image_registry.has_prefetch_requirements(config):
        # Kubecontrol won't use docker registries in the cloud due to conflicts with containerd
        if config_access.orchestrator_name(config) == "kubecontrol":
            docker_base_names = []
        else:
            image_registry.move_prefetched_images_to_remote_registry(config, machines)
            docker_base_names = machines[0].base_names

        # Kubernetes/KubeEdge don't need docker images on the cloud/edge nodes
        # These RM will automatically pull images, so we can skip this here.
        # Only pull endpoint images instead
        if config_access.orchestrator_name(config) in ("kubernetes", "kubeedge", "kubecontrol"):
            docker_base_names = [
                base_name for base_name in docker_base_names if "endpoint" in base_name
            ]

        image_registry.docker_pull(config, machines, docker_base_names)

    set_timezone(config, machines)


def start_vms(config, machines):
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
            sys.exit(1)
        elif "init" in command and not any(
            "Terraform has been successfully initialized!" in out for out in output
        ):
            logging.error("ERROR on init: %s", "".join(output))
            sys.exit(1)
        elif "validate" in command and not any(
            "The configuration is valid." in out for out in output
        ):
            logging.error("ERROR on validate: %s", "".join(output))
            sys.exit(1)
        elif "apply" in command and not any("Apply complete!" in out for out in output):
            logging.error("ERROR: Could not apply Terraform configuration: %s", "".join(output))
            sys.exit(1)

    set_ips(machines, output)

    # Kubecontrol doesn't use docker registries in the cloud due to conflicts with containerd
    if image_registry.has_prefetch_requirements(config):
        is_control = config_access.orchestrator_name(config) == "kubecontrol"
        image_registry.set_remote_registry_endpoint(config, machines, control=is_control)


def start(config, machines):
    """Manage infrastructure provider GCP / Terraform

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Set up GCP")
    logging.info("Generate configuration files for Infrastructure and Ansible")
    infrastructure.create_keypair(config, machines)
    generate.start(config, machines)

    copy(config, machines)
    start_vms(config, machines)

    m.gather_ips(config, machines)
    m.gather_ssh(config, machines)
    infrastructure.add_ssh(config, machines)

    for machine in machines:
        logging.debug(machine)

    runner = ansible.AnsibleRunner(config, machines)
    ansible.create_inventory_vm(config, machines)
    ansible.generate_group_vars(
        config,
        machines,
        os.path.join(
            config.get("tmp_dir", os.path.join(config["base"], ".tmp")),
            "inventory_group_vars",
        ),
    )
    ansible.copy(config, machines)

    base_install(config, machines, runner=runner)
