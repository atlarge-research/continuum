"""Fresh observation, guarded admission changes and the declared reactive baseline."""

import copy
import math

from forecast_trace import milliseconds


class IncompleteMembership(ValueError):
    """A non-atomic observer inventory still lacks a known unfinished Job."""


def snapshot_view(snapshot, config, *, now_seconds):
    """Validate a fresh worker/Job inventory and classify accepting/draining/reserves.

    Classifier termination does not release requests: only terminal Pods or Jobs
    do. Every configured worker must be observed Ready with a stable UID; C−1 is
    applied once to configured VM cores, then checked against actual allocatable.
    Availability uses collection completion; freshness includes its oldest API read.

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
    if not isinstance(collection.get("started_at"), str):
        raise ValueError("collection start time is unavailable")
    started = milliseconds(collection["started_at"]) / 1000
    if not started <= at or not 0 <= now_seconds - started <= 3:
        raise ValueError("collection is stale or its temporal bounds are invalid")
    if collection.get("missing_job_uids") != []:
        raise IncompleteMembership("observation membership is incomplete or unreconciled")
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
    demand = 0
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
            cpu, memory = job.get("requested_cpu_count"), job.get("requested_memory_mb")
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                for value in (cpu, memory)
            ):
                raise ValueError("requested resources are unknown")
            if not any(
                cpu <= worker["application_cores"] and memory <= worker["memory_mib"]
                for worker in nodes.values()
            ):
                raise ValueError("Job requests cannot fit any configured worker")
            demand += cpu
            node = job.get("node_name")
            if not node:
                if group == "finished":
                    raise ValueError("unfinished release has no assigned worker")
                queue.append({"uid": uid, "created_at": created, "requested_cpu_count": cpu})
                continue
            if node not in nodes:
                raise ValueError("assignment is unknown")
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
        "collection_started_seconds": started,
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
        "requested_cpu_demand": demand,
        "reactive_target_fraction": config.get("reactive_target_fraction", 0),
        "reactive_downscale_stabilization_seconds": config.get(
            "reactive_downscale_stabilization_seconds", 0
        ),
        "reactive_up_threshold": config.get("reactive_up_threshold", 0.9),
        "reactive_down_threshold": config.get("reactive_down_threshold", 0.7),
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
    if not math.isfinite(decision_age) or not 0 <= decision_age <= config.get(
        "decision_age_seconds", 30
    ):
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
    if before.get("pending_workers") or fresh.get("pending_workers"):
        raise ValueError("pending acquisition prevents another capacity change")
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
        previous = {uid for uid, node in before["assignments"].items() if node == worker}
        current = {uid for uid, node in fresh["assignments"].items() if node == worker}
        if not current <= previous:
            raise ValueError("selected drain worker acquired a new assignment")
    else:
        raise ValueError("unknown action")


def reactive_action(view, history, *, now_seconds, fallback, tick_id):
    """Compare unfinished CPU demand with current or reduced accepting capacity.

    With a configured capacity target, scale-up uses current unfinished demand
    immediately; scale-down retains the highest desired worker count over the
    stabilization window, including its exact lower boundary. The initial
    accepting count seeds that window. Legacy disabled settings keep the earlier
    threshold policy. Physical guards independently prevent unsafe dispatch.

    Args:
        view (dict): Fresh validated physical demand and allocation inventory.
        history (dict): Controller history to preserve without obsolete empty-check votes.
        now_seconds (float): UTC epoch seconds of this observation.
        fallback (bool): Whether an unavailable forecast invoked this same policy.
        tick_id (int): Monotonic scheduled check identity, shared by reads within a check.

    Returns:
        dict: Proposal, reason and next history; no physical action is performed.

    Raises:
        ValueError: The clock, check identity, capacity or recommendation history is invalid.
    """
    if (
        not math.isfinite(now_seconds)
        or isinstance(tick_id, bool)
        or not isinstance(tick_id, int)
        or tick_id < 1
    ):
        raise ValueError("invalid reactive clock or scheduled check identity")
    state = copy.deepcopy(history)
    state.pop("reactive_observation", None)
    if view.get("reactive_target_fraction", 0) > 0:
        return stabilized_reactive(view, state, now_seconds=now_seconds, fallback=fallback)
    demand, capacity = view["requested_cpu_demand"], view["application_slots"]
    eligible = {
        name
        for name in view["empty_workers"]
        if not view["draining_workers"]
        and len(view["active_workers"]) > view["minimum_workers"]
        and demand
        <= view["reactive_down_threshold"] * (capacity - view["nodes"][name]["application_cores"])
    }
    result = {
        "action": "unchanged",
        "selected_worker": None,
        "reason": "reactive_hold",
        "state": state,
        "fallback": fallback,
        "requested_cpu_demand": demand,
        "accepting_application_cores": capacity,
    }
    if (
        view["reserve_workers"]
        and len(view["active_workers"]) < view["maximum_workers"]
        and demand > view["reactive_up_threshold"] * capacity
    ):
        return {
            **result,
            "action": "scale-up",
            "selected_worker": view["reserve_workers"][0],
            "reason": "reactive_cpu_demand",
        }
    if eligible:
        return {
            **result,
            "action": "scale-down",
            "selected_worker": min(eligible),
            "reason": "reactive_empty_worker_with_capacity",
        }
    return result


def stabilized_reactive(view, state, *, now_seconds, fallback):
    """Apply an eager CPU target and trailing maximum before proposing removal.

    Args:
        view (dict): Validated homogeneous inventory and enabled policy settings.
        state (dict): Private copy of controller history, updated with recommendations.
        now_seconds (float): Current recommendation availability time in UTC seconds.
        fallback (bool): Whether this is the shared forecast fallback policy.

    Returns:
        dict: One-worker proposal, raw/stabilized targets and durable next history.

    Raises:
        ValueError: Capacity, settings, timestamps or recorded worker counts are invalid.
    """
    target = view["reactive_target_fraction"]
    window = view.get("reactive_downscale_stabilization_seconds", 0)
    capacities = {node["application_cores"] for node in view["nodes"].values()}
    if len(capacities) != 1 or not 0 < target <= 1 or not window > 0:
        raise ValueError("invalid homogeneous reactive capacity or stabilization settings")
    cores = next(iter(capacities))
    demand = view["requested_cpu_demand"]
    current = len(view["active_workers"])
    desired = min(
        view["maximum_workers"], max(view["minimum_workers"], math.ceil(demand / (target * cores)))
    )
    recommendations = state.get("reactive_recommendations", [])
    previous_at = float("-inf")
    # Exact integer counts reject bool; keep history validation at one boundary.
    # pylint: disable=too-many-boolean-expressions,unidiomatic-typecheck
    for row in recommendations:
        at, count = row["at_seconds"], row["desired_workers"]
        if (
            isinstance(at, bool)
            or not isinstance(at, (int, float))
            or not math.isfinite(at)
            or not previous_at <= at <= now_seconds
            or type(count) is not int
            or not view["minimum_workers"] <= count <= view["maximum_workers"]
        ):
            raise ValueError("invalid reactive recommendation history or backward clock")
        previous_at = at
    if not recommendations:
        recommendations = [{"at_seconds": now_seconds, "desired_workers": current}]
    recommendations = [row for row in recommendations if row["at_seconds"] >= now_seconds - window]
    recommendations.append({"at_seconds": now_seconds, "desired_workers": desired})
    state["reactive_recommendations"] = recommendations
    stabilized = max(row["desired_workers"] for row in recommendations)
    result = {
        "action": "unchanged",
        "selected_worker": None,
        "reason": "reactive_hold",
        "state": state,
        "fallback": fallback,
        "requested_cpu_demand": demand,
        "accepting_application_cores": view["application_slots"],
        "desired_workers": desired,
        "stabilized_desired_workers": stabilized,
    }
    if desired > current and view["reserve_workers"]:
        return {
            **result,
            "action": "scale-up",
            "selected_worker": view["reserve_workers"][0],
            "reason": "reactive_cpu_target",
        }
    eligible = [
        name
        for name in view["empty_workers"]
        if not view["draining_workers"]
        and stabilized < current
        and current > view["minimum_workers"]
        and demand
        <= target * (view["application_slots"] - view["nodes"][name]["application_cores"])
    ]
    if eligible:
        return {
            **result,
            "action": "scale-down",
            "selected_worker": min(eligible),
            "reason": "reactive_stabilized_empty_worker",
        }
    return result


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
