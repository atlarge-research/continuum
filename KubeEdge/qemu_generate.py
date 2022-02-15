'''\
Generate a QEMU configuration file
The file is generated from scratch instead of using an existing template file as
too many things can change depending on user input.
'''

import logging
from pathlib import Path


DOMAIN = """\
<domain type='kvm'>
    <name>%s</name>
    <memory>%i</memory>
    <os>
        <type>hvm</type>
        <boot dev="hd" />
    </os>
    <features>
        <acpi/>
    </features>
    <vcpu placement="static">%i</vcpu>
    <cputune>
        <period>%i</period>
        <quota>%i</quota>
%s
    </cputune>
    <devices>
        <interface type='bridge'>
            <source bridge='br0'/>
            <model type='e1000'/>
        </interface>
        <disk type='file' device='disk'>
            <driver type='qcow2' cache='none'/>
            <source file='/var/lib/libvirt/images/%s.qcow2'/>
            <target dev='vda' bus='virtio'/>
        </disk>
        <disk type='file' device='disk'>
            <source file='/var/lib/libvirt/images/user_data_%s.img'/>
            <target dev='vdb' bus='virtio'/>
        </disk>
        <console type="pty">
           <target type="serial" port="1"/>
        </console>
    </devices>
</domain>
"""

USER_DATA = """\
#cloud-config
hostname: %s
fqdn: %s
manage_etc_hosts: true
users:
  - name: %s
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, admin
    home: /home/%s
    shell: /bin/bash
    lock_passwd: false
    ssh-authorized-keys:
      - %s
ssh_pwauth: false
disable_root: false
chpasswd:
  list: |
     %s:password
  expire: False
write_files:
- path: /etc/cloud/cloud.cfg.d/99-custom-networking.cfg
  permissions: '0644'
  content: |
    network: {config: disabled}
- path: /etc/netplan/new-config.yaml
  permissions: '0644'
  content: |
    network:
      version: 2
      ethernets:
        ens2:
          dhcp4: false
          addresses: [%s/16]
          gateway4: 192.168.1.100
          nameservers:
            addresses: [1.1.1.1, 8.8.8.8]
            search: []
runcmd:
 - rm /etc/netplan/50-cloud-init.yaml
 - netplan generate
 - netplan apply
# written to /var/log/cloud-init-output.log
final_message: "The system is finally up, after $UPTIME seconds"
"""

def generate_config(args, machines):
    """Create QEMU config files for each machine

    Args:
        args (Namespace): Argparse object
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info('Start writing QEMU config files for cloud / edge')

    # Get the SSH public key
    home = str(Path.home())
    f = open(home + '/.ssh/id_rsa_benchmark.pub', 'r')
    ssh_key = f.read().rstrip()
    f.close()

    # Counter for pinning vcpu to physical cpu
    start_core = 0

    for i, machine in enumerate(machines):
        # Clouds
        for ip, name in zip(machine.cloud_controller_ips + machine.cloud_ips, 
                            machine.cloud_controller_names + machine.cloud_names):        
            f = open('.tmp/domain_%s.xml' % (name), 'w')
            memory = 1048576 * args.cloud_cores
            pinnings = ['        <vcpupin vcpu="%i" cpuset="%i"/>' % (a,b) for a,b in zip(range(args.cloud_cores), range(start_core,start_core+args.cloud_cores))]
            start_core += args.cloud_cores
            f.write(DOMAIN % (name, memory, args.cloud_cores, 10000 * 10, 10000 * 10, '\n'.join(pinnings), name, name))
            f.close()

            f = open('.tmp/user_data_%s.yml' % (name), 'w')
            hostname = name.replace('_', '')
            f.write(USER_DATA % (hostname, hostname, name, name, ssh_key, name, ip))
            f.close()

        # Edges
        for ip, name in zip(machine.edge_ips, machine.edge_names):
            f = open('.tmp/domain_%s.xml' % (name), 'w')
            memory = 1048576 * args.edge_cores
            pinnings = ['        <vcpupin vcpu="%i" cpuset="%i"/>' % (a,b) for a,b in zip(range(args.edge_cores), range(start_core,start_core+args.edge_cores))]
            start_core += args.edge_cores
            f.write(DOMAIN % (name, memory, args.edge_cores, 10000 * 10, args.edge_quota * 10, '\n'.join(pinnings), name, name))
            f.close()

            f = open('.tmp/user_data_%s.yml' % (name), 'w')
            f.write(USER_DATA % (name, name, name, name, ssh_key, name, ip))
            f.close()

        # Endpoints
        for ip, name in zip(machine.endpoint_ips, machine.endpoint_names):
            f = open('.tmp/domain_%s.xml' % (name), 'w')
            memory = 1048576 * args.endpoint_cores
            pinnings = ['        <vcpupin vcpu="%i" cpuset="%i"/>' % (a,b) for a,b in zip(range(args.endpoint_cores), range(start_core,start_core+args.endpoint_cores))]
            start_core += args.endpoint_cores
            f.write(DOMAIN % (name, memory, args.endpoint_cores, 10000 * 10, args.endpoint_quota * 10, '\n'.join(pinnings), name, name))
            f.close()

            f = open('.tmp/user_data_%s.yml' % (name), 'w')
            f.write(USER_DATA % (name, name, name, name, ssh_key, name, ip))
            f.close()

        # Base image
        f = open('.tmp/domain_base%i.xml' % (i), 'w')
        memory = 1048576 * args.cloud_cores
        pinnings = ['        <vcpupin vcpu="%i" cpuset="%i"/>' % (a,b) for a,b in zip(range(args.cloud_cores), range(start_core,start_core+args.cloud_cores))]
        start_core += args.cloud_cores
        f.write(DOMAIN % (machine.base_name, memory, args.cloud_cores, 0, 0, '\n'.join(pinnings), 'base', 'base'))
        f.close()

        f = open('.tmp/user_data_base%i.yml' % (i), 'w')
        f.write(USER_DATA % (machine.base_name, machine.base_name, machine.base_name, machine.base_name, ssh_key, machine.base_name, machine.base_ip))
        f.close()
