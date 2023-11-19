"""\
Generate Ansible inventory files
"""

import logging
import os
import sys

import settings


def check_output(out):
    """Check if an Ansible Playbook succeeded or failed
    Shared by all files launching Ansible playbooks

    Args:
        out (list(str), list(str)): List of process stdout and stderr
    """
    output, error = out

    # Print summary of execution times
    summary = False
    lines = [""]
    for line in output:
        if summary:
            lines.append(line.rstrip())

        if "==========" in line:
            summary = True

    if lines != [""]:
        logging.debug("\n".join(lines))

    # Check if execution was successful
    if error:
        logging.error("".join(error))
        sys.exit()
    elif any("FAILED!" in out for out in output):
        logging.error("".join(output))
        sys.exit()


def create_inventory_host(layer_name):
    """Create an Ansible inventory file with all hosts. This will be used by providers that operate
    on local infrastructure (like QEMU), not on remote infrastructure (like GCP, AWS). We assume
    that the IP and name of every Host connected to Continuum is already known.

    Besides the general all_host group, also create groups for specific layers, containing only
    those hosts that operate machines that live in that layer.

    Args:
        layer_name (str): Name of the layer to create a host group for (e.g., "cloud")

    TODO (high priority)
     - we removed combined host groups (like all_hosts). Instead, multiple host groups should be
       passed to the Ansible playbook file, like "host: cloud:edge:endpoint.
     - make sure the all_host group, and base groups in the inventory_vm aren't used anymore
     - see deploy.py for qemu for a to do on how to pass host groups to YML files

    TODO (high priority)
     - remove the cloud_controller VM completely
     - just make cloudX VMs and assign in metadata one or multiple machines as
       the controller. Don't create a machine that is literally named "controller"
     - that makes us more flexible, we can even create multiple controllers
     - I DON'T WANT TO SEE THE WORD CONTROLLER IN /INFRASTRUCTURE*
     - I DON'T WANT TO SEE DEDICATED CLOUD/EDGE/ENDPOINT CODE - LAYER NAMES ARE JUST TAGS
    """
    logging.info("Generate Ansible inventory file for hosts")
    dest = os.path.join(settings.config["base_path"], ".continuum/inventory_host")

    exists = False
    if os.path.exists(dest):
        exists = True

    with open(dest, "a", encoding="utf-8") as f:
        # Write shared variables between all groups once, if inventory did not yet exist
        if not exists:
            f.write("[all:vars]\n")
            f.write("ansible_python_interpreter=/usr/bin/python3\n")
            f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")
            f.write(f"base_path={settings.config['base_path']}\n")
            f.write(f"username={settings.config['username']}\n")

        # Write host groups per layer - with extra input to start (base) machines per layer
        for layer in settings.get_layers(layer_name=layer_name):
            f.write(f"\n[{layer['name']}]\n")
            machines = 0

            for host, base_machine in zip(
                settings.config["hosts"], settings.get_machines(layer_name=layer["name"], base=True)
            ):
                if not base_machine:
                    logging.error(f"ERROR: Can't find base machine in layer {layer['name']}")
                    sys.exit()

                base_machine = base_machine[0]
                machines_in_layer = len(settings.get_machines(layer_name=layer["name"]))

                # TODO (low priority)
                #  - this start/end/base_name is QEMU specific (perhaps)
                #  - in the future we might want to move this to the qemu code, similar to how
                #    we moved software parameters to the software packages via
                #    ansible-playbook --extra-vars ...
                custom_vars = (
                    f"layer={layer['name']} start={machines} "
                    f"end={machines + machines_in_layer - 1} base_name={base_machine.name}\n"
                )

                machines += machines_in_layer

                if host.is_local:
                    f.write(f"localhost ansible_connection=local " + custom_vars)
                else:
                    f.write(
                        f"{host.name_sanitized} ansible_connection=ssh ansible_host={host.ip} "
                        f"ansible_user={host.name} " + custom_vars
                    )


def create_inventory_machine(layer_name):
    """Create inventory for installing and configuring software in VMs

    Args:
        layer_name (str): Name of the layer to create a host group for (e.g., "cloud")

    TODO (high priority)
     - see the first to do from the previous function
     - don't create compound groups like 'base' which are all base groups
     - providers can dynamically add their own arguments using the command
        - each provider uses their own layer anyway, and not any other layers
        - we will only need the full inventory_vms file in /software anyway
        - what I mean: providers call this function for their layer(s), that's fine

    TODO (high priority)
     - move variables that were previously in the inventory file but are software package
       specific, to the software packages. They can pass something like this:
       ansible-playbook --extra-vars "host=cloud:edge:endpoint" -i inventory file.yml
     - this again disentangles software nicely from infrastructure.
            if (config["mode"] == "cloud" or config["mode"] == "edge") and (
                "benchmark" in config and config["benchmark"]["resource_manager"] != "mist"
            ):
                f.write("cloud_ip=%s\n" % (machines[0].cloud_controller_ips_internal[0]))
                f.write("cloud_ip_external=%s\n" % (machines[0].cloud_controller_ips[0]))
     .
     For details on what to move (li
     https://github.com/atlarge-research/continuum/blob/main/infrastructure/ansible.py#L218
    """
    logging.info("Generate Ansible inventory file for machine")
    dest = os.path.join(settings.config["base_path"], ".continuum/inventory_machine")

    exists = False
    if os.path.exists(dest):
        exists = True

    with open(dest, "a", encoding="utf-8") as f:
        # Write shared variables between all groups once, if inventory did not yet exist
        if not exists:
            f.write("[all:vars]\n")
            f.write("ansible_python_interpreter=/usr/bin/python3\n")
            f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")

            provider = settings.get_providers(layer_name=layer_name)
            ssh_key = settings.config["provider_init"][provider["name"]]["ssh_key"]
            f.write(f"ansible_ssh_private_key_file={ssh_key}\n")

            f.write("registry_ip=%s\n" % (settings.config["registry"]))

            home = os.path.join(settings.config["base_path"], ".continuum")
            f.write(f"continuum_home={home}\n")

        # Write host groups per layer - with extra input to start (base) machines per layer
        for layer in settings.get_layers(layer_name=layer_name):
            f.write(f"\n[{layer['name']}]\n")

            for host, machines in zip(
                settings.config["hosts"], settings.get_machines(layer_name=layer["name"])
            ):
                for machine in machines:
                    if machine.base:
                        continue

                    f.write(
                        f"{machine.name} ansible_connection=ssh ansible_host={machine.ip} "
                        f"ansible_user={machine.name} username={machine.name}"
                    )

        # Now do the same, but write host groups for base images
        for layer in settings.get_layers(layer_name=layer_name):
            f.write(f"\n[base_{layer['name']}]\n")

            for host, machines in zip(
                settings.config["hosts"], settings.get_machines(layer_name=layer["name"])
            ):
                for machine in machines:
                    if not machine.base:
                        continue

                    f.write(
                        f"{machine.name} ansible_connection=ssh ansible_host={machine.ip} "
                        f"ansible_user={machine.name} username={machine.name}"
                    )


# TODO (high priority)
#  - See original copy() function:
#    https://github.com/atlarge-research/continuum/blob/main/infrastructure/ansible.py#L343
#  - For the latter half of the function: Move the copying of software and benchmark files
#    to those modules instead of here in infrastructure.
#  - We need to call their modules anyway to install stuff in base images, so why can't we add
#    an extra call to copy their files over to "base_path/.continuum".
#    - Create a new mandatory interface function for these modules
#    - Call those functions in infrastructure.py -> let the infra modules do as little as possible
