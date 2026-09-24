"""Evaluate controlled Kubernetes admission changes from preserved API snapshots."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path


def _application_pods(snapshot):
    """Index application Pods without admitting observer or simulator runner Pods.

    Args:
        snapshot (dict): Kubernetes PodList.

    Returns:
        dict: Stable Pod UID to observed Pod record.

    Raises:
        ValueError: A snapshot repeats an application Pod identity.
    """
    records = [
        pod
        for pod in snapshot["items"]
        if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "image-batch-worker"
    ]
    indexed = {pod["metadata"]["uid"]: pod for pod in records}
    if len(indexed) != len(records):
        raise ValueError("duplicate application Pod identity")
    return indexed


def _scheduled_at(pod):
    """Read the successful scheduling condition without substituting container start.

    Args:
        pod (dict): Captured Kubernetes Pod.

    Returns:
        float or None: Epoch seconds, or missing scheduling evidence.
    """
    stamp = next(
        (
            condition.get("lastTransitionTime")
            for condition in pod["status"].get("conditions", [])
            if condition["type"] == "PodScheduled" and condition["status"] == "True"
        ),
        None,
    )
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() if stamp else None


def validate_intervention(evidence, final_pods):
    """Check observed cordon/drain or reserve admission without assuming VM shutdown.

    The request/acknowledgment interval and one-second API timestamp resolution
    define an explicitly inconclusive boundary. A final Pod absent from the
    post-ack snapshot is only a definite new admission when its scheduling
    timestamp is later than acknowledgment. These checks cover one controlled
    run; they do not estimate an action's causal performance improvement.

    Args:
        evidence (dict): Intervention kind, selected worker, times, controller clock-offset
            bounds and before/after API snapshots. Missing clock bounds are inconclusive.
        final_pods (dict): Final Kubernetes PodList after the measured workload's drain.

    Returns:
        dict: Supported, violated or inconclusive verdict with per-Pod evidence gaps.

    Raises:
        ValueError: Unknown operation, malformed request interval or duplicate Pod identity.
    """
    kind, worker = evidence["kind"], evidence["selected_worker"]
    requested = evidence["request_unix_seconds"]
    acknowledged = evidence["acknowledged_unix_seconds"]
    if kind not in ("busy", "empty", "up") or requested > acknowledged:
        raise ValueError("invalid intervention kind or request interval")
    expected_command = "uncordon" if kind == "up" else "cordon"
    if evidence["command"] != expected_command:
        raise ValueError("command does not match intervention kind")
    before = _application_pods(evidence["before_pods"])
    after = _application_pods(evidence["after_ack_pods"])
    final = _application_pods(final_pods)
    initially_assigned = {
        uid for uid, pod in before.items() if pod["spec"].get("nodeName") == worker
    }
    initial_active = sorted(
        uid
        for uid in initially_assigned
        if before[uid]["status"]["phase"] not in ("Succeeded", "Failed")
    )
    all_initial = {
        uid: pod["spec"]["nodeName"]
        for uid, pod in before.items()
        if pod["spec"].get("nodeName") and pod["status"]["phase"] not in ("Succeeded", "Failed")
    }
    violations, gaps = [], []
    clock = evidence.get("controller_clock_offset_seconds")
    if clock is None:
        gaps.append("host/controller clock alignment was not measured")
    elif (
        any(not math.isfinite(clock[key]) for key in ("lower", "upper"))
        or clock["lower"] > clock["upper"]
    ):
        raise ValueError("invalid controller clock-offset bounds")
    if (kind == "busy" and not initial_active) or (kind in ("empty", "up") and initial_active):
        violations.append("pre-action occupancy does not match the claimed intervention")
    for key, unschedulable in (("before_nodes", kind == "up"), ("after_nodes", kind != "up")):
        nodes = [n for n in evidence[key]["items"] if n["metadata"]["name"] == worker]
        if len(nodes) != 1:
            gaps.append(f"{key}: selected worker missing or duplicated")
        elif bool(nodes[0]["spec"].get("unschedulable", False)) != unschedulable:
            violations.append(f"{key}: selected worker admission state is incorrect")
    drained, missing, unfinished = [], [], []
    for uid, assigned_worker in all_initial.items():
        if uid not in final:
            missing.append(uid)
        elif final[uid]["spec"].get("nodeName") != assigned_worker:
            violations.append(f"initial Pod moved from its assigned worker: {uid}")
        elif final[uid]["status"]["phase"] == "Failed":
            violations.append(f"initial Pod failed instead of draining successfully: {uid}")
        elif final[uid]["status"]["phase"] != "Succeeded":
            unfinished.append(uid)
        else:
            drained.append(uid)
    if missing or unfinished:
        gaps.append("initial work lacks observed successful drain")
    new_after, boundary, unclassified = [], [], []
    for uid, pod in final.items():
        if pod["spec"].get("nodeName") != worker or uid in initially_assigned:
            continue
        stamp = _scheduled_at(pod)
        if stamp is None or clock is None:
            unclassified.append(uid)
        elif stamp > acknowledged + clock["upper"]:
            new_after.append(uid)
        else:
            # Second-resolution timestamps and the list/request interval cannot
            # reliably distinguish pre-request bindings from concurrent bindings.
            boundary.append(uid)
    disappeared = sorted(
        uid
        for uid, pod in after.items()
        if pod["spec"].get("nodeName") == worker and uid not in final and uid not in missing
    )
    if boundary or unclassified or disappeared:
        gaps.append("assignment ordering or final inventory is incomplete at the API boundary")
    if kind != "up" and new_after:
        violations.append(
            "new work was scheduled on the selected worker after cordon acknowledgment"
        )
    if kind == "up" and not new_after:
        gaps.append("no definite new reserve admission after acknowledgment")
    return {
        "schema_version": "opendc-observed-intervention-v1",
        "kind": kind,
        "selected_worker": worker,
        "status": "violated" if violations else "inconclusive" if gaps else "supported",
        "violations": violations,
        "gaps": gaps,
        "request_unix_seconds": requested,
        "acknowledged_unix_seconds": acknowledged,
        "controller_clock_offset_seconds": clock,
        "initial_active_pod_uids": initial_active,
        "all_initial_assignments": all_initial,
        "drained_initial_pod_uids": sorted(set(drained).intersection(initial_active)),
        "drained_all_initial_pod_uids": sorted(drained),
        "missing_initial_pod_uids": sorted(missing),
        "unfinished_initial_pod_uids": sorted(unfinished),
        "new_assignments_after_ack": sorted(new_after),
        "boundary_assignment_uids": sorted(boundary),
        "unknown_assignment_time_uids": sorted(unclassified),
        "disappeared_post_ack_pod_uids": disappeared,
        "physical_power_off_measured": False,
        "interpretation": "controlled Kubernetes admission/drain evidence; "
        "no measured VM power-off or causal action-performance benefit is inferred",
    }


def main():
    """Write a new observed-intervention verdict from preserved evidence files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intervention", type=Path, required=True)
    parser.add_argument("--final-pods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_intervention(
        json.loads(args.intervention.read_text()), json.loads(args.final_pods.read_text())
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
