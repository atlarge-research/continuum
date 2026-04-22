"""Shared orchestrator option descriptor catalog.

Each descriptor follows the existing Continuum module contract:
    [name, type, validator, mandatory, default]

Resource-manager modules compose these fragments to keep option ownership
explicit while avoiding duplicated validators/defaults across Kubernetes-family
orchestrators.
"""

from __future__ import annotations

KUBE_VERSIONS_CURRENT = ("v1.27.0",)
KUBE_VERSIONS_COMPAT = ("v1.27.0", "v1.26.0", "v1.25.0", "v1.24.0", "v1.23.0")
KUBE_DEPLOYMENT_MODES = ("pod", "container", "file", "call")
KATA_RUNTIMES = ("runc", "kata-qemu", "kata-fc")
KATA_FILESYSTEMS = ("overlayfs", "devmapper")


def _bool_option(name, default=False):
    return [name, bool, lambda x: x in [True, False], False, default]


def _enum_option(name, allowed_values, default):
    allowed = tuple(allowed_values)
    return [name, str, lambda x, allowed=allowed: x in allowed, False, default]


def kubernetes_common_options(kube_versions):
    """Options shared by Kubernetes-family orchestrators."""
    versions = tuple(kube_versions)
    if not versions:
        raise ValueError("kube_versions must include at least one entry")
    return [
        _bool_option("cache_worker", False),
        _enum_option("kube_version", versions, versions[0]),
    ]


def kube_deployment_options():
    """Options for Kubernetes workload launch strategy."""
    return [_enum_option("kube_deployment", KUBE_DEPLOYMENT_MODES, "pod")]


def kata_runtime_options():
    """Options required by the kube_kata orchestrator."""
    return [
        _enum_option("runtime", KATA_RUNTIMES, "runc"),
        _enum_option("runtime_filesystem", KATA_FILESYSTEMS, "devmapper"),
    ]
