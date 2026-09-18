"""Arrival-only forecasts from bounded observer evidence; never actuates Kubernetes."""
from __future__ import annotations

import argparse
import copy
import hashlib
from dataclasses import asdict, dataclass, fields
from importlib.metadata import version
import json
import math
from pathlib import Path
import statistics
import time
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import PoissonRegressor

from forecast_trace import (
    bounded_read,
    digest,
    iso,
    milliseconds,
    observed_milliseconds,
    parquet_tasks,
    read_trace,
    training_bins,
    write_json,
)
from simulation_input import SIMULATION_SCHEMA_VERSION, build_simulation_inputs


@dataclass(frozen=True)
class Settings:
    run_id: str
    origin_ms: int
    period_seconds: int = 120
    bin_seconds: int = 5
    warmup_periods: int = 2
    max_gap_seconds: float = 3.0
    horizon_seconds: int = 60
    scenarios: int = 100
    seed: int = 20261008
    image_count: int = 4
    inference_repetitions: int = 128

    def validate(self):
        for name in (
            "period_seconds",
            "bin_seconds",
            "warmup_periods",
            "horizon_seconds",
            "scenarios",
            "image_count",
            "inference_repetitions",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.seed < 0 or not self.run_id:
            raise ValueError("nonnegative seed and workload run ID required")
        if not math.isfinite(self.max_gap_seconds) or self.max_gap_seconds <= 0:
            raise ValueError("max_gap_seconds must be finite and positive")
        if self.period_seconds % self.bin_seconds or self.horizon_seconds % self.bin_seconds:
            raise ValueError("period and horizon must be multiples of bin width")


def eligible_profile(record, settings):
    task, source = record["task"], record["source"]
    fragments = task["fragments"]
    return (
        source["image_count"] == settings.image_count
        and source.get("inference_repetitions", 1) == settings.inference_repetitions
        and source.get("resource_sample_count", 0) >= 3
        and source.get("sampling_quality") == "sampled"
        and task["duration"] > 0
        and task["cpu_count"] == 1
        and task["mem_capacity"] == 512
        and task["cpu_capacity"] > 0
        and math.isfinite(task["cpu_capacity"])
        and bool(fragments)
        and sum(f["duration"] for f in fragments) == task["duration"]
        and all(
            f["duration"] > 0
            and f["cpu_count"] == task["cpu_count"]
            and math.isfinite(f["cpu_usage"])
            and 0 <= f["cpu_usage"] <= task["cpu_capacity"]
            for f in fragments
        )
    )


def select_template(trace, settings):
    eligible = [record for record in trace.completed if eligible_profile(record, settings)]
    if not eligible:
        return None
    median = statistics.median(record["task"]["duration"] for record in eligible)
    selected = min(
        eligible,
        key=lambda r: (
            abs(r["task"]["duration"] - median),
            r["source"]["kubernetes_job_uid"],
        ),
    )
    template = {
        "schema_version": 1,
        "selection_cutoff": iso(trace.cutoff),
        "selection_rule": "nearest eligible median duration; Job UID tie-break",
        "eligible_jobs": len(eligible),
        "median_duration_ms": median,
        "workload_run_id": settings.run_id,
        "record": copy.deepcopy(selected),
    }
    template["sha256"] = digest(template)
    return template


def check_template(template, cutoff, settings):
    if template is None:
        return "template_unavailable"
    unsigned = {key: value for key, value in template.items() if key != "sha256"}
    if digest(unsigned) != template["sha256"]:
        raise ValueError("template hash mismatch")
    selection = milliseconds(template["selection_cutoff"])
    if selection > cutoff:
        return "template_after_cutoff"
    if template["workload_run_id"] != settings.run_id or not eligible_profile(
        template["record"], settings
    ):
        raise ValueError("template does not match the homogeneous workload")
    if observed_milliseconds(template["record"]["source"]["completion_time"]) > selection:
        raise ValueError("template completed after selection")
    return None


def features(timestamps, settings):
    phase = (
        2
        * np.pi
        * (np.asarray(timestamps, dtype=float) - settings.origin_ms)
        / (settings.period_seconds * 1000)
    )
    return np.column_stack((np.sin(phase), np.cos(phase)))


def forecast(trace, settings, template=None):
    settings.validate()
    bin_ms = settings.bin_seconds * 1000
    bins = training_bins(trace, settings.origin_ms, bin_ms, round(settings.max_gap_seconds * 1000))
    eligible = [row for row in bins if row["eligible"]]
    phase_counts = [0] * (settings.period_seconds // settings.bin_seconds)
    for row in eligible:
        phase_counts[((row["start_ms"] - settings.origin_ms) // bin_ms) % len(phase_counts)] += 1
    summary = {
        "schema_version": 1,
        "status": "not_ready",
        "reasons": [],
        "cutoff": iso(trace.cutoff),
        "settings": asdict(settings),
        "history": {
            "eligible_bins": len(eligible),
            "excluded_bins": len(bins) - len(eligible),
            "incomplete_bins": int(
                trace.cutoff > settings.origin_ms
                and (trace.cutoff - settings.origin_ms) % bin_ms != 0
            ),
            "usable_seconds": len(eligible) * settings.bin_seconds,
            "phase_bin_observations": phase_counts,
            "observed_unique_jobs": len(trace.arrivals),
        },
        "uncertainty": (
            "Poisson arrival randomness conditional on fitted model; "
            "excludes full model/parameter uncertainty"
        ),
    }
    reasons = summary["reasons"]
    if trace.state is None:
        reasons.append("state_missing")
    elif trace.cutoff - trace.states[-1][0] > settings.max_gap_seconds * 1000:
        reasons.append("state_stale")
    if min(phase_counts) < settings.warmup_periods:
        reasons.append("history_insufficient")
    # Selection is made only when usable history is ready, then frozen by the caller.
    if template is None and not reasons:
        template = select_template(trace, settings)
    template_problem = check_template(template, trace.cutoff, settings)
    if template_problem:
        reasons.append(template_problem)
    if reasons:
        return summary, None, [], bins

    target_starts = list(
        range(trace.cutoff, trace.cutoff + settings.horizon_seconds * 1000, bin_ms)
    )
    y = np.asarray([row["count"] for row in eligible], dtype=float)
    reference = float(np.mean(y))
    try:
        if np.all(y == 0):
            means = np.zeros(len(target_starts))
            parameters = {"kind": "constant_zero", "alpha": 0.01}
        else:
            model = PoissonRegressor(alpha=0.01, max_iter=1000, tol=1e-8)
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                model.fit(
                    features([r["start_ms"] + bin_ms / 2 for r in eligible], settings),
                    y,
                )
            means = model.predict(
                features([start + bin_ms / 2 for start in target_starts], settings)
            )
            parameters = {
                "kind": "cyclic_poisson",
                "intercept": float(model.intercept_),
                "coefficients": model.coef_.tolist(),
                "alpha": 0.01,
            }
        if not np.all(np.isfinite(means)) or np.any(means < 0):
            raise ValueError("non-finite or negative prediction")
    except (ValueError, ArithmeticError, ConvergenceWarning) as exc:
        summary.update(status="fit_failed", reasons=["fit_failed"], error=str(exc))
        return summary, template, [], bins

    rng = np.random.default_rng(np.random.SeedSequence([settings.seed, trace.cutoff]))
    scenarios = []
    for _ in range(settings.scenarios):
        arrivals = []
        for start, mean in zip(target_starts, means):
            count = int(rng.poisson(mean))
            arrivals.extend((start + rng.integers(0, bin_ms, count)).tolist())
        arrivals.sort()
        tasks = []
        for index, arrival in enumerate(arrivals, len(trace.arrivals) + 1):
            task = copy.deepcopy(template["record"]["task"])
            task.update(id=index, submission_time=iso(arrival))
            for fragment in task["fragments"]:
                fragment["id"] = index
            tasks.append(task)
        scenarios.append(tasks)
    summary.update(
        status="ready",
        model=parameters,
        template_sha256=template["sha256"],
        predictions=[
            {
                "start_ms": start,
                "mean_count": float(mean),
                "reference_mean_count": reference,
            }
            for start, mean in zip(target_starts, means)
        ],
        scenario_job_counts=[len(tasks) for tasks in scenarios],
    )
    return summary, template, scenarios, bins


def run_once(
    observer_dir,
    output_dir,
    cutoff,
    settings,
    template=None,
    boundaries=None,
    *,
    simulation_inputs=False,
):
    """One reproducible cutoff. An existing output directory is never overwritten."""
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(output)
    rows, manifest = bounded_read(observer_dir, boundaries)
    trace = read_trace(rows, settings.run_id, cutoff)
    requested_cutoff = cutoff
    state_problem = None
    if simulation_inputs:
        if trace.state is None:
            state_problem = "state_missing"
        elif cutoff - trace.states[-1][0] > settings.max_gap_seconds * 1000:
            state_problem = "state_stale"
        else:
            cutoff = trace.states[-1][0]
            # Reuse the frozen prefixes; do not read live files a second time.
            trace = read_trace(rows, settings.run_id, cutoff)
    summary, selected, scenarios, bins = forecast(trace, settings, template)
    summary["inputs"] = manifest
    summary["dependencies"] = {
        name: version(name)
        for name in (
            "numpy",
            "scipy",
            "scikit-learn",
            "pyarrow",
            "joblib",
            "threadpoolctl",
        )
    }
    implementation_files = ["forecast_workload.py", "forecast_trace.py"]
    if simulation_inputs:
        implementation_files.append("simulation_input.py")
    summary["implementation_sha256"] = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in implementation_files
    }
    simulation = None
    if simulation_inputs:
        summary["requested_cutoff"] = iso(requested_cutoff)
        if state_problem or summary["status"] != "ready":
            reasons = ([state_problem] if state_problem else []) + summary["reasons"]
            simulation = (
                {
                    "schema_version": SIMULATION_SCHEMA_VERSION,
                    "status": "not_ready",
                    "reasons": list(dict.fromkeys(reasons)),
                    "diagnostics": [],
                },
                None,
                [],
            )
        else:
            simulation = build_simulation_inputs(trace, selected, scenarios, settings)
        simulation_manifest = simulation[0]
        simulation_manifest.update(
            requested_cutoff=iso(requested_cutoff),
            effective_cutoff=iso(cutoff) if not state_problem else None,
            inputs=manifest,
            template_sha256=selected["sha256"] if selected else None,
            implementation_sha256=summary["implementation_sha256"],
            dependencies=summary["dependencies"],
        )
        summary["simulation_inputs"] = {
            key: simulation_manifest[key] for key in ("status", "reasons", "diagnostics")
        }
    output.mkdir(parents=True)
    write_json(output / "forecast.json", summary)
    write_json(output / "boundaries.json", manifest)
    write_json(output / "training-bins.json", bins)
    write_json(output / "state.json", trace.state)
    ids = {
        uid: index
        for index, uid in enumerate(
            sorted(
                trace.arrivals,
                key=lambda uid: (trace.arrivals[uid]["creation_ms"], uid),
            ),
            1,
        )
    }
    write_json(output / "job-ids.json", ids)
    history = []
    for record in trace.completed:
        task = copy.deepcopy(record["task"])
        task["id"] = ids[record["source"]["kubernetes_job_uid"]]
        for fragment in task["fragments"]:
            fragment["id"] = task["id"]
        history.append(task)
    parquet_tasks(history, output / "history")
    if selected:
        write_json(output / "template.json", selected)
    for index, tasks in enumerate(scenarios):
        parquet_tasks(tasks, output / "scenarios" / f"{index:04d}")
    if simulation is not None:
        simulation_manifest, initial_state, combined = simulation
        directory = output / "simulation"
        directory.mkdir()
        if simulation_manifest["status"] == "ready":
            write_json(directory / "initial-state.json", initial_state)
            for index, tasks in enumerate(combined):
                parquet_tasks(tasks, directory / "scenarios" / f"{index:04d}")
        # The manifest is the commit marker; failed writes cannot publish ready.
        write_json(directory / "manifest.json", simulation_manifest)
    return summary, selected


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--observer-dir", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument(
        "--phase-origin",
        required=True,
        help="UTC service cycle origin, not a planned schedule",
    )
    result.add_argument("--cutoff", help="UTC cutoff for one-shot mode")
    result.add_argument(
        "--simulation-inputs",
        action="store_true",
        help="also export initial state and combined traces at the latest fresh snapshot",
    )
    result.add_argument(
        "--template",
        type=Path,
        help="frozen template.json; selection cutoff is enforced",
    )
    result.add_argument(
        "--boundaries", type=Path, help="saved boundaries.json for exact prefix replay"
    )
    result.add_argument(
        "--interval-seconds",
        type=float,
        help="periodic mode; no cutoff/boundaries; records runtime separately",
    )
    result.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="periodic iterations; zero runs until interrupted",
    )
    for name, default, value_type in (
        ("period-seconds", 120, int),
        ("bin-seconds", 5, int),
        ("warmup-periods", 2, int),
        ("max-gap-seconds", 3.0, float),
        ("horizon-seconds", 60, int),
        ("scenarios", 100, int),
        ("seed", 20261008, int),
        ("image-count", 4, int),
        ("inference-repetitions", 128, int),
    ):
        result.add_argument(f"--{name}", type=value_type, default=default)
    return result


def main():
    args = parser().parse_args()
    try:
        settings = Settings(
            **{
                field.name: getattr(args, field.name)
                for field in fields(Settings)
                if field.name != "origin_ms"
            },
            origin_ms=milliseconds(args.phase_origin),
        )
        settings.validate()
        template = json.loads(args.template.read_text()) if args.template else None
        boundaries = json.loads(args.boundaries.read_text()) if args.boundaries else None
        if args.interval_seconds is None:
            if not args.cutoff:
                raise ValueError("one-shot mode requires --cutoff")
            summary, _ = run_once(
                args.observer_dir,
                args.output_dir,
                milliseconds(args.cutoff),
                settings,
                template,
                boundaries,
                simulation_inputs=args.simulation_inputs,
            )
            print(
                json.dumps(
                    {
                        "status": summary["status"],
                        "reasons": summary["reasons"],
                        "history": summary["history"],
                        **(
                            {"simulation_inputs": summary["simulation_inputs"]}
                            if args.simulation_inputs
                            else {}
                        ),
                    }
                )
            )
            ready = summary["status"] == "ready" and (
                not args.simulation_inputs or summary["simulation_inputs"]["status"] == "ready"
            )
            raise SystemExit(0 if ready else 2)
        if (
            args.cutoff
            or args.boundaries
            or not math.isfinite(args.interval_seconds)
            or args.interval_seconds <= 0
            or args.iterations < 0
        ):
            raise ValueError(
                "periodic mode requires a positive interval, nonnegative iterations, and no "
                "cutoff/boundaries"
            )
        args.output_dir.mkdir(parents=True, exist_ok=False)
        index = 0
        while args.iterations == 0 or index < args.iterations:
            started = time.monotonic()
            cutoff = time.time_ns() // 1_000_000
            summary, selected = run_once(
                args.observer_dir,
                args.output_dir / str(cutoff),
                cutoff,
                settings,
                template,
                simulation_inputs=args.simulation_inputs,
            )
            if template is None and selected is not None:
                template = selected
                write_json(args.output_dir / "template.json", template)
            print(
                json.dumps(
                    {
                        "cutoff": iso(cutoff),
                        "status": summary["status"],
                        "reasons": summary["reasons"],
                        "history": summary["history"],
                        "elapsed_seconds": time.monotonic() - started,
                        **(
                            {
                                "effective_cutoff": summary["cutoff"],
                                "simulation_inputs": summary["simulation_inputs"],
                            }
                            if args.simulation_inputs
                            else {}
                        ),
                    }
                ),
                flush=True,
            )
            index += 1
            if args.iterations == 0 or index < args.iterations:
                time.sleep(max(0, args.interval_seconds - (time.monotonic() - started)))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}), flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
