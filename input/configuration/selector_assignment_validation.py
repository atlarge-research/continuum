"""Selector-assignment reconciliation helpers for normalized config."""

from __future__ import annotations

import json
from pathlib import Path

from . import selector_resolution, software_domain_validation, validation_utils

_fail = validation_utils.fail
_child_key_path = validation_utils.child_key_path
_is_int = validation_utils.is_int


def _required_mapping(value, path: Path, key_path: str) -> dict:
    if not isinstance(value, dict):
        _fail(path, key_path, "must be a mapping")
    return value


def _required_list(value, path: Path, key_path: str) -> list:
    if not isinstance(value, list):
        _fail(path, key_path, "must be a list")
    return value


def validate_selector_resolution(normalized: dict, path: Path, prefix: str):
    normalized_mapping = _required_mapping(normalized, path, prefix)
    infrastructure = _required_mapping(
        normalized_mapping.get("infrastructure"),
        path,
        _child_key_path(prefix, "infrastructure"),
    )
    software = _required_mapping(
        normalized_mapping.get("software"),
        path,
        _child_key_path(prefix, "software"),
    )
    run = _required_mapping(
        normalized_mapping.get("run"),
        path,
        _child_key_path(prefix, "run"),
    )

    run_targets = set(
        _required_list(
            run.get("targets"),
            path,
            _child_key_path(prefix, "run.targets"),
        )
    )
    resources = _required_list(
        infrastructure.get("resources"),
        path,
        _child_key_path(prefix, "infrastructure.resources"),
    )
    modules = _required_list(
        software.get("modules"),
        path,
        _child_key_path(prefix, "software.modules"),
    )

    resources_by_vm_id = {}
    has_endpoint_resources = False
    endpoint_resource_vm_ids = set()
    for index, resource in enumerate(resources):
        resource_prefix = _child_key_path(prefix, "infrastructure.resources[%s]" % (index))
        if not isinstance(resource, dict):
            _fail(path, resource_prefix, "must be a mapping")
        vm_id = resource.get("vm_id")
        if not _is_int(vm_id) or vm_id < 1:
            _fail(path, "%s.vm_id" % (resource_prefix), "must be integer >= 1")
        if vm_id in resources_by_vm_id:
            _fail(path, "%s.vm_id" % (resource_prefix), "duplicate vm_id '%s'" % (vm_id))

        tags = resource.get("tags")
        if not isinstance(tags, dict):
            _fail(path, "%s.tags" % (resource_prefix), "must be a mapping")

        cluster_id = resource.get("cluster_id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            _fail(path, "%s.cluster_id" % (resource_prefix), "must be a non-empty string")

        if tags.get("tier") == "endpoint":
            has_endpoint_resources = True
            endpoint_resource_vm_ids.add(vm_id)
        resources_by_vm_id[vm_id] = resource

    software_prefix = _child_key_path(prefix, "software")
    software_domain_validation.runtime_software_projection(modules, path, software_prefix)

    for index, module in enumerate(modules):
        selector_prefix = _child_key_path(
            prefix,
            "software.modules[%s].assign_to%s"
            % (index, ".match" if "match" in module.get("assign_to", {}) else ""),
        )
        resolved_prefix = _child_key_path(prefix, "software.modules[%s].resolved_vm_ids" % (index))
        scope_prefix = _child_key_path(prefix, "software.modules[%s].scope_identities" % (index))
        assignment = selector_resolution.reconcile_assignment(module, resources, resources_by_vm_id)
        if "any_of" in module.get("assign_to", {}) and assignment["empty_clause_indexes"]:
            clause_index = assignment["empty_clause_indexes"][0]
            _fail(
                path,
                "%s.any_of[%s]" % (selector_prefix, clause_index),
                "selector clause resolves to no infrastructure resources",
            )
        if not assignment["has_candidates"]:
            _fail(path, selector_prefix, "selector resolves to no infrastructure resources")
        if assignment["resolved_vm_ids_mismatch"]:
            _fail(
                path,
                resolved_prefix,
                "must match selector resolution derived from %s"
                % (
                    "assign_to.match"
                    if "match" in module.get("assign_to", {})
                    else "assign_to",
                ),
            )
        if assignment["scope_identities_mismatch"]:
            _fail(
                path,
                scope_prefix,
                "must match scope identities derived from selector resolution",
            )
        module["resolved_vm_ids"] = assignment["resolved_vm_ids"]
        module["scope_identities"] = assignment["scope_identities"]
        if "any_of" in module.get("assign_to", {}):
            module["assign_to"]["any_of"].sort(
                key=lambda match: json.dumps(match, separators=(",", ":"), sort_keys=True)
            )

    software_domain_validation.validate_module_registry_contract(
        modules,
        run_targets,
        has_endpoint_resources,
        path,
        software_prefix,
        endpoint_resource_vm_ids=endpoint_resource_vm_ids,
    )

    pipeline = []
    if "benchmark" in normalized_mapping:
        benchmark = _required_mapping(
            normalized_mapping["benchmark"],
            path,
            _child_key_path(prefix, "benchmark"),
        )
        pipeline = _required_list(
            benchmark.get("pipeline"),
            path,
            _child_key_path(prefix, "benchmark.pipeline"),
        )
    elif "application" in run_targets:
        _fail(
            path,
            _child_key_path(prefix, "benchmark"),
            "is required when run.targets includes application",
        )

    for index, stage in enumerate(pipeline):
        selector_prefix = _child_key_path(
            prefix, "benchmark.pipeline[%s].assign_to.match" % (index)
        )
        resolved_prefix = _child_key_path(
            prefix, "benchmark.pipeline[%s].resolved_vm_ids" % (index)
        )
        scope_prefix = _child_key_path(prefix, "benchmark.pipeline[%s].scope_identities" % (index))
        assignment = selector_resolution.reconcile_assignment(stage, resources, resources_by_vm_id)
        if not assignment["has_candidates"]:
            _fail(path, selector_prefix, "selector resolves to no infrastructure resources")
        if assignment["resolved_vm_ids_mismatch"]:
            _fail(
                path,
                resolved_prefix,
                "must match selector resolution derived from assign_to.match",
            )
        if assignment["scope_identities_mismatch"]:
            _fail(
                path,
                scope_prefix,
                "must match scope identities derived from selector resolution",
            )
        stage["resolved_vm_ids"] = assignment["resolved_vm_ids"]
        stage["scope_identities"] = assignment["scope_identities"]
