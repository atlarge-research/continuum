"""\
Create and use QEMU Vms
"""

import logging
import os
import string
import sys
import time

import settings
from infrastructure import ansible
from infrastructure import infrastructure
from . import generate


def _copy(config, machines):
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


def _os_image(config, machines):
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
        # TODO
        #  - pass the host group when executing (for the base_start.yml and start.yml you still
        #    need to set this for example)
        #  - do it like this:
        #    ansible-playbook --extra-vars "host=cloud:edge:endpoint" -i inventory file.yml
        #  - to add more extra vars, add a space between key=value pairs
        logging.info("Need to install OS image")
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/infrastructure/os.yml",
            ),
        ]
        ansible.check_output(machines[0].process(config, command)[0])
    else:
        logging.info("OS image is already there")


def _base_image(config, machines):
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
    inv_host = os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host")
    base_path = os.path.join(config["infrastructure"]["base_path"], "continuum/infrastructure")
    for base_name in base_names:
        logging.info("Create base image %s", base_name)
        if base_name == "base":
            command = f"ansible-playbook -i {inv_host} {base_path}/base_start.yml"
            command = command.split(" ")
            # TODO
            #  - there is only 1 base start file: base_start.yml
            #  - pass the host as variable, see to do above
        elif "base_cloud" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                inv_host,
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_cloud_start.yml",
                ),
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                inv_host,
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/infrastructure/base_edge_start.yml",
                ),
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                inv_host,
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
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_machine"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/cloud/base_install.yml",
                ),
            ]
        elif "base_edge" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_machine"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/edge/base_install.yml",
                ),
            ]
        elif "base_endpoint" in base_name:
            command = [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_machine"),
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
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_machine"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/infrastructure/netperf.yml",
        ),
    ]
    ansible.check_output(machines[0].process(config, command)[0])

    # --------------------------------------------------
    # Download containers if there are some registered
    # TODO
    #  - see infrastructure.py, we modified how this function works
    #  - it's called once per layer
    if settings.config["images"]:
        infrastructure.Infrastructure.docker_pull_base(layer)
    # --------------------------------------------------

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


def _launch_vms(config, machines, repeat=None):
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


def _start_vms():
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
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/infrastructure/remove.yml",
        ),
    ]
    ansible.check_output(machines[0].process(config, command)[0])

    # Check if os and base image need to be created, and if so do create them
    _os_image(config, machines)
    _base_image(config, machines)

    # Create cloud images
    if config["infrastructure"]["cloud_nodes"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host"),
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
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host"),
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
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_host"),
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


def start(layers):
    """Manage the infrastructure deployment using QEMU

    Args:
        layers (list(dict)): List of config layers this provider should provision infra for
    """
    logging.info(f"QEMU will provision layers: {', '.join(layer['name'] for layer in layers)}")

    logging.info("Generate configuration files for Infrastructure and Ansible")
    provider_name = settings.get_providers(layer_name=layers[0]["name"])["name"]
    infrastructure.Infrastructure.create_keypair(provider_name)

    # Create the inventory files needed to make the (base) VMs
    for layer in layers:
        ansible.create_inventory_host(layer["name"])
        ansible.create_inventory_machine(layer["name"])

    for layer in layer:
        generate.start()

    # TODO
    #  - see copy comment in ansible.py.
    #  - Software/workload copies should have already been done in infrastructure.py
    # _copy()

    # TODO
    #  - pass both layer so you can create images in parallel
    #  - e.g., pass multiple ansible host groups at once
    logging.info("Setting up the infrastructure")
    _start_vms(layers)

    # ---------------------- ALREADY PROCESSED BELOW -------------------------
    for layer in layers:
        infrastructure.Infrastructure.add_ssh(layer["name"])
