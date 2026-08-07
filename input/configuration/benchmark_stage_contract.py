"""Benchmark stage config contract validation helpers."""

from __future__ import annotations

from pathlib import Path


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_BENCHMARK_STAGE_KEY_INT_POSITIVE = ("integer >= 1", lambda value: _is_int(value) and value >= 1)
_BENCHMARK_STAGE_KEY_NUMBER_POSITIVE = (
    "number >= 0.001",
    lambda value: _is_number(value) and value >= 0.001,
)
_BENCHMARK_STAGE_KEY_NUMBER_STRICTLY_POSITIVE = (
    "number > 0",
    lambda value: _is_number(value) and value > 0,
)

BENCHMARK_STAGE_CONFIG_RULES = {
    "image_classification": {
        "frequency": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "duration": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_endpoint_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_endpoint_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
    "text_translation": {
        "frequency": _BENCHMARK_STAGE_KEY_NUMBER_STRICTLY_POSITIVE,
        "duration": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_endpoint_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_endpoint_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
    "empty": {
        "sleep_time": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
    "empty_kata": {
        "sleep_time": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "worker_ready_timeout_seconds": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
    "mem_usage": {
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
    "stress": {
        "stress_app_timeout": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "applications_per_worker": _BENCHMARK_STAGE_KEY_INT_POSITIVE,
        "application_worker_cpu": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
        "application_worker_memory": _BENCHMARK_STAGE_KEY_NUMBER_POSITIVE,
    },
}


def _fail(path: Path, key_path: str, message: str):
    raise ValueError("%s: %s: %s" % (path, key_path, message))


def validate_stage_config_contract(stage_type: str, config: dict, path: Path, prefix: str):
    """Validate benchmark stage config against strict known-stage contracts."""
    rules = BENCHMARK_STAGE_CONFIG_RULES.get(stage_type)
    if rules is None:
        return

    for key in sorted(config):
        if key not in rules:
            _fail(
                path,
                "%s.config.%s" % (prefix, key),
                "unexpected key for benchmark stage type '%s'" % (stage_type),
            )

    for key, (constraint_label, validator) in rules.items():
        key_path = "%s.config.%s" % (prefix, key)
        if key not in config:
            _fail(
                path,
                key_path,
                "is required for benchmark stage type '%s'" % (stage_type),
            )
        if not validator(config[key]):
            _fail(
                path,
                key_path,
                "must be %s for benchmark stage type '%s'" % (constraint_label, stage_type),
            )
