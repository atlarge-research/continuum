"""Baremetal provider - uses physical hardware without any virtualization"""

import logging
import sys

from infrastructure import machine as m
from infrastructure import network


def delete_vms(_config, _machines):
    """Delete the VMs created by Continuum: Always at the start of a run the delete old VMs,
    and possilby at the end if the run if configured by the user

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Baremetal doesn't have anything to delete")


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return []


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if (
        config["infrastructure"]["cloud_nodes"] != 1
        or config["infrastructure"]["edge_nodes"] != 0
        or config["infrastructure"]["edge_nodes"] < 1
    ):
        parser.error("ERROR: Baremetal only supports #clouds==1 and #endpoints>=1 at the moment")
    if config["infrastructure"]["external_physical_machines"]:
        parser.error("ERROR: Baremetal only supports 1 physical machine at the moment")


def set_ip_names(config, machines, nodes_per_machine):
    """Set amount of cloud / edge / endpoints nodes per machine, and their IPs / hostnames.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node
    """
    logging.info("Set the IPs and names of all VMs for each physical machine - BAREMETAL")
    middle_ip = config["infrastructure"]["middleIP"]
    postfix_ip = config["postfixIP_lower"]

    cloud_index = 0
    endpoint_index = 0

    for machine, nodes in enumerate(zip(machines, nodes_per_machine)):
        if nodes["edge"] > 0:
            logging.error("ERROR: Baremetal does not support edge at the moment")
            sys.exit(1)

        # Set cloud information
        machine.clouds = nodes["cloud"]

        ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
        machine.cloud_ips.append(ip)
        machine.cloud_ips_internal.append(ip)

        name = "cloud%i_%s" % (cloud_index, config["username"])
        machine.cloud_names.append(name)
        cloud_index += 1
        middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)

        # Set endpoint information
        ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
        machine.endpoint_ips.append(ip)
        machine.endpoint_ips_internal.append(ip)
        middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)

        name = "endpoint%i_%s" % (endpoint_index, config["username"])
        machine.endpoint_names.append(name)
        endpoint_index += 1


def start(config, machines):
    """Manage bare-metal deployments.
    Currently, this only supports 1 cloud apps (not controller), and 0 or more endpoint apps.

    This will be possibly extended in the future - currently this provider only functions
    as a baseline for certain scientifc experiments, to verify that the use of
    virtual machines doesn't slow the software inside the VMs down.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Set up baremetal")
    m.gather_ips(config, machines)
    m.gather_ssh(config, machines)

    for machine in machines:
        logging.debug(machine)
