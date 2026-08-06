"""Experiment lockfile writing helpers."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile

import yaml

from resource_manager import plans

from . import resume_contract, yaml_io


def write_experiment_lock(config):
    """Persist a resolved lock file for YAML-driven runs."""
    if config.get("config_format") != "yaml":
        return None

    normalized_raw = config.get("normalized")
    if not isinstance(normalized_raw, dict) or not normalized_raw:
        raise ValueError("Missing required config.normalized for experiment lock write")
    normalized = copy.deepcopy(normalized_raw)

    infra = config.get("infrastructure")
    if not isinstance(infra, dict):
        raise ValueError("Missing required config.infrastructure for experiment lock write")
    base_path = infra.get("base_path")
    if not isinstance(base_path, str) or not base_path.strip():
        raise ValueError(
            "Missing required config.infrastructure.base_path for experiment lock write"
        )

    lock_path = Path(base_path).expanduser() / ".continuum" / "experiment_lock.yaml"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    sources_raw = normalized.get("sources", {})
    if not isinstance(sources_raw, dict):
        raise ValueError("Invalid normalized.sources for experiment lock write")
    sources = copy.deepcopy(sources_raw)
    hashes = {}
    for key in ("experiment", "environment_profile", "software_profile"):
        source_path = sources.get(key)
        if source_path and Path(source_path).exists():
            hashes["%s_sha256" % key] = yaml_io.sha256(Path(source_path))

    domains = config.get("domains")
    planner_snapshot = None
    contract_config = config
    if isinstance(domains, dict):
        planner_snapshot = plans.build_planner_snapshot(config)
        contract_config = copy.copy(config)
        contract_config["planner_snapshot"] = planner_snapshot

    lock_data = {
        "schema_version": 1,
        "kind": "ContinuumExperimentLock",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "sources": {
            **sources,
            "hashes": hashes,
        },
        "normalized_config": normalized,
        "portability": {
            "mutable_fields": [
                "provider.config.base_path",
                "provider.config.ip.prefix",
                "provider.config.ip.middle",
                "provider.config.ip.middle_base",
                "provider.config.external_physical_machines",
            ],
            "notes": [
                "Local paths and network addressing may differ between sites.",
            ],
        },
        "resume_contract": resume_contract.build_persisted_resume_contract(contract_config),
    }

    if planner_snapshot is not None:
        lock_data["planner_snapshot"] = planner_snapshot

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=lock_path.parent,
            prefix=".%s." % lock_path.name,
            suffix=".tmp",
            delete=False,
        ) as filep:
            temporary_path = Path(filep.name)
            os.fchmod(filep.fileno(), 0o600)
            yaml.safe_dump(lock_data, filep, sort_keys=False)
            filep.flush()
            os.fsync(filep.fileno())

        os.replace(temporary_path, lock_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return str(lock_path)
