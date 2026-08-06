"""Selector-resolution reconciliation helpers for derived metadata."""

from __future__ import annotations

import json

from . import selector_scope


def _required_mapping(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Invalid selector-assignment %s: expected mapping" % (path,))
    return value


def _required_non_empty_string(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid selector-assignment %s: expected non-empty string" % (path,))
    return value.strip()


def reconcile_assignment(
    entity: dict, resources: list[dict], resources_by_vm_id: dict[int, dict]
) -> dict:
    """Resolve selector assignment and compare against existing derived metadata."""
    entity_mapping = _required_mapping(entity, "entity")
    assign_to = _required_mapping(entity_mapping.get("assign_to"), "entity.assign_to")
    if "match" in assign_to:
        matches = [_required_mapping(assign_to.get("match"), "entity.assign_to.match")]
    else:
        any_of = assign_to.get("any_of")
        if not isinstance(any_of, list) or not any_of:
            raise ValueError(
                "Invalid selector-assignment entity.assign_to.any_of: expected non-empty list"
            )
        matches = [
            _required_mapping(match, "entity.assign_to.any_of[%s]" % (index,))
            for index, match in enumerate(any_of)
        ]

    for index, match in enumerate(matches):
        clause_path = (
            "entity.assign_to.match"
            if "match" in assign_to
            else "entity.assign_to.any_of[%s]" % (index,)
        )
        if not match:
            raise ValueError(
                "Invalid selector-assignment %s: expected non-empty mapping" % (clause_path,)
            )
        for key, value in match.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(
                    "Invalid selector-assignment %s: key must be non-empty string"
                    % (clause_path,)
                )
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "Invalid selector-assignment %s.%s: expected non-empty string"
                    % (clause_path, key)
                )
    selector_id = _required_non_empty_string(
        entity_mapping.get("selector_id"), "entity.selector_id"
    )

    candidates, empty_clause_indexes = selector_scope.resolve_selector_union_vm_ids(
        resources, matches
    )
    if not candidates:
        return {
            "has_candidates": False,
            "empty_clause_indexes": empty_clause_indexes,
            "resolved_vm_ids": [],
            "scope_identities": [],
            "resolved_vm_ids_mismatch": False,
            "scope_identities_mismatch": False,
        }

    resolved_vm_ids = sorted(candidates)
    scope_identities = selector_scope.build_scope_identities(
        resources_by_vm_id,
        resolved_vm_ids,
        selector_id,
    )
    return {
        "has_candidates": True,
        "empty_clause_indexes": empty_clause_indexes,
        "resolved_vm_ids": resolved_vm_ids,
        "scope_identities": scope_identities,
        "resolved_vm_ids_mismatch": (
            "resolved_vm_ids" in entity_mapping
            and entity_mapping["resolved_vm_ids"] != resolved_vm_ids
        ),
        "scope_identities_mismatch": (
            "scope_identities" in entity_mapping
            and entity_mapping["scope_identities"] != scope_identities
        ),
    }


def scope_identity_repr(scope_identity: dict) -> str:
    """Return deterministic compact JSON string for a scope identity object."""
    return json.dumps(scope_identity, separators=(",", ":"), sort_keys=True)


def _fail(path, key_path: str, message: str):
    raise ValueError("%s: %s: %s" % (path, key_path, message))


def _fail_unknown_keys(path, key_path: str, mapping: dict, allowed: set[str]):
    for key in sorted(mapping.keys()):
        if key not in allowed:
            unknown_key_path = "%s.%s" % (key_path, key) if key_path else key
            _fail(path, unknown_key_path, "unexpected key for schema v1")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalize_match(match: dict, path, prefix: str) -> dict[str, str]:
    """Validate and normalize one exact-match selector clause."""
    if not isinstance(match, dict) or not match:
        _fail(path, prefix, "must be a non-empty mapping")

    source_keys_by_normalized_key = {}
    for key in match:
        if not isinstance(key, str) or not key.strip():
            _fail(path, prefix, "selector key must be a non-empty string")
        source_keys_by_normalized_key.setdefault(key.strip(), []).append(key)

    colliding_keys = sorted(
        normalized_key
        for normalized_key, source_keys in source_keys_by_normalized_key.items()
        if len(source_keys) > 1
    )
    if colliding_keys:
        normalized_key = colliding_keys[0]
        source_keys = ", ".join(
            repr(source_key)
            for source_key in sorted(source_keys_by_normalized_key[normalized_key])
        )
        _fail(
            path,
            prefix,
            "selector keys %s collide after trimming to normalized key '%s'"
            % (source_keys, normalized_key),
        )

    normalized_match = {}
    for key, value in match.items():
        if not isinstance(value, str) or not value.strip():
            _fail(path, "%s.%s" % (prefix, key), "selector value must be a non-empty string")
        normalized_match[key.strip()] = value.strip()
    return normalized_match


def validate_assign_to(
    assign_to: dict, path, prefix: str, *, allow_any_of: bool = False
) -> tuple[dict, dict, str]:
    """Validate and normalize selector assignment, returning canonical metadata."""
    if not isinstance(assign_to, dict):
        _fail(path, prefix, "must be a mapping")
    allowed_keys = {"match", "any_of"} if allow_any_of else {"match"}
    _fail_unknown_keys(path, prefix, assign_to, allowed_keys)

    selector_keys = [key for key in ("match", "any_of") if key in assign_to]
    if len(selector_keys) != 1:
        if allow_any_of:
            _fail(path, prefix, "must contain exactly one of match or any_of")
        _fail(path, "%s.match" % (prefix,), "must be a non-empty mapping")

    if "match" in assign_to:
        normalized_match = _normalize_match(assign_to.get("match"), path, "%s.match" % (prefix,))
        canonical_selector, selector_id = selector_scope.canonical_selector(normalized_match)
        return {"match": normalized_match}, canonical_selector, selector_id

    any_of = assign_to.get("any_of")
    if not isinstance(any_of, list) or not any_of:
        _fail(path, "%s.any_of" % (prefix,), "must be a non-empty list")

    normalized_matches = [
        _normalize_match(match, path, "%s.any_of[%s]" % (prefix, index))
        for index, match in enumerate(any_of)
    ]
    clause_sources = {}
    for index, match in enumerate(normalized_matches):
        clause_json = json.dumps(match, separators=(",", ":"), sort_keys=True)
        clause_sources.setdefault(clause_json, []).append(index)
    duplicate_clauses = sorted(
        clause_json for clause_json, indexes in clause_sources.items() if len(indexes) > 1
    )
    if duplicate_clauses:
        clause_json = duplicate_clauses[0]
        indexes = ", ".join(str(index) for index in clause_sources[clause_json])
        _fail(
            path,
            "%s.any_of" % (prefix,),
            "contains duplicate normalized selector clause at indexes %s: %s"
            % (indexes, clause_json),
        )

    canonical_selector, selector_id = selector_scope.canonical_selector_union(normalized_matches)
    return {"any_of": normalized_matches}, canonical_selector, selector_id


def validate_scope_identities(scope_identities: list, path, prefix: str):
    """Validate canonical scope identity list shape."""
    if not isinstance(scope_identities, list):
        _fail(path, prefix, "must be a list of scope identity objects")
    if not scope_identities:
        return

    selector_count = 0
    for index, scope_identity in enumerate(scope_identities):
        scope_prefix = "%s[%s]" % (prefix, index)
        if not isinstance(scope_identity, dict):
            _fail(path, scope_prefix, "must be a mapping")

        kind = scope_identity.get("kind")
        if kind == "vm":
            _fail_unknown_keys(path, scope_prefix, scope_identity, {"kind", "vm_id"})
            vm_id = scope_identity.get("vm_id")
            if not _is_int(vm_id) or vm_id < 1:
                _fail(path, "%s.vm_id" % (scope_prefix), "must be integer >= 1")
            continue

        if kind == "cluster":
            _fail_unknown_keys(path, scope_prefix, scope_identity, {"kind", "cluster_id"})
            cluster_id = scope_identity.get("cluster_id")
            if not isinstance(cluster_id, str) or not cluster_id.strip():
                _fail(path, "%s.cluster_id" % (scope_prefix), "must be a non-empty string")
            continue

        if kind == "selector":
            _fail_unknown_keys(path, scope_prefix, scope_identity, {"kind", "selector_id"})
            selector_id = scope_identity.get("selector_id")
            if not isinstance(selector_id, str) or not selector_id.strip():
                _fail(path, "%s.selector_id" % (scope_prefix), "must be a non-empty string")
            selector_count += 1
            continue

        _fail(path, "%s.kind" % (scope_prefix), "must be one of vm, cluster, selector")

    if selector_count != 1:
        _fail(path, prefix, "must include exactly one selector scope identity")


def validate_selector_derivatives(
    source_mapping: dict,
    canonical_selector: dict,
    selector_id: str,
    path,
    selector_key_path: str,
    selector_id_key_path: str,
    require_present: bool = False,
):
    """Validate optional/persisted selector and selector_id derived fields."""
    assign_to = source_mapping.get("assign_to")
    assignment_source = (
        "assign_to.match"
        if (isinstance(assign_to, dict) and "match" in assign_to)
        or (not isinstance(assign_to, dict) and "match" in canonical_selector)
        else "assign_to"
    )
    if require_present and "selector" not in source_mapping:
        _fail(path, selector_key_path, "is required in normalized lock config")
    if require_present and "selector_id" not in source_mapping:
        _fail(path, selector_id_key_path, "is required in normalized lock config")

    if "selector" in source_mapping:
        selector_value = source_mapping.get("selector")
        if not isinstance(selector_value, dict):
            _fail(path, selector_key_path, "must be a canonical selector mapping")
        if selector_value != canonical_selector:
            _fail(
                path,
                selector_key_path,
                "must match canonical selector derived from %s" % (assignment_source,),
            )

    if "selector_id" in source_mapping:
        selector_id_value = source_mapping.get("selector_id")
        if not isinstance(selector_id_value, str) or not selector_id_value.strip():
            _fail(path, selector_id_key_path, "must be a non-empty string")
        if selector_id_value.strip() != selector_id:
            _fail(
                path,
                selector_id_key_path,
                "must match canonical selector_id derived from %s" % (assignment_source,),
            )
