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


home = str(os.getenv('HOME'))
applications = ['image-classification']
images = {'image-classification': ['redplanet00/kubeedge-applications:image_classification_subscriber',
                                   'redplanet00/kubeedge-applications:image_classification_publisher',
                                   'redplanet00/kubeedge-applications:image_classification_combined']}
prefixIP = "192.168.122"
postfixIP = 10


def make_wide(formatter, w=120, h=36):
    """Return a wider HelpFormatter, if possible
    https://stackoverflow.com/questions/5462873/control-formatting-of-the-argparse-help-argument-list

    Beware: "Only the name of this class is considered a public API."

    Args:
        formatter (HelpFormatter): Format class for Python Argparse
        w (int, optional): Width of Argparse output. Defaults to 120.
        h (int, optional): Max help positions for Argparse output. Defaults to 36.

    Returns:
        formatter: Format class for Python Argparse, possibly with updated output sizes
    """
    try:
        kwargs = {'width': w, 'max_help_position': h}
        formatter(None, **kwargs)
        return lambda prog: formatter(prog, **kwargs)
    except TypeError:
        print('Argparse help formatter failed, falling back.')
        return formatter


def is_valid_file(parser, arg):
    """Check if input filepath is a valid file

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Path to a file

    Returns:
        error / filepointer: Returns either a filepointer or an error
    """
    if not (os.path.exists(arg) and os.path.isfile(arg)):
        parser.error("The given file does not exist: %s" % (arg))
    else:
        f = open(arg, 'r')
        lines = [line for line in f.read().splitlines() if line]
        f.close()
        return lines


def is_valid_application(parser, arg):
    """Check if input application is an existing application in this benchmark

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Application to run

    Returns:
        str: Valid application to run
    """
    if arg in applications:
        return arg
    else:
        parser.error('The given application does not exist: %s. \nChoose from: %s'
                     % (arg, ', '.join(applications)))


def is_valid_network(parser, arg):
    """Check if custom network settings are as expected, and will work with TC

    Args:
        parser (ArgumentParser): Argparse object
        arg (str): Network settings to use with TC

    Returns:
        list(float, float, int): Network delay average, network delay variance, throughput
    """    
    split = arg.rstrip().split(',')
    if len(split) == 3:
        try:
            vals =  [float(x) for x in split]
            vals[2] = int(vals[2])
            return vals
        except:
            pass

    parser.error('Could not parse custom network setting. Please give --cloud_network x,y,z')


def verbose_logging(args):
    """Enable logging to both stdout and file (/edge-benchmark-RM/logs/)
    If the -v / --verbose option is used, stdout will report logging.DEBUG, otherwise only logging.INFO
    The file will always use logging.DEBUG (which is the bigger scope)

    Args:
        args (Namespace): Argparse object
    """
    # Log to file parameters
    log_dir = '../logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    log_name = '%s_%s_%s.log' % (t, args.mode, args.app)

    file_handler = logging.FileHandler(log_dir + '/' + log_name)
    file_handler.setLevel(logging.DEBUG)

    # Log to stdout parameters
    stdout_handler = logging.StreamHandler(sys.stdout)
    if args.verbose:
        stdout_handler.setLevel(logging.DEBUG)
    else:
        stdout_handler.setLevel(logging.INFO)

    # Set parameters
    logging.basicConfig(format="[%(asctime)s %(filename)20s:%(lineno)4s - %(funcName)25s() ] %(message)s", 
                        level=logging.DEBUG, 
                        datefmt='%Y-%m-%d %H:%M:%S',
                        handlers=[
                            file_handler,
                            stdout_handler])

    logging.info('Logging has been enabled. Writing to stdout and file at %s/%s' % (log_dir, log_name))

    # Print input arguments to file
    log_info = '''
GENERATED ON        %s 
HOSTNAME            %s

APP                 %s
FILE                %s
CLOUDNODES          %i
CLOUD_CORES         %i
EDGENODES           %i
EDGE_CORES          %i
ENDPOINTS           %i
ENDPOINT_CORES      %i
DOCKER_PULL         %s
MODE                %s
VERBOSE             %s
DELETE              %s
NETWORK             %s
CONTROLLER_NETWORK  %s
ENDPOINT_NETWORK    %s
EDGE_QUOTA          %i
ENDPOINT_QUOTA      %i
NETPERF             %s
FREQUENCY           %i''' % (
        t, socket.gethostname(), args.app, args.file, args.cloudnodes, args.cloud_cores,
        args.edgenodes, args.edge_cores, args.endpoints, args.endpoint_cores,
        args.docker_pull, args.mode, args.verbose, args.delete, args.network,
        ','.join(map(str, args.controller_network)), ','.join(map(str, args.endpoint_network)),
        args.edge_quota, args.endpoint_quota, args.netperf, args.frequency)

    logging.debug(log_info)


def schedule(args, machines):
    """Check if the requested cloud / edge VMs and endpoint containers can be scheduled
    on the available hardware using a greedy algorithm:
    - If physical node 0 can fit the next cloud / edge VM or endpoint container, do it.
    - If not, go to the next node and try to fit it on there.
    - Then continue fitting the next cloud / edge VM or endpoint container on the node you left.
        - So once we go to the next node, we will never consider the old node for scheduling anymore.

    Args:
        args (Namespace): Argparse object
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

    if args.mode == 'cloud':
        types_to_go = {'cloud': args.cloudnodes + 1,
                       'edge': 0,
                       'endpoint': args.cloudnodes * args.endpoints}
    elif args.mode == 'edge':
        types_to_go = {'cloud': 1,
                       'edge': args.edgenodes,
                       'endpoint': args.edgenodes * args.endpoints}
    elif args.mode == 'endpoint':
        types_to_go = {'cloud': 0,
                       'edge': 0,
                       'endpoint': args.endpoints}

    cores_per_type = {'cloud': args.cloud_cores,
                      'edge': args.edge_cores,
                      'endpoint': args.endpoint_cores}

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


def create_keypair(machines):
    """Create SSH keys to be used for ssh'ing into KVM machines, local and remote if needed.
    QEMU uses the SSH key of the local machine for all machines, so we need to copy this key to all machines.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Create SSH keys to be used with VMs')
    for machine in machines:
        if machine.is_local:
            command = ['[[ ! -f %s/.ssh/id_rsa_benchmark.pub ]] && \
cd %s/.ssh && \
ssh-keygen -t rsa -b 4096 -f id_rsa_benchmark -C KubeEdge -N \'\' -q' % (home, home)]
            output, error = machine.process(command, shell=True)
        else:
            source = '%s/.ssh/id_rsa_benchmark*' % (home)
            dest = machine.name + ':./.ssh/'
            output, error = machine.copy_files(source, dest)

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output != [] and not any('Your public key has been saved in' in line for line in output):
            logging.error(''.join(output))
            sys.exit()


def create_dir(machines):
    """Generate a temporary directory for generated files.
    This directory is located inside the benchmark git repository.
    Afterwards, that data will be sent to each physical machine's ${HOME}/.edge directory

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """    
    logging.info('Create a temporary directory for generated files')
    benchmark_path = str(pathlib.Path(__file__).parent.resolve())

    command = 'rm -rf %s/.tmp && mkdir %s/.tmp' % (benchmark_path, benchmark_path)
    output, error = machines[0].process(command, shell=True)

    if error != []:
        logging.error(''.join(error))
        sys.exit()
    elif output != []:
        logging.error(''.join(output))
        sys.exit()


def copy_files(machines):
    """Copy QEMU and Ansible files to all machines with directory ${HOME}/.edge

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start copying files to all nodes')
    benchmark_path = str(pathlib.Path(__file__).parent.resolve())

    for machine in machines:
        # Create a source directory on each machiine
        if machine.is_local:
            command = 'rm -rf %s/.edge && mkdir %s/.edge' % (home, home)
            output, error = machine.process(command, shell=True)

            dest = home + '/.edge/'
        else:
            command = 'ssh %s "rm -rf ./.edge && mkdir ./.edge"' % (
                machine.name)
            output, error = machine.process(command, shell=True)

            dest = machine.name + ':./.edge/'

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output != []:
            logging.error(''.join(output))
            sys.exit()

        out = []
 
        # For the local machine, copy the ansible inventory file and benchmark launch
        if machine.is_local:
            out.append(machine.copy_files(benchmark_path + '/.tmp/inventory', dest))
            out.append(machine.copy_files(benchmark_path + '/.tmp/inventory_vms', dest))

            if args.mode == 'cloud' or args.mode == 'edge':
                out.append(machine.copy_files(benchmark_path + '/launch_benchmark.yml', dest))

        # Start selectevily copying QEMU files for each VM
        for name in machine.cloud_controller_names + machine.cloud_names + machine.edge_names + machine.endpoint_names + [machine.base_name]:
            if name == None:
                continue

            out.append(machine.copy_files(benchmark_path + '/.tmp/domain_' + name + '.xml', dest))
            out.append(machine.copy_files(benchmark_path + '/.tmp/user_data_' + name + '.yml', dest))

        # Copy Ansible YML files to each node
        out.append(machine.copy_files(benchmark_path + '/cloud/', dest, recursive=True))
        out.append(machine.copy_files(benchmark_path + '/edge/', dest, recursive=True))
        out.append(machine.copy_files(benchmark_path + '/endpoint/', dest, recursive=True))
        out.append(machine.copy_files(benchmark_path + '/qemu/', dest, recursive=True))

        for output, error in out:
            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif output != []:
                logging.error(''.join(output))
                sys.exit()


def add_ssh(machines, base=False):
    """Add SSH keys for generated VMs to known_hosts file
    Since all VMs are connected via a network bridge, 
    only touch the known_hosts file of the main physical machine

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start adding ssh keys to the known_hosts file for each VM (base=%s)' % (base))

    # Get IPs of all (base) machines
    control_ips, worker_ips, endpoint_ips, base_ips = setup_workers.get_ips(machines)
    if base:
        ips = base_ips
    else:
        ips = control_ips + worker_ips + endpoint_ips
 
    # Check if old keys are still in the known hosts file
    for ip in ips:
        command = ['ssh-keygen', '-f', home +
                '/.ssh/known_hosts', '-R', ip]
        _, error = machines[0].process(command)

        if error != [] and not any('not found in' in err for err in error):
            logging.error(''.join(error))
            sys.exit()

    # Once the known_hosts file has been cleaned up, add all new keys
    for ip in ips:
        command = 'ssh-keyscan %s >> %s/.ssh/known_hosts' % (ip, home)
        _, error = machines[0].process(command, shell=True)

        # If VM is not yet up, wait
        if error == [] or not any('# ' + str(ip) + ':' in err for err in error):
            logging.info('Wait for VM to have started up')
            while True:
                time.sleep(5)
                command = 'ssh-keyscan %s >> %s/.ssh/known_hosts' % (ip, home)
                _, error = machines[0].process(command, shell=True)

                if error != [] and any('# ' + str(ip) + ':' in err for err in error):
                    break


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
    machines = m.make_machine_objects(args)

    for machine in machines:
        machine.check_hardware()

    nodes_per_machine = schedule(args, machines)
    machines, nodes_per_machine = m.remove_idle(machines, nodes_per_machine)
    m.set_ip_names(args, machines, nodes_per_machine, prefixIP, postfixIP)
    delete_vms(machines)
    m.print_schedule(machines)

    for machine in machines:
        logging.debug(machine)

    logging.info('Generate configuration files for QEMU and Ansible')
    create_keypair(machines)
    create_dir(machines)
    ansible_inventory.create_inventory_machine(args, machines)
    ansible_inventory.create_inventory_vm(args, machines)

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


if __name__ == '__main__':
    """Get input arguments, and validate those arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500))

    parser.add_argument('app', type=lambda x: is_valid_application(parser, x),
                        help='application to be benchmarked with KubeEdge. Choose from: %s' % (', '.join(applications)))
    parser.add_argument('-f', '--file', type=lambda x: is_valid_file(parser, x),
                        help='file with user@host or hostnames of external nodes to use (one per line, to be used with SSH)')

    parser.add_argument('--cloudnodes', metavar='NODES', type=int, default=0,
                        help='number of cloud nodes to use (excluding cloud controller node)')
    parser.add_argument('--cloud_cores', metavar='CORES', type=int, default=4,
                        help='number of cores per cloud VM')

    parser.add_argument('--edgenodes', metavar='NODES', type=int, default=1,
                        help='number of edge nodes to use')
    parser.add_argument('--edge_cores', metavar='CORES', type=int, default=2,
                        help='number of cores per edge VM')

    parser.add_argument('--endpoints', metavar='NODES', type=int, default=1,
                        help='number of endpoints to use per edge node (when mode=edge), or per cloud (when mode=cloud) or in total (when mode=endpoint)')
    parser.add_argument('--endpoint_cores', metavar='CORES', type=int, default=1,
                        help='number of cores per endpoint container')

    parser.add_argument('--docker_pull', action='store_true',
                        help='force pull docker images')

    parser.add_argument('-m', '--mode', choices=['cloud', 'edge', 'endpoint'], default='edge',
                        help='edge continuum layer on which the processing happens')

    parser.add_argument('-v', '--verbose', action='store_true',
                        help='increase verbosity level')

    parser.add_argument('-d', '--delete', action='store_true',
                        help='Delete the VMs after the benchmark has run')

    parser.add_argument('--network', choices=['4g', '5g'], default='4g',
                        help='type of network that will be modeled')

    parser.add_argument('--controller_network', type=lambda x: is_valid_network(parser, x), default=[],
                        help='set cloud controller network settings: avg_delay,var_delay,throughput')
    parser.add_argument('--endpoint_network', type=lambda x: is_valid_network(parser, x), default=[],
                        help='set endpoint network settings: avg_delay,var_delay,throughput')

    parser.add_argument('--edge_quota', metavar='QUOTA', type=int, default=6666,
                        help='Edge VMs can only use quota us per 10000 us')
    parser.add_argument('--endpoint_quota', metavar='QUOTA', type=int, default=3333,
                        help='Endpoint VMs can only use quota us per 10000 us')

    parser.add_argument('--netperf', action='store_true',
                        help='benchmark the network between VMs using netperf')
    
    parser.add_argument('--frequency', type=int, default=5,
                        help='data generation frequency (data entities / second')

    args = parser.parse_args()

    # Check if #nodes works with given deployment mode
    if args.mode == 'cloud' and (args.cloudnodes == 0 or args.edgenodes != 0 or args.endpoints == 0):
        sys.exit('ERROR: mode=cloud requires cloudnodes>0, edgenodes=0 and endpoints>0')
    elif args.mode == 'edge' and (args.cloudnodes != 0 or args.edgenodes == 0 or args.endpoints == 0):
        sys.exit('ERROR: mode=edge requires cloudnodes=0, edgenodes>0 and endpoints>0')
    elif args.mode == 'endpoint' and (args.cloudnodes != 0 or args.edgenodes != 0 or args.endpoints == 0):
        sys.exit('ERROR: mode=endpoint requires cloudnodes=0, edgenodes=0 and endpoints>0')

    # Set loggers
    verbose_logging(args)

    main(args)
