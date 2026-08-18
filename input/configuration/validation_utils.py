"""Shared validation utility helpers for config parsing modules."""

from __future__ import annotations

import math
from pathlib import Path


def fail(path: Path, key_path: str, message: str):
    raise ValueError("%s: %s: %s" % (path, key_path, message))


def child_key_path(prefix: str, key: str) -> str:
    if prefix:
        return "%s.%s" % (prefix, key)
    return key


def fail_unknown_keys(path: Path, key_path: str, mapping: dict, allowed: set[str]):
    for key in sorted(mapping.keys()):
        if key not in allowed:
            unknown_key_path = child_key_path(key_path, key) if key_path else key
            fail(path, unknown_key_path, "unexpected key for schema v1")


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_finite_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def is_float_representable_number(value) -> bool:
    """Return whether a finite builtin number can be normalized to ``float`` safely."""
    if not is_finite_number(value):
        return False
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(converted)
