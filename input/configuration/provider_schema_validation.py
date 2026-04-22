"""Provider-domain schema validation helpers."""

from __future__ import annotations

import os
from pathlib import Path

from .runtime_option_contract import PROVIDER_IP_CONFIG_KEYS
from . import validation_utils

_fail = validation_utils.fail
_fail_unknown_keys = validation_utils.fail_unknown_keys
_is_int = validation_utils.is_int


def validate_provider(provider: dict, path: Path, prefix: str):
    if not isinstance(provider, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, provider, {"name", "config"})

    name = provider.get("name")
    if not isinstance(name, str) or not name.strip():
        _fail(path, "%s.name" % (prefix), "must be a non-empty string")

    if "config" in provider and provider["config"] is None:
        _fail(path, "%s.config" % (prefix), "must be a mapping")
    provider_cfg = provider.get("config", {})
    if not isinstance(provider_cfg, dict):
        _fail(path, "%s.config" % (prefix), "must be a mapping")

    if "base_path" not in provider_cfg:
        provider_cfg["base_path"] = os.getenv("HOME", "~")
    if not isinstance(provider_cfg["base_path"], str) or not provider_cfg["base_path"].strip():
        _fail(path, "%s.config.base_path" % (prefix), "must be a non-empty string")

    for key in ("cpu_pin", "netperf", "delete_on_exit"):
        if key not in provider_cfg:
            provider_cfg[key] = False
        if not isinstance(provider_cfg[key], bool):
            _fail(path, "%s.config.%s" % (prefix), "must be boolean")

    if "external_physical_machines" not in provider_cfg:
        provider_cfg["external_physical_machines"] = []
    machines = provider_cfg["external_physical_machines"]
    if not isinstance(machines, list) or not all(isinstance(x, str) for x in machines):
        _fail(
            path,
            "%s.config.external_physical_machines" % (prefix),
            "must be a list of strings",
        )

    if "ip" in provider_cfg and provider_cfg["ip"] is None:
        _fail(path, "%s.config.ip" % (prefix), "must be a mapping")
    ip_cfg = provider_cfg.get("ip", {})
    if not isinstance(ip_cfg, dict):
        _fail(path, "%s.config.ip" % (prefix), "must be a mapping")

    _fail_unknown_keys(path, "%s.config.ip" % (prefix), ip_cfg, PROVIDER_IP_CONFIG_KEYS)

    if "prefix" not in ip_cfg:
        ip_cfg["prefix"] = "192.168"
    if not isinstance(ip_cfg["prefix"], str) or not ip_cfg["prefix"].strip():
        _fail(path, "%s.config.ip.prefix" % (prefix), "must be a non-empty string")

    for key, default in (("middle", 100), ("middle_base", 90)):
        if key not in ip_cfg:
            ip_cfg[key] = default
        value = ip_cfg[key]
        if not _is_int(value) or value < 0 or value > 255:
            _fail(path, "%s.config.ip.%s" % (prefix, key), "must be integer in [0,255]")

    provider_cfg["ip"] = ip_cfg
    provider["config"] = provider_cfg
