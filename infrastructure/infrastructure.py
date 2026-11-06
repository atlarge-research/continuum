"""\
Impelemnt infrastructure
"""

import logging
import os
import shlex
import shutil
import subprocess
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
    """Create the guest keypair on the controller and copy it to worker run roots."""
    logging.info("Create SSH keys to be used with VMs")
    key = config["ssh_key"]
    key_dir = os.path.dirname(key)
    keypair = [key, f"{key}.pub"]
    batches = [[["mkdir", "-p", key_dir]]]
    if not os.path.isfile(key):
        batches.append([["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", key, "-N", "", "-q"]])
    batches.append([["chmod", "600", path] for path in keypair])

    # Machine.process without an SSH target always runs on the controller.
    controller = machines[0]
    for batch in batches:
        for output, error in controller.process(config, batch):
            if error or output:
                logging.error("Controller guest key setup failed: %s", "\n".join(error + output))
                sys.exit(1)

    for machine in machines:
        if machine.is_local:
            continue
        prepare = (
            'test ! -L "$1" && mkdir -m 700 -p -- "$1" && chmod 700 -- "$1"'
            ' && mktemp -d -- "$1/.upload.XXXXXXXX"'
        )
        output, error = machine.process_on_owner(
            config, ["sh", "-c", prepare, "sh", key_dir], timeout_seconds=30,
        )[0]
        if error or len(output) != 1:
            logging.error("Guest key staging on %s failed: %s", machine.name,
                          "\n".join(error + output))
            sys.exit(1)
        staging = output[0]
        if (os.path.normpath(os.path.dirname(staging)) != os.path.normpath(key_dir)
                or not os.path.basename(staging).startswith(".upload.")):
            logging.error("Invalid guest key staging path from %s: %r", machine.name, staging)
            sys.exit(1)
        output, error = machine.copy_to_worker(config, keypair, os.path.join(staging, ""))
        if not (output or error):
            # Keep the previous keys until both uploads have finished. The controller may see
            # the same filesystem as this worker, so never truncate a source key in place.
            install = (
                'test ! -d "$3" && test ! -d "$4"'
                ' && test -f "$1/$2" && test -f "$1/$2.pub"'
                ' && mv -fT -- "$1/$2" "$3" && mv -fT -- "$1/$2.pub" "$4" && rmdir -- "$1"'
            )
            output, error = machine.process_on_owner(
                config, ["sh", "-c", install, "sh", staging, os.path.basename(key), *keypair],
                timeout_seconds=30,
            )[0]
        if output or error:
            logging.error("Guest key transfer to %s failed: %s", machine.name,
                          "\n".join(error + output))
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
    """Clean generated workspace files on each physical owner."""
    base = shlex.quote(os.path.join(config["infrastructure"]["base_path"], ".continuum"))
    remove = "rm -rf %s" % " ".join(
        f"{base}/{name}" for name in ("cloud", "edge", "endpoint", "infrastructure")
    )
    clean_files = f"find {base} -maxdepth 1 -type f ! -name experiment_lock.yaml -delete"
    for machine in machines:
        if machine.is_local:
            command = (
                f"rm -rf {base}/images/*gcp* {base}/images/.gcp* {base}/images/*.tf"
                f" && {remove} && {clean_files}"
            )
            results = machine.process(config, [command], shell=True)
        else:
            command = f"{remove} && if [ -d {base} ]; then {clean_files}; fi"
            results = machine.process_on_owner(config, ["sh", "-c", command], timeout_seconds=120)
        for output, error in results:
            missing_local = machine.is_local and all(
                "No such file or directory" in line for line in error
            )
            if output or (error and not missing_local):
                logging.error("Workspace cleanup on %s: %s", machine.name, "\n".join(error + output))
                sys.exit(1)


def create_continuum_dir(config, machines):
    """Create the workspace and images directories on each physical owner."""
    base = shlex.quote(os.path.join(config["infrastructure"]["base_path"], ".continuum"))
    images = f"{base}/images"
    for machine in machines:
        user = shlex.quote(config["username"] if machine.is_local else machine.user)
        acl = f"u:{user}:rwx,g:kvm:rwx"
        command = (
            f"mkdir -p {base} && mkdir -p {images} && chmod 755 {base} && chmod 755 {images}"
            " && if command -v setfacl >/dev/null 2>&1; then "
            f"setfacl -m {acl} {images} >/dev/null 2>&1 || true; "
            f"setfacl -d -m {acl} {images} >/dev/null 2>&1 || true; fi"
        )
        if machine.is_local:
            results = machine.process(config, [command], shell=True)
        else:
            results = machine.process_on_owner(config, ["sh", "-c", command], timeout_seconds=30)
        for output, error in results:
            if error or output:
                logging.error("Workspace setup on %s: %s", machine.name, "\n".join(error + output))
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

    # One discovery budget covers every guest; a hung probe must also be bounded.
    started = time.monotonic()
    deadline = started + 600
    for ip in ips:
        logging.info("Wait for VM to have started up")
        last_error = "No host keys returned"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                message = "SSH key discovery failed for %s after %.1fs: %s" % (
                    ip, time.monotonic() - started, last_error
                )
                logging.error(message)
                raise RuntimeError(message)
            try:
                result = subprocess.run(
                    ["ssh-keyscan", ip], capture_output=True, text=True,
                    timeout=min(5, remaining), check=False,
                )
                keys = [line for line in result.stdout.splitlines()
                        if len(line.split()) >= 3 and not line.startswith("#")
                        and line.split()[1].startswith(("ssh-", "ecdsa-", "sk-"))]
                if result.returncode == 0 and keys:
                    with open(known_hosts_path, "a", encoding="utf-8") as filep:
                        filep.write("\n".join(keys) + "\n")
                    break
                last_error = result.stderr.strip() or "No host keys returned (exit %s)" % (
                    result.returncode
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                last_error = str(exc)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(5, remaining))

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

    controller = machines[0]
    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)

    is_qemu = config["infrastructure"]["provider"] == "qemu"
    if is_qemu:
        # QEMU checks planned names for protected system-libvirt collisions.
        set_ip_names(config, machines, nodes_per_machine)
        cleanup_hosts = [controller, *(machine for machine in machines if not machine.is_local)]
        config["module"]["provider"].cleanup_startup(config, cleanup_hosts)
    else:
        delete_vms(config, machines)

    # Prepare storage for Continuum files
    create_tmp_dir(config, machines)
    delete_old_content(config, machines)
    create_continuum_dir(config, machines)

    if not is_qemu:
        set_ip_names(config, machines, nodes_per_machine)
    m.print_schedule(machines)

    image_registry.prepare_runtime_images(config, machines)

    start_provider(config, machines)

    if config["infrastructure"]["network_emulation"]:
        network.start(config, machines)

    if config["infrastructure"]["netperf"]:
        network.benchmark(config, machines)

    return machines
