"""Opt-in local and isolated Kubernetes validation of a prebuilt OpenDC image.

Requires Docker, SSH access to the existing cluster, kubectl on its controller,
and passwordless sudo on the selected worker. Never provisions infrastructure.
"""
import argparse
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import write_json
from opendc_kubernetes import collect, job_manifest, ssh


def command(argv, log, data=None, expected=0):
    """Run local arguments, save stdout/stderr, and return stdout bytes and seconds.

    Optional data is passed as stdin bytes. Raise RuntimeError for an unexpected
    exit code; the subprocess has a 240-second timeout.

    Args:
        argv (list[str]): Local executable and arguments.
        log (Path): File receiving stdout and stderr, replacing existing contents.
        data (bytes or None): Optional standard input for the command.
        expected (int): Required process exit code.

    Returns:
        tuple[bytes, float]: Standard output and elapsed wall-clock seconds.

    Raises:
        RuntimeError: The command exit differs from expected.
        subprocess.TimeoutExpired: The command exceeds 240 seconds.
    """
    started = time.monotonic()
    result = subprocess.run(argv, input=data, capture_output=True, timeout=240, check=False)
    log.write_bytes(result.stdout + b"\nSTDERR:\n" + result.stderr)
    if result.returncode != expected:
        raise RuntimeError(f"unexpected exit {result.returncode}: see {log}")
    return result.stdout, time.monotonic() - started


def remote_input(host, key, argv, data):
    """Send stdin bytes to quoted remote arguments over SSH and return stdout.

    Used for image archives, fixture archives and kubectl manifests. Nonzero
    exits raise RuntimeError; the transfer has a 240-second timeout.

    Args:
        host (str): SSH destination, optionally including a user name.
        key (str or Path): SSH private-key path.
        argv (list[str]): Remote command arguments to quote.
        data (bytes): Standard input sent to the remote command.

    Returns:
        bytes: Standard output from the remote command.

    Raises:
        RuntimeError: SSH or the remote command returns nonzero.
        subprocess.TimeoutExpired: The SSH operation exceeds 240 seconds.
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
            shlex.join(argv),
        ],
        input=data,
        capture_output=True,
        timeout=240,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def local_runs(args, output):
    """Prepare both fixtures and run each three times in the supplied Docker image.

    Args:
        args (Namespace): Parsed options providing the image reference.
        output (Path): Existing absolute evidence root; its local child must be new.

    Returns:
        list: Per-run execution manifests and Docker wall-clock measurements,
            also saved to local-runs.json. Runs are offline with a read-only root.
    """
    local = output / "local"
    local.mkdir()
    base = [
        "docker",
        "run",
        "--rm",
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
        f"{local}:/evidence",
        args.image,
    ]
    measurements = []
    for fixture in ("controlled", "memory"):
        command(
            base + ["prepare", "--fixture", fixture, "--output-dir", f"/evidence/{fixture}-input"],
            output / f"prepare-{fixture}.log",
        )
        for index in range(3):
            name = f"{fixture}-{index}"
            argv = base + [
                "run",
                "--input-dir",
                f"/evidence/{fixture}-input",
                "--output-dir",
                f"/evidence/{name}",
            ]
            _, elapsed = command(argv, output / f"local-{name}.log")
            execution = json.loads((local / name / "execution.json").read_text())
            measurements.append(
                {"name": name, "docker_wall_seconds": elapsed, "execution": execution}
            )
    write_json(output / "local-runs.json", measurements)
    return measurements


def snapshot(args):
    """Return adapter Deployment and node configuration for preservation checks.

    Read via args.controller and args.ssh_key; omit transient status fields so
    the before/after comparison identifies configuration or node replacement.

    Args:
        args (Namespace): Controller SSH destination and key.

    Returns:
        dict: Adapter Deployment spec and node identities, specs and capacities.
    """

    def get(*argv):
        """Fetch a Kubernetes resource as parsed JSON through the controller.

        Args:
            *argv (str): Resource name and selectors passed after kubectl get.

        Returns:
            dict: Parsed JSON response from kubectl.
        """
        return json.loads(
            ssh(args.controller, args.ssh_key, ["kubectl", "get", *argv, "-o", "json"])
        )

    deployment = get("deployment", "image-batch-adapter", "-n", "fns-demo")
    nodes = get("nodes")
    return {
        "deployment_spec": deployment["spec"],
        "nodes": [
            {
                "name": node["metadata"]["name"],
                "uid": node["metadata"]["uid"],
                "spec": node["spec"],
                "capacity": node["status"]["capacity"],
            }
            for node in nodes["items"]
        ],
    }


def stage_case(args, source, remote, corrupt=False):
    """Stage prepared files and a UID-1000 results directory on the selected worker.

    Args:
        args (Namespace): Parsed worker SSH destination and key.
        source (Path): Local prepared fixture directory.
        remote (str): Unique remote staging root that must not already exist.
        corrupt (bool): Break Task Parquet and update its transport hash so the
            malformed-input case reaches the actual OpenDC loader.
    """
    ssh(
        args.worker,
        args.ssh_key,
        [
            "python3",
            "-c",
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir(); (p/'inputs').mkdir()",
            remote,
        ],
    )
    ssh(
        args.worker,
        args.ssh_key,
        ["sudo", "install", "-d", "-o", "1000", "-g", "1000", "-m", "0755", remote + "/results"],
    )
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(source), recursive=False)
    remote_input(
        args.worker,
        args.ssh_key,
        ["tar", "-xf", "-", "-C", remote + "/inputs", "--no-same-owner"],
        data.getvalue(),
    )
    if corrupt:
        # This negative fixture passes transport integrity but fails inside OpenDC.
        script = """import pathlib,json,hashlib,sys
p=pathlib.Path(sys.argv[1])
(p/'trace/tasks.parquet').write_bytes(b'intentionally malformed parquet')
m=json.loads((p/'manifest.json').read_text())
m['sha256']['trace/tasks.parquet']=hashlib.sha256((p/'trace/tasks.parquet').read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps(m))
"""
        ssh(args.worker, args.ssh_key, ["python3", "-c", script, remote + "/inputs"])


def wait_job(args, namespace, name):
    """Wait up to 210 seconds for a Complete or Failed Job condition.

    Raise RuntimeError on expiry without deleting the Job or its evidence.

    Args:
        args (Namespace): Controller SSH destination and key.
        namespace (str): Namespace containing the Job.
        name (str): Job name to poll.

    Raises:
        RuntimeError: The Job has not reached a terminal condition within 210 seconds.
    """
    deadline = time.monotonic() + 210
    while time.monotonic() < deadline:
        job = json.loads(
            ssh(
                args.controller,
                args.ssh_key,
                ["kubectl", "get", "job", name, "-n", namespace, "-o", "json"],
            )
        )
        if any(
            c["type"] in ("Complete", "Failed") and c["status"] == "True"
            for c in job.get("status", {}).get("conditions", [])
        ):
            return
        time.sleep(1)
    raise RuntimeError("Job did not become terminal; preserve namespace and remote artifacts")


def kubernetes_runs(args, output):
    """Stage the image and validate six sequential cases in an isolated namespace.

    Refuse an existing namespace or concurrent active Jobs. Verify image identity,
    expected execution status and copied artifacts before removing each owned
    Job/directory. Remove the namespace after all cases and compare cluster
    snapshots. Failures stop cleanup so remote evidence remains inspectable.

    Args:
        args (Namespace): Image, namespace, node and controller/worker SSH options.
        output (Path): Evidence root containing prepared inputs from local_runs.

    Returns:
        list: Per-case collection records and time to observed terminal status.
    """
    namespace = args.namespace
    existing = ssh(
        args.controller,
        args.ssh_key,
        ["kubectl", "get", "namespace", namespace, "--ignore-not-found", "-o", "name"],
    )
    if existing.strip():
        raise ValueError("integration namespace already exists")
    jobs = json.loads(
        ssh(args.controller, args.ssh_key, ["kubectl", "get", "jobs", "-A", "-o", "json"])
    )
    if any(job.get("status", {}).get("active", 0) for job in jobs["items"]):
        raise ValueError(
            "active Jobs exist; do not overlap controlled validation with another experiment"
        )
    before = snapshot(args)
    write_json(output / "cluster-before.json", before)
    image, _ = command(["docker", "image", "inspect", args.image], output / "image-inspect.log")
    write_json(output / "image-inspect.json", json.loads(image))
    archive = output / "image.tar"
    _, save_seconds = command(
        ["docker", "save", "-o", str(archive), args.image], output / "image-save.log"
    )
    staged_at = time.monotonic()
    result = remote_input(
        args.worker,
        args.ssh_key,
        ["sudo", "ctr", "-n", "k8s.io", "images", "import", "-"],
        archive.read_bytes(),
    )
    (output / "image-import.log").write_bytes(result)
    inspect = ssh(args.worker, args.ssh_key, ["sudo", "crictl", "inspecti", args.image])
    write_json(output / "worker-image.json", json.loads(inspect))
    if json.loads(inspect)["status"]["id"] != json.loads(image)[0]["Id"]:
        raise ValueError("worker image ID differs from local image")
    write_json(
        output / "image-staging.json",
        {
            "docker_save_seconds": save_seconds,
            "transfer_import_inspect_seconds": time.monotonic() - staged_at,
        },
    )
    ssh(args.controller, args.ssh_key, ["kubectl", "create", "namespace", namespace])
    cases = [(f"controlled-{index}", "controlled", 120, "succeeded") for index in range(3)]
    cases += [
        ("memory", "memory", 120, "succeeded"),
        ("malformed", "controlled", 120, "failed"),
        ("timeout", "controlled", 0.2, "timed_out"),
    ]
    collections = []
    for name, fixture, timeout, expected in cases:
        remote = f"/var/tmp/fns-opendc-{namespace}-{name}"
        stage_case(args, output / "local" / f"{fixture}-input", remote, corrupt=name == "malformed")
        manifest = job_manifest(namespace, name, args.image, args.node, remote, timeout)
        write_json(output / f"job-{name}.json", manifest)
        submitted = time.monotonic()
        remote_input(
            args.controller,
            args.ssh_key,
            ["kubectl", "create", "-f", "-"],
            json.dumps(manifest).encode(),
        )
        wait_job(args, namespace, name)
        terminal_seconds = time.monotonic() - submitted
        result = collect(
            args.controller,
            args.worker,
            args.ssh_key,
            namespace,
            name,
            remote,
            output / "kubernetes" / name,
        )
        if result["status"] != "collected" or result["execution"]["status"] != expected:
            raise ValueError(
                f"unexpected {name} result; preserve namespace and remote artifacts: {result}"
            )
        # Only verified, task-owned directories and Jobs are removed.
        ssh(
            args.controller,
            args.ssh_key,
            ["kubectl", "delete", "job", name, "-n", namespace, "--wait=true"],
        )
        ssh(args.worker, args.ssh_key, ["sudo", "rm", "-rf", "--", remote])
        collections.append(
            {"name": name, "job_terminal_seconds": terminal_seconds, "collection": result}
        )
        print(
            json.dumps(
                {"case": name, "status": result["execution"]["status"], "artifacts_verified": True}
            ),
            flush=True,
        )
    ssh(args.controller, args.ssh_key, ["kubectl", "delete", "namespace", namespace, "--wait=true"])
    after = snapshot(args)
    write_json(output / "cluster-after.json", after)
    if before != after:
        raise ValueError("existing deployment/node configuration changed during integration")
    write_json(output / "kubernetes-runs.json", collections)
    write_json(
        output / "cleanup.json",
        {
            "namespace_removed": True,
            "run_directories_removed": True,
            "existing_deployment_and_nodes_unchanged": True,
            "vms_reprovisioned": False,
        },
    )
    return collections


def main():
    """Run the opt-in integration CLI and require matching local/Kubernetes records.

    Create a fresh evidence directory and save invocations, measurements and
    comparisons. Exceptions produce a nonzero process exit and retain evidence.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--node", default="cloud0matthijs")
    args = parser.parse_args()
    args.evidence_dir = args.evidence_dir.resolve()
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.evidence_dir / "invocation.json", {k: str(v) for k, v in vars(args).items()})
    local = local_runs(args, args.evidence_dir)
    kubernetes_runs(args, args.evidence_dir)
    comparisons = {}
    for fixture in ("controlled", "memory"):
        hashes = [
            run["execution"]["validation"]["semantic_sha256"]
            for run in local
            if run["name"].startswith(fixture)
        ]
        cases = (
            [f"controlled-{index}" for index in range(3)] if fixture == "controlled" else ["memory"]
        )
        for case in cases:
            path = args.evidence_dir / "kubernetes" / case / "artifacts/results/run/execution.json"
            hashes.append(json.loads(path.read_text())["validation"]["semantic_sha256"])
        if len(set(hashes)) != 1:
            raise ValueError(f"{fixture} local/Kubernetes simulator output is not repeatable")
        comparisons[fixture] = {"runs": len(hashes), "semantic_sha256": hashes[0], "passed": True}
    write_json(args.evidence_dir / "repeatability.json", comparisons)
    print("LOCAL_AND_KUBERNETES_VALIDATION_PASSED", flush=True)


if __name__ == "__main__":
    main()
