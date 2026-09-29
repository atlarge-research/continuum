"""Retrospective arrival-knowledge rankings with frozen causal runtime and action sets."""

import copy
import json
from pathlib import Path
import shutil

from closed_loop_policy import summarize_candidate
from opendc_inputs import file_hashes, verify_inputs, write_json
from opendc_native_batch import plan_suite
from opendc_pinning import initial_assignments, initialization_metadata


def derive_case(oracle, primary):
    """Transfer an available action to an already calibrated known-arrival cohort.

    Args:
        oracle (dict): Verified unchanged known-arrival case with causal calibration.
        primary (dict): Original causal candidate, defining topology and target eligibility.

    Returns:
        dict: Independent case preserving exact oracle Tasks and calibration metadata.

    Raises:
        ValueError: Causal boundaries, calibration, backlog membership or scope differ.
    """
    shared = (
        "cutoff_ms",
        "horizon_ms",
        "initial_membership",
        "initial_cordoned_worker",
        "occupancy_model",
        "model_exhausted_jobs",
    )
    if any(
        (
            oracle["candidate"] != "unchanged",
            oracle["scope"] != "complete",
            primary["scope"] != "complete",
            oracle["omitted_tasks"],
            primary["omitted_tasks"],
            any(oracle.get(key) != primary.get(key) for key in shared),
        )
    ):
        raise ValueError("oracle and primary do not share complete causal state and calibration")
    backlogs = [
        [row for row in case["tasks"] if row["metadata"]["cohort"] == "backlog"]
        for case in (oracle, primary)
    ]
    if backlogs[0] != backlogs[1]:
        raise ValueError("known arrivals cannot change causal backlog tasks")
    for case in (oracle, primary):
        if case["candidate"] not in ("unchanged", "scale-up", "scale-down"):
            raise ValueError("unknown capacity candidate")
    result = copy.deepcopy(oracle)
    result.update(
        {
            key: copy.deepcopy(primary[key])
            for key in ("candidate", "workers", "selected_worker", "initial_cordoned_worker")
        }
    )
    result.update(scenario=0, experiment_kind="known-arrival-ranking-diagnostic")
    return result


def prepare_known_ranking(known_suite, primary_suite, output):
    """Expand a verified oracle cohort over the original cycle's available action set.

    Copies exact calibrated trace bytes, retaining exhausted estimates and their
    provenance without adding startup/release occupancy a second time. Original
    candidate topology/configuration is copied and validated against assignments.

    Args:
        known_suite (Path): Verified one-sample unchanged known-arrival suite.
        primary_suite (Path): Verified original causal action/scenario suite.
        output (Path): New diagnostic suite directory.

    Returns:
        dict: Verified one-sample action matrix manifest.

    Raises:
        ValueError: Source matrices or derived placement/cohort identities are inconsistent.
        FileExistsError: Output already exists.
    """
    known_suite, primary_suite, output = map(Path, (known_suite, primary_suite, output))
    known_plan, primary_plan = plan_suite(known_suite), plan_suite(primary_suite)
    if known_plan["samples"] != [0] or known_plan["actions"] != ["unchanged"]:
        raise ValueError("oracle source must be a single unchanged sample")
    known_manifest = json.loads((known_suite / "manifest.json").read_text())
    primary_manifest = json.loads((primary_suite / "manifest.json").read_text())
    if known_manifest["experiment_kind"] != "known-arrival":
        raise ValueError("oracle requires explicit known-arrival provenance")
    source = known_suite / known_manifest["experiments"][0]["input_dir"]
    oracle = json.loads((source / "case.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    evidence = output / "source-evidence"
    evidence.mkdir()
    write_json(evidence / "known-suite-manifest.json", known_manifest)
    write_json(evidence / "primary-suite-manifest.json", primary_manifest)
    experiments = []
    for action in primary_plan["actions"]:
        original = next(
            row
            for row in primary_manifest["experiments"]
            if row["candidate"] == action and row["scenario"] == 0
        )
        primary = primary_suite / original["input_dir"]
        case = derive_case(oracle, json.loads((primary / "case.json").read_text()))
        assignments = initial_assignments(case)
        if assignments != initial_assignments(oracle):
            raise ValueError("derived candidate changes initial pinned assignments")
        case["initialization"] = initialization_metadata(assignments, case)
        relative = Path("experiments") / action / "0000"
        destination = output / relative
        shutil.copytree(source, destination)
        for filename in ("topology.json", "experiment.json"):
            shutil.copyfile(primary / filename, destination / filename)
        write_json(destination / "case.json", case)
        member = json.loads((destination / "manifest.json").read_text())
        member["sha256"] = file_hashes(destination, exclude=("manifest.json",))
        write_json(destination / "manifest.json", member)
        verify_inputs(destination)
        experiments.append(dict(candidate=action, scenario=0, input_dir=relative.as_posix()))
    manifest = {
        **copy.deepcopy(known_manifest),
        "experiments": experiments,
        "experiment_kind": "known-arrival-ranking-diagnostic",
        "unavailable_candidates": primary_manifest["unavailable_candidates"],
        "derivation": dict(
            method="known arrivals with original causal action set",
            calibration="preserved exactly; never reapplied",
            primary_source=str(primary_suite),
            known_source=str(known_suite),
        ),
    }
    manifest["sha256"] = file_hashes(output, exclude=("manifest.json",))
    write_json(output / "manifest.json", manifest)
    plan_suite(output)
    return manifest


def rank_candidates(scores, decision_age, scenarios):
    """Describe per-cutoff objective preference before hysteresis and physical guards.

    Args:
        scores (list[dict]): Complete native candidate measurements.
        decision_age (float): Same original cycle latency margin for every diagnostic variant.
        scenarios (int): Required futures per candidate, one for known arrivals.

    Returns:
        dict: Feasible allocation ranking or infeasible response ranking, explicitly diagnostic.
    """
    rows = [summarize_candidate(row, decision_age, scenarios=scenarios) for row in scores]
    valid = [row for row in rows if row["valid"]]
    feasible = [row for row in valid if row["worst_late_fraction"] <= 0.05 + 1e-12]
    ranked = sorted(
        feasible or valid,
        key=lambda row: (
            (0, row["allocated_core_seconds"])
            if feasible
            else (row["worst_late_fraction"], row["mean_tardiness_seconds"]),
            row["candidate"] != "unchanged",
            row["candidate"],
        ),
    )
    return dict(
        scores=rows,
        feasible=bool(feasible),
        preferred=ranked[0]["candidate"] if ranked else None,
        ranking=[row["candidate"] for row in ranked],
        interpretation="Diagnostic objective ranking before hysteresis, cooldown and guards; "
        "known arrivals are retrospective, not deployable foresight or physical benefit.",
    )
