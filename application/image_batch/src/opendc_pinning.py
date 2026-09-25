"""Admission and ordering preconditions for the pinned FNS-demo engine."""

PINNED_MODE = "pinned-trace"
FNS_CONTRACT = "opendc-fns-v1"


def cordoned_worker(case):
    """Resolve the one existing or proposed cordon without forgetting draining work.

    Args:
        case (dict): Case with an optional previous cordon and candidate action.

    Returns:
        str or None: Worker closed to new admission throughout this simulation.

    Raises:
        ValueError: The case requests two simultaneous draining workers.
    """
    existing = case.get("initial_cordoned_worker")
    proposed = case.get("selected_worker") if case["candidate"] == "scale-down" else None
    if existing and proposed:
        raise ValueError("a second worker cannot drain while another cordon persists")
    return existing or proposed


def initial_assignments(case):
    """Validate simultaneous initial placement and return executable task assignments.

    The upstream scheduler can override its fitting-host choice when a task
    names a host. Check aggregate CPU and memory on that exact host first.
    Exhausted profiles remain observations; they create no synthetic allocation
    or completion and cannot define when a selected worker finishes draining.

    Args:
        case (dict): Prepared case containing worker capacities and task lineage.

    Returns:
        dict[int, str]: Executable initially assigned task IDs mapped to workers.

    Raises:
        ValueError: Placement is inconsistent, exceeds initial capacity, or a
            cordoned worker has observed work with no modeled drain duration.
    """
    workers = {worker["node_name"]: worker for worker in case["workers"]}
    used = {name: [0, 0] for name in workers}
    assigned = {}
    for record in case["tasks"]:
        task, metadata = record["task"], record["metadata"]
        host = metadata.get("preserved_assignment")
        if host is None:
            continue
        if (
            host not in workers
            or metadata.get("cohort") != "backlog"
            or metadata.get("phase") not in ("running", "startup")
            or task["submission_time"] != 0
        ):
            raise ValueError("invalid initial pinned assignment")
        assigned[task["id"]] = host
        used[host][0] += task["cpu_count"]
        used[host][1] += task["mem_capacity"]
        if (
            used[host][0] > workers[host]["modeled_cores"]
            or used[host][1] > workers[host]["memory_mib"]
        ):
            raise ValueError(f"initial pinned capacity exceeded on {host}")
    selected = cordoned_worker(case)
    if selected is not None:
        if selected not in workers or case["omitted_tasks"]:
            raise ValueError("native cordon must retain its worker and all executable work")
        remaining = [worker for name, worker in workers.items() if name != selected]
        for record in case["tasks"]:
            task = record["task"]
            if task["id"] not in assigned and not any(
                task["cpu_count"] <= worker["modeled_cores"]
                and task["mem_capacity"] <= worker["memory_mib"]
                for worker in remaining
            ):
                raise ValueError("unassigned task exceeds remaining worker capacity after cordon")
        if any(
            item["metadata"].get("preserved_assignment") == selected
            for item in case["model_exhausted_jobs"]
        ):
            raise ValueError("selected worker has exhausted work with unknown drain duration")
    return assigned


def native_order(task_ids, assignments):
    """Return a stable pinned-first permutation required by the upstream replayer.

    Args:
        task_ids (list[int]): Source row identities in their original order.
        assignments (dict[int, str]): Tasks assigned at time zero.

    Returns:
        list[int]: Row indices, with pinned tasks preceding ordinary queue/future work.

    Raises:
        ValueError: Source identities are duplicated or an assignment is absent.
    """
    if len(set(task_ids)) != len(task_ids) or not set(assignments) <= set(task_ids):
        raise ValueError("pinning identities differ from source tasks")
    return sorted(range(len(task_ids)), key=lambda index: task_ids[index] not in assignments)


def initialization_metadata(assignments):
    """Describe requested placement and the remaining startup/exhaustion approximations.

    Args:
        assignments (dict[int, str]): Validated initial task-to-host assignments.

    Returns:
        dict: Input intent and explicit limitations, not an execution success verdict.
    """
    return {
        "pinned_task_ids": sorted(assignments),
        "trace_order": "assigned tasks first, then original unassigned order",
        "startup_delay_restored": False,
        "exhausted_occupancy_restored": False,
        "interpretation": (
            "running remainders and starting profiles request their observed hosts at zero; "
            "startup resources are requested immediately but classifier startup delay is omitted; "
            "exhausted profiles have no invented allocation or completion"
        ),
    }
