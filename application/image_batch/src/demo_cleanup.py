"""Archive and remove native staging files only after their capture namespace is gone."""

import argparse
import io
import json
from pathlib import Path
import re

from opendc_inputs import file_hashes, write_json
from opendc_kubernetes import REMOTE_HASH_SCRIPT, extract_artifacts, ssh

LIST_SCRIPT = """import json,pathlib,re,sys
prefix='fns-opendc-'+sys.argv[1]+'-native-'
paths=[]
for path in pathlib.Path('/var/tmp').iterdir():
    if re.fullmatch(re.escape(prefix)+r'[0-9]{4,}', path.name):
        if path.is_symlink() or not path.is_dir(): raise ValueError('unsafe staging path')
        paths.append(str(path))
print(json.dumps(sorted(paths)))
"""


def cleanup_native(capture):
    """Preserve exact native inputs/results and delete only this completed capture's files.

    Args:
        capture (Path): Collected capture with invocation and successful namespace cleanup.

    Returns:
        dict: Removed directories and preserved archive hashes.

    Raises:
        ValueError: Namespace is live, identity differs, or archived file hashes disagree.
        FileExistsError: Cleanup evidence already exists; inspect it before recovery.
        RuntimeError: A remote inventory, archive or removal command fails.
    """
    capture = Path(capture)
    args = json.loads((capture / "invocation.json").read_text(encoding="utf-8"))
    cleanup = json.loads((capture / "cleanup.json").read_text(encoding="utf-8"))
    namespace = args["namespace"]
    if cleanup.get("namespace_removed") is not True or not re.fullmatch(
        r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace
    ):
        raise ValueError("capture namespace cleanup is not established")
    host, key = args["controller"], args["ssh_key"]
    live = ssh(
        host, key, ["kubectl", "get", "namespace", namespace, "--ignore-not-found", "-o", "json"]
    )
    if live.strip():
        raise ValueError("capture namespace still exists")
    if ssh(host, key, ["hostname"]).decode().strip() != args["control_node"]:
        raise ValueError("native artifact host identity differs")
    paths = json.loads(ssh(host, key, ["python3", "-c", LIST_SCRIPT, namespace]))
    output = capture / "native-cleanup"
    output.mkdir(exist_ok=False)
    result = {"namespace": namespace, "directories": []}
    for remote in paths:
        prefix = f"/var/tmp/fns-opendc-{namespace}-"
        if not re.fullmatch(re.escape(prefix) + r"native-[0-9]{4,}", remote):
            raise ValueError("unexpected native staging directory")
        destination = output / remote.removeprefix(prefix)
        destination.mkdir()
        before = json.loads(ssh(host, key, ["python3", "-c", REMOTE_HASH_SCRIPT, remote]))
        archive = ssh(host, key, ["tar", "-C", remote, "-cf", "-", "."], timeout=60)
        (destination / "artifacts.tar").write_bytes(archive)
        artifacts = destination / "artifacts"
        artifacts.mkdir()
        extract_artifacts(io.BytesIO(archive), artifacts)
        after = json.loads(ssh(host, key, ["python3", "-c", REMOTE_HASH_SCRIPT, remote]))
        local = file_hashes(artifacts)
        write_json(destination / "hashes.json", {"before": before, "after": after, "local": local})
        if before != after or before != local:
            raise ValueError("native artifact hashes differ; remote staging retained")
        ssh(host, key, ["sudo", "-n", "rm", "-rf", "--", remote])
        result["directories"].append({"remote": remote, "files": local})
        write_json(output / "cleanup.json", result)
    remaining = json.loads(ssh(host, key, ["python3", "-c", LIST_SCRIPT, namespace]))
    if remaining:
        raise ValueError("native staging directories remain")
    result["verified_absent"] = True
    write_json(output / "cleanup.json", result)
    return result


def main():
    """Expose the completed-capture cleanup workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(cleanup_native(args.capture)))


if __name__ == "__main__":
    main()
