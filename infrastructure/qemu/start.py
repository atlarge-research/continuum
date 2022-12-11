"""\
Create and use QEMU Vms
"""

import sys
import logging
import time
import string
import os
import sys

from .. import start as infrastructure

sys.path.append(os.path.abspath("../.."))

import main


def os_image(config, machines):
    """Check if the os image with Ubuntu 20.04 already exists, and if not create the image (on all machines)

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
                config["infrastructure"]["base_path"], ".continuum/images/ubuntu2004.qcow2"
            ),
        ]
        output, error = machine.process(config, command, ssh=machine.name)[0]

        if error != [] or output == []:
            need_image = True
            break

    if need_image:
        logging.info("Need to install OS image")
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(config["infrastructure"]["base_path"], ".continuum/infrastructure/os.yml"),
        ]
        main.ansible_check_output(machines[0].process(config, command)[0])
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

    # Names can be duplicates across machines, prevent this (TODO: can this be possible?)
    base_names = list(set(base_names))

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

            if error != [] or output == []:
                base_name = base_name.rsplit("_", 1)[0].rstrip(string.digits)
                need_images[base_names.index(base_name)] = True

    # Stop if no base images are required
    base_names = [name for name, need in zip(base_names, need_images) if need]
    if base_names == []:
        logging.info("Base image(s) are all already present")
        return

    # Create base images
    for base_name in base_names:
        logging.info("Create base image %s" % (base_name))
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

        main.ansible_check_output(machines[0].process(config, command)[0])

    # Create commands to launch the base VMs concurrently
    commands = []
    base_ips = []
    for machine in machines:
        for base_name, base_ip in zip(machine.base_names, machine.base_ips):
            base_name_r = base_name.rsplit("_", 1)[0].rstrip(string.digits)
            if base_name_r in base_names:
                path = os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/domain_%s.xml" % (base_name)
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
        logging.debug("Check output for command [%s]" % (command))

        if error != [] and "Connection to " not in error[0]:
            logging.error("ERROR: %s" % ("".join(error)))
            sys.exit()
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s" % ("".join(output)))
            sys.exit()

    # Fix SSH keys for each base image
    infrastructure.add_ssh(config, machines, base=base_ips)

    # Install software concurrently (ignore infra_only)
    commands = []
    for base_name in base_names:
        command = []
        if "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/cloud/base_install.yml"
                ),
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/edge/base_install.yml"
                ),
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/endpoint/base_install.yml"
                ),
            ]

        if command != []:
            commands.append(command)

    if commands != []:
        results = machines[0].process(config, commands)

        for command, (output, error) in zip(commands, results):
            logging.debug("Check output for command [%s]" % (" ".join(command)))
            main.ansible_check_output((output, error))

    # Install netperf (always, because base images aren't updated)
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"], ".continuum/infrastructure/netperf.yml"
        ),
    ]
    main.ansible_check_output(machines[0].process(config, command)[0])

    # Install docker containers if required
    if not config["infrastructure"]["infra_only"]:
        infrastructure.docker_pull(config, machines, base_names)

    # Get host timezone
    command = ["ls", "-alh", "/etc/localtime"]
    output, error = machines[0].process(config, command)[0]

    if output == [] or "/etc/localtime" not in output[0]:
        logging.error("Could not get host timezone: %s" % ("".join(output)))
        sys.exit()
    elif error != []:
        logging.error("Could not get host timezone: %s" % ("".join(error)))
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
        if output != []:
            logging.error("Could not set VM timezone: %s" % ("".join(output)))
            sys.exit()
        elif error != []:
            logging.error("Could not set VM timezone: %s" % ("".join(error)))
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
        logging.info("Check output for command [%s]" % (command))
        main.ansible_check_output((output, error))

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
        logging.debug("Check output for command [%s]" % (command))

        if error != [] and not (
            command.split(" ")[0] == "ssh"
            and any(["Connection to " in e for e in error])
        ):
            logging.error("".join(error))
            sys.exit()
        elif "Domain " not in output[0] or " is being shutdown" not in output[0]:
            logging.error("".join(output))
            sys.exit()

    # Wait for the shutdown to be completed
    time.sleep(5)


def launch_vms(config, machines, repeat=[]):
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

    # Sometimes previous QEMU commands aren't finished yet, so it's safer to wait a bit to prevent lock errors
    time.sleep(5)

    commands = []
    returns = []
    if repeat == []:
        for machine in machines:
            for name in (
                machine.cloud_controller_names
                + machine.cloud_names
                + machine.edge_names
                + machine.endpoint_names
            ):
                path = os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/domain_%s.xml" % (name)
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
        logging.debug("Check output for command [%s]" % (command))

        if error != [] and "kex_exchange_identification" in error[0]:
            # Repeat execution if key exchange error, can be solved by executing again
            logging.error("ERROR, REPEAT EXECUTION: %s" % ("".join(error)))
            repeat.append(command)
        elif error != [] and "Connection to " not in error[0]:
            logging.error("ERROR: %s" % ("".join(error)))
            sys.exit()
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s" % ("".join(output)))
            sys.exit()

    return repeat


def start(config, machines):
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
        os.path.join(config["infrastructure"]["base_path"], ".continuum/infrastructure/remove.yml"),
    ]
    main.ansible_check_output(machines[0].process(config, command)[0])

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
                config["infrastructure"]["base_path"], ".continuum/infrastructure/cloud_start.yml"
            ),
        ]
        main.ansible_check_output(machines[0].process(config, command)[0])

    # Create edge images
    if config["infrastructure"]["edge_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory"),
            os.path.join(
                config["infrastructure"]["base_path"], ".continuum/infrastructure/edge_start.yml"
            ),
        ]
        main.ansible_check_output(machines[0].process(config, command)[0])

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
        main.ansible_check_output(machines[0].process(config, command)[0])

    # Start VMs
    repeat = []
    i = 0
    while True:
        repeat = launch_vms(config, machines, repeat)
        if repeat == []:
            break
        elif i == 1:
            logging.error("ERROR AFTER %i REPS: %s" % (i + 1, " | ".join(repeat)))
            sys.exit()

        i += 1
