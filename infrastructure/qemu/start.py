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
            "%s/.continuum/images/ubuntu2004.qcow2" % (config["infrastructure"]["file_path"]),
        ]
        output, error = machine.process(command, ssh=True)

        if error != [] or output == []:
            logging.info("Need to install os image")
            need_image = True
            break

    if need_image:
        command = [
            "ansible-playbook",
            "-i",
            config["infrastructure"]["file_path"] + "/.continuum/inventory",
            config["infrastructure"]["file_path"] + "/.continuum/infrastructure/os.yml",
        ]
        main.ansible_check_output(machines[0].process(command))


def base_image(config, machines):
    """Check if a base image already exists, and if not create the image

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Check if new base image(s) needs to be created")
    base_names = [machine.base_names for machine in machines]
    base_names = list(
        set([item.rstrip(string.digits) for sublist in base_names for item in sublist])
    )
    need_images = [False for _ in range(len(base_names))]
    for machine in machines:
        for base_name in machine.base_names:
            command = [
                "find",
                "%s/.continuum/images/%s.qcow2"
                % (config["infrastructure"]["file_path"], base_name),
            ]
            output, error = machine.process(command, ssh=True)

            if error != [] or output == []:
                base_name = base_name.rstrip(string.digits)
                need_images[base_names.index(base_name)] = True

    # Stop if no base images are required
    base_names = [name for name, need in zip(base_names, need_images) if need]
    if base_names == []:
        return

    # Create base images
    for base_name in base_names:
        logging.info("Create base image %s" % (base_name))
        if base_name == "base":
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory",
                config["infrastructure"]["file_path"] + "/.continuum/infrastructure/base_start.yml",
            ]
        elif "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory",
                config["infrastructure"]["file_path"]
                + "/.continuum/infrastructure/base_cloud_start.yml",
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory",
                config["infrastructure"]["file_path"]
                + "/.continuum/infrastructure/base_edge_start.yml",
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory",
                config["infrastructure"]["file_path"]
                + "/.continuum/infrastructure/base_endpoint_start.yml",
            ]

        main.ansible_check_output(machines[0].process(command))

    # Launch the base VMs concurrently
    processes = []
    base_ips = []
    for machine in machines:
        for base_name, base_ip in zip(machine.base_names, machine.base_ips):
            base_name_r = base_name.rstrip(string.digits)
            if base_name_r in base_names:
                if machine.is_local:
                    command = (
                        "virsh --connect qemu:///system create %s/.continuum/domain_%s.xml"
                        % (config["infrastructure"]["file_path"], base_name)
                    )
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system create %s/.continuum/domain_%s.xml\"'"
                        % (machine.name, config["infrastructure"]["file_path"], base_name)
                    )

                processes.append(machines[0].process(command, shell=True, output=False))
                base_ips.append(base_ip)

    for process in processes:
        logging.debug("Check output for command [%s]" % ("".join(process.args)))
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]

        if error != [] and "Connection to " not in error[0]:
            logging.error("ERROR: %s" % ("".join(error)))
            sys.exit()
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s" % ("".join(output)))
            sys.exit()

    # Fix SSH keys for each base image
    infrastructure.add_ssh(config, machines, base=base_ips)

    # Install software concurrently (ignore infra_only)
    processes = []
    for base_name in base_names:
        command = []
        if "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory_vms",
                config["infrastructure"]["file_path"] + "/.continuum/cloud/base_install.yml",
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory_vms",
                config["infrastructure"]["file_path"] + "/.continuum/edge/base_install.yml",
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                config["infrastructure"]["file_path"] + "/.continuum/inventory_vms",
                config["infrastructure"]["file_path"] + "/.continuum/endpoint/base_install.yml",
            ]

        if command != []:
            processes.append(machines[0].process(command, output=False))

    for process in processes:
        logging.debug("Check output for command [%s]" % ("".join(process.args)))
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]
        main.ansible_check_output((output, error))

    # Install netperf (always, because base images aren't updated)
    command = [
        "ansible-playbook",
        "-i",
        config["infrastructure"]["file_path"] + "/.continuum/inventory_vms",
        config["infrastructure"]["file_path"] + "/.continuum/infrastructure/netperf.yml",
    ]
    main.ansible_check_output(machines[0].process(command))

    # Install docker containers if required
    if not config["infrastructure"]["infra_only"]:
        infrastructure.docker_pull(config, machines, base_names)

    # Clean the VM
    processes = []
    for machine in machines:
        for base_name, ip in zip(machine.base_names, machine.base_ips):
            base_name_r = base_name.rstrip(string.digits)
            if base_name_r in base_names:
                command = "ssh %s@%s -i %s/.ssh/id_rsa_benchmark sudo cloud-init clean" % (
                    base_name,
                    ip,
                    config["home"],
                )
                processes.append(machines[0].process(command, shell=True, output=False))

    for process in processes:
        logging.info("Check output for command [%s]" % ("".join(process.args)))
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]
        main.ansible_check_output((output, error))

    # Shutdown VMs
    processes = []
    for machine in machines:
        for base_name in machine.base_names:
            base_name_r = base_name.rstrip(string.digits)
            if base_name_r in base_names:
                if machine.is_local:
                    command = "virsh --connect qemu:///system shutdown %s" % (base_name)
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system shutdown %s\"'"
                        % (machine.name, base_name)
                    )

                processes.append(machines[0].process(command, shell=True, output=False))

    for process in processes:
        logging.debug("Check output for command [%s]" % ("".join(process.args)))
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]

        if error != [] and not (
            process.args.split(" ")[0] == "ssh" and any(["Connection to " in e for e in error])
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

    processes = []
    if repeat == []:
        for machine in machines:
            for name in (
                machine.cloud_controller_names
                + machine.cloud_names
                + machine.edge_names
                + machine.endpoint_names
            ):
                if machine.is_local:
                    command = (
                        "virsh --connect qemu:///system create %s/.continuum/domain_%s.xml"
                        % (config["infrastructure"]["file_path"], name)
                    )
                else:
                    command = (
                        "ssh %s -t 'bash -l -c \"virsh --connect qemu:///system create %s/.continuum/domain_%s.xml\"'"
                        % (machine.name, config["infrastructure"]["file_path"], name)
                    )

                processes.append(machines[0].process(command, shell=True, output=False))
    else:
        # Only execute specific commands on repeat until VMs are launched succesfully
        for rep in repeat:
            processes.append(machines[0].process(rep, shell=True, output=False))

    repeat = []
    for process in processes:
        logging.debug("Check output for command [%s]" % ("".join(process.args)))
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]

        if error != [] and "kex_exchange_identification" in error[0]:
            # Repeat execution if key exchange error, can be solved by executing again
            logging.error("ERROR, REPEAT EXECUTION: %s" % ("".join(error)))
            repeat.append("".join(process.args))
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
        config["infrastructure"]["file_path"] + "/.continuum/inventory",
        config["infrastructure"]["file_path"] + "/.continuum/infrastructure/remove.yml",
    ]
    main.ansible_check_output(machines[0].process(command))

    # Check if os and base image need to be created, and if so do create them
    os_image(config, machines)
    base_image(config, machines)

    # Create cloud images
    if config["infrastructure"]["cloud_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            config["infrastructure"]["file_path"] + "/.continuum/inventory",
            config["infrastructure"]["file_path"] + "/.continuum/infrastructure/cloud_start.yml",
        ]
        main.ansible_check_output(machines[0].process(command))

    # Create edge images
    if config["infrastructure"]["edge_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            config["infrastructure"]["file_path"] + "/.continuum/inventory",
            config["infrastructure"]["file_path"] + "/.continuum/infrastructure/edge_start.yml",
        ]
        main.ansible_check_output(machines[0].process(command))

    # Create endpoint images
    if config["infrastructure"]["endpoint_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            config["infrastructure"]["file_path"] + "/.continuum/inventory",
            config["infrastructure"]["file_path"] + "/.continuum/infrastructure/endpoint_start.yml",
        ]
        main.ansible_check_output(machines[0].process(command))

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
