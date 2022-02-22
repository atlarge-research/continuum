'''\
Create and use QEMU Vms
'''

import sys
import logging
import os
import time

from .. import start as infrastructure

home = str(os.getenv('HOME'))


def check_ansible_proc(out):
    """Check if an Ansible Playbook succeeded or failed

    Args:
        output (list(str), list(str)): List of process stdout and stderr
    """
    output, error = out

    if error != []:
        logging.error(''.join(error))
        sys.exit()
    elif any('FAILED!' in out for out in output):
        logging.error(''.join(output))
        sys.exit()


def os_image(machines):
    """Check if the os image with Ubuntu 20.04 already exists, and if not create the image (on all machines)

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Check if a new OS image needs to be created')
    need_image = False
    for machine in machines:
        command = ['find', '/var/lib/libvirt/images/ubuntu2004.qcow2']
        output, error = machine.process(command)

        if error != [] or output == []:
            logging.info('Need to install os image')
            need_image = True
            break

    if need_image:
        command = ['ansible-playbook', '-i', home + '/.continuum/inventory', 
                   home + '/.continuum/infrastructure/os_image.yml']
        check_ansible_proc(machines[0].process(command))


def base_image(config, machines):
    """Check if the base image with Kubernetes installed already exists, and if not create the image

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Check if a new base image needs to be created')
    need_image = False
    for machine in machines:
        command = ['find', '/var/lib/libvirt/images/base.qcow2']
        output, error = machine.process(command)

        if error != [] or output == []:
            logging.info('Need to install base image')
            need_image = True
            break

    if need_image:
        command = ['ansible-playbook', '-i', home + '/.continuum/inventory', 
                   home + '/.continuum/infrastructure/base_image.yml']
        check_ansible_proc(machines[0].process(command))

        # Launch the base VMs manually, one per physical machine
        processes = []
        for machine in machines:
            if machine.is_local:
                command = 'virsh --connect qemu:///system create %s/.continuum/domain_%s.xml' % (home, machine.base_name)
            else:
                command = 'ssh %s -t \'bash -l -c "virsh --connect qemu:///system create %s/.continuum/domain_%s.xml"\'' % (
                    machine.name, home, machine.base_name)

            processes.append(machine.process(command, shell=True, output=False))

        for process in processes:
            logging.debug('Check output for command [%s]' % (''.join(process.args)))
            output = [line.decode('utf-8') for line in process.stdout.readlines()]
            error = [line.decode('utf-8') for line in process.stderr.readlines()]

            if error != [] and 'Connection to ' not in error[0]:
                sys.exit('ERROR: %s' % (''.join(error)))
            elif 'Domain ' + machine.base_name + ' created from ' not in output[0]:
                sys.exit('ERROR: %s' % (''.join(output)))

        # Fix SSH keys for each base image
        infrastructure.add_ssh(config, machines, base=True)

        # TODO
        # - Install the software on the base image based on which RM is used (or non)
        # - Copy the base_install.yml files from RM to the infrastructure folder in .continuum
        # - There will be multiple base images, not just one

        # Install netperf
        if config['infrastructure']['netperf']:
            command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                   home + '/.continuum/infrastructure/netperf.yml']
            check_ansible_proc(machines[0].process(command))

        if 'resource_manager' in config:
            if 'cloud_rm' in config['resource_manager']:
                command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                        home + '/.continuum/infrastructure/base_install_cloud.yml']
                check_ansible_proc(machines[0].process(command))

            if 'edge_rm' in config['resource_manager']:
                command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                        home + '/.continuum/infrastructure/base_install_edge.yml']
                check_ansible_proc(machines[0].process(command))
        
        # TODO 
        # - Where does this file come from
        # - Already pull the docker container in the base image? Full all base images?
        #   - Note: Will this base image stuff work for firecracker? Disk is similar so I assume it will
        #   - This requires an extra mode argument, probably in Ansible config file (or command line here)
        if 'benchmark' in config:
            command = ['ansible-playbook', '-i', home + '/.continuum/inventory_vms', 
                        home + '/.continuum/infrastructure/base_install_endpoint.yml']
            check_ansible_proc(machines[0].process(command))













        # Clean the VM
        processes = []
        for machine in machines:
            command = 'ssh %s@%s -i %s/.ssh/id_rsa_benchmark sudo cloud-init clean' % (machine.base_name, machine.base_ip, home)
            processes.append(machine.process(command, shell=True, output=False))

        for process in processes:
            logging.info('Check output for command [%s]' % (''.join(process.args)))
            output = [line.decode('utf-8') for line in process.stdout.readlines()]
            error = [line.decode('utf-8') for line in process.stderr.readlines()]
            check_ansible_proc((output, error))

        # Shutdown VMs
        processes = []
        for machine in machines:
            if machine.is_local:
                command = 'virsh shutdown %s' % (machine.base_name)
            else:
                command = 'ssh %s -t \'bash -l -c "virsh shutdown %s"\'' % (
                    machine.name, machine.base_name)

            processes.append(machine.process(command, shell=True, output=False))

        for process in processes:
            logging.debug('Check output for command [%s]' % (''.join(process.args)))
            output = [line.decode('utf-8') for line in process.stdout.readlines()]
            error = [line.decode('utf-8') for line in process.stderr.readlines()]

            if error != []:
                logging.error(''.join(error))
                sys.exit()
            elif 'Domain ' + machine.base_name + ' is being shutdown' not in output[0]:
                logging.error(''.join(output))
                sys.exit()
        
        # Wait for the shutdown to be completed
        time.sleep(5)


def start(config, machines):
    """Create and launch QEMU cloud and edge VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start VM creation using QEMU')

    # Delete older VM images
    command = ['ansible-playbook', '-i', home + '/.continuum/inventory', 
               home + '/.continuum/infrastructure/delete_images.yml']
    check_ansible_proc(machines[0].process(command))

    # Check if os and base image need to be created, and if so do create them
    os_image(machines)
    base_image(config, machines)

    # Create cloud images
    if config['infrastructure']['cloud_nodes']:
        command = ['ansible-playbook', '-i', home +
                '/.continuum/inventory', home + '/.continuum/infrastructure/cloud.yml']
        check_ansible_proc(machines[0].process(command))

    # Create edge images
    if config['infrastructure']['edge_nodes']:
        command = ['ansible-playbook', '-i', home +
            '/.continuum/inventory', home + '/.continuum/infrastructure/edge.yml']
        check_ansible_proc(machines[0].process(command))

    # Create endpoint images
    command = ['ansible-playbook', '-i', home +
            '/.continuum/inventory', home + '/.continuum/infrastructure/endpoint.yml']
    check_ansible_proc(machines[0].process(command))

    # Launch the VMs manually
    processes = []
    for machine in machines:
        for name in machine.cloud_controller_names + machine.cloud_names + machine.edge_names + machine.endpoint_names:
            if name == None:
                continue

            if machine.is_local:
                command = 'virsh --connect qemu:///system create %s/.continuum/domain_%s.xml' % (home, name)
            else:
                command = 'ssh %s -t \'bash -l -c "virsh --connect qemu:///system create %s/.continuum/domain_%s.xml"\'' % (
                    machine.name, home, name)

            processes.append(machine.process(command, shell=True, output=False))

    for process in processes:
        logging.debug('Check output for command [%s]' % (''.join(process.args)))
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]

        if error != []:
            logging.error(''.join(error))
            sys.exit()
        elif 'Domain ' not in output[0] or ' created from ' not in output[0]:
            logging.error(''.join(output))
            sys.exit()
