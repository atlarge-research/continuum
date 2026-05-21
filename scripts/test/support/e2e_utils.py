"""\
Test utilities for Continuum end-to-end testing framework.
Provides functions for config discovery, base image management, success detection, and result storage.
"""

import argparse
import csv
import fnmatch
import getpass
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

from input.configuration import resume_contract, yaml_parser

_ORCHESTRATOR_MODULE_TYPES = ("none", "kubernetes", "kubeedge", "kubecontrol", "kube_kata", "mist")
_VERIFY_NETWORK_PROFILES = None


def _load_verify_network_profiles():
    """Load the structured network-profile verifier from this test directory."""
    global _VERIFY_NETWORK_PROFILES
    if _VERIFY_NETWORK_PROFILES is None:
        module_path = Path(__file__).resolve().parents[1] / "verify_network_profiles.py"
        spec = importlib.util.spec_from_file_location(
            "continuum_verify_network_profiles_runtime",
            module_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VERIFY_NETWORK_PROFILES = module
    return _VERIFY_NETWORK_PROFILES


def discover_config_files(
    directories: List[str],
    exclude_patterns: List[str],
    manifest: Optional[Dict] = None,
    provider: Optional[str] = None,
) -> List[str]:
    """Discover all configuration files matching the criteria.

    Args:
        directories: List of directories to search in
        exclude_patterns: List of patterns to exclude
        manifest: Optional test manifest with include/exclude patterns
        provider: Optional provider filter (qemu, gcp, aws)

    Returns:
        List of config file paths
    """
    config_files = set()

    # First, collect supported YAML config files from specified directories.
    for directory in directories:
        if not os.path.exists(directory):
            continue
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".yaml") or file.endswith(".yml"):
                    file_path = os.path.join(root, file)
                    config_files.add(file_path)

    # Apply exclude patterns
    for pattern in exclude_patterns:
        config_files = {
            f
            for f in config_files
            if not fnmatch.fnmatch(f, pattern) and not fnmatch.fnmatch(os.path.basename(f), pattern)
        }

    # Apply manifest include/exclude if provided
    if manifest:
        config_files = apply_manifest_filter(config_files, manifest)

    # Filter by provider if specified
    if provider:
        filtered_files = []
        for config_file in config_files:
            try:
                parsed = parse_config_simple(config_file)
                if parsed.get("infrastructure", {}).get("provider") == provider:
                    filtered_files.append(config_file)
            except Exception:
                # Skip files that can't be parsed
                continue
        config_files = filtered_files

    return sorted(list(config_files))


def apply_manifest_filter(config_files: Set[str], manifest: Dict) -> Set[str]:
    """Apply include/exclude patterns from test manifest.

    Args:
        config_files: Set of config file paths
        manifest: Manifest dict with 'include' and 'exclude' lists

    Returns:
        Filtered set of config file paths
    """
    result = set()

    # If include patterns exist, only include matching files
    if "include" in manifest and manifest["include"]:
        for pattern in manifest["include"]:
            for config_file in config_files:
                if fnmatch.fnmatch(config_file, pattern) or fnmatch.fnmatch(
                    os.path.basename(config_file), pattern
                ):
                    result.add(config_file)
    else:
        # No include patterns means include all
        result = config_files.copy()

    # Apply exclude patterns
    if "exclude" in manifest and manifest["exclude"]:
        for pattern in manifest["exclude"]:
            result = {
                f
                for f in result
                if not fnmatch.fnmatch(f, pattern)
                and not fnmatch.fnmatch(os.path.basename(f), pattern)
            }

    return result


def parse_config_simple(config_path: str) -> Dict:
    """Parse a config file to extract basic information without full validation.

    Args:
        config_path: Path to config file

    Returns:
        Dictionary with parsed config values
    """
    _, ext = os.path.splitext(config_path)
    if ext not in (".yaml", ".yml"):
        raise ValueError(
            "Only YAML experiment/lock configs are supported by the test runner, got %s"
            % (config_path)
        )
    return parse_yaml_config_simple(config_path)


def parse_yaml_config_simple(config_path: str) -> Dict:
    """Parse YAML experiment/lock config to extract basic information."""
    path = Path(config_path).expanduser().resolve()
    data = _load_yaml(path)
    data = _normalized_payload_for_testing(path, data)

    result = {
        "infrastructure": {},
        "benchmark": {},
    }

    infrastructure = data.get("infrastructure", {})
    clusters = infrastructure.get("clusters", [])
    if not isinstance(clusters, list):
        clusters = []

    tier_aggregate = {
        "cloud": {"count": 0, "cores": 4},
        "edge": {"count": 0, "cores": 2},
        "endpoint": {"count": 0, "cores": 1},
    }
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        tier = cluster.get("tier")
        if tier not in tier_aggregate:
            continue
        vms = ((cluster.get("resources") or {}).get("vms") or {})
        count = vms.get("count", 0)
        if not isinstance(count, int):
            continue
        if count < 0:
            continue
        tier_aggregate[tier]["count"] += count
        spec = vms.get("spec", {})
        if isinstance(spec, dict) and isinstance(spec.get("cores"), int) and spec["cores"] > 0:
            tier_aggregate[tier]["cores"] = spec["cores"]

    provider = data.get("provider", {})
    provider_cfg = provider.get("config", {})
    software = data.get("software", {})
    modules = software.get("modules", [])
    if not isinstance(modules, list):
        modules = []

    orchestrator_name = "none"
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_type = module.get("type")
        if isinstance(module_type, str) and module_type in _ORCHESTRATOR_MODULE_TYPES:
            orchestrator_name = module_type
            break

    result["infrastructure"]["provider"] = provider.get("name", "qemu")
    result["infrastructure"]["delete_on_exit"] = bool(provider_cfg.get("delete_on_exit", False))
    target_set = set(_run_targets(data))
    result["infrastructure"]["infra_only"] = (
        "infrastructure" in target_set
        and "software" not in target_set
        and "application" not in target_set
    )
    result["infrastructure"]["cloud_nodes"] = int(tier_aggregate["cloud"]["count"])
    result["infrastructure"]["edge_nodes"] = int(tier_aggregate["edge"]["count"])
    result["infrastructure"]["endpoint_nodes"] = int(tier_aggregate["endpoint"]["count"])
    result["infrastructure"]["cloud_cores"] = int(tier_aggregate["cloud"]["cores"])
    result["infrastructure"]["edge_cores"] = int(tier_aggregate["edge"]["cores"])
    result["infrastructure"]["endpoint_cores"] = int(tier_aggregate["endpoint"]["cores"])
    result["infrastructure"]["cpu_pin"] = bool(provider_cfg.get("cpu_pin", False))
    result["infrastructure"]["base_path"] = os.path.expanduser(provider_cfg.get("base_path", "~"))
    ip_cfg = provider_cfg.get("ip", {})
    result["infrastructure"]["middleIP"] = int(ip_cfg.get("middle", 100))
    result["infrastructure"]["middleIP_base"] = int(ip_cfg.get("middle_base", 90))
    external_machines = provider_cfg.get("external_physical_machines", [])
    result["infrastructure"]["external_physical_machines"] = (
        ",".join(external_machines) if external_machines else None
    )

    result["benchmark"]["resource_manager"] = orchestrator_name
    result["benchmark"]["resource_manager_only"] = (
        "software" in target_set and "application" not in target_set
    )
    return result


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as filep:
        data = yaml.safe_load(filep) or {}
    if not isinstance(data, dict):
        raise ValueError("Expected top-level YAML mapping in %s" % (path))
    return data


def _resolve_profile_path(experiment_path: Path, profile_kind: str, ref: str) -> Path:
    ref_path = Path(ref).expanduser()
    if ref_path.is_absolute() and ref_path.exists():
        return ref_path

    candidates = [
        (experiment_path.parent / ref).expanduser(),
        (experiment_path.parent / ("%s.yaml" % ref)).expanduser(),
        (experiment_path.parent / ("%s.yml" % ref)).expanduser(),
        (_repo_root() / ref).expanduser(),
        (_repo_root() / ("%s.yaml" % ref)).expanduser(),
        (_repo_root() / ("%s.yml" % ref)).expanduser(),
        (_repo_root() / "configs" / "profiles" / profile_kind / ("%s.yaml" % ref)),
        (Path.home() / ".continuum" / "configs" / "profiles" / profile_kind / ("%s.yaml" % ref)),
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError("Could not resolve %s profile reference '%s'" % (profile_kind, ref))


def _run_targets(data: Dict) -> List[str]:
    run = data.get("run", {})
    if not isinstance(run, dict):
        return ["infrastructure", "software", "application"]
    targets = run.get("targets", ["infrastructure", "software", "application"])
    if not isinstance(targets, list) or not targets:
        return ["infrastructure", "software", "application"]
    return [target for target in targets if isinstance(target, str)]


def _compose_experiment(path: Path, experiment: Dict) -> Dict:
    use = experiment.get("use", {})
    if not isinstance(use, dict):
        raise ValueError("%s: missing use mapping in experiment config" % path)

    env_ref = use.get("environment")
    sw_ref = use.get("software")
    if not isinstance(env_ref, str) or not env_ref:
        raise ValueError("%s: missing use.environment in experiment config" % path)
    if not isinstance(sw_ref, str) or not sw_ref:
        raise ValueError("%s: missing use.software in experiment config" % path)

    env_path = _resolve_profile_path(path, "environment", env_ref)
    sw_path = _resolve_profile_path(path, "software", sw_ref)
    environment = _load_yaml(env_path)
    software = _load_yaml(sw_path)

    return {
        "run": experiment.get("run", {}),
        "infrastructure": experiment.get("infrastructure", {}),
        "provider": (environment.get("provider") or {}),
        "software": (software.get("software") or {}),
        "benchmark": experiment.get("benchmark", {}),
    }


def _normalized_payload_for_testing(path: Path, data: Dict) -> Dict:
    kind = str(data.get("kind", "")).strip()
    if kind == "ContinuumExperimentLock":
        normalized = data.get("normalized_config", {})
        if not isinstance(normalized, dict) or not normalized:
            raise ValueError("%s: lock config must contain normalized_config mapping" % path)
        return normalized
    if kind == "ContinuumExperiment":
        return _compose_experiment(path, data)
    raise ValueError(
        "%s: unsupported YAML kind '%s' for test runner (expected ContinuumExperiment or "
        "ContinuumExperimentLock)" % (path, kind)
    )


def get_username() -> str:
    """Get the current username for base image naming.

    Returns:
        Username string
    """
    return getpass.getuser()


def identify_base_images(config: Dict, base_path_override: Optional[str] = None) -> List[str]:
    """Identify which base images will be needed for a given config.

    Args:
        config: Parsed config dictionary
        base_path_override: Optional override for base_path

    Returns:
        List of expected base image names (without .qcow2 extension)
    """
    base_images = []
    infra = config.get("infrastructure", {})
    benchmark = config.get("benchmark", {})

    username = get_username()
    provider = infra.get("provider", "qemu")

    # Only QEMU uses base images in this way
    if provider != "qemu":
        return base_images

    infra_only = infra.get("infra_only", False)

    if infra_only:
        # For infra_only, base image is just "base"
        base_images.append(f"base0_{username}")
    else:
        # Determine resource manager
        resource_manager = benchmark.get("resource_manager", "none")
        if resource_manager == "mist":
            resource_manager = "kubeedge"  # Mist uses KubeEdge setup

        # Cloud base images
        if infra.get("cloud_nodes", 0) > 0:
            base_images.append(f"base_cloud_{resource_manager}0_{username}")

        # Edge base images
        if infra.get("edge_nodes", 0) > 0:
            base_images.append(f"base_edge_{resource_manager}0_{username}")

        # Endpoint base images
        if infra.get("endpoint_nodes", 0) > 0:
            base_images.append(f"base_endpoint0_{username}")

    return base_images


def get_base_image_paths(base_images: List[str], base_path: str) -> List[str]:
    """Get full paths to base image files.

    Args:
        base_images: List of base image names (without extension)
        base_path: Base path where images are stored

    Returns:
        List of full paths to .qcow2 files
    """
    image_paths = []
    images_dir = os.path.join(base_path, ".continuum", "images")

    for base_name in base_images:
        image_path = os.path.join(images_dir, f"{base_name}.qcow2")
        image_paths.append(image_path)

    return image_paths


def delete_base_images(base_image_paths: List[str]) -> List[str]:
    """Delete base image files if they exist.

    Args:
        base_image_paths: List of full paths to base image files

    Returns:
        List of images that were actually deleted
    """
    deleted = []
    for image_path in base_image_paths:
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
                deleted.append(image_path)
            except OSError as e:
                # Log but continue
                print(f"Warning: Could not delete {image_path}: {e}")
    return deleted


def should_rebuild_base_images(
    test_run_count: int,
    rebuild_frequency: int,
    force_rebuild: bool,
    use_cache: bool,
) -> bool:
    """Determine if base images should be rebuilt.

    Args:
        test_run_count: Current test run number
        rebuild_frequency: How often to rebuild (every N runs)
        force_rebuild: Force rebuild flag
        use_cache: Use cache only flag

    Returns:
        True if images should be rebuilt
    """
    if use_cache:
        return False
    if force_rebuild:
        return True
    if rebuild_frequency > 0 and test_run_count % rebuild_frequency == 0:
        return True
    return False


def verify_network_validation_results(config: Dict) -> Tuple[bool, str]:
    """Validate structured network-validation netperf results for one run."""
    base_path = config.get("infrastructure", {}).get("base_path")
    if not isinstance(base_path, str) or not base_path.strip():
        return False, "Network validation artifact missing: infrastructure.base_path is not set"

    verifier = _load_verify_network_profiles()
    try:
        results_file = verifier.latest_results_file(base_path=base_path)
    except FileNotFoundError as exc:
        return False, "Network validation artifact missing: %s" % (exc,)

    try:
        results = verifier.load_results(results_file)
    except OSError as exc:
        return False, "Network validation artifact unreadable: %s" % (exc,)

    if not results:
        return False, "Network validation artifact invalid: no netperf entries found"

    failures = verifier.validate_results(results)
    if failures:
        return False, "Network validation profile mismatch: %s" % ("; ".join(failures),)

    return True, "network_validation_results=%s" % (results_file,)


def _benchmark_metrics_dir(base_path: str) -> str:
    return os.path.join(base_path, ".continuum", "logs", "benchmark")


def _latest_benchmark_metrics_manifest(base_path: str) -> str:
    metrics_dir = _benchmark_metrics_dir(base_path)
    if not os.path.isdir(metrics_dir):
        raise FileNotFoundError("benchmark metrics directory not found: %s" % (metrics_dir,))

    manifests = [
        os.path.join(metrics_dir, name)
        for name in os.listdir(metrics_dir)
        if name.endswith("_metrics_manifest.json")
    ]
    if not manifests:
        raise FileNotFoundError("no benchmark metrics manifest found under %s" % (metrics_dir,))
    return max(manifests, key=lambda path: (os.path.getmtime(path), path))


def _validate_benchmark_metric_rows(rows, table_config):
    label = table_config["label"]
    required_columns = table_config["columns"]
    min_rows = table_config["min_rows"]
    numeric_columns = table_config.get("numeric_columns", required_columns)

    if len(rows) < min_rows:
        return False, "Benchmark metric artifact invalid: %s has %s row(s), expected %s" % (
            label,
            len(rows),
            min_rows,
        )

    for column in numeric_columns:
        for row_index, row in enumerate(rows[:min_rows], 1):
            value = row.get(column)
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False, (
                    "Benchmark metric artifact invalid: %s row %s column %s is not numeric"
                    % (label, row_index, column)
                )
            if not math.isfinite(number):
                return False, (
                    "Benchmark metric artifact invalid: %s row %s column %s is not finite"
                    % (label, row_index, column)
                )

    stat_ok, stat_reason = _validate_benchmark_metric_stat_assertions(rows, table_config)
    if not stat_ok:
        return False, stat_reason

    return True, "benchmark_metric_rows_valid"


def _validate_benchmark_metric_stat_assertions(rows, table_config):
    label = table_config["label"]
    assertions = table_config.get("stat_assertions", [])
    if assertions is None:
        return True, "benchmark_metric_stats_valid"
    if not isinstance(assertions, list):
        return False, "Benchmark metric artifact config invalid: stat_assertions"

    allowed_bounds = {
        "min": "minimum",
        "max": "maximum",
        "mean_min": "mean minimum",
        "mean_max": "mean maximum",
    }
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return False, "Benchmark metric artifact config invalid: stat_assertions entry"

        column = assertion.get("column")
        if not isinstance(column, str) or not column:
            return False, "Benchmark metric artifact config invalid: stat_assertions column"

        values = []
        for row_index, row in enumerate(rows, 1):
            value = row.get(column)
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False, (
                    "Benchmark metric artifact invalid: %s row %s column %s is not numeric"
                    % (label, row_index, column)
                )
            if not math.isfinite(number):
                return False, (
                    "Benchmark metric artifact invalid: %s row %s column %s is not finite"
                    % (label, row_index, column)
                )
            values.append(number)

        if not values:
            return False, (
                "Benchmark metric artifact invalid: %s column %s has no numeric rows"
                % (label, column)
            )

        observed = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }

        for bound in allowed_bounds:
            if bound not in assertion:
                continue
            threshold = _benchmark_stat_threshold(assertion, bound)
            if threshold is None:
                return False, (
                    "Benchmark metric artifact config invalid: stat_assertions %s for %s"
                    % (bound, column)
                )
            passed = _benchmark_stat_bound_passed(observed, bound, threshold)
            if not passed:
                return False, (
                    "Benchmark metric artifact statistic failed: %s column %s %s %s "
                    "outside bound %s"
                    % (
                        label,
                        column,
                        allowed_bounds[bound],
                        _benchmark_stat_observed_value(observed, bound),
                        threshold,
                    )
                )

    return True, "benchmark_metric_stats_valid"


def _benchmark_stat_threshold(assertion, bound):
    if bound not in assertion:
        return None
    try:
        threshold = float(assertion[bound])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(threshold):
        return None
    return threshold


def _benchmark_stat_observed_value(observed, bound):
    if bound in ("min", "max"):
        return observed[bound]
    return observed["mean"]


def _benchmark_stat_bound_passed(observed, bound, threshold):
    if bound == "min":
        return observed["min"] >= threshold
    if bound == "max":
        return observed["max"] <= threshold
    if bound == "mean_min":
        return observed["mean"] >= threshold
    if bound == "mean_max":
        return observed["mean"] <= threshold
    return False


def _extract_run_timestamp(stdout: str) -> Optional[str]:
    """Extract Continuum's run timestamp from the log-file announcement."""
    match = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})_[^\s/]*\.log", stdout)
    if match:
        return match.group(1)
    return None


def verify_benchmark_metric_artifacts(
    config: Dict,
    table_configs: List[Dict],
    expected_timestamp: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate structured benchmark metric artifacts for one application run."""
    if not isinstance(table_configs, list):
        return False, "Benchmark metric artifact config invalid: expected list"

    base_path = config.get("infrastructure", {}).get("base_path")
    if not isinstance(base_path, str) or not base_path.strip():
        return False, "Benchmark metric artifact missing: infrastructure.base_path is not set"

    try:
        manifest_path = _latest_benchmark_metrics_manifest(base_path)
    except FileNotFoundError as exc:
        return False, "Benchmark metric artifact missing: %s" % (exc,)

    try:
        with open(manifest_path, "r", encoding="utf-8") as filep:
            manifest = json.load(filep)
    except (OSError, json.JSONDecodeError) as exc:
        return False, "Benchmark metric artifact unreadable: %s" % (exc,)

    if not isinstance(manifest, dict):
        return False, "Benchmark metric artifact invalid: manifest must be a mapping"
    if manifest.get("schema_version") != 1:
        return False, "Benchmark metric artifact invalid: unsupported schema_version %r" % (
            manifest.get("schema_version"),
        )
    if manifest.get("kind") != "ContinuumBenchmarkMetrics":
        return False, "Benchmark metric artifact invalid: unexpected kind %r" % (
            manifest.get("kind"),
        )
    if expected_timestamp and manifest.get("timestamp") != expected_timestamp:
        return False, (
            "Benchmark metric artifact missing: latest manifest timestamp %r does not match "
            "current run timestamp %r"
            % (manifest.get("timestamp"), expected_timestamp)
        )

    tables = manifest.get("tables")
    if not isinstance(tables, list) or not tables:
        return False, "Benchmark metric artifact invalid: manifest has no tables"

    tables_by_label = {}
    for table in tables:
        if not isinstance(table, dict):
            return False, "Benchmark metric artifact invalid: table entry must be mapping"
        label = table.get("label")
        if isinstance(label, str) and label:
            tables_by_label[label] = table

    for table_config in table_configs:
        if not isinstance(table_config, dict):
            return False, "Benchmark metric artifact config invalid: table entry must be mapping"

        label = table_config.get("label")
        columns = table_config.get("columns", [])
        min_rows = table_config.get("min_rows", 1)
        numeric_columns = table_config.get("numeric_columns", columns)
        if not isinstance(label, str) or not label:
            return False, "Benchmark metric artifact config invalid: label"
        if not isinstance(columns, list) or not all(
            isinstance(column, str) and column for column in columns
        ):
            return False, "Benchmark metric artifact config invalid: columns"
        if not isinstance(numeric_columns, list) or not all(
            isinstance(column, str) and column for column in numeric_columns
        ):
            return False, "Benchmark metric artifact config invalid: numeric_columns"
        if not isinstance(min_rows, int) or min_rows < 1:
            return False, "Benchmark metric artifact config invalid: min_rows"

        table = tables_by_label.get(label)
        if table is None:
            return False, "Benchmark metric artifact missing table: %s" % (label,)

        table_columns = table.get("columns")
        missing_columns = [
            column for column in columns if not isinstance(table_columns, list) or column not in table_columns
        ]
        if missing_columns:
            return False, "Benchmark metric artifact missing columns for %s: %s" % (
                label,
                ", ".join(missing_columns),
            )

        path = table.get("path")
        if not isinstance(path, str) or not path:
            return False, "Benchmark metric artifact invalid: %s path is missing" % (label,)
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(manifest_path), path)
        if not os.path.isfile(path):
            return False, "Benchmark metric artifact missing table file: %s" % (path,)

        try:
            with open(path, "r", encoding="utf-8", newline="") as filep:
                reader = csv.DictReader(filep)
                rows = list(reader)
                fieldnames = reader.fieldnames or []
        except OSError as exc:
            return False, "Benchmark metric artifact unreadable: %s" % (exc,)

        missing_file_columns = [column for column in columns if column not in fieldnames]
        if missing_file_columns:
            return False, "Benchmark metric artifact missing columns for %s: %s" % (
                label,
                ", ".join(missing_file_columns),
            )

        row_ok, row_reason = _validate_benchmark_metric_rows(
            rows,
            {
                "label": label,
                "columns": columns,
                "min_rows": min_rows,
                "numeric_columns": numeric_columns,
                "stat_assertions": table_config.get("stat_assertions", []),
            },
        )
        if not row_ok:
            return False, row_reason

    return True, "benchmark_metric_artifacts=%s" % (manifest_path,)


def _strip_log_prefix(line: str) -> str:
    """Return a log message line without Continuum's logging prefix when present."""
    if "] " in line:
        return line.split("] ", 1)[1]
    return line


def _line_contains_all(line: str, markers: List[str]) -> bool:
    return all(marker in line for marker in markers)


def _numeric_metric_row_count(lines: List[str], start_index: int) -> int:
    rows = 0
    for line in lines[start_index:]:
        message = _strip_log_prefix(line).strip()
        if not message:
            continue
        if set(message) <= {"-"}:
            if rows:
                break
            continue
        if message.endswith("OUTPUT"):
            break
        if re.search(r"[-+]?(?:\d+\.\d+|\d+)", message):
            rows += 1
    return rows


def verify_benchmark_metric_tables(stdout: str, table_configs: List[Dict]) -> Tuple[bool, str]:
    """Validate configured benchmark metric tables in captured stdout."""
    if not isinstance(table_configs, list):
        return False, "Benchmark metric evidence config invalid: expected list"

    lines = stdout.splitlines()
    for table_config in table_configs:
        if not isinstance(table_config, dict):
            return False, "Benchmark metric evidence config invalid: table entry must be mapping"

        label = table_config.get("label")
        columns = table_config.get("columns", [])
        min_rows = table_config.get("min_rows", 1)
        if not isinstance(label, str) or not label:
            return False, "Benchmark metric evidence config invalid: label"
        if not isinstance(columns, list) or not all(
            isinstance(column, str) and column for column in columns
        ):
            return False, "Benchmark metric evidence config invalid: columns"
        if not isinstance(min_rows, int) or min_rows < 1:
            return False, "Benchmark metric evidence config invalid: min_rows"

        label_index = None
        for index, line in enumerate(lines):
            if label in _strip_log_prefix(line):
                label_index = index
                break
        if label_index is None:
            return False, "Benchmark metric evidence missing table: %s" % (label,)

        header_index = None
        for index in range(label_index + 1, len(lines)):
            if _line_contains_all(_strip_log_prefix(lines[index]), columns):
                header_index = index
                break
        if header_index is None:
            return False, "Benchmark metric evidence missing columns for %s: %s" % (
                label,
                ", ".join(columns),
            )

        rows = _numeric_metric_row_count(lines, header_index + 1)
        if rows < min_rows:
            return False, "Benchmark metric evidence missing rows for %s" % (label,)

    return True, "benchmark_metric_tables_found"


def detect_success(
    stdout: str,
    stderr: str,
    exit_code: int,
    config: Dict,
    success_config: Dict,
) -> Tuple[bool, str]:
    """Detect if a test run was successful using multiple heuristics.

    Args:
        stdout: Standard output from test execution
        stderr: Standard error from test execution
        exit_code: Process exit code
        config: Parsed config dictionary
        success_config: Success detection configuration

    Returns:
        Tuple of (success: bool, reason: str)
    """
    infra_only = config.get("infrastructure", {}).get("infra_only", False)

    # Get success criteria (use infra_only override if available)
    if infra_only and "infra_only_override" in success_config:
        criteria = success_config["infra_only_override"]
    else:
        criteria = success_config

    require_ssh = criteria.get("require_ssh_output", True)
    require_exit_zero = criteria.get("require_exit_code_zero", True)
    require_experiment_lock = criteria.get("require_experiment_lock", True)
    require_state_file = criteria.get("require_state_file", True)
    require_state_phase = criteria.get("require_state_phase", True)
    require_resume_contract = criteria.get("require_resume_contract", True)
    require_teardown = criteria.get("require_teardown", False)
    require_network_validation_results = criteria.get("require_network_validation_results", False)
    required_stdout_markers = criteria.get("required_stdout_markers", [])
    required_stdout_metric_tables = criteria.get("required_stdout_metric_tables", [])
    required_benchmark_metric_artifacts = criteria.get("required_benchmark_metric_artifacts", [])
    check_logs = criteria.get("check_log_files", False)

    reasons = []

    # Check exit code
    exit_ok = exit_code == 0
    if require_exit_zero:
        if not exit_ok:
            return False, f"Exit code {exit_code} (expected 0)"
        reasons.append("exit_code=0")

    # Check for SSH output (indicates successful VM creation)
    ssh_pattern = r"ssh\s+\S+@\S+\s+-i\s+\S+"
    has_ssh_output = bool(re.search(ssh_pattern, stdout))
    if require_ssh:
        if not has_ssh_output:
            return False, "No SSH output found (expected SSH commands)"
        reasons.append("ssh_output_found")

    continuum_dir = os.path.join(config.get("infrastructure", {}).get("base_path", ""), ".continuum")
    experiment_lock_path = os.path.join(continuum_dir, "experiment_lock.yaml")
    state_path = os.path.join(continuum_dir, "state.json")

    if require_experiment_lock:
        if not os.path.exists(experiment_lock_path):
            return False, "Experiment lock file missing: %s" % (experiment_lock_path)
        reasons.append("experiment_lock_written")

    lock_payload = None
    if require_resume_contract:
        if not os.path.exists(experiment_lock_path):
            return False, "Experiment lock file missing: %s" % (experiment_lock_path)
        try:
            with open(experiment_lock_path, "r", encoding="utf-8") as filep:
                lock_payload = yaml.safe_load(filep) or {}
        except (OSError, yaml.YAMLError) as exc:
            return False, "Experiment lock file unreadable: %s" % (exc)
        if not isinstance(lock_payload, dict):
            return False, "Experiment lock schema mismatch: expected top-level mapping"
        if lock_payload.get("kind") != "ContinuumExperimentLock":
            return False, "Experiment lock schema mismatch: unexpected kind %r" % (
                lock_payload.get("kind"),
            )
        if lock_payload.get("schema_version") != 1:
            return False, "Experiment lock schema mismatch: expected schema_version 1"

    state_payload = None
    expected_phase = None
    if require_state_file or require_state_phase:
        if not os.path.exists(state_path):
            return False, "State file missing: %s" % (state_path)
        reasons.append("state_file_written")

        try:
            with open(state_path, "r", encoding="utf-8") as filep:
                state_payload = json.load(filep)
        except (OSError, json.JSONDecodeError) as exc:
            return False, "State file unreadable: %s" % (exc)

        state_schema_ok, state_schema_reason = _validate_state_artifact_schema(state_payload)
        if not state_schema_ok:
            return False, state_schema_reason

    if require_state_phase:
        expected_phase = _expected_phase_completed(config)
        actual_phase = state_payload.get("phase_completed")
        if actual_phase != expected_phase:
            return False, "State phase %r (expected %r)" % (actual_phase, expected_phase)
        reasons.append("state_phase=%s" % (expected_phase))

    if require_resume_contract:
        if state_payload is None:
            if not os.path.exists(state_path):
                return False, "State file missing: %s" % (state_path)
            try:
                with open(state_path, "r", encoding="utf-8") as filep:
                    state_payload = json.load(filep)
            except (OSError, json.JSONDecodeError) as exc:
                return False, "State file unreadable: %s" % (exc)
            state_schema_ok, state_schema_reason = _validate_state_artifact_schema(state_payload)
            if not state_schema_ok:
                return False, state_schema_reason

        try:
            lock_hash, _lock_details = resume_contract.validate_persisted_resume_contract(
                lock_payload.get("resume_contract"),
                "experiment_lock.resume_contract",
            )
        except ValueError as exc:
            return False, "Resume contract mismatch: %s" % (exc)
        try:
            state_hash, _state_details = resume_contract.validate_persisted_resume_contract(
                state_payload.get("resume_contract"),
                "state.resume_contract",
            )
        except ValueError as exc:
            return False, "Resume contract mismatch: %s" % (exc)
        if lock_hash != state_hash:
            return False, "Resume contract mismatch: lock %s != state %s" % (
                lock_hash,
                state_hash,
            )
        reasons.append("resume_contract_match")

    if require_teardown and config.get("infrastructure", {}).get("delete_on_exit", False):
        teardown_ok, teardown_reason = verify_qemu_teardown(config, state_payload or {})
        if not teardown_ok:
            return False, teardown_reason
        reasons.append(teardown_reason)

    if require_network_validation_results:
        network_ok, network_reason = verify_network_validation_results(config)
        if not network_ok:
            return False, network_reason
        reasons.append(network_reason)

    if required_stdout_markers:
        expected_phase = expected_phase or _expected_phase_completed(config)
    if required_stdout_markers and expected_phase == "application":
        if not isinstance(required_stdout_markers, list) or not all(
            isinstance(marker, str) and marker for marker in required_stdout_markers
        ):
            return False, "Benchmark evidence config invalid: required_stdout_markers"
        missing_markers = [
            marker for marker in required_stdout_markers if marker not in stdout
        ]
        if missing_markers:
            return False, "Benchmark evidence missing: %s" % (", ".join(missing_markers),)
        reasons.append("benchmark_evidence_found")

    if required_stdout_metric_tables:
        expected_phase = expected_phase or _expected_phase_completed(config)
    if required_stdout_metric_tables and expected_phase == "application":
        metric_ok, metric_reason = verify_benchmark_metric_tables(
            stdout,
            required_stdout_metric_tables,
        )
        if not metric_ok:
            return False, metric_reason
        reasons.append(metric_reason)

    if required_benchmark_metric_artifacts:
        expected_phase = expected_phase or _expected_phase_completed(config)
    if required_benchmark_metric_artifacts and expected_phase == "application":
        expected_artifact_timestamp = config.get("timestamp")
        if not expected_artifact_timestamp:
            expected_artifact_timestamp = _extract_run_timestamp(stdout)
        artifact_ok, artifact_reason = verify_benchmark_metric_artifacts(
            config,
            required_benchmark_metric_artifacts,
            expected_timestamp=expected_artifact_timestamp,
        )
        if not artifact_ok:
            return False, artifact_reason
        reasons.append(artifact_reason)

    # Optional: Check log files or stdout/stderr for explicit failure markers
    if check_logs:
        pass

    # Heuristic: even if exit code is 0, treat known Ansible failures as test failures
    ansible_failed = ("FAILED!" in stdout) or ("non-zero return code" in stdout)
    if ansible_failed:
        return False, "Ansible reported FAILED in stdout despite exit_code=0"

    reason_str = "Success: " + ", ".join(reasons) if reasons else "Success"
    return True, reason_str


def _validate_state_artifact_schema(state_payload: Dict) -> Tuple[bool, str]:
    """Validate the e2e-visible state artifact schema."""
    if not isinstance(state_payload, dict):
        return False, "State schema mismatch: expected top-level mapping"
    if state_payload.get("schema_version") != 2:
        return False, "State schema mismatch: expected schema_version 2 but found %r" % (
            state_payload.get("schema_version"),
        )
    if state_payload.get("kind") != "ContinuumState":
        return False, "State schema mismatch: expected kind 'ContinuumState' but found %r" % (
            state_payload.get("kind"),
        )
    if not isinstance(state_payload.get("created_at"), str) or not state_payload.get(
        "created_at"
    ).strip():
        return False, "State schema mismatch: missing created_at"
    if state_payload.get("phase_completed") not in (
        "infrastructure",
        "software",
        "application",
    ):
        return False, "State schema mismatch: invalid phase_completed %r" % (
            state_payload.get("phase_completed"),
        )
    machine_data = state_payload.get("machine_data")
    if not isinstance(machine_data, list) or not machine_data:
        return False, "State schema mismatch: machine_data must be a non-empty list"
    return True, "state_schema_valid"


def verify_qemu_teardown(config: Dict, state_payload: Dict) -> Tuple[bool, str]:
    """Verify that QEMU domains persisted in state are absent after teardown."""
    infrastructure = config.get("infrastructure", {})
    if infrastructure.get("provider") != "qemu":
        return True, "teardown_skipped_non_qemu"

    machine_data = state_payload.get("machine_data", [])
    if not isinstance(machine_data, list) or not machine_data:
        return False, "Teardown verification failed: state machine_data missing"

    domain_name_fields = (
        "cloud_controller_names",
        "cloud_names",
        "edge_names",
        "endpoint_names",
        "base_names",
    )
    domain_names = []
    for machine_entry in machine_data:
        if not isinstance(machine_entry, dict):
            return False, "Teardown verification failed: malformed state machine_data entry"
        for field in domain_name_fields:
            names = machine_entry.get(field, [])
            if isinstance(names, str):
                names = [names]
            if not isinstance(names, list):
                return False, "Teardown verification failed: malformed state field %s" % (field)
            domain_names.extend(name for name in names if isinstance(name, str) and name)

    if not domain_names:
        return False, "Teardown verification failed: state machine names missing"

    virsh = shutil.which("virsh")
    if virsh is None:
        return False, "Teardown verification failed: virsh not found"

    try:
        result = subprocess.run(
            [virsh, "list", "--all"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, "Teardown verification failed: could not execute virsh: %s" % (exc)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, "Teardown verification failed: virsh list --all failed: %s" % (detail)

    remaining = [name for name in domain_names if name in result.stdout]
    if remaining:
        return False, "Teardown verification failed: VM domain(s) still present: %s" % (
            ", ".join(sorted(remaining))
        )

    return True, "teardown_verified"


def _expected_phase_completed(config: Dict) -> str:
    """Return the expected saved state phase for a successful run."""
    infrastructure = config.get("infrastructure", {})
    benchmark = config.get("benchmark", {})

    if infrastructure.get("infra_only", False):
        return "infrastructure"
    if benchmark.get("resource_manager_only", False):
        return "software"
    return "application"


def classify_test_failure(result: Dict) -> Optional[str]:
    """Classify a failed test result into a stable debugging bucket."""
    if result.get("success", False):
        return None

    if result.get("timed_out", False):
        return "timeout"

    detail = str(result.get("error") or result.get("success_reason") or "")
    if detail.startswith("Failed to parse config:"):
        return "parse_failure"
    if detail.startswith("Failed to create temp config:"):
        return "override_failure"
    if detail.startswith("Failed to execute test:"):
        return "runner_failure"
    if detail.startswith("Experiment lock file missing:"):
        return "missing_lock"
    if detail.startswith("State file missing:"):
        return "missing_state"
    if detail.startswith("State file unreadable:"):
        return "unreadable_state"
    if detail.startswith("State schema mismatch:"):
        return "state_schema_mismatch"
    if detail.startswith("State phase "):
        return "wrong_state_phase"
    if detail.startswith("Experiment lock schema mismatch:"):
        return "state_schema_mismatch"
    if detail.startswith("Experiment lock file unreadable:"):
        return "unreadable_lock"
    if detail.startswith("Resume contract mismatch:"):
        return "resume_contract_mismatch"
    if detail.startswith("Teardown verification failed:"):
        return "teardown_failure"
    if detail.startswith("Benchmark evidence missing:"):
        return "missing_benchmark_evidence"
    if detail.startswith("Benchmark metric evidence missing"):
        return "missing_benchmark_metric_evidence"
    if detail.startswith("Benchmark metric evidence config invalid:"):
        return "benchmark_metric_evidence_config"
    if detail.startswith("Benchmark metric artifact missing:"):
        return "missing_benchmark_metric_artifact"
    if detail.startswith("Benchmark metric artifact unreadable:"):
        return "unreadable_benchmark_metric_artifact"
    if detail.startswith("Benchmark metric artifact invalid:"):
        return "invalid_benchmark_metric_artifact"
    if detail.startswith("Benchmark metric artifact statistic failed:"):
        return "invalid_benchmark_metric_artifact"
    if detail.startswith("Benchmark metric artifact config invalid:"):
        return "benchmark_metric_artifact_config"
    if detail.startswith("Network validation artifact missing:"):
        return "missing_network_artifact"
    if detail.startswith("Network validation artifact unreadable:"):
        return "unreadable_network_artifact"
    if detail.startswith("Network validation artifact invalid:"):
        return "invalid_network_artifact"
    if detail.startswith("Network validation profile mismatch:"):
        return "network_profile_mismatch"
    if detail.startswith("No SSH output found"):
        return "missing_ssh"
    if detail.startswith("Exit code "):
        return "nonzero_exit"
    if "Ansible reported FAILED" in detail:
        return "ansible_failure"
    return "runtime_failure"


def _sanitize_artifact_name(config_path: str) -> str:
    """Return a filesystem-safe stem for one test result artifact directory."""
    stem = Path(config_path).stem
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return safe or "test"


def save_test_results(results: List[Dict], output_dir: str) -> str:
    """Save test results to JSON file.

    Args:
        results: List of test result dictionaries
        output_dir: Directory to save results in

    Returns:
        Path to saved results file
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime())
    results_file = os.path.join(output_dir, f"test_results_{timestamp}.json")
    artifacts_dir = os.path.join(output_dir, f"test_results_{timestamp}")
    os.makedirs(artifacts_dir, exist_ok=True)

    serialized_results = []
    for index, result in enumerate(results, 1):
        serialized = dict(result)
        serialized["failure_class"] = classify_test_failure(serialized)

        artifact_name = "%02d_%s" % (
            index,
            _sanitize_artifact_name(serialized.get("config_path", "")),
        )
        result_dir = os.path.join(artifacts_dir, artifact_name)
        os.makedirs(result_dir, exist_ok=True)

        stdout_path = os.path.join(result_dir, "stdout.txt")
        stderr_path = os.path.join(result_dir, "stderr.txt")
        metadata_path = os.path.join(result_dir, "metadata.json")

        with open(stdout_path, "w", encoding="utf-8") as filep:
            filep.write(serialized.get("stdout", ""))
        with open(stderr_path, "w", encoding="utf-8") as filep:
            filep.write(serialized.get("stderr", ""))

        metadata_payload = dict(serialized)
        metadata_payload["stdout_artifact"] = stdout_path
        metadata_payload["stderr_artifact"] = stderr_path
        with open(metadata_path, "w", encoding="utf-8") as filep:
            json.dump(metadata_payload, filep, indent=2)
            filep.write("\n")

        serialized["stdout_artifact"] = stdout_path
        serialized["stderr_artifact"] = stderr_path
        serialized["metadata_artifact"] = metadata_path
        serialized_results.append(serialized)

    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "total_tests": len(results),
                "passed": sum(1 for r in results if r.get("success", False)),
                "failed": sum(1 for r in results if not r.get("success", False)),
                "artifacts_dir": artifacts_dir,
                "results": serialized_results,
            },
            f,
            indent=2,
        )
        f.write("\n")

    return results_file


def load_test_manifest(manifest_path: str) -> Optional[Dict]:
    """Load test manifest file.

    Args:
        manifest_path: Path to manifest JSON file

    Returns:
        Manifest dictionary or None if file doesn't exist
    """
    if not os.path.exists(manifest_path):
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load manifest {manifest_path}: {e}")
        return None


def calculate_total_cores(config: Dict) -> int:
    """Calculate total number of cores needed for a configuration.

    Args:
        config: Parsed config dictionary

    Returns:
        Total number of cores needed
    """
    infra = config.get("infrastructure", {})
    cloud_nodes = infra.get("cloud_nodes", 0)
    edge_nodes = infra.get("edge_nodes", 0)
    endpoint_nodes = infra.get("endpoint_nodes", 0)
    cloud_cores = infra.get("cloud_cores", 4)
    edge_cores = infra.get("edge_cores", 2)
    endpoint_cores = infra.get("endpoint_cores", 1)

    total_cores = (
        cloud_nodes * cloud_cores + edge_nodes * edge_cores + endpoint_nodes * endpoint_cores
    )
    return total_cores


def should_use_external_machine(
    config: Dict,
    physical_machine_cores: int = 20,
) -> bool:
    """Determine if an external physical machine is needed.

    Args:
        config: Parsed config dictionary
        physical_machine_cores: Number of cores available on the primary physical machine

    Returns:
        True if external machine is needed
    """
    infra = config.get("infrastructure", {})
    cpu_pin = infra.get("cpu_pin", False)

    # Only need external machine if cpu_pin is enabled
    if not cpu_pin:
        return False

    total_cores = calculate_total_cores(config)
    return total_cores > physical_machine_cores


def override_config_parameters(
    config_path: str,
    base_path: Optional[str] = None,
    middle_ip: Optional[int] = None,
    middle_ip_base: Optional[int] = None,
    external_physical_machines: Optional[str] = None,
) -> str:
    """Create a temporary YAML config file with overridden parameters.

    Args:
        config_path: Original config file path
        base_path: Override for base_path
        middle_ip: Override for middleIP
        middle_ip_base: Override for middleIP_base
        external_physical_machines: Override for external_physical_machines

    Returns:
        Path to temporary config file
    """
    _, ext = os.path.splitext(config_path)
    if ext not in (".yaml", ".yml"):
        raise ValueError(
            "Only YAML experiment/lock configs are supported by test overrides, got %s"
            % (config_path)
        )
    return override_yaml_config_parameters(
        config_path,
        base_path=base_path,
        middle_ip=middle_ip,
        middle_ip_base=middle_ip_base,
        external_physical_machines=external_physical_machines,
    )


def override_yaml_config_parameters(
    config_path: str,
    base_path: Optional[str] = None,
    middle_ip: Optional[int] = None,
    middle_ip_base: Optional[int] = None,
    external_physical_machines: Optional[str] = None,
) -> str:
    """Create temporary YAML config with overridden provider fields.

    For experiment configs, this generates a temporary lock-style payload so
    provider overrides are applied to the fully resolved runtime config.
    """
    path = Path(config_path).expanduser().resolve()
    data = _load_yaml(path)

    if data.get("kind") == "ContinuumExperimentLock":
        lock_data = data
    elif data.get("kind") == "ContinuumExperiment":
        parser = argparse.ArgumentParser(prog="continuum-test-override")
        try:
            parsed_config = yaml_parser.start(parser, str(path))
        except SystemExit as exc:
            raise ValueError("Failed to normalize experiment override input: %s" % (path)) from exc

        parsed_provider_cfg = parsed_config["normalized"]["provider"]["config"]
        parsed_infra = parsed_config["infrastructure"]
        if base_path is not None:
            expanded_path = os.path.expanduser(base_path)
            if expanded_path.endswith("/"):
                expanded_path = expanded_path[:-1]
            parsed_provider_cfg["base_path"] = expanded_path
            parsed_infra["base_path"] = expanded_path
        if middle_ip is not None:
            parsed_provider_cfg.setdefault("ip", {})["middle"] = int(middle_ip)
            parsed_infra["middleIP"] = int(middle_ip)
        if middle_ip_base is not None:
            parsed_provider_cfg.setdefault("ip", {})["middle_base"] = int(middle_ip_base)
            parsed_infra["middleIP_base"] = int(middle_ip_base)
        if external_physical_machines is not None:
            if external_physical_machines:
                parsed_provider_cfg["external_physical_machines"] = [
                    s.strip() for s in external_physical_machines.split(",") if s.strip()
                ]
            else:
                parsed_provider_cfg["external_physical_machines"] = []
            parsed_infra["external_physical_machines"] = ",".join(
                parsed_provider_cfg["external_physical_machines"]
            ) or None

        lock_path = Path(yaml_parser.write_experiment_lock(parsed_config))
        lock_data = _load_yaml(lock_path)
    else:
        raise ValueError(
            "Unsupported YAML kind '%s' for overrides at %s"
            % (data.get("kind"), path)
        )

    provider_cfg = ((lock_data.get("normalized_config", {}) or {}).get("provider", {}) or {}).get(
        "config", {}
    )

    if base_path is not None:
        expanded_path = os.path.expanduser(base_path)
        if expanded_path.endswith("/"):
            expanded_path = expanded_path[:-1]
        provider_cfg["base_path"] = expanded_path

    ip_cfg = provider_cfg.setdefault("ip", {})
    if middle_ip is not None:
        ip_cfg["middle"] = int(middle_ip)
    if middle_ip_base is not None:
        ip_cfg["middle_base"] = int(middle_ip_base)

    if external_physical_machines is not None:
        if external_physical_machines:
            provider_cfg["external_physical_machines"] = [
                s.strip() for s in external_physical_machines.split(",") if s.strip()
            ]
        else:
            provider_cfg["external_physical_machines"] = []

    import tempfile

    temp_fd, temp_path = tempfile.mkstemp(suffix=".yaml", prefix="continuum_test_")
    os.close(temp_fd)
    with open(temp_path, "w", encoding="utf-8") as filep:
        yaml.safe_dump(lock_data, filep, sort_keys=False)
    return temp_path
