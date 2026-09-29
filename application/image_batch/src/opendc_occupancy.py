"""Frozen causal lifecycle estimates layered around unchanged classifier profiles."""

import copy
import math
from statistics import median

from forecast_trace import milliseconds


def calibrate_occupancy(trace, template):
    """Freeze startup, release and residual samples at profile selection time.

    Startup uses first observed node assignment to classifier start, excluding
    left-censored assignment observations. Release uses successful Job completion
    minus classifier finish as a practical resource-release proxy. Neither is an
    exact scheduler binding or slot-release timestamp.

    Args:
        trace (Trace): Availability-bounded evidence at the template selection cutoff.
        template (dict): Frozen eligible classifier profile and selection timestamp.

    Returns:
        dict: Frozen estimates, sample identities, durations and interpretation limits.

    Raises:
        ValueError: Evidence is not bounded at selection or no eligible samples exist.
    """
    if trace.cutoff != milliseconds(template["selection_cutoff"]):
        raise ValueError("occupancy calibration requires the template selection cutoff")
    reference = template["record"]["source"]
    eligible = [
        record
        for record in trace.completed
        if all(
            record["source"].get(key) == reference.get(key)
            for key in ("image_count", "inference_repetitions")
        )
        and record["source"].get("sampling_quality") == "sampled"
        and record["source"].get("resource_sample_count", 0) >= 3
        and record["task"]["duration"] > 0
    ]
    if not eligible:
        raise ValueError("occupancy calibration has no eligible completed profiles")
    startup, release, evidence = [], [], []
    for record in eligible:
        source = record["source"]
        uid = source["kubernetes_job_uid"]
        observations = [
            (at, job.get("node_name"))
            for at, state in trace.states
            for group in ("queued", "active")
            for job in state["jobs"][group]
            if job.get("kubernetes_job_uid") == uid
        ]
        first = min((at for at, node in observations if node), default=None)
        uncensored = first is not None and any(at < first and not node for at, node in observations)
        start = source.get("execution_start_time")
        finish = source.get("execution_completion_time")
        completed = source.get("completion_time")
        start_delay = max(0, milliseconds(start) - first) if start and uncensored else None
        release_delay = (
            max(0, milliseconds(completed) - milliseconds(finish)) if completed and finish else None
        )
        if start_delay is not None:
            startup.append(start_delay)
        if release_delay is not None:
            release.append(release_delay)
        evidence.append(
            {
                "job_uid": uid,
                "startup_ms": start_delay,
                "release_ms": release_delay,
                "assignment_left_censored": not uncensored,
            }
        )
    task = template["record"]["task"]
    return {
        "contract": "causal-occupancy-v1",
        "cutoff_ms": trace.cutoff,
        "startup_ms": math.ceil(median(startup)) if startup else 0,
        "release_ms": math.ceil(median(release)) if release else 0,
        "source_job_uids": sorted(record["source"]["kubernetes_job_uid"] for record in eligible),
        "duration_samples_ms": sorted(record["task"]["duration"] for record in eligible),
        "residual_resources": {
            **{key: task[key] for key in ("cpu_count", "cpu_capacity", "mem_capacity")},
            "cpu_usage": task["fragments"][-1]["cpu_usage"],
        },
        "lifecycle_samples": evidence,
        "interpretation": (
            "first-observed assignment startup lower bound; Job-completion release proxy; "
            "zero when no eligible timing sample; warm-up-frozen classifier durations "
            "for conditional residuals"
        ),
    }


def _occupancy_fragments(task, startup, release):
    """Add zero-CPU lifecycle intervals while retaining the requested CPU slot.

    Args:
        task (dict): Copied classifier profile to extend in place.
        startup (int): Estimated milliseconds before classifier execution.
        release (int): Estimated milliseconds before resource release after execution.
    """
    idle = {"id": task["id"], "cpu_count": task["cpu_count"], "cpu_usage": 0.0}
    if startup:
        task["fragments"].insert(0, {**idle, "duration": startup})
    if release:
        task["fragments"].append({**idle, "duration": release})
    task["duration"] += startup + release


def apply_occupancy(case, calibration):
    """Represent startup/release and exhausted residuals without changing observations.

    Raw exhausted diagnostics remain present. Each estimated Task carries an
    explicit occupancy annotation; its completion is a prediction, never new
    evidence of observed success. Down candidates are excluded by the producer
    whenever any exhausted or unresolved work exists.

    Args:
        case (dict): Prepared classifier-only Tasks and original exhausted diagnostics.
        calibration (dict): Frozen causal lifecycle and conditional-duration estimates.

    Returns:
        dict: Independent modeled case with original evidence and additional occupancy.

    Raises:
        ValueError: Calibration is malformed or newer than the simulation cutoff.
    """
    if (
        calibration.get("contract") != "causal-occupancy-v1"
        or calibration["cutoff_ms"] > case["cutoff_ms"]
        or any(
            type(calibration.get(key)) is not int or calibration[key] < 0
            for key in ("startup_ms", "release_ms")
        )
        or not calibration.get("duration_samples_ms")
        or any(
            not math.isfinite(value) or value <= 0 for value in calibration["duration_samples_ms"]
        )
    ):
        raise ValueError("invalid occupancy calibration or future selection cutoff")
    modeled = copy.deepcopy(case)
    modeled["occupancy_model"] = copy.deepcopy(calibration)
    for item in modeled["model_exhausted_jobs"]:
        metadata = copy.deepcopy(item["metadata"])
        elapsed = metadata["elapsed_ms"]
        longer = [
            duration - elapsed
            for duration in calibration["duration_samples_ms"]
            if duration > elapsed
        ]
        residual = math.ceil(median(longer)) if longer else 5000
        resources = calibration["residual_resources"]
        task = {key: resources[key] for key in ("cpu_count", "cpu_capacity", "mem_capacity")}
        task.update(
            id=item["task_id"],
            submission_time=0,
            duration=residual,
            fragments=[
                {
                    "id": item["task_id"],
                    "duration": residual,
                    "cpu_count": resources["cpu_count"],
                    "cpu_usage": resources["cpu_usage"],
                }
            ],
        )
        metadata["occupancy"] = {
            "profile_exhausted": True,
            "residual_basis": "conditional_completed_durations"
            if longer
            else "five_second_fallback",
        }
        modeled["tasks"].append({"task": task, "metadata": metadata})
    for item in modeled["tasks"]:
        task, metadata = item["task"], item["metadata"]
        phase = metadata["phase"]
        if phase == "release":
            continue
        startup = calibration["startup_ms"] if phase in ("queued", "future", "startup") else 0
        if phase == "startup" and not metadata.get("assignment_left_censored", True):
            startup = max(
                0, startup - (case["cutoff_ms"] - metadata["first_assignment_observed_ms"])
            )
        metadata.setdefault("occupancy", {"profile_exhausted": False})
        metadata["occupancy"].update(
            startup_ms=startup,
            release_ms=calibration["release_ms"],
            classifier_profile_ms=task["duration"],
        )
        _occupancy_fragments(task, startup, calibration["release_ms"])
    return modeled


def estimated_exhausted_ids(case):
    """Verify the explicit overlap between raw exhausted evidence and estimated Tasks.

    Args:
        case (dict): Case containing original diagnostics and optional occupancy estimates.

    Returns:
        set[int]: Task IDs whose raw exhausted evidence is preserved alongside an estimate.

    Raises:
        ValueError: Estimated and observed identities or metadata disagree.
    """
    estimated = {
        item["task"]["id"]: item
        for item in case["tasks"]
        if item["metadata"].get("occupancy", {}).get("profile_exhausted") is True
    }
    original = {item["task_id"]: item for item in case.get("model_exhausted_jobs", [])}
    if not case.get("occupancy_model"):
        if estimated:
            raise ValueError("exhausted estimates require explicit occupancy calibration")
        return set()
    if set(estimated) != set(original):
        raise ValueError("exhausted estimates must retain every original exhausted identity")
    for task_id, record in estimated.items():
        metadata = {key: value for key, value in record["metadata"].items() if key != "occupancy"}
        if metadata != original[task_id]["metadata"]:
            raise ValueError("exhausted estimate changed original observation metadata")
    return set(estimated)
