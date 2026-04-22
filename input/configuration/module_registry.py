"""Software module registry semantics for parser/runtime validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleSpec:
    """Static internal contract for one software module type."""

    scope: str
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    exclusive_provides: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    allowed_config_keys: tuple[str, ...] = ()
    image_catalog_refs: tuple[str, ...] = ()


MODULE_REGISTRY: dict[str, ModuleSpec] = {
    "none": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.none",),
        exclusive_provides=("slot.orchestrator",),
    ),
    "kubernetes": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.kubernetes", "capability.observability_host"),
        exclusive_provides=("slot.orchestrator",),
    ),
    "kubeedge": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.kubeedge",),
        exclusive_provides=("slot.orchestrator",),
    ),
    "kubecontrol": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.kubecontrol", "capability.observability_host"),
        exclusive_provides=("slot.orchestrator",),
        image_catalog_refs=("kube.control_plane",),
    ),
    "kube_kata": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.kube_kata", "capability.observability_host"),
        exclusive_provides=("slot.orchestrator",),
        image_catalog_refs=("kube.control_plane",),
    ),
    "mist": ModuleSpec(
        scope="orchestrator",
        provides=("orchestrator.mist",),
        exclusive_provides=("slot.orchestrator",),
    ),
    "endpoint_runtime": ModuleSpec(
        scope="addon",
        provides=("capability.endpoint_runtime",),
    ),
    "openfaas": ModuleSpec(
        scope="addon",
        requires=("orchestrator.kubernetes",),
        provides=("capability.openfaas",),
    ),
    "observability": ModuleSpec(
        scope="addon",
        requires=("capability.observability_host",),
        provides=("capability.observability",),
    ),
}

ORCHESTRATOR_MODULE_TYPES = tuple(
    module_type for module_type, spec in MODULE_REGISTRY.items() if spec.scope == "orchestrator"
)
ADDON_MODULE_TYPES = tuple(
    module_type for module_type, spec in MODULE_REGISTRY.items() if spec.scope == "addon"
)
SUPPORTED_MODULE_TYPES = tuple(MODULE_REGISTRY.keys())


def get_spec(module_type: str) -> ModuleSpec | None:
    """Return registry metadata for one module type."""

    return MODULE_REGISTRY.get(module_type)
