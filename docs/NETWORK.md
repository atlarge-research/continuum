# Network

This file describes the host-side network setup used by Continuum's local
QEMU/libvirt provider. It is operational guidance, not part of the YAML schema.
For YAML network keys, see `docs/configuration_reference.md`.

## When A Bridge Is Needed

A bridge is needed when QEMU VMs must communicate directly across host or
physical-machine boundaries. Single-host smoke paths can often use the host's
existing libvirt/QEMU setup, but the operational smoke baseline still expects
working `virsh`, SSH, and bridge/route discovery.

The dedicated smoke wrapper can preserve explicit overrides when the host setup
forwards them:

```bash
CONTINUUM_QEMU_BRIDGE_NAME=br0
CONTINUUM_QEMU_BRIDGE_GATEWAY=192.168.100.1
```

Use overrides only to describe the real host network. They should not be used to
hide broken libvirt or route setup.

## Creating A Bridge On Ubuntu-like Hosts

The exact netplan file depends on the host. The outline is:

```bash
# Inspect current interfaces and routes
ip addr
ip route

# Inspect existing libvirt networks
virsh net-list --all

# Back up the current netplan file before editing
sudo cp /etc/netplan/00-installer-config.yaml /etc/netplan/00-installer-config.yaml.bak
```

A typical bridge shape is:

```yaml
network:
  version: 2
  ethernets:
    eno1:
      dhcp4: false
      dhcp6: false
  bridges:
    br0:
      interfaces: [eno1]
      addresses: [192.0.2.10/24]
      routes:
        - to: default
          via: 192.0.2.1
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
      parameters:
        stp: true
      dhcp4: false
      dhcp6: false
```

Apply and verify:

```bash
sudo netplan generate
sudo netplan apply
ip addr show br0
ip route
```

## Bridge Netfilter

If VMs cannot reach outside networks even though the bridge exists, check bridge
netfilter settings:

```bash
sudo tee -a /etc/sysctl.conf <<EOF
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-arptables = 0
EOF
sudo sysctl -p /etc/sysctl.conf
```

## YAML Network Settings

Active YAML configs set network intent under `infrastructure.network`:

```yaml
infrastructure:
  network:
    emulation: true
    wireless_preset: 4g
    overrides: {}
```

IP range defaults live in environment profiles under `provider.config.ip`:

```yaml
provider:
  config:
    ip:
      prefix: "192.168"
      middle: 100
      middle_base: 90
```

Do not edit code to replace `br0` for normal runs. Prefer host setup,
environment profiles, or the explicit wrapper bridge override variables when
the host really uses a different bridge.
