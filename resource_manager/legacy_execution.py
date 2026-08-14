"""Temporary fail-closed adapter for the legacy broad Ansible inventory."""

from __future__ import annotations

from input.configuration import config_access


LEGACY_TARGET_GROUPS = frozenset(
    {"cloudcontroller", "clouds", "edges", "endpoints"}
)

BENCHMARK_WORKER_GROUP_BY_MODE = {
    "cloud": "clouds",
    "edge": "edges",
    "endpoint": "endpoints",
}


def _normalized_resources(config: dict) -> list[dict]:
    normalized = config.get("normalized")
    if not isinstance(normalized, dict):
        raise ValueError("Missing required config path normalized")
    infrastructure = normalized.get("infrastructure")
    if not isinstance(infrastructure, dict):
        raise ValueError("Missing required config path normalized.infrastructure")
    resources = infrastructure.get("resources")
    if not isinstance(resources, list):
        raise ValueError("Missing required config path normalized.infrastructure.resources")

    validated = []
    seen_vm_ids = set()
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ValueError(
                "Invalid normalized.infrastructure.resources[%s]: expected mapping" % (index,)
            )
        vm_id = resource.get("vm_id")
        tier = resource.get("tier")
        if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
            raise ValueError(
                "Invalid normalized.infrastructure.resources[%s].vm_id: expected integer >= 1"
                % (index,)
            )
        if vm_id in seen_vm_ids:
            raise ValueError(
                "Duplicate vm_id '%s' in normalized.infrastructure.resources" % (vm_id,)
            )
        if not isinstance(tier, str) or not tier.strip():
            raise ValueError(
                "Invalid normalized.infrastructure.resources[%s].tier: expected non-empty string"
                % (index,)
            )
        seen_vm_ids.add(vm_id)
        validated.append(resource)
    return sorted(validated, key=lambda resource: resource["vm_id"])


def project_legacy_inventory_groups(config: dict) -> dict[str, tuple[int, ...]]:
    """Project normalized VM ids into the groups emitted by ``inventory_vms``.

    This deliberately mirrors the transitional mode/tier behavior in
    ``infrastructure/ansible.py``. It is not a canonical module placement model.
    """
    resources = _normalized_resources(config)
    resources_by_tier = {
        tier: [resource["vm_id"] for resource in resources if resource["tier"] == tier]
        for tier in ("cloud", "edge", "endpoint")
    }
    mode = config.get("mode")
    orchestrator = config_access.orchestrator_name(config)
    provider = config.get("infrastructure", {}).get("provider")

    cloud_vm_ids = resources_by_tier["cloud"]
    has_cloud_controller = (
        mode in ("cloud", "edge")
        and orchestrator != "mist"
        and provider != "baremetal"
        and bool(cloud_vm_ids)
    )
    controller_vm_ids = cloud_vm_ids[:1] if has_cloud_controller else []
    cloud_worker_vm_ids = cloud_vm_ids[1:] if has_cloud_controller else cloud_vm_ids

    return {
        "cloudcontroller": tuple(controller_vm_ids),
        "clouds": tuple(cloud_worker_vm_ids if mode == "cloud" else ()),
        "edges": tuple(resources_by_tier["edge"] if mode == "edge" else ()),
        "endpoints": tuple(resources_by_tier["endpoint"]),
    }


def _assignment_by_owner(config: dict, owner_id: str, use_planner_snapshot: bool) -> dict:
    if use_planner_snapshot:
        return config_access.software_module_assignment_handoff_by_id(config, owner_id)
    return config_access.software_module_by_id(config, owner_id)


def _resource_description(resource: dict) -> str:
    return "vm_id=%s cluster=%s tier=%s" % (
        resource.get("vm_id"),
        resource.get("cluster_id", "<unknown>"),
        resource.get("tier", "<unknown>"),
    )


def validate_benchmark_execution_envelope(config: dict):
    """Reject benchmark assignments narrower than the legacy worker group."""
    mode = config.get("mode")
    worker_group = BENCHMARK_WORKER_GROUP_BY_MODE.get(mode)
    if worker_group is None:
        raise ValueError(
            "Unsupported benchmark mode '%s' at the legacy application execution boundary"
            % (mode,)
        )

    assignment = config_access.benchmark_stage_assignment(config)
    resolved_vm_ids = assignment["resolved_vm_ids"]
    executable_vm_ids = set(project_legacy_inventory_groups(config)[worker_group])
    unselected_vm_ids = sorted(executable_vm_ids - set(resolved_vm_ids))
    if not unselected_vm_ids:
        return

    resources_by_vm_id = {
        resource["vm_id"]: resource for resource in _normalized_resources(config)
    }
    unselected = "; ".join(
        _resource_description(resources_by_vm_id[vm_id]) for vm_id in unselected_vm_ids
    )
    raise ValueError(
        "Benchmark stage '%s' (%s) authorizes resolved_vm_ids %s, but the current legacy "
        "%s worker group '%s' would also target unselected resources: %s. Partial benchmark "
        "assignments are unsupported at this execution boundary; include every legacy "
        "benchmark worker in assign_to"
        % (
            assignment["id"],
            assignment["type"],
            sorted(resolved_vm_ids),
            mode,
            worker_group,
            unselected,
        )
    )


def validate_software_execution_envelopes(
    config: dict,
    entries: list,
    *,
    use_planner_snapshot: bool,
):
    """Reject software plans whose legacy targets exceed owner assignments."""
    projected_groups = project_legacy_inventory_groups(config)
    resources = _normalized_resources(config)
    resources_by_vm_id = {resource["vm_id"]: resource for resource in resources}
    targets_by_owner: dict[str, set[int]] = {}
    sources_by_owner: dict[str, list[tuple[str, tuple[str, ...]]]] = {}

    for entry in entries:
        owner_id = getattr(entry, "owner_id", "")
        owner_type = getattr(entry, "owner_type", "")
        if not owner_id or not owner_type:
            raise ValueError("Software plan entry is missing owner metadata")
        if entry.kind == "command":
            raise ValueError(
                "Software module '%s' (%s) emits a command plan entry whose resource mutation "
                "scope cannot be proven at the current execution boundary"
                % (owner_id, owner_type)
            )
        if entry.kind != "playbook":
            raise ValueError("Unsupported software plan entry kind '%s'" % (entry.kind,))
        if entry.inventory != "vms":
            raise ValueError(
                "Software playbook '%s' uses unsupported inventory '%s'; resource scope cannot "
                "be proven" % (entry.playbook, entry.inventory)
            )

        target_groups = entry.legacy_target_groups
        if not isinstance(target_groups, tuple) or not target_groups:
            raise ValueError(
                "Software playbook '%s' must declare immutable legacy_target_groups metadata"
                % (entry.playbook,)
            )
        if len(set(target_groups)) != len(target_groups):
            raise ValueError(
                "Software playbook '%s' has duplicate legacy target groups" % (entry.playbook,)
            )
        unknown_groups = sorted(set(target_groups) - LEGACY_TARGET_GROUPS)
        if unknown_groups:
            raise ValueError(
                "Software playbook '%s' declares unknown legacy target group(s): %s"
                % (entry.playbook, ", ".join(unknown_groups))
            )

        owner_targets = targets_by_owner.setdefault(owner_id, set())
        for group in target_groups:
            owner_targets.update(projected_groups[group])
        sources_by_owner.setdefault(owner_id, []).append((entry.playbook, target_groups))

    for owner_id, executable_vm_ids in targets_by_owner.items():
        assignment = _assignment_by_owner(config, owner_id, use_planner_snapshot)
        owner_type = assignment.get("type")
        resolved_vm_ids = assignment.get("resolved_vm_ids")
        if not isinstance(resolved_vm_ids, list) or not all(
            isinstance(vm_id, int) and not isinstance(vm_id, bool) and vm_id > 0
            for vm_id in resolved_vm_ids
        ):
            raise ValueError(
                "Software module '%s' (%s) has invalid resolved_vm_ids assignment metadata"
                % (owner_id, owner_type)
            )
        unselected_vm_ids = sorted(executable_vm_ids - set(resolved_vm_ids))
        if not unselected_vm_ids:
            continue

        source_descriptions = [
            "%s [%s]" % (playbook, ", ".join(groups))
            for playbook, groups in sources_by_owner[owner_id]
        ]
        unselected = "; ".join(
            _resource_description(resources_by_vm_id[vm_id]) for vm_id in unselected_vm_ids
        )
        raise ValueError(
            "Software module '%s' (%s) authorizes resolved_vm_ids %s, but the current legacy "
            "executor for %s would also target unselected resources: %s. Partial assignments "
            "are unsupported at this execution boundary; include every execution participant "
            "in assign_to"
            % (
                owner_id,
                owner_type,
                sorted(resolved_vm_ids),
                ", ".join(source_descriptions),
                unselected,
            )
        )
