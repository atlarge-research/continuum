'''\
Main source code file.

Benchmark KubeEdge using one of the provided applications.
Check the README and help for more information.
'''

import argparse
import os.path
import sys
import logging
import os
import time
import pathlib
import json
import socket

import ansible_inventory
import machine as m
import output
import qemu_generate
import qemu
import setup_endpoints
import setup_workers


def docker_registry(args, machines):
    """Create and fill a local, private docker registry without the images needed for the benchmark.
    This is to prevent each spawned VM to pull from DockerHub, which has a rate limit.

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Create local Docker registry')
    apps = images[args.app]
    push = [True] * len(apps)

    command = ['curl', 'localhost:5000/v2/_catalog']
    output, error = machines[0].process(command)

    if error != [] and any('Failed to connect to' in line for line in error):
        # Registry is not up yet, launch
        command = ['docker', 'run', '-d', '-p', '5000:5000',
                   '--restart=always', '--name', 'registry', 'registry:2']
        output, error = machines[0].process(command)

        if error != [] and not (any('Unable to find image' in line for line in error) and
                                any('Pulling from' in line for line in error)):
            logging.error(''.join(error))
            sys.exit()
    elif output == []:
        logging.error('No output from Docker container')
        sys.exit()
    elif not args.docker_pull:
        # Registry is already up, check if containers are present
        repos = json.loads(output[0])['repositories']

        for i, app in enumerate(apps):
            a = app.split(':')[1]

            if a in repos:
                push[i] = False

    # Pull images which aren't present yet in the registry (or forced by args.docker_pull)
    for app, p in zip(apps, push):
        if not p:
            continue

        new_name = 'localhost:5000/' + app.split(':')[1]
        commands = [['docker', 'pull', app],
                    ['docker', 'tag', app, new_name],
                    ['docker', 'push', new_name]]

        for command in commands:
            output, error = machines[0].process(command)

            if error != []:
                logging.error(''.join(error))
                sys.exit()


def main(args):
    """Run the program flow: 
    1. Check if all physical nodes are reachable, get their hardware specs
    2. Make a schedule of cloud and edge VMs and endpoint containers on physical hardware
    3. Create QEMU config files, and deploy the cloud and edge VMs
    4. Use Ansible to deploy Kubernetes and KubeEdge on the VMs
    5. Deploy the edge applications on the VMs 
    6. Start endpoint Docker containers
    7. Wait for the applications to finish, gather output and present it

    Args:
        args (ArgumentParser): Contains all user input arguments
    """
    # machines = m.make_machine_objects(args)

    # for machine in machines:
    #     machine.check_hardware()

    # nodes_per_machine = schedule(args, machines)
    # machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)
    # m.set_ip_names(args, machines, nodes_per_machine, prefixIP, postfixIP)
    # delete_vms(machines)
    # m.print_schedule(machines)

    # for machine in machines:
    #     logging.debug(machine)

    # logging.info('Generate configuration files for QEMU and Ansible')
    # create_keypair(machines)
    # create_dir(machines)
    # ansible_inventory.create_inventory_machine(args, machines)
    # ansible_inventory.create_inventory_vm(args, machines)

    qemu_generate.generate_config(args, machines)
    copy_files(machines)

    logging.info('Setting up the infrastructure')
    qemu.start_qemu(args, machines)
    add_ssh(machines)

    logging.info('Install software on the infrastructure')
    if args.mode == 'cloud' or args.mode == 'edge':
        setup_workers.network_delay(args, machines)
        setup_workers.start_kube(args, machines)

        if args.netperf:
            setup_workers.benchmark_network(args, machines)

    setup_endpoints.setup_docker(machines)

    docker_registry(args, machines)

    if args.mode == 'cloud' or args.mode == 'edge':
        setup_workers.start_subscribers(args, machines)

    logging.info('Start publishers in Docker containers')
    endpoint_names = setup_endpoints.start_publisher(args, machines)
    setup_endpoints.wait_completion(machines, endpoint_names)
    endpoint_output = output.endpoint_output(machines, endpoint_names)

    logging.info('Benchmark has been finished, prepare results')
    worker_output = []
    if args.mode == 'cloud' or args.mode == 'edge':
        worker_output = output.get_subscriber_output(args, machines)

    sub_metrics, endpoint_metrics = output.gather_metrics(
        args, worker_output, endpoint_output, endpoint_names)
    output.format_output(args, sub_metrics, endpoint_metrics)

    if args.delete:
        delete_vms(machines)
