'''\
Get output from KubeEdge and Docker, and process it into readable format
'''

import sys
import logging
import copy
from datetime import datetime
import time
import numpy as np
import pandas as pd

def endpoint_output(machines, endpoint_names):
    """Get the output of endpoint docker containers.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(list(str)): Output of each endpoint container
    """
    logging.info('Extract output from endpoint publishers')

    endpoint_output = []
    for machine, endpoint_list in zip(machines, endpoint_names):
        for name, ip, dock_name in zip(machine.endpoint_names, machine.endpoint_ips, endpoint_list):
            logging.info('Get output from endpoint: %s' % (dock_name))
            endpoint_vm = name + '@' + ip

            # Alternatively, use docker logs -t container_name for detailed timestamps
            # Exampel: "2021-10-14T08:55:55.912611917Z Start connecting with the MQTT broker"
            command = ['docker', 'logs', '-t', dock_name]
            output, error = machines[0].process(command, ssh=True, ssh_target=endpoint_vm)

            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif output == []:
                logging.error('Container %s output empty' % (dock_name))
                sys.exit()

            output = [line.rstrip() for line in output]
            endpoint_output.append(output)

    return endpoint_output


def get_subscriber_output(args, machines):
    """Get the output of worker cloud / edge applications

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    logging.info('Gather output from subscribers')
    cloud_controller = machines[0].cloud_controller_names[0] + \
        '@' + machines[0].cloud_controller_ips[0]

    # Wait until the deployed pods are finished
    get_list = True
    i = 0

    while i < args.cloudnodes + args.edgenodes:
        # Get the list of deployed pods
        if get_list:
            command = ['kubectl', 'get', 'pods', 
                       '-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase',
                       '--sort-by=.spec.nodeName']
            output, error = machines[0].process(
                command, ssh=True, ssh_target=cloud_controller)

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

    # Given the list of pods, get their output
    sub_output = []
    for line in output[1:]:
        container = line.split(' ')[0]
        command = ['kubectl', 'logs', '--timestamps=true', container]
        output, error = machines[0].process(
            command, ssh=True, ssh_target=cloud_controller)

        if error != [] or output == []:
            logging.error(''.join(error))
            sys.exit()

        output = [line.rstrip() for line in output]
        sub_output.append(output)

    return sub_output


def to_datetime(s):
    """Parse a datetime string from docker logs to a Python datetime object

    Args:
        s (str): Docker datetime string

    Returns:
        datetime: Python datetime object
    """    
    s = s.split(' ')[0]
    s = s.replace('T', ' ')
    s = s.replace('Z', '')
    s = s[:s.find('.') + 7]
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S.%f')


def gather_worker_metrics(args, worker_output):
    """Gather metrics from cloud or edge workers

    Args:
        args (Namespace): Argparse object
        worker_output (list(list(str))): Output of each container ran on the edge

    Returns:
        list(dict): List of parsed output for each cloud or edge worker
    """
    worker_metrics = []
    if not (args.mode == 'edge' or args.mode == 'cloud'):
        return worker_metrics

    worker_set = {'worker_id': None,
                  'total_time': None,
                  'comm_delay_avg': None,
                  'comm_delay_stdev': None,
                  'proc_avg': None}

    for i, out in enumerate(worker_output):
        logging.info('Parse output from worker node %i' % (i))
        worker_metrics.append(copy.deepcopy(worker_set))
        worker_metrics[-1]['worker_id'] = i

        # Get network delay in ms (10**-3) and execution times
        # Sometimes, the program gets an incorrect line, then skip
        delays = []
        processing = []
        start_time = 0
        end_time = 0
        for line in out:
            if start_time == 0 and 'Read image and apply ML' in line:
                start_time = to_datetime(line)
            elif 'Get item' in line:
                end_time = to_datetime(line)
            elif any(word in line for word in ['Latency', 'Processing']):
                try:
                    unit = line[line.find('(')+1:line.find(')')]
                    time = int(line.rstrip().split(':')[-1])
                except Exception as e:
                    logging.warn('Got an error while parsing line: %s. Exception: %s' % (line, e))
                    continue
                
                units = ['ns']
                if time < 0:
                    logging.warn('Time < 0 should not be possible: %i' % (time))
                    continue
                elif unit not in units:
                    logging.warn('Unit should be [%s], got %s' % (','.join(units), unit))
                    continue

                if unit == 'ns':
                    if 'Latency' in line:
                        delays.append(round(time / 10**6, 4))
                    elif 'Processing' in line:
                        processing.append(round(time / 10**6, 4))

        worker_metrics[-1]['total_time'] = round((end_time - start_time).total_seconds(), 2)
        worker_metrics[-1]['comm_delay_avg'] = round(np.mean(delays), 2)
        worker_metrics[-1]['comm_delay_stdev'] = round(np.std(delays), 2)
        worker_metrics[-1]['proc_avg'] = round(np.mean(processing), 2)

    return sorted(worker_metrics, key=lambda x: x['worker_id'])


def gather_endpoint_metrics(args, endpoint_output, docker_names):
    """Gather metrics from endpoints

    Args:
        args (Namespace): Argparse object
        endpoint_output (list(list(str))): Output of each endpoint container
        docker_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(dict): List of parsed output for each endpoint
    """
    container_names = [item for sublist in docker_names for item in sublist]
    endpoint_metrics = []
    endpoint_set = {'worker_id': None,
                    'total_time': None,
                    'proc_avg': None,
                    'data_avg': None}

    for out, container_name in zip(endpoint_output, container_names):
        logging.info('Parse output from endpoint %s' % (container_name))
        endpoint_metrics.append(copy.deepcopy(endpoint_set))

        # Get timestamp from first and last line
        start_time = to_datetime(out[0])
        end_time = to_datetime(out[-1])

        endpoint_metrics[-1]['total_time'] = round((end_time - start_time).total_seconds(), 2)
        endpoint_metrics[-1]['proc_avg'] = 0.0
        endpoint_metrics[-1]['data_avg'] = 0.0

        if args.mode == 'cloud':
            name = container_name.split('_')[0]
            endpoint_metrics[-1]['worker_id'] = int(name[5:])
        elif args.mode == 'edge':            
            name = container_name.split('_')[0]
            endpoint_metrics[-1]['worker_id'] = int(name[4:])
        elif args.mode == 'endpoint':
            endpoint_metrics[-1]['worker_id'] = int(container_name[8:])

        # Parse line by line to get preparation, preprocessing and processing times
        processing = []
        data_size = []
        for line in out:
            if any(word in line for word in ['Preparation and preprocessing', 
                                             'Preparation, preprocessing and processing',
                                             'Sending data']):
                try:
                    unit = line[line.find('(')+1:line.find(')')]
                    number = int(line.rstrip().split(':')[-1])
                except Exception as e:
                    logging.warn('Got an error while parsing line: %s. Exception: %s' % (line, e))
                    continue

                units = ['ns', 'bytes']
                if number < 0:
                    logging.warn('Time/Size < 0 should not be possible: %i' % (number))
                    continue
                elif unit not in units:
                    logging.warn('Unit should be one of [%s], got %s' % (','.join(units), unit))
                    continue

                if unit == 'ns':
                    processing.append(round(number / 10**6, 4))
                elif unit == 'bytes':
                    data_size.append(round(number / 10**3, 4))

        if processing != []:
            endpoint_metrics[-1]['proc_avg'] = round(np.mean(processing), 2)
        if data_size != []:
            endpoint_metrics[-1]['data_avg'] = round(np.mean(data_size), 2)

    endpoint_metrics = sorted(endpoint_metrics, key=lambda x: x['worker_id'])

    return endpoint_metrics


def gather_metrics(args, worker_output, endpoint_output, docker_names):
    """Process the raw output to lists of dicts

    Args:
        args (Namespace): Argparse object
        worker_output (list(list(str))): Output of each container ran on the edge
        endpoint_output (list(list(str))): Output of each endpoint container
        docker_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        2x list(dict): Metrics of worker nodes and endpoints
    """
    logging.debug('Print raw output from subscribers and publishers')
    if args.mode == 'cloud' or args.mode == 'edge':
        logging.debug('------------------------------------')
        logging.debug('%s OUTPUT' % (args.mode.upper()))
        logging.debug('------------------------------------')
        for out in worker_output:
            for line in out:
                logging.debug(line)

            logging.debug('------------------------------------')

    logging.debug('------------------------------------')
    logging.debug('ENDPOINT OUTPUT')
    logging.debug('------------------------------------')
    for out in endpoint_output:
        for line in out:
            logging.debug(line)
        
        logging.debug('------------------------------------')

    worker_metrics = gather_worker_metrics(args, worker_output)
    endpoint_metrics = gather_endpoint_metrics(args, endpoint_output, docker_names)
    return worker_metrics, endpoint_metrics


def format_output(args, sub_metrics, endpoint_metrics):
    """Format processed output to provide useful insights

    Args:
        args (Namespace): Argparse object
        sub_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
    """
    df1 = None
    if args.mode == 'cloud' or args.mode == 'edge':
        logging.info('------------------------------------')
        logging.info('%s OUTPUT' % (args.mode.upper()))
        logging.info('------------------------------------') 
        df1 = pd.DataFrame(sub_metrics)
        df1.rename(columns={'total_time': 'total_time (s)', 
                           'comm_delay_avg': 'delay_avg (ms)', 
                           'comm_delay_stdev': 'delay_stdev (ms)', 
                           'proc_avg': 'proc/data (ms)'}, 
                           inplace=True)
        df1_no_indices = df1.to_string(index=False)
        logging.info('\n' + df1_no_indices)

    logging.info('------------------------------------')
    logging.info('ENDPOINT OUTPUT')
    logging.info('------------------------------------')
    if args.mode == 'cloud' or args.mode == 'edge':
        df2 = pd.DataFrame(endpoint_metrics)
        df2.rename(columns={'worker_id': 'connected_to',
                           'total_time': 'total_time (s)', 
                           'proc_avg': 'preproc/data (ms)',
                           'data_avg': 'data_size_avg (kb)'}, 
                           inplace=True)
    else:
        df2 = pd.DataFrame(endpoint_metrics, columns=['worker_id', 'total_time', 'proc_avg'])
        df2.rename(columns={'worker_id': 'endpoint_id',
                           'total_time': 'total_time (s)', 
                           'proc_avg': 'proc/data (ms)'}, 
                           inplace=True)

    df2_no_indices = df2.to_string(index=False)
    logging.info('\n' + df2_no_indices)

    # Print ouput in csv format
    if args.mode == 'cloud' or args.mode == 'edge':
        logging.debug('Output in csv format\n%s\n%s' % (repr(df1.to_csv()), repr(df2.to_csv())))
    else:
        logging.debug('Output in csv format\n%s' % (repr(df2.to_csv())))

#     logging.debug('''
# ------------------------------------
# GENERATED FILES
# ------------------------------------
# WHAT                        PATH
# VM images                   /var/lib/libvirt/images/
# Configuration files         ${HOME}/.edge/
# Logs                        <path>/edge-benchmark-RM/logs/
# SSH key                     ${HOME}/.ssh/id_rsa_benchmark

# ------------------------------------
# COMMANDS
# ------------------------------------
# COMMAND                     DESCRIPTION
# virsh list                  List the running VMs
# docker images               List available docker images
# docker container ls -a      List running and exited docker containers
# ssh name@ip -i key          SSH to a running VM. See printed machine objects for more info
# docker container logs ID    Get the logs of a docker container
# kubectl get nodes/pods      Get list of available nodes/pods in Kubernetes
# kubectl describe node/pod   Get more info on nodes/pods
# kubectl logs podname        Get the logs of a kubernetes pod
# ''')
# Shutdown all VMs: virsh list --all | grep -o -E "(cloud\w*|edge\w*|endpoint\w*)" | xargs -I % sh -c 'virsh destroy %'
