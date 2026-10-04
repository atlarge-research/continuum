"""Explicit synthetic slot reservations for controlled capacity acquisition."""

import copy
import math


CONTRACT = "capacity-acquisition-v1"


def application_tasks(case):
    """Read the real backlog/future cohort, excluding infrastructure reservations.

    Args:
        case (dict): Prepared native case.

    Returns:
        list[dict]: Real sampled Job records in original order.
    """
    return [row for row in case["tasks"] if row["metadata"].get("cohort") != "infrastructure"]


def native_cordons(case):
    """Resolve all hosts closed to new work while retaining their pinned reservations.

    Args:
        case (dict): Native case with optional delayed-acquisition admission metadata.

    Returns:
        list[str]: Sorted hosts that never admit new unassigned tasks in this case.

    Raises:
        ValueError: Native cordons refer to an absent modeled host.
    """
    acquisition = case.get("acquisition")
    if acquisition:
        names = {worker["node_name"] for worker in case["workers"]}
        allowed = set(acquisition["accepting_workers"]) | set(acquisition["pending_workers"])
        if not allowed <= names:
            raise ValueError("acquisition admission refers to an unknown host")
        return sorted(names - allowed)
    existing = case.get("initial_cordoned_worker")
    selected = case.get("selected_worker") if case["candidate"] == "scale-down" else None
    return sorted({name for name in (existing, selected) if name})


def apply_acquisition(case, settings):
    """Retain full topology and pin common zero-CPU reservations on empty reserves.

    One one-CPU Task per application slot retains requested capacity for its
    literal trace duration without adding classifier CPU work. Unrequested
    reserves remain natively cordoned after reservation release. All alternatives
    receive identical synthetic Tasks; only native admission and charged capacity
    differ. Synthetic identities never impersonate Kubernetes Jobs.

    Args:
        case (dict): Complete pinned case after causal lifecycle occupancy adaptation.
        settings (dict): Full worker records, active workers, delay, pending request clocks
            and first_synthetic_task_id shared by all candidates and futures. Optional modeled
            request delay precedes new requests; admission margin follows new or pending due
            time. Pending absolute clocks are retained without adding another request delay.

    Returns:
        dict: Independent acquisition-aware case, or unchanged zero-delay contract.

    Raises:
        ValueError: Delay, synthetic identities, worker roles or pending clocks are invalid.
    """
    delay = settings.get("acquisition_seconds", 0)
    request_delay = settings.get("modeled_request_delay_seconds", 0)
    admission_margin = settings.get("modeled_admission_margin_seconds", 0)
    pending = settings.get("pending_acquisitions", [])
    if (
        isinstance(delay, bool)
        or not isinstance(delay, (int, float))
        or not math.isfinite(delay)
        or delay < 0
    ):
        raise ValueError("acquisition delay must be finite and nonnegative")
    for value in (request_delay, admission_margin):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("modeled timing offsets must be finite and nonnegative")
    if delay == 0 and not pending and request_delay == 0 and admission_margin == 0:
        return copy.deepcopy(case)
    modeled = copy.deepcopy(case)
    workers = copy.deepcopy(settings["workers"])
    names = {worker["node_name"] for worker in workers}
    active = set(settings["active_workers"])
    draining = {case["initial_cordoned_worker"]} if case.get("initial_cordoned_worker") else set()
    pending_names = [request["selected_worker"] for request in pending]
    if len(names) != len(workers) or not active <= names or not draining <= names:
        raise ValueError("inconsistent acquisition worker roles")
    if (
        not set(pending_names) <= names
        or len(set(pending_names)) != len(pending_names)
        or active & (draining | set(pending_names))
    ):
        raise ValueError("inconsistent pending acquisition worker roles")
    accepting = set(active)
    selected = case.get("selected_worker")
    if case["candidate"] == "scale-up":
        if selected not in names - active - draining - set(pending_names):
            raise ValueError("acquisition target is not an empty reserve")
        accepting.add(selected)
    elif case["candidate"] == "scale-down":
        if selected not in active:
            raise ValueError("drain target is not an accepting worker")
        accepting.remove(selected)
    first = settings["first_synthetic_task_id"]
    real_ids = {record["task"]["id"] for record in case["tasks"]}
    if isinstance(first, bool) or not isinstance(first, int) or first <= max(real_ids, default=-1):
        raise ValueError("synthetic identities overlap application Tasks")
    availability = {}
    for name in sorted(names - active - draining):
        request = next((row for row in pending if row["selected_worker"] == name), None)
        seconds = (
            max(0, request["ready_at_seconds"] - case["cutoff_ms"] / 1000) + admission_margin
            if request
            else delay + request_delay + admission_margin
        )
        if not math.isfinite(seconds):
            raise ValueError("nonfinite pending acquisition clock")
        availability[name] = math.ceil(seconds * 1000)
    modeled["workers"] = workers
    modeled["acquisition"] = {
        "contract": CONTRACT,
        "delay_seconds": delay,
        "modeled_request_delay_seconds": request_delay,
        "modeled_admission_margin_seconds": admission_margin,
        "request_after_seconds": {selected: request_delay}
        if case["candidate"] == "scale-up"
        else {},
        "accepting_workers": sorted(accepting),
        "pending_workers": sorted(pending_names),
        "allocated_workers": sorted(
            active
            | draining
            | set(pending_names)
            | ({selected} if case["candidate"] == "scale-up" else set())
        ),
        "available_after_ms": availability,
        "synthetic_task_ids": [],
        "interpretation": (
            "controlled physical acquisition plus model-only request/admission offsets; "
            "pending due clocks remain original; scale-down still uses cutoff-time cordon; "
            "synthetic reservations are not Jobs"
        ),
    }
    next_id = first
    for name, duration in sorted(availability.items()):
        if duration == 0:
            continue
        worker = next(row for row in workers if row["node_name"] == name)
        for _ in range(worker["modeled_cores"]):
            task = {
                "id": next_id,
                "submission_time": 0,
                "duration": duration,
                "cpu_count": 1,
                "cpu_capacity": float(worker["frequency_mhz"]),
                "mem_capacity": 1,
                "fragments": [
                    {"id": next_id, "duration": duration, "cpu_count": 1, "cpu_usage": 0.0}
                ],
            }
            modeled["tasks"].append(
                {
                    "task": task,
                    "metadata": {
                        "cohort": "infrastructure",
                        "phase": "acquisition",
                        "synthetic": True,
                        "infrastructure_contract": CONTRACT,
                        "node_name": name,
                        "preserved_assignment": name,
                        "original_creation_ms": case["cutoff_ms"],
                        "identity": {"task_id": next_id, "synthetic_worker": name},
                    },
                }
            )
            modeled["acquisition"]["synthetic_task_ids"].append(next_id)
            next_id += 1
    return modeled


def validate_acquisition_results(case, completed, assignments):
    """Reject native application admission on closed or not-yet-available workers.

    Args:
        case (dict): Prepared acquisition-aware native case.
        completed (list[dict]): Validated native placements and lifecycle clocks.
        assignments (dict[int, str]): Initial pinned assignments, including reservations.

    Raises:
        ValueError: An unassigned task starts on a cordoned or unavailable worker.
    """
    acquisition = case.get("acquisition")
    if not acquisition:
        return
    closed = set(native_cordons(case))
    real_ids = {record["task"]["id"] for record in application_tasks(case)}
    for row in completed:
        if row["task_id"] not in real_ids or row["task_id"] in assignments:
            continue
        if row["host_name"] in closed:
            raise ValueError("cordoned acquisition reserve admitted application work")
        if row["schedule_time"] < acquisition["available_after_ms"].get(row["host_name"], 0):
            raise ValueError("application admission preceded capacity acquisition availability")
