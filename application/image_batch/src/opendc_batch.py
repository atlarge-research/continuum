"""Manually execute prepared candidates sequentially, retaining auditable failures."""
from __future__ import annotations

import argparse
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import time

from opendc_inputs import file_hashes, verify_inputs, write_json
from opendc_kubernetes import (
    collect,
    job_manifest,
    ssh,
    verify_execution_artifacts,
    classify_execution,
)
from opendc_run import utc_now


def remote_input(host, key, arguments, data):
    """Send bytes to a quoted SSH command without invoking a local shell.

    Args:
        host (str): SSH destination.
        key (str or Path): SSH private key.
        arguments (list[str]): Remote program and arguments.
        data (bytes): Standard input.

    Returns:
        bytes: Command output.

    Raises:
        RuntimeError: Remote command failed.
        subprocess.TimeoutExpired: Transfer exceeded four minutes.
    """
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-i",
            str(key),
            host,
            shlex.join(arguments),
        ],
        input=data,
        capture_output=True,
        timeout=240,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def run_local_case(source, output, image, timeout_seconds):
    """Execute a case in an offline constrained Docker container.

    Args:
        source (Path): Verified prepared inputs.
        output (Path): New directory for Docker logs and runner output.
        image (str): Locally built immutable image tag.
        timeout_seconds (float): Simulator process deadline.

    Returns:
        dict: Execution status and relative runner directory.

    Raises:
        ValueError: Final execution artifacts do not verify.
        subprocess.TimeoutExpired: Docker did not terminate after the runner deadline.
    """
    output.mkdir(parents=True, exist_ok=False)
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        "none",
        "--read-only",
        "--hostname",
        "opendc-controlled",
        "--add-host",
        "opendc-controlled:127.0.0.1",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=256m",
        "--cpus=1",
        "--memory=2g",
        "-v",
        f"{source}:/inputs:ro",
        "-v",
        f"{output}:/results",
        image,
        "run",
        "--input-dir",
        "/inputs",
        "--output-dir",
        "/results/run",
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, timeout=timeout_seconds + 60, check=False)
    (output / "docker.stdout").write_bytes(result.stdout)
    (output / "docker.stderr").write_bytes(result.stderr)
    path = output / "run/execution.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    if manifest:
        verify_execution_artifacts(path.parent, manifest)
    consistency = classify_execution(
        {
            "status": {
                "containerStatuses": [
                    {"name": "opendc", "state": {"terminated": {"exitCode": result.returncode}}}
                ]
            }
        },
        manifest,
    )
    return {
        "status": consistency["status"],
        "runner_dir": "run",
        "docker_exit_code": result.returncode,
        "wall_seconds": time.monotonic() - started,
        "validated": result.returncode == 0 and consistency["status"] == "succeeded",
    }


def _preflight(controller, runner_host, key, node, output):
    """Record current control-plane admission and load evidence before staging.

    Args:
        controller (str): SSH host providing kubectl.
        runner_host (str): SSH artifact host, which must be the selected control plane.
        key (str or Path): SSH private key.
        node (str): Expected hostname and Kubernetes node name.
        output (Path): Existing evidence directory.

    Raises:
        ValueError: Node identity, role, taint or readiness is unsuitable.
    """
    record = json.loads(ssh(controller, key, ["kubectl", "get", "node", node, "-o", "json"]))
    write_json(output / "node-before.json", record)
    if ssh(runner_host, key, ["hostname"]).decode().strip() != node:
        raise ValueError("runner SSH host differs from selected node")
    labels = record["metadata"]["labels"]
    taints = record["spec"].get("taints", [])
    if (
        "node-role.kubernetes.io/control-plane" not in labels
        or labels.get("kubernetes.io/hostname") != node
        or record["spec"].get("unschedulable", False)
        or not any(
            item.get("type") == "Ready" and item.get("status") == "True"
            for item in record["status"].get("conditions", [])
        )
        or not any(
            item["key"] == "node-role.kubernetes.io/control-plane"
            and item["effect"] == "NoSchedule"
            for item in taints
        )
    ):
        raise ValueError("runner needs a ready schedulable control plane with its NoSchedule taint")
    (output / "control-plane-describe.txt").write_bytes(
        ssh(controller, key, ["kubectl", "describe", "node", node])
    )
    (output / "node-load-before.txt").write_bytes(ssh(controller, key, ["kubectl", "top", "nodes"]))
    (output / "api-ready-before.txt").write_bytes(
        ssh(controller, key, ["kubectl", "get", "--raw=/readyz"])
    )


def _stage_image(image, runner_host, key, output):
    """Import the exact local image and verify its runtime identity.

    Args:
        image (str): Immutable local image tag.
        runner_host (str): SSH artifact host.
        key (str or Path): SSH private key.
        output (Path): Existing evidence directory.

    Raises:
        ValueError: Imported image identity differs from the local image.
        subprocess.CalledProcessError: Docker inspection/save fails.
    """
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", image], timeout=30))
    write_json(output / "local-image.json", info)
    archive = output / "image.tar"
    subprocess.run(["docker", "save", "-o", str(archive), image], check=True, timeout=120)
    (output / "image-import.log").write_bytes(
        remote_input(
            runner_host,
            key,
            ["sudo", "ctr", "-n", "k8s.io", "images", "import", "-"],
            archive.read_bytes(),
        )
    )
    remote = json.loads(ssh(runner_host, key, ["sudo", "crictl", "inspecti", image]))
    write_json(output / "runner-image.json", remote)
    if remote["status"]["id"] != info[0]["Id"]:
        raise ValueError("imported image differs from local image")


def _stage_inputs(source, remote, host, key):
    """Create a fresh remote input/result directory and copy verified inputs.

    Args:
        source (Path): Verified local input directory.
        remote (str): Unique task-owned remote root.
        host (str): SSH artifact host.
        key (str or Path): SSH private key.
    """
    ssh(host, key, ["mkdir", "-m", "755", remote])
    ssh(host, key, ["mkdir", remote + "/inputs", remote + "/results"])
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for path in sorted(source.rglob("*")):
            archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
    remote_input(host, key, ["tar", "-C", remote + "/inputs", "-xf", "-"], stream.getvalue())
    ssh(host, key, ["sudo", "chown", "1000:1000", remote + "/results"])
    ssh(host, key, ["chmod", "-R", "a+rX", remote + "/inputs"])


def _scheduling(pods):
    """Extract Pod scheduling and startup delays separately from simulation duration.

    Args:
        pods (dict): Collected Kubernetes Pod list.

    Returns:
        list[dict]: Delays for each Pod with available condition timestamps.
    """
    result = []
    for pod in pods["items"]:
        created = datetime.fromisoformat(
            pod["metadata"]["creationTimestamp"].replace("Z", "+00:00")
        )
        scheduled = next(
            (
                item.get("lastTransitionTime")
                for item in pod["status"].get("conditions", [])
                if item["type"] == "PodScheduled" and item["status"] == "True"
            ),
            None,
        )
        delay = (
            (datetime.fromisoformat(scheduled.replace("Z", "+00:00")) - created).total_seconds()
            if scheduled
            else None
        )
        result.append({"pod": pod["metadata"]["name"], "scheduling_delay_seconds": delay})
    return result


def run_kubernetes_case(source, output, image, timeout_seconds, cluster, name):
    """Run one control-plane Job and clean up only after verified success collection.

    Args:
        source (Path): Prepared input directory.
        output (Path): New per-case evidence directory.
        image (str): Exact preloaded image.
        timeout_seconds (float): Simulator deadline.
        cluster (dict): Controller, runner_host, key, node and namespace settings.
        name (str): Unique Job name in this batch namespace.

    Returns:
        dict: Execution/collection outcome and relative runner output location.
    """
    output.mkdir(parents=True, exist_ok=False)
    controller, host, key = cluster["controller"], cluster["runner_host"], cluster["key"]
    namespace = cluster["namespace"]
    remote = f"/var/tmp/fns-opendc-{namespace}-{name}"
    _stage_inputs(source, remote, host, key)
    job = job_manifest(
        namespace, name, image, cluster["node"], remote, timeout_seconds, control_plane=True
    )
    write_json(output / "job-submitted.json", job)
    remote_input(controller, key, ["kubectl", "create", "-f", "-"], json.dumps(job).encode())
    started = time.monotonic()
    while time.monotonic() - started < 240:
        current = json.loads(
            ssh(controller, key, ["kubectl", "get", "job", name, "-n", namespace, "-o", "json"])
        )
        if any(
            item["type"] in ("Complete", "Failed") and item["status"] == "True"
            for item in current.get("status", {}).get("conditions", [])
        ):
            break
        time.sleep(1)
    else:
        raise TimeoutError("Job did not become terminal; remote evidence retained")
    collection = collect(controller, host, key, namespace, name, remote, output / "collection")
    complete = collection["status"] == "collected" and collection.get("artifacts_verified") is True
    status = collection.get("execution", {}).get("status", "failed")
    result = {
        "status": status,
        "validated": complete and status == "succeeded",
        "runner_dir": "collection/artifacts/results/run",
        "remote_dir": remote,
        "collection_status": collection["status"],
        "terminal_seconds": time.monotonic() - started,
    }
    if (output / "collection/pods.json").exists():
        result["scheduling"] = _scheduling(
            json.loads((output / "collection/pods.json").read_text())
        )
    if complete:
        ssh(controller, key, ["kubectl", "delete", "job", name, "-n", namespace, "--wait=true"])
        ssh(host, key, ["sudo", "rm", "-rf", "--", remote])
        result["cleanup_verified_artifacts"] = True
    return result


def run_suite(suite_dir, output_dir, *, image, backend="local", timeout_seconds=120, cluster=None):
    """Execute a ready immutable suite sequentially and stop on the first failure.

    Args:
        suite_dir (str or Path): Prepared suite with relative experiment paths.
        output_dir (str or Path): New evidence directory.
        image (str): Unique locally available image tag or digest.
        backend (str): Local Docker or Kubernetes execution.
        timeout_seconds (float): Per-process deadline.
        cluster (dict or None): Kubernetes connection and placement settings.

    Returns:
        dict: Persisted batch status, outcomes and number of unexecuted cases.

    Raises:
        ValueError: Suite, image or paths are invalid before execution.
        FileExistsError: Output directory already exists.
    """
    suite, output = Path(suite_dir).resolve(), Path(output_dir).resolve()
    manifest = json.loads((suite / "manifest.json").read_text())
    if manifest.get("contract") != "opendc-scenarios-v1" or manifest.get("status") != "ready":
        raise ValueError("expected a ready prepared scenario suite")
    if not image or image.endswith(":latest") or (":" not in image and "@sha256:" not in image):
        raise ValueError("use an immutable local image tag or digest")
    if output == suite or output.is_relative_to(suite) or suite.is_relative_to(output):
        raise ValueError("suite and output directories must be separate")
    if manifest.get("sha256") != file_hashes(suite, exclude=("manifest.json",)):
        raise ValueError("suite hash mismatch")
    if not isinstance(manifest.get("experiments"), list) or not manifest["experiments"]:
        raise ValueError("suite needs at least one experiment")
    seen_cases, seen_paths = set(), set()
    for item in manifest["experiments"]:
        source = (suite / item["input_dir"]).resolve()
        if not source.is_relative_to(suite) or source == suite:
            raise ValueError("experiment input escapes suite")
        verify_inputs(source)
        case = json.loads((source / "case.json").read_text())
        identity = (item["candidate"], item["scenario"])
        if (
            identity != (case["candidate"], case["scenario"])
            or identity in seen_cases
            or source in seen_paths
        ):
            raise ValueError("suite labels or unique case identity differ from prepared inputs")
        seen_cases.add(identity)
        seen_paths.add(source)
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds < 170:
        raise ValueError("timeout must be positive and below the Kubernetes deadline")
    if backend not in ("local", "kubernetes") or (backend == "kubernetes" and not cluster):
        raise ValueError("unsupported backend or missing cluster settings")
    if backend == "kubernetes":
        job_manifest(
            cluster["namespace"],
            "validation",
            image,
            cluster["node"],
            "/var/tmp/fns-opendc-validation",
            timeout_seconds,
            control_plane=True,
        )
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "contract": "opendc-batch-v1",
        "status": "running",
        "started_at": utc_now(),
        "backend": backend,
        "image": image,
        "suite_manifest": manifest,
        "experiments": [],
        "remaining_experiments": len(manifest["experiments"]),
    }
    write_json(output / "batch.json", record)
    try:
        if backend == "kubernetes":
            _preflight(
                cluster["controller"],
                cluster["runner_host"],
                cluster["key"],
                cluster["node"],
                output,
            )
            # create, never apply: an existing namespace is not owned by this invocation.
            ssh(
                cluster["controller"],
                cluster["key"],
                ["kubectl", "create", "namespace", cluster["namespace"]],
            )
            _stage_image(image, cluster["runner_host"], cluster["key"], output)
        for index, item in enumerate(manifest["experiments"]):
            source = suite / item["input_dir"]
            relative = f"experiments/{index:04d}"
            case_output = output / relative
            if backend == "local":
                result = run_local_case(source, case_output, image, timeout_seconds)
            else:
                result = run_kubernetes_case(
                    source, case_output, image, timeout_seconds, cluster, f"case-{index:04d}"
                )
            record["experiments"].append({**item, "output_dir": relative, **result})
            record["remaining_experiments"] -= 1
            write_json(output / "batch.json", record)
            print(
                json.dumps(
                    {
                        "candidate": item["candidate"],
                        "scenario": item["scenario"],
                        "status": result["status"],
                    }
                ),
                flush=True,
            )
            if result["status"] != "succeeded" or result.get("validated") is not True:
                record["status"] = "failed"
                break
        else:
            record["status"] = "succeeded"
        if backend == "kubernetes" and record["status"] == "succeeded":
            (output / "node-load-after.txt").write_bytes(
                ssh(cluster["controller"], cluster["key"], ["kubectl", "top", "nodes"])
            )
            ssh(
                cluster["controller"],
                cluster["key"],
                ["kubectl", "delete", "namespace", cluster["namespace"], "--wait=true"],
            )
            record["namespace_removed"] = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    record["finished_at"] = utc_now()
    record["sha256"] = file_hashes(output, exclude=("batch.json",))
    write_json(output / "batch.json", record)
    return record


def main(argv=None):
    """Run a manual suite from CLI arguments without forecasting or actuation.

    Args:
        argv (list[str] or None): CLI arguments, defaulting to process arguments.

    Returns:
        int: Zero for complete validated success, one for failure, two for invalid input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--backend", choices=("local", "kubernetes"), default="local")
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--controller")
    parser.add_argument("--runner-host")
    parser.add_argument("--ssh-key", type=Path)
    parser.add_argument("--node", default="cloudcontrollermatthijs")
    parser.add_argument("--namespace")
    args = parser.parse_args(argv)
    cluster = None
    if args.backend == "kubernetes":
        if not all((args.controller, args.runner_host, args.ssh_key, args.namespace)):
            parser.error(
                "Kubernetes requires --controller, --runner-host, --ssh-key and --namespace"
            )
        cluster = {
            "controller": args.controller,
            "runner_host": args.runner_host,
            "key": args.ssh_key,
            "node": args.node,
            "namespace": args.namespace,
        }
    try:
        result = run_suite(
            args.suite_dir,
            args.output_dir,
            image=args.image,
            backend=args.backend,
            timeout_seconds=args.timeout_seconds,
            cluster=cluster,
        )
        return 0 if result["status"] == "succeeded" else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
