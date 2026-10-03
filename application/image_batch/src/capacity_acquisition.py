"""Durable acquisition clocks and pending application-capacity accounting."""

import copy
import math
import uuid

from closed_loop_guards import guard_action


def pending_activation(journal):
    """Read the sole unfinished acquisition, including its one dispatch attempt.

    Args:
        journal (Journal): Exclusively owned durable controller history.

    Returns:
        dict or None: Request and optional dispatch fields, never a new request clock.

    Raises:
        ValueError: More than one acquisition is unresolved.
    """
    terminal = {
        row["activation_id"] for row in journal.records if row["event"] == "activation.result"
    }
    requests = [
        row
        for row in journal.records
        if row["event"] == "activation.request" and row["activation_id"] not in terminal
    ]
    if len(requests) > 1:
        raise ValueError("multiple pending capacity acquisitions")
    if not requests:
        return None
    request = copy.deepcopy(requests[0])
    dispatches = [
        row
        for row in journal.records
        if row["event"] == "activation.dispatch"
        and row["activation_id"] == request["activation_id"]
    ]
    if dispatches:
        request["dispatch"] = copy.deepcopy(dispatches[-1])
    return request


def request_activation(journal, before, fresh, proposal, config, *, now_seconds, cutoff_seconds):
    """Reserve an empty Ready worker without making it schedulable.

    Args:
        journal (Journal): Durable exclusive controller history.
        before (dict): State underlying the causal proposal.
        fresh (dict): Independently validated pre-request state.
        proposal (dict): Scale-up action and explicit target.
        config (dict): Worker bounds and acquisition_seconds.
        now_seconds (float): Request time in epoch seconds.
        cutoff_seconds (float): Original proposal observation cutoff.

    Returns:
        dict: Durable request with an immutable minimum-availability clock.

    Raises:
        ValueError: Delay, clock, pending intent or physical preconditions are invalid.
    """
    delay = config.get("acquisition_seconds", 0)
    if (
        isinstance(delay, bool)
        or not isinstance(delay, (int, float))
        or not math.isfinite(delay)
        or delay < 0
        or not math.isfinite(now_seconds)
    ):
        raise ValueError("acquisition delay and request clock must be finite and nonnegative")
    if pending_activation(journal) or journal.pending_action():
        raise ValueError("pending capacity intent must be resolved before acquisition")
    if proposal["action"] != "scale-up":
        raise ValueError("capacity acquisition requires scale-up")
    guard_action(before, fresh, proposal, config, decision_age=now_seconds - cutoff_seconds)
    if not 0 <= now_seconds - fresh["collection_started_seconds"] <= 3:
        raise ValueError("pre-request acquisition observation became stale")
    worker = proposal["selected_worker"]
    return journal.append(
        "activation.request",
        activation_id=uuid.uuid4().hex,
        selected_worker=worker,
        node_uid=fresh["nodes"][worker]["uid"],
        requested_at_seconds=now_seconds,
        ready_at_seconds=now_seconds + delay,
        acquisition_seconds=delay,
        cutoff_seconds=cutoff_seconds,
        requested_application_cores=fresh["nodes"][worker]["application_cores"],
    )


def activation_view(view, journal):
    """Exclude requested reserves and charge their capacity from acquisition request.

    Args:
        view (dict): Fresh physical accepting/draining/reserve inventory.
        journal (Journal): Durable acquisition history.

    Returns:
        dict: Independent physical view with explicit pending capacity and combined cost.

    Raises:
        ValueError: The requested worker is absent or its identity changed.
    """
    result = copy.deepcopy(view)
    request = pending_activation(journal)
    result["pending_workers"] = []
    result["pending_acquisitions"] = []
    result["accepting_draining_application_cores"] = view["allocated_application_cores"]
    if request:
        name = request["selected_worker"]
        if name not in view["nodes"] or view["nodes"][name]["uid"] != request["node_uid"]:
            raise ValueError("pending acquisition worker identity changed")
        result["pending_workers"] = [name]
        result["pending_acquisitions"] = [request]
        result["reserve_workers"] = [
            worker for worker in result["reserve_workers"] if worker != name
        ]
        if name not in view["active_workers"] + view["draining_workers"]:
            result["allocated_application_cores"] += view["nodes"][name]["application_cores"]
    return result
