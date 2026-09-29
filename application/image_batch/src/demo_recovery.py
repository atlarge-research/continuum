"""Preserve a failed capture and stop its inspected sender without deleting evidence."""

import argparse
import json
from pathlib import Path
import re
import subprocess

from capture_run import CaptureSession
from opendc_inputs import write_json
from opendc_kubernetes import ssh


def stop_sender(values, output, result):
    """Stop only a container whose immutable inspection matches the recorded capture.

    Args:
        values (dict): Saved capture invocation with endpoint, image and namespace identity.
        output (Path): New recovery evidence directory.
        result (dict): Incrementally persisted recovery status.

    Raises:
        ValueError: Container identity or ownership differs, or stopping cannot be verified.
        RuntimeError: A bounded remote command fails.
        OSError: Evidence cannot be preserved before mutation.
    """
    namespace = values["namespace"]
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise ValueError("invalid saved capture namespace")
    host, key = values["endpoint"], values["ssh_key"]
    docker = ["sudo", "-n", "docker"]
    inventory = (
        ssh(
            host,
            key,
            docker
            + [
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                f"name=^/{namespace}$",
                "--format",
                "{{.ID}}",
            ],
            timeout=30,
        )
        .decode()
        .split()
    )
    write_json(output / "endpoint-inventory.json", inventory)
    if not inventory:
        result.update(endpoint_stopped=True, endpoint_status="already_absent")
        write_json(output / "recovery.json", result)
        return
    if len(inventory) != 1 or not re.fullmatch(r"[a-f0-9]{64}", inventory[0]):
        raise ValueError("endpoint inventory has no unique immutable container identity")
    inspected = json.loads(ssh(host, key, docker + ["inspect", inventory[0]], timeout=30))
    write_json(output / "endpoint-inspection.json", inspected)
    container = inspected[0] if len(inspected) == 1 else {}
    command = container.get("Config", {}).get("Cmd", [])
    run_ids = [
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--run-id"
    ]
    if (
        container.get("Id") != inventory[0]
        or container.get("Config", {}).get("Image") != values["endpoint_image"]
        or run_ids != [namespace]
        or not any(
            mount.get("Source") == "/tmp/" + namespace and mount.get("Destination") == "/review"
            for mount in container.get("Mounts", [])
        )
    ):
        raise ValueError("endpoint container ownership differs; no stop authorized")
    result.update(endpoint_container_id=container["Id"], endpoint_status="inspected_owned")
    write_json(output / "recovery.json", result)
    try:
        (output / "endpoint.log").write_bytes(
            ssh(host, key, docker + ["logs", container["Id"]], timeout=30)
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result["errors"].append(f"endpoint logs: {exc}")
    result["endpoint_status"] = "stop_requested"
    write_json(output / "recovery.json", result)
    ssh(host, key, docker + ["stop", "--time", "5", container["Id"]], timeout=30)
    remaining = (
        ssh(
            host,
            key,
            docker
            + [
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                "id=" + container["Id"],
                "--format",
                "{{.ID}} {{.State}}",
            ],
            timeout=30,
        )
        .decode()
        .strip()
    )
    (output / "endpoint-after.txt").write_text(remaining, encoding="utf-8")
    if remaining and remaining.split() not in (
        [container["Id"], "exited"],
        [container["Id"], "dead"],
    ):
        raise ValueError("owned endpoint stop could not be verified")
    result.update(endpoint_stopped=True, endpoint_status="stopped" if remaining else "removed")
    write_json(output / "recovery.json", result)


def recover_capture(capture):
    """Attempt bounded recovery while preserving incomplete namespaces and native staging.

    This function runs under the parent's aggregate recovery deadline. It never restores
    cordons/network or deletes the namespace; those require explicit reconciliation after
    failure. A successful function return is a recovery record, not restored infrastructure.

    Args:
        capture (Path): Exact output assigned to the failed capture child.

    Returns:
        dict: Incremental sender-stop and evidence outcomes, with unresolved restoration explicit.

    Raises:
        FileExistsError: Recovery evidence already exists and must not be overwritten.
        OSError: The initial recovery record cannot be written.
    """
    capture = Path(capture)
    output = capture / "timeout-recovery"
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "capture": str(capture),
        "endpoint_stopped": False,
        "restoration_complete": False,
        "namespace_preserved": True,
        "native_staging_preserved": True,
        "requires_reconciliation": True,
        "errors": [],
    }
    write_json(output / "recovery.json", result)
    try:
        values = json.loads((capture / "invocation.json").read_text())
        stop_sender(values, output, result)
        values["output"] = capture
        session = CaptureSession(argparse.Namespace(**values))
        for resource in ("nodes", "jobs", "pods"):
            arguments = () if resource == "nodes" else ("-n", values["namespace"])
            try:
                write_json(output / (resource + ".json"), session.get(resource, *arguments))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                result["errors"].append(f"{resource} inventory: {exc}")
            write_json(output / "recovery.json", result)
        recorded = json.loads((capture / "pod-start.json").read_text())
        session.pod_name = recorded["metadata"]["name"]
        current = session.get("pod", session.pod_name, "-n", values["namespace"])
        if current["metadata"]["uid"] != recorded["metadata"]["uid"]:
            raise ValueError("observer Pod was replaced; preserve namespace for reconciliation")
        session.archive_observer(output / "observer")
        result["observer_archived"] = True
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result["errors"].append(str(exc))
    write_json(output / "recovery.json", result)
    return result
