"""Infrastructure-domain schema validation helpers."""

from __future__ import annotations

import math
from pathlib import Path

from . import legacy_projection, validation_utils

_fail = validation_utils.fail
_fail_unknown_keys = validation_utils.fail_unknown_keys
_is_int = validation_utils.is_int
_is_number = validation_utils.is_number


def validate_network(
    network: dict,
    path: Path,
    prefix: str,
    network_override_keys: set[str],
    network_override_numeric_keys: tuple[str, ...],
    network_override_string_keys: tuple[str, ...],
) -> dict:
    if not isinstance(network, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, network, {"emulation", "wireless_preset", "overrides"})

    emulation = network.get("emulation", False)
    if not isinstance(emulation, bool):
        _fail(path, "%s.emulation" % (prefix), "must be boolean")

    wireless_preset = network.get("wireless_preset", "4g")
    if not isinstance(wireless_preset, str) or not wireless_preset.strip():
        _fail(path, "%s.wireless_preset" % (prefix), "must be a non-empty string")

    if "overrides" in network and network["overrides"] is None:
        _fail(path, "%s.overrides" % (prefix), "must be a mapping")
    overrides = network.get("overrides", {})
    if not isinstance(overrides, dict):
        _fail(path, "%s.overrides" % (prefix), "must be a mapping")

    normalized_overrides = {}
    for key, value in overrides.items():
        key_path = "%s.overrides.%s" % (prefix, key)
        if key not in network_override_keys:
            _fail(path, key_path, "unsupported override key")
        if key in network_override_numeric_keys and not _is_number(value):
            _fail(path, key_path, "must be number")
        if key in network_override_string_keys and (
            not isinstance(value, str) or not value.strip()
        ):
            _fail(path, key_path, "must be a non-empty string")
        normalized_overrides[key] = value

    return {
        "emulation": emulation,
        "wireless_preset": wireless_preset.strip(),
        "overrides": normalized_overrides,
    }


def validate_vm_spec(
    spec: dict,
    count: int,
    path: Path,
    prefix: str,
    default_tier_cpu_cores: int,
    default_tier_memory_gb: float,
    default_tier_cpu_quota: float,
    default_tier_storage_mbps: float,
) -> dict:
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(
        path,
        prefix,
        spec,
        {"cores", "memory_gb", "cpu_quota", "storage_read_mbps", "storage_write_mbps"},
    )

    cores = spec.get("cores", default_tier_cpu_cores if count > 0 else 0)
    if not _is_int(cores) or cores < 0:
        _fail(path, "%s.cores" % (prefix), "must be integer >= 0")
    if count > 0 and cores < 1:
        _fail(path, "%s.cores" % (prefix), "must be integer >= 1 when count > 0")

    memory_gb = spec.get("memory_gb", default_tier_memory_gb if count > 0 else 0.0)
    if not _is_number(memory_gb) or not math.isfinite(memory_gb) or memory_gb < 0:
        _fail(path, "%s.memory_gb" % (prefix), "must be finite number >= 0")

    cpu_quota = spec.get("cpu_quota", default_tier_cpu_quota if count > 0 else 0.0)
    if not _is_number(cpu_quota) or cpu_quota < 0:
        _fail(path, "%s.cpu_quota" % (prefix), "must be number >= 0")

    storage_read_mbps = spec.get("storage_read_mbps", default_tier_storage_mbps)
    if not _is_number(storage_read_mbps) or storage_read_mbps < 0:
        _fail(path, "%s.storage_read_mbps" % (prefix), "must be number >= 0")

    storage_write_mbps = spec.get("storage_write_mbps", default_tier_storage_mbps)
    if not _is_number(storage_write_mbps) or storage_write_mbps < 0:
        _fail(path, "%s.storage_write_mbps" % (prefix), "must be number >= 0")

    return {
        "cores": int(cores),
        "memory_gb": float(memory_gb),
        "cpu_quota": float(cpu_quota),
        "storage_read_mbps": float(storage_read_mbps),
        "storage_write_mbps": float(storage_write_mbps),
    }


def validate_cluster(
    cluster: dict,
    path: Path,
    prefix: str,
    allowed_tiers: tuple[str, ...],
    default_tier_cpu_cores: int,
    default_tier_memory_gb: float,
    default_tier_cpu_quota: float,
    default_tier_storage_mbps: float,
) -> dict:
    if not isinstance(cluster, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, cluster, {"id", "tier", "resources"})

    cluster_id = cluster.get("id")
    if not isinstance(cluster_id, str) or not cluster_id.strip():
        _fail(path, "%s.id" % (prefix), "must be a non-empty string")
    cluster_id = cluster_id.strip()

    tier = cluster.get("tier")
    if tier not in allowed_tiers:
        _fail(path, "%s.tier" % (prefix), "must be one of %s" % (", ".join(allowed_tiers)))

    resources = cluster.get("resources")
    if not isinstance(resources, dict):
        _fail(path, "%s.resources" % (prefix), "must be a mapping")
    _fail_unknown_keys(path, "%s.resources" % (prefix), resources, {"vms"})

    vms = resources.get("vms")
    if not isinstance(vms, dict):
        _fail(path, "%s.resources.vms" % (prefix), "must be a mapping")
    _fail_unknown_keys(path, "%s.resources.vms" % (prefix), vms, {"count", "spec"})

    count = vms.get("count")
    if not _is_int(count) or count < 0:
        _fail(path, "%s.resources.vms.count" % (prefix), "must be integer >= 0")

    spec = validate_vm_spec(
        vms.get("spec"),
        count,
        path,
        "%s.resources.vms.spec" % (prefix),
        default_tier_cpu_cores,
        default_tier_memory_gb,
        default_tier_cpu_quota,
        default_tier_storage_mbps,
    )
    return {
        "id": cluster_id,
        "tier": tier,
        "resources": {
            "vms": {
                "count": int(count),
                "spec": spec,
            }
        },
    }


def validate_infrastructure(
    infrastructure: dict,
    path: Path,
    prefix: str,
    allowed_tiers: tuple[str, ...],
    network_override_keys: set[str],
    network_override_numeric_keys: tuple[str, ...],
    network_override_string_keys: tuple[str, ...],
    default_tier_cpu_cores: int,
    default_tier_memory_gb: float,
    default_tier_cpu_quota: float,
    default_tier_storage_mbps: float,
    build_tagged_resources,
    allow_derived: bool = False,
):
    if not isinstance(infrastructure, dict):
        _fail(path, prefix, "must be a mapping")
    if "image_prefetch" in infrastructure:
        _fail(
            path,
            "%s.image_prefetch" % (prefix),
            "is not supported in infrastructure domain; use run.image_prefetch",
        )
    allowed = {"clusters", "network"}
    if allow_derived:
        allowed.add("resources")
    _fail_unknown_keys(path, prefix, infrastructure, allowed)

    clusters = infrastructure.get("clusters")
    if not isinstance(clusters, list) or not clusters:
        _fail(path, "%s.clusters" % (prefix), "must be a non-empty list")

    normalized_clusters = []
    cluster_ids = set()
    for index, cluster in enumerate(clusters):
        cluster_prefix = "%s.clusters[%s]" % (prefix, index)
        normalized_cluster = validate_cluster(
            cluster,
            path,
            cluster_prefix,
            allowed_tiers,
            default_tier_cpu_cores,
            default_tier_memory_gb,
            default_tier_cpu_quota,
            default_tier_storage_mbps,
        )
        cluster_id = normalized_cluster["id"]
        if cluster_id in cluster_ids:
            _fail(path, "%s.id" % (cluster_prefix), "duplicate cluster id '%s'" % (cluster_id))
        cluster_ids.add(cluster_id)
        normalized_clusters.append(normalized_cluster)

    if "network" in infrastructure and infrastructure["network"] is None:
        _fail(path, "%s.network" % (prefix), "must be a mapping")
    normalized_network = validate_network(
        infrastructure.get("network", {}),
        path,
        "%s.network" % (prefix),
        network_override_keys,
        network_override_numeric_keys,
        network_override_string_keys,
    )
    legacy_projection.aggregate_clusters_for_legacy(normalized_clusters, allowed_tiers)
    infrastructure["clusters"] = normalized_clusters
    infrastructure["network"] = normalized_network
    infrastructure["resources"] = build_tagged_resources(normalized_clusters)
