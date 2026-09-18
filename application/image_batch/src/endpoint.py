"""Endpoint sender for reproducible open-loop JPEG batch workloads."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import statistics
import sys
import tarfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.request import Request, urlopen

from events import emit_stream, new_event


NANOSECONDS_PER_SECOND = 1_000_000_000
FIDELITY_TOLERANCE_NS = 250_000_000
FIDELITY_REQUIRED_FRACTION = 0.95


@dataclass(frozen=True)
class PlannedArrival:
    """One arrival in a schedule, relative to the schedule start."""

    batch_index: int
    planned_offset_ns: int
    expected_rate_per_second: float | None


@dataclass(frozen=True)
class PreparedBatch:
    """A fully prepared request whose timed path only performs HTTP I/O."""

    arrival: PlannedArrival
    endpoint_batch_id: str
    payload: bytes
    image_count: int
    batch_build_duration_ns: int


@dataclass(frozen=True)
class SendResult:
    """Measured result of attempting one scheduled request."""

    arrival: PlannedArrival
    endpoint_batch_id: str
    actual_offset_ns: int
    schedule_lag_ns: int
    successful: bool


class ThreadSafeEmitter:
    """Serialize complete JSON events emitted by concurrent sender threads."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, Any]) -> None:
        with self._lock:
            emit_stream(self.stream, event)


def build_batch(image_paths: list[Path]) -> bytes:
    """Build a deterministic uncompressed tar containing image bytes."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:") as archive:
        for index, path in enumerate(image_paths):
            content = path.read_bytes()
            info = tarfile.TarInfo(name=f"{index:04d}-{path.name}")
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def select_images(images: list[Path], batch_size: int, generator: random.Random) -> list[Path]:
    """Select a fresh batch, avoiding repeats until all source images are used."""
    if not images:
        raise ValueError("cannot select images from an empty collection")
    selected: list[Path] = []
    while len(selected) < batch_size:
        cycle = images.copy()
        generator.shuffle(cycle)
        selected.extend(cycle[: batch_size - len(selected)])
    return selected


def send_batch(
    adapter_url: str,
    payload: bytes,
    endpoint_batch_id: str,
    workload_run_id: str,
) -> dict[str, str]:
    request = Request(
        f"{adapter_url.rstrip('/')}/v1/batches",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-tar",
            "X-Continuum-Batch-ID": endpoint_batch_id,
            "X-Continuum-Workload-Run-ID": workload_run_id,
        },
    )
    with urlopen(request, timeout=60) as response:  # nosec: explicit demo input
        receipt = json.load(response)
    return receipt


def build_constant_schedule(batches: int, interval_seconds: float) -> list[PlannedArrival]:
    """Build the backwards-compatible constant-interval schedule."""
    if batches < 1 or interval_seconds < 0 or not math.isfinite(interval_seconds):
        raise ValueError("batch count must be positive and interval finite/non-negative")
    expected_rate = 1.0 / interval_seconds if interval_seconds > 0 else None
    return [
        PlannedArrival(
            batch_index=index,
            planned_offset_ns=round(index * interval_seconds * NANOSECONDS_PER_SECOND),
            expected_rate_per_second=expected_rate,
        )
        for index in range(batches)
    ]


def build_periodic_schedule(
    *,
    period_seconds: float,
    minimum_rate_per_second: float,
    peak_rate_per_second: float,
    generator: random.Random,
    arrival_cycles: int = 1,
) -> list[PlannedArrival]:
    """Sample continuous arrivals for fixed-length cycles; more cycles extend the run."""
    if (
        isinstance(arrival_cycles, bool)
        or not isinstance(arrival_cycles, int)
        or arrival_cycles < 1
    ):
        raise ValueError("arrival cycles must be a positive integer")
    values = (period_seconds, minimum_rate_per_second, peak_rate_per_second)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("periodic schedule values must be finite")
    if period_seconds <= 0:
        raise ValueError("periodic cycle length must be positive")
    duration_seconds = period_seconds * arrival_cycles
    if not math.isfinite(duration_seconds):
        raise ValueError("total periodic duration must be finite")
    if (
        minimum_rate_per_second < 0
        or peak_rate_per_second < minimum_rate_per_second
        or peak_rate_per_second <= 0
    ):
        raise ValueError("periodic rates must satisfy 0 <= minimum <= peak and peak > 0")

    # Draw a homogeneous process at the peak rate, then thin each candidate by
    # the cosine-shaped instantaneous rate. This directly produces timestamps.
    generated: list[tuple[float, float]] = []
    offset = 0.0
    rate_range = peak_rate_per_second - minimum_rate_per_second
    while True:
        offset += generator.expovariate(peak_rate_per_second)
        if offset >= duration_seconds:
            break
        rate = minimum_rate_per_second + rate_range / 2.0 * (
            1.0 - math.cos(2.0 * math.pi * offset / period_seconds)
        )
        if generator.random() <= rate / peak_rate_per_second:
            generated.append((offset, rate))

    return [
        PlannedArrival(
            batch_index=index,
            planned_offset_ns=round(offset * NANOSECONDS_PER_SECOND),
            expected_rate_per_second=rate,
        )
        for index, (offset, rate) in enumerate(generated)
    ]


def prepare_batches(
    arrivals: list[PlannedArrival],
    images: list[Path],
    batch_size_min: int,
    batch_size_max: int,
    generator: random.Random,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> list[PreparedBatch]:
    """Prepare payloads and stable lineage before the timed schedule starts."""
    prepared = []
    for arrival in arrivals:
        batch_size = generator.randint(batch_size_min, batch_size_max)
        selected = select_images(images, batch_size, generator)
        build_started = monotonic_ns()
        payload = build_batch(selected)
        build_duration_ns = monotonic_ns() - build_started
        prepared.append(
            PreparedBatch(
                arrival=arrival,
                endpoint_batch_id=uuid.uuid4().hex,
                payload=payload,
                image_count=len(selected),
                batch_build_duration_ns=build_duration_ns,
            )
        )
    return prepared


def _utc_iso(timestamp_unix_ns: int) -> str:
    return datetime.fromtimestamp(
        timestamp_unix_ns / NANOSECONDS_PER_SECOND, timezone.utc
    ).isoformat()


def emit_planned_schedule(
    prepared: list[PreparedBatch],
    *,
    run_id: str,
    start_wall_ns: int,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    """Record the entire intended schedule before releasing any request."""
    for batch in prepared:
        arrival = batch.arrival
        planned_wall_ns = start_wall_ns + arrival.planned_offset_ns
        emit(
            new_event(
                "schedule.planned",
                component="endpoint",
                run_id=run_id,
                details={
                    "batch_index": arrival.batch_index,
                    "endpoint_batch_id": batch.endpoint_batch_id,
                    "planned_offset_ns": arrival.planned_offset_ns,
                    "planned_timestamp": _utc_iso(planned_wall_ns),
                    "planned_timestamp_unix_ns": planned_wall_ns,
                    "expected_rate_per_second": arrival.expected_rate_per_second,
                    "image_count": batch.image_count,
                    "payload_bytes": len(batch.payload),
                    "batch_build_duration_ns": batch.batch_build_duration_ns,
                },
            )
        )


class SenderMeasurements:
    """Small synchronized counter set for queue and concurrency evidence."""

    def __init__(self, max_concurrency: int = 1):
        self._lock = threading.Lock()
        self.max_concurrency = max_concurrency
        self.submitted = 0
        self.started = 0
        self.active = 0
        self.peak_active = 0
        self.peak_queue_depth = 0

    def submit(self) -> None:
        with self._lock:
            self.submitted += 1
            available_workers = max(0, self.max_concurrency - self.active)
            self.peak_queue_depth = max(
                self.peak_queue_depth,
                0,
                self.submitted - self.started - available_workers,
            )

    def start(self) -> tuple[int, int]:
        with self._lock:
            self.started += 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            return self.active, max(0, self.submitted - self.started)

    def finish(self) -> None:
        with self._lock:
            self.active -= 1


def _send_prepared_batch(
    batch: PreparedBatch,
    *,
    adapter_url: str,
    run_id: str,
    start_monotonic_ns: int,
    start_wall_ns: int,
    measurements: SenderMeasurements,
    emit: Callable[[dict[str, Any]], None],
    send: Callable[[str, bytes, str, str], dict[str, str]],
    monotonic_ns: Callable[[], int],
) -> SendResult:
    active, queue_depth = measurements.start()
    request_started = monotonic_ns()
    actual_monotonic_ns = request_started
    actual_offset_ns = actual_monotonic_ns - start_monotonic_ns
    schedule_lag_ns = actual_offset_ns - batch.arrival.planned_offset_ns
    actual_wall_ns = start_wall_ns + actual_offset_ns
    error = None
    request_id = None
    job_name = None
    try:
        receipt = send(adapter_url, batch.payload, batch.endpoint_batch_id, run_id)
        request_id = receipt["request_id"]
        job_name = receipt["job_name"]
        successful = True
    except Exception as exc:
        error = str(exc)
        successful = False
    finally:
        request_duration_ns = monotonic_ns() - request_started
        measurements.finish()

    common = {
        "batch_index": batch.arrival.batch_index,
        "endpoint_batch_id": batch.endpoint_batch_id,
        "payload_bytes": len(batch.payload),
        "image_count": batch.image_count,
        "batch_build_duration_ns": batch.batch_build_duration_ns,
        "planned_offset_ns": batch.arrival.planned_offset_ns,
        "planned_timestamp_unix_ns": start_wall_ns + batch.arrival.planned_offset_ns,
        "actual_send_offset_ns": actual_offset_ns,
        "actual_send_timestamp": _utc_iso(actual_wall_ns),
        "actual_send_timestamp_unix_ns": actual_wall_ns,
        "schedule_lag_ns": schedule_lag_ns,
        "sender_active_requests": active,
        "sender_queue_depth": queue_depth,
    }
    emit(
        new_event(
            "batch.send_started",
            component="endpoint",
            run_id=run_id,
            details=common,
        )
    )
    if error is not None:
        emit(
            new_event(
                "batch.send_failed",
                component="endpoint",
                run_id=run_id,
                details={
                    **common,
                    "request_duration_ns": request_duration_ns,
                    "error": error,
                },
            )
        )
    else:
        emit(
            new_event(
                "batch.receipt_received",
                component="endpoint",
                run_id=run_id,
                request_id=request_id,
                details={
                    **common,
                    "job_name": job_name,
                    "request_duration_ns": request_duration_ns,
                },
            )
        )
    return SendResult(
        arrival=batch.arrival,
        endpoint_batch_id=batch.endpoint_batch_id,
        actual_offset_ns=actual_offset_ns,
        schedule_lag_ns=schedule_lag_ns,
        successful=successful,
    )


def execute_schedule(
    prepared: list[PreparedBatch],
    *,
    adapter_url: str,
    run_id: str,
    max_concurrency: int,
    start_monotonic_ns: int,
    start_wall_ns: int,
    emit: Callable[[dict[str, Any]], None],
    send: Callable[[str, bytes, str, str], dict[str, str]] = send_batch,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[SendResult], SenderMeasurements]:
    """Release requests by planned time without waiting for earlier responses."""
    measurements = SenderMeasurements(max_concurrency)
    futures = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        for batch in prepared:
            due = start_monotonic_ns + batch.arrival.planned_offset_ns
            delay_ns = due - monotonic_ns()
            if delay_ns > 0:
                sleep(delay_ns / NANOSECONDS_PER_SECOND)
            measurements.submit()
            futures.append(
                executor.submit(
                    _send_prepared_batch,
                    batch,
                    adapter_url=adapter_url,
                    run_id=run_id,
                    start_monotonic_ns=start_monotonic_ns,
                    start_wall_ns=start_wall_ns,
                    measurements=measurements,
                    emit=emit,
                    send=send,
                    monotonic_ns=monotonic_ns,
                )
            )
        results = [future.result() for future in as_completed(futures)]
    return sorted(results, key=lambda item: item.arrival.batch_index), measurements


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[rank]


def build_schedule_summary(
    arrivals: list[PlannedArrival],
    results: list[SendResult],
    *,
    measurements: SenderMeasurements,
) -> dict[str, Any]:
    """Compare offered request starts with the precomputed plan."""
    lags = [result.schedule_lag_ns for result in results]
    on_time = sum(0 <= lag <= FIDELITY_TOLERANCE_NS for lag in lags)
    attempted = len(results)
    on_time_fraction = on_time / attempted if attempted else 0.0
    fidelity_passed = attempted == len(arrivals) and (
        on_time_fraction >= FIDELITY_REQUIRED_FRACTION
    )
    return {
        "planned_count": len(arrivals),
        "attempted_count": attempted,
        "successful_count": sum(result.successful for result in results),
        "failed_count": sum(not result.successful for result in results),
        "on_time_count": on_time,
        "on_time_fraction": on_time_fraction,
        "fidelity_tolerance_ns": FIDELITY_TOLERANCE_NS,
        "fidelity_required_fraction": FIDELITY_REQUIRED_FRACTION,
        "fidelity_passed": fidelity_passed,
        "schedule_lag_p50_ns": round(statistics.median(lags)) if lags else None,
        "schedule_lag_p95_ns": _percentile(lags, 0.95),
        "schedule_lag_max_ns": max(lags) if lags else None,
        "peak_sender_concurrency": measurements.peak_active,
        "peak_sender_queue_depth": measurements.peak_queue_depth,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--adapter-url",
        default=os.getenv("ADAPTER_URL"),
        required=os.getenv("ADAPTER_URL") is None,
    )
    parser.add_argument("--images", type=Path, default=Path(os.getenv("IMAGE_DIR", "/images")))
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ["BATCH_SIZE"]) if "BATCH_SIZE" in os.environ else None,
        help="fixed image count per batch; cannot be combined with a size range",
    )
    parser.add_argument(
        "--batch-size-min",
        type=int,
        default=(int(os.environ["BATCH_SIZE_MIN"]) if "BATCH_SIZE_MIN" in os.environ else None),
    )
    parser.add_argument(
        "--batch-size-max",
        type=int,
        default=(int(os.environ["BATCH_SIZE_MAX"]) if "BATCH_SIZE_MAX" in os.environ else None),
    )
    parser.add_argument(
        "--arrival-pattern",
        choices=("constant", "periodic"),
        default=os.getenv("ARRIVAL_PATTERN", "constant"),
    )
    parser.add_argument("--batches", type=int, default=int(os.getenv("BATCH_COUNT", "1")))
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.getenv("BATCH_INTERVAL_SECONDS", "1")),
    )
    parser.add_argument(
        "--period-seconds",
        type=float,
        default=float(os.getenv("ARRIVAL_PERIOD_SECONDS", "60")),
        help="length of each arrival cycle in seconds (periodic mode)",
    )
    parser.add_argument(
        "--arrival-cycles",
        type=int,
        default=int(os.getenv("ARRIVAL_CYCLES", "1")),
        help="number of arrival cycles; total duration is period times cycles (periodic mode)",
    )
    parser.add_argument(
        "--minimum-rate",
        type=float,
        default=float(os.getenv("MINIMUM_RATE_PER_SECOND", "0.2")),
        help="minimum periodic arrival rate in batches per second",
    )
    parser.add_argument(
        "--peak-rate",
        type=float,
        default=float(os.getenv("PEAK_RATE_PER_SECOND", "1")),
        help="peak periodic arrival rate in batches per second",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("MAX_SENDER_CONCURRENCY", "16")),
    )
    parser.add_argument("--random-seed", type=int, default=int(os.getenv("RANDOM_SEED", "0")))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID") or f"workload-{uuid.uuid4().hex}")
    args = parser.parse_args()
    if "SCHEDULE_DURATION_SECONDS" in os.environ:
        parser.error(
            "SCHEDULE_DURATION_SECONDS was replaced by ARRIVAL_PERIOD_SECONDS "
            "(one cycle's length)"
        )
    return args


def resolve_batch_size_range(args: argparse.Namespace) -> tuple[int, int]:
    """Resolve backwards-compatible fixed or variable batch-size arguments."""
    has_range = args.batch_size_min is not None or args.batch_size_max is not None
    if args.batch_size is not None and has_range:
        raise SystemExit("--batch-size cannot be combined with --batch-size-min/max")
    if args.batch_size is not None:
        minimum = maximum = args.batch_size
    elif has_range:
        if args.batch_size_min is None or args.batch_size_max is None:
            raise SystemExit("both --batch-size-min and --batch-size-max are required")
        minimum, maximum = args.batch_size_min, args.batch_size_max
    else:
        minimum = maximum = 4
    if minimum < 1 or maximum < minimum:
        raise SystemExit("batch-size range must satisfy 1 <= min <= max")
    return minimum, maximum


def main() -> None:
    args = parse_args()
    batch_size_min, batch_size_max = resolve_batch_size_range(args)
    if args.max_concurrency < 1:
        raise SystemExit("maximum sender concurrency must be positive")
    generator = random.Random(args.random_seed)
    try:
        if args.arrival_pattern == "constant":
            arrivals = build_constant_schedule(args.batches, args.interval_seconds)
            profile = {
                "batches": args.batches,
                "interval_seconds": args.interval_seconds,
            }
        else:
            arrivals = build_periodic_schedule(
                period_seconds=args.period_seconds,
                minimum_rate_per_second=args.minimum_rate,
                peak_rate_per_second=args.peak_rate,
                generator=generator,
                arrival_cycles=args.arrival_cycles,
            )
            profile = {
                "period_seconds": args.period_seconds,
                "arrival_cycles": args.arrival_cycles,
                "duration_seconds": args.period_seconds * args.arrival_cycles,
                "minimum_rate_per_second": args.minimum_rate,
                "peak_rate_per_second": args.peak_rate,
            }
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not arrivals:
        raise SystemExit("the configured arrival profile produced no requests")

    images = sorted(
        path
        for path in args.images.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    if not images:
        raise SystemExit(f"no JPEG images found in {args.images}")
    prepared = prepare_batches(arrivals, images, batch_size_min, batch_size_max, generator)
    emit = ThreadSafeEmitter(sys.stdout)

    # Leave enough lead time to flush the full plan before the first release.
    lead_ns = round(max(2.0, len(prepared) * 0.005) * NANOSECONDS_PER_SECOND)
    start_monotonic_ns = time.monotonic_ns() + lead_ns
    start_wall_ns = time.time_ns() + lead_ns
    emit_planned_schedule(prepared, run_id=args.run_id, start_wall_ns=start_wall_ns, emit=emit)
    emit(
        new_event(
            "schedule.ready",
            component="endpoint",
            run_id=args.run_id,
            details={
                "arrival_pattern": args.arrival_pattern,
                "planned_count": len(prepared),
                "schedule_start_timestamp": _utc_iso(start_wall_ns),
                "schedule_start_timestamp_unix_ns": start_wall_ns,
                "random_seed": args.random_seed,
                "batch_size_min": batch_size_min,
                "batch_size_max": batch_size_max,
                "max_concurrency": args.max_concurrency,
                "profile": profile,
            },
        )
    )
    if time.monotonic_ns() >= start_monotonic_ns:
        raise SystemExit("recording the planned schedule exceeded its start lead time")

    results, measurements = execute_schedule(
        prepared,
        adapter_url=args.adapter_url,
        run_id=args.run_id,
        max_concurrency=args.max_concurrency,
        start_monotonic_ns=start_monotonic_ns,
        start_wall_ns=start_wall_ns,
        emit=emit,
    )
    if args.arrival_pattern == "periodic":
        remaining_ns = (
            start_monotonic_ns
            + round(profile["duration_seconds"] * NANOSECONDS_PER_SECOND)
            - time.monotonic_ns()
        )
        if remaining_ns > 0:
            time.sleep(remaining_ns / NANOSECONDS_PER_SECOND)
    summary = build_schedule_summary(
        arrivals,
        results,
        measurements=measurements,
    )
    emit(
        new_event(
            "schedule.summary",
            component="endpoint",
            run_id=args.run_id,
            details=summary,
        )
    )
    if summary["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
