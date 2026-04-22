"""Experiment profile composition helpers."""

from __future__ import annotations

from pathlib import Path

from . import yaml_io


def compose_from_experiment(
    path: Path,
    experiment: dict,
    validate_environment,
    validate_software_profile,
) -> tuple[dict, dict, dict]:
    use = experiment.get("use", {})
    env_ref = use.get("environment")
    sw_ref = use.get("software")

    env_path = yaml_io.resolve_profile_path(path, "environment", str(env_ref))
    sw_path = yaml_io.resolve_profile_path(path, "software", str(sw_ref))
    environment = yaml_io.load_yaml(env_path)
    software = yaml_io.load_yaml(sw_path)
    validate_environment(environment, env_path)
    validate_software_profile(software, sw_path)
    return (
        environment,
        software,
        {
            "experiment": str(path),
            "environment_profile": str(env_path),
            "software_profile": str(sw_path),
        },
    )
