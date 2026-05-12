"""\
Generate Ansible inventory files
"""

import json
import logging
import os
import re
import sys

from infrastructure import orchestration_schema
from input.configuration import config_access


def _tmp_path(config, name):
    """Return the canonical generated-artifact path for one temp file."""
    root = config.get("tmp_dir", os.path.join(config.get("base", "."), ".tmp"))
    return os.path.join(root, name)


class AnsibleRunner:
    """Execute ansible-playbook commands with shared defaults."""

    def __init__(self, config, machines):
        """Initialize the runner and pin Ansible config resolution.

        Args:
            config (dict): Parsed Continuum configuration.
            machines (list[Machine]): Physical machine objects used for command execution.
        """
        self.config = config
        self.machines = machines
        self._executor = machines[0]
        self.repo_root = os.path.abspath(config["base"])
        self.base_path = config["infrastructure"]["base_path"]
        self.ansible_config = os.path.join(self.repo_root, "ansible.cfg")
        self.ansible_local_tmp = os.path.join(self.base_path, ".continuum", "ansible", "tmp")
        tmp_owner = re.sub(r"[^A-Za-z0-9_.-]", "_", str(config.get("username", "continuum")))
        # Ansible creates ``remote_tmp`` as the SSH user before privilege escalation.
        # Keep it under that user's home so resumed runs cannot get stuck on a stale
        # root-owned directory under /tmp from an earlier upload.
        self.ansible_remote_tmp = "~/.continuum-ansible-%s/tmp" % (tmp_owner)
        os.makedirs(self.ansible_local_tmp, exist_ok=True)
        preferred_playbook_bin = os.path.join(os.path.dirname(sys.executable), "ansible-playbook")
        if os.path.isfile(preferred_playbook_bin) and os.access(preferred_playbook_bin, os.X_OK):
            self.ansible_playbook_bin = preferred_playbook_bin
        else:
            self.ansible_playbook_bin = "ansible-playbook"
        self.default_env = {
            "ANSIBLE_CONFIG": self.ansible_config,
            "ANSIBLE_LOCAL_TEMP": self.ansible_local_tmp,
            "ANSIBLE_REMOTE_TMP": self.ansible_remote_tmp,
        }

        # Ensure Ansible resolves roles/config consistently regardless of CWD.
        os.environ.update(self.default_env)

    def inventory_path(self, inventory="vms"):
        """Return the inventory path for a logical inventory type.

        Args:
            inventory (str): Inventory selector, e.g. ``vms`` or ``machine``.

        Returns:
            str: Absolute path to the inventory file under ``.continuum``.
        """
        if inventory in ("machine", "machines", "physical"):
            return os.path.join(self.base_path, ".continuum/inventory")
        return os.path.join(self.base_path, ".continuum/inventory_vms")

    def run_playbook(
        self,
        playbook_path,
        inventory="vms",
        extra_vars=None,
        check=True,
        env=None,
    ):
        """Execute one playbook and optionally validate output.

        Args:
            playbook_path (str): Playbook path to execute. Relative paths are
                resolved from the repository root.
            inventory (str): Inventory selector for ``-i``.
            extra_vars (dict|str|None): Extra vars payload for ``--extra-vars``.
            check (bool): If True, run ``check_output`` on the result.
            env (dict|None): Extra environment variables for the subprocess.

        Returns:
            tuple[list[str], list[str]]: stdout and stderr lines.
        """
        command = self._build_command(playbook_path, inventory=inventory, extra_vars=extra_vars)
        result = self._executor.process(self.config, command, env=self._env(env))[0]
        if check:
            check_output(result)
        return result

    def run_playbooks(self, playbooks, inventory="vms", check=True, env=None):
        """Execute multiple playbooks in one process call.

        Args:
            playbooks (list[str]): Ordered list of playbooks to run.
            inventory (str): Inventory selector for all playbooks.
            check (bool): If True, validate each command output.
            env (dict|None): Extra environment variables for the subprocess.

        Returns:
            list[tuple[list[str], list[str]]]: Result per command.
        """
        commands = [self._build_command(playbook, inventory=inventory) for playbook in playbooks]
        results = self._executor.process(self.config, commands, env=self._env(env))
        if check:
            for command, (output, error) in zip(commands, results):
                logging.debug("Check output for command [%s]", " ".join(command))
                check_output((output, error))
        return results

    def run_command(self, command, check=True, shell=False, env=None):
        """Run a raw command through the shared machine executor.

        Args:
            command (str|list): Command passed to ``Machine.process``.
            check (bool): If True, validate output with ``check_output``.
            shell (bool): Whether to execute using ``/bin/bash``.
            env (dict|None): Extra environment variables for the subprocess.

        Returns:
            tuple[list[str], list[str]]: stdout and stderr lines.
        """
        result = self._executor.process(self.config, command, shell=shell, env=self._env(env))[0]
        if check:
            check_output(result)
        return result

    def _build_command(self, playbook_path, inventory="vms", extra_vars=None):
        """Build an ansible-playbook command list.

        Args:
            playbook_path (str): Playbook path to execute. Relative paths are
                resolved from the repository root.
            inventory (str): Inventory selector for ``-i``.
            extra_vars (dict|str|None): Optional ``--extra-vars`` value.

        Returns:
            list[str]: Command list suitable for ``Machine.process``.
        """
        command = [
            self.ansible_playbook_bin,
            "-i",
            self.inventory_path(inventory),
            self._resolve_playbook_path(playbook_path),
        ]
        if extra_vars is None:
            return command

        if isinstance(extra_vars, dict):
            extra_vars = json.dumps(extra_vars, separators=(",", ":"), sort_keys=True)

        command.extend(["--extra-vars", str(extra_vars)])
        return command

    def _resolve_playbook_path(self, playbook_path):
        """Resolve playbook paths, allowing concise repo-relative references.

        Args:
            playbook_path (str): Absolute or repo-relative playbook path.

        Returns:
            str: Absolute playbook path.
        """
        if os.path.isabs(playbook_path):
            return playbook_path
        return os.path.join(self.repo_root, playbook_path)

    def _env(self, env=None):
        merged = os.environ.copy()
        merged.update(self.default_env)
        if env:
            merged.update(env)
        return merged


def check_output(out):
    """Check if an Ansible Playbook succeeded or failed
    Shared by all files launching Ansible playbooks

    Args:
        output (list(str), list(str)): List of process stdout and stderr
    """
    output, error = out

    def _tail(lines, limit=80):
        if not lines:
            return []
        if len(lines) <= limit:
            return lines
        trimmed = ["... (%i lines omitted) ..." % (len(lines) - limit)]
        trimmed.extend(lines[-limit:])
        return trimmed

    # Print summary of executioo times
    summary = False
    lines = [""]
    for line in output:
        if summary:
            lines.append(line.rstrip())

        if "==========" in line:
            summary = True

    if lines != [""]:
        logging.debug("\n".join(lines))

    # Check if executino was succesful
    if error != [] and not all("WARNING" in line for line in error):
        failure_lines = ["Ansible command failed."]
        if output:
            failure_lines.append("stdout:")
            failure_lines.extend(_tail(output))
        if error:
            failure_lines.append("stderr:")
            failure_lines.extend(_tail(error))
        logging.error("\n".join(failure_lines))
        sys.exit(1)
    elif any("FAILED!" in out for out in output):
        failure_lines = ["Ansible playbook reported FAILED!"]
        failure_lines.extend(_tail(output))
        if error:
            failure_lines.append("stderr:")
            failure_lines.extend(_tail(error))
        logging.error("\n".join(failure_lines))
        sys.exit(1)


def create_inventory_machine(config, machines):
    """Create ansible inventory for creating VMs, so ssh to all physical machines is needed

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Generate Ansible inventory file for physical machines")
    infra_only = config_access.infra_only(config)
    with open(_tmp_path(config, "inventory"), "w", encoding="utf-8") as f:
        # Shared variables between all groups
        f.write("[all:vars]\n")
        f.write("ansible_python_interpreter=/usr/bin/python3\n")
        f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")
        f.write("base_path=%s\n" % (config["infrastructure"]["base_path"]))
        f.write("username=%s\n" % (config["username"]))

        # All hosts group
        f.write("\n[all_hosts]\n")

        for machine in machines:
            base = ""
            if infra_only:
                base = "base=%s" % (machine.base_names[0])

            if machine.is_local:
                f.write(
                    "localhost ansible_connection=local username=%s %s\n" % (machine.user, base)
                )
            else:
                f.write(
                    "%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s %s\n"
                    % (machine.name_sanitized, machine.ip, machine.user, machine.user, base)
                )

        # Specific cloud/edge/endpoint groups for installing RM software
        # For machines with cloud VMs
        if config["infrastructure"]["cloud_nodes"]:
            f.write("\n[clouds]\n")
            clouds = 0

            for machine in machines:
                if machine.cloud_controller + machine.clouds == 0:
                    continue

                base = machine.base_names[0]
                if not infra_only:
                    base = [name for name in machine.base_names if "_cloud_" in name][0]

                if machine.is_local:
                    f.write(
                        "localhost ansible_connection=local cloud_controller=%i \
cloud_start=%i cloud_end=%i base_cloud=%s\n"
                        % (machine.cloud_controller, clouds, clouds + machine.clouds - 1, base)
                    )
                else:
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s ansible_user=%s \
cloud_controller=%i cloud_start=%i cloud_end=%i base_cloud=%s\n"
                        % (
                            machine.name_sanitized,
                            machine.ip,
                            machine.user,
                            machine.cloud_controller,
                            clouds,
                            clouds + machine.clouds - 1,
                            base,
                        )
                    )

                clouds += machine.clouds

        # For machines with edge VMs
        if config["infrastructure"]["edge_nodes"]:
            f.write("\n[edges]\n")
            edges = 0

            for machine in machines:
                if machine.edges == 0:
                    continue

                base = machine.base_names[0]
                if not infra_only:
                    base = [name for name in machine.base_names if "_edge_" in name][0]

                if machine.is_local:
                    f.write(
                        "localhost ansible_connection=local edge_start=%i \
edge_end=%i base_edge=%s\n"
                        % (edges, edges + machine.edges - 1, base)
                    )
                else:
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s ansible_user=%s \
edge_start=%i edge_end=%i base_edge=%s\n"
                        % (
                            machine.name_sanitized,
                            machine.ip,
                            machine.user,
                            edges,
                            edges + machine.edges - 1,
                            base,
                        )
                    )

                edges += machine.edges

        # For machines with endpoint VMs
        if config["infrastructure"]["endpoint_nodes"]:
            f.write("\n[endpoints]\n")
            endpoints = 0
            for machine in machines:
                if machine.endpoints == 0:
                    continue

                base = machine.base_names[0]
                if not infra_only:
                    base = [name for name in machine.base_names if "_endpoint" in name][0]

                if machine.is_local:
                    f.write(
                        "localhost ansible_connection=local endpoint_start=%i \
endpoint_end=%i base_endpoint=%s\n"
                        % (endpoints, endpoints + machine.endpoints - 1, base)
                    )
                else:
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s ansible_user=%s \
endpoint_start=%i endpoint_end=%i base_endpoint=%s\n"
                        % (
                            machine.name_sanitized,
                            machine.ip,
                            machine.user,
                            endpoints,
                            endpoints + machine.endpoints - 1,
                            base,
                        )
                    )

                endpoints += machine.endpoints


def create_inventory_vm(config, machines):
    """Create inventory for installing and configuring software in VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Generate Ansible inventory file for VMs")
    infra_only = config_access.infra_only(config)
    kube_version = str(
        config_access.orchestrator_overrides(config, ["kube_version"]).get(
            "kube_version",
            "v1.27.0",
        )
    )

    repo_root = config.get("base", "")

    with open(_tmp_path(config, "inventory_vms"), "w", encoding="utf-8") as f:
        f.write("[all:vars]\n")
        f.write("ansible_python_interpreter=/usr/bin/python3\n")
        f.write("ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n")
        f.write("ansible_ssh_private_key_file=%s\n" % (config["ssh_key"]))
        f.write("continuum_repo_root=%s\n" % (repo_root))
        f.write(
            "continuum_resource_manager_type=%s\n" % (config_access.orchestrator_name(config))
        )

        if "registry" in config:
            f.write("registry_ip=%s\n" % (config["registry"]))

        f.write(
            "continuum_home=%s\n"
            % (os.path.join(config["infrastructure"]["base_path"], ".continuum"))
        )

        # Tier specific groups
        if (config["mode"] == "cloud" or config["mode"] == "edge") and (
            config_access.orchestrator_name(config) != "mist"
        ) and machines[0].cloud_controller_ips_internal:
            f.write("cloud_ip=%s\n" % (machines[0].cloud_controller_ips_internal[0]))
            f.write("cloud_ip_external=%s\n" % (machines[0].cloud_controller_ips[0]))

            # Cloud controller (is always on machine 0)
            f.write("\n[cloudcontroller]\n")
            f.write(
                "%s ansible_connection=ssh ansible_host=%s ansible_user=%s \
username=%s cloud_mode=%i kubeversion=%s kubeversion_major=%s\n"
                % (
                    machines[0].cloud_controller_names[0],
                    machines[0].cloud_controller_ips[0],
                    orchestration_schema.guest_login_name(machines[0].cloud_controller_names[0]),
                    orchestration_schema.guest_login_name(machines[0].cloud_controller_names[0]),
                    config["mode"] == "cloud",
                    kube_version[1:],
                    kube_version[:-2],
                )
            )

        # Cloud worker VM group
        if config["mode"] == "cloud":
            f.write("\n[clouds]\n")

            for machine in machines:
                for name, ip in zip(machine.cloud_names, machine.cloud_ips):
                    guest_user = orchestration_schema.guest_login_name(name)
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s\n"
                        % (name, ip, guest_user, guest_user)
                    )

        # Edge VM group
        if config["mode"] == "edge":
            f.write("\n[edges]\n")

            for machine in machines:
                for name, ip in zip(machine.edge_names, machine.edge_ips):
                    guest_user = orchestration_schema.guest_login_name(name)
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s\n"
                        % (name, ip, guest_user, guest_user)
                    )

        # Endpoint VM group
        if config["infrastructure"]["endpoint_nodes"]:
            f.write("\n[endpoints]\n")
            for machine in machines:
                for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
                    guest_user = orchestration_schema.guest_login_name(name)
                    f.write(
                        "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s\n"
                        % (name, ip, guest_user, guest_user)
                    )

        # Only include base VM logic if there are base VMs
        if not machines[0].base_ips:
            return

        # Make group with all base VMs for netperf installation
        f.write("\n[base]\n")
        for machine in machines:
            for name, ip in zip(machine.base_names, machine.base_ips):
                guest_user = orchestration_schema.guest_login_name(name)
                f.write(
                    "%s ansible_connection=ssh ansible_host=%s ansible_user=%s username=%s\n"
                    % (name, ip, guest_user, guest_user)
                )

        # Make specific groups for cloud/edge/endpoint base VM. Infra-only QEMU
        # can still use generic names like ``base0_user``; in that compatibility
        # path, infer base tier membership from the scheduled VM counts.
        if config["mode"] == "cloud" or config["mode"] == "edge":
            f.write("\n[base_cloud]\n")
            for machine in machines:
                for name, ip in zip(machine.base_names, machine.base_ips):
                    if infra_only:
                        include = machine.cloud_controller + machine.clouds > 0
                    else:
                        include = "cloud" in name
                    if include:
                        guest_user = orchestration_schema.guest_login_name(name)
                        f.write(
                            "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s kubeversion=%s kubeversionstrp=%s kubeversion_major=%s\n"
                            % (
                                name,
                                ip,
                                guest_user,
                                guest_user,
                                kube_version[1:],
                                kube_version.replace(".", ""),
                                kube_version[:-2],
                            )
                        )

        if config["mode"] == "edge":
            f.write("\n[base_edge]\n")
            for machine in machines:
                for name, ip in zip(machine.base_names, machine.base_ips):
                    if infra_only:
                        include = machine.edges > 0
                    else:
                        # The resource manager "kubeedge" has "edge" in the name,
                        # so cloud_kubeedge may be caught as "edge", filter this out.
                        # Only occurs for Qemu, because GCP doesn't really use base images.
                        # And: Mist computing uses kubeedge base images
                        occurences = len([i.start() for i in re.finditer("edge", name)])
                        is_qemu_kubeedge = int(
                            config["infrastructure"]["provider"] == "qemu"
                            and config_access.orchestrator_name(config) in ("kubeedge", "mist")
                        )
                        include = occurences == 1 + is_qemu_kubeedge

                    if include:
                        guest_user = orchestration_schema.guest_login_name(name)
                        f.write(
                            "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s\n"
                            % (name, ip, guest_user, guest_user)
                        )

        if not infra_only and config["infrastructure"]["endpoint_nodes"]:
            f.write("\n[base_endpoint]\n")
            for machine in machines:
                for name, ip in zip(machine.base_names, machine.base_ips):
                    if "endpoint" in name:
                        guest_user = orchestration_schema.guest_login_name(name)
                        f.write(
                            "%s ansible_connection=ssh ansible_host=%s \
ansible_user=%s username=%s\n"
                            % (name, ip, guest_user, guest_user)
                        )


def copy(config, machines):
    """Copy Ansible files to the local machine, base_path directory
    Machines other than the local one don't need Ansible files, Ansible itself will make it work.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start copying Ansible files to all nodes")

    dest = os.path.join(config["infrastructure"]["base_path"], ".continuum/")
    out = []

    # Copy inventory files
    if any("base" in base_name for base_name in machines[0].base_names):
        out.append(
            machines[0].copy_files(config, _tmp_path(config, "inventory"), dest)
        )

    out.append(
        machines[0].copy_files(config, _tmp_path(config, "inventory_vms"), dest)
    )

    # Phase C: playbooks and roles run directly from the repository through AnsibleRunner.
    # Keep copy() focused on generated runtime artifacts only (inventory and related files).

    for output, error in out:
        if error:
            logging.error("".join(error))
            sys.exit(1)
        elif output:
            logging.error("".join(output))
            sys.exit(1)


def _write_group_vars(path, variables):
    """Write one group_vars YAML-like file to disk.

    Args:
        path (str): Target file path.
        variables (dict): Variables to serialize.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as filep:
        json.dump(variables, filep, indent=2, sort_keys=True)
        filep.write("\n")


def generate_group_vars(config, machines, inventory_dir):
    """Generate group_vars files for future inventory-directory migration.

    Args:
        config (dict): Parsed Continuum configuration.
        machines (list[Machine]): Machine objects with resolved IP/name data.
        inventory_dir (str): Target inventory directory where ``group_vars`` is created.
    """
    continuum_home = os.path.join(config["infrastructure"]["base_path"], ".continuum")
    repo_root = config.get("base", "")
    kube_version = str(
        config_access.orchestrator_overrides(config, ["kube_version"]).get(
            "kube_version",
            "v1.27.0",
        )
    )
    kube_stripped = kube_version[1:] if kube_version.startswith("v") else kube_version
    kube_major = kube_version[:-2] if len(kube_version) > 2 else kube_version

    all_vars = {
        "ansible_python_interpreter": "/usr/bin/python3",
        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
        "ansible_ssh_private_key_file": config["ssh_key"],
        "continuum_base_path": config["infrastructure"]["base_path"],
        "continuum_home": continuum_home,
        "continuum_repo_root": repo_root,
        "continuum_resource_manager_type": config_access.orchestrator_name(config),
        "continuum_kubeversion": kube_stripped,
        "continuum_kubeversion_major": kube_major,
        "continuum_kubeversionstrp": kube_version.replace(".", ""),
        "continuum_mode": config["mode"],
        "continuum_username": config["username"],
    }

    if "registry" in config:
        all_vars["continuum_registry_ip"] = config["registry"]

    if machines and machines[0].cloud_controller_ips_internal:
        all_vars["continuum_cloud_ip"] = machines[0].cloud_controller_ips_internal[0]
    if machines and machines[0].cloud_controller_ips:
        all_vars["continuum_cloud_ip_external"] = machines[0].cloud_controller_ips[0]

    group_vars_dir = os.path.join(inventory_dir, "group_vars")
    logging.info("Generate group_vars files in %s", group_vars_dir)
    _write_group_vars(os.path.join(group_vars_dir, "all.yml"), all_vars)

    group_defaults = {
        "cloudcontroller": {
            "continuum_role_group": "cloudcontroller",
            "continuum_cloud_mode": int(config["mode"] == "cloud"),
        },
        "clouds": {"continuum_role_group": "clouds"},
        "edges": {"continuum_role_group": "edges"},
        "endpoints": {"continuum_role_group": "endpoints"},
        "base": {"continuum_role_group": "base"},
        "base_cloud": {"continuum_role_group": "base_cloud"},
        "base_edge": {"continuum_role_group": "base_edge"},
        "base_endpoint": {"continuum_role_group": "base_endpoint"},
    }

    for group, variables in group_defaults.items():
        _write_group_vars(os.path.join(group_vars_dir, "%s.yml" % (group)), variables)
