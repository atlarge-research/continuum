"""YAML-first configuration loader and compatibility adapter.

Schema v1 composes three YAML documents:
- ContinuumExperiment
- ContinuumEnvironment
- ContinuumSoftware

The loader normalizes those documents and adapts them to the existing
runtime config shape so current modules keep working during migration.
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import (
    experiment_lock_writer,
    infrastructure_schema_validation,
    legacy_projection,
    benchmark_domain_validation,
    provider_schema_validation,
    profile_composition,
    run_schema_validation,
    runtime_module_loader,
    runtime_option_validation,
    selector_assignment_validation,
    software_domain_validation,
    validation_utils,
    yaml_io,
)
from resource_manager import plans

def _kind(data: dict) -> str:
    return str(data.get("kind", "")).strip()


def _validate_kind(data: dict, expected: str, path: Path):
    kind = _kind(data)
    if kind != expected:
        raise ValueError("Expected kind '%s' in %s, got '%s'" % (expected, path, kind))


_ALLOWED_TARGETS = {"infrastructure", "software", "application"}
_ALLOWED_TIERS = ("cloud", "edge", "endpoint")
_ALLOWED_IMAGE_PREFETCH_MODES = {"off", "on"}
_NETWORK_OVERRIDE_NUMERIC_KEYS = (
    "cloud_latency_avg",
    "cloud_latency_var",
    "cloud_throughput",
    "edge_latency_avg",
    "edge_latency_var",
    "edge_throughput",
    "cloud_edge_latency_avg",
    "cloud_edge_latency_var",
    "cloud_edge_throughput",
    "cloud_endpoint_latency_avg",
    "cloud_endpoint_latency_var",
    "cloud_endpoint_throughput",
    "edge_endpoint_latency_avg",
    "edge_endpoint_latency_var",
    "edge_endpoint_throughput",
)
_NETWORK_OVERRIDE_STRING_KEYS = ("cloud_location", "edge_location")
_NETWORK_OVERRIDE_KEYS_IN_ORDER = _NETWORK_OVERRIDE_NUMERIC_KEYS + _NETWORK_OVERRIDE_STRING_KEYS
_NETWORK_OVERRIDE_KEYS = set(_NETWORK_OVERRIDE_KEYS_IN_ORDER)
_DEFAULT_TIER_CPU_CORES = 1
_DEFAULT_TIER_CPU_QUOTA = 1.0
_DEFAULT_TIER_MEMORY_GB = 1.0
_DEFAULT_TIER_STORAGE_MBPS = 0.0

_fail_unknown_keys = validation_utils.fail_unknown_keys
_fail = validation_utils.fail
_child_key_path = validation_utils.child_key_path
_is_int = validation_utils.is_int


def _validate_schema_version(data: dict, path: Path):
    schema_version = data.get("schema_version")
    if not _is_int(schema_version):
        _fail(path, "schema_version", "must be integer 1")
    if schema_version != 1:
        _fail(path, "schema_version", "unsupported value %s (expected 1)" % (schema_version))


def _validate_run(run: dict, path: Path, prefix: str) -> list[str]:
    return run_schema_validation.validate_run(
        run,
        path,
        prefix,
        _ALLOWED_TARGETS,
        _ALLOWED_IMAGE_PREFETCH_MODES,
    )


def _build_tagged_resources(clusters: list[dict]) -> list[dict]:
    resources = []
    vm_id = 1
    for cluster in sorted(clusters, key=lambda item: item["id"]):
        count = int(cluster["resources"]["vms"]["count"])
        spec = copy.deepcopy(cluster["resources"]["vms"]["spec"])
        for index in range(count):
            resources.append(
                {
                    "vm_id": vm_id,
                    "cluster_id": cluster["id"],
                    "tier": cluster["tier"],
                    "index_in_cluster": index,
                    "spec": copy.deepcopy(spec),
                    "tags": {
                        "tier": cluster["tier"],
                        "cluster": cluster["id"],
                    },
                }
            )
            vm_id += 1
    return resources


def _validate_infrastructure(
    infrastructure: dict,
    path: Path,
    prefix: str,
    allow_derived: bool = False,
):
    infrastructure_schema_validation.validate_infrastructure(
        infrastructure,
        path,
        prefix,
        _ALLOWED_TIERS,
        _NETWORK_OVERRIDE_KEYS,
        _NETWORK_OVERRIDE_NUMERIC_KEYS,
        _NETWORK_OVERRIDE_STRING_KEYS,
        _DEFAULT_TIER_CPU_CORES,
        _DEFAULT_TIER_MEMORY_GB,
        _DEFAULT_TIER_CPU_QUOTA,
        _DEFAULT_TIER_STORAGE_MBPS,
        _build_tagged_resources,
        allow_derived=allow_derived,
    )


def _validate_provider(provider: dict, path: Path, prefix: str):
    provider_schema_validation.validate_provider(provider, path, prefix)


def _validate_software(
    software: dict,
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
):
    software_domain_validation.validate_software(
        software,
        path,
        prefix,
        allow_derived=allow_derived,
        require_derived=require_derived,
    )


def _validate_phase_domains(
    container: dict,
    targets: list[str],
    path: Path,
    prefix: str,
    allow_derived: bool = False,
    require_derived: bool = False,
):
    benchmark_domain_validation.validate_phase_domains(
        container,
        targets,
        path,
        prefix,
        allow_derived=allow_derived,
        require_derived=require_derived,
    )


def _validate_selector_resolution(normalized: dict, path: Path, prefix: str):
    selector_assignment_validation.validate_selector_resolution(normalized, path, prefix)


def _validate_experiment(experiment: dict, path: Path):
    _validate_kind(experiment, "ContinuumExperiment", path)
    _validate_schema_version(experiment, path)
    _fail_unknown_keys(
        path,
        "",
        experiment,
        {"schema_version", "kind", "use", "run", "infrastructure", "benchmark"},
    )

    use = experiment.get("use")
    if not isinstance(use, dict):
        _fail(path, "use", "must be a mapping")
    _fail_unknown_keys(path, "use", use, {"environment", "software"})

    env_ref = use.get("environment")
    if not isinstance(env_ref, str) or not env_ref.strip():
        _fail(path, "use.environment", "must be a non-empty string")

    sw_ref = use.get("software")
    if not isinstance(sw_ref, str) or not sw_ref.strip():
        _fail(path, "use.software", "must be a non-empty string")

    run = experiment.get("run")
    normalized_targets = _validate_run(run, path, "run")
    run["targets"] = normalized_targets
    _validate_infrastructure(experiment.get("infrastructure"), path, "infrastructure")
    _validate_phase_domains(experiment, normalized_targets, path, "", allow_derived=False)


def _validate_environment(environment: dict, path: Path):
    _validate_kind(environment, "ContinuumEnvironment", path)
    _validate_schema_version(environment, path)
    _fail_unknown_keys(path, "", environment, {"schema_version", "kind", "provider"})
    _validate_provider(environment.get("provider"), path, "provider")


def _validate_software_profile(software: dict, path: Path):
    _validate_kind(software, "ContinuumSoftware", path)
    _validate_schema_version(software, path)
    _fail_unknown_keys(path, "", software, {"schema_version", "kind", "software"})
    _validate_software(software.get("software"), path, "software")


def _normalize(experiment: dict, environment: dict, software: dict) -> dict:
    """Compose normalized schema-v1 object."""
    normalized = {
        "schema_version": experiment.get("schema_version", 1),
        "kind": "ContinuumNormalizedConfig",
        "run": copy.deepcopy(experiment.get("run", {})),
        "infrastructure": copy.deepcopy(experiment.get("infrastructure", {})),
        "provider": copy.deepcopy(environment.get("provider", {})),
        "software": copy.deepcopy(software.get("software", {})),
    }
    if "benchmark" in experiment:
        normalized["benchmark"] = copy.deepcopy(experiment.get("benchmark"))
    return normalized


def _validate_normalized(normalized: dict, path: Path, prefix: str, require_derived: bool = False):
    if not isinstance(normalized, dict):
        _fail(path, prefix, "must be a mapping")
    _fail_unknown_keys(
        path,
        prefix,
        normalized,
        {
            "schema_version",
            "kind",
            "run",
            "infrastructure",
            "provider",
            "software",
            "benchmark",
            "sources",
        },
    )

    run = normalized.get("run")
    run_prefix = _child_key_path(prefix, "run")
    infra_prefix = _child_key_path(prefix, "infrastructure")
    provider_prefix = _child_key_path(prefix, "provider")
    software_prefix = _child_key_path(prefix, "software")

    normalized_targets = _validate_run(run, path, run_prefix)
    run["targets"] = normalized_targets
    _validate_infrastructure(
        normalized.get("infrastructure"),
        path,
        infra_prefix,
        allow_derived=True,
    )
    _validate_provider(normalized.get("provider"), path, provider_prefix)
    _validate_software(
        normalized.get("software"),
        path,
        software_prefix,
        allow_derived=True,
        require_derived=require_derived,
    )
    _validate_phase_domains(
        normalized,
        normalized_targets,
        path,
        prefix,
        allow_derived=True,
        require_derived=require_derived,
    )
    _validate_selector_resolution(normalized, path, prefix)


def _compose_from_experiment(path: Path, experiment: dict) -> tuple[dict, dict, dict]:
    return profile_composition.compose_from_experiment(
        path,
        experiment,
        _validate_environment,
        _validate_software_profile,
    )


def start(parser, arg):
    """Parse YAML config and return legacy-compatible runtime config dict."""
    path = Path(arg).expanduser().resolve()
    data = yaml_io.load_yaml(path)
    kind = _kind(data)
    lock_planner_snapshot = None

    try:
        if kind == "ContinuumExperimentLock":
            normalized = copy.deepcopy(data.get("normalized_config", {}))
            if not normalized:
                _fail(path, "normalized_config", "is required")
            _validate_normalized(normalized, path, "normalized_config", require_derived=True)
            if "planner_snapshot" in data:
                lock_planner_snapshot = copy.deepcopy(data.get("planner_snapshot"))
        else:
            _validate_experiment(data, path)
            environment, software, sources = _compose_from_experiment(path, data)
            normalized = _normalize(data, environment, software)
            normalized["sources"] = sources
            _validate_normalized(normalized, path, "normalized_config", require_derived=False)
    except (ValueError, TypeError, FileNotFoundError) as exc:
        parser.error("YAML config validation failed: %s" % (exc))

    # Resolve module-specific defaults/constraints directly into canonical domain config.
    bootstrap_config = legacy_projection.to_legacy_config(
        normalized,
        _ALLOWED_TIERS,
        _NETWORK_OVERRIDE_KEYS_IN_ORDER,
    )
    runtime_module_loader.dynamic_import(parser, bootstrap_config)
    runtime_option_validation.apply_module_options(parser, bootstrap_config)

    # Rebuild runtime config from canonical normalized domains after option normalization.
    config = legacy_projection.to_legacy_config(
        bootstrap_config["normalized"],
        _ALLOWED_TIERS,
        _NETWORK_OVERRIDE_KEYS_IN_ORDER,
    )
    runtime_module_loader.dynamic_import(parser, config)
    runtime_module_loader.add_constants(parser, config)
    runtime_option_validation.verify_options(parser, config)

    planner_snapshot = plans.build_planner_snapshot(config)
    if lock_planner_snapshot is not None:
        try:
            plans.validate_planner_snapshot(lock_planner_snapshot, planner_snapshot)
        except ValueError as exc:
            parser.error("YAML config validation failed: %s" % (exc,))
    config["planner_snapshot"] = planner_snapshot

    config["input_path"] = str(path)
    return config


def write_experiment_lock(config):
    return experiment_lock_writer.write_experiment_lock(config)
