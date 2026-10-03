"""Journal-derived activation attribution and physical pending-capacity costs."""

import copy
import math


def acquisition_history(records):
    """Join acquisition requests, dispatch attempts, API intent and observed results.

    Args:
        records (list[dict]): Complete durable controller journal in file order.

    Returns:
        list[dict]: Normalized acquisition records retaining original clocks and source ticks.

    Raises:
        ValueError: Requests duplicate identities or results lack their original request.
    """
    requests, current_tick, dispatching = {}, None, None
    for record in records:
        event = record["event"]
        if event == "cycle.begin":
            current_tick = record["tick"]
        elif event == "activation.request":
            identity = record["activation_id"]
            if identity in requests:
                raise ValueError("duplicate acquisition request identity")
            requests[identity] = {
                **copy.deepcopy(record),
                "tick": current_tick,
                "dispatches": [],
                "status": "unresolved",
                "terminal_seconds": None,
                "request_to_observed_seconds": None,
            }
        elif event == "activation.dispatch":
            identity = record["activation_id"]
            if identity not in requests:
                raise ValueError("acquisition dispatch has no original request")
            requests[identity]["dispatches"].append(copy.deepcopy(record))
            dispatching = identity
        elif event == "action.request" and dispatching is not None:
            requests[dispatching]["api_action_id"] = record["action_id"]
            dispatching = None
        elif event == "activation.result":
            identity = record["activation_id"]
            if identity not in requests:
                raise ValueError("acquisition result has no original request")
            request = requests[identity]
            terminal = (
                record["observed_at_seconds"]
                if record["status"] == "observed"
                else record["recorded_at_ns"] / 1e9
            )
            if not math.isfinite(terminal) or terminal < request["requested_at_seconds"]:
                raise ValueError("acquisition terminal clock precedes its request")
            request.update(
                status=record["status"], terminal_seconds=terminal, result=copy.deepcopy(record)
            )
            if record["status"] == "observed":
                request["observed_at_seconds"] = terminal
                request["request_to_observed_seconds"] = terminal - request["requested_at_seconds"]
    return list(requests.values())


def acquisition_audit(records):
    """Audit immutable acquisition clocks and exactly-once dispatch attempts.

    Args:
        records (list[dict]): Complete durable controller history.

    Returns:
        dict: Observed minimum-delay violations, unresolved requests and normalized history.
    """
    rows = acquisition_history(records)
    early = [
        row["activation_id"]
        for row in rows
        if any(d["dispatched_at_seconds"] < row["ready_at_seconds"] for d in row["dispatches"])
    ]
    duplicate = [row["activation_id"] for row in rows if len(row["dispatches"]) > 1]
    early_observed = [
        row["activation_id"]
        for row in rows
        if row["status"] == "observed" and row["observed_at_seconds"] < row["ready_at_seconds"]
    ]
    return dict(
        requests=len(rows),
        observed=sum(row["status"] == "observed" for row in rows),
        cancelled=sum(row["status"] == "cancelled" for row in rows),
        unresolved_activation_ids=[
            row["activation_id"] for row in rows if row["status"] == "unresolved"
        ],
        early_dispatch_activation_ids=early,
        duplicate_dispatch_activation_ids=duplicate,
        early_observed_activation_ids=early_observed,
        violations=bool(early or duplicate or early_observed),
        history=rows,
    )


def _pending_at(rows, at, allocated, end):
    """Read pending workers that are not already physically allocated at one instant.

    Args:
        rows (list[dict]): Normalized journal acquisition history.
        at (float): Instant in epoch seconds.
        allocated (list[str]): Workers already accepting or draining in the physical state.
        end (float): Bound for acquisitions without a terminal result.

    Returns:
        tuple[float, list[str]]: Additional charged cores and pending worker identities.

    Raises:
        ValueError: Overlapping requests charge the same worker twice.
    """
    active = [
        row
        for row in rows
        if row["requested_at_seconds"]
        <= at
        < (row["terminal_seconds"] if row["terminal_seconds"] is not None else end)
        and row["selected_worker"] not in allocated
    ]
    names = [row["selected_worker"] for row in active]
    if len(names) != len(set(names)):
        raise ValueError("overlapping acquisitions charge the same worker twice")
    return sum(row["requested_application_cores"] for row in active), names


def charge_acquisitions(base, records, maximum):
    """Add pending costs at exact journal boundaries without duplicating accepting capacity.

    Unknown physical intervals retain the original full-pool upper bound. Pending
    increments are integrated only across the same valid observation brackets as
    the base allocation. Journal boundaries split those brackets exactly.

    Args:
        base (dict): Accepting/draining allocation result with worker identities in its series.
        records (list[dict]): Durable acquisition journal events.
        maximum (float): Full powered pool's application-core capacity.

    Returns:
        dict: Combined charged allocation, physical component and pending-cost bounds.
    """
    rows = acquisition_history(records)
    if not rows:
        return base
    result = copy.deepcopy(base)
    start, end = base["start_seconds"], base["end_seconds"]
    boundaries = sorted(
        {
            at
            for row in rows
            for at in (row["requested_at_seconds"], row["terminal_seconds"])
            if at is not None
        }
    )
    pending_lower, combined_upper_increment = 0.0, 0.0
    for left, right in zip(base["series"], base["series"][1:]):
        lower, upper = max(start, left["time"]), min(end, right["time"])
        if (
            upper <= lower
            or right["time"] - left["time"] > 3
            or not left["valid"]
            or not right["valid"]
        ):
            continue
        cuts = [lower] + [at for at in boundaries if lower < at < upper] + [upper]
        for before, after in zip(cuts, cuts[1:]):
            cores, _ = _pending_at(rows, before, left.get("allocated_workers", []), end)
            pending_lower += (after - before) * cores
            combined_upper_increment += (after - before) * min(cores, maximum - left["upper"])
    total_requested = sum(
        max(
            0,
            min(end, row["terminal_seconds"] if row["terminal_seconds"] is not None else end)
            - max(start, row["requested_at_seconds"]),
        )
        * row["requested_application_cores"]
        for row in rows
    )
    raw_lower, raw_upper = base["allocated_core_seconds_bounds"]
    bounds = [raw_lower + pending_lower, raw_upper + combined_upper_increment]
    result["accepting_draining_core_seconds_bounds"] = list(base["allocated_core_seconds_bounds"])
    result["pending_acquisition_core_seconds_bounds"] = [
        pending_lower,
        total_requested if base["gaps"] else pending_lower,
    ]
    result["allocated_core_seconds_bounds"] = bounds
    result["known_allocated_core_seconds_lower_bound"] = bounds[0]
    result["allocated_application_core_seconds"] = bounds[0] if not base["gaps"] else None
    for point in result["series"]:
        if not point["valid"]:
            continue
        cores, names = _pending_at(rows, point["time"], point.get("allocated_workers", []), end)
        component_known = point["lower"] == point["upper"] and point.get(
            "membership_complete", True
        )
        point["accepting_draining_cores"] = point["lower"] if component_known else None
        point["pending"] = len(names)
        point["pending_application_cores"] = cores if component_known or not cores else None
        point["lower"] += cores
        point["upper"] = min(maximum, point["upper"] + cores)
        point["allocated"] = point["lower"] if point["lower"] == point["upper"] else None
    result["acquisitions"] = rows
    result["interpretation"] = (
        "Accepting + draining + requested pending application capacity; activation cost "
        "starts at request and never duplicates observed accepting/draining capacity. "
        "Reserves remain powered; no physical-energy estimate."
    )
    return result
