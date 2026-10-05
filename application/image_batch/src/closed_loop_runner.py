"""Control-plane native batches and complete-cohort policy measurements."""

import io
import json
import math
import time

from opendc_batch import _preflight, _stage_image, _stage_inputs, remote_input
from opendc_evaluate import load_batch
from opendc_inputs import write_json
from opendc_kubernetes import extract_artifacts, job_manifest, ssh, verify_collection_source
from opendc_native_batch import plan_suite
from opendc_acquisition import RESPONSE_TIME_CONTRACT, application_tasks
from opendc_pinning import cordoned_worker
from opendc_occupancy import estimated_exhausted_ids


def score_cases(rows, *, scenarios=3, allocation_seconds=120):
    """Adapt fully validated paired native cases into the approved policy contract.

    Responses end at modeled resource release, used explicitly as the practical
    Job-completion proxy. Classifier-only response remains separate in reporting.
    Accepting workers cost the full allocation window; a cordoned worker costs
    only its modeled drain interval, with no claim of physical power-off. New acquisitions
    start charging at the declared modeled request offset; existing pending capacity remains
    charged throughout. Scale-down retains the cutoff-time cordon approximation.

    Args:
        rows (list[dict]): Case metadata and successful native/analytical validation.
        scenarios (int): Exact number of shared future identities required per action.
        allocation_seconds (float): Common allocation window, initially120 seconds.

    Returns:
        list[dict]: Complete per-scenario responses and allocated application core-time.

    Raises:
        ValueError: Cohorts, identities, membership, completion or resource data disagree.
    """
    # Exact integer types intentionally reject bool and fractional scenario identities.
    # pylint: disable=unidiomatic-typecheck
    if (
        type(scenarios) is not int
        or scenarios < 1
        or not math.isfinite(allocation_seconds)
        or allocation_seconds <= 0
    ):
        raise ValueError("invalid scenario count or allocation window")
    grouped, cohorts, boundaries, timing_contracts = {}, {}, set(), set()
    for row in rows:
        case, validation = row["case"], row["validation"]
        action, scenario = case["candidate"], case["scenario"]
        contract = case.get("response_time_contract")
        allowance = case.get("acquisition", {}).get("modeled_request_delay_seconds", 0)
        # Keep the timing provenance validation as one fail-closed boundary.
        # pylint: disable=too-many-boolean-expressions
        if contract is not None and (
            contract != RESPONSE_TIME_CONTRACT
            or isinstance(allowance, bool)
            or not isinstance(allowance, (int, float))
            or not math.isfinite(allowance)
            or allowance <= 0
        ):
            raise ValueError("invalid response timing contract")
        timing_contracts.add((contract, allowance if contract is not None else 0))
        if (
            action not in ("unchanged", "scale-up", "scale-down")
            or type(scenario) is not int
            or not 0 <= scenario < scenarios
        ):
            raise ValueError("unknown action or scenario identity")
        boundaries.add((case["cutoff_ms"], case["horizon_ms"]))
        membership = case.get("initial_membership") or {}
        if (
            case.get("scope") != "complete"
            or case.get("omitted_tasks")
            or membership.get("complete") is not True
            or validation.get("status") != "passed"
        ):
            raise ValueError("policy requires complete scope, membership and successful execution")
        signature = (case["tasks"], case["model_exhausted_jobs"], membership)
        if scenario in cohorts and cohorts[scenario] != signature:
            raise ValueError("candidate actions do not share identical scenario cohorts")
        cohorts[scenario] = signature
        if case["model_exhausted_jobs"] and estimated_exhausted_ids(case) != {
            item["task_id"] for item in case["model_exhausted_jobs"]
        }:
            raise ValueError("exhausted observed work lacks modeled occupancy")
        completed = {item["task_id"]: item for item in validation["tasks"]}
        expected = {item["task"]["id"] for item in case["tasks"]}
        if (
            len(completed) != len(validation["tasks"])
            or set(completed) != expected
            or len(expected) != len(case["tasks"])
        ):
            raise ValueError("completion identities differ from the complete cohort")
        responses = [
            (
                case["cutoff_ms"]
                + completed[item["task"]["id"]]["finish_time"]
                - item["metadata"]["original_creation_ms"]
            )
            / 1000
            for item in application_tasks(case)
        ]
        if any(not math.isfinite(value) or value < 0 for value in responses):
            raise ValueError("invalid original-creation response")
        removed = cordoned_worker(case)
        drain = (
            max(
                (
                    item["finish_time"] / 1000
                    for item in completed.values()
                    if item.get("host_name") == removed
                ),
                default=0,
            )
            if removed
            else 0
        )
        charged = set(
            case.get("acquisition", {}).get(
                "allocated_workers", [worker["node_name"] for worker in case["workers"]]
            )
        )
        request_offsets = case.get("acquisition", {}).get("request_after_seconds", {})
        if any(
            isinstance(offset, bool)
            or not isinstance(offset, (int, float))
            or not math.isfinite(offset)
            or offset < 0
            for offset in request_offsets.values()
        ):
            raise ValueError("invalid modeled acquisition request offset")
        allocation = sum(
            worker["modeled_cores"]
            * (
                min(allocation_seconds, drain)
                if worker["node_name"] == removed
                else max(0, allocation_seconds - request_offsets.get(worker["node_name"], 0))
            )
            for worker in case["workers"]
            if worker["node_name"] in charged
        )
        score = grouped.setdefault(
            action,
            {"candidate": action, "selected_worker": case.get("selected_worker"), "scenarios": []},
        )
        if contract is not None:
            score.update(response_time_contract=contract, modeled_request_delay_seconds=allowance)
        if score["selected_worker"] != case.get("selected_worker") or any(
            item["scenario"] == scenario for item in score["scenarios"]
        ):
            raise ValueError("action target or scenario identity is inconsistent")
        score["scenarios"].append(
            {
                "scenario": scenario,
                "responses_seconds": responses,
                "cohort_size": len(application_tasks(case)),
                "complete": True,
                "allocated_core_seconds": allocation,
                "allocation_window_seconds": allocation_seconds,
            }
        )
    if len(timing_contracts) != 1:
        raise ValueError("native matrix has inconsistent response timing contracts")
    if (
        len(boundaries) != 1
        or "unchanged" not in grouped
        or any(
            {item["scenario"] for item in score["scenarios"]} != set(range(scenarios))
            for score in grouped.values()
        )
    ):
        raise ValueError("incomplete shared action/scenario matrix or conflicting cutoffs")
    for score in grouped.values():
        score["scenarios"].sort(key=lambda item: item["scenario"])
    return list(grouped.values())


def load_scores(batch_dir, *, scenarios=3, allocation_seconds=120):
    """Read one immutable native batch and verify its complete policy inputs.

    Args:
        batch_dir (Path): Collected successful native batch directory.
        scenarios (int): Required shared scenario count.
        allocation_seconds (float): Shared application allocation integration window.

    Returns:
        tuple: Candidate score inputs and the verified batch manifest.

    Raises:
        ValueError: Artifact hashes, case identity or complete scoring contract differ.
    """
    directory, batch = load_batch(batch_dir)
    rows = []
    for entry in batch["experiments"]:
        member = directory / entry["output_dir"] / entry["runner_dir"]
        case = json.loads((member / "inputs/case.json").read_text())
        execution = json.loads((member / "execution.json").read_text())
        if (case["candidate"], case["scenario"]) != (
            entry["candidate"],
            entry["scenario"],
        ) or execution.get("status") != "succeeded":
            raise ValueError("native case identity or execution status differs from batch")
        rows.append({"case": case, "validation": execution["validation"]})
    scores = score_cases(rows, scenarios=scenarios, allocation_seconds=allocation_seconds)
    scores.extend(
        {
            "candidate": item["candidate"],
            "selected_worker": None,
            "unavailable_reason": item["reason"],
            "scenarios": [],
        }
        for item in batch["suite_manifest"]["unavailable_candidates"]
    )
    return scores, batch


def prepare_runner(image, cluster, output):
    """Verify control-plane isolation and stage the exact native image before arrivals.

    Args:
        image (str): Immutable local wrapper image tag or digest.
        cluster (dict): Controller/runner SSH hosts, key, control-plane node and namespace.
        output (Path): New provenance directory, separate from measured cycle time.

    Raises:
        ValueError: Control-plane identity, readiness or imported image identity differs.
    """
    output.mkdir(parents=True, exist_ok=False)
    _preflight(
        cluster["controller"], cluster["runner_host"], cluster["key"], cluster["node"], output
    )
    _stage_image(image, cluster["runner_host"], cluster["key"], output)


def run_control_plane_suite(suite, output, image, cluster, name, *, timeout_seconds=20):
    """Run one bounded native matrix, preserving artifacts before deleting its Job.

    This function never changes application admission. Inputs are validated before
    staging; one CPU/two GiB and control-plane-only placement remain mandatory.
    Failed or timed-out resources and collected evidence remain for inspection.

    Args:
        suite (Path): Verified prepared scenario suite.
        output (Path): New per-cycle runner evidence directory.
        image (str): Exact image already staged by prepare_runner.
        cluster (dict): Controller/runner hosts, SSH key, control-plane node and namespace.
        name (str): Unique native Job name for this cycle.
        timeout_seconds (float): Native shared-process wall deadline.

    Returns:
        Path: Fully collected successful batch directory.

    Raises:
        ValueError: Native inputs, placement, exit status or artifact verification fail.
        RuntimeError: API/SSH operations fail or the outer terminal deadline expires.
    """
    plan_suite(suite)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    remote = f'/var/tmp/fns-opendc-{cluster["namespace"]}-{name}'
    _stage_inputs(suite, remote, cluster["runner_host"], cluster["key"])
    staged = time.monotonic()
    job = job_manifest(
        cluster["namespace"],
        name,
        image,
        cluster["node"],
        remote,
        timeout_seconds,
        control_plane=True,
    )
    job["spec"]["activeDeadlineSeconds"] = math.ceil(timeout_seconds) + 20
    container = job["spec"]["template"]["spec"]["containers"][0]
    container["command"] = ["python", "-u", "/app/opendc_native_batch.py"]
    container["args"] = [
        "--suite-dir",
        "/inputs",
        "--output-dir",
        "/results/batch",
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    write_json(output / "job-request.json", job)
    created = json.loads(
        remote_input(
            cluster["controller"],
            cluster["key"],
            ["kubectl", "create", "-f", "-", "-o", "json"],
            json.dumps(job).encode(),
        )
    )
    write_json(output / "job-created.json", created)
    deadline = time.monotonic() + timeout_seconds + 30
    while True:
        pods = json.loads(
            ssh(
                cluster["controller"],
                cluster["key"],
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    cluster["namespace"],
                    "-l",
                    "job-name=" + name,
                    "-o",
                    "json",
                ],
            )
        )
        write_json(output / "pods.json", pods)
        if len(pods["items"]) == 1 and pods["items"][0]["status"]["phase"] in (
            "Succeeded",
            "Failed",
        ):
            break
        if time.monotonic() > deadline:
            raise RuntimeError("native Job did not reach terminal state within its outer deadline")
        time.sleep(0.2)
    terminal = time.monotonic()
    pod = verify_collection_source(created, pods["items"], remote, cluster["node"])
    if pod["spec"].get("nodeName") != cluster["node"]:
        raise ValueError("native runner was not placed on the control plane")
    (output / "pod.log").write_bytes(
        ssh(
            cluster["controller"],
            cluster["key"],
            ["kubectl", "logs", "-n", cluster["namespace"], pod["metadata"]["name"]],
        )
    )
    archive = ssh(
        cluster["runner_host"], cluster["key"], ["tar", "-C", remote, "-cf", "-", "results"]
    )
    (output / "results.tar").write_bytes(archive)
    artifacts = output / "artifacts"
    artifacts.mkdir()
    extract_artifacts(io.BytesIO(archive), artifacts)
    batch_dir = artifacts / "results/batch"
    load_batch(batch_dir)
    statuses = pod["status"].get("containerStatuses", [])
    if (
        pod["status"]["phase"] != "Succeeded"
        or len(statuses) != 1
        or statuses[0].get("state", {}).get("terminated", {}).get("exitCode") != 0
        or statuses[0].get("restartCount") != 0
    ):
        raise ValueError("native Pod exit or restart evidence contradicts successful batch")
    write_json(
        output / "collection.json",
        {
            "status": "verified",
            "control_plane_node": cluster["node"],
            "pod_uid": pod["metadata"]["uid"],
            "image_id": statuses[0].get("imageID"),
            "elapsed_seconds": time.monotonic() - started,
            "stage_inputs_seconds": staged - started,
            "job_launch_and_execution_seconds": terminal - staged,
            "artifact_collection_seconds": time.monotonic() - terminal,
            "native_timeout_seconds": timeout_seconds,
            "remote_directory": remote,
        },
    )
    ssh(
        cluster["controller"],
        cluster["key"],
        ["kubectl", "delete", "job", "-n", cluster["namespace"], name, "--wait=true"],
    )
    return batch_dir
