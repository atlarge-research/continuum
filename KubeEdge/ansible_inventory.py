'''\
Generate Ansible inventory files
'''

import sys
import logging
import socket


def create_inventory_machine(args, machines):
    """Create ansible inventory for creating VMs, so ssh to all physical machines is needed

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Generate Ansible inventory file for physical machines')
    f = open('.tmp/inventory', 'w')

    # All hosts group
    f.write('[all_hosts]\n')

    for machine in machines:
        if machine.is_local:
            f.write('localhost ansible_connection=local username=%s base=%s\n' % (
                machine.user, machine.base_name))
        else:
            f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s base=%s\n' % (
                machine.name_sanitized, machine.ip, machine.user, machine.user, machine.base_name))

    f.write('\n[all:vars]\n')
    f.write('ansible_python_interpreter=/usr/bin/python3\n')
    f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")

    # Cloud (controller / worker) VM group
    if args.mode == 'cloud' or args.mode == 'edge':
        f.write('\n[clouds]\n')
        clouds = 0

        for machine in machines:
            if machine.cloud_controller + machine.clouds == 0:
                continue

            if machine.is_local:
                f.write('localhost ansible_connection=local username=%s cloud_controller=%i cloud_start=%i cloud_end=%i edges=%i\n' % (
                    machine.user, machine.cloud_controller, clouds, clouds + machine.clouds - 1, machine.edges))
            else:
                f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s cloud_controller=%i cloud_start=%i cloud_end=%i edges=%i\n' % (
                    machine.name_sanitized, machine.ip, machine.user, machine.user, machine.cloud_controller, clouds, clouds + machine.clouds - 1, machine.edges))

            clouds += machine.clouds

    # Edge VM group
    if args.mode == 'edge':
        f.write('\n[edges]\n')
        edges = 0

        for machine in machines:
            if machine.edges == 0:
                continue

            if machine.is_local:
                f.write('localhost ansible_connection=local username=%s edge_start=%i edge_end=%i\n' % (
                    machine.user, edges, edges + machine.edges - 1))
            else:
                f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s edge_start=%i edge_end=%i\n' % (
                    machine.name_sanitized, machine.ip, machine.user, machine.user, edges, edges + machine.edges - 1))

            edges += machine.edges

    f.write('\n[endpoints]\n')
    endpoints = 0
    for machine in machines:
        if machine.endpoints == 0:
            continue

        if machine.is_local:
            f.write('localhost ansible_connection=local username=%s endpoint_start=%i endpoint_end=%i\n' % (
                machine.user, endpoints, endpoints + machine.endpoints - 1))
        else:
            f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s endpoint_start=%i endpoint_end=%i\n' % (
                machine.name_sanitized, machine.ip, machine.user, machine.user, endpoints, endpoints + machine.endpoints - 1))

        endpoints += machine.endpoints

    f.close()


def create_inventory_vm(args, machines):
    """Create ansible inventory for setting up Kubernetes and KubeEdge, so ssh to all VMs is needed

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Generate Ansible inventory file for VMs')

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    except Exception as e:
        logging.error('Could not get host ip: %s' % (e))
        sys.exit()

    f = open('.tmp/inventory_vms', 'w')

    f.write('\n[all:vars]\n')
    f.write('ansible_python_interpreter=/usr/bin/python3\n')
    f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")
    f.write('ansible_ssh_private_key_file=~/.ssh/id_rsa_benchmark\n')
    f.write('registry_ip=%s:%i\n' % (host_ip, 5000))

    if args.mode == 'cloud' or args.mode == 'edge':
        f.write('cloud_ip=%s\n' % (machines[0].cloud_controller_ips[0]))

        # Cloud controller (is always on machine 0)
        f.write('[cloudcontroller]\n')
        f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s cloud_mode=%i\n' % (
                    machines[0].cloud_controller_names[0], machines[0].cloud_controller_ips[0],
                    machines[0].cloud_controller_names[0], machines[0].cloud_controller_names[0],
                    args.mode == 'cloud'))

    # Cloud worker VM group
    if args.mode == 'cloud':
        f.write('[clouds]\n')

        for machine in machines:
            for name, ip in zip(machine.cloud_names, machine.cloud_ips):
                f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s\n' % (
                    name, ip, name, name))

    # Edge VM group
    if args.mode == 'edge':
        f.write('\n[edges]\n')

        for machine in machines:
            for name, ip in zip(machine.edge_names, machine.edge_ips):
                f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s\n' % (
                    name, ip, name, name))

    # Endpoitn VM group
    f.write('\n[endpoints]\n')
    for machine in machines:
        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s\n' % (
                name, ip, name, name))

    # Base VM group
    f.write('\n[base]\n')
    for machine in machines:
        f.write('%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s\n' % (
            machine.base_name, machine.base_ip, machine.base_name, machine.base_name))

    f.close()
