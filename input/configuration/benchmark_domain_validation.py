"""Benchmark domain validation helpers."""

from __future__ import annotations

from pathlib import Path

from . import benchmark_stage_contract, selector_resolution, validation_utils

_fail = validation_utils.fail
_fail_unknown_keys = validation_utils.fail_unknown_keys
_child_key_path = validation_utils.child_key_path
_is_int = validation_utils.is_int

_BENCHMARK_RESERVED_TAG_KEYS = {"tier", "cluster", "role"}


def _validate_benchmark_stage(
    stage: dict,
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
) -> dict:
    if not isinstance(stage, dict):
        _fail(path, prefix, "must be a mapping")

    base_keys = {"id", "type", "assign_to", "tags", "config"}
    derived_keys = (
        {
            "selector",
            "selector_id",
            "resolved_vm_ids",
            "scope_identities",
        }
        if allow_derived
        else set()
    )
    _fail_unknown_keys(path, prefix, stage, base_keys | derived_keys)

    stage_id = stage.get("id")
    if not isinstance(stage_id, str) or not stage_id.strip():
        _fail(path, "%s.id" % (prefix), "must be a non-empty string")
    stage_id = stage_id.strip()

    stage_type = stage.get("type")
    if not isinstance(stage_type, str) or not stage_type.strip():
        _fail(path, "%s.type" % (prefix), "must be a non-empty string")
    stage_type = stage_type.strip()

    assign_to, canonical_selector, selector_id = selector_resolution.validate_assign_to(
        stage.get("assign_to"), path, "%s.assign_to" % (prefix)
    )
    if allow_derived:
        if require_derived:
            for derived_key in ("selector", "selector_id", "resolved_vm_ids", "scope_identities"):
                if derived_key not in stage:
                    _fail(
                        path,
                        "%s.%s" % (prefix, derived_key),
                        "is required in normalized lock config",
                    )
        selector_resolution.validate_selector_derivatives(
            stage,
            canonical_selector,
            selector_id,
            path,
            "%s.selector" % (prefix),
            "%s.selector_id" % (prefix),
            require_present=require_derived,
        )

    if "tags" in stage and stage["tags"] is None:
        _fail(path, "%s.tags" % (prefix), "must be a mapping")
    tags = stage.get("tags", {})
    if not isinstance(tags, dict):
        _fail(path, "%s.tags" % (prefix), "must be a mapping")
    normalized_tags = {}
    for key, value in tags.items():
        if not isinstance(key, str) or not key.strip():
            _fail(path, "%s.tags" % (prefix), "tag key must be a non-empty string")
        if not isinstance(value, str) or not value.strip():
            _fail(path, "%s.tags.%s" % (prefix, key), "tag value must be a non-empty string")
        key = key.strip()
        if key in _BENCHMARK_RESERVED_TAG_KEYS:
            _fail(
                path,
                "%s.tags.%s" % (prefix, key),
                "reserved benchmark tag key '%s' cannot be overwritten" % (key),
            )
        normalized_tags[key] = value.strip()

    if "config" in stage and stage["config"] is None:
        _fail(path, "%s.config" % (prefix), "must be a mapping")
    config = stage.get("config", {})
    if not isinstance(config, dict):
        _fail(path, "%s.config" % (prefix), "must be a mapping")
    benchmark_stage_contract.validate_stage_config_contract(stage_type, config, path, prefix)

    resolved_vm_ids = None
    if allow_derived and "resolved_vm_ids" in stage:
        resolved_vm_ids = stage.get("resolved_vm_ids")
        if not isinstance(resolved_vm_ids, list) or not all(
            _is_int(vm_id) and vm_id > 0 for vm_id in resolved_vm_ids
        ):
            _fail(path, "%s.resolved_vm_ids" % (prefix), "must be a list of vm_id integers")

    scope_identities = None
    if allow_derived and "scope_identities" in stage:
        scope_identities = stage.get("scope_identities")
        selector_resolution.validate_scope_identities(
            scope_identities,
            path,
            "%s.scope_identities" % (prefix),
        )

    normalized_stage = {
        "id": stage_id,
        "type": stage_type,
        "assign_to": assign_to,
        "tags": normalized_tags,
        "config": config,
        "selector": canonical_selector,
        "selector_id": selector_id,
    }
    if allow_derived and "resolved_vm_ids" in stage:
        normalized_stage["resolved_vm_ids"] = resolved_vm_ids
    if allow_derived and "scope_identities" in stage:
        normalized_stage["scope_identities"] = scope_identities
    return normalized_stage


def _validate_benchmark(
    benchmark: dict,
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
):
    if not isinstance(benchmark, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, benchmark, {"pipeline"})

    pipeline = benchmark.get("pipeline")
    if not isinstance(pipeline, list) or not pipeline:
        _fail(path, "%s.pipeline" % (prefix), "must be a non-empty list")
    if len(pipeline) > 1:
        _fail(
            path,
            "%s.pipeline" % (prefix),
            "must contain exactly one executable stage; ordered multi-stage execution "
            "is not supported (found %s stages)" % (len(pipeline),),
        )

    stage_ids = set()
    normalized_pipeline = []
    for index, stage in enumerate(pipeline):
        stage_prefix = "%s.pipeline[%s]" % (prefix, index)
        normalized_stage = _validate_benchmark_stage(
            stage,
            path,
            stage_prefix,
            allow_derived=allow_derived,
            require_derived=require_derived,
        )
        stage_id = normalized_stage["id"]
        if stage_id in stage_ids:
            _fail(path, "%s.id" % (stage_prefix), "duplicate benchmark stage id '%s'" % (stage_id))
        stage_ids.add(stage_id)
        normalized_pipeline.append(normalized_stage)
    benchmark["pipeline"] = normalized_pipeline


def validate_phase_domains(
    container: dict,
    targets: list[str],
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
):
    runs_application = "application" in set(targets)
    benchmark_key = _child_key_path(prefix, "benchmark")

    if runs_application:
        if "benchmark" in container:
            _validate_benchmark(
                container.get("benchmark"),
                path,
                benchmark_key,
                allow_derived=allow_derived,
                require_derived=require_derived,
            )
        else:
            _fail(path, benchmark_key, "is required when run.targets includes application")
        return

    if "benchmark" in container:
        _fail(path, benchmark_key, "must be omitted when run.targets does not include application")
