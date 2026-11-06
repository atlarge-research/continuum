"""Run-domain schema validation helpers."""

from __future__ import annotations

from pathlib import Path

from . import runtime_phase_targets, validation_utils

_fail = validation_utils.fail
_fail_unknown_keys = validation_utils.fail_unknown_keys


def normalize_targets(
    targets: list,
    path: Path,
    prefix: str,
    allowed_targets: set[str],
) -> list[str]:
    normalized = []
    seen = set()
    for index, target in enumerate(targets):
        key_path = "%s.targets[%s]" % (prefix, index)
        if not isinstance(target, str):
            _fail(path, key_path, "must be a string")
        target = target.strip()
        if target not in allowed_targets:
            _fail(
                path,
                key_path,
                "unsupported run target '%s' (allowed: %s)"
                % (target, ", ".join(sorted(allowed_targets))),
            )
        if target in seen:
            _fail(path, key_path, "duplicate run target '%s'" % (target))
        seen.add(target)
        normalized.append(target)
    return normalized


def validate_run_keys(run: dict, path: Path | str, prefix: str) -> None:
    """Validate the run mapping and its keys without applying defaults."""
    if not isinstance(run, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(path, prefix, run, {"targets", "registry_refresh", "prepare_for_resume"})


def validate_run(
    run: dict,
    path: Path,
    prefix: str,
    allowed_targets: set[str],
    allowed_registry_refresh_modes: set[str],
) -> list[str]:
    validate_run_keys(run, path, prefix)

    targets = run.get("targets")
    if not isinstance(targets, list) or not targets:
        _fail(path, "%s.targets" % (prefix), "must be a non-empty list")

    normalized_targets = normalize_targets(targets, path, prefix, allowed_targets)
    if not normalized_targets:
        _fail(path, "%s.targets" % (prefix), "must contain at least one supported target")
    if runtime_phase_targets.fresh_application_without_software(normalized_targets):
        _fail(
            path,
            "%s.targets" % (prefix),
            "fresh application execution requires the software phase when infrastructure "
            "is selected",
        )

    if not isinstance(run.setdefault("prepare_for_resume", False), bool):
        _fail(path, "%s.prepare_for_resume" % (prefix), "must be boolean")

    if run["prepare_for_resume"] and normalized_targets != ["infrastructure"]:
        _fail(
            path,
            "%s.prepare_for_resume" % (prefix),
            "is only valid when run.targets is exactly [infrastructure]",
        )

    registry_refresh = run.get("registry_refresh", "missing")
    if not isinstance(registry_refresh, str):
        _fail(path, "%s.registry_refresh" % (prefix), "must be one of all, missing")
    registry_refresh = registry_refresh.strip().lower()
    if registry_refresh not in allowed_registry_refresh_modes:
        _fail(
            path,
            "%s.registry_refresh" % (prefix),
            "must be one of %s" % (", ".join(sorted(allowed_registry_refresh_modes))),
        )
    run["registry_refresh"] = registry_refresh
    return normalized_targets
