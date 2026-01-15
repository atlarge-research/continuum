#!/usr/bin/env python3
"""\
Main test runner for Continuum end-to-end testing framework.
Discovers and executes test configurations, tracks results, and generates reports.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

# Add project root to path to import test_utils
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

# Import test_utils from scripts.test
import importlib.util

test_utils_path = os.path.join(os.path.dirname(__file__), "test_utils.py")
spec = importlib.util.spec_from_file_location("test_utils", test_utils_path)
test_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test_utils)


class Colors:
    """ANSI color codes for terminal output."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_colored(message: str, color: str = Colors.RESET):
    """Print colored message to console."""
    print(f"{color}{message}{Colors.RESET}")


def load_test_config(config_path: str) -> Dict:
    """Load test configuration from JSON file.

    Args:
        config_path: Path to test_config.json

    Returns:
        Configuration dictionary
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_single_test(
    config_path: str,
    test_config: Dict,
    base_path_override: Optional[str] = None,
    middle_ip_override: Optional[int] = None,
    middle_ip_base_override: Optional[int] = None,
    timeout_minutes: int = 30,
) -> Dict:
    """Run a single test configuration.

    Args:
        config_path: Path to test config file
        test_config: Test configuration dictionary
        base_path_override: Optional base_path override
        middle_ip_override: Optional middleIP override
        middle_ip_base_override: Optional middleIP_base override
        timeout_minutes: Test timeout in minutes

    Returns:
        Test result dictionary
    """
    start_time = time.time()
    result = {
        "config_path": config_path,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_time)),
        "success": False,
        "error": None,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "execution_time": 0,
        "base_images_rebuilt": [],
        "parameter_overrides": {},
    }

    # Parse config to get base images
    try:
        config = test_utils.parse_config_simple(config_path)
        base_path = base_path_override or config.get("infrastructure", {}).get("base_path", "~")
        base_images = test_utils.identify_base_images(config, base_path_override)
        result["parameter_overrides"] = {
            "base_path": base_path_override,
            "middleIP": middle_ip_override,
            "middleIP_base": middle_ip_base_override,
        }
    except Exception as e:
        result["error"] = f"Failed to parse config: {e}"
        result["execution_time"] = time.time() - start_time
        return result

    # Create temporary config with overrides if needed
    temp_config_path = config_path
    temp_file_created = False
    if base_path_override or middle_ip_override is not None or middle_ip_base_override is not None:
        try:
            temp_config_path = test_utils.override_config_parameters(
                config_path,
                base_path=base_path_override,
                middle_ip=middle_ip_override,
                middle_ip_base=middle_ip_base_override,
            )
            temp_file_created = True
        except Exception as e:
            result["error"] = f"Failed to create temp config: {e}"
            result["execution_time"] = time.time() - start_time
            return result

    # Run continuum.py
    try:
        # Get the continuum.py path (assume we're in project root)
        # Go up from scripts/test/run_tests.py to project root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        continuum_script = os.path.join(project_root, "continuum.py")

        cmd = [sys.executable, continuum_script, temp_config_path]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_root,
        )

        # Wait with timeout
        try:
            stdout, stderr = process.communicate(timeout=timeout_minutes * 60)
            result["exit_code"] = process.returncode
            result["stdout"] = stdout.decode("utf-8", errors="replace")
            result["stderr"] = stderr.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            result["exit_code"] = -1
            result["stdout"] = stdout.decode("utf-8", errors="replace") if stdout else ""
            result["stderr"] = stderr.decode("utf-8", errors="replace") if stderr else ""
            result["error"] = f"Test timed out after {timeout_minutes} minutes"

    except Exception as e:
        result["error"] = f"Failed to execute test: {e}"
        result["execution_time"] = time.time() - start_time
        return result
    finally:
        # Clean up temporary config file
        if temp_file_created and os.path.exists(temp_config_path):
            try:
                os.remove(temp_config_path)
            except Exception:
                pass

    # Detect success
    success_config = test_config.get("success_detection", {})
    success, reason = test_utils.detect_success(
        result["stdout"],
        result["stderr"],
        result["exit_code"],
        config,
        success_config,
    )

    result["success"] = success
    result["success_reason"] = reason
    result["execution_time"] = time.time() - start_time

    return result


def run_tests(
    config_files: List[str],
    test_config: Dict,
    base_path_override: Optional[str] = None,
    middle_ip_override: Optional[int] = None,
    middle_ip_base_override: Optional[int] = None,
    rebuild_base_images: bool = False,
    use_cache: bool = False,
    stop_on_failure: bool = False,
) -> List[Dict]:
    """Run multiple test configurations.

    Args:
        config_files: List of config file paths to test
        test_config: Test configuration dictionary
        base_path_override: Optional base_path override
        middle_ip_override: Optional middleIP override
        middle_ip_base_override: Optional middleIP_base override
        rebuild_base_images: Force rebuild base images
        use_cache: Use cache only (never rebuild)
        stop_on_failure: Stop on first failure

    Returns:
        List of test result dictionaries
    """
    results = []
    rebuild_frequency = test_config.get("base_image_rebuild_frequency", 10)
    timeout_minutes = test_config.get("test_timeout_minutes", 30)

    print_colored(f"\n{'='*80}", Colors.BOLD)
    print_colored(f"Running {len(config_files)} test(s)", Colors.BOLD)
    print_colored(f"{'='*80}\n", Colors.BOLD)

    for i, config_path in enumerate(config_files, 1):
        print_colored(f"[{i}/{len(config_files)}] Testing: {config_path}", Colors.BLUE)

        # Parse config to identify base images
        try:
            config = test_utils.parse_config_simple(config_path)
            base_path = base_path_override or config.get("infrastructure", {}).get("base_path", "~")
            base_images = test_utils.identify_base_images(config, base_path_override)
            base_image_paths = test_utils.get_base_image_paths(base_images, base_path)
        except Exception as e:
            print_colored(f"  Warning: Could not parse config: {e}", Colors.YELLOW)
            base_images = []
            base_image_paths = []

        # Check if we should rebuild base images
        should_rebuild = test_utils.should_rebuild_base_images(
            i,
            rebuild_frequency,
            rebuild_base_images,
            use_cache,
        )

        deleted_images = []
        if should_rebuild and base_image_paths:
            print_colored(f"  Rebuilding base images: {', '.join(base_images)}", Colors.YELLOW)
            deleted_images = test_utils.delete_base_images(base_image_paths)

        # Run the test
        result = run_single_test(
            config_path,
            test_config,
            base_path_override=base_path_override,
            middle_ip_override=middle_ip_override,
            middle_ip_base_override=middle_ip_base_override,
            timeout_minutes=timeout_minutes,
        )

        result["base_images_rebuilt"] = [os.path.basename(img) for img in deleted_images]
        results.append(result)

        # Print result
        if result["success"]:
            print_colored(
                f"  ✓ PASSED ({result['execution_time']:.1f}s) - {result['success_reason']}",
                Colors.GREEN,
            )
        else:
            error_msg = result.get("error") or result.get("success_reason", "Unknown error")
            print_colored(f"  ✗ FAILED ({result['execution_time']:.1f}s) - {error_msg}", Colors.RED)
            if result.get("stderr"):
                # Print first few lines of stderr
                stderr_lines = result["stderr"].split("\n")[:3]
                for line in stderr_lines:
                    if line.strip():
                        print_colored(f"    {line}", Colors.RED)

        # Stop on failure if requested
        if not result["success"] and stop_on_failure:
            print_colored("\nStopping on first failure (--stop-on-failure)", Colors.YELLOW)
            break

        print()  # Blank line between tests

    return results


def print_summary(results: List[Dict]):
    """Print test execution summary.

    Args:
        results: List of test result dictionaries
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("success", False))
    failed = total - passed
    total_time = sum(r.get("execution_time", 0) for r in results)

    print_colored(f"\n{'='*80}", Colors.BOLD)
    print_colored("Test Summary", Colors.BOLD)
    print_colored(f"{'='*80}", Colors.BOLD)
    print(f"Total tests: {total}")
    print_colored(f"Passed: {passed}", Colors.GREEN)
    print_colored(f"Failed: {failed}", Colors.RED)
    print(f"Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")

    if failed > 0:
        print_colored("\nFailed tests:", Colors.RED)
        for result in results:
            if not result.get("success", False):
                error = result.get("error") or result.get("success_reason", "Unknown")
                print_colored(f"  - {result['config_path']}: {error}", Colors.RED)

    print()


def main():
    """Main entry point for test runner."""
    parser = argparse.ArgumentParser(
        description="Run end-to-end tests for Continuum framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--suite",
        choices=["smoke", "full"],
        help="Test suite to run (smoke or full)",
    )
    parser.add_argument(
        "--config",
        help="Single config file to test",
    )
    parser.add_argument(
        "--provider",
        choices=["qemu", "gcp", "aws"],
        help="Filter tests by provider",
    )
    parser.add_argument(
        "--manifest",
        help="Path to test manifest JSON file",
    )
    parser.add_argument(
        "--base-path",
        help="Override base_path for all tests",
    )
    parser.add_argument(
        "--middle-ip",
        type=int,
        help="Override middleIP for all tests",
    )
    parser.add_argument(
        "--middle-ip-base",
        type=int,
        help="Override middleIP_base for all tests",
    )
    parser.add_argument(
        "--rebuild-base-images",
        action="store_true",
        help="Force rebuild base images for all tests",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cache only (never rebuild base images)",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop on first test failure",
    )
    parser.add_argument(
        "--test-config",
        default="scripts/test/test_config.json",
        help="Path to test configuration file (default: scripts/test/test_config.json)",
    )

    args = parser.parse_args()

    # Resolve test config path relative to project root if needed
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))

    if not os.path.isabs(args.test_config):
        # Relative path - try relative to project root first
        test_config_path = os.path.join(project_root, args.test_config)
        if not os.path.exists(test_config_path):
            # Try relative to current directory
            test_config_path = args.test_config
    else:
        test_config_path = args.test_config

    # Load test configuration
    if not os.path.exists(test_config_path):
        print_colored(f"Error: Test config file not found: {test_config_path}", Colors.RED)
        sys.exit(1)

    test_config = load_test_config(test_config_path)

    # Determine which config files to test
    if args.config:
        # Single config file
        if not os.path.exists(args.config):
            print_colored(f"Error: Config file not found: {args.config}", Colors.RED)
            sys.exit(1)
        config_files = [args.config]
    else:
        # Use test suite or discover all
        if args.suite:
            suite_config = test_config["test_suites"][args.suite]
            directories = suite_config["directories"]
            use_cache = suite_config.get("use_cache", False)
            rebuild_base_images = suite_config.get("rebuild_base_images", False)
        else:
            # Default to smoke tests
            suite_config = test_config["test_suites"]["smoke"]
            directories = suite_config["directories"]
            use_cache = suite_config.get("use_cache", False)
            rebuild_base_images = suite_config.get("rebuild_base_images", False)

        # Override with command-line flags
        if args.use_cache:
            use_cache = True
            rebuild_base_images = False
        if args.rebuild_base_images:
            rebuild_base_images = True
            use_cache = False

        exclude_patterns = test_config.get("exclude_patterns", [])

        # Load manifest if provided
        manifest = None
        if args.manifest:
            # Resolve manifest path
            if not os.path.isabs(args.manifest):
                manifest_path = os.path.join(project_root, args.manifest)
                if not os.path.exists(manifest_path):
                    manifest_path = args.manifest
            else:
                manifest_path = args.manifest
            manifest = test_utils.load_test_manifest(manifest_path)
            if manifest is None and os.path.exists(manifest_path):
                print_colored(f"Warning: Could not load manifest: {manifest_path}", Colors.YELLOW)

        # Discover config files
        try:
            config_files = test_utils.discover_config_files(
                directories,
                exclude_patterns,
                manifest=manifest,
                provider=args.provider,
            )
        except Exception as e:
            print_colored(f"Error discovering config files: {e}", Colors.RED)
            sys.exit(1)

        if not config_files:
            print_colored("No config files found matching criteria", Colors.YELLOW)
            print_colored(f"Searched in: {', '.join(directories)}", Colors.YELLOW)
            if manifest:
                print_colored(f"Using manifest: {args.manifest}", Colors.YELLOW)
            sys.exit(0)

    # Run tests
    results = run_tests(
        config_files,
        test_config,
        base_path_override=args.base_path,
        middle_ip_override=args.middle_ip,
        middle_ip_base_override=args.middle_ip_base,
        rebuild_base_images=rebuild_base_images,
        use_cache=use_cache,
        stop_on_failure=args.stop_on_failure,
    )

    # Print summary
    print_summary(results)

    # Save results
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    results_dir = os.path.join(project_root, "logs", "test_results")
    results_file = test_utils.save_test_results(results, results_dir)
    print_colored(f"Results saved to: {results_file}", Colors.BLUE)

    # Exit with appropriate code
    failed_count = sum(1 for r in results if not r.get("success", False))
    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    main()
