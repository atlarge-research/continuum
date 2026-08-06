"""Software domain validation helpers."""

from __future__ import annotations

import copy
from pathlib import Path

from . import module_contract_validation, module_registry, selector_resolution, validation_utils

_fail = validation_utils.fail
_fail_unknown_keys = validation_utils.fail_unknown_keys
_is_int = validation_utils.is_int

_ORCHESTRATOR_MODULE_TYPES = module_registry.ORCHESTRATOR_MODULE_TYPES
_ADDON_MODULE_TYPES = module_registry.ADDON_MODULE_TYPES
_SUPPORTED_MODULE_TYPES = set(module_registry.SUPPORTED_MODULE_TYPES)
_RESERVED_MODULE_DEPENDENCY_KEYS = (
    "depends_on",
    "dependencies",
    "requires",
    "provides",
    "exclusive_provides",
    "conflicts",
)
_REQUIRES_ERROR_OVERRIDES = {
    ("openfaas", "orchestrator.kubernetes"): "openfaas module requires orchestrator type kubernetes",
    (
        "observability",
        "capability.observability_host",
    ): "observability module requires orchestrator with observability support",
}


def runtime_software_projection(
    modules: list[dict],
    path: Path,
    prefix: str,
) -> tuple[dict, list[dict]]:
    orchestrator_modules = []
    addon_modules = []
    addon_types_seen = set()

    for index, module in enumerate(modules):
        module_type = module["type"]
        if module_type in _ORCHESTRATOR_MODULE_TYPES:
            orchestrator_modules.append((index, module))
        elif module_type in _ADDON_MODULE_TYPES:
            if module_type in addon_types_seen:
                _fail(
                    path,
                    "%s.modules[%s].type" % (prefix, index),
                    "duplicate addon module type '%s'" % (module_type),
                )
            addon_types_seen.add(module_type)
            addon_modules.append((index, module))

    if len(orchestrator_modules) != 1:
        _fail(
            path,
            "%s.modules" % (prefix),
            "must contain exactly one orchestrator module (allowed: %s)"
            % (", ".join(_ORCHESTRATOR_MODULE_TYPES)),
        )

    orchestrator_index, orchestrator_module = orchestrator_modules[0]
    orchestrator_config = orchestrator_module.get("config")
    if not isinstance(orchestrator_config, dict):
        _fail(
            path,
            "%s.modules[%s].config" % (prefix, orchestrator_index),
            "must be a mapping",
        )
    orchestrator = {
        "name": orchestrator_module["type"],
        "config": copy.deepcopy(orchestrator_config),
        "module_id": orchestrator_module["id"],
        "selector_id": orchestrator_module["selector_id"],
    }

    addons = []
    for addon_index, addon_module in addon_modules:
        addon_config = addon_module.get("config")
        if not isinstance(addon_config, dict):
            _fail(
                path,
                "%s.modules[%s].config" % (prefix, addon_index),
                "must be a mapping",
            )
        addons.append(
            {
                "name": addon_module["type"],
                "config": copy.deepcopy(addon_config),
                "module_id": addon_module["id"],
                "selector_id": addon_module["selector_id"],
                "index": addon_index,
            }
        )
    addons.sort(key=lambda item: item["index"])
    return orchestrator, addons


def validate_module_registry_contract(
    modules: list[dict],
    run_targets: set[str],
    require_endpoint_runtime: bool,
    path: Path,
    prefix: str,
    endpoint_resource_vm_ids: set[int] | None = None,
):
    evaluation = module_contract_validation.evaluate_module_contracts(
        modules,
        run_targets,
        require_endpoint_runtime,
        treat_missing_scope_as_global=False,
        endpoint_resource_vm_ids=endpoint_resource_vm_ids,
    )
    module_records = evaluation["module_records"]

    def _assignment_path(module_index):
        module = modules[module_index]
        assign_to = module.get("assign_to")
        suffix = (
            "assign_to.match"
            if isinstance(assign_to, dict) and "match" in assign_to
            else "assign_to"
        )
        return "%s.modules[%s].%s" % (prefix, module_index, suffix)

    for index, module, spec in module_records:
        module_type = module["type"]
        module_config = module.get("config")
        if not isinstance(module_config, dict):
            _fail(path, "%s.modules[%s].config" % (prefix, index), "must be a mapping")

        if spec.scope == "addon":
            allowed_addon_keys = set(spec.allowed_config_keys)
            unknown_keys = sorted(key for key in module_config.keys() if key not in allowed_addon_keys)
            if unknown_keys:
                _fail(
                    path,
                    "%s.modules[%s].config" % (prefix, index),
                    "unknown config key(s) for addon type '%s': %s"
                    % (module_type, ", ".join(unknown_keys)),
                )

    for violation in evaluation["violations"]:
        kind = violation.get("kind")
        if kind == "exclusive":
            module = violation["module"]
            left_module = violation["other_module"]
            scope_identity = violation["scope_identity"]
            _fail(
                path,
                "%s.modules[%s].type" % (prefix, violation["module_index"]),
                "module type '%s' conflicts: capability '%s' is exclusive and already provided by "
                "module '%s' in scope %s"
                % (
                    module["type"],
                    violation["capability"],
                    left_module["id"],
                    selector_resolution.scope_identity_repr(scope_identity),
                ),
            )
            continue

        if kind == "requires":
            module = violation["module"]
            module_type = module["type"]
            required_capability = violation["required_capability"]
            message = _REQUIRES_ERROR_OVERRIDES.get((module_type, required_capability))
            if message is None:
                message = "module type '%s' requires capability '%s'" % (
                    module_type,
                    required_capability,
                )
            _fail(path, "%s.modules[%s].type" % (prefix, violation["module_index"]), message)
            continue

        if kind == "requires_scope":
            module = violation["module"]
            module_type = module["type"]
            required_capability = violation["required_capability"]
            message = _REQUIRES_ERROR_OVERRIDES.get((module_type, required_capability))
            if message is None:
                message = "module type '%s' requires capability '%s'" % (
                    module_type,
                    required_capability,
                )
            _fail(
                path,
                _assignment_path(violation["module_index"]),
                "%s in an overlapping assignment scope" % (message,),
            )
            continue

        if kind == "conflict":
            module = violation["module"]
            provider_module = violation["provider_module"]
            _fail(
                path,
                "%s.modules[%s].type" % (prefix, violation["module_index"]),
                "module type '%s' conflicts with module '%s' via capability '%s' in scope %s"
                % (
                    module["type"],
                    provider_module["id"],
                    violation["conflict_capability"],
                    selector_resolution.scope_identity_repr(violation["scope_identity"]),
                ),
            )
            continue

        if kind == "endpoint_runtime_missing":
            _fail(
                path,
                "%s.modules" % (prefix),
                "run.targets including software/application with endpoint resources requires "
                "endpoint_runtime module",
            )
            continue

        if kind == "endpoint_runtime_not_on_endpoint":
            _fail(
                path,
                _assignment_path(violation["module_index"]),
                "endpoint_runtime module must be assigned to endpoint resources when endpoint "
                "resources are present",
            )


def validate_software(
    software: dict,
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
):
    if not isinstance(software, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, software, {"modules"})

    modules = software.get("modules")
    if not isinstance(modules, list) or not modules:
        _fail(path, "%s.modules" % (prefix), "must be a non-empty list")

    normalized_modules = []
    module_ids = set()
    base_keys = {"id", "type", "assign_to", "config"}
    reserved_dependency_keys = set(_RESERVED_MODULE_DEPENDENCY_KEYS)
    derived_keys = (
        {
            "selector",
            "selector_id",
            "resolved_vm_ids",
            "scope_identities",
        }
        if allow_derived
        else set()
    )

    for index, module in enumerate(modules):
        module_prefix = "%s.modules[%s]" % (prefix, index)
        if not isinstance(module, dict):
            _fail(path, module_prefix, "must be a mapping")
        _fail_unknown_keys(
            path,
            module_prefix,
            module,
            base_keys | derived_keys | reserved_dependency_keys,
        )

        for dependency_key in _RESERVED_MODULE_DEPENDENCY_KEYS:
            if dependency_key in module:
                _fail(
                    path,
                    "%s.%s" % (module_prefix, dependency_key),
                    "dependency edges are not allowed in user schema",
                )

        module_id = module.get("id")
        if not isinstance(module_id, str) or not module_id.strip():
            _fail(path, "%s.id" % (module_prefix), "must be a non-empty string")
        module_id = module_id.strip()
        if module_id in module_ids:
            _fail(path, "%s.id" % (module_prefix), "duplicate module id '%s'" % (module_id))
        module_ids.add(module_id)

        module_type = module.get("type")
        if not isinstance(module_type, str) or not module_type.strip():
            _fail(path, "%s.type" % (module_prefix), "must be a non-empty string")
        module_type = module_type.strip()
        if module_type not in _SUPPORTED_MODULE_TYPES:
            _fail(
                path,
                "%s.type" % (module_prefix),
                "unknown module type '%s' (supported: %s)"
                % (module_type, ", ".join(sorted(_SUPPORTED_MODULE_TYPES))),
            )

        assign_to, canonical_selector, selector_id = selector_resolution.validate_assign_to(
            module.get("assign_to"),
            path,
            "%s.assign_to" % (module_prefix),
            allow_any_of=True,
        )
        if allow_derived:
            if require_derived:
                for derived_key in (
                    "selector",
                    "selector_id",
                    "resolved_vm_ids",
                    "scope_identities",
                ):
                    if derived_key not in module:
                        _fail(
                            path,
                            "%s.%s" % (module_prefix, derived_key),
                            "is required in normalized lock config",
                        )
            selector_resolution.validate_selector_derivatives(
                module,
                canonical_selector,
                selector_id,
                path,
                "%s.selector" % (module_prefix),
                "%s.selector_id" % (module_prefix),
                require_present=require_derived,
            )

        if "config" not in module:
            _fail(path, "%s.config" % (module_prefix), "is required")
        config = module.get("config")
        if not isinstance(config, dict):
            _fail(path, "%s.config" % (module_prefix), "must be a mapping")

        resolved_vm_ids = None
        if allow_derived and "resolved_vm_ids" in module:
            resolved_vm_ids = module.get("resolved_vm_ids")
            if not isinstance(resolved_vm_ids, list) or not all(
                _is_int(vm_id) and vm_id > 0 for vm_id in resolved_vm_ids
            ):
                _fail(path, "%s.resolved_vm_ids" % (module_prefix), "must be a list of vm_id integers")

        scope_identities = None
        if allow_derived and "scope_identities" in module:
            scope_identities = module.get("scope_identities")
            selector_resolution.validate_scope_identities(
                scope_identities,
                path,
                "%s.scope_identities" % (module_prefix),
            )

        normalized_module = {
            "id": module_id,
            "type": module_type,
            "assign_to": assign_to,
            "config": config,
            "selector": canonical_selector,
            "selector_id": selector_id,
        }
        if allow_derived and "resolved_vm_ids" in module:
            normalized_module["resolved_vm_ids"] = resolved_vm_ids
        if allow_derived and "scope_identities" in module:
            normalized_module["scope_identities"] = scope_identities
        normalized_modules.append(normalized_module)

    runtime_software_projection(normalized_modules, path, prefix)
    software["modules"] = normalized_modules
