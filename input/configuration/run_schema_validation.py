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


def validate_run(
    run: dict,
    path: Path,
    prefix: str,
    allowed_targets: set[str],
    allowed_image_prefetch_modes: set[str],
) -> list[str]:
    if not isinstance(run, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(
        path,
        prefix,
        run,
        {"targets", "dry_run", "clean", "image_prefetch", "prepare_for_resume"},
    )

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

    for key in ("dry_run", "clean", "prepare_for_resume"):
        if key in run and not isinstance(run[key], bool):
            _fail(path, "%s.%s" % (prefix, key), "must be boolean")
        if key not in run:
            run[key] = False

    if run["prepare_for_resume"] and normalized_targets != ["infrastructure"]:
        _fail(
            path,
            "%s.prepare_for_resume" % (prefix),
            "is only valid when run.targets is exactly [infrastructure]",
        )

    image_prefetch = run.get("image_prefetch", "off")
    if not isinstance(image_prefetch, str):
        _fail(path, "%s.image_prefetch" % (prefix), "must be one of off, on")
    image_prefetch = image_prefetch.strip().lower()
    if image_prefetch not in allowed_image_prefetch_modes:
        _fail(
            path,
            "%s.image_prefetch" % (prefix),
            "must be one of %s" % (", ".join(sorted(allowed_image_prefetch_modes))),
        )
    run["image_prefetch"] = image_prefetch
    return normalized_targets
