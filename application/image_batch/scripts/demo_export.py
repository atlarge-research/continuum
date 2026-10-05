"""Export selected illustrative demo evidence without changing held-out verdicts."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def response_plot(run):
    """Produce original-creation plotting data without dropping late or censored Jobs.

    Args:
        run (dict): Canonical evaluated response cohort and time origin.

    Returns:
        dict: All response points and completion CDF using the full Job denominator.

    Raises:
        ValueError: Cohort count, unique identities or terminal timing is inconsistent.
    """
    responses = run["responses"]
    cohort = responses["cohort"]
    if len(cohort) != responses["jobs"] or len({row["uid"] for row in cohort}) != len(cohort):
        raise ValueError("response cohort differs from evaluated Job denominator")
    points, completed = [], []
    for row in cohort:
        terminal = row.get("job_finish_ms") if row["status"] == "Complete" else None
        response = (terminal - row["creation_ms"]) / 1000 if terminal is not None else None
        if response is not None and response < 0:
            raise ValueError("terminal Job time precedes original API creation")
        if response is not None:
            completed.append(response)
        classifier = row.get("finish_ms")
        points.append(
            dict(
                **row,
                creation_offset_seconds=row["creation_ms"] / 1000 - run["evaluation_start_seconds"],
                response_seconds=response,
                classifier_response_seconds=(classifier - row["creation_ms"]) / 1000
                if classifier is not None
                else None,
                within_deadline=response is not None and response <= 120,
            )
        )
    return dict(
        jobs=points,
        denominator=responses["jobs"],
        completion_cdf=[
            dict(seconds=value, fraction=index / len(cohort))
            for index, value in enumerate(sorted(completed), 1)
        ],
    )


def case_metadata(candidate, seed, payload):
    """Describe an independently analyzed case without promoting its held-out flags.

    Args:
        candidate (str): Predeclared workload candidate.
        seed (int): Shared workload seed.
        payload (dict): Canonical matched-case analysis, including source and sender proof.

    Returns:
        dict: Whole-case selection metadata and separate illustrative qualification.

    Raises:
        ValueError: Case identity, unique arms, source or arrival provenance disagree.
    """
    runs = payload["runs"]
    arms = {run["arm"] for run in runs}
    if not runs or len(arms) != len(runs) or not arms <= {"fixed", "forecast", "reactive"}:
        raise ValueError("empty or duplicate/unknown policy arms")
    for run in runs:
        if run["seed"] != seed or not run["source_hashes"]:
            raise ValueError("missing source or mismatched seed")
        for key in ["source_hashes", "arrival_plan_sha256"]:
            if run[key] != runs[0][key]:
                raise ValueError(f"unmatched case provenance: {key}")
    summaries = payload["summary"]
    if {(r["seed"], r["arm"]) for r in summaries} != {(seed, arm) for arm in arms}:
        raise ValueError("summary identities differ from case runs")
    verdicts = payload["seed_verdicts"]
    if len(verdicts) != 1 or verdicts[0]["seed"] != seed:
        raise ValueError("case does not have exactly one matched seed verdict")
    complete = arms == {"fixed", "forecast", "reactive"}
    valid = all(
        run["accepted_capture"] and run["sender_evaluated_window"]["fidelity_passed"]
        for run in runs
    )
    service = all(
        row["jobs"] > 0 and row["deadline_fraction"] >= 0.95
        for row in summaries
        if row["arm"] in {"fixed", "forecast"}
    )
    observed = any(
        row["arm"] == "forecast" and row["observed_forecast_actions"] > 0 for row in summaries
    )
    return dict(
        id=f"{candidate.lower()}-s{seed}",
        candidate=candidate,
        seed=seed,
        arms=sorted(arms),
        complete_trio=complete,
        demo_ready=complete and valid and service and observed and verdicts[0]["passed"],
        heldout_validated=False,
        matched_verdict=verdicts[0],
    )


def plotting_data(run):
    """Normalize plotted clocks while retaining canonical controller and uncertainty data.

    Args:
        run (dict): Self-contained canonical metrics for one policy.

    Returns:
        dict: Offline HTML inputs with seconds relative to evaluated-window start.
    """
    start = run["evaluation_start_seconds"]
    return dict(
        arm=run["arm"],
        seed=run["seed"],
        deadline_seconds=120,
        time_origin_seconds=start,
        evaluated_duration_seconds=run["arrival_end_seconds"] - start,
        responses=response_plot(run),
        allocation=[
            dict(**row, seconds=row["time"] - start) for row in run["allocation"].get("series", [])
        ],
        planned_arrivals=[
            dict(**row, seconds=row["planned_offset_ns"] / 1e9 + run["origin_seconds"] - start)
            for row in run["arrival_plan"]
        ],
        controller=run["controller"],
        controller_full_operation=run.get("controller_full_operation"),
        forecast_diagnostics=run.get("forecast_diagnostics"),
        sender=run["sender_evaluated_window"],
    )


def physical_attempts(state, output):
    """Export every physical attempt with portable failure and reconciliation evidence.

    Args:
        state (dict): Durable accepted, failed and possibly inflight capture accounting.
        output (Path): Fresh bundle directory receiving compact failure evidence copies.

    Returns:
        list[dict]: Ordered physical inventory with explicit status and acceptance.

    Raises:
        ValueError: Durable attempt identities or count disagree with completed records.
        OSError: Referenced failed-attempt evidence cannot be copied; export fails closed.
    """
    count = state.get("attempts", len(state["records"]))
    failed = state.get("failed_attempts", [])
    entries = {row["attempt"]: dict(row, status="failed", accepted_capture=False) for row in failed}
    if len(entries) != len(failed) or any(number < 1 or number > count for number in entries):
        raise ValueError("failed physical attempt identities are inconsistent")
    active = state.get("active_request")
    if active and count not in entries:
        candidate, arm, seed = active
        entries[count] = dict(
            attempt=count,
            candidate=candidate,
            arm=arm,
            seed=seed,
            status="failed" if state.get("error") else "in_progress",
            accepted_capture=False,
            error=state.get("error"),
        )
    complete_numbers = [number for number in range(1, count + 1) if number not in entries]
    if len(complete_numbers) != len(state["records"]):
        raise ValueError("physical attempt count differs from durable completed/failed inventory")
    for number, record in zip(complete_numbers, state["records"]):
        entries[number] = dict(
            record,
            attempt=number,
            status="complete",
            accepted_capture=record.get("summary", {}).get("accepted_capture", True),
        )
    for number, row in entries.items():
        if row["status"] == "complete":
            continue
        row["failure_evidence"] = {}
        for label in ("failure", "reconciliation"):
            if not row.get(label):
                continue
            data = Path(row[label]).read_bytes()
            json.loads(data)
            relative = f"failure-evidence/attempt-{number:02d}-{label}.json"
            destination = output / relative
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(data)
            row["failure_evidence"][label] = relative
    return [entries[number] for number in range(1, count + 1)]


def export_bundle(checkpoint, output):
    """Write all cases and select a complete scenario in a fresh portable directory.

    Args:
        checkpoint (Path): Durable completed or failed campaign checkpoint.
        output (Path): Fresh bundle destination; existing output is never overwritten.

    Raises:
        ValueError: Completed records and canonical analysis disagree.
        FileExistsError: The bundle destination already exists.
    """
    state = json.loads(Path(checkpoint).read_text(encoding="utf-8"))
    groups = {}
    for record in state["records"]:
        groups.setdefault((record["candidate"], record["seed"]), []).append(record)
    prepared = []
    for (candidate, seed), records in groups.items():
        payload = json.loads(
            (Path(records[-1]["analysis"]) / "metrics.json").read_text(encoding="utf-8")
        )
        if {run["arm"] for run in payload["runs"]} != {record["arm"] for record in records}:
            raise ValueError("canonical case does not include every completed policy record")
        prepared.append((case_metadata(candidate, seed, payload), payload))
    complete = [case for case, _ in prepared if case["complete_trio"]]
    selected = next(
        (case for case in complete if case["demo_ready"]), complete[0] if complete else None
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "cases").mkdir()
    (output / "plots").mkdir()
    rows = []
    for case, payload in prepared:
        case["metrics"] = f"cases/{case['id']}.json"
        case["plots"] = {}
        (output / case["metrics"]).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        for run in payload["runs"]:
            relative = f"plots/{case['id']}-{run['arm']}.json"
            case["plots"][run["arm"]] = relative
            (output / relative).write_text(
                json.dumps(plotting_data(run), indent=2) + "\n", encoding="utf-8"
            )
        rows.extend(
            dict(candidate=case["candidate"], case=case["id"], **row) for row in payload["summary"]
        )
    if rows:
        with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    failure = state.get("preflight_failure_evidence")
    index = dict(
        schema_version="opendc-illustrative-demo-bundle-v1",
        selected_case=selected["id"] if selected else None,
        demo_ready=bool(selected and selected["demo_ready"]),
        heldout_validated=False,
        selection_basis=(
            "First qualifying complete predeclared scenario; otherwise first complete scenario "
            "for decision. All completed policies and unsuccessful launches remain visible."
        ),
        interpretation=(
            "Selected development illustration, not held-out validation. Allocation includes "
            "pending/draining application resources and observation bounds; powered reserves "
            "remain on. Deadline uses original API Job creation and terminal Job completion."
        ),
        cases=[case for case, _ in prepared],
        attempts=physical_attempts(state, output),
        physical_attempt_count=state.get("attempts", len(state["records"])),
        execution_state=state,
        preflight_failures=[json.loads(Path(failure).read_text(encoding="utf-8"))]
        if failure
        else [],
    )
    (output / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    hashes = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


def main():
    """Export the requested campaign to a new offline bundle.

    Raises:
        ValueError: Campaign records do not match canonical metrics.
        FileExistsError: The requested bundle output already exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_bundle(args.checkpoint, args.output)


if __name__ == "__main__":
    main()
