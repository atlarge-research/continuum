'''\
Impelemnt infrastructure
'''
import logging
import sys
import time
import json
import socket
import numpy as np

from . import machine as m
from . import ansible
from . import network


def schedule_equal(config, machines):
    """Distribute the VMs equally over the available machines, based on utilization

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Schedule VMs on machine: Based on utilization')
    machines_per_node = [{'cloud': 0, 'edge': 0, 'endpoint': 0} for _ in range(len(machines))]
    machines_cores_used = [0 for _ in range(len(machines))]

    types_to_go = {'cloud': config['infrastructure']['cloud_nodes'],
                   'edge': config['infrastructure']['edge_nodes'],
                   'endpoint': config['infrastructure']['endpoint_nodes']}
    cores_per_type = {'cloud': config['infrastructure']['cloud_cores'],
                      'edge': config['infrastructure']['edge_cores'],
                      'endpoint': config['infrastructure']['endpoint_cores']}

    machine_type = 'cloud'
    while sum(types_to_go.values()) != 0:
        if types_to_go[machine_type] == 0:
            if machine_type == 'cloud':
                machine_type = 'edge'
            elif machine_type == 'edge':
                machine_type = 'endpoint'

            continue

        # Get machine with least cores used compared to total cores
        i = np.argmin([cores_used / m.cores for cores_used, m in zip(machines_cores_used, machines)])

        # Place VM on that machine
        machines_cores_used[i] += cores_per_type[machine_type]
        machines_per_node[i][machine_type] += 1
        types_to_go[machine_type] -= 1

    return machines_per_node


def schedule_pin(config, machines):
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
    logging.info('Schedule VMs on machine: Based on CPU cores left / Greedy')
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


def delete_vms(machines):
    """The benchmark has been completed succesfully, now delete the VMs.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start deleting VMs after benchmark has completed')
    processes = []
    for machine in machines:
        if machine.is_local:
            command = 'virsh list --all | grep -o -E "(cloud\w*|edge\w*|endpoint\w*|base\w*)" | xargs -I % sh -c "virsh destroy %"'
        else:
            comm = 'virsh list --all | grep -o -E \\"(cloud\w*|edge\w*|endpoint\w*|base\w*)\\" | xargs -I % sh -c \\"virsh destroy %\\"'
            command = 'ssh %s -t \'bash -l -c "%s"\'' % (machine.name, comm)

        processes.append(machine.process(command, shell=True, output=False))

    # Wait for process to finish. Outcome of destroy command does not matter
    for process in processes:
        logging.debug('Check output for command [%s]' % (''.join(process.args)))
        _ = [line.decode('utf-8') for line in process.stdout.readlines()]
        _ = [line.decode('utf-8') for line in process.stderr.readlines()]


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

            if not config['infrastructure']['infra_only'] and (config['mode'] == 'cloud' or config['mode'] == 'edge'):
                path = config['base'] + '/resource_manager/' + config['benchmark']['resource_manager'] + '/launch_benchmark.yml'
                out.append(machine.copy_files(path, dest))

        # Copy VM creation files
        for name in machine.cloud_controller_names + machine.cloud_names + machine.edge_names + machine.endpoint_names + machine.base_names:
            out.append(machine.copy_files(config['base'] + '/.tmp/domain_' + name + '.xml', dest))
            out.append(machine.copy_files(config['base'] + '/.tmp/user_data_' + name + '.yml', dest))

        # Copy Ansible files for infrastructure
        path = config['base'] + '/infrastructure/' + config['infrastructure']['provider'] + '/infrastructure/'
        out.append(machine.copy_files(path, dest, recursive=True))

        # For cloud/edge/endpoint specific
        if not config['infrastructure']['infra_only']:
            if config['mode'] == 'cloud' or config['mode'] == 'edge':
                path = config['base'] + '/resource_manager/' + config['benchmark']['resource_manager'] + '/cloud/'
                out.append(machine.copy_files(path, dest, recursive=True))

                if config['mode'] == 'edge':
                    path = config['base'] + '/resource_manager/' + config['benchmark']['resource_manager'] + '/edge/'
                    out.append(machine.copy_files(path, dest, recursive=True))

            path = config['base'] + '/resource_manager/endpoint/'
            out.append(machine.copy_files(path, dest, recursive=True))

        for output, error in out:
            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif output != []:
                logging.error(''.join(output))
                sys.exit()


def add_ssh(config, machines, base=False):
    """Add SSH keys for generated VMs to known_hosts file
    Since all VMs are connected via a network bridge, 
    only touch the known_hosts file of the main physical machine

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start adding ssh keys to the known_hosts file for each VM (base=%s)' % (base))

    # Get IPs of all (base) machines
    if base:
        ips = config['base_ips']
    else:
        ips = config['control_ips'] + config['cloud_ips'] + config['edge_ips'] + config['endpoint_ips']
 
    # Check if old keys are still in the known hosts file
    for ip in ips:
        command = ['ssh-keygen', '-f', config['home'] + '/.ssh/known_hosts', '-R', ip]
        _, error = machines[0].process(command)

        if error != [] and not any('not found in' in err for err in error):
            logging.error(''.join(error))
            sys.exit()

    # Once the known_hosts file has been cleaned up, add all new keys
    for ip in ips:
        logging.info('Wait for VM to have started up')
        while True:
            command = 'ssh-keyscan %s >> %s/.ssh/known_hosts' % (ip, config['home'])
            _, error = machines[0].process(command, shell=True)

            if any('# ' + str(ip) + ':' in err for err in error):
                break

            time.sleep(5)


def docker_registry(config, machines):
    """Create and fill a local, private docker registry without the images needed for the benchmark.
    This is to prevent each spawned VM to pull from DockerHub, which has a rate limit.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Create local Docker registry')
    need_pull = [True for _ in range(len(config['images']))]

    # Check if registry is up
    command = ['curl', 'localhost:5000/v2/_catalog']
    output, error = machines[0].process(command)

    if error != [] and any('Failed to connect to' in line for line in error):
        # Not yet up, so launch
        command = ['docker', 'run', '-d', '-p', '5000:5000',
                   '--restart=always', '--name', 'registry', 'registry:2']
        output, error = machines[0].process(command)

        if error != [] and not (any('Unable to find image' in line for line in error) and
                                any('Pulling from' in line for line in error)):
            logging.error(''.join(error))
            sys.exit()
    elif output == []:
        # Crash
        logging.error('No output from Docker container')
        sys.exit()
    elif not config['benchmark']['docker_pull']:
        # Registry is already up, check if containers are present
        repos = json.loads(output[0])['repositories']

        for i, image in enumerate(config['images']):
            if image.split(':')[1] in repos:
                need_pull[i] = False

    # Pull images which aren't present yet in the registry
    for image, pull in zip(config['images'], need_pull):
        if not pull:
            continue

        dest = 'localhost:5000/' + image.split(':')[1]
        commands = [['docker', 'pull', image],
                    ['docker', 'tag', image, dest],
                    ['docker', 'push', dest]]

        for command in commands:
            output, error = machines[0].process(command)

            if error != []:
                logging.error(''.join(error))
                sys.exit()


def docker_pull(config, machines):
    """Start running the endpoint containers using Docker.
    Wait for them to finish, and get their output.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    logging.info('Pull docker containers into base images')

    # Images need to be pulled from local registry, get address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    except Exception as e:
        logging.error('Could not get host ip: %s' % (e))
        sys.exit()

    # Pull the images
    processes = []
    for machine in machines:
        for name, ip in zip(machine.base_names, machine.base_ips):
            # Edge mode has cloud controllers, which don't need docker containers
            if (config['mode'] == 'edge' and '_cloud_' in name):
                continue

            if '_cloud_' in name or '_endpoint' in name:
                image = '%s:5000/%s' % (str(host_ip), config['images'][0].split(':')[1])
            elif '_edge_' in name:
                image = '%s:5000/%s' % (str(host_ip), config['images'][1].split(':')[1])

            command = ['docker', 'pull', image]
            processes.append([name, machines[0].process(command, output=False, ssh=True, ssh_target=name + '@' + ip)])

    # Checkout process output
    for name, process in processes:
        logging.debug('Check output of command [%s]' % (' '.join(process.args)))
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]

        if error != [] and any('server gave HTTP response to HTTPS client' in line for line in error):
            logging.warn('''\
File /etc/docker/daemon.json does not exist, or is empty on Machine %s. 
This will most likely prevent the machine from pulling endpoint docker images 
from the private Docker registry running on the main machine %s.
Please create this file on machine %s with content: { "insecure-registries":["%s:5000"] }
Followed by a restart of Docker: systemctl restart docker''' % (
                name, machines[0].name, name, host_ip))
        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output == []:
            logging.error('No output from command docker pull')
            sys.exit()


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

    if config['infrastructure']['cpu_pin']:
        nodes_per_machine = schedule_pin(config, machines)
    else:
        nodes_per_machine = schedule_equal(config, machines)

    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)
    m.set_ip_names(config, machines, nodes_per_machine)

    m.gather_ips(config, machines)
    m.gather_ssh(config, machines)

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
    if not config['infrastructure']['infra_only']:
        docker_registry(config, machines)

    start.start(config, machines)
    add_ssh(config, machines)

    if config['infrastructure']['network_emulation']:
        network.start(config, machines)

    if config['infrastructure']['netperf']:
        network.benchmark(config, machines)

    return machines
