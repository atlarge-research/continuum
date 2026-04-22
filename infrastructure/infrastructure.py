"""\
Impelemnt infrastructure
"""

import logging
import os
import shutil
import shlex
import sys
import time

from . import image_registry, machine as m, network


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

    Returns:
        object: Options from provider add_options.
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

    Returns:
        list[dict[str, int]]: Planned VM counts per physical machine and tier.
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
        i = min(range(len(machines)), key=lambda i: machines_cores_used[i] / machines[i].cores)

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
        sys.exit(1)

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
            ssh_key_dir = shlex.quote(os.path.dirname(config["ssh_key"]))
            ssh_key_path = shlex.quote(config["ssh_key"])
            command = "mkdir -p %s && [[ ! -f %s ]] && ssh-keygen -t rsa -b 4096 -f %s -N '' -q" % (
                ssh_key_dir,
                ssh_key_path,
                ssh_key_path,
            )
            output, error = machine.process(config, command, shell=True)[0]
        else:
            source = "%s*" % (config["ssh_key"])
            dest = machine.name + ":./.ssh/"
            output, error = machine.copy_files(config, source, dest)

        if error:
            logging.error("".join(error))
            sys.exit(1)
        elif output and not any("Your public key has been saved in" in line for line in output):
            logging.error("".join(output))
            sys.exit(1)

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
                    sys.exit(1)
                elif output:
                    logging.error("".join(output))
                    sys.exit(1)


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
    tmp_path = os.path.join(config["infrastructure"]["base_path"], ".continuum", "tmp")
    config["tmp_dir"] = tmp_path
    try:
        shutil.rmtree(tmp_path, ignore_errors=True)
        os.makedirs(tmp_path, exist_ok=True)
    except OSError as exc:
        logging.error("Could not prepare temp workspace %s: %s", tmp_path, exc)
        sys.exit(1)


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
rm -rf %s/.continuum/infrastructure && \
find %s/.continuum -maxdepth 1 -type f -delete""" % (
                (config["infrastructure"]["base_path"],) * 8
            )
        else:
            command = """\
ssh %s \"\
rm -rf %s/.continuum/cloud && \
rm -rf %s/.continuum/edge && \
rm -rf %s/.continuum/endpoint && \
rm -rf %s/.continuum/infrastructure && \
find %s/.continuum -maxdepth 1 -type f -delete\"""" % (
                (machine.name,) + (config["infrastructure"]["base_path"],) * 5
            )

        commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for output, error in results:
        if error and not all("No such file or directory" in line for line in error):
            logging.error("".join(error))
            sys.exit(1)
        elif output:
            logging.error("".join(output))
            sys.exit(1)


def create_continuum_dir(config, machines):
    """Create the .continuum and .continuum/images folders for storage

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    commands = []

    # Mahimahi support is only required when using a Mahimahi-based wireless preset.
    # For non-mahimahi presets, we should not assume Mahimahi is needed or installed.
    wireless_preset = config["infrastructure"].get("wireless_network_preset", "")
    need_mahimahi = isinstance(wireless_preset, str) and wireless_preset.endswith("_mahimahi")

    for machine in machines:
        if machine.is_local:
            command = (
                "mkdir -p %s/.continuum && \
                 mkdir -p %s/.continuum/images && \
                 chmod 755 %s/.continuum && \
                 chmod 755 %s/.continuum/images && \
                 if command -v setfacl >/dev/null 2>&1; then \
                   setfacl -m u:%s:rwx,g:kvm:rwx %s/.continuum/images >/dev/null 2>&1 || true; \
                   setfacl -d -m u:%s:rwx,g:kvm:rwx %s/.continuum/images >/dev/null 2>&1 || true; \
                 fi"
                % (
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    config["username"],
                    config["infrastructure"]["base_path"],
                    config["username"],
                    config["infrastructure"]["base_path"],
                )
            )
        else:
            command = (
                'ssh %s "\
                 mkdir -p %s/.continuum && \
                 mkdir -p %s/.continuum/images && \
                 chmod 755 %s/.continuum && \
                 chmod 755 %s/.continuum/images && \
                 if command -v setfacl >/dev/null 2>&1; then \
                   setfacl -m u:%s:rwx,g:kvm:rwx %s/.continuum/images >/dev/null 2>&1 || true; \
                   setfacl -d -m u:%s:rwx,g:kvm:rwx %s/.continuum/images >/dev/null 2>&1 || true; \
                 fi"'
                % (
                    machine.name,
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    config["infrastructure"]["base_path"],
                    machine.user,
                    config["infrastructure"]["base_path"],
                    machine.user,
                    config["infrastructure"]["base_path"],
                )
            )

        commands.append(command)

        # Only copy Mahimahi support files when using a Mahimahi-based preset.
        if machine.is_local and need_mahimahi:
            src_dir = os.path.join(config["base"], "mahimahi")
            if not os.path.isdir(src_dir):
                # Attempt to automatically fetch the modded Mahimahi implementation
                # from the official Continuum Mahimahi repository:
                # https://github.com/atlarge-research/continuum-modded-mahimahi
                logging.info(
                    "Mahimahi directory not found at %s; cloning continuum-modded-mahimahi...",
                    src_dir,
                )
                clone_cmd = (
                    "git clone https://github.com/atlarge-research/continuum-modded-mahimahi.git %s"
                    % src_dir
                )
                clone_out, clone_err = machines[0].process(config, clone_cmd, shell=True)[0]

                # Git prints normal progress (like "Cloning into ...", "remote: ...")
                # to stderr. We should only treat *real* errors as fatal here.
                if clone_err:
                    non_empty_err = [line for line in clone_err if line.strip()]

                    # Consider lines that clearly indicate a problem. Everything else
                    # (progress, informational messages) is treated as benign.
                    fatal_err = [
                        line
                        for line in non_empty_err
                        if (
                            "fatal:" in line
                            or "error:" in line.lower()
                            or "Permission denied" in line
                        )
                    ]

                    if fatal_err:
                        logging.error("Failed to clone continuum-modded-mahimahi repository.")
                        logging.error("".join(clone_err))
                        sys.exit(1)
                    else:
                        # Benign stderr from git clone, keep it for debugging purposes.
                        logging.debug("Git clone stderr (benign): %s", "".join(clone_err))

            # After ensuring src_dir exists, perform the copy; fail hard if it still doesn't.
            if os.path.isdir(src_dir):
                # Use rsync instead of cp so we can safely exclude the Git metadata.
                # Copying the .git directory has been observed to fail with "Permission denied"
                # on packed objects when they were created by a different user. We don't need
                # the repository metadata for running experiments, so we explicitly skip it.
                dst_base = os.path.join(
                    config["infrastructure"]["base_path"], ".continuum", "mahimahi"
                )
                os.makedirs(dst_base, exist_ok=True)

                command = "rsync -a --exclude='.git' %s/ %s" % (src_dir, dst_base)
                commands.append(command)
            else:
                logging.error(
                    "Mahimahi directory not found at %s after clone attempt; required for preset %s. "
                    "Either create/populate this directory or use a non-mahimahi preset.",
                    src_dir,
                    wireless_preset,
                )
                sys.exit(1)

    results = machines[0].process(config, commands, shell=True)

    for (output, error), command in zip(results, commands):
        if error:
            logging.error("Command: %s", command)
            logging.error("".join(error))
            sys.exit(1)
        elif output:
            logging.error("Command: %s", command)
            logging.error("".join(output))
            sys.exit(1)


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

    known_hosts_path = config.get(
        "ssh_known_hosts_file",
        os.path.join(config["home"], ".ssh", "known_hosts"),
    )
    os.makedirs(os.path.dirname(known_hosts_path), exist_ok=True)
    with open(known_hosts_path, "a", encoding="utf-8"):
        pass

    # Check if old keys are still in the known hosts file
    for ip in ips:
        command = ["ssh-keygen", "-f", known_hosts_path, "-R", ip]
        _, error = machines[0].process(config, command)[0]

        if error and not any("not found in" in err for err in error):
            logging.error("".join(error))
            sys.exit(1)

    # Once the known_hosts file has been cleaned up, add all new keys
    for ip in ips:
        logging.info("Wait for VM to have started up")
        while True:
            command = f"ssh-keyscan {ip} >> {known_hosts_path}"
            _, error = machines[0].process(config, command, shell=True)[0]

            if any("# " + str(ip) + ":" in err for err in error):
                break

            time.sleep(5)

    logging.info("SSH keys have been added")


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

    image_registry.resolve_prefetch_requirements(config)
    image_registry.docker_registry(config, machines)

    start_provider(config, machines)

    if config["infrastructure"]["network_emulation"]:
        network.start(config, machines)

    if config["infrastructure"]["netperf"]:
        network.benchmark(config, machines)

    return machines
