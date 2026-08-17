"""Internal image requirement discovery for registry prefetch behavior."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import config_access, module_registry

_STAGE_IMAGE_CATALOG: dict[str, tuple[str, ...]] = {
    "empty": ("app.empty",),
    "empty_kata": ("app.empty_kata",),
    "mem_usage": ("app.mem_usage",),
    "stress": ("app.stress",),
    "image_classification": ("app.image_classification",),
    "text_translation": ("app.text_translation",),
}
_KUBE_ETCD_COREDNS_PAUSE_BY_VERSION: dict[str, tuple[str, str, str]] = {
    "v1.27.0": ("3.5.7-0", "v1.10.1", "3.9"),
    "v1.26.0": ("3.5.6-0", "v1.9.3", "3.9"),
    "v1.25.0": ("3.5.4-0", "v1.9.3", "3.8"),
    "v1.24.0": ("3.5.3-0", "v1.8.6", "3.7"),
    "v1.23.0": ("3.5.1-0", "v1.8.6", "3.6"),
}


def _required_mapping(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Missing required config path %s" % (path,))
    return value


def _required_non_empty_string(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing required config path %s" % (path,))
    return value.strip()


def _kube_control_plane_images(owner_record: dict | None, _config: dict | None) -> tuple[str, ...]:
    module = _required_mapping(owner_record, "image-prefetch owner record")
    module_id = _required_non_empty_string(module.get("id"), "image-prefetch owner id")
    module_config = _required_mapping(
        module.get("config"),
        "image-prefetch owner config for module '%s'" % (module_id,),
    )

    raw_version = module_config.get("kube_version")
    if not isinstance(raw_version, str) or not raw_version.strip():
        raise ValueError(
            "Missing required kube_version for image prefetch on module '%s'" % (module_id,)
        )
    kube_version = raw_version.strip()
    version_tuple = _KUBE_ETCD_COREDNS_PAUSE_BY_VERSION.get(kube_version)
    if version_tuple is None:
        raise ValueError(
            "Unsupported Kubernetes version '%s' for image prefetch "
            "(supported: %s)"
            % (kube_version, ", ".join(sorted(_KUBE_ETCD_COREDNS_PAUSE_BY_VERSION)))
        )
    etcd_version, coredns_version, pause_version = version_tuple
    return (
        "redplanet00/kube-proxy:%s" % (kube_version),
        "redplanet00/kube-controller-manager:%s" % (kube_version),
        "redplanet00/kube-scheduler:%s" % (kube_version),
        "redplanet00/kube-apiserver:%s" % (kube_version),
        "redplanet00/etcd:%s" % (etcd_version),
        "redplanet00/coredns:%s" % (coredns_version),
        "redplanet00/pause:%s" % (pause_version),
    )


def _image_classification_images(
    _owner_record: dict | None, config: dict | None
) -> tuple[str, ...]:
    if not isinstance(config, dict):
        raise ValueError("Missing required runtime config for image_classification image mapping")
    if config_access.has_addon(config, "openfaas"):
        return (
            "redplanet00/kubeedge-applications:image_classification_publisher_serverless",
            "redplanet00/kubeedge-applications:image_classification_subscriber_serverless",
        )
    return (
        "redplanet00/kubeedge-applications:image_classification_combined",
        "redplanet00/kubeedge-applications:image_classification_publisher",
        "redplanet00/kubeedge-applications:image_classification_subscriber",
    )


_TEXT_TRANSLATION_PUBLISHER_SOURCE = (
    "redplanet00/continuum-text-translation-publisher"
    "@sha256:502142b93182c63f1225165f44d0308537aac95ee75a99b6f0ba19e668f6f6bf"
)
_TEXT_TRANSLATION_SUBSCRIBER_SOURCE = (
    "redplanet00/continuum-text-translation-subscriber"
    "@sha256:9aac61a0a1f0fe8938db7283b7f09ab9f9c5f84d95467fa267e9ca3220aabd26"
)
_TEXT_TRANSLATION_PUBLISHER_CONFIG_DIGEST = (
    "sha256:5fab1472b1ba67c56b86dcb48c7d9aeee270604a42514f0edf6f853988f57cfe"
)
_TEXT_TRANSLATION_SUBSCRIBER_CONFIG_DIGEST = (
    "sha256:8973a8d27ba02c08b5dbbc43329a1c8f54c56a887945e3520cc10bab63167417"
)
_IMAGE_CATALOG: dict[
    str,
    str | tuple[str, ...] | Callable[[dict | None, dict | None], str | tuple[str, ...]],
] = {
    "kube.control_plane": _kube_control_plane_images,
    "kube.kata_jaeger": "jaegertracing/all-in-one:1.47",
    "app.empty": "redplanet00/kubeedge-applications:empty",
    "app.empty_kata": "ansk/empty:empty",
    "app.mem_usage": "redplanet00/kubeedge-applications:empty",
    "app.stress": "ansk/empty:stress",
    "app.image_classification": _image_classification_images,
    "app.text_translation": (
        _TEXT_TRANSLATION_PUBLISHER_SOURCE,
        _TEXT_TRANSLATION_SUBSCRIBER_SOURCE,
    ),
}
_LOCAL_IMAGE_NAMES_BY_SOURCE = {
    _TEXT_TRANSLATION_PUBLISHER_SOURCE: "text_translation_publisher_en-nl-8aad73b-r1",
    _TEXT_TRANSLATION_SUBSCRIBER_SOURCE: "text_translation_subscriber_en-nl-8aad73b-r1",
}
_LOCAL_IMAGE_CONFIG_DIGEST_BY_SOURCE = {
    _TEXT_TRANSLATION_PUBLISHER_SOURCE: _TEXT_TRANSLATION_PUBLISHER_CONFIG_DIGEST,
    _TEXT_TRANSLATION_SUBSCRIBER_SOURCE: _TEXT_TRANSLATION_SUBSCRIBER_CONFIG_DIGEST,
}
_SHA256_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ImageRequirement:
    """Resolved image requirement consumed by infrastructure registry flow."""

    source_ref: str
    local_name: str
    owners: tuple[str, ...]
    tier_targets: tuple[str, ...]


def _local_name_for_source(source_ref: str) -> str:
    explicit_name = _LOCAL_IMAGE_NAMES_BY_SOURCE.get(source_ref)
    if explicit_name is not None:
        return explicit_name
    if "/" not in source_ref:
        return source_ref
    return source_ref.split("/", 1)[1]


def source_ref_is_digest_pinned(source_ref: str) -> bool:
    """Return whether an image source uses an immutable digest reference."""
    return isinstance(source_ref, str) and "@" in source_ref.strip()


def is_valid_sha256_digest(value: object) -> bool:
    """Return whether a value is a canonical sha256 digest string."""
    return isinstance(value, str) and _SHA256_DIGEST_PATTERN.fullmatch(value) is not None


def expected_local_config_digest(source_ref: str) -> str | None:
    """Return the trusted run-local image-config identity for a pinned source."""
    expected_digest = _LOCAL_IMAGE_CONFIG_DIGEST_BY_SOURCE.get(source_ref)
    if expected_digest is None:
        return None
    if not is_valid_sha256_digest(expected_digest):
        raise ValueError(
            "Invalid expected local image-config digest for source '%s': %r"
            % (source_ref, expected_digest)
        )
    return expected_digest


def _normalize_catalog_sources(
    value: str | tuple[str, ...] | list[str] | None,
    catalog_ref: str,
    owner: str,
) -> tuple[str, ...]:
    if value is None:
        raise ValueError(
            "Missing internal image catalog mapping for '%s' (owner=%s)" % (catalog_ref, owner)
        )
    if isinstance(value, str):
        normalized = (value,)
    elif isinstance(value, tuple):
        normalized = value
    elif isinstance(value, list):
        normalized = tuple(value)
    else:
        raise ValueError(
            "Invalid internal image catalog mapping for '%s' (owner=%s)" % (catalog_ref, owner)
        )
    cleaned = tuple(str(item).strip() for item in normalized if str(item).strip())
    if not cleaned:
        raise ValueError(
            "Internal image catalog mapping for '%s' resolved to empty source set (owner=%s)"
            % (catalog_ref, owner)
        )
    return cleaned


def _resolve_catalog_sources(
    catalog_ref: str,
    owner: str,
    owner_record: dict | None = None,
    config: dict | None = None,
) -> tuple[str, ...]:
    source_ref = _IMAGE_CATALOG.get(catalog_ref)
    if callable(source_ref):
        resolved = source_ref(owner_record, config)
        return _normalize_catalog_sources(resolved, catalog_ref, owner)
    return _normalize_catalog_sources(source_ref, catalog_ref, owner)


def _tier_targets_for_record(
    record: dict, resources_by_vm_id: dict[int, dict], owner: str
) -> tuple[str, ...]:
    resolved_vm_ids = record.get("resolved_vm_ids")
    if not isinstance(resolved_vm_ids, list):
        raise ValueError("Missing required resolved_vm_ids for %s" % (owner,))
    if not resolved_vm_ids:
        raise ValueError("resolved_vm_ids must not be empty for %s" % (owner,))

    tiers = set()
    for vm_id in resolved_vm_ids:
        if not isinstance(vm_id, int) or vm_id <= 0:
            raise ValueError("Invalid vm_id in resolved_vm_ids for %s: %r" % (owner, vm_id))
        resource = resources_by_vm_id.get(vm_id)
        if not isinstance(resource, dict):
            raise ValueError(
                "Resolved vm_id %s for %s is missing from normalized.infrastructure.resources"
                % (vm_id, owner)
            )
        tags = resource.get("tags")
        if not isinstance(tags, dict):
            raise ValueError("Missing tags for vm_id %s (%s)" % (vm_id, owner))
        tier = tags.get("tier")
        if not isinstance(tier, str) or not tier:
            raise ValueError("Missing tier tag for vm_id %s (%s)" % (vm_id, owner))
        tiers.add(tier)

    return tuple(sorted(tiers))


def _collect_module_image_refs(module: dict) -> tuple[str, ...]:
    module_type = module.get("type")
    if not isinstance(module_type, str) or not module_type.strip():
        raise ValueError("Missing required software module type for image prefetch discovery")
    module_type = module_type.strip()
    spec = module_registry.get_spec(module_type)
    if spec is None:
        raise ValueError("Unknown software module type '%s' in image prefetch discovery" % (module_type,))
    return tuple(spec.image_catalog_refs or ())


def _collect_stage_image_refs(stage: dict) -> tuple[str, ...]:
    stage_type = stage.get("type")
    if not isinstance(stage_type, str) or not stage_type.strip():
        raise ValueError("Missing required benchmark stage type for image prefetch discovery")
    stage_type = stage_type.strip()
    refs = _STAGE_IMAGE_CATALOG.get(stage_type)
    if refs is None:
        raise ValueError(
            "Missing internal stage image mapping for benchmark stage type '%s'" % (stage_type)
        )
    return tuple(refs)


def discover_required_images(config: dict) -> list[ImageRequirement]:
    """Discover deterministic image requirements from module and benchmark intent."""
    run_targets = set(config_access.run_targets(config))
    normalized = _required_mapping(config.get("normalized"), "normalized")
    infrastructure = _required_mapping(normalized.get("infrastructure"), "normalized.infrastructure")
    resources = infrastructure.get("resources")
    if not isinstance(resources, list):
        raise ValueError("Missing required config path normalized.infrastructure.resources")

    resources_by_vm_id: dict[int, dict] = {}
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ValueError(
                "Invalid normalized.infrastructure.resources[%s]: expected mapping" % (index,)
            )
        vm_id = resource.get("vm_id")
        if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
            raise ValueError(
                "Invalid normalized.infrastructure.resources[%s].vm_id: expected integer >= 1"
                % (index,)
            )
        if vm_id in resources_by_vm_id:
            raise ValueError(
                "Duplicate vm_id '%s' in normalized.infrastructure.resources" % (vm_id,)
            )
        resources_by_vm_id[vm_id] = resource

    aggregates: dict[str, dict[str, set[str]]] = {}

    if "software" in run_targets or "application" in run_targets:
        for module in config_access.software_modules(config):
            module_id = _required_non_empty_string(
                module.get("id"),
                "domains.software.modules[*].id",
            )
            owner = "software.module:%s" % (module_id)
            for catalog_ref in _collect_module_image_refs(module):
                for source_ref in _resolve_catalog_sources(catalog_ref, owner, module, config):
                    aggregate = aggregates.setdefault(
                        source_ref, {"owners": set(), "tier_targets": set()}
                    )
                    aggregate["owners"].add(owner)
                    aggregate["tier_targets"].update(
                        _tier_targets_for_record(module, resources_by_vm_id, owner)
                    )

    benchmark_pipeline = []
    if "application" in run_targets:
        benchmark_pipeline = config_access.benchmark_pipeline(config)
        for stage in benchmark_pipeline:
            stage_id = _required_non_empty_string(
                stage.get("id"),
                "domains.benchmark.pipeline[*].id",
            )
            owner = "benchmark.stage:%s" % (stage_id)
            for catalog_ref in _collect_stage_image_refs(stage):
                for source_ref in _resolve_catalog_sources(catalog_ref, owner, stage, config):
                    aggregate = aggregates.setdefault(
                        source_ref, {"owners": set(), "tier_targets": set()}
                    )
                    aggregate["owners"].add(owner)
                    aggregate["tier_targets"].update(
                        _tier_targets_for_record(stage, resources_by_vm_id, owner)
                    )

    requirements = []
    for source_ref in sorted(aggregates):
        aggregate = aggregates[source_ref]
        requirements.append(
            ImageRequirement(
                source_ref=source_ref,
                local_name=_local_name_for_source(source_ref),
                owners=tuple(sorted(aggregate["owners"])),
                tier_targets=tuple(sorted(aggregate["tier_targets"])),
            )
        )
    return requirements
