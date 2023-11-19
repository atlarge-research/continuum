"""\
This file defines the two global variables used in Continuum: config and machines
- config (dict): Parsed configuration
    - Will be set after parsing the user input configuration file
    - Contains the global configuration of Continuum
- machines (list(Machine object)): List of machine objects representing physical machines
    - Will be set at the start of the infrastructure deployment phase
    - Contains the information of all provisioned (virtual) machines and other infrastructure
    - This is used by Continuum to interact with the provisioned infrastructure
"""

import logging
import math
import subprocess
import sys

from infrastructure import host as h
from infrastructure import machine as m

config = {}


def get_layers(layer_name=""):
    """Return a list of all layers in the config, optionally filter for a specific layer by name

    Args:
        layer_name (str, optional): Name of a specific layer to filter for. Defaults to "".

    Returns:
        list(str): List of layers
    """
    if "layer" not in config:
        logging.error("ERROR: Key 'layer' required in configuration but not found")
        sys.exit()

    layers = []
    for layer in config["layer"]:
        if layer_name != "":
            # Filter a specific layer by name
            if layer["name"] == layer_name:
                layers.append(layer)
        else:
            layers.append(layer)

    if layer_name == "" and len(layers) == 0:
        logging.error("ERROR: Found 0 layers in the config - there should be at least 1")
        sys.exit()

    return layers


def get_providers(layer_name="", flat=False):
    """Get the sub-dictionary containing the infrastructure provider info of one or all layers

    -> Example YML
    layer:
    - name: cloud
      infrastructure
        qemu:
          nodes: 2
          cores: 4
          ...

    -> Output of get_providers("cloud")
    {
        nodes: 2,
        cores: 4,
        ...
    }

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".
        flat (bool, optional): Flatten the returned list to unique providers

    Returns:
        list(dict): List of the dicts containing the infra provider info per layer
    """
    providers = []
    for layer in get_layers(layer_name=layer_name):
        providers.append(get_layer_provider(layer["name"]))

    if len(providers) == 0:
        logging.error(f"ERROR: No providers found for layer [{layer_name}]")
        sys.exit()

    if layer_name != "" and len(providers) != 1:
        logging.error(f"ERROR: Found multiple providers for layer {layer_name}")
        logging.error(providers)
        sys.exit()

    if flat:
        providers = list(set(providers))

    return providers


def get_layer_provider(layer_name):
    """Get the infrastructure provider of a specific layer

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".

    Returns:
        dict: Provider dict of a specific layer
    """
    # Remove network and storage entries
    layer = get_layers(layer_name=layer_name)[0]

    if "infrastructure" not in layer:
        logging.error("ERROR: Expected infrastructure keyword in layer, but not found")
        sys.exit()

    provider_names = list(layer["infrastructure"].keys())

    # Remove network and storage entries
    to_remove = ["network", "storage"]
    for name in to_remove:
        if name in provider_names:
            provider_names.remove(name)

    if len(provider_names) != 1:
        logging.error(
            f"ERROR: Expected exactly 1 provider per layer, found {', '.join(provider_names)}"
        )
        sys.exit()

    provider_name = provider_names[0]
    return layer["infrastructure"][provider_name]


def get_package_names(layer_name=""):
    """Get the names of software packages used in all or specific layers

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".

    Returns:
        list(str): List of software package names
    """
    modules = []

    for layer in get_layers(layer_name=layer_name):
        if "software" not in layer:
            continue

        layer_modules = list(layer["software"].keys())
        if len(layer_modules) != len(list(set(layer_modules))):
            logging.error(
                "ERROR: Duplicate packages in layer %s not allowed: %s"
                % (layer["name"], ", ".join(layer_modules))
            )
            sys.exit()

        modules += layer_modules

    # Filter out duplicate modules between layers
    return list(set(modules))


def get_packages(layer_name="", flat=False):
    """Get all software packages

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".
        flat (bool, optional): Get packages across all layers without duplicates. Defaults to False.

    Returns:
        list(dict): List of software packages, described as dict per package
    """
    packages = []
    for layer in get_layers(layer_name=layer_name):
        p = []
        for package_name in layer["software"]:
            p.append(layer["software"][package_name])

        if flat:
            packages += p
        else:
            packages.append(p)

    # Remove duplicates
    if flat:
        packages = list(set(packages))

    return packages


def get_benchmark():
    """Get the benchmark (only one allowed)

    Returns:
        dict: Benchmark description
    """
    if "benchmark" not in config:
        return {}

    keys = list(config["benchmark"].keys())
    if len(keys) == 0:
        logging.error("ERROR: Benchmark keyword defined in config but empty")
        sys.exit()
    if len(keys) > 1:
        logging.error("ERROR: Continuum should only support 1 benchmark at a time")
        sys.exit()

    return config["benchmark"][keys[0]]


def get_sshs(layer_name=""):
    """Get SSH addresses of all provisioned machines - or from machines of a specific layer

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".

    Returns:
        list(str): List of ssh addresses
    """
    addresses = []

    for layer in get_layers(layer_name=layer_name):
        if "ssh" not in layer:
            logging.error("ERROR: SSH addresses of this layer haven't been set yet")
            sys.exit()

        addresses.append(layer["ssh"])

    # Provisioned machines should be unique
    if len(addresses) != len(list(set(addresses))):
        logging.error("ERROR: Duplicate provisioned machines between layers!")
        sys.exit()

    return addresses


def get_machines(layer_name="", base=False):
    """Get all machines of one or all layers

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".
        base (bool, optional): Only return base machines. Defaults to False.

    Returns:
        list(list(Machine)): Get all IPs per layer - type depends on flat argument
    """
    machines = []
    for layer in get_layers(layer_name=layer_name):
        machs = []
        for mach in layer["machines"]:
            if not base or (base and mach.base):
                mach.append(m)

        machines += machs

    return machines


def get_ips(layer_name="", base=0, flat=False, internal=False):
    """Get all IPs from one or all layers

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".
        base (int, optional): Don't get base images (0), get all images including base images (1),
            or get only the base images (2). Defaults to 0.
        flat (bool, optional): Get ips across all layers as a flat list. Defaults to False.
        internal (bool, optional): Get internal ip addresses instead of external

    Returns:
        list(list(str)) or list(str): Get all IPs per layer - type depends on flat argument
    """
    ips = []
    for layer_machines in get_machines(layer_name=layer_name):
        ip = []
        for machine in layer_machines:
            if ((base == 1 or base == 2) and machine.base) or (
                (base == 0 or base == 1) and not machine.base
            ):
                if internal:
                    ip.append(machine.ip_internal)
                else:
                    ip.append(machine.ip)

        if flat:
            ips += ip
        else:
            ips.append(ip)

    return ips


def get_ssh_keys(layer_name=""):
    """Get the SSH key for each infrastructure layer (given 1 provider per layer).
    May filter for a specific layer

    Args:
        layer_name (str, optional): Filter for a specific layer by name. Defaults to "".

    Returns:
        list(str): List of ssh keys
    """
    # We can not search through provider_init directly, where the SSH keys are stored, as we don't
    # know which provider is running on which layer. We first need to find this by looping through
    # the layers and finding their providers.
    keys = []
    for layer in get_layers(layer_name=layer_name):
        provider = get_providers(layer_name=layer["name"])

        if provider["name"] not in config["provider_init"]:
            pass

        provider_init = config["provider_init"][provider["name"]]
        if "ssh_key" not in provider_init:
            pass

        key = provider_init["ssh_key"]
        keys.append(key)

    if len(keys) == 0:
        logging.error(f"ERROR: Could not find SSH key with filter [{layer_name}]")
        sys.exit()
    if layer_name != "" and len(keys) != 1:
        logging.error(f"ERROR: Found multiple keys for filter [{layer_name}]: {', '.join(keys)}")

    return keys


def get_ssh_key_host(provider_name=""):
    """Gather for each host the list of SSH keys per provider required on that host.
    For example, if host 1 uses 2 providers and host 2 uses 1 provider, the return value will be:
    '[[host1_key1, host1_key2], [host2_key1]]'

    Args:
        provider_name (str, optional): Name of the provider to filter for

    Returns:
        list(list(str)): List with for each host, a list of SSh keys required on that host
    """
    ssh_keys = []
    for host in config["hosts"]:
        # Get all unique providers for all machines running on this host
        providers = []
        for machine in host.machines:
            if provider_name == "" or provider_name == machine.provider:
                providers.append(machine.provider)

        providers = list(set(providers))

        # Get the corresponding SSH keys
        keys = []
        for provider in providers:
            keys.append(config["provider_init"][provider]["ssh_key"])

        # Note: Hierarchical list (so ssh_keys = [[],[],[]]
        ssh_keys.append(keys)

    return ssh_keys


# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------


def _process_command(command, shell):
    """Check if command falls in one of the four options below, and transform into option 3 or 4

    Accepted command types:
        1. "grep -ri 'key'"                     -> 1 command, shell=True
        2. ["grep", "-ri", "'key'"]             -> 1 command
        3. [["grep -ri 'key'"], ...]            -> 1 or more commands, shell=True
        4. [["grep", "-ri", "'key'"], ...]      -> 1 or more commands

    Args:
        command (str or list(str)): Command to be executed
        shell (bool): Use the shell for the subprocess

    Returns:
        list(list(str)): Command to execute as nested lists
    """
    if isinstance(command, str):
        # Option 1: "grep -ri 'key'"
        if not shell:
            logging.error("ERROR: Command is type string but shell = False")
            logging.error(command)
            sys.exit()

        # Transform Option 1 into Option 3
        command = [[command]]
    elif isinstance(command, list):
        if len(command) == 0:
            logging.error("ERROR: Command is an empty list")
            sys.exit()

        if all(isinstance(c, str) for c in command):
            # Option 2: ["grep", "-ri", "'key'"]
            if shell:
                logging.error("ERROR: Command is type list(str) but shell = True")
                logging.error(command)
                sys.exit()

            # Transform Option 2 into Option 4
            command = [command]
        elif all(isinstance(c, list) for c in command):
            # Option 3: [["grep -ri 'key'"], ...]
            # No dedicated option 3 - could also be option 4 with just a 1 word string
            if not all(len(c) for c in command):
                logging.error("ERROR: Command is type list(list()), but some are empty")
                logging.error(command)
                sys.exit()

            if not all(isinstance(c, str) for subc in command for c in subc):
                logging.error("ERROR: Command should be type list(list(str))")
                logging.error(command)
                sys.exit()

            if shell and not all(len(c) == 1 for c in command):
                # Option 3: [["grep -ri 'key'"], ...]
                # Option 4. [["grep", "-ri", "'key'"], ...]
                # Option 3 can be Option 4 if using a one word command ("ls")
                logging.error("ERROR: on shell=True, command strings can only be of length 1")
                logging.error(command)
                sys.exit()
        else:
            logging.error("ERROR: Command is a list, and should only have str and list items ")
            logging.error(command)
            sys.exit()
    else:
        logging.error(f"ERROR: Command should be type string or list, got {type(command)}")
        logging.error(command)

    return command


def _build_process_ssh(targets):
    """Create SSH prepend commands needed to execute a command on a specific host/machine.

    For example:
        targets = [Host(is_local=False), Machine()]
        returns: [["user@host"], ["user@host", "-i", "ssh-key-path"]]

    Args:
        targets (list(object)): List of Host and Machine objects

    Returns:
        list(list(str)): List of ssh prepend commands as list of strings, one sublist per target
    """
    sshs = []
    for target in targets:
        ssh = []
        if isinstance(target, h.Host):
            if not target.is_local:
                ssh += [target.ssh]
        elif isinstance(target, m.Machine):
            ssh += [target.ssh, "-i", config["provider_init"][target.provider]["ssh_key"]]
        else:
            logging.error("ERROR: ...")
            sys.exit()

        if ssh:
            ssh = ["ssh"] + ssh

        sshs.append(ssh)

    return sshs


def _process_ssh(command, shell, ssh):
    """Add supplied SSH info to the command(s)

    Accepted command types:
        1. [["grep -ri 'key'"], ...]            -> 1 or more commands, shell=True
        2. [["grep", "-ri", "'key'"], ...]      -> 1 or more commands

    Args:
        command (str or list(str)): Command to be executed
        shell (bool): Use the shell for the subprocess
        ssh (list(object), optional): List of hosts/machines objects to SSH to. Defaults to None.

    Returns:
        list(list(str)): Command to execute as nested lists
    """
    # Add SSH logic to the command
    if ssh is None:
        return command
    elif not (
        isinstance(ssh, list)
        and len(ssh)
        and all(isinstance(s, h.Host) or isinstance(s, m.Machine) for s in ssh)
    ):
        logging.error("ERROR: SSH should be a list of Host and Machine objects, found")
        logging.error(ssh)
        sys.exit()

    # Transform list of hosts/machines into ssh prepend commands
    # We get back something like [["user@host"], ["user@host", "-i", "ssh-key-path"]]
    ssh = _build_process_ssh(ssh)

    # Solve one-to-many mappings (one ssh to many commands or vice versa)
    if len(ssh) == 1:
        # User can pass a single ssh for many commands (one-to-many)
        ssh = [ssh[0] * len(command)]
    elif len(command) == 1:
        command = [command[0] * len(ssh)]
    elif len(ssh) != len(command):
        logging.error(f"ERROR: {len(ssh)} SSH addresses given with {len(command)} commands")
        sys.exit()

    # Attach SSH to each command
    # ssh and command are the same length, and both nested lists [[],...]
    for i, (c, s) in enumerate(zip(command, ssh)):
        # The physical machine Continuum runs on doesn't need SSH information
        if not s:
            continue

        if shell:
            command[i] = " ".join(s) + " " + c
        else:
            command[i] = s + c

    return command


def process(command, shell=False, env=None, ssh=None, retry_on_output=False, wait=True):
    """Execute a process using the subprocess library, return the output/error of the process
    For more information on accepted types per argument, check called functions.
    The commands are executed from the physical machine / host Continuum runs on

    Args:
        command (str or list(str)): Command to be executed
        shell (bool, optional): Use the shell for the subprocess. Defaults to False.
        env (dict, optional): Environment variables. Defaults to None.
        ssh (list(object), optional): List of hosts/machines objects to SSH to. Defaults to None.
        retry_on_output (bool, optional): Retry command on empty output. Defaults to False.
        wait (bool, optional): Should we wait for output? Defaults to True.

    Returns:
        list(list(str), list(str)): Return a list of [output, error] lists, one per command.
    """
    # Command will now be of type list(list(str))
    command = _process_command(command, shell)
    command = _process_ssh(command, shell, ssh)

    # Set the right shell executable (such as bash, or pass it directly)
    executable = None
    if shell:
        executable = "/bin/bash"

    # Hardcoded values for retrying and batch execution
    max_tries = 5
    batch_size = 100

    outputs = [None for _ in range(len(command))]

    # The indices of commands to execute. Start with all commands, and remove those that
    # complete successfully. Then, retry those command indices still in the list.
    new_tries = [i for i in range(len(command))]

    # pylint: disable=consider-using-with

    for t in range(max_tries):
        tries = new_tries

        # TODO (low priority)
        #  - Check if this sort statement can be removed or not
        # tries.sort()

        new_tries = []

        if t > 0 and tries:
            # Only print if there is actually something new to execute in the retry
            logging.debug(f"TRY {t+1}")

        # Execute commands in batches of size batch_size
        for i in range(math.ceil(len(tries) / batch_size)):
            # First, execute the commands and gather their processes
            processes = {}
            for try_index in tries[i * batch_size : (i + 1) * batch_size]:
                logging.debug("Start subprocess: %s", command[try_index])
                proc = subprocess.Popen(
                    command[try_index],
                    shell=shell,
                    executable=executable,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                processes[str(try_index)] = proc

            # We may not be interested in the output at all - fire and forget
            if not wait:
                continue

            # Second, check the outputs for this batch of commands (blocking)
            for try_index, proc in processes.values():
                # Use communicate() to prevent buffer overflows
                stdout, stderr = proc.communicate()
                output = stdout.decode("utf-8").split("\n")
                error = stderr.decode("utf-8").split("\n")

                # Byproduct of split
                if len(output) >= 1 and output[-1] == "":
                    output = output[:-1]
                if len(error) >= 1 and error[-1] == "":
                    error = error[:-1]

                # Retry if the user wants and there is no output
                # Otherwise, save the stdout and stderr, and continue
                if retry_on_output and not output:
                    new_tries.append(try_index)
                else:
                    outputs[try_index] = [output, error]

    # pylint: enable=consider-using-with

    # Outputs was filled with None - if there is still any left, some commands didn't execute
    # This should only happen because of an error in the source code, not because of user input
    if any(None in out for out in outputs):
        logging.error("Could not successfully execute all commands for an unknown reason")
        sys.exit()

    return outputs


def copy_files(source, dest, target=None, recursive=False):
    """Copy files from host machine to destination machine.

    Args:
        source (str): Source file
        dest (str): Destination file
        target (object, optional): Hosts or machine objects where to copy to. Defaults to None.
        recursive (bool, optional): Copy recursively. Defaults to False.

    Returns:
        process: The output of the copy command
    """
    if not isinstance(source, str):
        logging.error(f"ERROR: For copy, source should be type str, found {type(source)}")
        sys.exit()
    if not isinstance(dest, str):
        logging.error(f"ERROR: For copy, dest should be type str, found {type(dest)}")
        sys.exit()
    if not (isinstance(target, h.Host) or isinstance(target, m.Machine)):
        logging.error(f"ERROR: SSH target should be type Host or Machine, got {type(target)}")
        sys.exit()

    rec = ""
    if recursive:
        rec = "-r"

    if target is None:
        command = f"cp {rec} {source} {dest}"
    else:
        command = f"scp {rec} {source} {target.ssh}:{dest}"

    return process([[command]], shell=True)[0]
