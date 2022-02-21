'''\
Impelemnt infrastructure
'''
import logging
import sys
import time

from . import machine as m
from . import ansible
from . import network


def schedule(config, machines):
    """Check if the requested cloud / edge VMs and endpoint containers can be scheduled
    on the available hardware using a greedy algorithm:
    - If physical node 0 can fit the next cloud / edge VM or endpoint container, do it.
    - If not, go to the next node and try to fit it on there.
    - Then continue fitting the next cloud / edge VM or endpoint container on the node you left.
        - So once we go to the next node, we will never consider the old node for scheduling anymore.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(set): List of 'cloud', 'edge', 'endpoint' sets containing the number of 
            those machines per physical node
    """
    logging.info('Trying to schedule all cloud / edge / endpoint nodes on the available hardware')
    machines_per_node = [{'cloud': 0, 'edge': 0, 'endpoint': 0}]

    node = 0
    machine_cores_left = machines[0].cores

    machine_type = 'cloud'
    types_to_go = {'cloud': config['infrastructure']['cloud_nodes'],
                   'edge': config['infrastructure']['edge_nodes'],
                   'endpoint': config['infrastructure']['endpoint_nodes']}
    cores_per_type = {'cloud': config['infrastructure']['cloud_cores'],
                      'edge': config['infrastructure']['edge_cores'],
                      'endpoint': config['infrastructure']['endpoint_cores']}

    while sum(types_to_go.values()) != 0 and node < len(machines):
        if types_to_go[machine_type] == 0:
            if machine_type == 'cloud':
                machine_type = 'edge'
            elif machine_type == 'edge':
                machine_type = 'endpoint'

            continue

        if cores_per_type[machine_type] <= machine_cores_left:
            machine_cores_left -= cores_per_type[machine_type]
            machines_per_node[node][machine_type] += 1
            types_to_go[machine_type] -= 1

            if types_to_go[machine_type] == 0:
                if machine_type == 'cloud':
                    machine_type = 'edge'
                elif machine_type == 'edge':
                    machine_type = 'endpoint'
                else:
                    continue

            if machine_cores_left == 0:
                node += 1

                if node == len(machines):
                    break

                machine_cores_left = machines[node].cores
                machines_per_node.append(
                    {'cloud': 0, 'edge': 0, 'endpoint': 0})
        else:
            node += 1

            if node == len(machines):
                break

            machine_cores_left = machines[node].cores
            machines_per_node.append({'cloud': 0, 'edge': 0, 'endpoint': 0})

    if sum(types_to_go.values()) != 0:
        logging.error('''\
Not all VMs or containers fit on the available hardware.
Please request less cloud / edge / endpoints nodes, 
less cores per VM / container or add more hardware
using the --file option''')
        sys.exit()

    return machines_per_node


def create_keypair(config, machines):
    """Create SSH keys to be used for ssh'ing into VMs, local and remote if needed.
    We use the SSH key of the local machine for all machines, so copy to all.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Create SSH keys to be used with VMs')
    for machine in machines:
        if machine.is_local:
            command = ['[[ ! -f %s/.ssh/id_rsa_benchmark.pub ]] && \
cd %s/.ssh && \
ssh-keygen -t rsa -b 4096 -f id_rsa_benchmark -C KubeEdge -N \'\' -q' % (config['home'], config['home'])]
            output, error = machine.process(command, shell=True)
        else:
            source = '%s/.ssh/id_rsa_benchmark*' % (config['home'])
            dest = machine.name + ':./.ssh/'
            output, error = machine.copy_files(source, dest)

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output != [] and not any('Your public key has been saved in' in line for line in output):
            logging.error(''.join(output))
            sys.exit()


def create_dir(config, machines):
    """Generate a temporary directory for generated files.
    This directory is located inside the benchmark git repository.
    Later, that data will be sent to each physical machine's ${HOME}/.continuum directory

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Create a temporary directory for generated files')
    command = 'rm -rf %s/.tmp && mkdir %s/.tmp' % (config['base'], config['base'])
    output, error = machines[0].process(command, shell=True)

    if error != []:
        logging.error(''.join(error))
        sys.exit()
    elif output != []:
        logging.error(''.join(output))
        sys.exit()


def copy_files(config, machines):
    """Copy Infrastructure and Ansible files to all machines with directory ${HOME}/.continuum

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start copying files to all nodes')

    for machine in machines:
        # Create a source directory on each machiine
        if machine.is_local:
            command = 'rm -rf %s/.continuum && mkdir %s/.continuum' % (config['home'], config['home'])
            output, error = machine.process(command, shell=True)

            dest = config['home'] + '/.continuum/'
        else:
            command = 'ssh %s "rm -rf ./.continuum && mkdir ./.continuum"' % (
                machine.name)
            output, error = machine.process(command, shell=True)

            dest = machine.name + ':./.continuum/'

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output != []:
            logging.error(''.join(output))
            sys.exit()

        out = []

        # For the local machine, copy the ansible inventory file and benchmark launch
        if machine.is_local:
            out.append(machine.copy_files(config['base'] + '/.tmp/inventory', dest))
            out.append(machine.copy_files(config['base'] + '/.tmp/inventory_vms', dest))

            if 'benchmark' in config:
                if config['benchmark']['mode'] == 'cloud':
                    path = config['base'] + '/resource_manager/' + config['resource_manager']['cloud_rm'] + '/launch_benchmark.yml'
                elif config['benchmark']['mode'] == 'edge':
                    path = config['base'] + '/resource_manager/' + config['resource_manager']['edge_rm'] + '/launch_benchmark.yml'
                
                out.append(machine.copy_files(path, dest))

        # Start selectevily copying Infra files for each VM
        for name in machine.cloud_controller_names + machine.cloud_names + machine.edge_names + machine.endpoint_names + [machine.base_name]:
            if name == None:
                continue

            out.append(machine.copy_files(config['base'] + '/.tmp/domain_' + name + '.xml', dest))
            out.append(machine.copy_files(config['base'] + '/.tmp/user_data_' + name + '.yml', dest))

        # Copy Ansible YML files to each node
        # For infrastructure
        path = config['base'] + '/infrastructure/' + config['infrastructure']['provider'] + '/infrastructure/'
        out.append(machine.copy_files(path, dest, recursive=True))

        # For cloud/edge RM
        if 'resource_manager' in config:
            if 'cloud_rm' in config['resource_manager']:
                path = config['base'] + '/resource_manager/' + config['resource_manager']['cloud_rm'] + '/cloud/'
                out.append(machine.copy_files(path, dest, recursive=True))
            if 'edge_rm' in config['resource_manager']:
                path = config['base'] + '/resource_manager/' + config['resource_manager']['edge_rm'] + '/edge/'
                out.append(machine.copy_files(path, dest, recursive=True))

        # For endpoint
        if 'benchmark' in config:
            if config['benchmark']['mode'] == 'cloud':
                path = config['base'] + '/resource_manager/' + config['resource_manager']['cloud_rm'] + '/endpoint/'
            elif config['benchmark']['mode'] == 'edge':
                path = config['base'] + '/resource_manager/' + config['resource_manager']['edge_rm'] + '/endpoint/'

            out.append(machine.copy_files(path, dest, recursive=True))

        for output, error in out:
            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif output != []:
                logging.error(''.join(output))
                sys.exit()


# def add_ssh(machines, base=False):
#     """Add SSH keys for generated VMs to known_hosts file
#     Since all VMs are connected via a network bridge, 
#     only touch the known_hosts file of the main physical machine

#     Args:
#         machines (list(Machine object)): List of machine objects representing physical machines
#     """
#     logging.info('Start adding ssh keys to the known_hosts file for each VM (base=%s)' % (base))

#     # Get IPs of all (base) machines
#     control_ips, worker_ips, endpoint_ips, base_ips = setup_workers.get_ips(machines)
#     if base:
#         ips = base_ips
#     else:
#         ips = control_ips + worker_ips + endpoint_ips
 
#     # Check if old keys are still in the known hosts file
#     for ip in ips:
#         command = ['ssh-keygen', '-f', home +
#                 '/.ssh/known_hosts', '-R', ip]
#         _, error = machines[0].process(command)

#         if error != [] and not any('not found in' in err for err in error):
#             logging.error(''.join(error))
#             sys.exit()

#     # Once the known_hosts file has been cleaned up, add all new keys
#     for ip in ips:
#         command = 'ssh-keyscan %s >> %s/.ssh/known_hosts' % (ip, home)
#         _, error = machines[0].process(command, shell=True)

#         # If VM is not yet up, wait
#         if error == [] or not any('# ' + str(ip) + ':' in err for err in error):
#             logging.info('Wait for VM to have started up')
#             while True:
#                 time.sleep(5)
#                 command = 'ssh-keyscan %s >> %s/.ssh/known_hosts' % (ip, home)
#                 _, error = machines[0].process(command, shell=True)

#                 if error != [] and any('# ' + str(ip) + ':' in err for err in error):
#                     break


def start(config):
    """Create and manage infrastructure

    Args:
        config (dict): Parsed configuration

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    if config['infrastructure']['provider'] == 'qemu':
        from .qemu import generate
        from .qemu import start

    machines = m.make_machine_objects(config)

    for machine in machines:
        machine.check_hardware()

    nodes_per_machine = schedule(config, machines)
    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)
    m.set_ip_names(config, machines, nodes_per_machine)
    m.gather_ips(config, machines)
    delete_vms(machines)
    m.print_schedule(machines)

    for machine in machines:
        logging.debug(machine)

    logging.info('Generate configuration files for Infrastructure and Ansible')
    create_keypair(config, machines)
    create_dir(config, machines)

    ansible.create_inventory_machine(config, machines)
    ansible.create_inventory_vm(config, machines)

    generate.start(config, machines)
    copy_files(config, machines)

    logging.info('Setting up the infrastructure')
    start.start(config, machines)
    # add_ssh(machines)

    # logging.info('Install software on the infrastructure')
    # if args.mode == 'cloud' or args.mode == 'edge':
    #     network.start(args, machines)

    #     if args.netperf:
    #         network.benchmark(config, machines)

    return machines


def delete_vms(machines):
    """The benchmark has been completed succesfully, now delete the VMs.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start deleting VMs after benchmark has completed')
    processes = []
    for machine in machines:
        if machine.is_local:
            command = 'virsh list --all | grep -o -E "(cloud\w*|edge\w*|endpoint\w*)" | xargs -I % sh -c "virsh destroy %"'
        else:
            comm = 'virsh list --all | grep -o -E \\"(cloud\w*|edge\w*|endpoint\w*)\\" | xargs -I % sh -c \\"virsh destroy %\\"'
            command = 'ssh %s -t \'bash -l -c "%s"\'' % (machine.name, comm)

        processes.append(machine.process(command, shell=True, output=False))

    # Wait for process to finish. Outcome of destroy command does not matter
    for process in processes:
        logging.debug('Check output for command [%s]' % (''.join(process.args)))
        _ = [line.decode('utf-8') for line in process.stdout.readlines()]
        _ = [line.decode('utf-8') for line in process.stderr.readlines()]
