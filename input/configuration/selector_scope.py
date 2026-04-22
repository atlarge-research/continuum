"""Shared selector canonicalization and scope identity helpers."""

from __future__ import annotations

import hashlib
import json


def canonical_selector(match: dict[str, str]) -> tuple[dict, str]:
    """Return canonical selector object and deterministic selector_id."""
    canonical_pairs = sorted((str(key), str(value)) for key, value in match.items())
    canonical = {"match": [[key, value] for key, value in canonical_pairs]}
    selector_json = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    selector_id = "sel_%s" % (hashlib.sha256(selector_json.encode("utf-8")).hexdigest()[:12])
    return canonical, selector_id


def selector_matches(resource_tags: dict, match: dict[str, str]) -> bool:
    """Return True when all selector predicates match the resource tag map."""
    for key, value in match.items():
        if resource_tags.get(key) != value:
            return False
    return True


def resolve_selector_vm_ids(resources: list[dict], match: dict[str, str]) -> list[int]:
    """Resolve selector candidates to sorted vm_id list."""
    vm_ids = []
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ValueError(
                "Invalid selector resource resources[%s]: expected mapping" % (index,)
            )
        vm_id = resource.get("vm_id")
        if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id < 1:
            raise ValueError(
                "Invalid selector resource resources[%s].vm_id: expected integer >= 1"
                % (index,)
            )
        tags = resource.get("tags")
        if not isinstance(tags, dict):
            raise ValueError(
                "Invalid selector resource resources[%s].tags: expected mapping" % (index,)
            )
        if selector_matches(tags, match):
            vm_ids.append(vm_id)
    return sorted(vm_ids)


def build_scope_identities(
    resources_by_vm_id: dict[int, dict],
    resolved_vm_ids: list[int],
    selector_id: str,
) -> list[dict]:
    """Build canonical scope identity records for vm/cluster/selector scopes."""
    cluster_ids = sorted(
        {
            str(resources_by_vm_id[vm_id]["cluster_id"])
            for vm_id in resolved_vm_ids
            if vm_id in resources_by_vm_id
        }
    )
    return (
        [{"kind": "vm", "vm_id": int(vm_id)} for vm_id in sorted(set(resolved_vm_ids))]
        + [{"kind": "cluster", "cluster_id": cluster_id} for cluster_id in cluster_ids]
        + [{"kind": "selector", "selector_id": selector_id}]
    )


def first_overlap_scope_identity(left_scope: list[dict], right_scope: list[dict]) -> dict | None:
    """Return deterministic first overlapping scope identity or None."""
    left_vms = sorted(
        {
            int(entry.get("vm_id"))
            for entry in left_scope
            if isinstance(entry, dict)
            and entry.get("kind") == "vm"
            and isinstance(entry.get("vm_id"), int)
        }
    )
    right_vms = {
        int(entry.get("vm_id"))
        for entry in right_scope
        if isinstance(entry, dict)
        and entry.get("kind") == "vm"
        and isinstance(entry.get("vm_id"), int)
    }
    for vm_id in left_vms:
        if vm_id in right_vms:
            return {"kind": "vm", "vm_id": vm_id}

    left_clusters = sorted(
        {
            str(entry.get("cluster_id"))
            for entry in left_scope
            if isinstance(entry, dict)
            and entry.get("kind") == "cluster"
            and isinstance(entry.get("cluster_id"), str)
        }
    )
    right_clusters = {
        str(entry.get("cluster_id"))
        for entry in right_scope
        if isinstance(entry, dict)
        and entry.get("kind") == "cluster"
        and isinstance(entry.get("cluster_id"), str)
    }
    for cluster_id in left_clusters:
        if cluster_id in right_clusters:
            return {"kind": "cluster", "cluster_id": cluster_id}

    left_selectors = sorted(
        {
            str(entry.get("selector_id"))
            for entry in left_scope
            if isinstance(entry, dict)
            and entry.get("kind") == "selector"
            and isinstance(entry.get("selector_id"), str)
        }
    )
    right_selectors = {
        str(entry.get("selector_id"))
        for entry in right_scope
        if isinstance(entry, dict)
        and entry.get("kind") == "selector"
        and isinstance(entry.get("selector_id"), str)
    }
    for selector_id in left_selectors:
        if selector_id in right_selectors:
            return {"kind": "selector", "selector_id": selector_id}
    return None
