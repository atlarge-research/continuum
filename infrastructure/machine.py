"""\
Define Machine object and functions to work with this object
The Machine object represents a physical machine used to run this benchmark
"""

import sys
import logging
import os
import subprocess
import re
import getpass


class Machine:
    def __init__(self, name, is_local):
        """Initialize the object

        Args:
            name (str): Name of this node, also functions as ssh target
            is_local (bool): Is this the machine on which the benchmark is started by the user
        """
        self.name = name
        self.is_local = is_local

        # Name with only alphanumeric characters
        self.name_sanitized = re.sub(r"\W+", "", name)

        # Assume user@ip as name for remote nodes
        if is_local:
            self.user = str(getpass.getuser())
            self.ip = None
        else:
            self.user = name.split("@")[0]
            self.ip = name.split("@")[1]

        # Cores on this machine
        self.cores = None

        # VM info
        self.cloud_controller = None
        self.clouds = None
        self.edges = None
        self.endpoints = None

        self.cloud_controller_ips = []
        self.cloud_ips = []
        self.edge_ips = []
        self.endpoint_ips = []
        self.base_ips = []

        self.cloud_controller_names = []
        self.cloud_names = []
        self.edge_names = []
        self.endpoint_names = []
        self.base_names = []

    def __repr__(self):
        """Returns this string when called as print(machine_object)"""
        return """
[ MACHINE NAME: %20s ]
IS_LOCAL                %s
NAME_SANITIZED          %s
USER                    %s
IP                      %s
CORES                   %i
CLOUD_CONTROLLER        %i
CLOUDS                  %i
EDGES                   %i
ENDPOINTS               %i
CLOUD_CONTROLLER_IPS    %s
CLOUD_IPS               %s
EDGE_IPS                %s
ENDPOINT_IPS            %s
BASE_IPS                %s
CLOUD_CONTROLLER_NAMES  %s
CLOUD_NAMES             %s
EDGE_NAMES              %s
ENDPOINT_NAMES          %s
BASE_NAMES              %s""" % (
            self.name,
            str(self.is_local),
            self.name_sanitized,
            self.user,
            self.ip,
            self.cores,
            self.cloud_controller,
            self.clouds,
            self.edges,
            self.endpoints,
            ", ".join(self.cloud_controller_ips),
            ", ".join(self.cloud_ips),
            ", ".join(self.edge_ips),
            ", ".join(self.endpoint_ips),
            ", ".join(self.base_ips),
            ", ".join(self.cloud_controller_names),
            ", ".join(self.cloud_names),
            ", ".join(self.edge_names),
            ", ".join(self.endpoint_names),
            ", ".join(self.base_names),
        )

    def process(
        self, command, shell=False, env=None, output=True, ssh=False, ssh_target=None
    ):
        """Execute a process using the subprocess library, and return the output/error or the process

        Args:
            command (str or list(str)): Command to be executed. Either a string can be given
                (when using the shell) or a list of strings (when not using the shell)
            shell (bool, optional): Use the shell for the subprocess. Defaults to False.
            env (dict, optional): Environment variables. Defaults to None.
            output (bool, optional): Return the output and error, or the process itself. Defaults to True.
            ssh (bool, optional): Prepend SSH command if machine is not local. Default to False
            ssh_target (str, optional): VM to SSH into (instead of physical machine). Default to None

        Returns:
            (list(str), list(str)) OR subprocess object: Return either the output and error generated
                by this process, or the process object itself.
        """
        executable = None
        if shell == True:
            executable = "/bin/bash"

        if ssh:
            if not (self.is_local and ssh_target == None):
                if ssh_target == None:
                    add = ["ssh", self.name]
                else:
                    add = [
                        "ssh",
                        ssh_target,
                        "-i",
                        str(os.getenv("HOME")) + "/.ssh/id_rsa_benchmark",
                    ]

                if type(command) == str:
                    command = " ".join(add) + " " + command
                elif type(command) == list:
                    command = add + command
                else:
                    logging.error(
                        "ERROR: Command is not type str or list, could not add ssh info.\nCommand: %s"
                        % (command)
                    )
                    sys.exit()

        logging.debug("Start subprocess: %s" % (command))
        process = subprocess.Popen(
            command,
            shell=shell,
            executable=executable,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if output:
            output = [line.decode("utf-8") for line in process.stdout.readlines()]
            error = [line.decode("utf-8") for line in process.stderr.readlines()]
            return output, error
        else:
            return process

    def check_hardware(self):
        """Get the amount of physical cores for this machine.
        This automatically functions as reachability check for this machine.
        """
        logging.info("Check hardware of node %s" % (self.name))
        command = "lscpu"

        if self.is_local:
            command = [command]
        else:
            command = ["ssh", self.name, command]

        output, error = self.process(command)

        if output == []:
            logging.error("".join(error))
            sys.exit()
        else:
            threads = -1
            threads_per_core = -1
            for line in output:
                if line.startswith("CPU(s):"):
                    threads = int(line.split(":")[-1])
                if line.startswith("Thread(s) per core:"):
                    threads_per_core = int(line.split(":")[-1])

            if threads == -1 or threads_per_core == -1:
                logging.error(
                    "Command did not produce the expected output: %s"
                    % ("".join(output))
                )
                sys.exit()

            logging.debug(
                "Threads: %s | Threads_per_core: %s" % (threads, threads_per_core)
            )

            self.cores = int(threads / threads_per_core)

    def copy_files(self, source, dest, recursive=False):
        """Copy files from host machine to destination machine.

        Args:
            source (str): Source file
            dest (str): Destination file
            recursive (bool, optional): Copy recursively (default: false)

        Returns:
            process: The output of the copy command
        """
        rec = ""
        if recursive:
            rec = "-r "

        if self.is_local:
            command = ["cp " + rec + source + " " + dest]
        else:
            command = ["scp " + rec + source + " " + dest]

        return self.process(command, shell=True)


def make_machine_objects(config):
    """Initialize machine objects

    Args:
        config (dict): Parsed configuration

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    logging.info("Initialize machine objects")
    machines = []
    names = ["local"]
    if "external_physical_machines" in config["infrastructure"]:
        names += config["infrastructure"]["external_physical_machines"]

    for name in names:
        machine = Machine(name, "local" in name)
        machines.append(machine)

    return machines


def remove_idle(machines, nodes_per_machine):
    """Check whether each machine will actually be used according to the scheduler.
    Remove the machines that won't be used.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    logging.info("Update machine list based on whether they will actually be used")
    new_machines = []
    new_nodes_per_machine = []
    for machine, nodes in zip(machines, nodes_per_machine):
        if nodes["cloud"] + nodes["edge"] + nodes["endpoint"] > 0:
            new_machines.append(machine)
            new_nodes_per_machine.append(nodes)

    m1 = "" if len(machines) <= 1 else "s"
    m2 = "" if len(new_machines) <= 1 else "s"
    logging.debug(
        "User offered %i machine%s, we will use %i machine%s"
        % (len(machines), m1, len(new_machines), m2)
    )
    return new_machines, new_nodes_per_machine


def gather_ssh(config, machines):
    """Get a list of all VM name@ip for SSH, save to config for easy access

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.debug("Get ips of controllers/workers")
    cloud_ssh = []
    edge_ssh = []
    endpoint_ssh = []

    for machine in machines:
        for name, ip in zip(
            machine.cloud_controller_names + machine.cloud_names,
            machine.cloud_controller_ips + machine.cloud_ips,
        ):
            cloud_ssh += [name + "@" + ip]

        for name, ip in zip(machine.edge_names, machine.edge_ips):
            edge_ssh += [name + "@" + ip]

        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            endpoint_ssh += [name + "@" + ip]

    config["cloud_ssh"] = cloud_ssh
    config["edge_ssh"] = edge_ssh
    config["endpoint_ssh"] = endpoint_ssh

    logging.debug("Cloud SSH: " + ", ".join(config["cloud_ssh"]))
    logging.debug("Edge SSH: " + ", ".join(config["edge_ssh"]))
    logging.debug("Endpoint SSH: " + ", ".join(config["endpoint_ssh"]))


def gather_ips(config, machines):
    """Get a list of all VM ips, save to config for easy access

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.debug("Get ips of controllers/workers")
    control_ips = []
    cloud_ips = []
    edge_ips = []
    endpoint_ips = []
    base_ips = []

    for machine in machines:
        control_ips += machine.cloud_controller_ips
        cloud_ips += machine.cloud_ips
        edge_ips += machine.edge_ips
        endpoint_ips += machine.endpoint_ips
        base_ips += machine.base_ips

    config["control_ips"] = control_ips
    config["cloud_ips"] = cloud_ips
    config["edge_ips"] = edge_ips
    config["endpoint_ips"] = endpoint_ips
    config["base_ips"] = base_ips

    logging.debug("Control IPs: " + ", ".join(config["control_ips"]))
    logging.debug("Cloud IPs: " + ", ".join(config["cloud_ips"]))
    logging.debug("Edge IPs: " + ", ".join(config["edge_ips"]))
    logging.debug("Endpoint IPs: " + ", ".join(config["endpoint_ips"]))
    logging.debug("Base IPs: " + ", ".join(config["base_ips"]))


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
    middle_ip = config["middleIP"]
    postfix_ip = config["postfixIP_lower"]

    middle_ip_base = config["middleIP_base"]
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

            ip = "%s.%s.%s" % (config["prefixIP"], middle_ip, postfix_ip)
            machine.cloud_controller_ips.append(ip)
            machine.cloud_controller_names.append("cloud_controller")
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)
        else:
            machine.cloud_controller = 0
            machine.clouds = nodes["cloud"]

        machine.edges = nodes["edge"]
        machine.endpoints = nodes["endpoint"]

        # Set IP / name for cloud
        for _ in range(machine.clouds):
            ip = "%s.%s.%s" % (config["prefixIP"], middle_ip, postfix_ip)
            machine.cloud_ips.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "cloud" + str(cloud_index)
            machine.cloud_names.append(name)
            cloud_index += 1

        # Set IP / name for edge
        for _ in range(machine.edges):
            ip = "%s.%s.%s" % (config["prefixIP"], middle_ip, postfix_ip)
            machine.edge_ips.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "edge" + str(edge_index)
            machine.edge_names.append(name)
            edge_index += 1

        # Set IP / name for endpoint
        for _ in range(machine.endpoints):
            ip = "%s.%s.%s" % (config["prefixIP"], middle_ip, postfix_ip)
            machine.endpoint_ips.append(ip)
            middle_ip, postfix_ip = update_ip(config, middle_ip, postfix_ip)

            name = "endpoint" + str(endpoint_index)
            machine.endpoint_names.append(name)
            endpoint_index += 1

        # Set IP / name for base image(s)
        if config["infrastructure"]["infra_only"]:
            machine.base_ips.append("%s.%s.%s" % (config["prefixIP"], middle_ip_base, postfix_ip_base))
            machine.base_names.append("base" + str(i))
            middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)
        else:
            # Use Kubeedge setup code for mist computing
            rm = config["benchmark"]["resource_manager"]
            if config["benchmark"]["resource_manager"] == "mist":
                rm = "kubeedge"

            if machine.cloud_controller + machine.clouds > 0:
                machine.base_ips.append("%s.%s.%s" % (config["prefixIP"], middle_ip_base, postfix_ip_base))
                machine.base_names.append("base_cloud_%s%i" % (rm, i))
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)

            if machine.edges > 0:
                machine.base_ips.append("%s.%s.%s" % (config["prefixIP"], middle_ip_base, postfix_ip_base))
                machine.base_names.append("base_edge_%s%i" % (rm, i))
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)

            if machine.endpoints > 0:
                machine.base_ips.append("%s.%s.%s" % (config["prefixIP"], middle_ip_base, postfix_ip_base))
                machine.base_names.append("base_endpoint%i" % (i))
                middle_ip_base, postfix_ip_base = update_ip(config, middle_ip_base, postfix_ip_base)


def print_schedule(machines):
    """Print the VM to physical machine scheduling

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("-" * 78)
    logging.info("Schedule of VMs and containers on physical machines")
    logging.info("-" * 78)

    logging.info(
        "%-30s %-15s %-15s %-15s"
        % ("Machine", "Cloud nodes", "Edge nodes", "Endpoints")
    )

    for machine in machines:
        logging.info(
            "%-30s %-15s %-15s %-15s"
            % (
                machine.name,
                machine.cloud_controller + machine.clouds,
                machine.edges,
                machine.endpoints,
            )
        )

    logging.info("-" * 78)

