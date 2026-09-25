"""Execute a compatible FNS action/sample matrix in one sequential native process."""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import sys
import time

from opendc_inputs import file_hashes, verify_inputs, write_json
from opendc_pinning import FNS_CONTRACT, PINNED_MODE, cordoned_worker
from opendc_process import run_process
from opendc_results import validate_provisional_results
from opendc_run import runtime_provenance, utc_now
from opendc_runtime import fns_runtime, topology_hosts


ACTIONS = ("unchanged", "scale-up", "scale-down")


def _common_experiment(path):
    """Normalize only the topology, trace location and intended action cordon axis.

    Args:
        path (Path): Verified individual case directory.

    Returns:
        dict: Experiment settings that every member must share exactly.

    Raises:
        ValueError: The case expands a dimension outside the supported matrix.
    """
    config = json.loads((path / "experiment.json").read_text())
    if (
        config.get("name") != "controlled"
        or config.get("runs") != 1
        or config.get("initialSeed") != 0
    ):
        raise ValueError(
            "native batch requires controlled experiment name and one run with seed zero"
        )
    for key in (
        "topologies",
        "workloads",
        "allocationPolicies",
        "failureModels",
        "checkpointModels",
        "exportModels",
        "maxNumFailures",
    ):
        if key in config and (not isinstance(config[key], list) or len(config[key]) != 1):
            raise ValueError(f"native batch requires singleton experiment dimension: {key}")
    config.pop("cordonHosts", None)
    config["topologies"][0]["importFrom"] = "case-topology"
    config["workloads"][0]["source"] = {"type": "named", "name": "case-trace"}
    return config


def plan_suite(suite_dir):
    """Verify a complete compatible matrix and derive its explicit native mapping.

    The pinned SDK expands cordon lists outside workload samples. A common
    topology retains the individual host order; hosts absent from an action
    close immediately and have no assigned work. Each sample has a distinct
    URI even when its bytes match another sample, preventing SDK set deduplication.

    Args:
        suite_dir (str or Path): Existing, hash-verified pinned scenario suite.

    Returns:
        dict: Native experiment, topology, ordered mapping and source suite manifest.

    Raises:
        ValueError: Inputs are incompatible, incomplete, empty or not pinned FNS cases.
    """
    suite = Path(suite_dir).resolve()
    manifest = json.loads((suite / "manifest.json").read_text())
    if not fns_runtime() or manifest.get("contract") != "opendc-scenarios-v1":
        raise ValueError("single-experiment execution requires a pinned FNS suite")
    if manifest.get("status") != "ready" or manifest.get("sha256") != file_hashes(
        suite, exclude=("manifest.json",)
    ):
        raise ValueError("suite readiness or artifact hashes differ")
    cases = {}
    for item in manifest["experiments"]:
        path = (suite / item["input_dir"]).resolve()
        if path == suite or not path.is_relative_to(suite):
            raise ValueError("case path escapes suite")
        verify_inputs(path)
        case = json.loads((path / "case.json").read_text())
        key = (item["candidate"], item["scenario"])
        if key in cases or key != (case["candidate"], case["scenario"]):
            raise ValueError("duplicate or inconsistent sample/action identity")
        if case["initialization_mode"] != PINNED_MODE or not case["tasks"]:
            raise ValueError(
                "native batch needs nonempty pinned cases; use individual empty execution"
            )
        cases[key] = (item, case, path)
    actions = [name for name in ACTIONS if any(key[0] == name for key in cases)]
    samples = sorted({key[1] for key in cases})
    if not cases or set(cases) != {(action, sample) for action in actions for sample in samples}:
        raise ValueError("suite must contain the complete action/sample Cartesian matrix")
    largest = max(cases.values(), key=lambda entry: len(entry[1]["workers"]))
    topology = json.loads((largest[2] / "topology.json").read_text())
    hosts = topology_hosts(topology)
    union_names = {host["name"] for host in hosts}
    reference = next(iter(cases.values()))[1]
    experiment = json.loads((largest[2] / "experiment.json").read_text())
    common = _common_experiment(largest[2])
    mapping, cordons = [], []
    for action in actions:
        action_reference = cases[(action, samples[0])][1]
        names = {worker["node_name"] for worker in action_reference["workers"]}
        removed = cordoned_worker(action_reference)
        cordon = sorted((union_names - names) | ({removed} if removed else set()))
        if cordon in cordons:
            raise ValueError("distinct actions would collapse to one native cordon specification")
        cordons.append(cordon)
        for sample in samples:
            item, case, path = cases[(action, sample)]
            if _common_experiment(path) != common:
                raise ValueError("member experiment settings differ from the shared configuration")
            source_case = cases[(actions[0], sample)][1]
            if any(case[key] != reference[key] for key in ("cutoff_ms", "horizon_ms")):
                raise ValueError("native matrix requires one cutoff and horizon")
            if any(
                case.get(key) != action_reference.get(key)
                for key in ("workers", "selected_worker", "initial_cordoned_worker")
            ):
                raise ValueError("action topology or cordon differs between samples")
            if any(
                case[key] != source_case[key]
                for key in ("tasks", "model_exhausted_jobs", "initial_membership", "initialization")
            ):
                raise ValueError("actions must share identical sample tasks and initial evidence")
            individual = json.loads((path / "topology.json").read_text())
            expected_topology = copy.deepcopy(topology)
            topology_hosts(expected_topology)[:] = [host for host in hosts if host["name"] in names]
            if individual != expected_topology:
                raise ValueError("union topology changes individual topology resources or order")
            mapping.append(
                {
                    **item,
                    "native_index": len(mapping),
                    "case_sha256": file_hashes(path),
                    "cordon_hosts": cordon,
                }
            )
    experiment["cordonHosts"] = cordons
    experiment["topologies"][0]["importFrom"] = str(largest[2] / "topology.json")
    workload = experiment["workloads"][0]
    experiment["workloads"] = [
        {
            **copy.deepcopy(workload),
            "source": {"type": "uri", "uri": (cases[(actions[0], sample)][2] / "trace").as_uri()},
        }
        for sample in samples
    ]
    return {
        "suite_manifest": manifest,
        "actions": actions,
        "samples": samples,
        "mapping": mapping,
        "topology": topology,
        "experiment": experiment,
        "mapping_contract": "cf10c06 Cartesian: cordon-major, workload-minor; one seed/topology",
    }


def _materialize_members(output, plan, record):
    """Validate all expected native directories and publish standard per-case artifacts.

    Args:
        output (Path): Batch root with frozen inputs and native output.
        plan (dict): Verified ordered action/sample mapping.
        record (dict): Mutable batch status, updated after each validated member.

    Raises:
        ValueError: Native output inventory or any case lifecycle is invalid.
    """
    raw = output / "native/controlled/raw-output"
    expected = {str(item["native_index"]) for item in plan["mapping"]}
    if not raw.is_dir() or {path.name for path in raw.iterdir()} != expected:
        raise ValueError("native Cartesian output inventory differs from declared mapping")
    for item in plan["mapping"]:
        native = raw / str(item["native_index"])
        if {path.name for path in native.iterdir()} != {"seed=0"}:
            raise ValueError("native sample has missing or unexpected seed output")
        relative = Path("experiments") / f'{item["native_index"]:04d}'
        member = output / relative / "run"
        member.mkdir(parents=True)
        shutil.copytree(output / "inputs" / item["input_dir"], member / "inputs")
        destination = member / "simulator/controlled/raw-output/0"
        shutil.copytree(native, destination)
        case = json.loads((member / "inputs/case.json").read_text())
        validation = validate_provisional_results(member / "simulator", case)
        execution = {
            "contract": FNS_CONTRACT,
            "status": "succeeded",
            "validation": validation,
            "process": {
                "execution_kind": "shared_native_batch",
                "exit_code": 0,
                "shared_process_path": "../../../shared-resources.json",
            },
            "provenance": record["provenance"],
            "native_mapping": item,
            "sha256": file_hashes(member, exclude=("execution.json",)),
        }
        write_json(member / "execution.json", execution)
        record["experiments"].append(
            {
                **{key: item[key] for key in ("candidate", "scenario", "input_dir")},
                "output_dir": relative.as_posix(),
                "runner_dir": "run",
                "status": "succeeded",
                "validated": True,
                "native_index": item["native_index"],
            }
        )
        record["remaining_experiments"] -= 1
        write_json(output / "batch.json", record)


def execute_suite(suite_dir, output_dir, timeout_seconds=120, runner="/opt/opendc/bin/opendc"):
    """Execute one FNS matrix with one measured process and independently validated members.

    Failed or interrupted executions retain frozen inputs and partial native
    output. Process cost belongs to the complete matrix and is never divided
    among members. Empty or incompatible matrices use the individual runner.

    Args:
        suite_dir (str or Path): Prepared pinned suite with one cutoff and horizon.
        output_dir (str or Path): New destination outside the source tree.
        timeout_seconds (float): Positive finite deadline for the complete process.
        runner (str): Native OpenDC executable.

    Returns:
        int: Zero for a fully validated batch, one for failure, or124 for timeout.

    Raises:
        ValueError: Paths, timeout or source suite are invalid before execution.
        FileExistsError: Output already exists.
    """
    source, output = Path(suite_dir).resolve(), Path(output_dir).resolve()
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("source and output must be separate")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be finite and positive")
    plan_suite(source)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    shutil.copytree(source, output / "inputs")
    plan = plan_suite(output / "inputs")
    write_json(output / "plan.json", plan)
    write_json(output / "experiment.json", plan["experiment"])
    record = {
        "contract": "opendc-batch-v1",
        "status": "running",
        "started_at": utc_now(),
        "backend": "native-single-experiment",
        "provenance": runtime_provenance(),
        "suite_manifest": plan["suite_manifest"],
        "experiments": [],
        "remaining_experiments": len(plan["mapping"]),
        "shared_process": None,
        "cost_scope": "one process for the full Cartesian matrix; no per-case attribution",
    }
    write_json(output / "batch.json", record)
    code = 1
    try:
        command = [
            runner,
            "--strict",
            "run",
            str(output / "experiment.json"),
            "--output",
            str(output / "native"),
            "--parallelism",
            "1",
            "--no-progress",
            "--no-summary",
        ]
        process = run_process(command, output, timeout_seconds)
        record["shared_process"] = process
        write_json(output / "shared-resources.json", process)
        if process["timed_out"]:
            record["status"], code = "timed_out", 124
        elif process["exit_code"] != 0 or process.get("received_signal"):
            record["status"] = "failed"
        else:
            _materialize_members(output, plan, record)
            record["status"], code = "succeeded", 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record.update(status="failed", error=str(exc))
    finally:
        record.update(
            finished_at=utc_now(),
            elapsed_seconds=time.monotonic() - started,
            sha256=file_hashes(output, exclude=("batch.json",)),
        )
        write_json(output / "batch.json", record)
    return code


def main():
    """Run a prepared matrix inside the matching pinned FNS engine environment.

    Returns:
        int: Validated batch exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    return execute_suite(args.suite_dir, args.output_dir, args.timeout_seconds)


if __name__ == "__main__":
    sys.exit(main())
