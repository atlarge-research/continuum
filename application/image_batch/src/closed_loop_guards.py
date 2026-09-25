"""Fresh observation, guarded admission changes and the declared reactive baseline."""

import copy
import math

from forecast_trace import milliseconds


def snapshot_view(snapshot, config, *, now_seconds):
    """Validate a fresh worker/Job inventory and classify accepting/draining/reserves.

    Classifier termination does not release requests: only terminal Pods or Jobs
    do. Every configured worker must be observed Ready with a stable UID; C−1 is
    applied once to configured VM cores, then checked against actual allocatable.

    Args:
        snapshot (dict): Observer snapshot, including bounded membership reconciliation.
        config (dict): Configured worker resources and accepting-worker bounds.
        now_seconds (float): Current UTC epoch seconds on the controller host.

    Returns:
        dict: Validated topology, requests, queue and allocation accounting.

    Raises:
        ValueError: State is stale, incomplete, malformed, outside bounds or over capacity.
    """
    at = milliseconds(snapshot["timestamp"]) / 1000
    if not math.isfinite(now_seconds) or not 0 <= now_seconds - at <= 3:
        raise ValueError("state is stale or its timestamp is in the future")
    collection = snapshot.get("collection", {})
    if collection.get("missing_job_uids") != []:
        raise ValueError("observation membership is incomplete or unreconciled")
    configured = {worker["node_name"]: worker for worker in config["workers"]}
    observed = {worker["node_name"]: worker for worker in snapshot["workers"]}
    if (
        len(configured) != len(config["workers"])
        or len(observed) != len(snapshot["workers"])
        or set(configured) != set(observed)
    ):
        raise ValueError("observed worker topology differs from configured pool")
    nodes = {}
    for name, worker in observed.items():
        cores = configured[name]["configured_cores"]
        if (
            type(cores) is not int
            or cores <= 1
            or worker.get("ready") is not True
            or not worker.get("kubernetes_node_uid")
            or type(worker.get("schedulable")) is not bool
        ):
            raise ValueError("worker identity, readiness or configured capacity is invalid")
        cpu, memory = worker["allocatable_cpu_count"], worker["allocatable_memory_mb"]
        if (
            not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                for value in (cpu, memory)
            )
            or cpu < cores - 1
        ):
            raise ValueError("observed worker allocatable capacity cannot fit the model")
        nodes[name] = {
            "uid": worker["kubernetes_node_uid"],
            "accepting": worker["schedulable"],
            "application_cores": cores - 1,
            "memory_mib": math.floor(memory),
        }
    assignments, queue, seen = {}, [], set()
    used = {name: [0, 0] for name in nodes}
    for group in ("queued", "active", "finished"):
        for job in snapshot["jobs"].get(group, []):
            uid = job.get("kubernetes_job_uid")
            if not uid or uid in seen:
                raise ValueError("Job membership contains missing or duplicate identities")
            seen.add(uid)
            if job.get("pod_phase") in ("Succeeded", "Failed") or job.get(
                "job_terminal_status"
            ) in ("Complete", "Failed"):
                continue
            created = milliseconds(job["creation_time"]) / 1000
            if created > at:
                raise ValueError("Job creation is later than its observation")
            node = job.get("node_name")
            if not node:
                if group == "finished":
                    raise ValueError("unfinished release has no assigned worker")
                queue.append({"uid": uid, "created_at": created})
                continue
            cpu, memory = job.get("requested_cpu_count"), job.get("requested_memory_mb")
            if node not in nodes or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                for value in (cpu, memory)
            ):
                raise ValueError("assignment or requested resources are unknown")
            used[node][0] += cpu
            used[node][1] += memory
            if (
                used[node][0] > nodes[node]["application_cores"]
                or used[node][1] > nodes[node]["memory_mib"]
            ):
                raise ValueError("observed application requests exceed worker capacity")
            assignments[uid] = node
    accepting = sorted(name for name, node in nodes.items() if node["accepting"])
    draining = sorted(
        name for name, node in nodes.items() if not node["accepting"] and used[name][0]
    )
    reserves = sorted(set(nodes) - set(accepting) - set(draining))
    minimum, maximum = config.get("minimum_workers", 1), config.get("maximum_workers", 3)
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or not 1 <= minimum <= len(accepting) <= maximum <= len(nodes)
        or len(draining) > 1
    ):
        raise ValueError("accepting/draining worker count violates configured bounds")
    return {
        "timestamp_seconds": at,
        "nodes": nodes,
        "assignments": assignments,
        "queue": sorted(queue, key=lambda item: (item["created_at"], item["uid"])),
        "oldest_queue_wait_seconds": max(
            (now_seconds - item["created_at"] for item in queue), default=0
        ),
        "active_workers": accepting,
        "draining_workers": draining,
        "reserve_workers": reserves,
        "empty_workers": sorted(name for name in accepting if not used[name][0]),
        "application_slots": sum(nodes[name]["application_cores"] for name in accepting),
        "allocated_application_cores": sum(
            nodes[name]["application_cores"] for name in accepting + draining
        ),
        "powered_worker_count": len(nodes),
        "minimum_workers": minimum,
        "maximum_workers": maximum,
    }


def guard_action(before, fresh, proposal, config, *, decision_age):
    """Veto stale proposals or unsafe changes after a fresh pre-action observation.

    Args:
        before (dict): Validated state used for the forecast or reactive proposal.
        fresh (dict): Independently refreshed and validated pre-action state.
        proposal (dict): Action and explicit selected worker.
        config (dict): Configured accepting-worker bounds.
        decision_age (float): Current age of the causal proposal cutoff in seconds.

    Raises:
        ValueError: Proposal age, topology, membership or admission preconditions changed.
    """
    if not math.isfinite(decision_age) or not 0 <= decision_age <= 30:
        raise ValueError("decision is stale or its cutoff is in the future")
    if before["nodes"] != fresh["nodes"]:
        raise ValueError("worker topology, identity, capacity or admission state changed")
    if any(
        uid in fresh["assignments"] and fresh["assignments"][uid] != node
        for uid, node in before["assignments"].items()
    ):
        raise ValueError("an existing Pod assignment changed")
    action, worker = proposal["action"], proposal.get("selected_worker")
    if action == "unchanged":
        return
    if action == "scale-up":
        if worker not in fresh["reserve_workers"] or len(fresh["active_workers"]) >= config.get(
            "maximum_workers", 3
        ):
            raise ValueError("scale-up requires an empty Ready reserve within capacity bounds")
    elif action == "scale-down":
        if fresh["draining_workers"]:
            raise ValueError("another worker is already draining")
        if worker not in fresh["active_workers"] or len(fresh["active_workers"]) <= config.get(
            "minimum_workers", 1
        ):
            raise ValueError("scale-down target is not accepting or violates capacity bounds")
        if not before["queue"] and fresh["queue"]:
            raise ValueError("new queue pressure vetoes down selected from an empty queue")
        previous = {uid for uid, node in before["assignments"].items() if node == worker}
        current = {uid for uid, node in fresh["assignments"].items() if node == worker}
        if not current <= previous:
            raise ValueError("selected drain worker acquired a new assignment")
    else:
        raise ValueError("unknown action")


def reactive_action(view, history, *, now_seconds, fallback):
    """Apply the approved reactive baseline or its up-only forecast fallback.

    Args:
        view (dict): Fresh validated physical queue and allocation inventory.
        history (dict): Previous acknowledged action time and empty-worker streak.
        now_seconds (float): UTC epoch seconds for the shared cooldown.
        fallback (bool): True forbids down when the forecast is invalid or unavailable.

    Returns:
        dict: Proposal, explicit reason and next history; no physical action is performed.
    """
    state = copy.deepcopy(history)
    state.update(down_worker=None, down_wins=0)
    result = {
        "action": "unchanged",
        "selected_worker": None,
        "reason": "reactive_hold",
        "state": state,
        "fallback": fallback,
    }
    last = history.get("last_action_at")
    if last is not None and (
        not isinstance(last, (float, int))
        or isinstance(last, bool)
        or not math.isfinite(last)
        or not 0 <= now_seconds - last
        or now_seconds - last < 120
    ):
        return {**result, "reason": "action_cooldown_or_invalid_history"}
    if (
        view["reserve_workers"]
        and len(view["active_workers"]) < view["maximum_workers"]
        and (
            view["oldest_queue_wait_seconds"] > 30 or len(view["queue"]) > view["application_slots"]
        )
    ):
        return {
            **result,
            "action": "scale-up",
            "selected_worker": view["reserve_workers"][0],
            "reason": "reactive_queue_pressure",
        }
    if (
        fallback
        or view["queue"]
        or view["draining_workers"]
        or not view["empty_workers"]
        or len(view["active_workers"]) <= view["minimum_workers"]
    ):
        return result
    worker = view["empty_workers"][0]
    wins = history.get("down_wins", 0) if history.get("down_worker") == worker else 0
    if type(wins) is not int or wins < 0:
        return {**result, "reason": "proposal_history_invalid"}
    state.update(down_worker=worker, down_wins=wins + 1)
    if wins < 1:
        return {**result, "reason": "awaiting_second_empty_tick"}
    return {
        **result,
        "action": "scale-down",
        "selected_worker": worker,
        "reason": "reactive_two_empty_ticks",
    }


def reconcile_pending(pending, view):
    """Classify an uncertain API outcome without repeating its old request.

    Args:
        pending (dict): Durably journaled action intent and target node UID.
        view (dict): Fresh physical state after restart or an API exception.

    Returns:
        str: Whether the desired admission state is now observed; attribution stays uncertain.

    Raises:
        ValueError: The target identity changed or the journal contains an invalid action.
    """
    node = view["nodes"].get(pending["selected_worker"])
    if node is None or node["uid"] != pending["node_uid"]:
        raise ValueError("pending action target identity changed")
    if pending["action"] not in ("scale-up", "scale-down"):
        raise ValueError("pending action is not an admission change")
    expected = pending["action"] == "scale-up"
    return "observed_applied" if node["accepting"] == expected else "not_observed_applied"
