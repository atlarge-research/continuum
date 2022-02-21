'''\
Use TC to control latency / throughput between VMs, and perform network benchmarks with netperf.
'''

import logging
import sys


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








# TODO
# Currently, this network shaping doesn't work in infra-only mode, where you don't have cloud controllers
#   but maybe only edge and cloud works, which can't work in the benchmark

# add endpoint delay to cloud and edge if both are present -> needed for infra-only mode
# 

def start(config, machines):
    """Add network latency between VMs to emulate edge continuum networking
    Finally, benchmark the latency to check if the latency is as expected

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """    
    logging.info('Add network latency between VMs')

    cloud = [7.5, 2.5, 1000]
    cloud_4g = [45, 5, 7.21]
    cloud_5g = [45, 5, 29.66]
    edge_4g = [7.5, 2.5, 5]
    edge_5g = [7.5, 2.5, 29.66]

    # sys.exit()

    # TODO: Need a name or name@ip catalog as well! Or simply a getter function given an ip give ssh code
    # config['control_ips']
    # config['worker_ips']
    # config['endpoint_ips']
    # config['base_ips']

    # # Between cloud nodes
    # for controller in config['control_ips']

    # # Set [latency_avg, latency_var, throughput]
    # if config['infrastructure']['cloud_nodes']:


    if config['infrastructure']['cloud_nodes'] and not config['infrastructure']['edge_nodes']:
        controller = config['infrastructure']['']
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
    out = []

    # Generate all TC commands, and execute them
    for machine in machines:
        # Controller
        for name, ip in zip(machine.cloud_controller_names, machine.cloud_controller_ips):
            commands = network_delay_commands(controller[0], controller[1], controller[2], overhead, config['worker_ips'])
            vm = name + '@' + ip
            for command in commands:
                out.append(machines[0].process(command, ssh=True, ssh_target=vm))

        # Worker
        for name, ip in zip(machine.cloud_names + machine.edge_names, machine.cloud_ips + machine.edge_ips):
            commands = network_delay_commands(controller[0], controller[1], controller[2], overhead, config['control_ips'])
            vm = name + '@' + ip
            for command in commands:
                out.append(machines[0].process(command, ssh=True, ssh_target=vm))
        
        # Endpoint
        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            commands = network_delay_commands(endpoint[0], endpoint[1], endpoint[2], overhead, config['worker_ips'])
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


def benchmark(config, machines):
    """Benchmark network 

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Test controller -> worker(s) 
    lat_commands, tp_commands = netperf_commands(config['worker_ips'])
    for ip in config['control_ips']:
        vm = 'cloud_controller@' + ip

        for command in lat_commands + tp_commands:
            output, error = machines[0].process(command, ssh=True, ssh_target=vm)
            logging.info('Controller (%s) -> Worker: %s' % (vm, command))
            logging.info('\n' + ''.join(output))
            logging.info('\n' + ''.join(error))

    # Test worker(s) -> controller
    lat_commands, tp_commands = netperf_commands(config['control_ips'])
    for i, ip in enumerate(config['worker_ips']):
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
    lat_commands, tp_commands = netperf_commands(config['worker_ips'])
    for i, ip in enumerate(config['endpoint_ips']):
        vm = 'endpoint%i@%s' % (i, ip)

        for command in lat_commands + tp_commands:
            output, error = machines[0].process(command, ssh=True, ssh_target=vm)
            logging.info('Endpoint (%s) -> Worker: %s' % (vm, command))
            logging.info('\n' + ''.join(output))
            logging.info('\n' + ''.join(error))
