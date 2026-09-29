"""Tracked source freezes, matched captures and read-only infrastructure verification."""

import argparse
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

from capture_run import CaptureSession
from closed_loop_audit import audit_capture
from closed_loop_evidence import SCHEMA as EVIDENCE_SCHEMA, capture_evidence
from demo_cleanup import cleanup_native
from demo_configuration import (
    resolve_deployment,
    validate_experiment,
    validate_live_inventory,
)
from opendc_inputs import file_hashes, write_json
from opendc_kubernetes import ssh


def run_budget_seconds(settings):
    """Bound one run including response follow-up, profile emission and setup/collection.

    Args:
        settings (dict): Complete experiment settings.

    Returns:
        float: Seconds reserved before launching another physical run.
    """
    return (
        settings["period_seconds"] * settings["cycles"] + settings["followup_seconds"] + 180 + 300
    )


def require_time(settings, *, now, closure_at):
    """Keep the final closure reserve unavailable to experiment launches.

    Args:
        settings (dict): Complete experiment settings.
        now (float): Current UTC epoch seconds.
        closure_at (float): Absolute start of the protected closure window.

    Raises:
        ValueError: The full run budget would cross the closure boundary.
    """
    if now + run_budget_seconds(settings) > closure_at:
        raise ValueError("insufficient time before the protected closure reserve")


def freeze_source(output):
    """Archive committed source, including sibling manifests, into a fresh directory.

    Args:
        output (Path): New directory for the immutable committed source.

    Returns:
        dict: Source commit, archive hash and absolute extracted root.

    Raises:
        FileExistsError: Output already exists.
        subprocess.CalledProcessError: Git cannot read the committed source.
    """
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=tar", commit])
    (output / "source.tar").write_bytes(archive)
    root = output / "checkout"
    root.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        # The archive is produced from this repository's committed Git tree.
        stream.extractall(root, filter="data")
    result = dict(
        source_commit=commit,
        archive_sha256=hashlib.sha256(archive).hexdigest(),
        source_root=str(root),
        files=file_hashes(root),
    )
    write_json(output / "source.json", result)
    return result


def verify_frozen_source(source):
    """Check all committed bytes before executing a frozen comparison.

    Args:
        source (Path): Extracted checkout beside its source.json and source.tar.

    Raises:
        ValueError: The source files or preserved archive differ from their freeze.
    """
    recorded = json.loads((source.parent / "source.json").read_text(encoding="utf-8"))
    if (
        file_hashes(source) != recorded["files"]
        or hashlib.sha256((source.parent / "source.tar").read_bytes()).hexdigest()
        != recorded["archive_sha256"]
    ):
        raise ValueError("frozen source or archive changed")


def seal_protocol(protocol_path, output):
    """Copy numerical/deployment inputs and bind the matrix to source and image identity.

    Args:
        protocol_path (Path): Draft matrix with paths to existing source/configuration.
        output (Path): New directory holding the sealed protocol and exact input bytes.

    Returns:
        Path: Sealed protocol.json ready for the matrix runner.

    Raises:
        ValueError: Settings, source identity or matrix entries are invalid.
        FileExistsError: The protocol destination already exists.
        subprocess.CalledProcessError: The declared local native image is unavailable.
    """
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    validate_experiment(json.loads(Path(protocol["experiment_config"]).read_text(encoding="utf-8")))
    verify_frozen_source(Path(protocol["source_root"]))
    matrix_commands(protocol, output)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    origins, hashes = {}, {}
    for key, name in (
        ("continuum_config", "continuum.cfg"),
        ("inventory", "inventory.ini"),
        ("experiment_config", "experiment.json"),
    ):
        source = Path(protocol[key]).resolve()
        destination = output / name
        shutil.copyfile(source, destination)
        origins[key] = str(source)
        protocol[key] = str(destination)
        hashes[key] = hashlib.sha256(destination.read_bytes()).hexdigest()
    protocol.update(
        input_origins=origins,
        input_sha256=hashes,
        native_image_id=subprocess.check_output(
            ["docker", "image", "inspect", protocol["native_image"], "--format", "{{.Id}}"],
            text=True,
        ).strip(),
        sealed_at_seconds=time.time(),
    )
    destination = output / "protocol.json"
    write_json(destination, protocol)
    write_json(
        output / "seal.json",
        dict(protocol_sha256=hashlib.sha256(destination.read_bytes()).hexdigest()),
    )
    return destination


def verify_protocol(protocol_path):
    """Verify sealed study inputs and the local image before each physical run.

    Args:
        protocol_path (Path): Sealed protocol.json beside its seal and copied inputs.

    Returns:
        dict: Verified matrix and immutable input locations.

    Raises:
        ValueError: Protocol, input bytes, source or native image identity changed.
    """
    path = Path(protocol_path)
    seal = json.loads((path.parent / "seal.json").read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != seal["protocol_sha256"]:
        raise ValueError("sealed protocol changed")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    for key, expected in protocol["input_sha256"].items():
        if hashlib.sha256(Path(protocol[key]).read_bytes()).hexdigest() != expected:
            raise ValueError(f"sealed input changed: {key}")
    verify_frozen_source(Path(protocol["source_root"]))
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", protocol["native_image"], "--format", "{{.Id}}"], text=True
    ).strip()
    if image_id != protocol["native_image_id"]:
        raise ValueError("frozen native image identity changed")
    return protocol


def matrix_commands(protocol, output):
    """Build exact matched capture commands from a frozen protocol, without execution.

    Args:
        protocol (dict): Source, deployment, experiment, image and ordered seed/arm inputs.
        output (Path): Study evidence root containing fresh per-run destinations.

    Returns:
        list[dict]: Seed/arm identities, output paths and complete argv lists.

    Raises:
        ValueError: An arm is unsupported or the matrix duplicates a seed/arm pair.
    """
    result, seen = [], set()
    for row in protocol["matrix"]:
        seed, arm = row["seed"], row["arm"]
        if (seed, arm) in seen:
            raise ValueError("duplicate seed/arm in matrix")
        if (
            arm not in ("fixed", "reactive", "forecast")
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed < 0
        ):
            raise ValueError("invalid matrix seed or arm")
        seen.add((seed, arm))
        name = f"{protocol['run_prefix']}-s{seed}-{arm}"
        destination = Path(output).resolve() / "experiments" / name
        command = [
            sys.executable,
            "-m",
            "capture_run",
            "--output",
            str(destination),
            "--namespace",
            name,
            "--seed",
            str(seed),
            "--control-arm",
            arm,
            "--admission-mode",
            "fifo",
            "--continuum-config",
            protocol["continuum_config"],
            "--inventory",
            protocol["inventory"],
            "--experiment-config",
            protocol["experiment_config"],
            "--native-image",
            protocol["native_image"],
            "--source-dir",
            str(Path(protocol["source_root"]) / "application/image_batch/src"),
            "--template-namespace",
            protocol.get("template_namespace", "fns-demo"),
            "--template-deployment",
            protocol.get("template_deployment", "image-batch-adapter"),
        ]
        result.append(dict(seed=seed, arm=arm, output=str(destination), command=command))
    return result


def cleanup_complete(cleanup):
    """Check capture restoration independently of whether its controller was beneficial.

    Args:
        cleanup (dict): Capture cleanup record.

    Returns:
        bool: All required restoration checks explicitly passed.
    """
    return all(
        cleanup.get(key) is True
        for key in ("namespace_removed", "network_restored", "original_deployment_preserved")
    )


def collect_metrics(capture, role):
    """Produce current metrics and audits directly from a preserved capture.

    Args:
        capture (Path): Collected capture directory, including failed policy attempts.
        role (str): Predeclared pilot or heldout role.

    Returns:
        dict: Paths of the generated numerical evidence.

    Raises:
        FileExistsError: Analysis destinations already exist.
    """
    capture = Path(capture)
    paths = {
        name: capture.with_name(capture.name + f"-{name}.json") for name in ("metrics", "safety")
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("analysis output already exists")
    write_json(
        paths["metrics"],
        {"schema_version": EVIDENCE_SCHEMA, "runs": [capture_evidence(capture, role)]},
    )
    write_json(paths["safety"], audit_capture(capture))
    return {name: str(path) for name, path in paths.items()}


def run_matrix(protocol_path, output):
    """Run a frozen matrix sequentially, stopping on capture or restoration failure.

    Args:
        protocol_path (Path): Frozen JSON protocol including closure_at_seconds and role.
        output (Path): Existing study evidence root.

    Raises:
        ValueError: Time reserve is insufficient or source identity changed.
        RuntimeError: A capture fails or does not restore its infrastructure.
        FileExistsError: A run or its execution log already exists.
    """
    protocol = verify_protocol(protocol_path)
    settings = json.loads(Path(protocol["experiment_config"]).read_text(encoding="utf-8"))
    source = Path(protocol["source_root"])
    verify_frozen_source(source)
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(source / "application/image_batch/src"), str(source))),
        "OPENDC_RUNTIME": "fns-demo",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MPLCONFIGDIR": str(Path(output) / "mpl-cache"),
    }
    commands = matrix_commands(protocol, output)
    (Path(output) / "experiments").mkdir(exist_ok=True)
    for row in commands:
        verify_protocol(protocol_path)
        require_time(settings, now=time.time(), closure_at=protocol["closure_at_seconds"])
        capture = Path(row["output"])
        if capture.exists():
            raise FileExistsError(capture)
        write_json(capture.with_suffix(".command.json"), {**row, "started_at_seconds": time.time()})
        with capture.with_suffix(".log").open("xb") as stream:
            result = subprocess.run(
                row["command"],
                cwd=source,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=run_budget_seconds(settings),
            )
        if result.returncode or not (capture / "cleanup.json").exists():
            raise RuntimeError(
                f"capture failed; preserve and reconcile before continuing: {capture}"
            )
        cleanup = json.loads((capture / "cleanup.json").read_text(encoding="utf-8"))
        if not cleanup_complete(cleanup):
            raise RuntimeError(f"capture restoration incomplete: {capture}")
        cleanup_native(capture)
        metrics = collect_metrics(capture, protocol["role"])
        print(
            json.dumps({**row, "collected": metrics, "finished_at_seconds": time.time()}),
            flush=True,
        )


def snapshot_infrastructure(settings, output):
    """Preserve live API, network, scheduler and local QEMU state without remote mutation.

    Args:
        settings (dict): Resolved deployment plus capture namespace/output settings.
        output (Path): Fresh evidence destination.

    Returns:
        dict: Complete inventory and stable VM identities for restoration comparisons.

    Raises:
        ValueError: Live node identity/readiness differs from configured deployment.
        FileExistsError: Destination already exists.
        subprocess.CalledProcessError: A required read-only inventory command fails.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    session = CaptureSession(
        argparse.Namespace(**{**settings, "output": output, "namespace": "fns-inventory"})
    )
    api = {}
    for kind in (
        "nodes",
        "pods",
        "jobs",
        "namespaces",
        "clusterrolebindings",
        "deployments",
        "services",
    ):
        arguments = [kind] + (
            [] if kind in ("nodes", "namespaces", "clusterrolebindings") else ["-A"]
        )
        document = session.get(*arguments)
        write_json(output / f"{kind}.json", document)
        api[kind] = document["items"]
    validate_live_inventory({"items": api["nodes"]}, settings)
    scheduler = {}
    for name, path in (
        ("manifest", "/etc/kubernetes/manifests/kube-scheduler.yaml"),
        ("packing", "/etc/kubernetes/fns-packing.yaml"),
    ):
        scheduler[name] = ssh(
            settings["controller"], settings["ssh_key"], ["sudo", "cat", path]
        ).decode()
    replay = {
        "state": ssh(
            settings["endpoint"],
            settings["ssh_key"],
            [
                "sudo",
                "sh",
                "-c",
                "if test -e /run/continuum-mahimahi/state.json; "
                "then cat /run/continuum-mahimahi/state.json; else echo absent; fi",
            ],
        )
        .decode()
        .strip(),
        "service": ssh(
            settings["endpoint"],
            settings["ssh_key"],
            [
                "systemctl",
                "show",
                "continuum-mahimahi.service",
                "--property=ActiveState",
                "--value",
            ],
        )
        .decode()
        .strip(),
    }
    running = subprocess.check_output(["virsh", "list", "--name"], text=True).split()
    vms = {}
    for host in settings["inventory_hosts"]:
        name = host["name"]
        raw = subprocess.check_output(["virsh", "dumpxml", name])
        (output / f"{name}.xml").write_bytes(raw)
        tree = ET.fromstring(raw)
        vms[name] = dict(
            uuid=tree.findtext("uuid"),
            disks=[item.attrib for item in tree.findall("./devices/disk/source")],
            memory=tree.findtext("memory"),
            vcpus=tree.findtext("vcpu"),
            running=name in running,
        )
    result = dict(
        api=api, scheduler=scheduler, replay=replay, vms=vms, network=session.network_state()
    )
    write_json(output / "snapshot.json", result)
    write_json(output / "settings.json", settings)
    return result


def restoration_checks(baseline, current):
    """Compare stable specifications and identities without hiding new live work.

    Args:
        baseline (dict): Preserved pre-experiment snapshot.
        current (dict): New read-only snapshot after restoration.

    Returns:
        dict[str, bool]: Independent preservation, readiness and live-work checks.
    """
    checks = {
        name + "_preserved": current[name] == baseline[name]
        for name in ("network", "scheduler", "replay", "vms")
    }
    for kind in ("nodes", "deployments", "services"):
        identities = [
            {item["metadata"]["uid"]: item["spec"] for item in snapshot["api"][kind]}
            for snapshot in (baseline, current)
        ]
        checks[kind + "_preserved"] = identities[0] == identities[1]
    for kind in ("namespaces", "clusterrolebindings"):
        checks[kind + "_preserved"] = {
            item["metadata"]["uid"] for item in baseline["api"][kind]
        } == {item["metadata"]["uid"] for item in current["api"][kind]}
    checks["no_active_jobs"] = not any(
        item.get("status", {}).get("active", 0) for item in current["api"]["jobs"]
    )
    checks["all_nodes_ready"] = all(
        any(
            row["type"] == "Ready" and row["status"] == "True"
            for row in item["status"].get("conditions", [])
        )
        for item in current["api"]["nodes"]
    )
    checks["vms_running"] = all(item["running"] for item in current["vms"].values())
    checks["deployments_available"] = all(
        item.get("status", {}).get("observedGeneration", 0) >= item["metadata"]["generation"]
        and item.get("status", {}).get("availableReplicas", 0) >= item["spec"].get("replicas", 1)
        for item in current["api"]["deployments"]
    )
    return checks


def main():
    """Expose tracked source, capture, metric and restoration-check workflows."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-source")
    freeze.add_argument("--output", type=Path, required=True)
    seal = commands.add_parser("seal-protocol")
    seal.add_argument("--protocol", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--protocol", type=Path, required=True)
    matrix.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--capture", type=Path, required=True)
    collect.add_argument("--role", choices=("pilot", "heldout"), required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--continuum-config", type=Path, required=True)
    snapshot.add_argument("--inventory", type=Path)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.command == "freeze-source":
        print(json.dumps(freeze_source(args.output)))
    elif args.command == "seal-protocol":
        print(seal_protocol(args.protocol, args.output))
    elif args.command == "matrix":
        run_matrix(args.protocol, args.output)
    elif args.command == "collect":
        print(json.dumps(collect_metrics(args.capture, args.role)))
    else:
        settings = resolve_deployment(args.continuum_config, args.inventory)
        current = snapshot_infrastructure(settings, args.output)
        if args.baseline:
            baseline = json.loads((args.baseline / "snapshot.json").read_text(encoding="utf-8"))
            checks = restoration_checks(baseline, current)
            write_json(args.output / "checks.json", checks)
            print(json.dumps(checks, indent=2))
            if not all(checks.values()):
                raise SystemExit("infrastructure restoration check failed")


if __name__ == "__main__":
    main()
