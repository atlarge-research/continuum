'''\
Execute the benchmark and get raw output
'''

import logging
import sys
import time
import os
import sys

sys.path.append(os.path.abspath('..'))

import main

from . import output


def start_worker(config, machines):
    """Start the MQTT subscriber application on cloud / edge workers.
    Submit the job request to the cloud controller, which will automatically start it on the cluster.
    Every cloud / edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start subscriber pods on %s' % (config['mode']))

    # Set parameters based on mode
    if config['mode'] == 'cloud':
        workers = config['infrastructure']['cloud_nodes'] - 1 # Includes cloud controller
        cores = config['infrastructure']['cloud_cores']
    elif config['mode'] == 'edge':
        workers = config['infrastructure']['edge_nodes']
        cores = config['infrastructure']['edge_cores']

    vars = {
        'app_name': config['benchmark']['application'].replace('_', '-'),
        'image': '%s/%s' % (config['registry'], config['images'][0].split(':')[1]),
        'mqtt_logs': True,
        'endpoint_connected': int(config['infrastructure']['endpoint_nodes'] / workers),
        'memory_req': cores - 0.5,
        'memory_lim': cores,
        'cpu_req': cores - 0.5,
        'cpu_lim': cores,
        'replicas': workers - 1, # In cloud mode, this includes controller
        'cpu_threads': cores
    }

    vars_str = ''
    for k, v in vars.items(): 
        vars_str += (str(k) + '=' + str(v) + ' ')

    # Launch applications on cloud/edge
    command = ['ansible-playbook', '-i', config['home'] + '/.continuum/inventory_vms',
               '--extra-vars', vars_str[:-1], config['home'] + '/.continuum/launch_benchmark.yml']
    main.ansible_check_output(machines[0].process(command))

    # Waiting for the applications to fully initialize (includes scheduling)
    time.sleep(10)
    logging.info('Deployed %i %s applications' % (workers, config['mode']))
    logging.info('Wait for subscriber applications to be scheduled and running')

    pending = True
    i = 0

    while i < workers:
        # Get the list of deployed pods
        if pending:
            command = ['kubectl', 'get', 'pods', 
                    '-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase',
                    '--sort-by=.spec.nodeName']
            output, error = machines[0].process(
                command, ssh=True, ssh_target=config['cloud_ssh'][0])

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


def start_endpoint(config, machines):
    """Start running the endpoint containers using Docker.
    Wait for them to finish, and get their output.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    logging.info('Deploy Docker containers on endpoints with publisher application')

    processes = []
    container_names = []
    end_per_work = int(config['infrastructure']['endpoint_nodes'] / 
        (config['infrastructure']['cloud_nodes'] + config['infrastructure']['edge_nodes'] - int(config['mode'] == 'edge')))

    # For each worker (cloud or edge), connect to end_per_work endpoints.
    for worker_i, worker_ip in enumerate(config['cloud_ips'] + config['edge_ips']):
        for endpoint_i, endpoint_ssh in enumerate(config['endpoint_ssh'][worker_i * end_per_work:(worker_i+1)*end_per_work]):
            # Docker container name and variables depends on deployment mode
            cont_name = 'endpoint%i' % (worker_i * end_per_work + endpoint_i)
            env = ['FREQUENCY=%i' % (config['benchmark']['frequency'])]

            if config['mode'] == 'cloud' or config['mode'] == 'edge':
                cont_name = '%s%i_' % (config['mode'], worker_i) + cont_name
                env.append('MQTT_SERVER_IP=%s' % (worker_ip))
            else:
                env.append('CPU_THREADS=%i' % (config['infrastructure']['endpoint_cores']))

            logging.info('Launch %s' % (cont_name))

            command = ['docker', 'container', 'run',
                '--detach',
                '--cpus=%i' % (config['infrastructure']['endpoint_cores']),
                '--memory=%ig' % (config['infrastructure']['endpoint_cores']),
                '--network=host'] + \
                ['--env %s' % (e) for e in env] + \
                ['--name', cont_name,
                config['registry'] + '/' + config['images'][1 - (int(config['mode'] == 'endpoint'))].split(':')[1]]

            processes.append(machines[0].process(command, output=False, ssh=True, ssh_target=endpoint_ssh))
            container_names.append(cont_name)

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

    return container_names


def wait_endpoint_completion(config, machines, container_names):
    """Wait for all containers to be finished running the benchmark on endpoints

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(str)): Names of docker containers launched
    """
    logging.info('Wait on all endpoint containers to finish')
    time.sleep(10)

    for ssh, cont_name in zip(config['endpoint_ssh'], container_names):
        logging.info('Wait for container to finish: %s on VM %s' % (cont_name, ssh.split('@')[0]))
        finished = False

        while not finished:
            # Get list of docker containers
            command = ['docker', 'container', 'ls', '-a', '--format', '\"{{.ID}}: {{.Status}} {{.Names}}\"']
            output, error = machines[0].process(command, ssh=True, ssh_target=ssh)

            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif output == []:
                logging.error('No output from docker container')
                sys.exit()

            # Get status of docker container
            status_line = None
            for line in output:
                if cont_name in line:
                    status_line = line

            if status_line == None:
                logging.error('ERROR: Could not find status of container %s running in VM %s: %s' % (
                    cont_name, ssh.split('@')[0], ''.join(output)))
                sys.exit()

            parsed = line.rstrip().split(' ')

            # Check status
            if parsed[1] == 'Up':
                time.sleep(5)
            elif parsed[1] == 'Exited' and parsed[2] == '(0)':
                finished = True
            else:
                logging.error('ERROR: Container %s failed in VM %s with status "%s"' % (
                    cont_name, ssh.split('@')[0], status_line))
                sys.exit()


def wait_worker_completion(config, machines):
    """Wait for all containers to be finished running the benchmark on cloud/edge workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    get_list = True
    i = 0

    # On the cloud controller, check the status of each pod, and wait until finished
    while i < config['infrastructure']['cloud_nodes'] + config['infrastructure']['edge_nodes'] - int(config['mode'] == 'edge'):
        # Get the list of deployed pods
        if get_list:
            command = ['kubectl', 'get', 'pods', 
                '-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase',
                '--sort-by=.spec.nodeName']
            output, error = machines[0].process(
                command, ssh=True, ssh_target=config['cloud_ssh'][0])

            if error != [] or output == []:
                logging.error(''.join(error))
                sys.exit()

        # Parse list, get status of app i
        line = output[i + 1].rstrip().split(' ')
        app_name = line[0]
        app_status = line[-1]

        # Check status of app i
        if app_status == 'Running':
            time.sleep(5)
            get_list = True
        elif app_status == 'Succeeded':
            i += 1
            get_list = False
        else:
            logging.error(('ERROR: Container on cloud/edge %s has status %s, expected \"Running\" or \"Succeeded\"' % (
                app_name, app_status)))
            sys.exit()


def start(config, machines):
    """Run the benchmark

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    
    Returns:
        list(str): Raw output from the benchmark
    """
    if config['mode'] == 'cloud' or config['mode'] == 'edge':
        start_worker(config, machines)
    
    container_names = start_endpoint(config, machines)

    # Wait for benchmark to finish
    wait_endpoint_completion(config, machines, container_names)
    if config['mode'] == 'cloud' or config['mode'] == 'edge':
        wait_worker_completion(config, machines)

    # Now get raw output
    logging.info('Benchmark has been finished, prepare results')
    endpoint_output = output.get_endpoint_output(config, machines, container_names)

    worker_output = []
    if config['mode'] == 'cloud' or config['mode'] == 'edge':
        worker_output = output.get_worker_output(config, machines)

    # Parse output into dicts, and print result
    worker_metrics, endpoint_metrics = output.gather_metrics(
        config, worker_output, endpoint_output, container_names)
    output.format_output(config, worker_metrics, endpoint_metrics)
