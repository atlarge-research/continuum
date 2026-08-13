#!/usr/bin/env python3
"""Fetch one immutable Hugging Face model snapshot and verify every artifact."""

import argparse
import hashlib
import json
from pathlib import Path, PurePath
import re
import shutil
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen


def _validate_manifest(manifest):
    """Reject malformed or unsafe artifact manifests before any download."""
    if manifest.get("schema_version") != 1:
        raise ValueError("model lock must use schema_version 1")

    model = manifest.get("model", {})
    repository = model.get("repository", "")
    revision = model.get("revision", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("model lock must identify a safe repository")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("model lock revision must be a full commit identity")

    artifacts = manifest.get("artifacts", [])
    if not artifacts:
        raise ValueError("model lock must contain at least one artifact")

    seen = set()
    for artifact in artifacts:
        filename = artifact.get("filename", "")
        if not filename or PurePath(filename).name != filename or filename in seen:
            raise ValueError("model lock contains an unsafe or duplicate filename")
        seen.add(filename)

        sha256 = artifact.get("sha256", "")
        size = artifact.get("size")
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise ValueError("model lock contains an invalid SHA-256 for %s" % filename)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("model lock contains an invalid size for %s" % filename)


def _open_url(url):
    """Open a public artifact URL without sending credentials."""
    request = Request(url, headers={"User-Agent": "continuum-model-fetch/1"})
    return urlopen(request, timeout=120)


def fetch_artifacts(manifest, destination, open_url=_open_url):
    """Download the locked artifact set and fail on any identity mismatch."""
    _validate_manifest(manifest)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    repository = manifest["model"]["repository"]
    revision = manifest["model"]["revision"]
    base_url = "https://huggingface.co/%s/resolve/%s" % (repository, revision)

    for artifact in manifest["artifacts"]:
        filename = artifact["filename"]
        url = "%s/%s" % (base_url, quote(filename))
        digest = hashlib.sha256()
        size = 0

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
                temporary_path = Path(output.name)
                with open_url(url) as response:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        if size > artifact["size"]:
                            raise ValueError(
                                "%s exceeds locked size %i" % (filename, artifact["size"])
                            )

            if size != artifact["size"]:
                raise ValueError(
                    "%s size mismatch: expected %i, received %i"
                    % (filename, artifact["size"], size)
                )
            if digest.hexdigest() != artifact["sha256"]:
                raise ValueError("%s SHA-256 mismatch" % filename)

            # The build stage runs as root, while the runtime uses an unprivileged UID.
            # Artifacts are immutable image inputs, so make them readable but not writable.
            temporary_path.chmod(0o444)
            temporary_path.replace(destination / filename)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def main():
    """Parse command-line arguments and fetch the locked snapshot."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()

    with args.lock.open("r", encoding="utf-8") as lock_file:
        manifest = json.load(lock_file)

    fetch_artifacts(manifest, args.destination)
    installed_lock = args.destination / "model.lock.json"
    shutil.copyfile(args.lock, installed_lock)
    installed_lock.chmod(0o444)


if __name__ == "__main__":
    main()
