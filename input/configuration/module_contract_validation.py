"""Shared module capability and contract validation helpers."""

from __future__ import annotations

from . import module_registry, selector_scope


def module_identity(module_entry: dict) -> tuple[str, str]:
    """Return stable `(module_id, module_type)` tuple for diagnostics."""
    module_type = str(module_entry.get("type") or "unknown")
    module_id = str(module_entry.get("id") or module_type)
    return module_id, module_type


def _scope_overlap(
    first_module: dict,
    second_module: dict,
    treat_missing_scope_as_global: bool = False,
) -> tuple[bool, dict | None]:
    """Return overlap flag and first deterministic overlapping scope identity."""
    first_scope = first_module.get("scope_identities")
    second_scope = second_module.get("scope_identities")
    if (
        not isinstance(first_scope, list)
        or not isinstance(second_scope, list)
        or not first_scope
        or not second_scope
    ):
        if treat_missing_scope_as_global:
            return True, None
        return False, None

    scope_identity = selector_scope.first_overlap_scope_identity(first_scope, second_scope)
    return scope_identity is not None, scope_identity


def _collect_capability_providers(modules: list[dict]):
    module_records = []
    capability_providers = {}
    exclusive_capability_providers = {}

    for index, module in enumerate(modules):
        module_type = module.get("type")
        if not isinstance(module_type, str):
            continue
        spec = module_registry.get_spec(module_type)
        if spec is None:
            continue
        record = (index, module, spec)
        module_records.append(record)
        for capability in spec.provides:
            capability_providers.setdefault(capability, []).append(record)
        for capability in spec.exclusive_provides:
            capability_providers.setdefault(capability, []).append(record)
            exclusive_capability_providers.setdefault(capability, []).append(record)

    return module_records, capability_providers, exclusive_capability_providers


def _resolved_vm_id_set(module: dict) -> set[int]:
    resolved_vm_ids = module.get("resolved_vm_ids")
    if not isinstance(resolved_vm_ids, list):
        return set()
    return {
        vm_id
        for vm_id in resolved_vm_ids
        if isinstance(vm_id, int) and not isinstance(vm_id, bool) and vm_id > 0
    }


def evaluate_module_contracts(
    modules: list[dict],
    run_targets: set[str],
    require_endpoint_runtime: bool,
    treat_missing_scope_as_global: bool = False,
    endpoint_resource_vm_ids: set[int] | None = None,
) -> dict:
    """Evaluate shared module contract violations.

    Returns:
        dict: {
            "module_records": list[(index, module, spec)],
            "provided_capabilities": set[str],
            "violations": list[dict],
        }
    """
    (
        module_records,
        capability_providers,
        exclusive_capability_providers,
    ) = _collect_capability_providers(modules)
    provided_capabilities = set(capability_providers.keys())

    violations = []

    for capability, providers in exclusive_capability_providers.items():
        if len(providers) < 2:
            continue
        for provider_index in range(len(providers) - 1):
            left_index, left_module, _left_spec = providers[provider_index]
            for right_index in range(provider_index + 1, len(providers)):
                index, module, _spec = providers[right_index]
                overlaps, scope_identity = _scope_overlap(
                    left_module,
                    module,
                    treat_missing_scope_as_global=treat_missing_scope_as_global,
                )
                if not overlaps:
                    continue
                violations.append(
                    {
                        "kind": "exclusive",
                        "capability": capability,
                        "module_index": index,
                        "module": module,
                        "other_module_index": left_index,
                        "other_module": left_module,
                        "scope_identity": scope_identity,
                    }
                )

    for index, module, spec in module_records:
        for requirement in spec.requires:
            providers = capability_providers.get(requirement, [])
            if not providers:
                violations.append(
                    {
                        "kind": "requires",
                        "required_capability": requirement,
                        "module_index": index,
                        "module": module,
                    }
                )
                continue
            if any(
                _scope_overlap(
                    module,
                    provider_module,
                    treat_missing_scope_as_global=treat_missing_scope_as_global,
                )[0]
                for _provider_index, provider_module, _provider_spec in providers
            ):
                continue
            violations.append(
                {
                    "kind": "requires_scope",
                    "required_capability": requirement,
                    "module_index": index,
                    "module": module,
                    "provider_modules": [
                        provider_module for _idx, provider_module, _spec in providers
                    ],
                }
            )

        for conflict_capability in spec.conflicts:
            providers = capability_providers.get(conflict_capability, [])
            for provider_index, provider_module, _provider_spec in providers:
                if provider_index == index:
                    continue
                overlaps, scope_identity = _scope_overlap(
                    module,
                    provider_module,
                    treat_missing_scope_as_global=treat_missing_scope_as_global,
                )
                if not overlaps:
                    continue
                violations.append(
                    {
                        "kind": "conflict",
                        "conflict_capability": conflict_capability,
                        "module_index": index,
                        "module": module,
                        "provider_module_index": provider_index,
                        "provider_module": provider_module,
                        "scope_identity": scope_identity,
                    }
                )

    if ("software" in run_targets or "application" in run_targets) and require_endpoint_runtime:
        endpoint_runtime_providers = capability_providers.get("capability.endpoint_runtime", [])
        if not endpoint_runtime_providers:
            violations.append({"kind": "endpoint_runtime_missing"})
        elif endpoint_resource_vm_ids is not None and endpoint_resource_vm_ids:
            if not any(
                _resolved_vm_id_set(provider_module) & endpoint_resource_vm_ids
                for _index, provider_module, _spec in endpoint_runtime_providers
            ):
                index, module, _spec = endpoint_runtime_providers[0]
                violations.append(
                    {
                        "kind": "endpoint_runtime_not_on_endpoint",
                        "module_index": index,
                        "module": module,
                    }
                )

    return {
        "module_records": module_records,
        "provided_capabilities": provided_capabilities,
        "violations": violations,
    }
