"""Centralized orchestration plan model and executors for software modules."""

from __future__ import annotations

import logging
import sys
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from infrastructure import orchestration_schema
from input.configuration import config_access
from resource_manager import legacy_execution
from resource_manager.endpoint import endpoint


@dataclass(frozen=True)
class PlanEntry:
    """Represent one executable orchestration action."""

    kind: str
    playbook: str = ""
    inventory: str = "vms"
    extra_vars: dict[str, Any] | None = None
    command: list[str] | str | None = None
    shell: bool = False
    check: bool = True
    owner_id: str = ""
    owner_type: str = ""
    legacy_target_groups: tuple[str, ...] | None = None


def _validate_entry(entry: PlanEntry):
    """Validate one plan entry before execution.

    Args:
        entry (PlanEntry): Entry to validate.
    """
    if entry.kind == "playbook":
        if not entry.playbook:
            logging.error("Plan entry kind=playbook requires non-empty playbook path")
            sys.exit(1)
        return

    if entry.kind == "command":
        if entry.command is None:
            logging.error("Plan entry kind=command requires command payload")
            sys.exit(1)
        return

    logging.error("Unsupported plan entry kind: %s", entry.kind)
    sys.exit(1)


def _with_owner(entry: PlanEntry, owner_id: str, owner_type: str) -> PlanEntry:
    """Return a plan entry with owner metadata populated when missing."""
    if entry.owner_id and entry.owner_type:
        return entry
    return replace(entry, owner_id=owner_id, owner_type=owner_type)


def _owner_metadata_from_module(module: dict) -> tuple[str, str]:
    """Extract stable owner metadata from a canonical software module record."""
    module_id = module.get("id")
    module_type = module.get("type")
    if not isinstance(module_id, str) or not module_id.strip():
        raise ValueError("Missing required software module id for planner snapshot")
    if not isinstance(module_type, str) or not module_type.strip():
        raise ValueError("Missing required software module type for planner snapshot")
    return module_id.strip(), module_type.strip()


def _plan_entry_snapshot(entry: PlanEntry) -> dict[str, Any]:
    """Serialize one validated plan entry for lock/debug snapshots."""
    _validate_entry(entry)
    if not entry.owner_id or not entry.owner_type:
        raise ValueError("Software plan entry is missing owner metadata")

    snapshot = {
        "kind": entry.kind,
        "owner_id": entry.owner_id,
        "owner_type": entry.owner_type,
    }
    if entry.kind == "playbook":
        snapshot["playbook"] = entry.playbook
    elif isinstance(entry.command, list):
        snapshot["command"] = list(entry.command)
    else:
        snapshot["command"] = entry.command
    return snapshot


def _resources_by_vm_id(config: dict) -> dict[int, dict]:
    """Return normalized infrastructure resources keyed by VM id."""
    normalized = config.get("normalized")
    if not isinstance(normalized, dict):
        raise ValueError("Missing required config path normalized")
    infrastructure = normalized.get("infrastructure")
    if not isinstance(infrastructure, dict):
        raise ValueError("Missing required config path normalized.infrastructure")
    resources = infrastructure.get("resources")
    if not isinstance(resources, list):
        raise ValueError("Missing required config path normalized.infrastructure.resources")

    by_vm_id: dict[int, dict] = {}
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
        if vm_id in by_vm_id:
            raise ValueError("Duplicate vm_id '%s' in normalized.infrastructure.resources" % (vm_id,))
        by_vm_id[vm_id] = resource
    return by_vm_id


def _resource_snapshot(resource: dict, record_kind: str) -> dict[str, Any]:
    """Serialize one normalized resource record for benchmark handoff metadata."""
    vm_id = resource.get("vm_id")
    cluster_id = resource.get("cluster_id")
    tier = resource.get("tier")
    index_in_cluster = resource.get("index_in_cluster")
    tags = resource.get("tags")

    if not isinstance(vm_id, int) or isinstance(vm_id, bool) or vm_id <= 0:
        raise ValueError("Invalid resolved resource vm_id for %s" % (record_kind,))
    if not isinstance(cluster_id, str) or not cluster_id.strip():
        raise ValueError("Invalid resolved resource cluster_id for %s" % (record_kind,))
    if not isinstance(tier, str) or not tier.strip():
        raise ValueError("Invalid resolved resource tier for %s" % (record_kind,))
    if (
        not isinstance(index_in_cluster, int)
        or isinstance(index_in_cluster, bool)
        or index_in_cluster < 0
    ):
        raise ValueError("Invalid resolved resource index_in_cluster for %s" % (record_kind,))
    if not isinstance(tags, dict):
        raise ValueError("Invalid resolved resource tags for %s" % (record_kind,))
    if tags.get("cluster") != cluster_id.strip():
        raise ValueError("Invalid resolved resource cluster tag for %s" % (record_kind,))
    if tags.get("tier") != tier.strip():
        raise ValueError("Invalid resolved resource tier tag for %s" % (record_kind,))

    return {
        "vm_id": vm_id,
        "cluster_id": cluster_id.strip(),
        "tier": tier.strip(),
        "index_in_cluster": index_in_cluster,
        "tags": deepcopy(tags),
    }


def _resolved_resource_snapshots(
    resolved_vm_ids: list[int],
    resources_by_vm_id: dict[int, dict],
    record_kind: str,
) -> list[dict[str, Any]]:
    """Build deterministic resource handoff records for a placement assignment."""
    resolved_resources = []
    for vm_id in resolved_vm_ids:
        resource = resources_by_vm_id.get(vm_id)
        if not isinstance(resource, dict):
            raise ValueError(
                "Resolved vm_id %s for %s is missing from normalized.infrastructure.resources"
                % (vm_id, record_kind)
            )
        resolved_resources.append(_resource_snapshot(resource, record_kind))
    return resolved_resources


def _assignment_snapshot(
    record: dict,
    record_kind: str,
    resources_by_vm_id: dict[int, dict],
    include_tags: bool = False,
) -> dict[str, Any]:
    """Build deterministic assignment metadata for software or benchmark records."""
    record_id = record.get("id")
    record_type = record.get("type")
    selector_id = record.get("selector_id")
    resolved_vm_ids = record.get("resolved_vm_ids")
    scope_identities = record.get("scope_identities")

    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("Missing required id for %s" % (record_kind,))
    if not isinstance(record_type, str) or not record_type.strip():
        raise ValueError("Missing required type for %s" % (record_kind,))
    if not isinstance(selector_id, str) or not selector_id.strip():
        raise ValueError("Missing required selector_id for %s" % (record_kind,))
    if not isinstance(resolved_vm_ids, list) or not all(
        isinstance(vm_id, int) and not isinstance(vm_id, bool) and vm_id > 0
        for vm_id in resolved_vm_ids
    ):
        raise ValueError("Missing required resolved_vm_ids for %s" % (record_kind,))
    if not resolved_vm_ids:
        raise ValueError("resolved_vm_ids must not be empty for %s" % (record_kind,))
    if not isinstance(scope_identities, list) or not scope_identities:
        raise ValueError("Missing required scope_identities for %s" % (record_kind,))

    snapshot = {
        "id": record_id.strip(),
        "type": record_type.strip(),
        "selector_id": selector_id.strip(),
        "resolved_vm_ids": list(resolved_vm_ids),
        "resolved_resources": _resolved_resource_snapshots(
            resolved_vm_ids,
            resources_by_vm_id,
            record_kind,
        ),
        "scope_identities": deepcopy(scope_identities),
    }
    if include_tags:
        tags = record.get("tags")
        if not isinstance(tags, dict):
            raise ValueError("Missing required tags for %s" % (record_kind,))
        snapshot["tags"] = deepcopy(tags)
    return snapshot


def execute_entries(runner, entries: list[PlanEntry]):
    """Execute plan entries with the shared runner.

    Args:
        runner (AnsibleRunner): Shared runner instance.
        entries (list[PlanEntry]): Ordered entries to execute.
    """
    for entry in entries:
        _validate_entry(entry)
        if entry.kind == "playbook":
            runner.run_playbook(
                entry.playbook,
                inventory=entry.inventory,
                extra_vars=entry.extra_vars,
                check=entry.check,
            )
        else:
            runner.run_command(entry.command, check=entry.check, shell=entry.shell)


def _endpoint_runtime_targets_endpoint(config, *, use_planner_snapshot: bool) -> bool:
    if not config_access.has_addon(config, "endpoint_runtime"):
        return False

    if use_planner_snapshot:
        return (
            config_access.software_module_assignment_handoff(config, "endpoint_runtime")[
                "resource_counts_by_tier"
            ].get("endpoint", 0)
            > 0
        )

    return (
        config_access.software_module_resolved_resource_count(
            config,
            "endpoint_runtime",
            tier="endpoint",
        )
        > 0
    )


def build_base_image_playbooks(
    config,
    base_names: list[str],
    *,
    use_planner_snapshot: bool = True,
) -> list[str]:
    """Return unique base-image install playbooks for the selected software modules.

    Args:
        config (dict): Parsed configuration.
        base_names (list[str]): Normalized base image names selected for preparation.

    Returns:
        list[str]: Repo-relative playbooks for base image software installation.
    """
    playbooks: list[str] = []
    rm_module = config["module"].get("resource_manager")

    for base_name in base_names:
        tier = orchestration_schema.tier_from_base_name(base_name)
        if tier is None:
            continue

        if tier == "endpoint":
            if not _endpoint_runtime_targets_endpoint(
                config,
                use_planner_snapshot=use_planner_snapshot,
            ):
                continue
            playbook = endpoint.base_install_playbook(config, tier)
        else:
            if not rm_module or not hasattr(rm_module, "base_install_playbook"):
                logging.error(
                    "Resource manager %s does not define base_install_playbook()",
                    config_access.orchestrator_name(config),
                )
                sys.exit(1)
            playbook = rm_module.base_install_playbook(config, tier)

        if playbook and playbook not in playbooks:
            playbooks.append(playbook)

    return playbooks


def build_software_phase_entries(
    config,
    *,
    use_planner_snapshot: bool = True,
) -> list[PlanEntry]:
    """Build centralized software-phase entries for the selected modules.

    Args:
        config (dict): Parsed configuration.

    Returns:
        list[PlanEntry]: Ordered entries for software phase execution.
    """
    entries: list[PlanEntry] = []
    rm_module = config["module"].get("resource_manager")
    if rm_module:
        if not hasattr(rm_module, "build_phase_plan"):
            logging.error(
                "Resource manager %s does not define build_phase_plan()",
                config_access.orchestrator_name(config),
            )
            sys.exit(1)
        orchestrator_owner = _owner_metadata_from_module(config_access.orchestrator_module(config))
        entries.extend(
            [
                _with_owner(entry, *orchestrator_owner)
                for entry in rm_module.build_phase_plan(config)
            ]
        )

    if config_access.has_addon(config, "openfaas"):
        addon_owner = _owner_metadata_from_module(
            config_access.software_module_by_type(config, "openfaas")
        )
        entries.append(
            PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/openfaas.yml",
                owner_id=addon_owner[0],
                owner_type=addon_owner[1],
                legacy_target_groups=("cloudcontroller",),
            )
        )

    if _endpoint_runtime_targets_endpoint(
        config,
        use_planner_snapshot=use_planner_snapshot,
    ):
        addon_owner = _owner_metadata_from_module(
            config_access.software_module_by_type(config, "endpoint_runtime")
        )
        entries.append(
            PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/endpoint_install.yml",
                owner_id=addon_owner[0],
                owner_type=addon_owner[1],
                legacy_target_groups=("endpoints",),
            )
        )

    legacy_execution.validate_software_execution_envelopes(
        config,
        entries,
        use_planner_snapshot=use_planner_snapshot,
    )
    return entries


def build_planner_snapshot(config) -> dict[str, Any]:
    """Build deterministic software-plan and benchmark-handoff metadata."""
    resources_by_vm_id = _resources_by_vm_id(config)
    plan_entries = build_software_phase_entries(config, use_planner_snapshot=False)
    plan_snapshots = [_plan_entry_snapshot(entry) for entry in plan_entries]

    execution_order = []
    seen_owner_ids = set()
    for entry in plan_snapshots:
        owner_id = entry["owner_id"]
        if owner_id in seen_owner_ids:
            continue
        seen_owner_ids.add(owner_id)
        execution_order.append(owner_id)

    snapshot = {
        "software_execution_order": execution_order,
        "software_plan_entries": plan_snapshots,
        "software_module_assignments": [
            _assignment_snapshot(
                module,
                "software module '%s'" % (module.get("id") or module.get("type") or "<unknown>",),
                resources_by_vm_id,
            )
            for module in config_access.software_modules(config)
        ],
        "benchmark_stage_assignments": [],
    }

    if config_access.runs_application(config):
        snapshot["benchmark_stage_assignments"] = [
            _assignment_snapshot(
                stage,
                "benchmark stage '%s'" % (stage.get("id") or stage.get("type") or "<unknown>",),
                resources_by_vm_id,
                include_tags=True,
            )
            for stage in config_access.benchmark_pipeline(config)
        ]
    return snapshot


def validate_planner_snapshot(
    observed_snapshot: dict[str, Any],
    expected_snapshot: dict[str, Any],
    prefix: str = "planner_snapshot",
):
    """Validate that a persisted planner snapshot matches the deterministic snapshot."""

    def _mismatch(path: str):
        raise ValueError(
            "%s must match deterministic planner snapshot derived from canonical config" % (path,)
        )

    def _validate(observed, expected, path: str):
        if isinstance(expected, dict):
            if not isinstance(observed, dict):
                raise ValueError("%s must be a mapping" % (path,))

            expected_keys = set(expected.keys())
            observed_keys = set(observed.keys())
            missing_keys = sorted(expected_keys - observed_keys)
            if missing_keys:
                raise ValueError("%s.%s is required in planner snapshot" % (path, missing_keys[0]))
            extra_keys = sorted(observed_keys - expected_keys)
            if extra_keys:
                raise ValueError("%s.%s is not part of the deterministic planner snapshot" % (path, extra_keys[0]))

            for key in sorted(expected.keys()):
                _validate(observed[key], expected[key], "%s.%s" % (path, key))
            return

        if isinstance(expected, list):
            if not isinstance(observed, list):
                raise ValueError("%s must be a list" % (path,))
            if len(observed) != len(expected):
                _mismatch(path)
            for index, (observed_item, expected_item) in enumerate(zip(observed, expected)):
                _validate(observed_item, expected_item, "%s[%s]" % (path, index))
            return

        if type(observed) is not type(expected) or observed != expected:
            _mismatch(path)

    _validate(observed_snapshot, expected_snapshot, prefix)


def run_post_phase_hook(runner):
    """Run optional post-install hook for the selected resource manager.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    module = runner.config["module"].get("resource_manager")
    if module is not None and hasattr(module, "post_phase_hook"):
        module.post_phase_hook(runner)
