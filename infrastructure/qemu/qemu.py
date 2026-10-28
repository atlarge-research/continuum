"""\
Create and use QEMU Vms
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import shlex
import sys
import time

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError

from infrastructure import ansible, image_registry, infrastructure
from infrastructure import machine as m
from infrastructure import network, orchestration_schema
from input.configuration import config_access
from resource_manager import plans as rm_plans

from . import generate, host_cache_helper

_CACHE_PROTOCOL = host_cache_helper.PROTOCOL
_SYNTHETIC_NONZERO_MARKER = "Command exited with non-zero return code"
_BASE_SHUTDOWN_ATTEMPTS = 12
_BASE_SHUTDOWN_INTERVAL_SECONDS = 5


def _load_host_cache_helper_source():
    """Load the exact standalone helper source shipped beside this module."""
    helper_path = os.path.join(os.path.dirname(__file__), "host_cache_helper.py")
    with open(helper_path, "r", encoding="utf-8") as filep:
        return filep.read()


_HOST_CACHE_HELPER_SOURCE = _load_host_cache_helper_source()


def _machine_playbook_env():
    """Return environment overrides for local host-side QEMU playbooks.

    These playbooks operate on the physical QEMU host and should not inherit the
    global Ansible ``become = True`` default. Host prerequisites are installed
    explicitly during smoke-host setup instead.
    """

    return {"ANSIBLE_BECOME": "False"}


def _delete_local_path(path):
    """Best-effort local cleanup retained for the OS-image cache path."""
    if os.path.exists(path):
        os.remove(path)


def _base_image_metadata_path(config, raw_base_name):
    """Return the cache metadata path for one raw base image name."""
    return os.path.join(
        config["infrastructure"]["base_path"],
        ".continuum/images/%s.meta.json" % (raw_base_name),
    )


def _base_image_paths(config, raw_base_name):
    """Return the exact owner-local paths associated with one base image."""
    base_path = config["infrastructure"]["base_path"]
    images_path = os.path.join(base_path, ".continuum", "images")
    return {
        "metadata": _base_image_metadata_path(config, raw_base_name),
        "image": os.path.join(images_path, "%s.qcow2" % (raw_base_name,)),
        "cloud_init": os.path.join(images_path, "user_data_%s.img" % (raw_base_name,)),
        "user_data": os.path.join(
            base_path,
            ".continuum",
            "user_data_%s.yml" % (raw_base_name,),
        ),
    }


def _owner_process(machine, config, command):
    """Run one flat argv command on its physical owner without a shell."""
    if machine.is_local:
        return machine.process(config, command)
    remote_command = [shlex.quote(argument) for argument in command]
    return machine.process(config, remote_command, ssh=machine.name, ssh_key=False)


def _single_process_result(results, operation):
    """Require one unambiguous successful Machine.process result."""
    validated = _validated_process_results(results, 1, operation)
    output, error = validated[0]
    if error:
        raise RuntimeError("%s failed: %s" % (operation, "\n".join(map(str, error))))
    return output


def _validated_process_results(results, expected_count, operation):
    """Validate result shape/count and reject every synthetic nonzero marker."""
    if not isinstance(results, list) or len(results) != expected_count:
        raise RuntimeError("%s failed: expected %s process result(s)" % (operation, expected_count))
    validated = []
    for result in results:
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise RuntimeError("%s failed: malformed process result" % (operation,))
        output, error = result
        if not isinstance(output, list) or not isinstance(error, list):
            raise RuntimeError("%s failed: malformed process output" % (operation,))
        if any(_SYNTHETIC_NONZERO_MARKER in str(line) for line in error):
            details = "\n".join(str(line) for line in error
                                if _SYNTHETIC_NONZERO_MARKER not in str(line))
            raise RuntimeError("%s failed: command returned nonzero%s" %
                               (operation, ": " + details if details else ""))
        validated.append((output, error))
    return validated


def _host_cache_operation(machine, config, operation, arguments, response_keys):
    """Execute one strict cache-helper protocol operation on an owning host."""
    command = ["python3", "-c", _HOST_CACHE_HELPER_SOURCE, operation]
    command.extend(arguments)
    output = _single_process_result(
        _owner_process(machine, config, command),
        "QEMU cache %s on %s" % (operation, machine.name),
    )
    if len(output) != 1:
        raise RuntimeError(
            "QEMU cache %s on %s failed: expected one protocol response" % (operation, machine.name)
        )
    try:
        response = json.loads(output[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "QEMU cache %s on %s failed: malformed protocol response" % (operation, machine.name)
        ) from exc
    if not isinstance(response, dict) or set(response) not in response_keys:
        raise RuntimeError(
            "QEMU cache %s on %s failed: malformed protocol mapping" % (operation, machine.name)
        )
    if response.get("protocol") != _CACHE_PROTOCOL:
        raise RuntimeError(
            "QEMU cache %s on %s failed: protocol mismatch" % (operation, machine.name)
        )
    return response


def _cleanup_base_image_cache(machine, config, raw_base_name):
    """Remove one invalid owner's exact cache files, ready metadata first."""
    paths = _base_image_paths(config, raw_base_name)
    response = _host_cache_operation(
        machine,
        config,
        "cleanup",
        [paths["metadata"], paths["image"], paths["cloud_init"]],
        ({"protocol", "status"},),
    )
    if response["status"] != "ok":
        raise RuntimeError("QEMU cache cleanup on %s did not succeed" % (machine.name,))


def _invalidate_base_image_marker(machine, config, raw_base_name):
    """Remove one participating owner's marker before its cache can be modified."""
    response = _host_cache_operation(
        machine,
        config,
        "invalidate",
        [_base_image_metadata_path(config, raw_base_name)],
        ({"protocol", "status"},),
    )
    if response["status"] != "ok":
        raise RuntimeError("QEMU cache invalidation on %s did not succeed" % (machine.name,))


def _confirm_base_vms_stopped(config, selected_entries):
    """Boundedly confirm selected transient domains are absent from running domains."""
    owners = []
    for machine, _raw_base_name, _normalized_name, _invalid_reason in selected_entries:
        if all(machine is not owner for owner in owners):
            owners.append(machine)

    for machine in owners:
        selected_names = {
            raw_base_name
            for owner, raw_base_name, _normalized_name, _invalid_reason in selected_entries
            if owner is machine
        }
        command = [
            "virsh",
            "--connect",
            "qemu:///system",
            "list",
            "--state-running",
            "--name",
        ]
        for attempt in range(_BASE_SHUTDOWN_ATTEMPTS):
            output = _single_process_result(
                _owner_process(machine, config, command),
                "base VM shutdown confirmation on %s" % (machine.name,),
            )
            if all(isinstance(name, str) for name in output) and selected_names.isdisjoint(output):
                break
            if attempt + 1 < _BASE_SHUTDOWN_ATTEMPTS:
                time.sleep(_BASE_SHUTDOWN_INTERVAL_SECONDS)
        else:
            raise RuntimeError(
                "Base VM shutdown on %s was not confirmed after %s attempts"
                % (machine.name, _BASE_SHUTDOWN_ATTEMPTS)
            )


def _select_base_image_rebuilds(config, machines, timezone=None):
    """Validate owners, invalidate every participant, then clean invalid caches."""
    timezone = _controller_timezone() if timezone is None else timezone
    # Complete controller-side recipe validation before touching any owner marker.
    recipes = [
        (machine, raw_name, _expected_base_image_metadata(
            config, machines, raw_name, timezone=timezone
        ))
        for machine in machines
        for raw_name in machine.base_names
    ]
    cache_entries = []
    rebuild_names = []
    for machine, raw_base_name, expected in recipes:
        normalized_name = orchestration_schema.normalized_base_name(raw_base_name)
        invalid_reason = _base_image_cache_invalid_reason(
            config,
            machines,
            raw_base_name,
            machine=machine,
            expected=expected,
        )
        cache_entries.append((machine, raw_base_name, normalized_name, invalid_reason))
        if invalid_reason and normalized_name not in rebuild_names:
            rebuild_names.append(normalized_name)

    selected_entries = [entry for entry in cache_entries if entry[2] in rebuild_names]
    for machine, raw_base_name, _normalized_name, _invalid_reason in selected_entries:
        _invalidate_base_image_marker(machine, config, raw_base_name)

    for machine, raw_base_name, _normalized_name, invalid_reason in selected_entries:
        if not invalid_reason:
            continue
        logging.info(
            "Cached base image is invalid on %s (%s); removing and rebuilding: %s",
            machine.name,
            invalid_reason,
            _base_image_paths(config, raw_base_name)["image"],
        )
        _cleanup_base_image_cache(machine, config, raw_base_name)
    return rebuild_names, selected_entries


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
        prepare_for_resume = infra_only and config_access.prepare_for_resume_enabled(config)
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


def _common_base_install_hosts_for_base_names(normalized_base_names):
    """Return the inventory host pattern for common setup on rebuilt base VMs."""
    groups = []
    for normalized_name in normalized_base_names:
        tier = orchestration_schema.tier_from_base_name(normalized_name)
        if tier is None:
            return "base"
        group = "base_%s" % (tier)
        if group not in groups:
            groups.append(group)

    return ":".join(groups) if groups else "base"


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
    data = _recipe_yaml(playbook_path)
    if not isinstance(data, list) or not data or not all(isinstance(play, dict) for play in data):
        raise RuntimeError("Invalid QEMU base playbook %s: expected plays" % playbook_path)

    role_names = []
    for play in data:
        roles = play.get("roles", [])
        if not isinstance(roles, list):
            raise RuntimeError("Invalid QEMU base playbook roles: %s" % playbook_path)
        for role in roles:
            role_name = role if isinstance(role, str) else None
            if isinstance(role, dict):
                role_name = role.get("role")
            if not isinstance(role_name, str) or not role_name or "{{" in role_name:
                raise RuntimeError("QEMU base playbook requires literal roles: %s" % playbook_path)
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


def _files_under(path, exclude_git=False):
    """Return all regular files under one file or directory path."""
    if os.path.isfile(path):
        return [path]
    files = []
    for root, _dirs, filenames in os.walk(path):
        if exclude_git:
            _dirs[:] = [name for name in _dirs if name != ".git"]
        for filename in filenames:
            if exclude_git and filename == ".git":
                continue
            files.append(os.path.join(root, filename))
    return files


def _recipe_yaml(path):
    """Read one static recipe document without interpreting Ansible tasks."""
    try:
        with open(path, "r", encoding="utf-8") as filep:
            return yaml.safe_load(filep)
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError("Cannot read QEMU base recipe %s: %s" % (path, exc)) from exc


def _literal_role_includes(value):
    """Yield literal included roles and their explicit task vars, including blocks."""
    if isinstance(value, list):
        for item in value:
            yield from _literal_role_includes(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("include_role", "import_role", "ansible.builtin.include_role",
                       "ansible.builtin.import_role"):
                name = item.get("name") if isinstance(item, dict) else item
                if not isinstance(name, str) or not name or "{{" in name:
                    raise RuntimeError("QEMU base cache requires literal included role names")
                yield name, value.get("vars", {})
            elif key in ("block", "rescue", "always"):
                yield from _literal_role_includes(item)


def _validate_base_role_sources(path):
    """Reject damaged selected static role sources before cache mutation."""
    # These shipped base roles consume variables supplied by their defaults.
    # Defaults are optional for arbitrary Ansible roles, not for these recipes.
    if os.path.basename(path) in {
        "netperf", "mahimahi", "k8s_prereqs", "containerd_setup", "mosquitto",
        "k8s_binary_override", "kubeedge_prereqs", "docker_setup",
        "endpoint_prereqs", "endpoint_runtime",
    }:
        _recipe_yaml(os.path.join(path, "defaults", "main.yml"))
    entrypoint = os.path.join(path, "tasks", "main.yml")
    if not os.path.isfile(entrypoint) and os.path.isfile(entrypoint[:-3] + "yaml"):
        entrypoint = entrypoint[:-3] + "yaml"
    tasks = _recipe_yaml(entrypoint)
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        raise RuntimeError("Invalid QEMU base role tasks: %s" % entrypoint)
    for source in _files_under(path):
        section = os.path.relpath(source, path).split(os.sep)[0]
        if section not in ("tasks", "handlers", "defaults", "vars", "meta"):
            continue
        if source.endswith((".yml", ".yaml")):
            value = _recipe_yaml(source)
            expected = list if section in ("tasks", "handlers") else dict
            if value is not None and not isinstance(value, expected):
                raise RuntimeError("Invalid QEMU base role YAML shape: %s" % source)
            if isinstance(value, list) and not all(isinstance(task, dict) for task in value):
                raise RuntimeError("Invalid QEMU base role task shape: %s" % source)


def _base_recipe_roles(config, playbooks, raw_base_name):
    """Resolve the current recipes' literal role closure, not general Ansible logic."""
    pending = [(name, {}) for playbook in playbooks
               for name in _playbook_role_names(config, playbook)]
    roles = []
    visited = set()
    while pending:
        name, overrides = pending.pop(0)
        if name in visited:
            continue
        visited.add(name)
        if name == "mahimahi" and not _mahimahi_enabled(config):
            continue
        # This is the explicit hostname condition in k8s_base_install.yml.
        if name == "k8s_binary_override" and not any(
            token in raw_base_name for token in ("kubecontrol", "kube_kata")
        ):
            continue
        path = _role_path(config, name)
        if not path:
            raise RuntimeError("Cannot resolve required QEMU base role: %s" % name)
        _validate_base_role_sources(path)
        roles.append((name, path, overrides))
        for task_path in _files_under(os.path.join(path, "tasks")):
            if task_path.endswith((".yml", ".yaml")):
                pending.extend(_literal_role_includes(_recipe_yaml(task_path)))
    return roles


def _resolved_recipe_value(value, context, label):
    """Render only a known copied-source/version field with inventory input values."""
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("QEMU base recipe lacks %s" % label)
    try:
        return Environment(undefined=StrictUndefined).from_string(value).render(context).strip()
    except TemplateError as exc:
        raise RuntimeError("Cannot resolve QEMU base recipe %s: %s" % (label, exc)) from exc


def _copied_base_recipe_inputs(config, roles):
    """Return required copied files and values actually consumed by these roles."""
    copied = []
    inputs = {}
    relevant = {name for name, _path, _overrides in roles}
    if not relevant.intersection({"containerd_setup", "docker_setup", "k8s_binary_override",
                                  "kubeedge_prereqs"}):
        return copied, inputs
    version = config_access.orchestrator_overrides(config, ["kube_version"]).get(
        "kube_version", "v1.27.0"
    )
    context = {
        "continuum_repo_root": os.path.abspath(config.get("base", ".")),
        "continuum_resource_manager_type": config_access.orchestrator_name(config),
        "kubeversionstrp": version.replace(".", ""),
        "continuum_kubeversionstrp": version.replace(".", ""),
        "kubeversion_major": version[:-2],
        "continuum_kubeversion_major": version[:-2],
    }
    if relevant.intersection({"containerd_setup", "docker_setup"}):
        inputs["registry"] = config.get("registry", "")
    for name, path, overrides in roles:
        key = {"containerd_setup": "rm_containerd_setup_config_src",
               "k8s_binary_override": "rm_k8s_binary_override_tarball_path",
               "kubeedge_prereqs": "rm_kubeedge_prereqs_repo_major_minor"}.get(name)
        if key is None:
            continue
        defaults_path = os.path.join(path, "defaults", "main.yml")
        defaults = _recipe_yaml(defaults_path) or {}
        value = overrides.get(key, defaults.get(key))
        resolved = _resolved_recipe_value(value, context, key)
        if name == "kubeedge_prereqs":
            inputs["kubeedge_repo_major_minor"] = resolved
            continue
        source = _repo_path(config, resolved)
        try:
            if not os.path.isfile(source):
                raise OSError("not a regular file")
            # Validate readability now, before ANY owner-cache operation.
            with open(source, "rb") as filep:
                filep.read(1)
        except OSError as exc:
            raise RuntimeError(
                "Cannot read required QEMU base input %s: %s" % (source, exc)
            ) from exc
        copied.append(source)
    return copied, inputs


def _base_install_fingerprints(config, playbooks, additional_files=(), roles=()):
    """Return content fingerprints for base-install playbooks and active role closure."""
    paths = set(additional_files)
    for playbook in playbooks:
        playbook_path = _repo_path(config, playbook)
        if os.path.exists(playbook_path):
            paths.add(playbook_path)

    for _name, role_path, _overrides in roles:
        paths.update(_files_under(role_path))

    base = os.path.abspath(config.get("base", "."))
    fingerprints = []
    for path in sorted(paths):
        relpath = os.path.relpath(path, base)
        fingerprints.append({"path": relpath, "sha256": _file_digest(path)})
    return fingerprints


def _mahimahi_enabled(config):
    """Return the same optional common-install intent used by the base build."""
    preset = config["infrastructure"].get("wireless_network_preset", "")
    return isinstance(preset, str) and preset.endswith("_mahimahi")


def _controller_timezone():
    """Read the exact controller timezone before any cache invalidation."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError as exc:
        raise RuntimeError("Cannot read controller timezone /etc/localtime: %s" % exc) from exc
    if not isinstance(target, str) or not target.strip():
        raise RuntimeError("Controller timezone /etc/localtime has an empty symlink target")
    return target


def _expected_base_image_metadata(config, machines, raw_base_name, timezone=None):
    """Return the expected ready-marker payload for one base image."""
    normalized_name = orchestration_schema.normalized_base_name(raw_base_name)
    playbooks = _base_install_playbooks_for_base_names(
        config,
        machines,
        [normalized_name],
    )
    recipe_inputs = {
        "timezone": _controller_timezone() if timezone is None else timezone,
        "mahimahi_enabled": _mahimahi_enabled(config),
    }
    source_files = []
    if recipe_inputs["mahimahi_enabled"]:
        source = os.path.join(
            config["infrastructure"]["base_path"], ".continuum", "mahimahi", "repo"
        )
        recipe_inputs["mahimahi_source"] = "available" if os.path.isdir(source) else "pending-fetch"
        source_files = _files_under(source, exclude_git=True)
    fingerprint_playbooks = playbooks + ["playbooks/infrastructure/common_base_install.yml"]
    roles = _base_recipe_roles(config, fingerprint_playbooks, raw_base_name)
    copied_files, copied_inputs = _copied_base_recipe_inputs(config, roles)
    source_files.extend(copied_files)
    recipe_inputs.update(copied_inputs)
    recipe_inputs["preloaded_images"] = image_registry.qemu_base_preload_identities(
        config, machines, raw_base_name
    )
    return {
        "schema_version": 1,
        "status": "ready",
        "guest_user": orchestration_schema.guest_login_name(raw_base_name),
        "base_install_playbooks": playbooks,
        "base_install_fingerprints": _base_install_fingerprints(
            config, fingerprint_playbooks, additional_files=source_files, roles=roles
        ),
        "base_recipe_inputs": recipe_inputs,
    }


def _base_image_cache_invalid_reason(config, machines, raw_base_name, machine=None, expected=None):
    """Return an owner-proven cache validation reason, or None when valid."""
    if expected is None:
        expected = _expected_base_image_metadata(config, machines, raw_base_name)
    if machine is None:
        machine = m.Machine("localhost", True)
    paths = _base_image_paths(config, raw_base_name)
    response = _host_cache_operation(
        machine,
        config,
        "check",
        [paths["image"], paths["metadata"]],
        (
            {"protocol", "status", "reason"},
            {"protocol", "status", "metadata_b64"},
        ),
    )
    if response["status"] == "invalid":
        reason = response["reason"]
        if reason not in (
            "image missing",
            "metadata missing",
        ):
            raise RuntimeError("QEMU cache check returned an unknown invalid reason")
        return reason
    if response["status"] != "ok" or not isinstance(response.get("metadata_b64"), str):
        raise RuntimeError("QEMU cache check returned an invalid status")

    try:
        metadata_bytes = base64.b64decode(response["metadata_b64"], validate=True)
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "metadata malformed"
    if not isinstance(payload, dict):
        return "metadata invalid"

    schema_version = payload.get("schema_version")
    if (
        type(schema_version) is not int  # pylint: disable=unidiomatic-typecheck
        or schema_version != expected["schema_version"]
    ):
        return "metadata schema_version mismatch"
    for key, value in expected.items():
        if key == "schema_version":
            continue
        if payload.get(key) != value:
            return "metadata %s mismatch" % (key,)
    return None


def _canonical_base_image_metadata(config, machines, raw_base_name, timezone=None):
    """Return deterministic canonical schema-v1 ready metadata bytes."""
    payload = _expected_base_image_metadata(config, machines, raw_base_name, timezone=timezone)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_base_image_metadata(config, machines, raw_base_name, machine=None, timezone=None):
    """Atomically publish ready metadata on one owning physical host."""
    if machine is None:
        machine = m.Machine("localhost", True)
    encoded_payload = base64.b64encode(
        _canonical_base_image_metadata(config, machines, raw_base_name, timezone=timezone)
    ).decode("ascii")
    response = _host_cache_operation(
        machine,
        config,
        "publish",
        [_base_image_metadata_path(config, raw_base_name), encoded_payload],
        ({"protocol", "status"},),
    )
    if response["status"] != "ok":
        raise RuntimeError("QEMU cache publication on %s did not succeed" % (machine.name,))


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
    # Future cleanup: move base_ip and related logic here; that path is not generic
    # because GCP does not use it.
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

    timezone = _controller_timezone()
    rebuild_names, selected_entries = _select_base_image_rebuilds(
        config, machines, timezone=timezone
    )
    if not rebuild_names:
        logging.info("Base image(s) are all already present")
        return

    logging.info("Create base image set via qemu_prepare_base.yml")
    runner.run_playbook(
        "playbooks/infrastructure/qemu_prepare_base.yml",
        inventory="machine",
        extra_vars={
            "continuum_base_images_by_host": orchestration_schema.base_images_by_host(
                machines, rebuild_names
            )
        },
        env=_machine_playbook_env(),
    )

    base_ips = []
    for machine, raw_base_name, _normalized_name, _invalid_reason in selected_entries:
        base_ip = machine.base_ips[machine.base_names.index(raw_base_name)]
        path = os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum",
            "domain_%s.xml" % (raw_base_name,),
        )
        command = ["virsh", "--connect", "qemu:///system", "create", path]
        output = _single_process_result(
            _owner_process(machine, config, command),
            "base VM launch on %s" % (machine.name,),
        )
        # virsh adds presentation blank lines; cache-helper responses remain strict.
        launch_output = (
            [line for line in output if line.strip()]
            if all(isinstance(line, str) for line in output)
            else []
        )
        if (
            len(launch_output) != 1
            or not launch_output[0].startswith("Domain ")
            or " created from " not in launch_output[0]
        ):
            raise RuntimeError(
                "Base VM launch on %s returned an invalid response: %r" % (machine.name, output)
            )
        base_ips.append(base_ip)

    # Fix SSH keys for each base image
    infrastructure.add_ssh(config, machines, base=base_ips)

    # Install software concurrently (infra_only won't get anything installed)
    playbooks = _base_install_playbooks_for_base_names(config, machines, rebuild_names)

    if playbooks:
        logging.info("Install software in the base VMs")
        runner.run_playbooks(playbooks, inventory="vms")

    # Install common infrastructure software (netperf + optional Mahimahi)
    runner.run_playbook(
        "playbooks/infrastructure/common_base_install.yml",
        inventory="vms",
        extra_vars={
            "continuum_common_base_hosts": _common_base_install_hosts_for_base_names(rebuild_names),
            "continuum_enable_mahimahi": _mahimahi_enabled(config),
        },
    )

    # Install docker containers if required
    if image_registry.has_prefetch_requirements(config):
        # Kubernetes/KubeEdge don't need docker images on the cloud/edge nodes
        # These RM will automatically pull images, so we can skip this here.
        # Only pull endpoint images instead
        docker_base_names = image_registry.qemu_preload_base_names(config, rebuild_names)
        image_registry.docker_pull(config, machines, docker_base_names)

    # Reuse the exact timezone resolved before cache invalidation.
    command = ["sudo", "ln", "-sf", timezone, "/etc/localtime"]
    sshs = []
    for machine in machines:
        for ip, name in zip(machine.base_ips, machine.base_names):
            name_r = orchestration_schema.normalized_base_name(name)
            if name_r in rebuild_names:
                ssh = "%s@%s" % (orchestration_schema.guest_login_name(name), ip)
                sshs.append(ssh)

    results = machines[0].process(config, command, ssh=sshs)

    results = _validated_process_results(results, len(sshs), "base VM timezone update")
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
            if base_name_r in rebuild_names:
                sshs.append("%s@%s" % (orchestration_schema.guest_login_name(base_name), ip))

    results = machines[0].process(config, command, ssh=sshs)

    results = _validated_process_results(results, len(sshs), "base VM cloud-init cleanup")
    for ssh, (output, error) in zip(sshs, results):
        logging.info("Check output for command [sudo cloud-init clean] on [%s]", ssh)
        ansible.check_output((output, error))

    for machine, raw_base_name, _normalized_name, _invalid_reason in selected_entries:
        command = ["virsh", "--connect", "qemu:///system", "shutdown", raw_base_name]
        output = _single_process_result(
            _owner_process(machine, config, command),
            "base VM shutdown on %s" % (machine.name,),
        )
        # Success prose varies by virsh version/locale; confirm actual state below.
        if not all(isinstance(line, str) for line in output):
            raise RuntimeError(
                "Base VM shutdown on %s returned an invalid response: %r" % (machine.name, output)
            )

    _confirm_base_vms_stopped(config, selected_entries)

    for machine, raw_base_name, _normalized_name, _invalid_reason in selected_entries:
        _write_base_image_metadata(
            config,
            machines,
            raw_base_name,
            machine=machine,
            timezone=timezone,
        )


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
