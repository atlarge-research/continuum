"""\
Create and use QEMU Vms
"""

import sys
import logging
import time
import string
import os

from infrastructure import infrastructure
from infrastructure import ansible
from infrastructure import machine as m

from . import generate


def delete_vms(config, machines):
    """Delete the VMs created by Continuum: Always at the start of a run the delete old VMs,
    and possilby at the end if the run if configured by the user

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start deleting VMs")

    commands = []
    sshs = []
    for machine in machines:
        if machine.is_local:
            command = (
                r'virsh list --all | grep -o -E "(\w*_%s)" | \
xargs -I %% sh -c "virsh destroy %%"'
                % (config["username"])
            )
        else:
            comm = (
                r"virsh list --all | grep -o -E \"(\w*_%s)\" | \
xargs -I %% sh -c \"virsh destroy %%\""
                % (config["username"])
            )
            command = "ssh %s -t 'bash -l -c \"%s\"'" % (machine.name, comm)

        commands.append(command)
        sshs.append(None)

    results = machines[0].process(config, commands, shell=True, ssh=sshs, ssh_key=False)

    # Wait for process to finish. Outcome of destroy command does not matter
    for command, (_, _) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # TODO: Move base_ip and related logic to here - that's not generic
    #       (that is, GCP doesnt use it)
    return []


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["infrastructure"]["provider"] != "qemu":
        parser.error("ERROR: Infrastructure provider should be qemu")


def update_ip(config, middle_ip, postfix_ip):
    """Update IPs. Once the last number of the IP string (the zzz in www.xxx.yyy.zzz)
    reaches the configured upperbound, reset this number to the lower bound and reset
    the yyy number to += 1 to go to the next IP range.

    Args:
        config (dict): Parsed configuration
        middle_ip (int): yyy part of IP in www.xxx.yyy.zzz
        postfix_ip (int): zzz part of IP in www.xxx.yyy.zzz

    Returns:
        int, int: Updated middle_ip and postfix_ip
    """
    postfix_ip += 1
    if postfix_ip == config["postfixIP_upper"]:
        middle_ip += 1
        postfix_ip = config["postfixIP_lower"]

    return middle_ip, postfix_ip


def set_ip_names(config, machines, nodes_per_machine):
    """Set amount of cloud / edge / endpoints nodes per machine, and their IPs / hostnames.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node
    """
    logging.info("Set the IPs and names of all VMs for each physical machine")
    middle_ip = config["infrastructure"]["middleIP"]
    postfix_ip = config["postfixIP_lower"]

    middle_ip_base = config["infrastructure"]["middleIP_base"]
    postfix_ip_base = config["postfixIP_lower"]

    cloud_index = 0
    edge_index = 0
    endpoint_index = 0

    for i, (machine, nodes) in enumerate(zip(machines, nodes_per_machine)):
        # Set IP / name for controller (on first machine only)
        if (
            machine == machines[0]
            and not config["infrastructure"]["infra_only"]
            and not config["mode"] == "endpoint"
            and not config["benchmark"]["resource_manager"] == "mist"
        ):
            machine.cloud_controller = int(nodes["cloud"] > 0)
            machine.clouds = nodes["cloud"] - int(nodes["cloud"] > 0)

            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip,
                postfix_ip,
            )
            machine.cloud_controller_ips.append(ip)
            machine.cloud_controller_ips_internal.append(ip)

            name = "cloud_controller_%s" % (config["username"])
            machine.cloud_controller_names.append(name)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)
        else:
            machine.cloud_controller = 0
            machine.clouds = nodes["cloud"]

        machine.edges = nodes["edge"]
        machine.endpoints = nodes["endpoint"]

        # Set IP / name for cloud
        for _ in range(machine.clouds):
            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip,
                postfix_ip,
            )
            machine.cloud_ips.append(ip)
            machine.cloud_ips_internal.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "cloud%i_%s" % (cloud_index, config["username"])
            machine.cloud_names.append(name)
            cloud_index += 1

        # Set IP / name for edge
        for _ in range(machine.edges):
            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip,
                postfix_ip,
            )
            machine.edge_ips.append(ip)
            machine.edge_ips_internal.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "edge%i_%s" % (edge_index, config["username"])
            machine.edge_names.append(name)
            edge_index += 1

        # Set IP / name for endpoint
        for _ in range(machine.endpoints):
            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip,
                postfix_ip,
            )
            machine.endpoint_ips.append(ip)
            machine.endpoint_ips_internal.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "endpoint%i_%s" % (endpoint_index, config["username"])
            machine.endpoint_names.append(name)
            endpoint_index += 1

        # Set IP / name for base image(s)
        if config["infrastructure"]["infra_only"]:
            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip_base,
                postfix_ip_base,
            )
            machine.base_ips.append(ip)

            name = "base%i_%s" % (i, config["username"])
            machine.base_names.append(name)
            middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)
        else:
            # Base images for resource manager images
            if "resource_manager" in config["benchmark"]:
                # Use Kubeedge setup code for mist computing
                rm = config["benchmark"]["resource_manager"]
                if config["benchmark"]["resource_manager"] == "mist":
                    rm = "kubeedge"

            if machine.cloud_controller + machine.clouds > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_cloud_%s%i_%s" % (rm, i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)

            if machine.edges > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_edge_%s%i_%s" % (rm, i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)

            if machine.endpoints > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_endpoint%i_%s" % (i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)


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
        else:
            dest = machine.name + ":%s/.continuum/" % (config["infrastructure"]["base_path"])

        out = []

        # Copy VM creation files
        for name in (
            machine.cloud_controller_names
            + machine.cloud_names
            + machine.edge_names
            + machine.endpoint_names
            + machine.base_names
        ):
            out.append(
                machine.copy_files(
                    config,
                    os.path.join(config["base"], ".tmp", "domain_" + name + ".xml"),
                    dest,
                )
            )
            out.append(
                machine.copy_files(
                    config,
                    os.path.join(config["base"], ".tmp", "user_data_" + name + ".yml"),
                    dest,
                )
            )

        # Copy Ansible files for infrastructure
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


def os_image(config, machines):
    """Check if the os image with Ubuntu 20.04 already exists,
    and if not create the image (on all machines)

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Check if a new OS image needs to be created")
    need_image = False
    for machine in machines:
        command = [
            "find",
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/images/ubuntu2004.qcow2",
            ),
        ]
        output, error = machine.process(config, command, ssh=machine.name)[0]

        if error or not output:
            need_image = True
            break

    if need_image:
        logging.info("Need to install OS image")
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/infrastructure/os.yml",
            ),
        ]
        ansible.check_output(machines[0].process(config, command)[0])
    else:
        logging.info("OS image is already there")


def base_image(config, machines):
    """Check if a base image already exists, and if not create the image

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Check if new base image(s) needs to be created")

    # Create a flat list of base_names, without any special characters
    base_names = []
    for machine in machines:
        for base_name in machine.base_names:
            name = base_name.rsplit("_", 1)[0]
            name = name.rstrip(string.digits)
            base_names.append(name)

    # Create a mask for the previous list
    need_images = [False for _ in range(len(base_names))]

    # Check if all images are available on each machine, otherwise set need_images
    for machine in machines:
        for base_name in machine.base_names:
            command = [
                "find",
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/images/%s.qcow2" % (base_name),
                ),
            ]
            output, error = machine.process(config, command, ssh=machine.name)[0]

            if error or not output:
                base_name = base_name.rsplit("_", 1)[0].rstrip(string.digits)
                need_images[base_names.index(base_name)] = True

    # Stop if no base images are required
    base_names = [name for name, need in zip(base_names, need_images) if need]
    if base_names == []:
        logging.info("Base image(s) are all already present")
        return

    # Create base images
    for base_name in base_names:
        logging.info("Create base image %s", base_name)
        if base_name == "base":
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_start.yml",
                ),
            ]
        elif "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_cloud_start.yml",
                ),
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_edge_start.yml",
                ),
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_endpoint_start.yml",
                ),
            ]

        ansible.check_output(machines[0].process(config, command)[0])

    # Create commands to launch the base VMs concurrently
    commands = []
    base_ips = []
    for machine in machines:
        for base_name, base_ip in zip(machine.base_names, machine.base_ips):
            base_name_r = base_name.rsplit("_", 1)[0].rstrip(string.digits)
            if base_name_r in base_names:
                path = os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/domain_%s.xml" % (base_name),
                )
                if machine.is_local:
                    command = "virsh --connect qemu:///system create %s" % (path)
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system create %s\"'"
                        % (machine.name, path)
                    )

                commands.append(command)
                base_ips.append(base_ip)

    # Now launch the VMs
    results = machines[0].process(config, commands, shell=True)

    # Check if VM launching went as expected
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and "Connection to " not in error[0]:
            logging.error("ERROR: %s", "".join(error))
            sys.exit()
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s", "".join(output))
            sys.exit()

    # Fix SSH keys for each base image
    infrastructure.add_ssh(config, machines, base=base_ips)

    # Install software concurrently (infra_only won't get anything installed)
    commands = []
    for base_name in base_names:
        command = []
        if "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/cloud/base_install.yml",
                ),
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/edge/base_install.yml",
                ),
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/endpoint/base_install.yml",
                ),
            ]

        if command:
            commands.append(command)

    if commands:
        logging.info("Install software in the base VMs")
        results = machines[0].process(config, commands)

        for command, (output, error) in zip(commands, results):
            logging.debug("Check output for command [%s]", " ".join(command))
            ansible.check_output((output, error))

    # Install netperf (always, because base images aren't updated)
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

    # Install docker containers if required
    if not (config["infrastructure"]["infra_only"] or config["benchmark"]["resource_manager_only"]):
        # Kubernetes/KubeEdge don't need docker images on the cloud/edge nodes
        # These RM will automatically pull images, so we can skip this here.
        # Only pull endpoint images instead
        docker_base_names = base_names
        if config["benchmark"]["resource_manager"] in [
            "kubernetes",
            "kubeedge",
            "kubecontrol",
            "kube_kata",
        ]:
            docker_base_names = [
                base_name for base_name in docker_base_names if "endpoint" in base_name
            ]

        infrastructure.docker_pull(config, machines, docker_base_names)

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
    for machine in machines:
        for ip, name in zip(machine.base_ips, machine.base_names):
            name_r = name.rsplit("_", 1)[0].rstrip(string.digits)
            if name_r in base_names:
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

    # Clean the VM
    commands = []
    for machine in machines:
        for base_name, ip in zip(machine.base_names, machine.base_ips):
            base_name_r = base_name.rsplit("_", 1)[0].rstrip(string.digits)
            if base_name_r in base_names:
                command = "ssh %s@%s -i %s sudo cloud-init clean" % (
                    base_name,
                    ip,
                    config["ssh_key"],
                )
                commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for command, (output, error) in zip(commands, results):
        logging.info("Check output for command [%s]", command)
        ansible.check_output((output, error))

    # Shutdown VMs
    commands = []
    for machine in machines:
        for base_name in machine.base_names:
            base_name_r = base_name.rsplit("_", 1)[0].rstrip(string.digits)
            if base_name_r in base_names:
                if machine.is_local:
                    command = "virsh --connect qemu:///system shutdown %s" % (base_name)
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system shutdown %s\"'"
                        % (machine.name, base_name)
                    )

                commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and not (
            command.split(" ")[0] == "ssh" and any("Connection to " in e for e in error)
        ):
            logging.error("".join(error))
            sys.exit()
        elif "Domain " not in output[0] or " is being shutdown" not in output[0]:
            logging.error("".join(output))
            sys.exit()

    # Wait for the shutdown to be completed
    time.sleep(5)


def launch_vms(config, machines, repeat=None):
    """Launch VMs concurrently
    Moved into a function so it can be re-executed when a VM didn't start for some reason

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        repeat (list, optional): Repeat specific execution. If empty, start all VMs. Defaults to [].

    Returns:
        list: Commands to execute again
    """
    # Launch the VMs concurrently
    logging.info("Start VMs")

    # Sometimes previous QEMU commands aren't finished yet,
    # so it's safer to wait a bit to prevent lock errors
    time.sleep(5)

    commands = []
    if not repeat:
        for machine in machines:
            for name in (
                machine.cloud_controller_names
                + machine.cloud_names
                + machine.edge_names
                + machine.endpoint_names
            ):
                path = os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/domain_%s.xml" % (name),
                )
                if machine.is_local:
                    command = "virsh --connect qemu:///system create %s" % (path)
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system create %s\"'"
                        % (machine.name, path)
                    )

                commands.append(command)

        results = machines[0].process(config, commands, shell=True)
    else:
        # Only execute specific commands on repeat until VMs are launched succesfully
        commands = repeat
        results = machines[0].process(config, commands, shell=True)

    repeat = []
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and "kex_exchange_identification" in error[0]:
            # Repeat execution if key exchange error, can be solved by executing again
            logging.error("ERROR, REPEAT EXECUTION: %s", "".join(error))
            repeat.append(command)
        elif error and "Connection to " not in error[0]:
            logging.error("ERROR: %s", "".join(error))
            sys.exit()
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s", "".join(output))
            sys.exit()

    return repeat


def start_vms(config, machines):
    """Create and launch QEMU cloud and edge VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start VM creation using QEMU")

    # Delete older VM images
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/infrastructure/remove.yml",
        ),
    ]
    ansible.check_output(machines[0].process(config, command)[0])

    # Check if os and base image need to be created, and if so do create them
    os_image(config, machines)
    base_image(config, machines)

    # Create cloud images
    if config["infrastructure"]["cloud_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/infrastructure/cloud_start.yml",
            ),
        ]
        ansible.check_output(machines[0].process(config, command)[0])

    # Create edge images
    if config["infrastructure"]["edge_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/infrastructure/edge_start.yml",
            ),
        ]
        ansible.check_output(machines[0].process(config, command)[0])

    # Create endpoint images
    if config["infrastructure"]["endpoint_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/infrastructure/endpoint_start.yml",
            ),
        ]
        ansible.check_output(machines[0].process(config, command)[0])

    # Start VMs
    repeat = []
    i = 0
    while True:
        repeat = launch_vms(config, machines, repeat)
        if not repeat:
            break

        if i == 1:
            logging.error("ERROR AFTER %i REPS: %s", i + 1, " | ".join(repeat))
            sys.exit()

        i += 1


def start(config, machines):
    """Manage infrastructure provider QEMU

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Set up QEMU")
    m.gather_ips(config, machines)
    m.gather_ssh(config, machines)

    for machine in machines:
        logging.debug(machine)

    logging.info("Generate configuration files for Infrastructure and Ansible")
    infrastructure.create_keypair(config, machines)

    ansible.create_inventory_machine(config, machines)
    ansible.create_inventory_vm(config, machines)
    ansible.copy(config, machines)

    generate.start(config, machines)
    copy(config, machines)

    logging.info("Setting up the infrastructure")
    start_vms(config, machines)
    infrastructure.add_ssh(config, machines)
