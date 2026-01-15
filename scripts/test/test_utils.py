"""\
Test utilities for Continuum end-to-end testing framework.
Provides functions for config discovery, base image management, success detection, and result storage.
"""

import configparser
import fnmatch
import getpass
import json
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple


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

    # First, collect all .cfg files from specified directories
    for directory in directories:
        if not os.path.exists(directory):
            continue
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".cfg"):
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
    config = configparser.ConfigParser()
    config.read(config_path)

    result = {
        "infrastructure": {},
        "benchmark": {},
    }

    # Parse infrastructure section
    if "infrastructure" in config:
        infra = config["infrastructure"]
        result["infrastructure"]["provider"] = infra.get("provider", "qemu")
        result["infrastructure"]["infra_only"] = infra.getboolean("infra_only", False)
        result["infrastructure"]["cloud_nodes"] = infra.getint("cloud_nodes", 0)
        result["infrastructure"]["edge_nodes"] = infra.getint("edge_nodes", 0)
        result["infrastructure"]["endpoint_nodes"] = infra.getint("endpoint_nodes", 0)
        result["infrastructure"]["base_path"] = os.path.expanduser(infra.get("base_path", "~"))
        result["infrastructure"]["middleIP"] = infra.getint("middleIP", 100)
        result["infrastructure"]["middleIP_base"] = infra.getint("middleIP_base", 90)

    # Parse benchmark section
    if "benchmark" in config:
        bench = config["benchmark"]
        result["benchmark"]["resource_manager"] = bench.get("resource_manager", "none")
        result["benchmark"]["resource_manager_only"] = bench.getboolean(
            "resource_manager_only", False
        )

    return result


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
        benchmark: Benchmark config dictionary
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

    # Optional: Check log files for errors
    if check_logs:
        # This would require reading log files - implement if needed
        pass

    reason_str = "Success: " + ", ".join(reasons) if reasons else "Success"
    return True, reason_str


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

    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "total_tests": len(results),
                "passed": sum(1 for r in results if r.get("success", False)),
                "failed": sum(1 for r in results if not r.get("success", False)),
                "results": results,
            },
            f,
            indent=2,
        )

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


def override_config_parameters(
    config_path: str,
    base_path: Optional[str] = None,
    middle_ip: Optional[int] = None,
    middle_ip_base: Optional[int] = None,
) -> str:
    """Create a temporary config file with overridden parameters.

    Args:
        config_path: Original config file path
        base_path: Override for base_path
        middle_ip: Override for middleIP
        middle_ip_base: Override for middleIP_base

    Returns:
        Path to temporary config file
    """
    config = configparser.ConfigParser()
    config.read(config_path)

    # Ensure infrastructure section exists
    if "infrastructure" not in config:
        config.add_section("infrastructure")

    # Apply overrides (check for None explicitly, not just truthiness)
    if base_path is not None:
        # Expand user path and normalize
        expanded_path = os.path.expanduser(base_path)
        if expanded_path.endswith("/"):
            expanded_path = expanded_path[:-1]
        config["infrastructure"]["base_path"] = expanded_path

    if middle_ip is not None:
        config["infrastructure"]["middleIP"] = str(middle_ip)

    if middle_ip_base is not None:
        config["infrastructure"]["middleIP_base"] = str(middle_ip_base)

    # Create temporary file
    import tempfile

    temp_fd, temp_path = tempfile.mkstemp(suffix=".cfg", prefix="continuum_test_")
    os.close(temp_fd)

    with open(temp_path, "w", encoding="utf-8") as f:
        config.write(f)

    return temp_path
