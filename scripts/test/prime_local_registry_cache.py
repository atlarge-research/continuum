#!/usr/bin/env python3
"""Prime or verify Continuum's local application image registry cache."""

# pylint: disable=wrong-import-position,too-few-public-methods

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from input.configuration import runtime_module_loader
from input.configuration import yaml_parser
from infrastructure import image_registry


class StaticHostIpSocket:
    """Socket shim that returns the selected registry host IP without network IO."""

    def __init__(self, host_ip: str):
        self._host_ip = host_ip

    def __enter__(self):
        """Return this shim from context-manager entry."""
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        """Propagate exceptions from the context body."""
        return False

    def connect(self, _target):
        """Pretend the route probe succeeded."""
        return None

    def getsockname(self):
        """Return the selected host IP in socket.getsockname shape."""
        return (self._host_ip, 5000)


class StaticSocketModule:
    """Minimal socket module shim accepted by runtime_module_loader."""

    AF_INET = runtime_module_loader.socket_lib.AF_INET
    SOCK_DGRAM = runtime_module_loader.socket_lib.SOCK_DGRAM
    gaierror = runtime_module_loader.socket_lib.gaierror

    def __init__(self, host_ip: str):
        self._host_ip = host_ip

    def socket(self, *_args, **_kwargs):
        """Return a static host-IP socket shim."""
        return StaticHostIpSocket(self._host_ip)


class LocalMachine:
    """Small process shim matching the Machine.process return shape."""

    name = "localhost"

    def process(self, _config, commands, ssh=None):
        """Run local commands and return Continuum's list-of-results shape."""
        if ssh is not None:
            raise ValueError("Local registry cache checks do not support ssh commands")
        command_list = commands
        if command_list and isinstance(command_list[0], str):
            command_list = [command_list]

        results = []
        for command in command_list:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            output = completed.stdout.splitlines()
            error = completed.stderr.splitlines()
            results.append((output, error))
        return results


def _repo_root() -> Path:
    return REPO_ROOT


def _registry_host_ip() -> str:
    override = os.environ.get("CONTINUUM_REGISTRY_HOST_IP")
    if override:
        return override
    return socket.gethostbyname(socket.gethostname())


def _config_paths_for_suite(repo_root: Path, test_config_path: Path, suite_name: str) -> list[Path]:
    with test_config_path.open("r", encoding="utf-8") as filep:
        test_config = json.load(filep)

    suites = test_config.get("test_suites", {})
    if suite_name not in suites:
        raise ValueError(
            "Unknown suite '%s' in %s (available: %s)"
            % (suite_name, test_config_path, ", ".join(sorted(suites)))
        )

    paths = []
    for directory in suites[suite_name].get("directories", []):
        root = repo_root / directory
        if not root.exists():
            continue
        for candidate in sorted(root.rglob("*")):
            if candidate.suffix in (".yaml", ".yml"):
                paths.append(candidate)
    return paths


def _parse_runtime_config(repo_root: Path, config_path: Path):
    parser = argparse.ArgumentParser(prog="prime_local_registry_cache")
    target = config_path if config_path.is_absolute() else repo_root / config_path
    host_ip = _registry_host_ip()
    original_add_constants = runtime_module_loader.add_constants

    def add_constants_with_static_host_ip(parser_obj, config, socket_module=None):
        del socket_module
        return original_add_constants(
            parser_obj,
            config,
            socket_module=StaticSocketModule(host_ip),
        )

    runtime_module_loader.add_constants = add_constants_with_static_host_ip
    try:
        return yaml_parser.start(parser, str(target))
    finally:
        runtime_module_loader.add_constants = original_add_constants


def _resolve_config_paths(args) -> list[Path]:
    repo_root = _repo_root()
    paths = [Path(config) for config in args.config]
    test_config_path = Path(args.test_config)
    if not test_config_path.is_absolute():
        test_config_path = repo_root / test_config_path

    for suite_name in args.suite:
        paths.extend(_config_paths_for_suite(repo_root, test_config_path, suite_name))

    deduped = []
    seen = set()
    for path in paths:
        resolved = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
        if resolved not in seen:
            deduped.append(resolved)
            seen.add(resolved)
    return deduped


def _format_requirement(requirement):
    owners = ",".join(requirement["owners"])
    tiers = ",".join(requirement["tier_targets"]) or "all"
    return "%s -> %s (owners=%s tiers=%s)" % (
        requirement["source_ref"],
        requirement["local_name"],
        owners,
        tiers,
    )


def _process_config(config_path: Path, check_only: bool) -> bool:
    repo_root = _repo_root()
    config = _parse_runtime_config(repo_root, config_path)
    image_registry.resolve_prefetch_requirements(config)
    requirements = image_registry.get_prefetch_requirements(config)
    if not requirements:
        print("OK %s: no registry-backed image requirements" % (config_path,))
        return True

    machine = LocalMachine()
    if check_only:
        missing = image_registry.missing_cached_requirements(config, [machine])
        if not missing:
            print(
                "OK %s: %s image(s) cached in %s"
                % (config_path, len(requirements), config["registry"])
            )
            return True

        print(
            "MISSING %s: %s of %s image(s) absent from %s"
            % (config_path, len(missing), len(requirements), config["registry"]),
            file=sys.stderr,
        )
        for requirement in missing:
            print("  - %s" % (_format_requirement(requirement),), file=sys.stderr)
        print(
            "Prime the cache before running the dedicated smoke suite, for example: "
            "python3 scripts/test/prime_local_registry_cache.py --config %s"
            % (config_path,),
            file=sys.stderr,
        )
        return False

    image_registry.docker_registry(config, [machine])
    missing = image_registry.missing_cached_requirements(config, [machine])
    if missing:
        print(
            "FAILED %s: cache priming finished but %s image(s) are still missing"
            % (config_path, len(missing)),
            file=sys.stderr,
        )
        return False
    print(
        "OK %s: primed %s image(s) in %s"
        % (config_path, len(requirements), config["registry"])
    )
    return True


def main() -> int:
    """Run the registry cache prime/check command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="append", default=[], help="Test suite to process")
    parser.add_argument("--config", action="append", default=[], help="Config file to process")
    parser.add_argument(
        "--test-config",
        default="scripts/test/test_config.json",
        help="Test configuration JSON used for --suite discovery",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify cache readiness without pulling or pushing images",
    )
    args = parser.parse_args()

    if not args.suite and not args.config:
        parser.error("at least one --suite or --config is required")

    os.chdir(_repo_root())
    try:
        config_paths = _resolve_config_paths(args)
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % (exc,), file=sys.stderr)
        return 2

    if not config_paths:
        print("ERROR: no YAML configs matched the requested suites/configs", file=sys.stderr)
        return 2

    ok = True
    for config_path in config_paths:
        ok = _process_config(config_path, args.check_only) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
