"""Declarative runtime-option contracts shared by parser/runtime validation."""

from __future__ import annotations

# Core-owned provider keys consumed by Continuum infrastructure/runtime code.
# Provider modules may extend this set via their add_options() descriptors.
CORE_PROVIDER_CONFIG_KEYS = frozenset(
    {
        "base_path",
        "cpu_pin",
        "external_physical_machines",
        "ip",
        "netperf",
        "delete_on_exit",
    }
)

# Canonical provider.config.ip mapping keys.
PROVIDER_IP_CONFIG_KEYS = frozenset(
    {
        "prefix",
        "middle",
        "middle_base",
    }
)

