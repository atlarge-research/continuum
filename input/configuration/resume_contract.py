"""Canonical resume contract helpers for lock and state artifacts."""

from __future__ import annotations

import copy
import hashlib
import json

from . import config_access

CONTRACT_SCHEMA_VERSION = 1
HASH_PREFIX = "sha256:"


def _require_mapping(value, path):
    if not isinstance(value, dict):
        raise ValueError("Invalid resume contract path %s: expected mapping" % (path,))
    return value


def _require_non_empty_string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid resume contract path %s: expected non-empty string" % (path,))
    return value.strip()


def _provider_config_for_contract(provider_config):
    """Return provider config fields that affect retained resume compatibility."""
    provider_config = _require_mapping(provider_config, "normalized.provider.config")
    contract_config = copy.deepcopy(provider_config)
    contract_config.pop("base_path", None)
    contract_config.pop("delete_on_exit", None)
    return contract_config


def _software_modules_for_contract(config):
    modules = config_access.software_modules(config)
    return copy.deepcopy(modules)


def _planner_fields_for_contract(config):
    snapshot = config_access.planner_snapshot(config)
    return {
        "software_execution_order": copy.deepcopy(snapshot.get("software_execution_order", [])),
        "software_plan_entries": copy.deepcopy(snapshot.get("software_plan_entries", [])),
        "software_module_assignments": copy.deepcopy(
            snapshot.get("software_module_assignments", [])
        ),
    }


def build_resume_contract(config):
    """Build the deterministic config subset required for phase resume."""
    normalized = _require_mapping(config.get("normalized"), "normalized")
    provider = _require_mapping(normalized.get("provider"), "normalized.provider")
    infrastructure = _require_mapping(
        normalized.get("infrastructure"),
        "normalized.infrastructure",
    )

    provider_name = _require_non_empty_string(provider.get("name"), "normalized.provider.name")
    provider_config = _provider_config_for_contract(provider.get("config"))

    return {
        "provider": {
            "name": provider_name,
            "config": provider_config,
        },
        "infrastructure": {
            "clusters": copy.deepcopy(infrastructure.get("clusters", [])),
            "resources": copy.deepcopy(infrastructure.get("resources", [])),
            "network": copy.deepcopy(infrastructure.get("network", {})),
        },
        "software": {
            "resource_manager": config_access.orchestrator_name(config),
            "modules": _software_modules_for_contract(config),
        },
        "planner": _planner_fields_for_contract(config),
    }


def hash_resume_contract(details):
    """Return a deterministic hash for resume contract details."""
    _require_mapping(details, "resume_contract.details")
    encoded = json.dumps(
        details,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "%s%s" % (HASH_PREFIX, hashlib.sha256(encoded).hexdigest())


def build_persisted_resume_contract(config):
    """Build the persisted resume_contract section for lock/state files."""
    details = build_resume_contract(config)
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "hash": hash_resume_contract(details),
        "details": details,
    }


def persisted_resume_contract_from_details(details):
    """Build a persisted resume_contract section from prebuilt details."""
    details = copy.deepcopy(details)
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "hash": hash_resume_contract(details),
        "details": details,
    }


def validate_persisted_resume_contract(section, path="resume_contract"):
    """Validate a persisted resume_contract section and return its hash/details."""
    section = _require_mapping(section, path)
    schema_version = section.get("schema_version")
    if schema_version != CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            "%s.schema_version must be %s" % (path, CONTRACT_SCHEMA_VERSION)
        )

    expected_hash = _require_non_empty_string(section.get("hash"), "%s.hash" % (path,))
    details = _require_mapping(section.get("details"), "%s.details" % (path,))
    actual_hash = hash_resume_contract(details)
    if expected_hash != actual_hash:
        raise ValueError("%s.hash does not match %s.details" % (path, path))
    return expected_hash, details


def validate_current_resume_contract(config, section, path="resume_contract"):
    """Validate a persisted contract section against the current runtime config."""
    persisted_hash, _details = validate_persisted_resume_contract(section, path)
    current_section = build_persisted_resume_contract(config)
    current_hash = current_section["hash"]
    if persisted_hash != current_hash:
        raise ValueError(
            "%s hash does not match current configuration: expected %s but found %s"
            % (path, current_hash, persisted_hash)
        )
    return current_hash
