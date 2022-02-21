'''\
Generate Ansible inventory files, and start ansible playbooks
'''

import sys
import logging
import os
import time
import socket

home = str(os.getenv('HOME'))
images = {'image-classification': ['redplanet00/kubeedge-applications:image_classification_subscriber',
                                   'redplanet00/kubeedge-applications:image_classification_publisher',
                                   'redplanet00/kubeedge-applications:image_classification_combined']}


def setup_docker(machines):
    """Do the set up of Docker on each endpoint VM

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start and set up Docker on VMs')

    # Start Docker in endpoints
    command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
               home + '/.continuum/endpoint/endpoint_startup.yml']
    output, error = machines[0].process(command)

    if error != []:
        logging.error(''.join(error))
        sys.exit()
    elif any('FAILED!' in out for out in output):
        logging.error(''.join(output))
        sys.exit()


def start_publisher(args, machines):
    """Start running the endpoint containers using Docker.
    Wait for them to finish, and get their output.

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    logging.info('Deploy Docker containers on endpoints with publisher application')

    # Images need to be pulled from local registry, get address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]

        if args.mode == 'cloud' or args.mode == 'edge':
            image = '%s:5000/%s' % (str(host_ip), images[args.app][1].split(':')[1])
        else:
            image = '%s:5000/%s' % (str(host_ip), images[args.app][2].split(':')[1])
    except Exception as e:
        logging.error('Could not get host ip: %s' % (e))
        sys.exit()

    # Pull the images
    processes = []
    for machine in machines:
        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            endpoint_vm = name + '@' + ip

            command = ['docker', 'pull', image]
            processes.append([name, machines[0].process(command, output=False, ssh=True, ssh_target=endpoint_vm)])

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
                name, name, machines[0].name, name, host_ip))
        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output == []:
            logging.error('No output from command docker pull')
            sys.exit()

    # Launch endpoints with the correct arguments based on the deployment mode
    if args.mode == 'cloud':
        worker_ips = [ip for machine in machines for ip in machine.cloud_ips]
    elif args.mode == 'edge':
        worker_ips = [ip for machine in machines for ip in machine.edge_ips]

    processes = []
    endpoint_names = []
    worker_index = 0
    endpoint_index = 0

    # Set variables based on deployment mode, and launch the containers
    for machine in machines:
        endpoint_names.append([])
        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            endpoint_vm = name + '@' + ip

            if args.mode == 'cloud':
                logging.info('Launch endpoint %i for cloud node %i' % (endpoint_index, worker_index))
                dock_name = 'cloud%i_endpoint%i' % (worker_index, endpoint_index)
                env = ['MQTT_SERVER_IP=%s' % (worker_ips[worker_index]), 'FREQUENCY=%i' % (args.frequency)]
            elif args.mode == 'edge':
                logging.info('Launch endpoint %i for edge node %i' % (endpoint_index, worker_index))
                dock_name = 'edge%i_endpoint%i' % (worker_index, endpoint_index)
                env = ['MQTT_SERVER_IP=%s' % (worker_ips[worker_index]), 'FREQUENCY=%i' % (args.frequency)]
            elif args.mode == 'endpoint':
                logging.info('Launch endpoint %i' % (endpoint_index))
                dock_name = 'endpoint%i' % (endpoint_index)
                env = ['CPU_THREADS=%i' % (args.endpoint_cores), 'FREQUENCY=%i' % (args.frequency)]

            command = ['docker', 'container', 'run',
                    '--detach',
                    '--cpus=%i' % (args.endpoint_cores),
                    '--memory=%ig' % (args.endpoint_cores),
                    '--network=host'] + \
                    ['--env %s' % (e) for e in env] + \
                    ['--name', dock_name,
                    image]

            processes.append(machines[0].process(command, output=False, ssh=True, ssh_target=endpoint_vm))

            # Update metadata
            endpoint_names[-1].append(dock_name)
            endpoint_index += 1

            # Make sure only N endpoints connect to a single worker node
            if args.mode == 'cloud' or args.mode == 'edge':
                if endpoint_index == args.endpoints:
                    worker_index += 1
                    endpoint_index = 0

    # Checkout process output
    for process in processes:
        logging.debug('Check output of command [%s]' % (' '.join(process.args)))
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]

        if error != [] and 'Your kernel does not support swap limit capabilities' not in error[0]:
            logging.error(''.join(error))
            sys.exit()
        elif output == []:
            logging.error('No output from docker container')
            sys.exit()

    return endpoint_names


def wait_completion(machines, endpoint_names):
    """Wait for all containers to be finished running the benchmark

    Args:
        machines ([type]): [description]
        endpoint_names ([type]): [description]
    """    
    logging.info('Wait on all endpoint containers to finish')
    time.sleep(10)

    # For every endpoint running inside a VM, check for completion
    for machine, endpoint_list in zip(machines, endpoint_names):
        for name, ip, dock_name in zip(machine.endpoint_names, machine.endpoint_ips, endpoint_list):
            endpoint_vm = name + '@' + ip
            up = False

            while not up:
                # Get list of docker containers
                command = ['docker', 'container', 'ls', '-a', '--format', '\"{{.ID}}: {{.Status}} {{.Names}}\"']
                output, error = machines[0].process(command, ssh=True, ssh_target=endpoint_vm)

                if error != []:
                    logging.error(''.join(error))
                    sys.exit()
                elif output == []:
                    logging.error('No output from docker container')
                    sys.exit()

                # Get status of docker container
                status_line = None
                for line in output:
                    if dock_name in line:
                        status_line = line
                
                if status_line == None:
                    logging.error('ERROR: Could not find status of container %s running in VM %s on machine %s: %s' % (
                        dock_name, name, machine.name, ''.join(output)))
                    sys.exit()

                parsed = line.rstrip().split(' ')

                # Check status
                if parsed[1] == 'Up':
                    time.sleep(5)
                elif parsed[1] == 'Exited' and parsed[2] == '(0)':
                    up = True
                else:
                    logging.error('ERROR: container %s failed in VM %s on machine %s with status "%s"' % (
                        dock_name, name, machine.name, status_line))
                    sys.exit()
