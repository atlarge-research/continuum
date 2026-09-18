"""Render a bounded Job and retrieve its terminal evidence without a storage class."""
from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tarfile
import time

from opendc_inputs import CONTRACT, file_hashes, verify_inputs, write_json
from opendc_run import utc_now

TEMPLATE = Path(__file__).resolve().parent.parent / "manifests" / "opendc-job.yaml"
REMOTE_HASH_SCRIPT = """import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
result={}
for p in sorted(root.rglob('*')):
    if p.is_symlink(): raise ValueError('symlink in artifact directory')
    if p.is_file(): result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True))
"""


def _name(value):
    """Return a Kubernetes DNS label, raising ValueError for invalid names.

    Args:
        value (str): Namespace, Job name or node hostname label to validate.

    Returns:
        str: The validated label, unchanged.

    Raises:
        ValueError: The value is not a valid Kubernetes DNS label.
    """
    if len(value) > 63 or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", value):
        raise ValueError("expected a Kubernetes DNS label")
    return value


def _remote_directory(value):
    """Validate the dedicated /var/tmp/fns-opendc-NAME path and return it.

    Args:
        value (str): Absolute staging path under /var/tmp.

    Returns:
        str: The validated staging path.

    Raises:
        ValueError: The path does not match the dedicated staging-directory convention.
    """
    path = PurePosixPath(value)
    if path.parent != PurePosixPath("/var/tmp") or not re.fullmatch(r"fns-opendc-[a-zA-Z0-9-]+", path.name):
        raise ValueError("remote directory must be a unique /var/tmp/fns-opendc-NAME directory")
    return str(path)


def job_manifest(namespace, name, image, node, remote_dir, timeout_seconds=120):
    """Render a bounded Job without creating Kubernetes resources.

    Args:
        namespace (str): Namespace for the Job.
        name (str): Job name within that namespace.
        image (str): Preloaded image with a unique tag or digest.
        node (str): Hostname label used by the scheduler to select the worker.
        remote_dir (str): Existing staging root containing inputs and results.
        timeout_seconds (float): Process timeout inside the 180-second Job limit.

    Returns:
        dict: Job manifest with resource limits and node-local volume paths.

    Raises:
        ValueError: Names, image reference, staging path or timeout are invalid.
    """
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds < 170:
        raise ValueError("process timeout must be positive and less than the Job deadline")
    _remote_directory(remote_dir)
    if not image or image.endswith(":latest") or (":" not in image and "@sha256:" not in image):
        raise ValueError("use a unique image tag or digest")
    job = json.loads(TEMPLATE.read_text())
    job["metadata"].update({"name": _name(name), "namespace": _name(namespace)})
    spec = job["spec"]["template"]["spec"]
    spec["nodeSelector"]["kubernetes.io/hostname"] = _name(node)
    spec["containers"][0]["image"] = image
    spec["containers"][0]["args"][-1] = str(timeout_seconds)
    spec["volumes"][0]["hostPath"]["path"] = remote_dir + "/inputs"
    spec["volumes"][1]["hostPath"]["path"] = remote_dir + "/results"
    return job


def ssh(host, key, command, timeout=45):
    """Run quoted remote arguments over noninteractive SSH and return stdout bytes.

    Args:
        host (str): SSH destination, optionally including the user name.
        key (str or Path): Private-key path.
        command (list): Remote command arguments, individually shell-quoted.
        timeout (float): Maximum local SSH process duration in seconds.

    Returns:
        bytes: Standard output from the successful remote command.

    Raises:
        RuntimeError: SSH or the remote command returns nonzero.
        subprocess.TimeoutExpired: The SSH operation exceeds the timeout.
    """
    if not host or host.startswith("-"):
        raise ValueError("invalid SSH host")
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-i", str(key),
                             host, shlex.join(command)], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace") or f"SSH exit {result.returncode}")
    return result.stdout


def extract_artifacts(stream, directory):
    """Extract regular files and directories from a tar stream into a fresh root.

    Reject absolute paths, parent traversal, links and special files before
    extraction. Existing files are never overwritten; failures can leave
    partially extracted evidence for inspection.

    Args:
        stream (BinaryIO): Binary file-like object containing the archive.
        directory (Path): Fresh destination directory.

    Raises:
        ValueError: An entry uses an absolute path, parent traversal or a nonregular type.
        FileExistsError: Extraction would overwrite an existing file.
    """
    with tarfile.open(fileobj=stream, mode="r:*") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe artifact archive entry: {member.name}")
        for member in members:
            path = directory / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    with path.open("xb") as destination:
                        destination.write(source.read())


def classify_execution(pod, manifest):
    """Reconcile a runner manifest with the OpenDC container's termination state.

    Args:
        pod (dict): Kubernetes Pod record with container termination evidence.
        manifest (dict): Execution manifest, or an empty object if no manifest survived.

    Returns:
        dict: Execution status, container exit/reason, image ID and termination
            details. Missing final evidence is interrupted; conflicting success
            or exit evidence is inconsistent. This does not verify file contents.
    """
    statuses = pod.get("status", {}).get("containerStatuses", [])
    container = next((item for item in statuses if item["name"] == "opendc"), {})
    terminated = container.get("state", {}).get("terminated", {})
    exit_code = terminated.get("exitCode")
    status = manifest.get("status", "interrupted")
    if not manifest or status == "started" or not terminated:
        status = "interrupted"
    elif manifest.get("runner_exit_code") != exit_code:
        status = "inconsistent"
    elif status == "succeeded":
        process = manifest.get("process") or {}
        validation = manifest.get("validation") or {}
        if (manifest.get("contract") != CONTRACT or exit_code != 0
                or not isinstance(validation, dict) or validation.get("status") != "passed"
                or not isinstance(process, dict)
                or process.get("exit_code") != 0 or process.get("timed_out") is not False
                or process.get("received_signal") is not None or process.get("launch_error") is not None):
            status = "inconsistent"
    return {"status": status, "container_exit_code": exit_code,
            "termination_reason": terminated.get("reason"), "image_id": container.get("imageID"),
            "termination": terminated}


def verify_collection_source(job, pods, remote_dir, worker_hostname):
    """Return the single Pod after binding its Job, worker and artifact paths.

    Check owner UID, node selectors, scheduled node and both hostPath mounts.
    An unscheduled Pod is allowed so prepared inputs remain retrievable after
    a deadline; execution classification still reports interruption.

    Args:
        job (dict): Retrieved Job record and Pod template.
        pods (list[dict]): Pods retrieved for the Job.
        remote_dir (str): Requested staging root containing inputs and results.
        worker_hostname (str): Hostname reported by the SSH artifact source.

    Returns:
        dict: The single Pod whose ownership and artifact location match the Job.

    Raises:
        ValueError: Ownership, worker identity, Pod count or volume paths differ.
    """
    job_spec = job["spec"]["template"]["spec"]
    node = job_spec.get("nodeSelector", {}).get("kubernetes.io/hostname")
    if not node or worker_hostname != node:
        raise ValueError("SSH worker hostname differs from the Job node selector")
    job_uid = job.get("metadata", {}).get("uid")
    if len(pods) != 1 or not job_uid:
        raise ValueError("expected one Pod owned by the retrieved Job")
    pod = pods[0]
    if not any(owner.get("kind") == "Job" and owner.get("uid") == job_uid and owner.get("controller")
               for owner in pod.get("metadata", {}).get("ownerReferences", [])):
        raise ValueError("Pod does not belong to the retrieved Job")
    pod_spec = pod.get("spec", {})
    if pod_spec.get("nodeName") and pod_spec["nodeName"] != worker_hostname:
        raise ValueError("SSH worker hostname differs from the scheduled Pod node")
    # A deadline can fail an unscheduled Pod. Its selected worker still holds
    # the prepared inputs, so allow retrieval while classification stays interrupted.
    for description, spec in (("Job", job_spec), ("Pod", pod_spec)):
        if spec.get("nodeSelector", {}).get("kubernetes.io/hostname") != node:
            raise ValueError(f"{description} node selector differs from the artifact worker")
        volumes = {volume["name"]: volume for volume in spec.get("volumes", [])}
        for name in ("inputs", "results"):
            if volumes.get(name, {}).get("hostPath", {}).get("path") != remote_dir + "/" + name:
                raise ValueError(f"{description} {name} hostPath differs from the requested artifact directory")
    return pod


def verify_execution_artifacts(directory, manifest):
    """Check finalized output hashes and recheck inputs for successful runs.

    An absent or started manifest has no finalized inventory and is left for
    interruption classification. Other malformed or mismatched manifests
    raise ValueError; this check never converts partial results into success.

    Args:
        directory (str or Path): Collected run directory containing execution.json.
        manifest (dict): Parsed execution record, or an empty object for an interrupted run.

    Raises:
        ValueError: The finalized manifest, artifact hashes or copied inputs are invalid.
    """
    if not isinstance(manifest, dict):
        raise ValueError("expected an execution manifest object")
    if not manifest or manifest.get("status") == "started":
        return
    if (manifest.get("contract") != CONTRACT
            or manifest.get("status") not in ("succeeded", "failed", "timed_out", "interrupted", "invalid_input")):
        raise ValueError("unrecognized finalized execution manifest")
    if file_hashes(directory, exclude=("execution.json",)) != manifest.get("sha256"):
        raise ValueError("execution artifact hash mismatch: finalized files changed or are missing")
    if manifest["status"] == "succeeded":
        verify_inputs(Path(directory) / "inputs")


def collect(controller, worker, key, namespace, job_name, remote_dir, output_dir):
    """Retrieve terminal Kubernetes evidence and verify copied node-local files.

    Never delete remote resources here; cleanup follows verified collection.

    Args:
        controller (str): SSH destination providing kubectl access.
        worker (str): SSH destination holding the experiment directory.
        key (str or Path): SSH private-key path for both destinations.
        namespace (str): Namespace containing the Job.
        job_name (str): Terminal Job to collect.
        remote_dir (str): Staging root matching the Job and Pod volume paths.
        output_dir (str or Path): New local directory for collected evidence.

    Returns:
        dict: Persisted collection record. A collected record can describe a
            failed or interrupted simulation; inspect its execution status too.
            Retrieval or verification failures produce an incomplete record
            and retain any partial evidence, including unavailable-log errors.

    Raises:
        ValueError: Initial name or staging-path validation fails.
        FileExistsError: The output directory already exists.
    """
    namespace, job_name = _name(namespace), _name(job_name)
    remote_dir = _remote_directory(remote_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    record = {"status": "collecting", "started_at": utc_now(), "namespace": namespace,
              "job": job_name, "worker": worker, "remote_dir": remote_dir, "errors": []}
    write_json(output / "collection.json", record)
    try:
        base = ["kubectl", "-n", namespace]
        job = json.loads(ssh(controller, key, base + ["get", "job", job_name, "-o", "json"]))
        write_json(output / "job.json", job)
        conditions = job.get("status", {}).get("conditions", [])
        if not any(c["type"] in ("Complete", "Failed") and c["status"] == "True" for c in conditions):
            raise ValueError("Job is not terminal; preserve it and collect after completion or deadline")
        pods = json.loads(ssh(controller, key, base + ["get", "pods", "-l", f"job-name={job_name}", "-o", "json"]))
        write_json(output / "pods.json", pods)
        events = json.loads(ssh(controller, key, base + ["get", "events", "-o", "json"]))
        write_json(output / "events.json", events)
        for pod in pods["items"]:
            name = pod["metadata"]["name"]
            try:
                (output / f"{name}.log").write_bytes(ssh(controller, key, base + ["logs", name, "-c", "opendc", "--timestamps"]))
            except RuntimeError as exc:
                record["errors"].append(f"container logs unavailable: {exc}")
            if pod.get("spec", {}).get("nodeName"):
                node = json.loads(ssh(controller, key, ["kubectl", "get", "node", pod["spec"]["nodeName"], "-o", "json"]))
                write_json(output / "node.json", node)
        record["worker_hostname"] = ssh(worker, key, ["hostname"]).decode().strip()
        pod = verify_collection_source(job, pods["items"], remote_dir, record["worker_hostname"])
        before = json.loads(ssh(worker, key, ["python3", "-c", REMOTE_HASH_SCRIPT, remote_dir]))
        archive = ssh(worker, key, ["tar", "-C", remote_dir, "-cf", "-", "."], timeout=60)
        (output / "artifacts.tar").write_bytes(archive)
        artifacts = output / "artifacts"
        artifacts.mkdir()
        extract_artifacts(io.BytesIO(archive), artifacts)
        after = json.loads(ssh(worker, key, ["python3", "-c", REMOTE_HASH_SCRIPT, remote_dir]))
        if before != after or file_hashes(artifacts) != after:
            raise ValueError("artifact hash mismatch or remote artifacts changed during collection")
        write_json(output / "remote-sha256.json", after)
        execution = artifacts / "results/run/execution.json"
        manifest = json.loads(execution.read_text()) if execution.exists() else {}
        verify_execution_artifacts(execution.parent, manifest)
        record["execution"] = classify_execution(pod, manifest)
        if record["execution"]["status"] == "inconsistent":
            raise ValueError("execution manifest is inconsistent with successful validation or container termination")
        record["artifacts_verified"] = True
        record["status"] = "collected" if not record["errors"] else "incomplete"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired, tarfile.TarError) as exc:
        record["status"] = "incomplete"
        record["errors"].append(str(exc))
    record.update({"finished_at": utc_now(), "collection_seconds": time.monotonic() - started,
                   "sha256": file_hashes(output, exclude=("collection.json",))})
    write_json(output / "collection.json", record)
    return record


def main(argv=None):
    """Render a Job or collect evidence from CLI arguments and return an exit code.

    Return 0 for rendering or a collected successful run, 1 for incomplete or
    unsuccessful collection, and 2 for handled input/filesystem errors.
    argv defaults to the process arguments.

    Args:
        argv (list[str] or None): CLI arguments; None uses the process arguments.

    Returns:
        int: 0 for rendering or collected success, 1 for unsuccessful collection,
            or 2 for handled input/filesystem errors.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("manifest")
    retrieve = commands.add_parser("collect")
    for command in (render, retrieve):
        command.add_argument("--namespace", required=True)
        command.add_argument("--job", required=True)
        command.add_argument("--remote-dir", required=True)
    render.add_argument("--image", required=True)
    render.add_argument("--node", default="cloud0matthijs")
    render.add_argument("--timeout-seconds", type=float, default=120)
    retrieve.add_argument("--controller", required=True)
    retrieve.add_argument("--worker", required=True)
    retrieve.add_argument("--ssh-key", type=Path, required=True)
    retrieve.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            print(json.dumps(job_manifest(args.namespace, args.job, args.image, args.node, args.remote_dir, args.timeout_seconds), indent=2))
            return 0
        result = collect(args.controller, args.worker, args.ssh_key, args.namespace, args.job, args.remote_dir, args.output_dir)
        print(json.dumps(result))
        return 0 if result["status"] == "collected" and result["execution"]["status"] == "succeeded" else 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
