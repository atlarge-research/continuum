"""Centralized config-domain access helpers for YAML runtime config."""

from __future__ import annotations

import os
from copy import deepcopy

from . import module_registry, selector_resolution

_ALLOWED_RUN_TARGETS = ("infrastructure", "software", "application")
_ALLOWED_IMAGE_PREFETCH_MODES = ("off", "on")
_ORCHESTRATOR_MODULE_TYPES = module_registry.ORCHESTRATOR_MODULE_TYPES
_ADDON_MODULE_TYPES = module_registry.ADDON_MODULE_TYPES


def _require_non_empty_string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid config path %s: expected non-empty string" % (path,))
    return value.strip()


def _require_mapping(value, path):
    if not isinstance(value, dict):
        raise ValueError("Invalid config path %s: expected mapping" % (path,))
    return value


def _require_list(value, path):
    if not isinstance(value, list):
        raise ValueError("Invalid config path %s: expected list" % (path,))
    return value


def _nested_value(mapping, *keys, default=None):
    node = mapping
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def run_targets(config):
    targets = _nested_value(config, "domains", "run", "targets", default=None)
    if not isinstance(targets, list) or not targets:
        raise ValueError("Missing required config path domains.run.targets")

    normalized = []
    seen = set()
    for target in targets:
        if not isinstance(target, str):
            raise ValueError("Invalid run target type in domains.run.targets: %r" % (target,))
        if target not in _ALLOWED_RUN_TARGETS:
            raise ValueError(
                "Invalid run target '%s' in domains.run.targets (allowed: %s)"
                % (target, ", ".join(_ALLOWED_RUN_TARGETS))
            )
        if target not in seen:
            seen.add(target)
            normalized.append(target)

    return normalized


def image_prefetch_mode(config):
    mode = _nested_value(config, "domains", "run", "image_prefetch", default=None)
    if mode is None:
        raise ValueError("Missing required config path domains.run.image_prefetch")
    if not isinstance(mode, str):
        raise ValueError(
            "Invalid image prefetch mode type in domains.run.image_prefetch: %r" % (mode,)
        )
    normalized_mode = mode.strip().lower()
    if normalized_mode not in _ALLOWED_IMAGE_PREFETCH_MODES:
        raise ValueError(
            "Invalid image prefetch mode '%s' in domains.run.image_prefetch (allowed: %s)"
            % (normalized_mode, ", ".join(_ALLOWED_IMAGE_PREFETCH_MODES))
        )
    return normalized_mode


def image_prefetch_enabled(config):
    return image_prefetch_mode(config) == "on"


def prepare_for_resume_enabled(config):
    enabled = _nested_value(config, "domains", "run", "prepare_for_resume", default=None)
    if enabled is None:
        raise ValueError("Missing required config path domains.run.prepare_for_resume")
    if not isinstance(enabled, bool):
        raise ValueError(
            "Invalid prepare_for_resume type in domains.run.prepare_for_resume: %r"
            % (enabled,)
        )
    return enabled


def runs_infrastructure(config):
    return "infrastructure" in set(run_targets(config))


def runs_software(config):
    return "software" in set(run_targets(config))


def runs_application(config):
    return "application" in set(run_targets(config))


def infra_only(config):
    return (
        runs_infrastructure(config) and not runs_software(config) and not runs_application(config)
    )


def infrastructure_base_path(config):
    base_path = _nested_value(config, "infrastructure", "base_path", default=None)
    return _require_non_empty_string(base_path, "infrastructure.base_path")


def continuum_home(config):
    return os.path.join(infrastructure_base_path(config), ".continuum")


def runtime_logs_dir(config):
    return os.path.join(continuum_home(config), "logs")


def network_validation_logs_dir(config):
    return os.path.join(runtime_logs_dir(config), "network_validation")


def benchmark_pipeline(config):
    pipeline = _nested_value(config, "domains", "benchmark", "pipeline", default=None)
    if not isinstance(pipeline, list):
        raise ValueError("Missing required config path domains.benchmark.pipeline")
    if not pipeline:
        raise ValueError("domains.benchmark.pipeline must be a non-empty list")

    stage_ids = set()
    for index, stage in enumerate(pipeline):
        stage_path = "domains.benchmark.pipeline[%s]" % (index,)
        _require_mapping(stage, stage_path)
        stage_id = _require_non_empty_string(stage.get("id"), "%s.id" % (stage_path,))
        if stage_id in stage_ids:
            raise ValueError(
                "Invalid config path %s.id: duplicate benchmark stage id '%s'"
                % (stage_path, stage_id)
            )
        stage_ids.add(stage_id)
        _require_non_empty_string(stage.get("type"), "%s.type" % (stage_path,))
        _require_mapping(stage.get("config"), "%s.config" % (stage_path,))
    return pipeline


def _benchmark_stage_with_index(config, stage_id):
    if not isinstance(stage_id, str) or not stage_id:
        raise ValueError("benchmark stage id must be a non-empty string")
    for index, stage in enumerate(benchmark_pipeline(config)):
        if stage["id"] == stage_id:
            return index, stage
    raise ValueError("Missing benchmark stage '%s' in domains.benchmark.pipeline" % (stage_id))


def benchmark_stage(config, stage_id):
    return _benchmark_stage_with_index(config, stage_id)[1]


def benchmark_stage_ids(config):
    return [stage["id"] for stage in benchmark_pipeline(config)]


def benchmark_primary_stage(config):
    return benchmark_pipeline(config)[0]


def benchmark_primary_stage_type(config):
    return benchmark_primary_stage(config)["type"]


def planner_snapshot(config):
    snapshot = config.get("planner_snapshot")
    if snapshot is None:
        raise ValueError("Missing required config path planner_snapshot")
    return _require_mapping(snapshot, "planner_snapshot")


def _planner_assignment_list(config, key):
    assignments = planner_snapshot(config).get(key)
    if assignments is None:
        raise ValueError("Missing required config path planner_snapshot.%s" % (key,))
    return _require_list(assignments, "planner_snapshot.%s" % (key,))


def _validate_resolved_resource(resource, path):
    _require_mapping(resource, path)
    vm_id = resource.get("vm_id")
    if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
        raise ValueError("Invalid config path %s.vm_id: expected integer >= 1" % (path,))
    cluster_id = _require_non_empty_string(resource.get("cluster_id"), "%s.cluster_id" % (path,))
    tier = _require_non_empty_string(resource.get("tier"), "%s.tier" % (path,))
    index_in_cluster = resource.get("index_in_cluster")
    if (
        not isinstance(index_in_cluster, int)
        or isinstance(index_in_cluster, bool)
        or index_in_cluster < 0
    ):
        raise ValueError(
            "Invalid config path %s.index_in_cluster: expected integer >= 0" % (path,)
        )
    tags = _require_mapping(resource.get("tags"), "%s.tags" % (path,))
    if tags.get("cluster") != cluster_id:
        raise ValueError(
            "Invalid config path %s.tags.cluster: must match %s.cluster_id" % (path, path)
        )
    if tags.get("tier") != tier:
        raise ValueError(
            "Invalid config path %s.tags.tier: must match %s.tier" % (path, path)
        )
    return resource


def _normalized_resources_by_vm_id(config):
    normalized = _require_mapping(config.get("normalized"), "normalized")
    infrastructure = _require_mapping(
        normalized.get("infrastructure"),
        "normalized.infrastructure",
    )
    resources = _require_list(
        infrastructure.get("resources"),
        "normalized.infrastructure.resources",
    )

    resources_by_vm_id = {}
    for index, resource in enumerate(resources):
        path = "normalized.infrastructure.resources[%s]" % (index,)
        _validate_resolved_resource(resource, path)
        vm_id = resource["vm_id"]
        if vm_id in resources_by_vm_id:
            raise ValueError(
                "Invalid config path %s.vm_id: duplicate vm_id '%s'" % (path, vm_id)
            )
        resources_by_vm_id[vm_id] = resource
    return resources_by_vm_id


def _resources_for_resolved_vm_ids(resolved_vm_ids, resources_by_vm_id, owner_path):
    _require_list(resolved_vm_ids, "%s.resolved_vm_ids" % (owner_path,))
    if not resolved_vm_ids:
        raise ValueError(
            "Invalid config path %s.resolved_vm_ids: expected non-empty list" % (owner_path,)
        )

    resources = []
    for index, vm_id in enumerate(resolved_vm_ids):
        if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
            raise ValueError(
                "Invalid config path %s.resolved_vm_ids[%s]: expected integer >= 1"
                % (owner_path, index)
            )
        if vm_id not in resources_by_vm_id:
            raise ValueError(
                "Resolved vm_id %s for %s is missing from normalized.infrastructure.resources"
                % (vm_id, owner_path)
            )
        resources.append(resources_by_vm_id[vm_id])
    return resources


def _validate_planner_assignment(assignment, index, assignment_key, require_tags=False):
    path = "planner_snapshot.%s[%s]" % (assignment_key, index)
    _require_mapping(assignment, path)
    _require_non_empty_string(assignment.get("id"), "%s.id" % (path,))
    _require_non_empty_string(assignment.get("type"), "%s.type" % (path,))
    _require_non_empty_string(assignment.get("selector_id"), "%s.selector_id" % (path,))

    resolved_vm_ids = _require_list(
        assignment.get("resolved_vm_ids"),
        "%s.resolved_vm_ids" % (path,),
    )
    if not resolved_vm_ids:
        raise ValueError(
            "Invalid config path %s.resolved_vm_ids: expected non-empty list" % (path,)
        )
    for vm_index, vm_id in enumerate(resolved_vm_ids):
        if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
            raise ValueError(
                "Invalid config path %s.resolved_vm_ids[%s]: expected integer >= 1"
                % (path, vm_index)
            )

    resources = _require_list(
        assignment.get("resolved_resources"),
        "%s.resolved_resources" % (path,),
    )
    if len(resources) != len(resolved_vm_ids):
        raise ValueError(
            "Invalid config path %s.resolved_resources: length must match resolved_vm_ids" % (path,)
        )
    for resource_index, resource in enumerate(resources):
        validated_resource = _validate_resolved_resource(
            resource,
            "%s.resolved_resources[%s]" % (path, resource_index),
        )
        if validated_resource["vm_id"] != resolved_vm_ids[resource_index]:
            raise ValueError(
                "Invalid config path %s.resolved_resources[%s].vm_id: must match "
                "%s.resolved_vm_ids[%s]"
                % (path, resource_index, path, resource_index)
            )

    scope_identities = _require_list(
        assignment.get("scope_identities"),
        "%s.scope_identities" % (path,),
    )
    if not scope_identities:
        raise ValueError(
            "Invalid config path %s.scope_identities: expected non-empty list" % (path,)
        )
    selector_resolution.validate_scope_identities(
        scope_identities,
        "config",
        "%s.scope_identities" % (path,),
    )

    if require_tags:
        _require_mapping(assignment.get("tags"), "%s.tags" % (path,))
    return assignment


def _validate_benchmark_assignment(assignment, index):
    return _validate_planner_assignment(
        assignment,
        index,
        "benchmark_stage_assignments",
        require_tags=True,
    )


def _validate_software_assignment(assignment, index):
    return _validate_planner_assignment(assignment, index, "software_module_assignments")


def benchmark_stage_assignment(config, stage_id=None):
    stage = _benchmark_stage_for_param(config, stage_id)
    expected_stage_id = stage["id"]
    expected_stage_type = stage["type"]

    matches = []
    assignments = _planner_assignment_list(config, "benchmark_stage_assignments")
    for index, assignment in enumerate(assignments):
        validated = _validate_benchmark_assignment(assignment, index)
        if validated["id"] == expected_stage_id:
            matches.append(validated)

    if not matches:
        raise ValueError(
            "Missing planner assignment for benchmark stage '%s' in "
            "planner_snapshot.benchmark_stage_assignments" % (expected_stage_id,)
        )
    if len(matches) > 1:
        raise ValueError(
            "Multiple planner assignments for benchmark stage '%s' in "
            "planner_snapshot.benchmark_stage_assignments" % (expected_stage_id,)
        )
    assignment = matches[0]
    if assignment["type"] != expected_stage_type:
        raise ValueError(
            "planner_snapshot.benchmark_stage_assignments[id=%s].type must match "
            "domains.benchmark.pipeline type '%s'" % (expected_stage_id, expected_stage_type)
        )
    return assignment


def benchmark_stage_resolved_resources(config, stage_id=None, tier=None):
    if tier is not None:
        tier = _require_non_empty_string(tier, "tier")
    resources = benchmark_stage_assignment(config, stage_id=stage_id)["resolved_resources"]
    if tier is None:
        return resources
    return [resource for resource in resources if resource["tier"] == tier]


def benchmark_stage_resolved_resource_count(config, tier=None, stage_id=None):
    return len(benchmark_stage_resolved_resources(config, stage_id=stage_id, tier=tier))


def _resource_counts_by_tier(resources):
    counts = {}
    for resource in resources:
        tier = resource["tier"]
        counts[tier] = counts.get(tier, 0) + 1
    return {tier: counts[tier] for tier in sorted(counts)}


def benchmark_stage_handoff(config, stage_id=None):
    if stage_id is None:
        stage_index = 0
        stage = benchmark_primary_stage(config)
    else:
        stage_index, stage = _benchmark_stage_with_index(config, stage_id)
    assignment = benchmark_stage_assignment(config, stage_id=stage_id)
    resources = assignment["resolved_resources"]
    return {
        "id": assignment["id"],
        "type": assignment["type"],
        "pipeline_index": stage_index,
        "selector_id": assignment["selector_id"],
        "config": deepcopy(stage["config"]),
        "resolved_vm_ids": list(assignment["resolved_vm_ids"]),
        "resolved_resources": deepcopy(resources),
        "scope_identities": deepcopy(assignment["scope_identities"]),
        "tags": deepcopy(assignment["tags"]),
        "resource_counts_by_tier": _resource_counts_by_tier(resources),
    }


def benchmark_stage_handoffs(config):
    return [
        benchmark_stage_handoff(config, stage_id=stage["id"])
        for stage in benchmark_pipeline(config)
    ]


def _benchmark_stage_for_param(config, stage_id):
    if stage_id is None:
        return benchmark_primary_stage(config)
    return benchmark_stage(config, stage_id)


def _benchmark_param_path(key, stage_id):
    if stage_id is None:
        return "domains.benchmark.pipeline[0].config.%s" % (key,)
    return "domains.benchmark.pipeline[id=%s].config.%s" % (stage_id, key)


def benchmark_param(config, key, stage_id=None):
    stage = _benchmark_stage_for_param(config, stage_id)
    stage_config = _require_mapping(
        stage.get("config"),
        _benchmark_param_path(key, stage_id).rsplit(".", 1)[0],
    )
    if key not in stage_config:
        raise ValueError("Missing required config path %s" % (_benchmark_param_path(key, stage_id),))
    return stage_config[key]


def benchmark_param_int(config, key, stage_id=None):
    value = benchmark_param(config, key, stage_id=stage_id)
    path = _benchmark_param_path(key, stage_id)
    if isinstance(value, bool):
        raise ValueError("Invalid integer value for %s" % (path,))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid integer value for %s: %r" % (path, value)) from exc


def benchmark_param_float(config, key, stage_id=None):
    value = benchmark_param(config, key, stage_id=stage_id)
    path = _benchmark_param_path(key, stage_id)
    if isinstance(value, bool):
        raise ValueError("Invalid float value for %s" % (path,))
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid float value for %s: %r" % (path, value)) from exc


def software_modules(config):
    modules = _nested_value(config, "domains", "software", "modules", default=None)
    if not isinstance(modules, list):
        raise ValueError("Missing required config path domains.software.modules")

    module_ids = set()
    for index, module in enumerate(modules):
        module_path = "domains.software.modules[%s]" % (index,)
        _require_mapping(module, module_path)
        module_id = _require_non_empty_string(module.get("id"), "%s.id" % (module_path,))
        if module_id in module_ids:
            raise ValueError(
                "Invalid config path %s.id: duplicate module id '%s'"
                % (module_path, module_id)
            )
        module_ids.add(module_id)
        _require_non_empty_string(module.get("type"), "%s.type" % (module_path,))
        _require_mapping(module.get("config"), "%s.config" % (module_path,))
    return modules


def software_addons(config):
    modules = software_modules(config)
    addons = []
    for module in modules:
        module_type = module["type"]
        if module_type not in _ADDON_MODULE_TYPES:
            continue
        addons.append(
            {
                "name": module_type,
                "config": module["config"],
            }
        )
    return addons


def _software_module_with_index(config, module_type):
    if not isinstance(module_type, str) or not module_type.strip():
        raise ValueError("software module type must be a non-empty string")

    normalized_type = module_type.strip()
    matches = [
        (index, module)
        for index, module in enumerate(software_modules(config))
        if module.get("type") == normalized_type
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            "Multiple software modules found for type '%s' in domains.software.modules"
            % (normalized_type,)
        )
    raise ValueError(
        "Missing software module type '%s' in domains.software.modules" % (normalized_type,)
    )


def _software_module_with_index_by_id(config, module_id):
    if not isinstance(module_id, str) or not module_id.strip():
        raise ValueError("software module id must be a non-empty string")

    normalized_id = module_id.strip()
    for index, module in enumerate(software_modules(config)):
        if module["id"] == normalized_id:
            return index, module
    raise ValueError(
        "Missing software module id '%s' in domains.software.modules" % (normalized_id,)
    )


def software_module_by_type(config, module_type):
    return _software_module_with_index(config, module_type)[1]


def software_module_by_id(config, module_id):
    return _software_module_with_index_by_id(config, module_id)[1]


def software_module_resolved_resources(config, module_type, tier=None):
    module = software_module_by_type(config, module_type)
    resources = _resources_for_resolved_vm_ids(
        module.get("resolved_vm_ids"),
        _normalized_resources_by_vm_id(config),
        "domains.software.modules[id=%s]" % (module["id"],),
    )
    if tier is None:
        return resources
    normalized_tier = _require_non_empty_string(tier, "tier")
    return [resource for resource in resources if resource["tier"] == normalized_tier]


def software_module_resolved_resource_count(config, module_type, tier=None):
    return len(software_module_resolved_resources(config, module_type, tier=tier))


def _software_module_assignment_for_module(config, module):
    expected_module_id = module["id"]
    expected_module_type = module["type"]

    matches = []
    assignments = _planner_assignment_list(config, "software_module_assignments")
    for index, assignment in enumerate(assignments):
        validated = _validate_software_assignment(assignment, index)
        if validated["id"] == expected_module_id:
            matches.append(validated)

    if not matches:
        raise ValueError(
            "Missing planner assignment for software module '%s' in "
            "planner_snapshot.software_module_assignments" % (expected_module_id,)
        )
    if len(matches) > 1:
        raise ValueError(
            "Multiple planner assignments for software module '%s' in "
            "planner_snapshot.software_module_assignments" % (expected_module_id,)
        )
    assignment = matches[0]
    if assignment["type"] != expected_module_type:
        raise ValueError(
            "planner_snapshot.software_module_assignments[id=%s].type must match "
            "domains.software.modules type '%s'" % (expected_module_id, expected_module_type)
        )
    return assignment


def software_module_assignment(config, module_type):
    module = software_module_by_type(config, module_type)
    return _software_module_assignment_for_module(config, module)


def software_module_assignment_by_id(config, module_id):
    module = software_module_by_id(config, module_id)
    return _software_module_assignment_for_module(config, module)


def software_module_assignment_resolved_resources(config, module_type, tier=None):
    if tier is not None:
        tier = _require_non_empty_string(tier, "tier")
    resources = software_module_assignment(config, module_type)["resolved_resources"]
    if tier is None:
        return resources
    return [resource for resource in resources if resource["tier"] == tier]


def software_module_assignment_resolved_resource_count(config, module_type, tier=None):
    return len(
        software_module_assignment_resolved_resources(config, module_type, tier=tier)
    )


def _software_module_assignment_handoff(config, module_index, module):
    assignment = _software_module_assignment_for_module(config, module)
    resources = assignment["resolved_resources"]
    return {
        "id": assignment["id"],
        "type": assignment["type"],
        "module_index": module_index,
        "selector_id": assignment["selector_id"],
        "config": deepcopy(module["config"]),
        "resolved_vm_ids": list(assignment["resolved_vm_ids"]),
        "resolved_resources": deepcopy(resources),
        "scope_identities": deepcopy(assignment["scope_identities"]),
        "resource_counts_by_tier": _resource_counts_by_tier(resources),
    }


def software_module_assignment_handoff(config, module_type):
    module_index, module = _software_module_with_index(config, module_type)
    return _software_module_assignment_handoff(config, module_index, module)


def software_module_assignment_handoff_by_id(config, module_id):
    module_index, module = _software_module_with_index_by_id(config, module_id)
    return _software_module_assignment_handoff(config, module_index, module)


def software_module_assignment_handoffs(config):
    return [
        _software_module_assignment_handoff(config, module_index, module)
        for module_index, module in enumerate(software_modules(config))
    ]


def planner_runtime_handoff(config):
    return {
        "software_modules": software_module_assignment_handoffs(config),
        "benchmark_stages": benchmark_stage_handoffs(config),
    }


def orchestrator_module_index(config):
    modules = software_modules(config)
    orchestrator_indices = [
        index
        for index, module in enumerate(modules)
        if module["type"] in _ORCHESTRATOR_MODULE_TYPES
    ]
    if len(orchestrator_indices) == 1:
        return orchestrator_indices[0]
    if len(orchestrator_indices) > 1:
        raise ValueError("Multiple orchestrator modules found in domains.software.modules")
    raise ValueError("Missing required orchestrator module in domains.software.modules")


def orchestrator_module(config):
    modules = software_modules(config)
    return modules[orchestrator_module_index(config)]


def has_addon(config, addon_name):
    return any(addon["name"] == addon_name for addon in software_addons(config))


def orchestrator_name(config):
    return orchestrator_module(config)["type"]


def orchestrator_value(config, key):
    orch_module = orchestrator_module(config)
    orch_cfg = orch_module["config"]
    if key not in orch_cfg:
        raise ValueError("Missing required orchestrator config key '%s'" % (key,))
    return orch_cfg[key]


def orchestrator_value_optional(config, key, default=None):
    orch_module = orchestrator_module(config)
    orch_cfg = orch_module["config"]
    return orch_cfg.get(key, default)


def orchestrator_bool(config, key):
    value = orchestrator_value(config, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        raise ValueError("Invalid boolean value for orchestrator config key '%s': %r" % (key, value))
    raise ValueError("Invalid boolean value for orchestrator config key '%s': %r" % (key, value))


def orchestrator_bool_optional(config, key, default=False):
    value = orchestrator_value_optional(config, key, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        raise ValueError("Invalid boolean value for orchestrator config key '%s': %r" % (key, value))
    raise ValueError("Invalid boolean value for orchestrator config key '%s': %r" % (key, value))


def orchestrator_overrides(config, keys):
    """Return selected orchestrator config keys from canonical domain config."""
    orch_module = orchestrator_module(config)
    orch_cfg = orch_module["config"]

    values = {}
    for key in keys:
        if key in orch_cfg:
            values[key] = orch_cfg[key]
    return values
