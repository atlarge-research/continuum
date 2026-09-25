"""Namespace FIFO admission of suspended Jobs, retaining Kubernetes placement."""

import json
import os
import time

from kubernetes import client, config
from kubernetes.utils.quantity import parse_quantity
from urllib3.exceptions import HTTPError


LABEL = "app.kubernetes.io/name=image-batch-worker"


def requests(spec):
    """Sum calibrated Pod requests while rejecting unsupported resource semantics.

    Args:
        spec (dict): Pod specification with regular containers only.

    Returns:
        tuple[float, float]: Requested CPU cores and memory bytes.

    Raises:
        ValueError: Requests are absent/nonpositive or init/overhead semantics are present.
    """
    if spec.get("initContainers") or spec.get("overhead") or not spec.get("containers"):
        raise ValueError("unsupported admission resource specification")
    cpu, memory = 0.0, 0.0
    for container in spec["containers"]:
        value = container.get("resources", {}).get("requests", {})
        cores = float(parse_quantity(value.get("cpu", "0")))
        size = float(parse_quantity(value.get("memory", "0")))
        if cores <= 0 or size <= 0:
            raise ValueError("explicit positive CPU and memory requests required")
        cpu += cores
        memory += size
    return cpu, memory


def choose(jobs, pods, nodes, workers):
    """Choose the oldest suspended Job only after all previous admissions bind.

    Original Job timestamps and UIDs define FIFO. Pod requests remain occupied
    until terminal phase, including after classifier exit. C−1 is applied once
    to configured VM cores; the Kubernetes scheduler still performs final fit.

    Args:
        jobs (list[dict]): Application Jobs in the isolated namespace.
        pods (list[dict]): Application Pods in that namespace, read after Jobs.
        nodes (list[dict]): Fresh cluster Node objects.
        workers (dict[str, int]): Allowed worker names mapped to configured VM cores.

    Returns:
        dict: Explicit no-op reason or the oldest Job identity and fitting workers.

    Raises:
        ValueError: Topology, resource specification or outstanding reservations conflict.
    """
    observed = {node["metadata"]["name"]: node for node in nodes}
    if not set(workers) <= set(observed):
        raise ValueError("configured admission worker is missing")
    free = {}
    for name, cores in workers.items():
        node = observed[name]
        if type(cores) is not int or cores < 2:  # pylint: disable=unidiomatic-typecheck
            raise ValueError("configured VM cores must be an integer above one")
        if node["spec"].get("unschedulable") or not any(
            item["type"] == "Ready" and item["status"] == "True"
            for item in node["status"].get("conditions", [])
        ):
            continue
        if any(
            taint.get("effect") in ("NoSchedule", "NoExecute")
            for taint in node["spec"].get("taints", [])
        ):
            continue
        allocatable = node["status"]["allocatable"]
        free[name] = [
            min(cores - 1, float(parse_quantity(allocatable["cpu"]))),
            float(parse_quantity(allocatable["memory"])),
        ]
    bound, seen = set(), set()
    job_ids = {job["metadata"]["uid"] for job in jobs}
    for pod in pods:
        owners = [
            owner["uid"]
            for owner in pod["metadata"].get("ownerReferences", [])
            if owner["kind"] == "Job"
        ]
        if len(owners) != 1 or owners[0] not in job_ids:
            raise ValueError("Pod/Job membership changed during admission collection")
        if owners[0] in seen:
            raise ValueError("multiple Pods for one finite Job are unsupported")
        seen.add(owners[0])
        node = pod["spec"].get("nodeName")
        if node:
            if node not in workers:
                raise ValueError("application Pod placed outside the worker pool")
            bound.add(owners[0])
            if pod["status"]["phase"] not in ("Succeeded", "Failed") and node in free:
                cpu, memory = requests(pod["spec"])
                free[node][0] -= cpu
                free[node][1] -= memory
    live = [
        job
        for job in jobs
        if not job.get("status", {}).get("succeeded") and not job.get("status", {}).get("failed")
    ]
    outstanding = [
        job
        for job in live
        if not job["spec"].get("suspend", False) and job["metadata"]["uid"] not in bound
    ]
    if len(outstanding) > 1:
        raise ValueError("more than one outstanding unbound admission")
    if outstanding:
        return dict(reason="awaiting_binding", outstanding_uid=outstanding[0]["metadata"]["uid"])
    suspended = sorted(
        [job for job in live if job["spec"].get("suspend")],
        key=lambda job: (job["metadata"]["creationTimestamp"], job["metadata"]["uid"]),
    )
    if not suspended:
        return dict(reason="empty_queue")
    head = suspended[0]
    cpu, memory = requests(head["spec"]["template"]["spec"])
    fitting = sorted(
        name for name, (cores, size) in free.items() if cores >= cpu and size >= memory
    )
    if not fitting:
        return dict(reason="no_fit", head_uid=head["metadata"]["uid"])
    return dict(
        reason="admit",
        job_uid=head["metadata"]["uid"],
        job_name=head["metadata"]["name"],
        resource_version=head["metadata"]["resourceVersion"],
        fitting_workers=fitting,
    )


def release(api, namespace, decision):
    """Unsuspend one identified Job while distinguishing rejection from uncertainty.

    Args:
        api (BatchV1Api): Namespace-scoped Kubernetes mutation client.
        namespace (str): Isolated experiment namespace.
        decision (dict): Current FIFO head identity and observed resource version.

    Returns:
        dict: Released, definitely rejected/retry observation, or uncertain/stop outcome.
    """
    patch = [
        dict(op="test", path="/metadata/uid", value=decision["job_uid"]),
        dict(op="test", path="/metadata/resourceVersion", value=decision["resource_version"]),
        dict(op="test", path="/spec/suspend", value=True),
        dict(op="replace", path="/spec/suspend", value=False),
    ]
    try:
        api.patch_namespaced_job(decision["job_name"], namespace, patch, _request_timeout=5)
    except client.exceptions.ApiException as exc:
        rejected = exc.status in (404, 409, 422)
        return dict(status="retry_snapshot" if rejected else "uncertain_stop", error=str(exc))
    except (HTTPError, OSError) as exc:
        return dict(status="uncertain_stop", error=str(exc))
    return dict(status="released")


def halt(reason, **details):
    """Record failed admission and remain stopped without restarting or releasing work.

    Args:
        reason (str): Explicit uncertainty, binding timeout or repeated-rejection reason.
        details (dict): JSON-compatible failure evidence for the capture monitor.
    """
    print(
        json.dumps(
            dict(timestamp_ns=time.time_ns(), event="admission.stopped", reason=reason, **details)
        ),
        flush=True,
    )
    while True:
        time.sleep(60)


def main():
    """Release one oldest Job, await binding, and fail closed on prolonged uncertainty."""
    config.load_incluster_config()
    api_client = client.ApiClient()
    batch, core = client.BatchV1Api(api_client), client.CoreV1Api(api_client)
    namespace = os.environ["JOB_NAMESPACE"]
    workers = json.loads(os.environ["ADMISSION_WORKERS"])
    outstanding_uid, outstanding_since = None, None
    previous = None
    rejections = 0
    while True:
        jobs = api_client.sanitize_for_serialization(
            batch.list_namespaced_job(namespace, label_selector=LABEL, _request_timeout=5)
        )["items"]
        pods = api_client.sanitize_for_serialization(
            core.list_namespaced_pod(namespace, label_selector=LABEL, _request_timeout=5)
        )["items"]
        nodes = api_client.sanitize_for_serialization(core.list_node(_request_timeout=5))["items"]
        try:
            result = choose(jobs, pods, nodes, workers)
        except ValueError as exc:
            # A concurrent creation can temporarily produce a Pod absent from the older Job list.
            result = dict(reason="invalid_snapshot", error=str(exc))
        uid = result.get("outstanding_uid")
        if uid != outstanding_uid:
            outstanding_uid, outstanding_since = uid, time.monotonic()
        if uid and time.monotonic() - outstanding_since > 30:
            halt("binding_timeout", job_uid=uid)
        if result != previous:
            print(
                json.dumps(dict(timestamp_ns=time.time_ns(), event="admission.decision", **result)),
                flush=True,
            )
            previous = result
        if result["reason"] == "admit":
            outcome = release(batch, namespace, result)
            print(
                json.dumps(
                    dict(
                        timestamp_ns=time.time_ns(),
                        event="admission.release",
                        job_uid=result["job_uid"],
                        **outcome
                    )
                ),
                flush=True,
            )
            if outcome["status"] == "uncertain_stop":
                halt("uncertain_patch_outcome", job_uid=result["job_uid"], error=outcome["error"])
            rejections = rejections + 1 if outcome["status"] == "retry_snapshot" else 0
            if rejections >= 10:
                halt("repeated_patch_rejection", job_uid=result["job_uid"], error=outcome["error"])
        time.sleep(0.2)


if __name__ == "__main__":
    main()
