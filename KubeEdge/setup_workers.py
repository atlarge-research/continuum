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


def get_ips(machines):
    """Get a list of all VM ips

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(str x 4: Lists of cloud controller, cloud/edge worker, endpoint, and base VM ips
    """
    logging.debug('Get ips of controllers/workers')
    control_ips = []
    worker_ips = []
    endpoint_ips = []
    base_ips = []

    for machine in machines:
        if machine.cloud_controller > 0:
            control_ips += machine.cloud_controller_ips
        if machine.clouds > 0:
            worker_ips += machine.cloud_ips
        if machine.edges > 0:
            worker_ips += machine.edge_ips
        if machine.endpoints > 0:
            endpoint_ips += machine.endpoint_ips
        if machine.base_ip != None:
            base_ips += [machine.base_ip]

    return control_ips, worker_ips, endpoint_ips, base_ips


def network_delay_commands(latency_avg, latency_var, throughput, overhead, ips):
    """Generate TC commands

    Args:
        latency_avg (float): Delay in ms
        latency_var (float): Delay variance in ms
        throughput (int): Throughput in mbit
        packets_overhead (int): Increase the buffer by x for safety
        ips (list(str)): List of ips to filter TC for

    Returns:
        list(str): List of TC commands
    """    
    logging.debug('Generate TC commands')
    commands = []
    commands.append(['sudo', 'tc', 'qdisc', 'add', 'dev', 'ens2', 'root', 'handle', '1:', 'prio'])

    # With x delay and y throughput, a buffer of at least x * y is needed to hold data
    # Convert latency from ms to sec, and throughput from mbit to byte
    buffer = int((latency_avg / 1000.0) * (throughput * 1000000.0 / 8.0) * overhead)

    commands.append(['sudo', 'tc', 'qdisc', 'add', 'dev', 'ens2', 'parent', '1:3', 'handle', '30:', 
                     'tbf', 'rate', '%smbit' % (throughput), 'buffer', str(buffer), 'latency', '%sms' % (latency_avg * overhead)])
    commands.append(['sudo', 'tc', 'qdisc', 'add', 'dev', 'ens2', 'parent', '30:1', 'handle', '31:', 
                     'netem', 'delay', '%sms' % (latency_avg), '%sms' % (latency_var), 'distribution', 'normal'])

    for ip in ips:
        commands.append(['sudo', 'tc', 'filter', 'add', 'dev', 'ens2', 'protocol', 'ip', 'parent', '1:0', 'prio',
                         '3', 'u32', 'match', 'ip', 'dst', ip, 'flowid', '1:3'])

    return commands


def network_delay(args, machines):
    """Add network latency between VMs to emulate edge continuum networking
    Finally, benchmark the latency to check if the latency is as expected

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """    
    logging.info('Add network latency between VMs')

    # Set [latency_avg, latency_var, throughput]
    if args.mode == 'cloud':
        controller = args.controller_network
        if controller == []:
            # From cloud controller to cloud worker
            controller = [7.5, 2.5, 1000]

        endpoint = args.endpoint_network
        if endpoint == []:
            # From endpoint to cloud worker
            if args.network == '4g':
                endpoint = [45, 5, 7.21]
            elif args.network == '5g':
                endpoint = [45, 5, 29.66]
    elif args.mode == 'edge':
        controller = args.controller_network
        if controller == []:
            # From cloud controller to edge worker
            controller = [25, 5, 100]

        endpoint = args.endpoint_network
        if endpoint == []:
            # From endpoint to edge worker
            if args.network == '4g':
                endpoint = [7.5, 2.5, 5]
            elif args.network == '5g':
                endpoint = [7.5, 2.5, 29.66]

    overhead = 2 # Increase buffer by *x for safety
    control_ips, worker_ips, _, _ = get_ips(machines)
    out = []

    # Generate all TC commands, and execute them
    for machine in machines:
        # Controller
        for name, ip in zip(machine.cloud_controller_names, machine.cloud_controller_ips):
            commands = network_delay_commands(controller[0], controller[1], controller[2], overhead, worker_ips)
            vm = name + '@' + ip
            for command in commands:
                out.append(machines[0].process(command, ssh=True, ssh_target=vm))

        # Worker
        for name, ip in zip(machine.cloud_names + machine.edge_names, machine.cloud_ips + machine.edge_ips):
            commands = network_delay_commands(controller[0], controller[1], controller[2], overhead, control_ips)
            vm = name + '@' + ip
            for command in commands:
                out.append(machines[0].process(command, ssh=True, ssh_target=vm))
        
        # Endpoint
        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            commands = network_delay_commands(endpoint[0], endpoint[1], endpoint[2], overhead, worker_ips)
            vm = name + '@' + ip
            for command in commands:
                out.append(machines[0].process(command, ssh=True, ssh_target=vm))

    # Check output of TC commands
    for output, error in out:
        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif output != []:
            logging.error(''.join(output))
            sys.exit()


def netperf_commands(target_ips):
    """Generate latency or throughput commands for netperf

    Args:
        target_ips (list(str)): List of ips to use netperf to
        mode (str): Generate latency or throughput commands

    Returns:
        list(str): List of netperf commands
    """
    lat_commands = []
    tp_commands = []
    for ip in target_ips:
        lat_commands.append(['netperf', '-H', ip, '-t', 'TCP_RR','--', '-O',
            'min_latency,mean_latency,max_latency,stddev_latency,transaction_rate,p50_latency,p90_latency,p99_latency'])
    
        tp_commands.append(['netperf', '-H', ip, '-t', 'TCP_STREAM'])

    return lat_commands, tp_commands


def benchmark_network(args, machines):
    """Benchmark network 

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    control_ips, worker_ips, endpoint_ips, _ = get_ips(machines)

    # Test controller -> worker(s) 
    lat_commands, tp_commands = netperf_commands(worker_ips)
    for ip in control_ips:
        vm = 'cloud_controller@' + ip

        for command in lat_commands + tp_commands:
            output, error = machines[0].process(command, ssh=True, ssh_target=vm)
            logging.info('Controller (%s) -> Worker: %s' % (vm, command))
            logging.info('\n' + ''.join(output))
            logging.info('\n' + ''.join(error))

    # Test worker(s) -> controller
    lat_commands, tp_commands = netperf_commands(control_ips)
    for i, ip in enumerate(worker_ips):
        if args.mode == 'cloud':
            vm = 'cloud%i@%s' % (i, ip)
        elif args.mode == 'edge':
            vm = 'edge%i@%s' % (i, ip)

        for command in lat_commands + tp_commands:
            output, error = machines[0].process(command, ssh=True, ssh_target=vm)
            logging.info('Worker (%s) -> Controller: %s' % (vm, command))
            logging.info('\n' + ''.join(output))
            logging.info('\n' + ''.join(error))

    # Test endpoint(s) -> worker(s)
    lat_commands, tp_commands = netperf_commands(worker_ips)
    for i, ip in enumerate(endpoint_ips):
        vm = 'endpoint%i@%s' % (i, ip)

        for command in lat_commands + tp_commands:
            output, error = machines[0].process(command, ssh=True, ssh_target=vm)
            logging.info('Endpoint (%s) -> Worker: %s' % (vm, command))
            logging.info('\n' + ''.join(output))
            logging.info('\n' + ''.join(error))


def start_kube(args, machines):
    """Start Ansible to setup Kubernetes/KubeEdge parts on each cloud_controller/cloud/edge VM.

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start Kubernetes/KubeEdge cluster on VMs')
    processes = []

    command = ['ansible-playbook', '-i', home + '/.edge/inventory_vms', 
               home + '/.edge/%s/controller_startup.yml' % (args.mode)]
    processes.append(machines[0].process(command, output=False))

    command = ['ansible-playbook', '-i', home + '/.edge/inventory_vms', 
               home + '/.edge/%s/%s_startup.yml' % (args.mode, args.mode)]
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
        commands = [['ansible-playbook', '-i', home + '/.edge/inventory_vms', 
                    home + '/.edge/edge/controller_log.yml'],
                    ['ansible-playbook', '-i', home + '/.edge/inventory_vms', 
                    home + '/.edge/edge/edge_log.yml']]

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

    command = ['ansible-playbook', '-i', home + '/.edge/inventory_vms',
               '--extra-vars', extra_vars, home + '/.edge/launch_benchmark.yml']
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
