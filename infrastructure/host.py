"""\
Define a Host class and helper functions that represent the physical machines Continuum runs on.
Continuum uses at least 1 Host object, namely the physical machine on which Continuum is invoked.

A Host runs multiple Machines (see machine.py). 
Machines are the provisioned infrastructure, such as cloud or edge VMs. 
A Host can support multiple Machines with various infrastructure providers.

Machines that are hosted on physical machines we can't control, such as AWS cloud VMs, are added
as Machines to the main Host (the one Continuum was invoked on). We don't make a new Host object
for these as we can't control the physical hardware, which is required to operate on hosts.

This is how Host and Machine objects are added to the config (presented as YML)
---
hosts:
- name: local
  ...
  machines:         <- All machines deployed/managed on this host
  - name: cloud0    <- This machine is the same as
    ...
- name: node3
  ...
layer:
- name: cloud
  machines:
  - name: cloud0    <- This machine. These are pointers so the same object
    ...
"""

import getpass
import logging
import re
import sys

import settings


class Host:
    """Class representing physical machines Continuum uses to deploy infrastructure on"""

    def __init__(self, name):
        """Initialize the Host object

        Args:
            name (str): Name of this host as 'user@host'
        """
        if name == "local":
            # For the machine on which Continuum is executed
            self.is_local = True
            self.ssh = str(getpass.getuser())
            self.name = str(getpass.getuser())
            self.ip = ""
        else:
            # For all external machines
            self.is_local = False
            self.ssh = name
            self.name = name.split("@")[0]
            self.ip = name.split("@")[1]

        # Name with only alphanumeric characters
        self.name_sanitized = re.sub(r"\W+", "", self.name)

        # Cores on this machine
        self.cores = self._check_hardware()
        self.cores_free = self.cores

        self.machines = []

    def __repr__(self):
        """Returns this string on print"""
        machines = ""
        if len(self.machines) > 0:
            machines = "\nMACHINES\n"
            for machine in self.machines:
                machines += f"- NAME          {machine.ssh}"

        return """
[ HOST ]
    SSH             %s
    NAME            %s
    NAME_SANITIZED  %s
    IP              %s
    CORES           %i
    CORES_FREE      %i%s""" % (
            self.ssh,
            self.name,
            self.name_sanitized,
            self.ip,
            self.cores,
            self.cores_free,
            machines,
        )

    def _get_machine(self, prop, layer=""):
        values = []
        for machine in self.machines:
            if layer == "" or machine.layer == layer:
                values.append(getattr(machine, prop))

        return values

    def get_machine_users(self, layer=""):
        """Get the names of all machines running on this host or on a specific layer

        Args:
            layer (str, optional): Layer to filter for. Defaults to "".

        Returns:
            list(str): List of names of all machines running on this host
        """
        return self._get_machine("user", layer)

    def get_machine_ips(self, layer=""):
        """Get the IP of all machines running on this host

        Returns:
            list(str): List of IPs of all machines running on this host
        """
        return self._get_machine("ip", layer)

    def get_machine_sshs(self, layer=""):
        """Get the SSH addresses of all machines running on this host

        Returns:
            list(str): List of SSH addresses of all machines running on this host
        """
        return self._get_machine("ssh", layer)

    def _check_hardware(self):
        """Get the amount of physical cores on this host.
        This automatically functions as reachability check for this host.
        """
        logging.info("Check hardware of node %s", self.name)
        command = ["lscpu"]

        output, error = settings.process(command, ssh=self)[0]

        if not output:
            logging.error("".join(error))
            sys.exit()

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

        return int(threads / threads_per_core)


def init():
    """Initialize host objects

    Returns:
        list(Host object): List of host objects representing physical machines
    """
    logging.info("Initialize host objects")

    external = []
    for provider in settings.config["provider_init"]:
        if "external_physical_machines" in provider:
            e = [e.name for e in provider["external_physical_machines"]]
            external += e

    names = ["local"] + external
    hosts = []

    for name in names:
        host = Host(name)
        hosts.append(host)

    return hosts


def remove_idle():
    """Remove hosts that have no machines scheduled onto them"""
    logging.info("Update machine list based on whether they will actually be used")
    to_remove = []
    for host in settings.config["hosts"]:
        if len(host.machines) == 0:
            to_remove.append(host)

    for host in to_remove:
        settings.config["hosts"].remove(host)
