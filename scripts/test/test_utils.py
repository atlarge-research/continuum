"""\
Test utilities for Continuum end-to-end testing framework.
Provides functions for config discovery, base image management, success detection, and result storage.
"""

import argparse
import fnmatch
import getpass
import json
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
    return Path(__file__).resolve().parents[2]


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
    required_stdout_markers = criteria.get("required_stdout_markers", [])
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
