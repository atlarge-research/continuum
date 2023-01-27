# Network
This file describes how to setup and configure bridged network interfaces if you want to use Continuum with Libvirt on multiple physical machines. This allows for large scale infrastructure deployments. The network bridge is required for VMs on different physical machines to directly communicate with each other.

## Creating a network bridge
We assume the operating system is Ubuntu 20.04 with Netcat for network configuration, and that a default, bridgeless Netcat configuration file already exists. Simimlar network bridge configuration can be done on other operating systems.

```
# Check if there already is a network bridge active on your machine. If so, you are done.
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
Finally, use the correct configuration parameters to reflect your network settings using settings "prefixIP", "middleIP", and "middleIP_base". 
Here, if your IP range is AAA.BBB.CCC.DDD, prefixIP=AAA.BBB, and middleIP(_base)=CCC. DDD is set between 2 and 252 for all subranges.
We assume the network bridge is called `br0`, otherwise change all occurences of `br0` in the framework (e.g., using grep).