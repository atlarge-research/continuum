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


def start_kube(args, machines):
    """Start Ansible to setup Kubernetes/KubeEdge parts on each cloud_controller/cloud/edge VM.

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start Kubernetes/KubeEdge cluster on VMs')
    processes = []

    command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
               home + '/.continuum/%s/controller_startup.yml' % (args.mode)]
    processes.append(machines[0].process(command, output=False))

    command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
               home + '/.continuum/%s/%s_startup.yml' % (args.mode, args.mode)]
    processes.append(machines[0].process(command, output=False))

    # All previous Ansible commands are running, check on Success
    for process in processes:
        logging.debug('Check output for Ansible command [%s]' % (' '.join(process.args)))
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]

        summary = False
        lines = ['']
        for line in output:
            if summary:
                lines.append(line.rstrip())

            if '==========' in line:
                summary = True

        logging.debug('\n'.join(lines))

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif any('FAILED!' in out for out in output):
            logging.error(''.join(output))
            sys.exit()

    # Delete files created by Ansible on host
    for machine in machines:
        command = ['rm', '-f', '/tmp/join-command.txt']
        output, error = machine.process(command, ssh=True)

    if args.mode == 'edge':
        # Fix logs of KubeEdge on the cloud and edge
        commands = [['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                    home + '/.continuum/edge/controller_log.yml'],
                    ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                    home + '/.continuum/edge/edge_log.yml']]

        for command in commands:
            output, error = machines[0].process(command)

            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif any('FAILED!' in out for out in output):
                logging.error(''.join(output))
                sys.exit()


def start_subscribers(args, machines):
    """Start the MQTT subscriber applications running on the cloud / edge node.
    This only needs to be done once because there only is 1 cloud controller node to submit to.
    Every cloud / edge node will automatically have 1 subscriber running using all resources of that node.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start subscriber pods on %s' % (args.mode))

    # Get location of docker image in registry
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        image = '%s:5000/%s' % (str(ip), images[args.app][0].split(':')[1])
    except Exception as e:
        logging.error('Could not get host ip: %s' % (e))
        sys.exit()

    # Set parameters
    if args.mode == 'cloud':
        cores = args.cloud_cores
        nodes = args.cloudnodes
    elif args.mode == 'edge':
        cores = args.edge_cores
        nodes = args.edgenodes

    extra_vars = \
        ' app_name=' + args.app + \
        ' image=' + str(image) + \
        ' mqtt_logs=' + str(True) + \
        ' endpoint_connected=' + str(args.endpoints) + \
        ' memory_req=' + str(cores - 0.5) + \
        ' memory_lim=' + str(cores) + \
        ' cpu_req=' + str(cores - 0.5) + \
        ' cpu_lim=' + str(cores) + \
        ' replicas=' + str(nodes - 1) + \
        ' cpu_threads=' + str(cores)

    command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms',
               '--extra-vars', extra_vars, home + '/.continuum/launch_benchmark.yml']
    output, error = machines[0].process(command)

    if error != []:
        logging.error(''.join(error))
        sys.exit()
    elif any('FAILED!' in out for out in output):
        logging.error(''.join(output))
        sys.exit()

    # Waiting for the applications to fully initialize (includes scheduling)
    time.sleep(10)
    logging.info('Deployed %i %s applications' % (nodes, args.mode))
    logging.info('Wait for subscriber applications to be scheduled and running')

    cloud_controller = machines[0].cloud_controller_names[0] + \
        '@' + machines[0].cloud_controller_ips[0]

    pending = True
    i = 0
    num_apps = args.cloudnodes + args.edgenodes

    while i < num_apps:
        # Get the list of deployed pods
        if pending:
            command = ['kubectl', 'get', 'pods', 
                    '-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase',
                    '--sort-by=.spec.nodeName']
            output, error = machines[0].process(
                command, ssh=True, ssh_target=cloud_controller)

            if error != [] and any('couldn\'t find any field with path' in line for line in error):
                logging.debug('Retry getting list of kubernetes pods')
                time.sleep(5)
                pending = True
                continue
            elif error != [] or output == []:
                logging.error(''.join(error))
                sys.exit()

        line = output[i + 1].rstrip().split(' ')
        app_name = line[0]
        app_status = line[-1]

        # Check status of app
        if app_status == 'Pending':
            time.sleep(5)
            pending = True
        elif app_status == 'Running':
            i += 1
            pending = False
        else:
            logging.error('Container on cloud/edge %s has status %s, expected \"Pending\" or \"Running\"' % (
                app_name, app_status))
            sys.exit()
