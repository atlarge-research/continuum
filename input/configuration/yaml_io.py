"""YAML file I/O and path resolution helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as filep:
        data = yaml.safe_load(filep) or {}
    if not isinstance(data, dict):
        raise ValueError("Expected top-level YAML mapping in %s" % (path))
    return data


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as filep:
        while True:
            chunk = filep.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_profile_path(experiment_path: Path, profile_kind: str, ref: str) -> Path:
    """Resolve a profile reference to an existing YAML path."""
    ref_path = Path(ref).expanduser()
    if ref_path.is_absolute() and ref_path.exists():
        return ref_path

    root = repo_root()
    candidates = []
    candidates.append((experiment_path.parent / ref).expanduser())
    candidates.append((experiment_path.parent / ("%s.yaml" % ref)).expanduser())
    candidates.append((experiment_path.parent / ("%s.yml" % ref)).expanduser())
    candidates.append((root / ref).expanduser())
    candidates.append((root / ("%s.yaml" % ref)).expanduser())
    candidates.append((root / ("%s.yml" % ref)).expanduser())
    candidates.append((root / "configs" / "profiles" / profile_kind / ("%s.yaml" % ref)))
    candidates.append(
        (Path.home() / ".continuum" / "configs" / "profiles" / profile_kind / ("%s.yaml" % ref))
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError("Could not resolve %s profile reference '%s'" % (profile_kind, ref))
