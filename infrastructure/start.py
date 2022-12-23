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
from . import ansible
from . import network

# pylint: disable=unused-import
from .qemu import generate as qemu_generate
from .qemu import start as qemu_vm

from .terraform import generate as terraform_generate
from .terraform import start as terraform_vm

# pylint: enable=unused-import


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
            command = "[[ ! -f %s ]] && ssh-keygen -t rsa -b 4096 -f %s -C KubeEdge -N '' -q" % (
                config["ssh_key"],
                os.path.join(".ssh", config["ssh_key"].split("/")[-1]),
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
rm -rf %s/.continuum/images/*terraform* && \
rm -rf %s/.continuum/images/.terraform* && \
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

    for output, error in results:
        if error:
            logging.error("".join(error))
            sys.exit()
        elif output:
            logging.error("".join(output))
            sys.exit()


def copy_files(config, machines):
    """Copy Infrastructure and Ansible files to all machines with
    directory config["infrastructure"]["base_path"]/.continuum
    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start copying files to all nodes")

    # Delete old content
    delete_old_content(config, machines)

    # Create a source directory on each machine
    create_continuum_dir(config, machines)

    # Now copy the files over
    for machine in machines:
        if machine.is_local:
            dest = os.path.join(config["infrastructure"]["base_path"], ".continuum/")
        else:
            dest = machine.name + ":%s/.continuum/" % (config["infrastructure"]["base_path"])

        out = []

        # For the local machine, copy the ansible inventory file and benchmark launch
        if machine.is_local:
            out.append(
                machine.copy_files(config, os.path.join(config["base"], ".tmp/inventory"), dest)
            )
            out.append(
                machine.copy_files(config, os.path.join(config["base"], ".tmp/inventory_vms"), dest)
            )

            if (
                not config["infrastructure"]["infra_only"]
                and (config["mode"] == "cloud" or config["mode"] == "edge")
                and config["benchmark"]["resource_manager"] != "mist"
            ):
                path = os.path.join(
                    config["base"],
                    "application",
                    config["benchmark"]["application"],
                    "launch_benchmark_%s.yml" % (config["benchmark"]["resource_manager"]),
                )
                d = dest + "launch_benchmark.yml"
                out.append(machine.copy_files(config, path, d))

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

        # For cloud/edge/endpoint specific
        if not config["infrastructure"]["infra_only"]:
            if config["mode"] == "cloud" or config["mode"] == "edge":
                # Use Kubeedge setup code for mist computing
                rm = config["benchmark"]["resource_manager"]
                if config["benchmark"]["resource_manager"] == "mist":
                    rm = "kubeedge"

                path = os.path.join(config["base"], "resource_manager", rm, "cloud")
                out.append(machine.copy_files(config, path, dest, recursive=True))

                if config["mode"] == "edge":
                    path = os.path.join(config["base"], "resource_manager", rm, "edge")
                    out.append(machine.copy_files(config, path, dest, recursive=True))
            if "execution_model" in config:
                path = os.path.join(config["base"], "execution_model")
                out.append(machine.copy_files(config, path, dest, recursive=True))

            path = os.path.join(config["base"], "resource_manager/endpoint/")
            out.append(machine.copy_files(config, path, dest, recursive=True))

        for output, error in out:
            if error:
                logging.error("".join(error))
                sys.exit()
            elif output:
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
    if config["benchmark"]["resource_manager"] == "kubernetes-control":
        images_kube = [
            "redplanet00/kube-proxy:v1.25.3",
            "redplanet00/kube-controller-manager:v1.25.3",
            "redplanet00/kube-scheduler:v1.25.3",
            "redplanet00/kube-apiserver:v1.25.3",
            "redplanet00/etcd:3.5.4-0",
            "redplanet00/pause:3.8",
        ]
        images += images_kube
        need_pull += [True] * 6

    # Pull images which aren't present yet in the registry
    for image, pull in zip(images, need_pull):
        if not pull:
            continue

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
    Not for Kubernetes/KubeEdge deployments, as those use the registries
    For endpoint, pull both the publisher and combined images, as it can be used in
    either cloud/edge mode, or in endpoint mode for publisher and subscriber are combined.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        base_names (list(str)): List of base images to actually pull to

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
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

                    # Only load combined if there are no cloud or edge nodes
                    if not (
                        config["infrastructure"]["cloud_nodes"]
                        + config["infrastructure"]["edge_nodes"]
                    ):
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
    generate = globals()["%s_generate" % (config["infrastructure"]["provider"])]
    vm = globals()["%s_vm" % (config["infrastructure"]["provider"])]

    machines = m.make_machine_objects(config)

    for machine in machines:
        machine.check_hardware(config)

    if config["infrastructure"]["cpu_pin"]:
        nodes_per_machine = schedule_pin(config, machines)
    else:
        nodes_per_machine = schedule_equal(config, machines)

    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)

    # Delete old resources
    vm.delete_vms(config, machines)

    # Prepare storage for Continuum files
    create_tmp_dir(config, machines)
    delete_old_content(config, machines)
    create_continuum_dir(config, machines)

    # Sets IPs and names for
    vm.set_ip_names(config, machines, nodes_per_machine)
    m.print_schedule(machines)

    if not config["infrastructure"]["infra_only"]:
        docker_registry(config, machines)

    # TODO: Replace this if/else with something better, more uniform
    if config["infrastructure"]["provider"] == "qemu":
        m.gather_ips(config, machines)
        m.gather_ssh(config, machines)

        for machine in machines:
            logging.debug(machine)

        logging.info("Generate configuration files for Infrastructure and Ansible")
        create_keypair(config, machines)

        ansible.create_inventory_machine(config, machines)
        ansible.create_inventory_vm(config, machines)
        ansible.copy(config, machines)

        generate.start(config, machines)
        vm.copy(config, machines)

        logging.info("Setting up the infrastructure")
        vm.start(config, machines)
        add_ssh(config, machines)
    elif config["infrastructure"]["provider"] == "terraform":
        logging.info("Generate configuration files for Infrastructure and Ansible")
        create_keypair(config, machines)
        generate.start(config, machines)

        vm.copy(config, machines)
        vm.start(config, machines)

        # TODO: Do something with the internal ips (networking between VMs)
        m.gather_ips(config, machines)
        m.gather_ssh(config, machines)
        add_ssh(config, machines)

        for machine in machines:
            logging.debug(machine)

        ansible.create_inventory_vm(config, machines)
        ansible.copy(config, machines)

        vm.base_install(config, machines)

    if config["infrastructure"]["network_emulation"]:
        network.start(config, machines)

    if config["infrastructure"]["netperf"]:
        network.benchmark(config, machines)

    return machines
