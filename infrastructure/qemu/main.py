"""\
Create and use QEMU Vms
"""

import logging
import sys

from schema import And, Optional

import settings
from infrastructure import infrastructure
from infrastructure import machine as m
from . import deploy


class Module(infrastructure.Infrastructure):
    @staticmethod
    def add_options():
        """Add config options for a particular module

        Returns:
            tuple(schema): schema x2 to validate input yml
        """
        provider_init = {
            Optional("cpu_pin", default=False): And(bool, lambda x: x in [True, False]),
            Optional("prefixIP", default="192.168"): And(
                str,
                lambda x: len(x.split(".")) == 2
                and 0 < int(x.split(".")[0]) < 255
                and 0 < int(x.split(".")[1]) < 255,
            ),
            Optional("middleIP", default="100"): And(int, lambda x: 0 < x < 255),
            Optional("middleIP_base", default="90"): And(int, lambda x: 0 < x < 255),
            Optional("external_physical_machines"): [
                {
                    "name": And(str, lambda x: "@" in x),
                }
            ],
        }

        layer_infrastructure = {
            "nodes": And(int, lambda x: x >= 1),
            "cores": And(int, lambda x: x >= 1),
            "memory": And(int, lambda x: x >= 1),
            Optional("quota", default=1.0): And(float, lambda x: 0.1 <= x <= 1.0),
        }

        return provider_init, layer_infrastructure

    @staticmethod
    def verify_options(parser):
        """Verify the config from the module's requirements

        Args:
            parser (ArgumentParser): Argparse object
        """
        if settings.config["middleIP"] == settings.config["middleIP_base"]:
            parser.error("ERROR: middleIP == middleIP_base shouldn't happen")

        used = False
        for layer in settings.config["layer"]:
            if "qemu" in layer["infrastructure"]:
                used = True
                provider = layer["infrastructure"]["qemu"]

                # Verify storage
                if (
                    "storage" in provider
                    and provider["storage"]["read"] == -1
                    and provider["storage"]["write"] == -1
                ):
                    del provider["storage"]

                # Verify network
                if "network" in provider:
                    if len(provider["network"]) == 0:
                        parser.error("ERROR: QEMU network definition is empty")

                    if "link" in provider["network"]:
                        if len(provider["network"]["link"]) == 0:
                            parser.error("ERROR: Network per-link emulation defined without links")

                        for link in provider["network"]["link"]:
                            if list(link.keys()) == ["destination"]:
                                msg = (
                                    "ERROR: For per-link network emulation, "
                                    + "need at least latency or throughput defined"
                                )
                                parser.error(msg)

                            if (
                                link["latency_avg"] == -1
                                and link["latency_var"] >= 0.0
                                or link["latency_avg"] >= 0.0
                                and link["latency_var"] == -1
                            ):
                                msg = (
                                    "ERROR: For per-link network latency emulation, "
                                    + "both avg and var defined with a value >= 0.0"
                                )
                                parser.error(msg)

        if not used:
            parser.error("ERROR: QEMU isn't used as provider in any layer")
        if "qemu" not in settings.config["provider_init"]:
            parser.error("ERROR: QEMU missing from provider_init")

        for external_machine in settings.config["provider_init"]["external_physical_machines"]:
            if "@" not in external_machine:
                parser.error("ERROR: external physical machine names should be like 'user@host'")

    @staticmethod
    def is_external():
        """Does this infrastructure provider provision in local or remote hardware (e.g., clouds)

        Returns:
            bool: Provisions on external hardware
        """
        return False

    @staticmethod
    def has_base():
        """Does this infrastructure provider support dedicated base images, such as QEMU where we
        can generate backing images, containing the OS and required software, which are used by all
        cloud/edge/endpoint VMs subsequently.

        Returns:
            bool: Provisions on external hardware
        """
        return True

    @staticmethod
    def supports_network_emulation():
        """Does this infrastructure provider support network emulation?

        Returns:
            bool: Support of network emulation
        """
        return True

    @staticmethod
    def supports_storage_emulation():
        """Does this infrastructure provider support network emulation?

        Returns:
            bool: Support of network emulation
        """
        return True

    @staticmethod
    def set_ip_names(layer):
        """Set the names and IP addresses of each machine on a specific layer

        Args:
            layer (dict): A single layer described in the global config

        TODO (low priority)
            - If we run 2 providers that statically determine IP addresses (like QEMU, and not like
              GCP or AWS which dynamically set IP addresses without our interference), IP addresses
              will start clashing because IP address information is partially stored in
              settings.config["provider_init"]["qemu"] and is therefore provider specific.
            - Solve this by making IP info global and not per provider, and then use the same logic
              we use below to make sure that QEMU VMs across multiple layers don't collide in IPs.
        """
        logging.info("Set the IPs and names of all VMs for each physical machine")
        provider_init = settings.config["provider_init"]["qemu"]

        provider = settings.get_providers(layer_name=layer["name"])[0]
        if provider["name"] != "qemu":
            logging.error(f"ERROR: Provider {provider['name']} in layer with QEMU")
            sys.exit()

        for i, machine in enumerate(settings.get_machines(layer_name=layer["name"])):
            if machine.layer != layer["name"]:
                logging.error(
                    f"ERROR: Machine is scheduled in layer {machine.layer} "
                    f"but attached to layer {layer['name']}"
                )
                sys.exit()

            if machine.provider == "":
                logging.error("ERROR: Machine provider is not set, expected QEMU")
                sys.exit()

            # Set machine details
            machine.user = f"{layer['name']}_{i}_{settings.config['username']}"
            machine.ip = (
                f"{provider_init['prefixIP']}."
                f"{provider_init['middleIP']}."
                f"{provider_init['postfixIP']}"
            )
            machine.ip_internal = machine.ip
            machine.ssh = f"{machine.user}@{machine.ip}"

            # Accounting: Update IP (needs to be unique)
            provider_init["postfixIP"] += 1
            if provider_init["postfixIP"] == provider_init["postfixIP_max"]:
                provider_init["middleIP"] += 1
                provider_init["postfixIP"] = provider_init["postfixIP_min"]

        # Now add base images
        _set_ip_names_base(layer)

    @staticmethod
    def start(layers):
        """Manage the infrastructure deployment using QEMU

        Args:
            layers (list(dict)): List of config layers this provider should provision infra for
        """
        deploy.start(layers)

    @staticmethod
    def delete_vms():
        """Delete infrastructure created by this provider in the current or previous Continuum run
        (this depends on whether this function is invoked at the start or end of Continuum).
        Execution at the end of Continuum is optional, if the user wants to delete all provided
        infrastructure after benchmarking or doesn't.
        """
        logging.info("Start deleting VMs")

        commands = []
        for host in settings.config["hosts"]:
            command = (
                r"virsh list --all | "
                r'grep -o -E "(\w*_%s)" | '
                r'xargs -I %% sh -c "virsh destroy %%"' % (settings.config["username"])
            )

            # Not the ideal SSH way, but good enough for now
            if not host.is_local:
                command = f"ssh {host.name} -t 'bash -l -c \"{command}\"'"

            commands.append(command)

        results = settings.process(commands, shell=True)

        # Wait for process to finish. Outcome of destroy command does not matter
        for command, (_, _) in zip(commands, results):
            logging.debug("Check output for command [%s]", command)

    @staticmethod
    def finish():
        """Optional: Execute code or print information to users at the end of a Continuum run"""

        if settings.config["infrastructure"]["delete"]:
            Module.delete_vms()
            logging.info("Finished\n")
        else:
            s = []
            for layer in settings.get_layers():
                key = settings.get_ssh_keys(layer_name=layer)[0]
                for ssh in settings.get_sshs(layer_name=layer):
                    s.append("ssh %s -i %s" % (ssh, key))

            logging.info("To access the VMs:\n\t%s\n", "\n\t".join(s))


def _set_ip_names_base(layer):
    """Set the names and IP addresses of each machine on a specific layer
    Assume all base images can fit on a single ___.___.XXX.___ (250 IPs)

    Args:
        layer (dict): A single layer described in the global config
    """
    provider_init = settings.config["provider_init"]["qemu"]
    provider = settings.get_providers(layer_name=layer["name"])[0]

    # You can have the same base image (let's say, cloud-qemu) on multiple physical host
    # We could also create 1, and then copy it to all physical hosts, but that would be slower
    # than just creating identical base images on each host (you don't need to copy)
    i = 0

    for host in settings.config["hosts"]:
        # For each host, check if there is a machine for this layer and provider (QEMU)
        create_base = False
        for machine in host.machines:
            if machine.layer == layer and machine.provider == "qemu":
                create_base = True

        # If so, create a new machine object for this host that will be the base image
        if create_base:
            machine = m.Machine(layer, provider, base=True)

            # Name is specific to the provider and software packages
            # This allows us to create, use, and reuse many base images
            packages = list(layer["software"].keys())
            machine.user = (
                f"base_{layer['name']}_qemu_{'_'.join(packages)}_{i}_{settings.config['username']}"
            )
            machine.ip = (
                f"{provider_init['prefixIP']}."
                f"{provider_init['middleIP_base']}."
                f"{provider_init['postfixIP_base']}"
            )
            machine.ip_internal = machine.ip
            machine.ssh = f"{machine.user}@{machine.ip}"

            i += 1

            host.machines.append(machine)
            layer["machine"].append(machine)

            # Accounting: Update IP (needs to be unique)
            provider_init["postfixIP_base"] += 1
            if provider_init["postfixIP_base"] == provider_init["postfixIP_max"]:
                logging.error("ERROR: We support only 250 base images max")
                sys.exit()
