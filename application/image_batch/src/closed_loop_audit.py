"""Observed controller and placement safety, retaining incomplete evidence explicitly."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from forecast_trace import milliseconds
from opendc_inputs import write_json


def audit_journal(rows):
    """Check intent uniqueness and serialization without treating reconciliation as a retry.

    Args:
        rows (list[dict]): Durable journal records in original file order.

    Returns:
        dict: Request counts, unresolved/uncertain identities and observed violations.
    """
    requests, pending, uncertain, overlaps, orphaned = Counter(), set(), set(), [], []
    intervals, opened = [], {}
    sequence_errors, mismatched, missing_proposal = [], [], []
    proposal = None
    for index, row in enumerate(rows):
        if row.get("sequence") != index:
            sequence_errors.append(index)
        event, identity = row["event"], row.get("action_id")
        if event == "cycle.begin":
            proposal = None
        elif event == "cycle.proposal":
            proposal = row
        if event == "action.request":
            if proposal is None:
                missing_proposal.append(identity)
            else:
                choice = proposal["proposal"]
                node = proposal["before"]["nodes"].get(row.get("selected_worker"), {})
                if (
                    choice["action"] != row.get("action")
                    or choice["selected_worker"] != row.get("selected_worker")
                    or node.get("uid") != row.get("node_uid")
                    or node.get("accepting") != (row.get("action") == "scale-down")
                ):
                    mismatched.append(identity)
            if pending:
                overlaps.append(identity)
            requests[identity] += 1
            pending.add(identity)
            opened[identity] = row
        elif event in ("action.result", "action.uncertain"):
            if identity not in requests:
                orphaned.append(identity)
            if event == "action.uncertain":
                uncertain.add(identity)
            else:
                pending.discard(identity)
                request = opened.pop(identity, None)
                if request and row.get("status") != "not_dispatched_stale":
                    intervals.append(
                        dict(
                            action_id=identity,
                            action=request.get("action"),
                            worker=request.get("selected_worker"),
                            start=request["recorded_at_ns"] / 1e9,
                            end=row.get("recorded_at_ns", request["recorded_at_ns"]) / 1e9,
                            status=row.get("status"),
                        )
                    )
    duplicate = sorted(identity for identity, count in requests.items() if count > 1)
    intervals.extend(
        dict(
            action_id=identity,
            action=row.get("action"),
            worker=row.get("selected_worker"),
            start=row["recorded_at_ns"] / 1e9,
            end=None,
            status="unresolved",
        )
        for identity, row in opened.items()
    )
    return dict(
        request_count=sum(requests.values()),
        duplicate_action_ids=duplicate,
        overlapping_request_ids=overlaps,
        unresolved_action_ids=sorted(pending),
        uncertain_action_ids=sorted(uncertain),
        orphan_result_ids=sorted(set(orphaned)),
        sequence_error_rows=sequence_errors,
        mismatched_proposal_action_ids=mismatched,
        missing_proposal_action_ids=missing_proposal,
        mutation_intervals=intervals,
        violations=bool(duplicate or overlaps or orphaned or sequence_errors or mismatched),
    )


def audit_inventory(jobs, pods, workers):
    """Join final application Job/Pod identities and inspect observed termination evidence.

    Args:
        jobs (list[dict]): Final application Jobs; native runner Jobs are excluded by caller.
        pods (list[dict]): Final namespace Pod inventory, including nonapplication Pods.
        workers (set[str]): Permitted application worker names.

    Returns:
        dict: Placement/replacement/termination findings and missing final evidence.
    """
    job_uids = {job["metadata"]["uid"] for job in jobs}
    owned = defaultdict(list)
    off_pool, evicted, deleted, restarted, unsuccessful = [], [], [], [], []
    unmatched, ambiguous = [], []
    for pod in pods:
        all_owners = {
            row["uid"] for row in pod["metadata"].get("ownerReferences", []) if row["kind"] == "Job"
        }
        owners = all_owners & job_uids
        application = (
            pod["metadata"].get("labels", {}).get("continuum.atlarge.nl/workload") == "image-batch"
        )
        if not owners and not application:
            continue
        name, status = pod["metadata"]["name"], pod.get("status", {})
        if not owners:
            unmatched.append(name)
        if len(all_owners) != 1:
            ambiguous.append(name)
        for uid in owners:
            owned[uid].append(name)
        node = pod.get("spec", {}).get("nodeName")
        if node and node not in workers:
            off_pool.append(name)
        if status.get("reason") == "Evicted":
            evicted.append(name)
        if pod["metadata"].get("deletionTimestamp"):
            deleted.append(name)
        if any(row.get("restartCount", 0) for row in status.get("containerStatuses", [])):
            restarted.append(name)
        if status.get("phase") != "Succeeded":
            unsuccessful.append(name)
    multiple = sorted(uid for uid, names in owned.items() if len(names) != 1)
    return dict(
        jobs=len(job_uids),
        application_pods=sum(len(names) for names in owned.values()),
        missing_final_pod_job_uids=sorted(job_uids - set(owned)),
        multiple_pod_job_uids=multiple,
        unmatched_application_pods=sorted(unmatched),
        ambiguous_job_owner_pods=sorted(ambiguous),
        off_pool_pods=sorted(off_pool),
        evicted_pods=sorted(evicted),
        deleting_pods=sorted(deleted),
        restarted_pods=sorted(restarted),
        nonsuccessful_pods=sorted(unsuccessful),
        final_application_pod_names=sorted(name for names in owned.values() for name in names),
        violations=bool(multiple or off_pool or evicted or deleted or restarted or ambiguous),
    )


def _state_view(state):
    """Extract simultaneous assignment and admission observations with freshness validity.

    Args:
        state (dict): One observer cluster-state record.

    Returns:
        dict: Timestamp, validity, nodes and live assigned Jobs.
    """
    at = milliseconds(state["timestamp"]) / 1000
    collection = state.get("collection", {})
    start = collection.get("started_at")
    valid = (
        start is not None
        and collection.get("missing_job_uids") == []
        and 0 <= at - milliseconds(start) / 1000 <= 3
    )
    assigned = {
        job["kubernetes_job_uid"]: job
        for group in ("active", "queued", "finished")
        for job in state["jobs"][group]
        if job.get("node_name")
        and job.get("pod_phase") not in ("Succeeded", "Failed")
        and job.get("job_terminal_status") not in ("Complete", "Failed")
    }
    return dict(
        time=at,
        collection_start=milliseconds(start) / 1000 if start else at,
        valid=valid,
        assigned=assigned,
        nodes={row["node_name"]: row for row in state["workers"]},
    )


def _binding_status(previous, view, name, intervals):
    """Classify one assignment using only a covered, unchanged admission bracket.

    Args:
        previous (dict or None): Immediately preceding observer view.
        view (dict): Current observer view containing the new assignment.
        name (str): Assigned worker name.
        intervals (list[dict]): Mutation intervals, with None for unresolved ends.

    Returns:
        str: covered, cordoned or uncertain assignment evidence.
    """
    if previous is None or not previous["valid"] or not view["valid"]:
        return "uncertain"
    if not 0 < view["time"] - previous["time"] <= 3:
        return "uncertain"
    if any(
        row["start"] <= view["time"]
        and (row["end"] is None or row["end"] >= previous["collection_start"])
        for row in intervals
    ):
        return "uncertain"
    node, prior = view["nodes"].get(name, {}), previous["nodes"].get(name, {})
    if (
        not node
        or node.get("schedulable") != prior.get("schedulable")
        or node.get("kubernetes_node_uid") != prior.get("kubernetes_node_uid")
    ):
        return "uncertain"
    return "covered" if node.get("schedulable") else "cordoned"


def audit_states(states, config, intervals):
    """Check live capacity and new-assignment brackets without inferring unseen events.

    Binding brackets use observer collection order. Mutation intervals use the
    host clock; without a measured offset bound, action-adjacent findings retain
    clock-alignment uncertainty even when no overlap is apparent.
    A binding overlapping mutation, missing membership or a collection gap is
    inconclusive. Completed inventory retirement is not a Pod disappearance.

    Args:
        states (list[dict]): Chronological observer states.
        config (dict): Declared worker CPU/memory and accepting-worker bounds.
        intervals (list[dict]): Journaled API mutation or reconciliation intervals.

    Returns:
        dict: Observed invariants, covered/uncertain bindings and concrete violation identities.
    """
    workers = {row["node_name"]: row for row in config["workers"]}
    seen, pod_names, previous = {}, set(), None
    cordoned, uncertain, moved, outside = set(), set(), set(), set()
    capacity, bounds, drains, invalid, covered = [], [], [], 0, 0
    node_uids, replaced = {}, set()
    for state in states:
        view = _state_view(state)
        if set(view["nodes"]) != set(workers):
            view["valid"] = False
        for name, node in view["nodes"].items():
            uid = node.get("kubernetes_node_uid")
            if name in node_uids and node_uids[name] != uid:
                replaced.add(name)
            node_uids[name] = uid
        invalid += not view["valid"]
        usage = defaultdict(lambda: [0, 0])
        for uid, job in view["assigned"].items():
            name = job["node_name"]
            if job.get("pod_name"):
                pod_names.add(job["pod_name"])
            if name not in workers:
                outside.add(uid)
            if uid in seen and seen[uid] != name:
                moved.add(uid)
            if uid not in seen:
                status = _binding_status(previous, view, name, intervals)
                if status == "uncertain":
                    uncertain.add(uid)
                elif status == "cordoned":
                    cordoned.add(uid)
                else:
                    covered += 1
            seen[uid] = name
            usage[name][0] += job.get("requested_cpu_count", 0)
            usage[name][1] += job.get("requested_memory_mb", 0)
        if view["valid"]:
            accepting = sum(row.get("schedulable") is True for row in view["nodes"].values())
            if not config["minimum_workers"] <= accepting <= config["maximum_workers"]:
                bounds.append(view["time"])
            draining = [
                name
                for name, count in usage.items()
                if count[0] and not view["nodes"].get(name, {}).get("schedulable")
            ]
            if len(draining) > 1:
                drains.append(view["time"])
            for name, count in usage.items():
                if name in workers and (
                    count[0] > workers[name]["configured_cores"] - 1 + 1e-9
                    or count[1] > workers[name]["memory_mib"]
                ):
                    capacity.append(dict(time=view["time"], worker=name, observed_usage=count))
        previous = view
    return dict(
        snapshots=len(states),
        invalid_snapshots=invalid,
        covered_new_bindings=covered,
        uncertain_binding_job_uids=sorted(uncertain),
        cordoned_binding_job_uids=sorted(cordoned),
        moved_job_uids=sorted(moved),
        off_pool_job_uids=sorted(outside),
        replaced_nodes=sorted(replaced),
        capacity_violations=capacity,
        accepting_bound_violation_times=bounds,
        multiple_draining_times=drains,
        observed_assigned_pod_names=sorted(pod_names),
        violations=bool(cordoned or moved or outside or replaced or capacity or bounds or drains),
    )


def audit_capture(capture):
    """Build a self-contained audit from immutable capture artifacts.

    Args:
        capture (Path): Collected physical capture directory.

    Returns:
        dict: Observed safety findings with explicit missing and uncertain evidence.
    """
    invocation = json.loads((capture / "invocation.json").read_text())
    config = dict(
        workers=[
            dict(
                node_name=name,
                configured_cores=invocation["worker_cores"],
                memory_mib=invocation["worker_memory_mib"],
            )
            for name in invocation["workers"]
        ],
        minimum_workers=invocation["minimum_workers"],
        maximum_workers=invocation["maximum_workers"],
    )
    journal_path = capture / "controller/journal.jsonl"
    journal = audit_journal(
        [json.loads(line) for line in journal_path.read_text().splitlines()]
        if journal_path.exists()
        else []
    )
    jobs = [
        row
        for row in json.loads((capture / "jobs.json").read_text())["items"]
        if row["metadata"].get("labels", {}).get("continuum.atlarge.nl/workload") == "image-batch"
    ]
    pods = json.loads((capture / "pods-final.json").read_text())["items"]
    inventory = audit_inventory(jobs, pods, set(invocation["workers"]))
    states = audit_states(
        [
            json.loads(line)
            for line in (capture / "observer/cluster-state.jsonl").read_text().splitlines()
        ],
        config,
        journal["mutation_intervals"],
    )
    missing = sorted(
        set(states["observed_assigned_pod_names"]) - set(inventory["final_application_pod_names"])
    )
    return dict(
        schema_version="opendc-closed-loop-safety-v1",
        capture=str(capture),
        journal=journal,
        inventory=inventory,
        states=states,
        observed_pods_missing_from_final_inventory=missing,
        observed_violations=any(row["violations"] for row in (journal, inventory, states)),
        interpretation="Observed invariants only; no Kubernetes Events/API audit log. "
        "Missing inventories and uncertain binding brackets cannot prove absence of violations. "
        "Host mutation versus observer timestamps lack a measured clock-offset bound.",
    )


def main():
    """Write a new audit without overwriting an earlier evidence result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    write_json(args.output, audit_capture(args.capture))


if __name__ == "__main__":
    main()
