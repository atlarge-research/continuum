"""\
Create and use QEMU Vms
"""

import hashlib
import json
import logging
import os
import sys
import time

import yaml

from input.configuration import config_access
from infrastructure import ansible, image_registry, infrastructure
from infrastructure import machine as m
from infrastructure import network, orchestration_schema
from resource_manager import plans as rm_plans

from . import generate


def _machine_playbook_env():
    """Return environment overrides for local host-side QEMU playbooks.

    These playbooks operate on the physical QEMU host and should not inherit the
    global Ansible ``become = True`` default. Host prerequisites are installed
    explicitly during smoke-host setup instead.
    """

    return {"ANSIBLE_BECOME": "False"}


def _delete_local_path(path):
    """Best-effort local cache cleanup for unreadable QEMU artifacts."""
    if os.path.exists(path):
        os.remove(path)


def _base_image_metadata_path(config, raw_base_name):
    """Return the cache metadata path for one raw base image name."""
    return os.path.join(
        config["infrastructure"]["base_path"],
        ".continuum/images/%s.meta.json" % (raw_base_name),
    )


def _base_install_playbooks_for_base_names(config, machines, normalized_base_names):
    """Return required base-image install playbooks for the selected base names.

    QEMU infra-only resume still uses generic base names such as ``base0_user``.
    Those names do not encode a tier, so planner-level tier detection skips the
    resource-manager base install playbook. Infer cloud/edge intent from the
    machine schedule in that compatibility path so retained infra-only runs can
    still bake orchestrator prerequisites into shared base images.
    """
    try:
        playbooks = rm_plans.build_base_image_playbooks(config, normalized_base_names)
    except (KeyError, TypeError, ValueError):
        playbooks = []

    try:
        infra_only = config_access.infra_only(config)
    except (KeyError, TypeError, ValueError):
        infra_only = False

    try:
        prepare_for_resume = (
            infra_only and config_access.prepare_for_resume_enabled(config)
        )
    except (KeyError, TypeError, ValueError):
        prepare_for_resume = False

    rm_module = config.get("module", {}).get("resource_manager")
    if not prepare_for_resume or not rm_module:
        return playbooks

    normalized_set = set(normalized_base_names)
    for machine in machines:
        for raw_base_name in getattr(machine, "base_names", []):
            normalized_name = orchestration_schema.normalized_base_name(raw_base_name)
            if normalized_name not in normalized_set:
                continue
            if orchestration_schema.tier_from_base_name(normalized_name) is not None:
                continue

            for tier, count in (
                ("cloud", getattr(machine, "cloud_controller", 0) + getattr(machine, "clouds", 0)),
                ("edge", getattr(machine, "edges", 0)),
            ):
                if count <= 0:
                    continue
                if not hasattr(rm_module, "base_install_playbook"):
                    logging.error(
                        "Resource manager %s does not define base_install_playbook()",
                        config_access.orchestrator_name(config),
                    )
                    sys.exit(1)
                playbook = rm_module.base_install_playbook(config, tier)
                if playbook and playbook not in playbooks:
                    playbooks.append(playbook)

    return playbooks


def _repo_path(config, path):
    """Return an absolute path for one repository-relative path."""
    if os.path.isabs(path):
        return path
    return os.path.join(config.get("base", "."), path)


def _role_path(config, role_name):
    """Resolve an Ansible role name using this repo's configured role roots."""
    if os.path.isabs(role_name):
        return role_name if os.path.isdir(role_name) else None

    role_roots = (
        "roles/resource_manager",
        "roles/infrastructure",
        "roles/application",
        "roles",
    )
    for root in role_roots:
        candidate = _repo_path(config, os.path.join(root, role_name))
        if os.path.isdir(candidate):
            return candidate
    return None


def _playbook_role_names(config, playbook):
    """Return role names referenced directly by an Ansible playbook."""
    playbook_path = _repo_path(config, playbook)
    try:
        with open(playbook_path, "r", encoding="utf-8") as filep:
            data = yaml.safe_load(filep)
    except (OSError, yaml.YAMLError):
        return []

    if not isinstance(data, list):
        return []

    role_names = []
    for play in data:
        if not isinstance(play, dict):
            continue
        roles = play.get("roles", [])
        if not isinstance(roles, list):
            continue
        for role in roles:
            role_name = role if isinstance(role, str) else None
            if isinstance(role, dict):
                role_name = role.get("role")
            if isinstance(role_name, str) and role_name:
                role_names.append(role_name)
    return role_names


def _file_digest(path):
    """Return a stable digest for one file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as filep:
        while True:
            chunk = filep.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _files_under(path):
    """Return all regular files under one file or directory path."""
    if os.path.isfile(path):
        return [path]
    files = []
    for root, _dirs, filenames in os.walk(path):
        for filename in filenames:
            files.append(os.path.join(root, filename))
    return files


def _base_install_fingerprints(config, playbooks):
    """Return content fingerprints for base-install playbooks and direct roles."""
    paths = set()
    for playbook in playbooks:
        playbook_path = _repo_path(config, playbook)
        if os.path.exists(playbook_path):
            paths.add(playbook_path)

        for role_name in _playbook_role_names(config, playbook):
            role_path = _role_path(config, role_name)
            if not role_path:
                continue
            paths.update(_files_under(role_path))

    base = os.path.abspath(config.get("base", "."))
    fingerprints = []
    for path in sorted(paths):
        relpath = os.path.relpath(path, base)
        fingerprints.append({"path": relpath, "sha256": _file_digest(path)})
    return fingerprints


def _expected_base_image_metadata(config, machines, raw_base_name):
    """Return the expected ready-marker payload for one base image."""
    normalized_name = orchestration_schema.normalized_base_name(raw_base_name)
    playbooks = _base_install_playbooks_for_base_names(
        config,
        machines,
        [normalized_name],
    )
    return {
        "schema_version": 1,
        "status": "ready",
        "guest_user": orchestration_schema.guest_login_name(raw_base_name),
        "base_install_playbooks": playbooks,
        "base_install_fingerprints": _base_install_fingerprints(config, playbooks),
    }


def _base_image_cache_invalid_reason(config, machines, raw_base_name):
    """Return a human-readable cache validation reason, or None when valid."""
    metadata_path = _base_image_metadata_path(config, raw_base_name)
    if not os.path.exists(metadata_path):
        return "metadata missing"

    try:
        with open(metadata_path, "r", encoding="utf-8") as filep:
            payload = json.load(filep)
    except (OSError, json.JSONDecodeError):
        return "metadata unreadable"

    if not isinstance(payload, dict):
        return "metadata invalid"

    expected = _expected_base_image_metadata(config, machines, raw_base_name)
    for key, value in expected.items():
        if payload.get(key) != value:
            return "metadata %s mismatch" % (key,)
    return None


def _write_base_image_metadata(config, machines, raw_base_name):
    """Persist the ready-marker metadata for one successfully prepared base image."""
    metadata_path = _base_image_metadata_path(config, raw_base_name)
    with open(metadata_path, "w", encoding="utf-8") as filep:
        json.dump(
            _expected_base_image_metadata(config, machines, raw_base_name),
            filep,
            sort_keys=True,
        )


def _base_profile_token(config):
    """Return a deterministic feature-profile token for base image identity.

    The token encodes software/features baked into base images so cache reuse
    is safe across runs with different feature toggles.

    Args:
        config (dict): Parsed Continuum configuration.

    Returns:
        str: Stable token that identifies base-image feature selection.
    """
    wireless_preset = config["infrastructure"].get("wireless_network_preset", "")
    enable_mahimahi = isinstance(wireless_preset, str) and wireless_preset.endswith("_mahimahi")

    # Netperf is currently always installed in the QEMU base flow.
    return "np1_mm%s" % (int(enable_mahimahi))


def delete_vms(config, machines):
    """Delete the VMs created by Continuum: Always at the start of a run the delete old VMs,
    and possilby at the end if the run if configured by the user

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start deleting VMs")

    commands = []
    sshs = []
    for machine in machines:
        if machine.is_local:
            command = (
                r'virsh list --all | grep -o -E "(\w*_%s)" | \
xargs -I %% sh -c "virsh destroy %%"'
                % (config["username"])
            )
        else:
            comm = (
                r"virsh list --all | grep -o -E \"(\w*_%s)\" | \
xargs -I %% sh -c \"virsh destroy %%\""
                % (config["username"])
            )
            command = "ssh %s 'bash -l -c \"%s\"'" % (machine.name, comm)

        commands.append(command)
        sshs.append(None)

    results = machines[0].process(config, commands, shell=True, ssh=sshs, ssh_key=False)

    # Wait for process to finish. Outcome of destroy command does not matter
    for command, (_, _) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # TODO: Move base_ip and related logic to here - that's not generic
    #       (that is, GCP doesnt use it)
    return []


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["infrastructure"]["provider"] != "qemu":
        parser.error("ERROR: Infrastructure provider should be qemu")


def set_ip_names(config, machines, nodes_per_machine):
    """Set amount of cloud / edge / endpoints nodes per machine, and their IPs / hostnames.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node
    """
    logging.info("Set the IPs and names of all VMs for each physical machine")
    middle_ip = config["infrastructure"]["middleIP"]
    postfix_ip = config["postfixIP_lower"]

    middle_ip_base = config["infrastructure"]["middleIP_base"]
    postfix_ip_base = config["postfixIP_lower"]

    cloud_index = 0
    edge_index = 0
    endpoint_index = 0
    infra_only = config_access.infra_only(config)

    for i, (machine, nodes) in enumerate(zip(machines, nodes_per_machine)):
        # Set IP / name for controller (on first machine only)
        if (
            machine == machines[0]
            and not config["mode"] == "endpoint"
            and config_access.orchestrator_name(config) != "mist"
            and nodes["cloud"] > 0
        ):
            machine.cloud_controller = int(nodes["cloud"] > 0)
            machine.clouds = nodes["cloud"] - int(nodes["cloud"] > 0)

            ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
            machine.cloud_controller_ips.append(ip)
            machine.cloud_controller_ips_internal.append(ip)

            name = "cloud_controller_%s" % (config["username"])
            machine.cloud_controller_names.append(name)
            middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)
        else:
            machine.cloud_controller = 0
            machine.clouds = nodes["cloud"]

        machine.edges = nodes["edge"]
        machine.endpoints = nodes["endpoint"]

        # Set IP / name for cloud
        for _ in range(machine.clouds):
            ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
            machine.cloud_ips.append(ip)
            machine.cloud_ips_internal.append(ip)
            middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)

            name = "cloud%i_%s" % (cloud_index, config["username"])
            machine.cloud_names.append(name)
            cloud_index += 1

        # Set IP / name for edge
        for _ in range(machine.edges):
            ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
            machine.edge_ips.append(ip)
            machine.edge_ips_internal.append(ip)
            middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)

            name = "edge%i_%s" % (edge_index, config["username"])
            machine.edge_names.append(name)
            edge_index += 1

        # Set IP / name for endpoint
        for _ in range(machine.endpoints):
            ip = "%s.%s.%s" % (config["infrastructure"]["prefixIP"], middle_ip, postfix_ip)
            machine.endpoint_ips.append(ip)
            machine.endpoint_ips_internal.append(ip)
            middle_ip, postfix_ip = network.next_configured_ip(config, middle_ip, postfix_ip)

            name = "endpoint%i_%s" % (endpoint_index, config["username"])
            machine.endpoint_names.append(name)
            endpoint_index += 1

        # Set IP / name for base image(s)
        if infra_only:
            ip = "%s.%s.%s" % (
                config["infrastructure"]["prefixIP"],
                middle_ip_base,
                postfix_ip_base,
            )
            machine.base_ips.append(ip)

            name = "base%i_%s" % (i, config["username"])
            machine.base_names.append(name)
            middle_ip_base, postfix_ip_base = network.next_configured_ip(
                config, middle_ip_base, postfix_ip_base
            )
        else:
            # Base images for resource manager images
            # Use KubeEdge setup code for mist computing.
            rm = config_access.orchestrator_name(config) or "none"
            if rm == "mist":
                rm = "kubeedge"
            profile_token = _base_profile_token(config)

            if machine.cloud_controller + machine.clouds > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_cloud_%s_%s_%i_%s" % (rm, profile_token, i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = network.next_configured_ip(
                    config, middle_ip_base, postfix_ip_base
                )

            if machine.edges > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_edge_%s_%s_%i_%s" % (rm, profile_token, i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = network.next_configured_ip(
                    config, middle_ip_base, postfix_ip_base
                )

            if machine.endpoints > 0:
                ip = "%s.%s.%s" % (
                    config["infrastructure"]["prefixIP"],
                    middle_ip_base,
                    postfix_ip_base,
                )
                machine.base_ips.append(ip)

                name = "base_endpoint_%s_%i_%s" % (profile_token, i, config["username"])
                machine.base_names.append(name)
                middle_ip_base, postfix_ip_base = network.next_configured_ip(
                    config, middle_ip_base, postfix_ip_base
                )


def copy(config, machines):
    """Copy Infrastructure files to all machines

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start copying infrastructure files to all nodes")

    # Now copy the files over
    for machine in machines:
        if machine.is_local:
            dest = os.path.join(config["infrastructure"]["base_path"], ".continuum/")
        else:
            dest = machine.name + ":%s/.continuum/" % (config["infrastructure"]["base_path"])

        out = []

        # Copy VM creation files
        for name in (
            machine.cloud_controller_names
            + machine.cloud_names
            + machine.edge_names
            + machine.endpoint_names
            + machine.base_names
        ):
            out.append(
                machine.copy_files(
                    config,
                    os.path.join(
                        config.get("tmp_dir", os.path.join(config["base"], ".tmp")),
                        "domain_" + name + ".xml",
                    ),
                    dest,
                )
            )
            out.append(
                machine.copy_files(
                    config,
                    os.path.join(
                        config.get("tmp_dir", os.path.join(config["base"], ".tmp")),
                        "user_data_" + name + ".yml",
                    ),
                    dest,
                )
            )

        for output, error in out:
            if error:
                logging.error("".join(error))
                sys.exit(1)
            elif output:
                logging.error("".join(output))
                sys.exit(1)


def os_image(config, machines, runner=None):
    """Check if the os image with Ubuntu 20.04 already exists,
    and if not create the image (on all machines)

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        runner (AnsibleRunner, optional): Shared runner instance for playbook execution.
    """
    logging.info("Check if a new OS image needs to be created")
    need_image = False
    for machine in machines:
        image_path = os.path.join(
            config["infrastructure"]["base_path"], ".continuum/images/ubuntu2004.qcow2"
        )
        command = [
            "find",
            image_path,
        ]
        output, error = machine.process(config, command, ssh=machine.name)[0]

        if error or not output:
            need_image = True
            break
        if machine.is_local and not os.access(image_path, os.R_OK):
            logging.info("Cached OS image is unreadable; removing and rebuilding: %s", image_path)
            _delete_local_path(image_path)
            resize_marker = os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/images/.ubuntu2004.qcow2_resized",
            )
            _delete_local_path(resize_marker)
            need_image = True
            break

    if runner is None:
        runner = ansible.AnsibleRunner(config, machines)

    if need_image:
        logging.info("Need to install OS image")
        runner.run_playbook(
            "playbooks/infrastructure/qemu_prepare_os.yml",
            inventory="machine",
            env=_machine_playbook_env(),
        )
    else:
        logging.info("OS image is already there")


def base_image(config, machines, runner=None):
    """Check if a base image already exists, and if not create the image

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        runner (AnsibleRunner, optional): Shared runner instance for playbook execution.
    """
    if runner is None:
        runner = ansible.AnsibleRunner(config, machines)

    logging.info("Check if new base image(s) needs to be created")

    # Create a flat list of base_names, without any special characters
    base_names = []
    for machine in machines:
        for base_name in machine.base_names:
            name = orchestration_schema.normalized_base_name(base_name)
            base_names.append(name)

    # Create a mask for the previous list
    need_images = [False for _ in range(len(base_names))]

    # Check if all images are available on each machine, otherwise set need_images
    for machine in machines:
        for base_name in machine.base_names:
            raw_base_name = base_name
            image_path = os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/images/%s.qcow2" % (base_name),
            )
            command = [
                "find",
                image_path,
            ]
            output, error = machine.process(config, command, ssh=machine.name)[0]

            if error or not output:
                base_name = orchestration_schema.normalized_base_name(base_name)
                need_images[base_names.index(base_name)] = True
            elif machine.is_local and not os.access(image_path, os.R_OK):
                logging.info("Cached base image is unreadable; removing and rebuilding: %s", image_path)
                _delete_local_path(image_path)
                user_data_path = os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/images/user_data_%s.img" % (raw_base_name),
                )
                _delete_local_path(user_data_path)
                _delete_local_path(_base_image_metadata_path(config, raw_base_name))
                base_name = orchestration_schema.normalized_base_name(base_name)
                need_images[base_names.index(base_name)] = True
            elif machine.is_local:
                invalid_reason = _base_image_cache_invalid_reason(config, machines, raw_base_name)
                if invalid_reason:
                    logging.info(
                        "Cached base image is stale (%s); removing and rebuilding: %s",
                        invalid_reason,
                        image_path,
                    )
                    _delete_local_path(image_path)
                    user_data_path = os.path.join(
                        config["infrastructure"]["base_path"],
                        ".continuum/images/user_data_%s.img" % (raw_base_name),
                    )
                    _delete_local_path(user_data_path)
                    _delete_local_path(_base_image_metadata_path(config, raw_base_name))
                    base_name = orchestration_schema.normalized_base_name(base_name)
                    need_images[base_names.index(base_name)] = True

    # Stop if no base images are required
    base_names = [name for name, need in zip(base_names, need_images) if need]
    if base_names == []:
        logging.info("Base image(s) are all already present")
        return

    logging.info("Create base image set via qemu_prepare_base.yml")
    runner.run_playbook(
        "playbooks/infrastructure/qemu_prepare_base.yml",
        inventory="machine",
        extra_vars={
            "continuum_base_images_by_host": orchestration_schema.base_images_by_host(
                machines, base_names
            )
        },
        env=_machine_playbook_env(),
    )

    # Create commands to launch the base VMs concurrently
    commands = []
    base_ips = []
    for machine in machines:
        for base_name, base_ip in zip(machine.base_names, machine.base_ips):
            base_name_r = orchestration_schema.normalized_base_name(base_name)
            if base_name_r in base_names:
                path = os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/domain_%s.xml" % (base_name)
                )
                if machine.is_local:
                    command = "virsh --connect qemu:///system create %s" % (path)
                else:
                    command = "ssh %s 'bash -l -c \"virsh --connect qemu:///system create %s\"'" % (
                        machine.name,
                        path,
                    )

                commands.append(command)
                base_ips.append(base_ip)

    # Now launch the VMs
    results = machines[0].process(config, commands, shell=True)

    # Check if VM launching went as expected
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and "Connection to " not in error[0]:
            logging.error("ERROR: %s", "".join(error))
            sys.exit(1)
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s", "".join(output))
            sys.exit(1)

    # Fix SSH keys for each base image
    infrastructure.add_ssh(config, machines, base=base_ips)

    # Install software concurrently (infra_only won't get anything installed)
    playbooks = _base_install_playbooks_for_base_names(config, machines, base_names)

    if playbooks:
        logging.info("Install software in the base VMs")
        runner.run_playbooks(playbooks, inventory="vms")

    # Install common infrastructure software (netperf + optional Mahimahi)
    wireless_preset = config["infrastructure"].get("wireless_network_preset", "")
    runner.run_playbook(
        "playbooks/infrastructure/common_base_install.yml",
        inventory="vms",
        extra_vars={
            "continuum_enable_mahimahi": (
                isinstance(wireless_preset, str) and wireless_preset.endswith("_mahimahi")
            )
        },
    )

    # Install docker containers if required
    if image_registry.has_prefetch_requirements(config):
        # Kubernetes/KubeEdge don't need docker images on the cloud/edge nodes
        # These RM will automatically pull images, so we can skip this here.
        # Only pull endpoint images instead
        docker_base_names = base_names
        if config_access.orchestrator_name(config) in (
            "kubernetes",
            "kubeedge",
            "kubecontrol",
            "kube_kata",
        ):
            docker_base_names = [
                base_name for base_name in docker_base_names if "endpoint" in base_name
            ]

        image_registry.docker_pull(config, machines, docker_base_names)

    # Get host timezone
    command = ["ls", "-alh", "/etc/localtime"]
    output, error = machines[0].process(config, command)[0]

    if not output or "/etc/localtime" not in output[0]:
        logging.error("Could not get host timezone: %s", "".join(output))
        sys.exit(1)
    elif error:
        logging.error("Could not get host timezone: %s", "".join(error))
        sys.exit(1)

    timezone = output[0].split("-> ")[1].strip()

    # Fix timezone on every base vm
    command = ["sudo", "ln", "-sf", timezone, "/etc/localtime"]
    sshs = []
    for machine in machines:
        for ip, name in zip(machine.base_ips, machine.base_names):
            name_r = orchestration_schema.normalized_base_name(name)
            if name_r in base_names:
                ssh = "%s@%s" % (orchestration_schema.guest_login_name(name), ip)
                sshs.append(ssh)

    results = machines[0].process(config, command, ssh=sshs)

    for output, error in results:
        if output:
            logging.error("Could not set VM timezone: %s", "".join(output))
            sys.exit(1)
        elif error:
            logging.error("Could not set VM timezone: %s", "".join(error))
            sys.exit(1)

    # Clean the VM
    command = ["sudo", "cloud-init", "clean"]
    sshs = []
    for machine in machines:
        for base_name, ip in zip(machine.base_names, machine.base_ips):
            base_name_r = orchestration_schema.normalized_base_name(base_name)
            if base_name_r in base_names:
                sshs.append("%s@%s" % (orchestration_schema.guest_login_name(base_name), ip))

    results = machines[0].process(config, command, ssh=sshs)

    for ssh, (output, error) in zip(sshs, results):
        logging.info("Check output for command [sudo cloud-init clean] on [%s]", ssh)
        ansible.check_output((output, error))

    # Shutdown VMs
    commands = []
    for machine in machines:
        for base_name in machine.base_names:
            base_name_r = orchestration_schema.normalized_base_name(base_name)
            if base_name_r in base_names:
                if machine.is_local:
                    command = "virsh --connect qemu:///system shutdown %s" % (base_name)
                else:
                    command = (
                        "ssh %s 'bash -l -c \"virsh --connect qemu:///system shutdown %s\"'"
                        % (machine.name, base_name)
                    )

                commands.append(command)

    results = machines[0].process(config, commands, shell=True)

    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and not (
            command.split(" ")[0] == "ssh" and any("Connection to " in e for e in error)
        ):
            logging.error("".join(error))
            sys.exit(1)
        elif "Domain " not in output[0] or " is being shutdown" not in output[0]:
            logging.error("".join(output))
            sys.exit(1)

    for machine in machines:
        if not machine.is_local:
            continue
        for raw_base_name in machine.base_names:
            normalized_base_name = orchestration_schema.normalized_base_name(raw_base_name)
            if normalized_base_name in base_names:
                _write_base_image_metadata(config, machines, raw_base_name)

    # Wait for the shutdown to be completed
    time.sleep(5)


def launch_vms(config, machines, repeat=None):
    """Launch VMs concurrently
    Moved into a function so it can be re-executed when a VM didn't start for some reason

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        repeat (list, optional): Repeat specific execution. If empty, start all VMs. Defaults to [].

    Returns:
        list: Commands to execute again
    """
    # Launch the VMs concurrently
    logging.info("Start VMs")

    # Sometimes previous QEMU commands aren't finished yet,
    # so it's safer to wait a bit to prevent lock errors
    time.sleep(5)

    commands = []
    if not repeat:
        for machine in machines:
            for name in (
                machine.cloud_controller_names
                + machine.cloud_names
                + machine.edge_names
                + machine.endpoint_names
            ):
                path = os.path.join(
                    config["infrastructure"]["base_path"], ".continuum/domain_%s.xml" % (name)
                )
                if machine.is_local:
                    command = "virsh --connect qemu:///system create %s" % (path)
                else:
                    command = "ssh %s 'bash -l -c \"virsh --connect qemu:///system create %s\"'" % (
                        machine.name,
                        path,
                    )

                commands.append(command)

        results = machines[0].process(config, commands, shell=True)
    else:
        # Only execute specific commands on repeat until VMs are launched succesfully
        commands = repeat
        results = machines[0].process(config, commands, shell=True)

    repeat = []
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error and "kex_exchange_identification" in error[0]:
            # Repeat execution if key exchange error, can be solved by executing again
            logging.error("ERROR, REPEAT EXECUTION: %s", "".join(error))
            repeat.append(command)
        elif error and "Connection to " not in error[0]:
            logging.error("ERROR: %s", "".join(error))
            sys.exit(1)
        elif "Domain " not in output[0] or " created from " not in output[0]:
            logging.error("ERROR: %s", "".join(output))
            sys.exit(1)

    return repeat


def start_vms(config, machines, runner=None):
    """Create and launch QEMU cloud and edge VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        runner (AnsibleRunner, optional): Shared runner instance for playbook execution.
    """
    logging.info("Start VM creation using QEMU")

    if runner is None:
        runner = ansible.AnsibleRunner(config, machines)

    # Delete older VM images
    runner.run_playbook(
        "playbooks/infrastructure/qemu_cleanup.yml",
        inventory="machine",
        env=_machine_playbook_env(),
    )

    # Check if os and base image need to be created, and if so do create them
    os_image(config, machines, runner=runner)
    base_image(config, machines, runner=runner)

    # Create VM overlay images for all tiers in one playbook call
    if any(
        [
            config["infrastructure"]["cloud_nodes"],
            config["infrastructure"]["edge_nodes"],
            config["infrastructure"]["endpoint_nodes"],
        ]
    ):
        cloud_vm_nodes_by_host = orchestration_schema.tier_vm_nodes_by_host(machines, "cloud")
        cloud_base_image_by_host = orchestration_schema.tier_base_image_by_host(machines, "cloud")
        edge_vm_nodes_by_host = orchestration_schema.tier_vm_nodes_by_host(machines, "edge")
        edge_base_image_by_host = orchestration_schema.tier_base_image_by_host(machines, "edge")
        endpoint_vm_nodes_by_host = orchestration_schema.tier_vm_nodes_by_host(machines, "endpoint")
        endpoint_base_image_by_host = orchestration_schema.tier_base_image_by_host(
            machines, "endpoint"
        )
        logging.info(
            "QEMU VM image mapping: cloud_nodes=%s cloud_base=%s edge_nodes=%s edge_base=%s endpoint_nodes=%s endpoint_base=%s",
            cloud_vm_nodes_by_host,
            cloud_base_image_by_host,
            edge_vm_nodes_by_host,
            edge_base_image_by_host,
            endpoint_vm_nodes_by_host,
            endpoint_base_image_by_host,
        )
        output, _ = runner.run_playbook(
            "playbooks/infrastructure/qemu_create_vms.yml",
            inventory="machine",
            extra_vars={
                "cloud_vm_nodes_by_host": cloud_vm_nodes_by_host,
                "cloud_base_image_by_host": cloud_base_image_by_host,
                "edge_vm_nodes_by_host": edge_vm_nodes_by_host,
                "edge_base_image_by_host": edge_base_image_by_host,
                "endpoint_vm_nodes_by_host": endpoint_vm_nodes_by_host,
                "endpoint_base_image_by_host": endpoint_base_image_by_host,
            },
            env=_machine_playbook_env(),
        )
        logging.info("qemu_create_vms playbook output:\n%s", "".join(output))

    # Start VMs
    repeat = []
    i = 0
    while True:
        repeat = launch_vms(config, machines, repeat)
        if not repeat:
            break

        if i == 1:
            logging.error("ERROR AFTER %i REPS: %s", i + 1, " | ".join(repeat))
            sys.exit(1)

        i += 1


def start(config, machines):
    """Manage infrastructure provider QEMU

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Set up QEMU")
    m.gather_ips(config, machines)
    m.gather_ssh(config, machines)

    for machine in machines:
        logging.debug(machine)

    logging.info("Generate configuration files for Infrastructure and Ansible")
    infrastructure.create_keypair(config, machines)
    runner = ansible.AnsibleRunner(config, machines)

    ansible.create_inventory_machine(config, machines)
    ansible.create_inventory_vm(config, machines)
    ansible.generate_group_vars(
        config,
        machines,
        os.path.join(
            config.get("tmp_dir", os.path.join(config["base"], ".tmp")),
            "inventory_group_vars",
        ),
    )
    ansible.copy(config, machines)

    generate.start(config, machines)
    copy(config, machines)

    logging.info("Setting up the infrastructure")
    start_vms(config, machines, runner=runner)
    infrastructure.add_ssh(config, machines)
