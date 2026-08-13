"""Legacy runtime projection helpers for normalized YAML configuration."""

from __future__ import annotations

import copy
import os


def _required(mapping: dict, key: str, key_path: str):
    if not isinstance(mapping, dict) or key not in mapping:
        raise ValueError("Missing required normalized config path %s" % (key_path,))
    return mapping[key]


def infra_only_from_targets(targets: list[str]) -> bool:
    """Map run targets to legacy infrastructure-only execution flag."""
    target_set = set(targets)
    has_software = "software" in target_set
    has_application = "application" in target_set
    has_infrastructure = "infrastructure" in target_set
    return has_infrastructure and not has_software and not has_application


def aggregate_clusters_for_legacy(clusters: list[dict], allowed_tiers: tuple[str, ...]) -> dict:
    """Aggregate cluster resources by tier for legacy runtime projection."""
    by_tier = {
        tier: {
            "count": 0,
            "spec": None,
        }
        for tier in allowed_tiers
    }

    for cluster in clusters:
        tier = cluster["tier"]
        vms = cluster["resources"]["vms"]
        count = int(vms["count"])
        spec = copy.deepcopy(vms["spec"])
        by_tier[tier]["count"] += count

        if count == 0:
            continue

        if by_tier[tier]["spec"] is None:
            by_tier[tier]["spec"] = spec
            continue

        if by_tier[tier]["spec"] != spec:
            raise ValueError(
                "Cannot project infrastructure.clusters[] to legacy tier fields: "
                "tier '%s' has inconsistent VM spec across clusters" % (tier)
            )

    for tier in allowed_tiers:
        if by_tier[tier]["spec"] is None:
            by_tier[tier]["spec"] = {
                "cores": 0,
                "memory_gb": 0.0,
                "cpu_quota": 0.0,
                "storage_read_mbps": 0.0,
                "storage_write_mbps": 0.0,
            }
    return by_tier


def to_legacy_config(
    normalized: dict,
    allowed_tiers: tuple[str, ...],
    network_override_keys_in_order: tuple[str, ...],
    validated_provider_config_keys=(),
) -> dict:
    """Convert normalized YAML model to current legacy runtime config shape."""
    run = _required(normalized, "run", "run")
    targets = _required(run, "targets", "run.targets")
    infra_only = infra_only_from_targets(targets)

    provider = _required(normalized, "provider", "provider")
    provider_cfg = _required(provider, "config", "provider.config")
    infrastructure = _required(normalized, "infrastructure", "infrastructure")
    clusters = _required(infrastructure, "clusters", "infrastructure.clusters")
    network = _required(infrastructure, "network", "infrastructure.network")
    software = _required(normalized, "software", "software")

    tier_aggregates = aggregate_clusters_for_legacy(clusters, allowed_tiers)
    cloud_count = int(tier_aggregates["cloud"]["count"])
    edge_count = int(tier_aggregates["edge"]["count"])
    endpoint_count = int(tier_aggregates["endpoint"]["count"])

    cloud_spec = tier_aggregates["cloud"]["spec"]
    edge_spec = tier_aggregates["edge"]["spec"]
    endpoint_spec = tier_aggregates["endpoint"]["spec"]

    ip_cfg = _required(provider_cfg, "ip", "provider.config.ip")

    mode = "endpoint"
    if edge_count > 0:
        mode = "edge"
    elif cloud_count > 0:
        mode = "cloud"

    config = {
        "infrastructure": {
            "provider": _required(provider, "name", "provider.name"),
            "infra_only": infra_only,
            "cloud_nodes": cloud_count,
            "edge_nodes": edge_count,
            "endpoint_nodes": endpoint_count,
            "cloud_cores": int(cloud_spec["cores"] or 0),
            "cloud_memory": float(cloud_spec["memory_gb"]),
            "cloud_quota": float(cloud_spec["cpu_quota"] or 0),
            "edge_cores": int(edge_spec["cores"] or 0),
            "edge_memory": float(edge_spec["memory_gb"]),
            "edge_quota": float(edge_spec["cpu_quota"] or 0),
            "endpoint_cores": int(endpoint_spec["cores"] or 0),
            "endpoint_memory": float(endpoint_spec["memory_gb"]),
            "endpoint_quota": float(endpoint_spec["cpu_quota"] or 0),
            "cloud_read_speed": int(cloud_spec["storage_read_mbps"] or 0),
            "cloud_write_speed": int(cloud_spec["storage_write_mbps"] or 0),
            "edge_read_speed": int(edge_spec["storage_read_mbps"] or 0),
            "edge_write_speed": int(edge_spec["storage_write_mbps"] or 0),
            "endpoint_read_speed": int(endpoint_spec["storage_read_mbps"] or 0),
            "endpoint_write_speed": int(endpoint_spec["storage_write_mbps"] or 0),
            "network_emulation": bool(_required(network, "emulation", "infrastructure.network.emulation")),
            "wireless_network_preset": _required(
                network,
                "wireless_preset",
                "infrastructure.network.wireless_preset",
            ),
            "cpu_pin": bool(_required(provider_cfg, "cpu_pin", "provider.config.cpu_pin")),
            "external_physical_machines": _required(
                provider_cfg,
                "external_physical_machines",
                "provider.config.external_physical_machines",
            ),
            "netperf": bool(_required(provider_cfg, "netperf", "provider.config.netperf")),
            "base_path": os.path.expanduser(
                _required(provider_cfg, "base_path", "provider.config.base_path")
            ),
            "prefixIP": _required(ip_cfg, "prefix", "provider.config.ip.prefix"),
            "middleIP": int(
                _required(ip_cfg, "middle", "provider.config.ip.middle")
            ),
            "middleIP_base": int(
                _required(ip_cfg, "middle_base", "provider.config.ip.middle_base")
            ),
            "delete": bool(_required(provider_cfg, "delete_on_exit", "provider.config.delete_on_exit")),
        },
        "benchmark": {},
        "mode": mode,
    }

    provider_specific_keys = sorted(set(validated_provider_config_keys))
    reserved_infrastructure_keys = set(config["infrastructure"]) | set(
        network_override_keys_in_order
    )
    collisions = sorted(set(provider_specific_keys) & reserved_infrastructure_keys)
    if collisions:
        raise ValueError(
            "Validated provider config key(s) collide with reserved runtime "
            "infrastructure key(s): %s" % (", ".join(collisions),)
        )

    for key in provider_specific_keys:
        config["infrastructure"][key] = copy.deepcopy(
            _required(provider_cfg, key, "provider.config.%s" % (key,))
        )

    overrides = _required(network, "overrides", "infrastructure.network.overrides")
    for key in network_override_keys_in_order:
        if key in overrides:
            config["infrastructure"][key] = overrides[key]

    config["domains"] = {
        "run": {
            "targets": targets,
            "dry_run": bool(_required(run, "dry_run", "run.dry_run")),
            "clean": bool(_required(run, "clean", "run.clean")),
            "image_prefetch": str(_required(run, "image_prefetch", "run.image_prefetch")),
            "prepare_for_resume": bool(
                _required(run, "prepare_for_resume", "run.prepare_for_resume")
            ),
        },
        "provider": provider,
        "software": copy.deepcopy(software),
        "infrastructure": infrastructure,
        "benchmark": normalized.get("benchmark", {}),
    }
    config["normalized"] = normalized
    config["config_format"] = "yaml"
    return config
