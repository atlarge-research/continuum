"""\
Define Machine object and functions to work with this object
The Machine object represents a physical machine used to run this benchmark
"""

import sys
import logging
import subprocess
import re
import getpass
import math


class Machine:
    """The Machine object represent one physical machine Continuum runs on.
    The object includes all information about the machine, mainly info on
    the virtual machines that run on that particular physical machine.
    """

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
            self.ip = ""
        else:
            self.user = name.split("@")[0]
            self.ip = name.split("@")[1]

        # Cores on this machine
        self.cores = 0

        # VM info
        self.cloud_controller = 0
        self.clouds = 0
        self.edges = 0
        self.endpoints = 0

        self.cloud_controller_ips = []
        self.cloud_ips = []
        self.edge_ips = []
        self.endpoint_ips = []
        self.base_ips = []

        # Internal IPs, used for communication between VMs
        # These IPs may differ from the external IPs, most notably for cloud providers
        self.cloud_controller_ips_internal = []
        self.cloud_ips_internal = []
        self.edge_ips_internal = []
        self.endpoint_ips_internal = []

        self.cloud_controller_names = []
        self.cloud_names = []
        self.edge_names = []
        self.endpoint_names = []
        self.base_names = []

    def __repr__(self):
        """Returns this string when called as print(machine_object)"""
        return """
[ MACHINE NAME: %20s ]
IS_LOCAL                    %s
NAME_SANITIZED              %s
USER                        %s
IP                          %s
CORES                       %i
CLOUD_CONTROLLER            %i
CLOUDS                      %i
EDGES                       %i
ENDPOINTS                   %i
CLOUD_CONTROLLER_IPS (int)  %s (%s)
CLOUD_IPS (int)             %s (%s)
EDGE_IPS (int)              %s (%s)
ENDPOINT_IPS (int)          %s (%s)
BASE_IPS                    %s
CLOUD_CONTROLLER_NAMES      %s
CLOUD_NAMES                 %s
EDGE_NAMES                  %s
ENDPOINT_NAMES              %s
BASE_NAMES                  %s""" % (
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
            ", ".join(self.cloud_controller_ips_internal),
            ", ".join(self.cloud_ips),
            ", ".join(self.cloud_ips_internal),
            ", ".join(self.edge_ips),
            ", ".join(self.edge_ips_internal),
            ", ".join(self.endpoint_ips),
            ", ".join(self.endpoint_ips_internal),
            ", ".join(self.base_ips),
            ", ".join(self.cloud_controller_names),
            ", ".join(self.cloud_names),
            ", ".join(self.edge_names),
            ", ".join(self.endpoint_names),
            ", ".join(self.base_names),
        )

    def process(
        self,
        config,
        command,
        shell=False,
        env=None,
        ssh=None,
        ssh_key=True,
        retryonoutput=False,
        wait=True,
    ):
        """Execute a process using the subprocess library, return the output/error of the process

        Args:
            command (str or list(str)): Command to be executed. Either a string can be given
                (when using the shell) or a list of strings (when not using the shell)
            config (dict): Parsed configuration
            shell (bool, optional): Use the shell for the subprocess. Defaults to False.
            env (dict, optional): Environment variables. Defaults to None.
            ssh (str, optional): VM to SSH into (instead of physical machine). Default to None
            ssh_key (bool, optional): Use the custom SSH key for VMs. Default to True
            retryonoutput (bool, optional): Retry command on empty output. Default to False
            wait (bool, optional): Should we wait for output? Default to true

        Returns:
            list(list(str), list(str)): Return a list of [output, error] lists, one per command.
        """
        # Set the right shell executable (such as bash, or pass it directly)
        executable = None
        if shell:
            executable = "/bin/bash"

        # You can pass a single string if you want to execute 1 command without bash
        # OR: Passing one list without bash, move into a nested list
        if isinstance(command, str) or (
            isinstance(command[0], str) and all(len(c.split(" ")) == 1 for c in command)
        ):
            command = [command]

        # Add SSH logic to the command
        if ssh is not None:
            # SSH can be a list of multiple SSHs
            if isinstance(ssh, str):
                ssh = [ssh]

            # User can pass a single ssh for many commands, fix that
            if len(ssh) == 1 and len(command) > 1:
                ssh = ssh * len(command)

            # Other way around: one command, many ssh commands
            if len(command) == 1 and len(ssh) > 1:
                command = command * len(ssh)

            for i, (c, s) in enumerate(zip(command, ssh)):
                if s is None:
                    # Don't SSH if no target was set
                    continue

                if self.is_local and s == self.name:
                    # You can't ssh to the machine you're already on
                    continue

                add = ["ssh", s]
                if ssh_key and s != self.name:
                    # You can only use this custom key to SSH to VMs, not to physical machines
                    add += ["-i", config["ssh_key"]]

                if shell:
                    # Use bash shell = use a string
                    command[i] = " ".join(add) + " " + c
                else:
                    # Don't use a shell, so a list
                    command[i] = add + c

        # Execute all commands, max 100 at a time
        batchsize = 100
        outputs = []

        new_retries = []

        # pylint: disable=consider-using-with

        for i in range(math.ceil(len(command) / batchsize)):
            processes = []
            for j, c in enumerate(command[i * batchsize : (i + 1) * batchsize]):
                logging.debug("Start subprocess: %s", c)
                process = subprocess.Popen(
                    c,
                    shell=shell,
                    executable=executable,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                processes.append(process)

            # We may not be interested in the output at all
            if not wait:
                continue

            # Get outputs for this batch of commmands (blocking)
            for j, process in enumerate(processes):
                # Use communicate() to prevent buffer overflows
                stdout, stderr = process.communicate()
                output = stdout.decode("utf-8").split("\n")
                error = stderr.decode("utf-8").split("\n")

                # Byproduct of split
                if len(output) >= 1 and output[-1] == "":
                    output = output[:-1]
                if len(error) >= 1 and error[-1] == "":
                    error = error[:-1]

                outputs.append([output, error])

                if retryonoutput and not output:
                    new_retries.append(i * batchsize + j)

        # Retry commands with empty output
        max_tries = 5
        for t in range(max_tries):
            if not new_retries:
                break

            retries = new_retries
            new_retries = []

            retries.sort()
            processes = []

            for i in retries:
                logging.debug("Retry %i, subprocess %i: %s", t, i, command[i])
                process = subprocess.Popen(
                    command[i],
                    shell=shell,
                    executable=executable,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                processes.append(process)

            # Get outputs for this batch of commmands (blocking)
            for i, process in zip(retries, processes):
                stdout, stderr = process.communicate()
                output = stdout.decode("utf-8").split("\n")
                error = stderr.decode("utf-8").split("\n")

                # Byproduct of split
                if len(output) >= 1 and output[-1] == "":
                    output = output[:-1]
                if len(error) >= 1 and error[-1] == "":
                    error = error[:-1]

                outputs[i] = [output, error]

                if not output:
                    new_retries.append(i)

        # pylint: enable=consider-using-with

        return outputs

    def check_hardware(self, config):
        """Get the amount of physical cores for this machine.
        This automatically functions as reachability check for this machine.
        """
        # GCP and AWS uses Terraform (cloud), so the number of local cores won't matter
        # Just set the value extremely high so everything can be scheduled on the
        # same "machine" (your local machine is seen as the cloud provider)
        if config["infrastructure"]["provider"] in ["gcp", "aws"]:
            self.cores = 100000
            return

        logging.info("Check hardware of node %s", self.name)
        command = "lscpu"

        if self.is_local:
            command = [command]
        else:
            command = ["ssh", self.name, command]

        output, error = self.process(config, command)[0]

        if not output:
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
                logging.error("Command did not produce the expected output: %s", "".join(output))
                sys.exit()

            logging.debug("Threads: %s | Threads_per_core: %s", threads, threads_per_core)

            self.cores = int(threads / threads_per_core)

    def copy_files(self, config, source, dest, recursive=False):
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

        return self.process(config, command, shell=True)[0]


def make_machine_objects(config):
    """Initialize machine objects

    Args:
        config (dict): Parsed configuration

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    logging.info("Initialize machine objects")
    machines = []
    names = ["local"] + config["infrastructure"]["external_physical_machines"]

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
        "User offered %i machine%s, we will use %i machine%s",
        len(machines),
        m1,
        len(new_machines),
        m2,
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

    logging.debug("Cloud SSH: %s", ", ".join(config["cloud_ssh"]))
    logging.debug("Edge SSH: %s", ", ".join(config["edge_ssh"]))
    logging.debug("Endpoint SSH: %s", ", ".join(config["endpoint_ssh"]))


def gather_ips(config, machines):
    """Get a list of all VM ips, save to config for easy access

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.debug("Get ips of controllers/workers")
    config["control_ips"] = [ip for machine in machines for ip in machine.cloud_controller_ips]
    config["cloud_ips"] = [ip for machine in machines for ip in machine.cloud_ips]
    config["edge_ips"] = [ip for machine in machines for ip in machine.edge_ips]
    config["endpoint_ips"] = [ip for machine in machines for ip in machine.endpoint_ips]
    config["base_ips"] = [ip for machine in machines for ip in machine.base_ips]

    config["control_ips_internal"] = [
        ip for machine in machines for ip in machine.cloud_controller_ips_internal
    ]
    config["cloud_ips_internal"] = [ip for machine in machines for ip in machine.cloud_ips_internal]
    config["edge_ips_internal"] = [ip for machine in machines for ip in machine.edge_ips_internal]
    config["endpoint_ips_internal"] = [
        ip for machine in machines for ip in machine.endpoint_ips_internal
    ]

    logging.debug("Control IPs: %s", ", ".join(config["control_ips"]))
    logging.debug("Cloud IPs: %s", ", ".join(config["cloud_ips"]))
    logging.debug("Edge IPs: %s", ", ".join(config["edge_ips"]))
    logging.debug("Endpoint IPs: %s", ", ".join(config["endpoint_ips"]))
    logging.debug("Base IPs: %s", ", ".join(config["base_ips"]))


def print_schedule(machines):
    """Print the VM to physical machine scheduling

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("-" * 78)
    logging.info("Schedule of VMs and containers on physical machines")
    logging.info("-" * 78)

    logging.info("%-30s %-15s %-15s %-15s", "Machine", "Cloud nodes", "Edge nodes", "Endpoints")

    for machine in machines:
        logging.info(
            "%-30s %-15s %-15s %-15s",
            machine.name,
            machine.cloud_controller + machine.clouds,
            machine.edges,
            machine.endpoints,
        )

    logging.info("-" * 78)
