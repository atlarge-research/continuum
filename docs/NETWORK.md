# Network
This file describes how to setup and configure bridge network interfaces in case you want to use this benchmark with multiple physical machines so as to deploy more VMs and containers. Network bridges are needed so VMs and containers deployed on different physical machines can directly access each other.

Ignore this file if using the Terraform version of the benchmark, as that version only works on a single physical machine. 
For the QEMU version, the use of a network bridge is mandatory, even when only using a single physical machine. If your system already uses network bridges, skip the next section.

## Creating a network bridge
We assume the operating system is Ubuntu 20.04 with Netcat for network configuration, and that a default, bridgeless Netcat configuration file already exists.

```
# Check if there is a network bridge active on your machine. If so, stop.
# Ignore virtual bridges such as docker0 and virbr0. Most often a bridge is called 'br0'.
brctl show

# List current virtual networks still active
virsh net-list

# Destroy all virtual network. Example name: default
virsh net-destroy default
virsh net-undefine default

# Make a backup of the bridgeless config file, called '***.yaml.bak
cp /etc/netplan/00-installer-config.yaml /etc/netplan/00-installer-config.yaml.bak

# Edit the original file and add the bridge. 
# Copy the settings from the original ethernet interface to the bridge interface, 
# while adding a 'interfaces: ' option, refering to the ethernet interface.
# The final file should look similar to this:
'''
network:
  ethernets:
    eno1:
      dhcp4: false
      dhcp6: false
  bridges:
    br0:
      interfaces: [eno1]
      addresses:
      - xxx.xxx.x.x/xx
      gateway4: xxx.xxx.x.x
      nameservers:
        addresses: [x.x.x.x, x.x.x.x]
        search: []
      parameters:
        stp: true
      dhcp4: false
      dhcp6: false
'''

# Apply this new configuration
netplan generate
netplan apply

# Possibly needed to reboot the system
systemctl restart systemd=network

# Finally, disable netfilter on the bridge
# Not doing this may result in the VM not being able to communicate outside of the host machine
cat >> /etc/sysctl.conf <<EOF
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-arptables = 0
EOF

sysctl -p /etc/sysctl.conf
```

## Updating network configuration
Finally, update the benchmark code with the correct gateway4 and nameserver settings among others. Please see `KubeEdge/qemu_generate.py`, and update the `NETWORK_CONFIG` string to reflect your settings. Do only replace the hardcoded values.