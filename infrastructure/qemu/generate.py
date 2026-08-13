"""\
Generate a QEMU configuration file
The file is generated from scratch instead of using an existing template file as
too many things can change depending on user input.
"""

from decimal import Decimal, ROUND_CEILING
import logging
import os
import re
import sys
import socket
import struct

from infrastructure import orchestration_schema
from input.configuration import config_access

_IPV4_PATTERN = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
_KIB_PER_GIB = 1048576


def _tmp_path(config, name):
    """Return the canonical generated-artifact path for one temp file."""
    root = config.get("tmp_dir", os.path.join(config.get("base", "."), ".tmp"))
    return os.path.join(root, name)


def _memory_gib_to_kib(memory_gib):
    """Convert GiB to whole KiB without provisioning less memory than requested."""
    numerator, denominator = memory_gib.as_integer_ratio()
    scaled_numerator = numerator * _KIB_PER_GIB
    aligned_memory_kib, remainder = divmod(scaled_numerator, denominator)
    if remainder == 0:
        return aligned_memory_kib

    memory_kib = Decimal(str(memory_gib)) * Decimal(_KIB_PER_GIB)
    return int(memory_kib.to_integral_value(rounding=ROUND_CEILING))


DOMAIN = """\
<domain type='kvm'>
    <name>%s</name>
    <memory>%i</memory>
    <os>
        <type>hvm</type>
        <boot dev="hd"/>
    </os>
%s
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
            <source bridge='%s'/>
            <model type='e1000'/>
        </interface>
        <disk type='file' device='disk'>
            <driver type='qcow2' cache='none'/>
            <source file='%s/.continuum/images/%s.qcow2'/>
            <target dev='vda' bus='virtio'/>
            <iotune>
                <read_bytes_sec>%i</read_bytes_sec>
                <write_bytes_sec>%i</write_bytes_sec>
                <read_bytes_sec_max>%i</read_bytes_sec_max>
                <write_bytes_sec_max>%i</write_bytes_sec_max>
            </iotune>
        </disk>
        <disk type='file' device='disk'>
            <source file='%s/.continuum/images/user_data_%s.img'/>
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
        primary:
          match:
            name: "e*"
          dhcp4: false
          addresses: [%s/16]
          gateway4: %s
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


def _render_user_data(hostname, guest_user, ssh_key, ip, gateway):
    """Render cloud-init user-data for one generated QEMU guest."""
    return USER_DATA % (
        hostname,
        hostname,
        guest_user,
        guest_user,
        ssh_key,
        guest_user,
        ip,
        gateway,
    )


def find_bridge(config, machine, bridge):
    """Check if bridge <bridge> is available on the system.

    Args:
        config (dict): Parsed configuration
        machine (Machine object): Object representing the physical machine we currently use
        bridge (str): Bridge name to check

    Returns:
        int: Bool representing if we found the bridge on this machine
    """
    output, error = machine.process(
        config, "brctl show | grep '^%s' | wc -l" % (bridge), shell=True
    )[0]
    if error != [] or output == []:
        logging.error("ERROR: Could not find a network bridge")
        sys.exit(1)

    return int(output[0].rstrip())


def _extract_gateway_from_lines(lines, prefer_second=False):
    """Extract one IPv4 address from route or addr output lines."""
    fallback = None
    for line in lines:
        matches = _IPV4_PATTERN.findall(line)
        if prefer_second and len(matches) > 1:
            return matches[1]
        if matches and fallback is None:
            fallback = matches[0]
    return fallback


def _extract_gateway_from_proc_net_route(lines, bridge_name):
    """Extract a default-route gateway for one interface from `/proc/net/route`."""
    for line in lines[1:]:
        columns = line.split()
        if len(columns) < 3:
            continue
        iface, destination, gateway = columns[:3]
        if iface != bridge_name or destination != "00000000":
            continue
        try:
            packed = struct.pack("<L", int(gateway, 16))
        except ValueError:
            continue
        return socket.inet_ntoa(packed)
    return None


def _find_bridge_gateway(config, machine, bridge_name):
    """Resolve the gateway address for a selected bridge with fallbacks."""
    commands = []
    if bridge_name == "br0":
        commands = [
            ("ip route show default dev %s" % (bridge_name), False),
            ("ip route show default", False),
            ("ip route | grep ' dev %s '" % (bridge_name), False),
        ]
    else:
        commands = [
            ("ip route | grep ' dev %s '" % (bridge_name), True),
            ("ip -4 addr show dev %s" % (bridge_name), False),
        ]

    for command, prefer_second in commands:
        output, error = machine.process(config, command, shell=True)[0]
        if error or not output:
            continue
        gateway = _extract_gateway_from_lines(output, prefer_second=prefer_second)
        if gateway:
            return gateway

    if bridge_name == "br0":
        output, error = machine.process(config, "cat /proc/net/route", shell=True)[0]
        if not error and output:
            gateway = _extract_gateway_from_proc_net_route(output, bridge_name)
            if gateway:
                return gateway
    return None


def _bridge_runtime_overrides():
    """Return optional host-runtime bridge overrides from the environment."""
    bridge_name = os.getenv("CONTINUUM_QEMU_BRIDGE_NAME")
    gateway = os.getenv("CONTINUUM_QEMU_BRIDGE_GATEWAY")
    return bridge_name, gateway


def start(config, machines):
    """Create QEMU config files for each machine

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start writing QEMU config files for cloud / edge")

    using_kata = False
    if config_access.orchestrator_name(config) == "kube_kata" and "kata" in str(
        config_access.orchestrator_value(config, "runtime")
    ):
        using_kata = True

    # Get the SSH public key
    with open("%s.pub" % (config["ssh_key"]), "r", encoding="utf-8") as f:
        ssh_key = f.read().rstrip()
        f.close()

    # --------------------------------------------------------------------------------------------
    # NOTE
    # If an error occurs in the following lines, please:
    # 1. Comment this part of the code between the two ---- lines out
    # 2. Set the "bridge_name" variable to the name of your bridge (e.g. br0, virbr0, etc.)
    # 3. Set the gateway variable to the IP of your gateway (e.g. 10.0.2.2, 192.168.122.1, etc)
    # --------------------------------------------------------------------------------------------
    bridge_name_override, gateway_override = _bridge_runtime_overrides()
    if bridge_name_override:
        bridge_name = bridge_name_override
        if find_bridge(config, machines[0], bridge_name) == 0:
            logging.error("ERROR: Could not find configured network bridge %s", bridge_name)
            sys.exit(1)
    else:
        bridge = find_bridge(config, machines[0], "br0")
        bridge_name = "br0"
        if bridge == 0:
            bridge = find_bridge(config, machines[0], "virbr0")
            bridge_name = "virbr0"
            if bridge == 0:
                logging.error("ERROR: Could not find a network bridge")
                sys.exit(1)

    gateway = gateway_override or _find_bridge_gateway(config, machines[0], bridge_name)
    if not gateway:
        logging.error("ERROR: Could not find gateway address")
        sys.exit(1)
    # --------------------------------------------------------------------------------------------

    cc = config["infrastructure"]["cloud_cores"]
    ec = config["infrastructure"]["edge_cores"]
    pc = config["infrastructure"]["endpoint_cores"]

    period = 100000
    pinnings = []

    for machine in machines:
        # Counter for pinning vcpu to physical cpu
        start_core = 0

        # Clouds
        for ip, name in zip(
            machine.cloud_controller_ips + machine.cloud_ips,
            machine.cloud_controller_names + machine.cloud_names,
        ):
            with open(_tmp_path(config, "domain_%s.xml" % (name)), "w", encoding="utf-8") as f:
                memory = _memory_gib_to_kib(config["infrastructure"]["cloud_memory"])

                if config["infrastructure"]["cpu_pin"]:
                    pinnings = [
                        '        <vcpupin vcpu="%i" cpuset="%i"/>' % (a, b)
                        for a, b in zip(range(cc), range(start_core, start_core + cc))
                    ]
                    start_core += cc

                f.write(
                    DOMAIN
                    % (
                        name,
                        memory,
                        "    <cpu mode='host-passthrough'/>" if using_kata else "",
                        cc,
                        period,
                        int(period * config["infrastructure"]["cloud_quota"]),
                        "\n".join(pinnings),
                        bridge_name,
                        config["infrastructure"]["base_path"],
                        name,
                        config["infrastructure"]["cloud_read_speed"],
                        config["infrastructure"]["cloud_write_speed"],
                        config["infrastructure"]["cloud_read_speed"],
                        config["infrastructure"]["cloud_write_speed"],
                        config["infrastructure"]["base_path"],
                        name,
                    )
                )
                f.close()

            with open(
                _tmp_path(config, "user_data_%s.yml" % (name)), "w", encoding="utf-8"
            ) as f:
                hostname = name.replace("_", "")
                guest_user = orchestration_schema.guest_login_name(name)
                f.write(_render_user_data(hostname, guest_user, ssh_key, ip, gateway))
                f.close()

        # Edges
        for ip, name in zip(machine.edge_ips, machine.edge_names):
            with open(_tmp_path(config, "domain_%s.xml" % (name)), "w", encoding="utf-8") as f:
                memory = _memory_gib_to_kib(config["infrastructure"]["edge_memory"])

                if config["infrastructure"]["cpu_pin"]:
                    pinnings = [
                        '        <vcpupin vcpu="%i" cpuset="%i"/>' % (a, b)
                        for a, b in zip(range(ec), range(start_core, start_core + ec))
                    ]
                    start_core += ec

                f.write(
                    DOMAIN
                    % (
                        name,
                        memory,
                        "    <cpu mode='host-passthrough'/>" if using_kata else "",
                        ec,
                        period,
                        int(period * config["infrastructure"]["edge_quota"]),
                        "\n".join(pinnings),
                        bridge_name,
                        config["infrastructure"]["base_path"],
                        name,
                        config["infrastructure"]["edge_read_speed"],
                        config["infrastructure"]["edge_write_speed"],
                        config["infrastructure"]["edge_read_speed"],
                        config["infrastructure"]["edge_write_speed"],
                        config["infrastructure"]["base_path"],
                        name,
                    )
                )
                f.close()

            with open(
                _tmp_path(config, "user_data_%s.yml" % (name)), "w", encoding="utf-8"
            ) as f:
                hostname = name.replace("_", "")
                guest_user = orchestration_schema.guest_login_name(name)
                f.write(_render_user_data(hostname, guest_user, ssh_key, ip, gateway))
                f.close()

        # Endpoints
        for ip, name in zip(machine.endpoint_ips, machine.endpoint_names):
            with open(_tmp_path(config, "domain_%s.xml" % (name)), "w", encoding="utf-8") as f:
                memory = _memory_gib_to_kib(config["infrastructure"]["endpoint_memory"])

                if config["infrastructure"]["cpu_pin"]:
                    pinnings = [
                        '        <vcpupin vcpu="%i" cpuset="%i"/>' % (a, b)
                        for a, b in zip(range(pc), range(start_core, start_core + pc))
                    ]
                    start_core += pc

                f.write(
                    DOMAIN
                    % (
                        name,
                        memory,
                        "    <cpu mode='host-passthrough'/>" if using_kata else "",
                        pc,
                        period,
                        int(period * config["infrastructure"]["endpoint_quota"]),
                        "\n".join(pinnings),
                        bridge_name,
                        config["infrastructure"]["base_path"],
                        name,
                        config["infrastructure"]["endpoint_read_speed"],
                        config["infrastructure"]["endpoint_write_speed"],
                        config["infrastructure"]["endpoint_read_speed"],
                        config["infrastructure"]["endpoint_write_speed"],
                        config["infrastructure"]["base_path"],
                        name,
                    )
                )
                f.close()

            with open(
                _tmp_path(config, "user_data_%s.yml" % (name)), "w", encoding="utf-8"
            ) as f:
                hostname = name.replace("_", "")
                guest_user = orchestration_schema.guest_login_name(name)
                f.write(_render_user_data(hostname, guest_user, ssh_key, ip, gateway))
                f.close()

        # Base image(s)
        for ip, name in zip(machine.base_ips, machine.base_names):
            with open(_tmp_path(config, "domain_%s.xml" % (name)), "w", encoding="utf-8") as f:
                f.write(
                    DOMAIN
                    % (
                        name,
                        1048576,
                        "    <cpu mode='host-passthrough'/>" if using_kata else "",
                        1,
                        0,
                        0,
                        "",
                        bridge_name,
                        config["infrastructure"]["base_path"],
                        name,
                        0,
                        0,
                        0,
                        0,
                        config["infrastructure"]["base_path"],
                        name,
                    )
                )
                f.close()

            with open(
                _tmp_path(config, "user_data_%s.yml" % (name)), "w", encoding="utf-8"
            ) as f:
                hostname = name.replace("_", "")
                guest_user = orchestration_schema.guest_login_name(name)
                f.write(_render_user_data(hostname, guest_user, ssh_key, ip, gateway))
                f.close()
