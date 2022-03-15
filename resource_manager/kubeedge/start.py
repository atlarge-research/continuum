'''\
Setup KubeEdge on cloud/edge
'''

import logging

import os
import sys

sys.path.append(os.path.abspath('../..'))

import main


def start(config, machines):
    """Setup KubeEdge on cloud/edge VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start KubeEdge cluster on VMs')
    processes = []

    # Setup cloud controller
    command = ['ansible-playbook', '-i', config['home'] + '/.continuum/inventory_vms', 
               config['home'] + '/.continuum/cloud/control_install.yml']
    processes.append(machines[0].process(command, output=False))

    # Setup edge
    command = ['ansible-playbook', '-i', config['home'] + '/.continuum/inventory_vms', 
               config['home'] + '/.continuum/edge/install.yml']
    processes.append(machines[0].process(command, output=False))

    # Check playbooks
    for process in processes:
        logging.debug('Check output for Ansible command [%s]' % (' '.join(process.args)))
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]
        main.ansible_check_output((output, error))

    # Patch: Fix accessing KubeEdge logs from the cloud host
    logging.info('Enable KubeEdge logging feature')
    commands = []
    commands.append(['ansible-playbook', '-i', config['home'] + '/.continuum/inventory_vms',
        config['home'] + '/.continuum/cloud/control_log.yml'])
    commands.append(['ansible-playbook', '-i', config['home'] + '/.continuum/inventory_vms',
        config['home'] + '/.continuum/edge/log.yml'])

    # Wait for the cloud to finish before starting the edge
    for command in commands:
        main.ansible_check_output(machines[0].process(command))
