"""Image prefetch and registry lifecycle helpers for infrastructure phase."""

from __future__ import annotations

import json
import logging
import os
import sys
from urllib.parse import quote

from input.configuration import config_access, image_requirements

from . import orchestration_schema


def _fail_prefetch_requirements(message):
    logging.error("Invalid prefetch image requirements: %s", message)
    sys.exit(1)


def _serialize_prefetch_requirements(requirements):
    return [
        {
            "source_ref": requirement.source_ref,
            "local_name": requirement.local_name,
            "owners": list(requirement.owners),
            "tier_targets": list(requirement.tier_targets),
        }
        for requirement in requirements
    ]


def get_prefetch_requirements(config):
    if "prefetch_image_requirements" not in config:
        _fail_prefetch_requirements("missing required config key 'prefetch_image_requirements'")

    requirements = config["prefetch_image_requirements"]
    if not isinstance(requirements, list):
        _fail_prefetch_requirements("prefetch_image_requirements must be a list")

    normalized = []
    for index, requirement in enumerate(requirements):
        requirement_prefix = "prefetch_image_requirements[%s]" % (index,)
        if not isinstance(requirement, dict):
            _fail_prefetch_requirements("%s must be a mapping" % (requirement_prefix,))

        source_ref = requirement.get("source_ref")
        local_name = requirement.get("local_name")
        if isinstance(source_ref, str):
            source_ref = source_ref.strip()
        if isinstance(local_name, str):
            local_name = local_name.strip()
        if not isinstance(source_ref, str) or not source_ref:
            _fail_prefetch_requirements("%s.source_ref must be a non-empty string" % (requirement_prefix,))
        if not isinstance(local_name, str) or not local_name:
            _fail_prefetch_requirements("%s.local_name must be a non-empty string" % (requirement_prefix,))

        owners = requirement.get("owners")
        if not isinstance(owners, list):
            _fail_prefetch_requirements("%s.owners must be a list" % (requirement_prefix,))
        owner_values = set()
        for owner in owners:
            if not isinstance(owner, str) or not owner.strip():
                _fail_prefetch_requirements(
                    "%s.owners must contain non-empty strings" % (requirement_prefix,)
                )
            owner_values.add(owner.strip())
        if not owner_values:
            _fail_prefetch_requirements("%s.owners must not be empty" % (requirement_prefix,))

        tier_targets = requirement.get("tier_targets")
        if not isinstance(tier_targets, list):
            _fail_prefetch_requirements("%s.tier_targets must be a list" % (requirement_prefix,))
        tier_values = set()
        for tier in tier_targets:
            if not isinstance(tier, str) or not tier.strip():
                _fail_prefetch_requirements(
                    "%s.tier_targets must contain non-empty strings" % (requirement_prefix,)
                )
            tier_values.add(tier.strip())

        normalized.append(
            {
                "source_ref": source_ref,
                "local_name": local_name,
                "owners": sorted(owner_values),
                "tier_targets": sorted(tier_values),
            }
        )
    return normalized


def has_prefetch_requirements(config):
    return bool(get_prefetch_requirements(config))


def resolve_prefetch_requirements(config):
    """Resolve and cache deterministic image requirements for this run."""
    try:
        requirements = image_requirements.discover_required_images(config)
    except ValueError as exc:
        logging.error("Failed to resolve image requirements: %s", exc)
        sys.exit(1)
    serialized = _serialize_prefetch_requirements(requirements)
    config["prefetch_image_requirements"] = serialized
    return serialized


def _registry_catalog(config, machines):
    command = ["curl", "%s/v2/_catalog" % (config["registry"])]
    output, error = machines[0].process(config, command)[0]
    if error and any("Failed to connect to" in line for line in error):
        return None
    if error:
        logging.error("".join(error))
        sys.exit(1)
    if not output:
        logging.error("No output from Docker registry catalog")
        sys.exit(1)
    try:
        payload = json.loads(output[0])
    except (ValueError, TypeError) as exc:
        logging.error("Invalid registry catalog payload: %s", exc)
        sys.exit(1)
    repos = payload.get("repositories", [])
    if not isinstance(repos, list):
        logging.error("Invalid registry catalog payload: repositories must be a list")
        sys.exit(1)
    return set(str(repo) for repo in repos)


def _ensure_registry_running(config, machines):
    repos = _registry_catalog(config, machines)
    if repos is not None:
        return repos

    logging.info("Create local Docker registry")
    port = config["registry"].split(":")[-1]
    command = [
        "docker",
        "run",
        "-d",
        "-p",
        "%s:%s" % (port, port),
        "-e",
        "REGISTRY_STORAGE_DELETE_ENABLED=true",
        "--restart=always",
        "--name",
        "registry",
        "registry:2",
    ]
    _, error = machines[0].process(config, command)[0]

    if error and not (
        any("Unable to find image" in line for line in error)
        and any("Pulling from" in line for line in error)
    ):
        logging.error("".join(error))
        sys.exit(1)

    repos = _registry_catalog(config, machines)
    if repos is None:
        logging.error("Docker registry is still unreachable after startup")
        sys.exit(1)
    return repos


def _registry_repo_name(local_name):
    local_name = str(local_name or "").strip()
    if not local_name:
        return ""
    if "@" in local_name:
        return local_name.split("@", 1)[0]
    last_slash = local_name.rfind("/")
    last_colon = local_name.rfind(":")
    if last_colon > last_slash:
        return local_name[:last_colon]
    return local_name


def _registry_tag_name(local_name):
    local_name = str(local_name or "").strip()
    if not local_name or "@" in local_name:
        return None
    last_slash = local_name.rfind("/")
    last_colon = local_name.rfind(":")
    if last_colon > last_slash:
        return local_name[last_colon + 1 :]
    return None


def _registry_has_digest(local_name):
    local_name = str(local_name or "").strip()
    return "@" in local_name


def _registry_repo_tags(config, machines, repo_name):
    if not repo_name:
        return set()
    encoded_repo = quote(repo_name, safe="/")
    command = ["curl", "%s/v2/%s/tags/list" % (config["registry"], encoded_repo)]
    output, error = machines[0].process(config, command)[0]
    if error:
        logging.error("".join(error))
        sys.exit(1)
    if not output:
        logging.error("No output from Docker registry tags endpoint")
        sys.exit(1)
    try:
        payload = json.loads(output[0])
    except (ValueError, TypeError) as exc:
        logging.error("Invalid registry tags payload: %s", exc)
        sys.exit(1)

    errors = payload.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, dict) and err.get("code") == "NAME_UNKNOWN":
                return set()

    tags = payload.get("tags", [])
    if tags is None:
        return set()
    if not isinstance(tags, list):
        logging.error("Invalid registry tags payload: tags must be a list")
        sys.exit(1)
    return set(str(tag) for tag in tags)


def _registry_has_required_image(config, machines, requirement, repos, tags_cache):
    local_name = requirement["local_name"]
    repo_name = _registry_repo_name(local_name)
    if not repo_name:
        return False
    if repo_name not in repos:
        return False
    if _registry_has_digest(local_name):
        # Digest references are treated as non-cacheable in this pass.
        return False

    required_tag = _registry_tag_name(local_name)
    if required_tag is None:
        return True

    if repo_name not in tags_cache:
        tags_cache[repo_name] = _registry_repo_tags(config, machines, repo_name)
    return required_tag in tags_cache[repo_name]


def _requirements_to_pull(config, machines, requirements, repos):
    if config_access.image_prefetch_enabled(config):
        return list(requirements)

    tags_cache = {}
    return [
        requirement
        for requirement in requirements
        if not _registry_has_required_image(config, machines, requirement, repos, tags_cache)
    ]


def docker_registry(config, machines):
    """Ensure local registry cache and prefetch required container images."""
    requirements = get_prefetch_requirements(config)
    if not requirements:
        logging.info(
            "Skip local Docker registry: no required images for current software/benchmark intent"
        )
        return []

    repos = _ensure_registry_running(config, machines)
    to_pull = _requirements_to_pull(config, machines, requirements, repos)
    mode = config_access.image_prefetch_mode(config)
    if not to_pull:
        logging.info(
            "Skip remote image prefetch: all required images already cached in local registry (mode=%s)",
            mode,
        )
        return requirements

    logging.info(
        "Prefetch %s required image(s) into local registry (mode=%s)",
        len(to_pull),
        mode,
    )
    for requirement in to_pull:
        source_ref = requirement["source_ref"]
        local_name = requirement["local_name"]
        dest = os.path.join(config["registry"], local_name)
        for command in (
            ["docker", "pull", source_ref],
            ["docker", "tag", source_ref, dest],
            ["docker", "push", dest],
        ):
            _output, error = machines[0].process(config, command)[0]
            if error:
                logging.error("".join(error))
                sys.exit(1)
    return requirements


def docker_pull(config, machines, base_names):
    """Pull required prefetched images into selected base images."""
    requirements = get_prefetch_requirements(config)
    if not base_names or not requirements:
        return

    logging.info("Pull docker containers into base images")

    for machine in machines:
        commands = []
        sshs = []
        for name, ip in zip(machine.base_names, machine.base_ips):
            name_r = orchestration_schema.normalized_base_name(name)
            if name_r not in base_names:
                continue

            tier = orchestration_schema.tier_from_base_name(name_r)
            for requirement in requirements:
                tier_targets = requirement["tier_targets"]
                if tier_targets and tier not in tier_targets:
                    continue
                command = [
                    "docker",
                    "pull",
                    os.path.join(config["registry"], requirement["local_name"]),
                ]
                commands.append(command)
                sshs.append(orchestration_schema.guest_login_name(name) + "@" + ip)

        if commands:
            results = machines[0].process(config, commands, ssh=sshs)

            for ssh, (output, error) in zip(sshs, results):
                logging.info("Execute docker pull command on address [%s]", ssh)

                if error and any(
                    "server gave HTTP response to HTTPS client" in line for line in error
                ):
                    logging.warning(
                        """\
        File /etc/docker/daemon.json does not exist, or is empty on machine %s. 
        This will most likely prevent the machine from pulling endpoint docker images 
        from the private Docker registry running on the main machine %s.
        Please create this file on machine %s with content: { "insecure-registries":["%s"] }
        Followed by a restart of Docker: systemctl restart docker""",
                        ssh,
                        machines[0].name,
                        ssh,
                        config["registry"],
                    )
                if error:
                    logging.error("".join(error))
                    sys.exit(1)
                elif not output:
                    logging.error("No output from command docker pull")
                    sys.exit(1)


def _first_ssh_target(config, key):
    if key not in config:
        logging.error("Missing remote SSH target for registry migration at config key '%s'", key)
        sys.exit(1)
    entries = config[key]
    if isinstance(entries, list) and entries and isinstance(entries[0], str) and entries[0]:
        return entries[0]
    logging.error("Missing remote SSH target for registry migration at config key '%s'", key)
    sys.exit(1)


def _remote_registry_ssh(config):
    infra = config["infrastructure"]
    if int(infra["cloud_nodes"]) > 0:
        return _first_ssh_target(config, "cloud_ssh")
    if int(infra["edge_nodes"]) > 0:
        return _first_ssh_target(config, "edge_ssh")
    return _first_ssh_target(config, "endpoint_ssh")


def _first_internal_ip(machines, attr_name, tier_label):
    if not machines:
        logging.error("No machines available for %s registry endpoint selection", tier_label)
        sys.exit(1)
    ips = getattr(machines[0], attr_name, [])
    if isinstance(ips, list) and ips and isinstance(ips[0], str) and ips[0]:
        return ips[0]
    logging.error(
        "Missing %s internal IP for registry endpoint selection (expected machines[0].%s[0])",
        tier_label,
        attr_name,
    )
    sys.exit(1)


def set_remote_registry_endpoint(config, machines, control=False):
    """Set the active registry endpoint to provider-side address for base image pulls."""
    config["old_registry"] = config["registry"]

    if control:
        config["registry"] = "docker.io/redplanet00"
        return

    infra = config["infrastructure"]
    if int(infra["cloud_nodes"]) > 0:
        registry = _first_internal_ip(machines, "cloud_controller_ips_internal", "cloud-controller")
    elif int(infra["edge_nodes"]) > 0:
        registry = _first_internal_ip(machines, "edge_ips_internal", "edge")
    else:
        registry = _first_internal_ip(machines, "endpoint_ips_internal", "endpoint")

    config["registry"] = registry + ":5000"


def move_prefetched_images_to_remote_registry(config, machines):
    """Move required prefetched images from local registry to provider-side registry."""
    requirements = get_prefetch_requirements(config)
    if not requirements:
        logging.info("Skip registry migration: no required prefetched images")
        return
    if "old_registry" not in config:
        logging.error(
            "Missing old_registry in config before registry migration; call set_remote_registry_endpoint() first"
        )
        sys.exit(1)

    ssh = _remote_registry_ssh(config)
    logging.info("Create Docker registry on %s - %s", ssh, config["registry"])

    port = config["old_registry"].split(":")[-1]
    command = [
        "docker",
        "run",
        "-d",
        "-p",
        "%s:%s" % (port, port),
        "--restart=always",
        "--name",
        "registry",
        "registry:2",
    ]
    _, error = machines[0].process(config, command, ssh=ssh)[0]

    if error and not (
        any("Unable to find image" in line for line in error)
        and any("Pulling from" in line for line in error)
    ):
        logging.error("".join(error))
        sys.exit(1)

    logging.info("Copy all container images to new remote registry")
    for requirement in requirements:
        image_name = requirement["local_name"]
        tar_name = image_name.replace("/", "_").replace(":", "__")
        full_image = os.path.join(config["old_registry"], image_name)

        # Pull the image from the local registry to the local machine.
        command = ["docker", "pull", full_image]
        _, error = machines[0].process(config, command)[0]
        if error:
            logging.error("ERROR: Docker pull on image %s failed with error: %s", full_image, error)
            sys.exit(1)

        # Save the image as tar.
        source = os.path.join(
            config["infrastructure"]["base_path"], ".continuum", "%s.tar" % (tar_name)
        )
        command = ["docker", "save", "-o", source, full_image]
        _, error = machines[0].process(config, command)[0]
        if error:
            logging.error("ERROR: Docker save on image %s failed with error: %s", full_image, error)
            sys.exit(1)

        # Copy the image tar to the remote machine.
        dest = "%s:/tmp/" % (ssh)
        command = ["scp", "-i", config["ssh_key"], source, dest]
        output, error = machines[0].process(config, command)[0]
        if error:
            logging.error("".join(error))
            sys.exit(1)
        elif output and not any("Your public key has been saved in" in line for line in output):
            logging.error("".join(output))
            sys.exit(1)

        # Load image into remote docker storage.
        command = ["docker", "load", "-i", os.path.join("/tmp", "%s.tar" % (tar_name))]
        _, error = machines[0].process(config, command, ssh=ssh)[0]
        if error:
            logging.error("ERROR: Docker load on image %s failed with error: %s", full_image, error)
            sys.exit(1)

        # Tag and push into the remote registry.
        tag = os.path.join(config["registry"], image_name)
        for command in (["docker", "tag", full_image, tag], ["docker", "push", tag]):
            _, error = machines[0].process(config, command, ssh=ssh)[0]
            if error:
                logging.error("".join(error))
                sys.exit(1)
