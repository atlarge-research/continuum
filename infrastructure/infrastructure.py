"""\
Impelemnt infrastructure
"""
import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod

import settings
# pylint: disable-next=redefined-builtin
from input_parser import input_parser
from . import host as h
from . import machine as m
from . import network


class Infrastructure(ABC):
    @staticmethod
    def create_keypair(provider_name):
        """One host can support multiple providers at the same time. Each provider has one SSH key
        that is used to communicate with the machines. Here, create that SSH keypair on each host
        for a specific provider.

        Args:
            provider_name (str, optional): Name of the provider to filter for
        """
        logging.info("Create SSH keys to be used with VMs")
        all_host_keys = settings.get_ssh_key_host(provider_name=provider_name)
        for host, keys in zip(settings.config["hosts"], all_host_keys):
            # Each provider has its own SSH key
            # One host can have multiple providers, and hence, multiple SSH keys
            for key in keys:
                if host.is_local:
                    # Create key if on local machine
                    command = f"[[ ! -f {key} ]] && ssh-keygen -t rsa -b 4096 -f {key} -N '' -q"
                    output, error = settings.process(command, shell=True, ssh=[host])[0]
                else:
                    # Copy the local key to external machines. Note that this isn't required
                    # for the framework to function, but helps users if they later want to access
                    # the provided infrastructure by hand from the external machine
                    source = "%s*" % (settings.config["ssh_key"])
                    dest = "./.ssh/"
                    output, error = settings.copy_files(source, dest, target=host)

                if error:
                    logging.error("".join(error))
                    sys.exit()
                elif output and not any(
                    "Your public key has been saved in" in line for line in output
                ):
                    logging.error("".join(output))
                    sys.exit()

                # Set correct key permissions to be sure
                if host.is_local:
                    commands = [[f"chmod 600 {key}"], [f"chmod 600 {key}.pub"]]
                    results = settings.process(commands)
                    for output, error in results:
                        if error:
                            logging.error("".join(error))
                            sys.exit()
                        elif output:
                            logging.error("".join(output))
                            sys.exit()

    @staticmethod
    def add_ssh(layer_name, base=False):
        """Add created SSH keys to access provisioned infrastructure to the host's known_hosts file
        We access all infrastructure from the local host, so only update its known_hosts file

        Args:
            layer_name (str): Name of the layer to execute the operation on (e.g., "cloud")
            base (bool, optional): Check only the base images of this layer. Defaults to False
        """
        logging.info(f"Add SSH keys to the known_hosts file for layer {layer_name} [base={base}]")

        # Get IPs of all (base) machines
        if base:
            ips = settings.get_ips(layer_name=layer_name, base=2, flat=True)
        else:
            ips = settings.get_ips(layer_name=layer_name, base=0, flat=True)

        # Check if old keys are still in the known hosts file
        path = os.path.join(settings.config["home"], ".ssh/known_hosts")
        for ip in ips:
            command = ["ssh-keygen", "-f", path, "-R", ip]

            _, error = settings.process(command)[0]

            if error and not any("not found in" in err for err in error):
                logging.error("".join(error))
                sys.exit()

        # Once the known_hosts file has been cleaned up, add all new keys
        for ip in ips:
            logging.info("Wait for VM to have started up")
            while True:
                command = f"ssh-keyscan {ip} >> {path}"
                _, error = settings.process(command, shell=True)[0]

                if any("# " + str(ip) + ":" in err for err in error):
                    break

                time.sleep(5)

        logging.info("SSH keys have been added")

    @staticmethod
    def docker_pull_base(layer_name):
        """Pull container images into provided machines. We do not restrict what images and into
        which machines, software packages and benchmarks can freely register images to pull.

        TODO (high priority)
         - Make a sister function of get_image_location() that works similarly (for softw./workl.)
         - Software packages and workload benchmarks can map the images in settings.config["images"]
           to specific machines. Make for Machine() a new variable that's a list to which image
           names (the keys in settings.config["images"] can be appended
         - Then, in this function, we only need to iterate all machines, and for each machine
           the images list per machine and pull every image there into that particular machine.
         This is very flexible and will help in the future
         - FINISH THIS FUNCTION WHEN THAT'S DONE

        Args:
            layer_name (str): Name of the layer to execute the operation on (e.g., "cloud")
        """
        logging.info("Pull docker containers into base images")
        commands = []
        machines = []

        # Define the images to be pulled
        for machine in settings.get_machines(layer_name=layer_name):
            for image in machine.images:
                image_path = settings.config["images"][image]
                command = ["docker", "pull", os.path.join(settings.config["registry"], image_path)]

                commands.append(command)
                machines.append(machine)

        # Execute all pull commands at once
        if not commands:
            return

        results = settings.process(commands, ssh=machines)
        for machine, command, (output, error) in zip(machines, commands, results):
            logging.info(f"For machine {machine.name}, pull image {command[2]}")

            if error and any("server gave HTTP response to HTTPS client" in line for line in error):
                logging.error(
                    "Docker is incorrectly configured. Please see the README.md on how to configure"
                    "docker, and specifically how to set up the file in /etc/docker/daemon.json"
                )
                sys.exit()

            if error:
                logging.error("".join(error))
                sys.exit()
            elif not output:
                logging.error("No output from command docker pull")
                sys.exit()

    @staticmethod
    @abstractmethod
    def add_options():
        """Add config options for a particular module"""
        pass

    @staticmethod
    @abstractmethod
    def verify_options(parser):
        """Verify the config from the module's requirements

        Args:
            parser (ArgumentParser): Argparse object
        """
        pass

    @staticmethod
    @abstractmethod
    def is_external():
        """Does this infrastructure provider provision in local or remote hardware (e.g., clouds)

        Returns:
            bool: Provisions on external hardware
        """
        pass

    @staticmethod
    @abstractmethod
    def has_base():
        """Does this infrastructure provider support dedicated base images, such as QEMU where we
        can generate backing images, containing the OS and required software, which are used by all
        cloud/edge/endpoint VMs subsequently.

        Returns:
            bool: Provisions on external hardware
        """
        pass

    @staticmethod
    @abstractmethod
    def supports_network_emulation():
        """Does this infrastructure provider support network emulation?

        Returns:
            bool: Support of network emulation
        """
        pass

    @staticmethod
    @abstractmethod
    def supports_storage_emulation():
        """Does this infrastructure provider support network emulation?

        Returns:
            bool: Support of network emulation
        """
        pass

    @staticmethod
    @abstractmethod
    def set_ip_names(layer):
        """Set the names and IP addresses of each machine on a specific layer

        Args:
            layer (dict): A single layer described in the global config
        """
        pass

    @staticmethod
    @abstractmethod
    def start(layers):
        """Manage the infrastructure deployment

        Args:
            layers (list(dict)): List of config layers this provider should provision infra for
        """
        pass

    @staticmethod
    @abstractmethod
    def delete_vms():
        """Delete VM infrastructure"""
        pass

    @staticmethod
    @abstractmethod
    def finish():
        """Optional: Execute code or print information to users at the end of a Continuum run"""


def _schedule_pin(layer):
    """Eager scheduler: Schedule all nodes on the first host until all host CPU cores are assigned
    to virtual CPU cores from provided infrastructure. Then, go to the second host and continue.
    Externally hosted machines (e.g., as cloud VMs) are always attached to the primary host,
    which is the host on which Continuum is invoked.

    Args:
        layer (dict): Layer to do scheduling for
    """
    logging.info(f"Schedule for layer [{layer['name']}] based on CPU cores left (greedy)")

    # The user defines for each layer a provider, and how many nodes that provider should provision
    # For each node, we try to find a physical Host that has free CPU cores to schedule the node on
    provider = settings.get_providers(layer_name=layer)[0]
    nodes_to_schedule = provider["nodes"]

    # Try to find a free spot per node
    for host in settings.config["hosts"]:
        nodes = nodes_to_schedule
        for _ in nodes:
            # If we can't schedule a node on this host anymore, go to the next host
            # Externally hosted machined (like in the cloud) don't use any of the host's cores
            if not provider["interface"].is_external() and provider["cores"] > host.cores_free:
                break

            # Create the machine object and attach it to the host and layer
            # These empty machine objects will later get named correctly
            machine = m.Machine(layer, provider)
            host.machines.append(machine)

            if "machines" not in layer:
                layer["machines"] = []

            layer["machines"].append(machine)

            # Do accounting: Update free cpu cores on this machine
            nodes_to_schedule -= 1
            if not provider["interface"].is_external():
                host.cores_free -= provider["cores"]

    if nodes_to_schedule != 0:
        logging.error(
            """\
Not all nodes (e.g., VMs) fit on the available hardware.
Please request less cloud / edge / endpoints nodes, 
less cores per VM / container or add more external
hardware using the external_physical_machines option"""
        )
        sys.exit()


def _host_least_util(cores):
    """For _schedule_equal(): Find the used with the lowest CPU utilization based on how many
    machines are scheduled onto the host already. The currently least used host will be used
    to schedule a new node on

    Args:
        cores (int): Number of cores the to be scheduled node requires

    Returns:
        int: Index of the host that will run the new machine
    """
    least_index = -1
    least_util = -1
    for i, host in enumerate(settings.config["hosts"]):
        # Ignore hosts on which we can't fit the node
        if host.cores_free < cores:
            continue

        util = host.cores_free / host.cores
        if util > least_util:
            least_util = util
            least_index = i

    if least_index == -1 or least_util == -1:
        logging.error("ERROR: Could not find a host to schedule node onto")
        sys.exit()

    return least_index


def _schedule_equal(layer):
    """Distribute Machines equally over the available machines, based on utilization.
    Externally hosted machines (e.g., as cloud VMs) are always attached to the primary host,
    which is the host on which Continuum is invoked.

    Args:
        layer (dict): Layer to do scheduling for
    """
    logging.info(f"Schedule for layer [{layer['name']}] based on utilization")
    provider = settings.get_providers(layer_name=layer)[0]

    for _ in provider["nodes"]:
        # Find the host on which to schedule this node
        if provider["interface"].is_external():
            i = 0
        else:
            i = _host_least_util(provider["cores"])

        # Add the new machine/node to the host
        machine = m.Machine(layer, provider)
        settings.config["hosts"][i].machines.append(machine)

        if "machines" not in layer:
            layer["machines"] = []

        layer["machines"].append(machine)

        # Do accounting: Update free cpu cores on this machine
        if not provider["interface"].is_external():
            settings.config["hosts"][i].cores_free -= provider["cores"]


def _create_tmp_dir():
    """Generate a temporary directory for generated files. This directory is located inside the
    benchmark git repository. Later, that data will be sent to each physical machine's
    config["base_path"]/.continuum directory.
    """
    logging.info("Create a temporary directory for generated files")
    path = os.path.join(settings.config["base"], ".tmp")
    command = f"rm -rf {path} && mkdir {path}"
    output, error = settings.process(command, shell=True)[0]

    if error:
        logging.error("".join(error))
        sys.exit()
    elif output:
        logging.error("".join(output))
        sys.exit()


def _delete_old_content():
    """Delete continuum content from previous runs, excluding base images"""
    commands = []
    for host in settings.config["hosts"]:
        # Delete old content except QEMU images in /images
        path = f"{settings.config['base_path']}/.continuum"
        command = (
            f"find {path} -mindepth 1 ! -regex '^{path}/images\(/.*\)?' -delete && "
            f"rm -rf {path}/images/*gcp* && "
            f"rm -rf {path}/images/.gcp* && "
            f"rm -rf {path}/images/*.tf"
        )

        # For remote hosts, add SSH to command
        if not host.is_local:
            command = f"ssh {host.name} '{command}]'"

        commands.append(command)

    results = settings.process(commands, shell=True)
    for output, error in results:
        if error and not all("No such file or directory" in line for line in error):
            logging.error("".join(error))
            sys.exit()
        elif output:
            logging.error("".join(output))
            sys.exit()


def _create_continuum_dir():
    """Create the .continuum and .continuum/images folders for storage"""
    commands = []
    for host in settings.config["hosts"]:
        if host.is_local:
            command = "mkdir -p %s/.continuum && mkdir -p %s/.continuum/images" % (
                (settings.config["base_path"],) * 2
            )
        else:
            command = 'ssh %s "mkdir -p %s/.continuum && mkdir -p %s/.continuum/images' % (
                (host.name,) + (settings.config["base_path"],) * 2
            )

        commands.append(command)

    results = settings.process(commands, shell=True)

    for (output, error), command in zip(results, commands):
        if error:
            logging.error("Command: %s", command)
            logging.error("".join(error))
            sys.exit()
        elif output:
            logging.error("Command: %s", command)
            logging.error("".join(output))
            sys.exit()


def _docker_registry():
    """Create and fill a local, private docker registry with the images needed for the benchmark.
    This is to prevent each spawned VM to pull from DockerHub, which has a rate limit.
    """
    logging.info("Create local Docker registry")
    need_pull = [True for _ in range(len(settings.config["images"]))]

    # Check if registry is up
    command = ["curl", "%s/v2/_catalog" % (settings.config["registry"])]
    output, error = settings.process(command)[0]

    if error and any("Failed to connect to" in line for line in error):
        # Not yet up, so launch
        port = settings.config["registry"].split(":")[-1]
        command = (
            f"docker run -d -p {port}:{port} -e REGISTRY_STORAGE_DELETE_ENABLED=true "
            f"--restart=always --name registry registry:2"
        )
        _, error = settings.process(command.split(" "))[0]

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
    elif not settings.config["docker_pull"]:
        # Registry is already up, check if containers are present
        repos = json.loads(output[0])["repositories"]

        for i, image in enumerate(settings.config["images"].values()):
            if image.split(":")[1] in repos:
                need_pull[i] = False

    # Pull images which aren't present yet in the registry
    for i, (image_key, pull) in enumerate(zip(settings.config["images"], need_pull)):
        if not pull:
            continue

        # Kubecontrol images need different splitting
        image = settings.config["images"][image_key]
        if "kubecontrol" in image_key:
            dest = os.path.join(settings.config["registry"], image.split("/")[1])
        else:
            dest = os.path.join(settings.config["registry"], image.split(":")[1])

        commands = [
            ["docker", "pull", image],
            ["docker", "tag", image, dest],
            ["docker", "push", dest],
        ]

        for command in commands:
            output, error = settings.process(command)[0]

            if error:
                logging.error("".join(error))
                sys.exit()


def start():
    """Create and manage infrastructure

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    settings.config["hosts"] = h.init()

    # schedule_equal is default, and pin only when explicitly mentioned by user
    # Schedule per layer, because scheduling algorithm may differ
    # Note: We don't schedule or create base machines, that's provider-specific
    for layer in settings.get_layers():
        provider = settings.get_providers(layer_name=layer["name"])

        cpu_pin = False
        if "cpu_pin" in settings.config["provider_init"][provider["name"]]:
            cpu_pin = settings.config["provider_init"][provider["name"]]["cpu_pin"]

        if cpu_pin:
            _schedule_pin(layer)
        else:
            _schedule_equal(layer)

    # Remove hosts that didn't get any Machines assigned
    h.remove_idle()

    # Delete old resources (this happens per provider as we can't control old layers)
    for provider in settings.get_providers(flat=True):
        provider["interface"].delete_vms()

    # Prepare storage for Continuum files
    _create_tmp_dir()
    _delete_old_content()
    _create_continuum_dir()

    # Sets names of machines, and IPs if already present (otherwise do that in module internally)
    for provider, layer in zip(settings.get_providers(), settings.get_layers()):
        provider["interface"].set_ip_names(layer)

    # Print updated config file after creating Host and Machine objects
    input_parser.print_input()

    # Create a registry as long as one container image is required
    if settings.config["images"]:
        _docker_registry()

    # Create the infrastructure. Call each provider only once, with one or multiple layers
    provider_layers = {}
    for layer in settings.get_layers():
        provider = settings.get_providers(layer_name=layer["name"])
        if provider["name"] in provider_layers:
            provider_layers[provider["name"]].append(layer)
        else:
            provider_layers[provider["name"]] = [layer]

    for provider in provider_layers:
        provider["interface"].start(provider_layers[provider])

    # Check if user wants emulation for a specific layer, and if provider supports it
    for layer in settings.get_layers():
        if "network" in layer["infrastructure"]:
            network.start(layer)

    if settings.config["netperf"]:
        network.benchmark()


def finish():
    """Execute code or print information to users at the end of a Continuum run"""
    for provider in settings.get_providers():
        provider["interface"].finish()
