"""\
Impelemnt infrastructure
"""

import logging
import os
import sys
import time
import json
import string
import numpy as np

from . import machine as m
from . import network


def delete_vms(config, machines):
    """[INTERFACE] Delete VM infrastructure

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    config["module"]["provider"].delete_vms(config, machines)


def set_ip_names(config, machines, nodes_per_machine):
    """[INTERFACE] Set the number of VMs per tier, and their IP/hostname

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node
    """
    config["module"]["provider"].set_ip_names(config, machines, nodes_per_machine)


def start_provider(config, machines):
    """[INTERFACE] Manage the infrastructure deployment

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    config["module"]["provider"].start(config, machines)


def add_options(config):
    """[INTERFACE] Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object
    """
    return config["module"]["provider"].add_options(config)


def verify_options(parser, config):
    """[INTERFACE] Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    config["module"]["provider"].verify_options(parser, config)


def schedule_equal(config, machines):
    """Distribute the VMs equally over the available machines, based on utilization

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Schedule VMs on machine: Based on utilization")
    machines_per_node = [{"cloud": 0, "edge": 0, "endpoint": 0} for _ in range(len(machines))]
    machines_cores_used = [0 for _ in range(len(machines))]

    types_to_go = {
        "cloud": config["infrastructure"]["cloud_nodes"],
        "edge": config["infrastructure"]["edge_nodes"],
        "endpoint": config["infrastructure"]["endpoint_nodes"],
    }
    cores_per_type = {
        "cloud": config["infrastructure"]["cloud_cores"],
        "edge": config["infrastructure"]["edge_cores"],
        "endpoint": config["infrastructure"]["endpoint_cores"],
    }

    machine_type = "cloud"
    while sum(types_to_go.values()) != 0:
        if types_to_go[machine_type] == 0:
            if machine_type == "cloud":
                machine_type = "edge"
            elif machine_type == "edge":
                machine_type = "endpoint"

            continue

        # Get machine with least cores used compared to total cores
        i = np.argmin(
            [cores_used / m.cores for cores_used, m in zip(machines_cores_used, machines)]
        )

        # Place VM on that machine
        machines_cores_used[i] += cores_per_type[machine_type]
        machines_per_node[i][machine_type] += 1
        types_to_go[machine_type] -= 1

    return machines_per_node


def schedule_pin(config, machines):
    """Check if the requested cloud / edge VMs and endpoint containers can be scheduled
    on the available hardware using a greedy algorithm:
    - If physical node 0 can fit the next cloud / edge VM or endpoint container, do it.
    - If not, go to the next node and try to fit it on there.
    - The scheduling algorithm never considers to previous node for any scheduling anymore.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(set): List of 'cloud', 'edge', 'endpoint' sets containing the number of
            those machines per physical node
    """
    logging.info("Schedule VMs on machine: Based on CPU cores left / Greedy")
    machines_per_node = [{"cloud": 0, "edge": 0, "endpoint": 0}]

    node = 0
    machine_cores_left = machines[0].cores

    machine_type = "cloud"
    types_to_go = {
        "cloud": config["infrastructure"]["cloud_nodes"],
        "edge": config["infrastructure"]["edge_nodes"],
        "endpoint": config["infrastructure"]["endpoint_nodes"],
    }
    cores_per_type = {
        "cloud": config["infrastructure"]["cloud_cores"],
        "edge": config["infrastructure"]["edge_cores"],
        "endpoint": config["infrastructure"]["endpoint_cores"],
    }

    while sum(types_to_go.values()) != 0 and node < len(machines):
        if types_to_go[machine_type] == 0:
            if machine_type == "cloud":
                machine_type = "edge"
            elif machine_type == "edge":
                machine_type = "endpoint"

            continue

        if cores_per_type[machine_type] <= machine_cores_left:
            machine_cores_left -= cores_per_type[machine_type]
            machines_per_node[node][machine_type] += 1
            types_to_go[machine_type] -= 1

            if types_to_go[machine_type] == 0:
                if machine_type == "cloud":
                    machine_type = "edge"
                elif machine_type == "edge":
                    machine_type = "endpoint"
                else:
                    continue

            if machine_cores_left == 0:
                node += 1

                if node == len(machines):
                    break

                machine_cores_left = machines[node].cores
                machines_per_node.append({"cloud": 0, "edge": 0, "endpoint": 0})
        else:
            node += 1

            if node == len(machines):
                break

            machine_cores_left = machines[node].cores
            machines_per_node.append({"cloud": 0, "edge": 0, "endpoint": 0})

    if sum(types_to_go.values()) != 0:
        logging.error(
            """\
Not all VMs or containers fit on the available hardware.
Please request less cloud / edge / endpoints nodes, 
less cores per VM / container or add more hardware
using the --file option"""
        )
        sys.exit()

    return machines_per_node


def create_keypair(config, machines):
    """Create SSH keys to be used for ssh'ing into VMs, local and remote if needed.
    We use the SSH key of the local machine for all machines, so copy to all.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Create SSH keys to be used with VMs")
    for machine in machines:
        if machine.is_local:
            command = "[[ ! -f %s ]] && ssh-keygen -t rsa -b 4096 -f %s -N '' -q" % (
                config["ssh_key"],
                config["ssh_key"],
            )
            output, error = machine.process(config, command, shell=True)[0]
        else:
            source = "%s*" % (config["ssh_key"])
            dest = machine.name + ":./.ssh/"
            output, error = machine.copy_files(config, source, dest)

        if error:
            logging.error("".join(error))
            sys.exit()
        elif output and not any("Your public key has been saved in" in line for line in output):
            logging.error("".join(output))
            sys.exit()

        # Set correct key permissions to be sure
        if machine.is_local:
            commands = [
                ["chmod", "600", config["ssh_key"]],
                ["chmod", "600", "%s.pub" % (config["ssh_key"])],
            ]
            results = machine.process(config, commands)
            for output, error in results:
                if error:
                    logging.error("".join(error))
                    sys.exit()
                elif output:
                    logging.error("".join(output))
                    sys.exit()


def create_tmp_dir(config, machines):
    """Generate a temporary directory for generated files.
    This directory is located inside the benchmark git repository.
    Later, that data will be sent to each physical machine's
    config["infrastructure"]["base_path"]/.continuum directory

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Create a temporary directory for generated files")
    command = "rm -rf %s && mkdir %s" % (
        os.path.join(config["base"], ".tmp"),
        os.path.join(config["base"], ".tmp"),
    )
    output, error = machines[0].process(config, command, shell=True)[0]

    if error:
        logging.error("".join(error))
        sys.exit()
    elif output:
        logging.error("".join(output))
        sys.exit()


def delete_old_content(config, machines):
    """Delete continuum content from previous runs, excluding base images

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    commands = []
    for machine in machines:
        if machine.is_local:
            command = """\
rm -rf %s/.continuum/images/*gcp* && \
rm -rf %s/.continuum/images/.gcp* && \
rm -rf %s/.continuum/images/*.tf && \
rm -rf %s/.continuum/cloud && \
rm -rf %s/.continuum/edge && \
rm -rf %s/.continuum/endpoint && \
rm -rf %s/.continuum/execution_model && \
rm -rf %s/.continuum/infrastructure && \
find %s/.continuum -maxdepth 1 -type f -delete""" % (
                (config["infrastructure"]["base_path"],) * 9
            )
        else:
            command = """\
ssh %s \"\
rm -rf %s/.continuum/cloud && \
rm -rf %s/.continuum/edge && \
rm -rf %s/.continuum/endpoint && \
rm -rf %s/.continuum/execution_model && \
rm -rf %s/.continuum/infrastructure && \
find %s/.continuum -maxdepth 1 -type f -delete\"""" % (
                (machine.name,) + (config["infrastructure"]["base_path"],) * 6
            )

        commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for output, error in results:
        if error and not all("No such file or directory" in line for line in error):
            logging.error("".join(error))
            sys.exit()
        elif output:
            logging.error("".join(output))
            sys.exit()


def create_continuum_dir(config, machines):
    """Create the .continuum and .continuum/images folders for storage

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    commands = []
    for machine in machines:
        if machine.is_local:
            command = (
                "mkdir -p %s/.continuum && \
                 mkdir -p %s/.continuum/images"
                % ((config["infrastructure"]["base_path"],) * 2)
            )
        else:
            command = (
                'ssh %s "\
                 mkdir -p %s/.continuum && \
                 mkdir -p %s/.continuum/images"'
                % ((machine.name,) + (config["infrastructure"]["base_path"],) * 2)
            )

        commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for (output, error), command in zip(results, commands):
        if error:
            logging.error("Command: %s", command)
            logging.error("".join(error))
            sys.exit()
        elif output:
            logging.error("Command: %s", command)
            logging.error("".join(output))
            sys.exit()


def add_ssh(config, machines, base=None):
    """Add SSH keys for generated VMs to known_hosts file
    Since all VMs are connected via a network bridge,
    only touch the known_hosts file of the main physical machine

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        base (list, optional): Base image ips to check. Defaults to None
    """
    logging.info(
        "Start adding ssh keys to the known_hosts file for each VM (base=%s)",
        base == [] or base is None,
    )

    # Get IPs of all (base) machines
    if base:
        ips = base
    else:
        ips = (
            config["control_ips"]
            + config["cloud_ips"]
            + config["edge_ips"]
            + config["endpoint_ips"]
        )

    # Check if old keys are still in the known hosts file
    for ip in ips:
        command = [
            "ssh-keygen",
            "-f",
            os.path.join(config["home"], ".ssh/known_hosts"),
            "-R",
            ip,
        ]
        _, error = machines[0].process(config, command)[0]

        if error and not any("not found in" in err for err in error):
            logging.error("".join(error))
            sys.exit()

    # Once the known_hosts file has been cleaned up, add all new keys
    for ip in ips:
        logging.info("Wait for VM to have started up")
        while True:
            command = f"ssh-keyscan {ip} >> {os.path.join(config['home'], '.ssh/known_hosts')}"
            _, error = machines[0].process(config, command, shell=True)[0]

            if any("# " + str(ip) + ":" in err for err in error):
                break

            time.sleep(5)

    logging.info("SSH keys have been added")


def docker_registry(config, machines):
    """Create and fill a local, private docker registry with the images needed for the benchmark.
    This is to prevent each spawned VM to pull from DockerHub, which has a rate limit.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Create local Docker registry")
    need_pull = [True for _ in range(len(config["images"]))]

    # Check if registry is up
    command = ["curl", "%s/v2/_catalog" % (config["registry"])]
    output, error = machines[0].process(config, command)[0]

    if error and any("Failed to connect to" in line for line in error):
        # Not yet up, so launch
        port = config["registry"].split(":")[-1]
        command = [
            "docker",
            "run",
            "-d",
            "-p",
            "%s:%s" % (port, port),
            "-e",
            "REGISTRY_STORAGE_DELETE_ENABLED=true",
            "--restart=always",
            "--name",
            "registry",
            "registry:2",
        ]
        _, error = machines[0].process(config, command)[0]

        if error and not (
            any("Unable to find image" in line for line in error)
            and any("Pulling from" in line for line in error)
        ):
            logging.error("".join(error))
            sys.exit()
    elif not output:
        # Crash
        logging.error("No output from Docker container")
        sys.exit()
    elif not config["benchmark"]["docker_pull"]:
        # Registry is already up, check if containers are present
        repos = json.loads(output[0])["repositories"]

        for i, image in enumerate(config["images"].values()):
            if image.split(":")[1] in repos:
                need_pull[i] = False

    images = list(config["images"].values())

    # TODO This is RM specific, move this to the RM code
    if config["benchmark"]["resource_manager"] in ["kubecontrol", "kube_kata"]:
        version = str(config["benchmark"]["kube_version"])

        # Get specific etcd and pause versions per Kubernetes version
        if version == "v1.27.0":
            etcd = "3.5.7-0"
            pause = "3.9"
        elif version == "v1.26.0":
            etcd = "3.5.6-0"
            pause = "3.9"
        elif version == "v1.25.0":
            etcd = "3.5.4-0"
            pause = "3.8"
        elif version == "v1.24.0":
            etcd = "3.5.3-0"
            pause = "3.7"
        elif version == "v1.23.0":
            etcd = "3.5.1-0"
            pause = "3.6"
        else:
            logging.error("Continuum supports Kubernetes v1.[23-27].0, not: %s", version)

        images_kube = [
            "redplanet00/kube-proxy:" + version,
            "redplanet00/kube-controller-manager:" + version,
            "redplanet00/kube-scheduler:" + version,
            "redplanet00/kube-apiserver:" + version,
            "redplanet00/etcd:" + etcd,
            "redplanet00/pause:" + pause,
        ]
        images += images_kube
        need_pull += [True] * 6

    # Pull images which aren't present yet in the registry
    for i, (image, pull) in enumerate(zip(images, need_pull)):
        if not pull:
            continue

        # Kubecontrol images need different splitting
        if config["benchmark"]["resource_manager"] in ["kubecontrol", "kube_kata"] and i >= (
            len(images) - 6
        ):
            dest = os.path.join(config["registry"], image.split("/")[1])
        else:
            dest = os.path.join(config["registry"], image.split(":")[1])

        commands = [
            ["docker", "pull", image],
            ["docker", "tag", image, dest],
            ["docker", "push", dest],
        ]

        for command in commands:
            output, error = machines[0].process(config, command)[0]

            if error:
                logging.error("".join(error))
                sys.exit()


def docker_pull(config, machines, base_names):
    """Pull the correct docker images into the base images.
    Do this for (i) All QEMU base images and (ii) All GCP endpoint VMs
    Resource managers like Kubernetes don't need this, they will pull the containers by themselves

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        base_names (list(str)): List of base images to actually pull to
    """
    if not base_names:
        return

    logging.info("Pull docker containers into base images")

    # Pull the images
    for machine in machines:
        commands = []
        sshs = []
        for name, ip in zip(machine.base_names, machine.base_ips):
            name_r = name
            if "_" in name:
                name_r = name.rsplit("_", 1)[0].rstrip(string.digits)

            if name_r in base_names:
                images = []

                if "cloud" in name or "edge" in name:
                    # Load worker application (always in base image for mist deployment)
                    images.append(config["images"]["worker"].split(":")[1])
                elif "endpoint" in name:
                    # Load endpoint and combined applications
                    images.append(config["images"]["endpoint"].split(":")[1])

                    if "combined" in config["images"]:
                        images.append(config["images"]["combined"].split(":")[1])

                for image in images:
                    command = [
                        "docker",
                        "pull",
                        os.path.join(config["registry"], image),
                    ]
                    commands.append(command)
                    sshs.append(name + "@" + ip)

        if commands:
            results = machines[0].process(config, commands, ssh=sshs)

            for ssh, (output, error) in zip(sshs, results):
                logging.info("Execute docker pull command on address [%s]", ssh)

                if error and any(
                    "server gave HTTP response to HTTPS client" in line for line in error
                ):
                    logging.warning(
                        """\
        File /etc/docker/daemon.json does not exist, or is empty on machine %s. 
        This will most likely prevent the machine from pulling endpoint docker images 
        from the private Docker registry running on the main machine %s.
        Please create this file on machine %s with content: { "insecure-registries":["%s"] }
        Followed by a restart of Docker: systemctl restart docker""",
                        ssh,
                        machines[0].name,
                        ssh,
                        config["registry"],
                    )
                if error:
                    logging.error("".join(error))
                    sys.exit()
                elif not output:
                    logging.error("No output from command docker pull")
                    sys.exit()


def start(config):
    """Create and manage infrastructure

    Args:
        config (dict): Parsed configuration

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    machines = m.make_machine_objects(config)

    for machine in machines:
        machine.check_hardware(config)

    if config["infrastructure"]["cpu_pin"]:
        nodes_per_machine = schedule_pin(config, machines)
    else:
        nodes_per_machine = schedule_equal(config, machines)

    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)

    # Delete old resources
    delete_vms(config, machines)

    # Prepare storage for Continuum files
    create_tmp_dir(config, machines)
    delete_old_content(config, machines)
    create_continuum_dir(config, machines)

    # Sets IPs and names for
    set_ip_names(config, machines, nodes_per_machine)
    m.print_schedule(machines)

    if not (config["infrastructure"]["infra_only"] or config["benchmark"]["resource_manager_only"]):
        docker_registry(config, machines)

    start_provider(config, machines)

    if config["infrastructure"]["network_emulation"]:
        network.start(config, machines)

    if config["infrastructure"]["netperf"]:
        network.benchmark(config, machines)

    return machines
