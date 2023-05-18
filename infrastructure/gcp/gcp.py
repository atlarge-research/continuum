"""Create infrastructure for GCP by applying a Terraform configuration"""

import os
import sys
import logging

from infrastructure import infrastructure
from infrastructure import ansible
from infrastructure import machine as m

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


def netperf_install(config, machines):
    """Install NetPerf on GCP with Terraform.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Install NetPerf on GCP with Terraform")
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/infrastructure/netperf.yml",
        ),
    ]
    ansible.check_output(machines[0].process(config, command)[0])


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
        sys.exit()
    elif error:
        logging.error("Could not get host timezone: %s", "".join(error))
        sys.exit()

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
            sys.exit()
        elif error:
            logging.error("Could not set VM timezone: %s", "".join(error))
            sys.exit()


def move_registry(config, machines):
    """Move the Docker Registry from your local machine to the cloud_controller VM (cloud0)
    in GCP. For the VMs in GCP to make use of the registry on the local machine, you need to
    open port 5000 to these specific IPs. This will result in all GCP VMs pulling Docker containers
    over the internet to the cloud, which can be slow with many VMs.
    Therefore, we move the registry to the cloud_controller VM in the cloud, so containers
    can be quickly shared between VMs in the same cloud datacenter.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Determine to new location of the registry
    if config["infrastructure"]["cloud_nodes"]:
        ssh = config["cloud_ssh"][0]
    elif config["infrastructure"]["edge_nodes"]:
        ssh = config["edge_ssh"][0]
    else:
        ssh = config["endpoint_ssh"][0]

    # Create a registry on the cloud controller
    logging.info("Create Docker registry on %s - %s", ssh, config["registry"])

    port = config["old_registry"].split(":")[-1]
    command = [
        "docker",
        "run",
        "-d",
        "-p",
        "%s:%s" % (port, port),
        "--restart=always",
        "--name",
        "registry",
        "registry:2",
    ]
    _, error = machines[0].process(config, command, ssh=ssh)[0]

    if error and not (
        any("Unable to find image" in line for line in error)
        and any("Pulling from" in line for line in error)
    ):
        logging.error("".join(error))
        sys.exit()

    # Move all Docker containers from the local registry to the new remote registry
    logging.info("Copy all container images to new remote registry")
    for image in config["images"].values():
        image_name = image.split(":")[1]
        full_image = os.path.join(config["old_registry"], image_name)

        # Pull the image from the local registry to the local machine
        command = ["docker", "pull", full_image]
        _, error = machines[0].process(config, command)[0]

        if error:
            logging.error("ERROR: Docker save on image %s failed with error: %s", full_image, error)

        # Save the image as tar
        source = os.path.join(
            config["infrastructure"]["base_path"], ".continuum", "%s.tar" % (image_name)
        )
        command = ["docker", "save", "-o", source, full_image]
        _, error = machines[0].process(config, command)[0]

        if error:
            logging.error("ERROR: Docker save on image %s failed with error: %s", full_image, error)

        # Copy the image over to the new registry location
        dest = "%s:/tmp/" % (ssh)
        command = ["scp", "-i", config["ssh_key"], source, dest]
        output, error = machines[0].process(config, command)[0]

        if error:
            logging.error("".join(error))
            sys.exit()
        elif output and not any("Your public key has been saved in" in line for line in output):
            logging.error("".join(output))
            sys.exit()

        # Load the image into the remote docker storage
        command = ["docker", "load", "-i", os.path.join("/tmp", "%s.tar" % (image_name))]
        _, error = machines[0].process(config, command, ssh=ssh)[0]

        if error:
            logging.error("ERROR: Docker load on image %s failed with error: %s", full_image, error)

        # Finally, load the image from the remote docker storage into the remote docker registry
        tag = os.path.join(config["registry"], image_name)
        commands = [
            ["docker", "tag", full_image, tag],
            ["docker", "push", tag],
        ]

        for command in commands:
            _, error = machines[0].process(config, command, ssh=ssh)[0]

            if error:
                logging.error("".join(error))
                sys.exit()


def set_registry(config, machines, control=False):
    """Registry will be moved to the cloud controller, see the move_registry function.
    We need to change the registry IP before installing base software.
    We can only configure the registry itself afterward.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        is_control (bool): For kubecontrol, use the public dockerhub registry instead of local
    """
    config["old_registry"] = config["registry"]

    # Determine to new location of the registry
    if control:
        registry = "docker.io/redplanet00"
    else:
        if config["infrastructure"]["cloud_nodes"]:
            registry = machines[0].cloud_controller_ips_internal[0] + ":5000"
        elif config["infrastructure"]["edge_nodes"]:
            registry = machines[0].edge_ips_internal[0] + ":5000"
        else:
            registry = machines[0].endpoint_ips_internal[0] + ":5000"

    config["registry"] = registry


def base_install(config, machines):
    """Install Software on the VMs, without user configuration still

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Install software in the VMs")
    commands = []

    if not config["infrastructure"]["infra_only"]:
        if any("cloud" in base_name for base_name in machines[0].base_names):
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/cloud/base_install.yml",
                ),
            ]
            commands.append(command)

        if any("edge" in base_name for base_name in machines[0].base_names):
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/edge/base_install.yml",
                ),
            ]
            commands.append(command)

        if any("endpoint" in base_name for base_name in machines[0].base_names):
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/endpoint/base_install.yml",
                ),
            ]
            commands.append(command)

        if commands:
            results = machines[0].process(config, commands)

            for command, (output, error) in zip(commands, results):
                logging.debug("Check output for command [%s]", " ".join(command))
                ansible.check_output((output, error))

    # Install netperf (only if netperf=True)
    if config["infrastructure"]["netperf"]:
        netperf_install(config, machines)

    # Install docker containers if required
    if not (config["infrastructure"]["infra_only"] or config["benchmark"]["resource_manager_only"]):
        # Kubecontrol won't use docker registries in the cloud due to conflicts with containerd
        if config["benchmark"]["resource_manager"] == "kubecontrol":
            docker_base_names = []
        else:
            move_registry(config, machines)
            docker_base_names = machines[0].base_names

        # Kubernetes/KubeEdge don't need docker images on the cloud/edge nodes
        # These RM will automatically pull images, so we can skip this here.
        # Only pull endpoint images instead
        if config["benchmark"]["resource_manager"] in ["kubernetes", "kubeedge", "kubecontrol"]:
            docker_base_names = [
                base_name for base_name in docker_base_names if "endpoint" in base_name
            ]

        infrastructure.docker_pull(config, machines, docker_base_names)

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

    # Kubecontrol doesn't use docker registries in the cloud due to conflicts with containerd
    if not (config["infrastructure"]["infra_only"] or config["benchmark"]["resource_manager_only"]):
        is_control = config["benchmark"]["resource_manager"] == "kubecontrol"
        set_registry(config, machines, control=is_control)


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

    ansible.create_inventory_vm(config, machines)
    ansible.copy(config, machines)

    base_install(config, machines)
