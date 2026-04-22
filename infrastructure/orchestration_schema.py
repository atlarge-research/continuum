"""Shared orchestration mapping helpers for Ansible payloads."""

from __future__ import annotations

import hashlib
import string
from typing import Dict, List


def inventory_host_name(machine) -> str:
    """Return inventory host key for one physical machine.

    Args:
        machine (Machine): Physical machine object from Continuum.

    Returns:
        str: Inventory key (``localhost`` for local machine, otherwise sanitized name).
    """
    return "localhost" if machine.is_local else machine.name_sanitized


def normalized_base_name(base_name: str) -> str:
    """Normalize a base image name by removing host-local suffix parts.

    Args:
        base_name (str): Raw base image name from machine metadata.

    Returns:
        str: Normalized base image identity used for cross-host comparisons.
    """
    stem = base_name.rsplit("_", 1)[0]
    parts = stem.split("_")
    if parts and parts[-1].isdigit():
        return "_".join(parts[:-1])

    if not parts:
        return stem

    last = parts[-1].rstrip(string.digits)
    if last:
        parts[-1] = last
        return "_".join(parts)
    return "_".join(parts[:-1])


def guest_login_name(node_name: str, max_length: int = 32) -> str:
    """Return a deterministic guest login name that fits Linux username limits.

    QEMU guest VM and base image names can be longer than what the guest OS will
    reliably accept as a login user. Keep short names unchanged and fold long
    names into a stable, readable prefix plus hash suffix.
    """
    if len(node_name) <= max_length:
        return node_name

    digest = hashlib.sha1(node_name.encode("utf-8")).hexdigest()[:8]
    prefix_length = max_length - len(digest) - 1
    prefix = node_name[:prefix_length].rstrip("_-")
    if not prefix:
        prefix = "node"
    return "%s_%s" % (prefix, digest)


def base_images_by_host(machines, allowed_base_names: List[str]) -> Dict[str, List[str]]:
    """Build per-host raw base image lists that should be prepared.

    Args:
        machines (list[Machine]): Physical machine objects with base image metadata.
        allowed_base_names (list[str]): Normalized base image identities selected for preparation.

    Returns:
        dict[str, list[str]]: Mapping of inventory host to raw base image names.
    """
    allowed = set(allowed_base_names)
    images: Dict[str, List[str]] = {}

    for machine in machines:
        host = inventory_host_name(machine)
        names: List[str] = []
        for base_name in machine.base_names:
            normalized = normalized_base_name(base_name)
            if normalized in allowed and base_name not in names:
                names.append(base_name)
        images[host] = names
    return images


def tier_vm_nodes_by_host(machines, tier: str) -> Dict[str, List[str]]:
    """Build per-host VM node lists for a given tier.

    Args:
        machines (list[Machine]): Physical machine objects.
        tier (str): VM tier selector (``cloud``, ``edge``, or ``endpoint``).

    Returns:
        dict[str, list[str]]: Mapping of inventory host to VM node names for the tier.
    """
    nodes_by_host: Dict[str, List[str]] = {}
    for machine in machines:
        host = inventory_host_name(machine)
        if tier == "cloud":
            nodes = machine.cloud_controller_names + machine.cloud_names
        elif tier == "edge":
            nodes = machine.edge_names
        elif tier == "endpoint":
            nodes = machine.endpoint_names
        else:
            raise ValueError("Unknown VM tier for node mapping: %s" % (tier))
        nodes_by_host[host] = nodes
    return nodes_by_host


def tier_base_image_by_host(machines, tier: str) -> Dict[str, str]:
    """Build per-host base image mapping for a given tier.

    Args:
        machines (list[Machine]): Physical machine objects.
        tier (str): VM tier selector (``cloud``, ``edge``, or ``endpoint``).

    Returns:
        dict[str, str]: Mapping of inventory host to selected base image name.
    """
    suffix_map = {
        "cloud": "_cloud_",
        "edge": "_edge_",
        "endpoint": "_endpoint",
    }
    if tier not in suffix_map:
        raise ValueError("Unknown VM tier for base image mapping: %s" % (tier))

    base_by_host: Dict[str, str] = {}
    suffix = suffix_map[tier]
    for machine in machines:
        host = inventory_host_name(machine)
        matches = [name for name in machine.base_names if suffix in name]
        if matches:
            base_by_host[host] = matches[0]
            continue

        # Infra-only runs can still use legacy single-base naming like
        # ``base0_<user>`` for a single-tier machine. In that case the tier is
        # implied by the machine's scheduled VM counts rather than the base name.
        tier_count = {
            "cloud": getattr(machine, "cloud_controller", 0) + getattr(machine, "clouds", 0),
            "edge": getattr(machine, "edges", 0),
            "endpoint": getattr(machine, "endpoints", 0),
        }
        if len(machine.base_names) == 1 and tier_count[tier] > 0:
            base_by_host[host] = machine.base_names[0]
        else:
            base_by_host[host] = ""
    return base_by_host


def tier_from_base_name(base_name: str) -> str | None:
    """Resolve VM tier from a normalized base image name.

    Args:
        base_name (str): Normalized base image name.

    Returns:
        str | None: Tier name (``cloud``, ``edge``, ``endpoint``) or None when unmatched.
    """
    if "base_cloud" in base_name:
        return "cloud"
    if "base_edge" in base_name:
        return "edge"
    if "base_endpoint" in base_name:
        return "endpoint"
    return None
