"""Endpoint sender for reproducible fixed- or variable-size JPEG batches."""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import tarfile
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from events import emit_stream, new_event


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


def select_images(
    images: list[Path], batch_size: int, generator: random.Random
) -> list[Path]:
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
    adapter_url: str, payload: bytes, endpoint_batch_id: str
) -> dict[str, str]:
    request = Request(
        f"{adapter_url.rstrip('/')}/v1/batches",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-tar",
            "X-Continuum-Batch-ID": endpoint_batch_id,
        },
    )
    with urlopen(request, timeout=60) as response:  # nosec: URL is explicit demo input
        receipt = json.load(response)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--adapter-url",
        default=os.getenv("ADAPTER_URL"),
        required=os.getenv("ADAPTER_URL") is None,
    )
    parser.add_argument(
        "--images", type=Path, default=Path(os.getenv("IMAGE_DIR", "/images"))
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ["BATCH_SIZE"]) if "BATCH_SIZE" in os.environ else None,
        help="fixed image count per batch; cannot be combined with a size range",
    )
    parser.add_argument(
        "--batch-size-min",
        type=int,
        default=(
            int(os.environ["BATCH_SIZE_MIN"])
            if "BATCH_SIZE_MIN" in os.environ
            else None
        ),
    )
    parser.add_argument(
        "--batch-size-max",
        type=int,
        default=(
            int(os.environ["BATCH_SIZE_MAX"])
            if "BATCH_SIZE_MAX" in os.environ
            else None
        ),
    )
    parser.add_argument(
        "--batches", type=int, default=int(os.getenv("BATCH_COUNT", "1"))
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.getenv("BATCH_INTERVAL_SECONDS", "1")),
    )
    parser.add_argument(
        "--random-seed", type=int, default=int(os.getenv("RANDOM_SEED", "0"))
    )
    parser.add_argument("--run-id", default=os.getenv("RUN_ID", "fns-v1-local"))
    return parser.parse_args()


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
    if args.batches < 1 or args.interval_seconds < 0:
        raise SystemExit(
            "batch count must be positive and interval must be non-negative"
        )
    images = sorted(
        path
        for path in args.images.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    if not images:
        raise SystemExit(f"no JPEG images found in {args.images}")

    generator = random.Random(args.random_seed)
    previous_send_started: int | None = None
    for index in range(args.batches):
        cycle_started = time.monotonic_ns()
        batch_size = generator.randint(batch_size_min, batch_size_max)
        selected = select_images(images, batch_size, generator)
        build_started = time.monotonic_ns()
        payload = build_batch(selected)
        build_duration_ns = time.monotonic_ns() - build_started
        endpoint_batch_id = uuid.uuid4().hex
        send_started = time.monotonic_ns()
        send_start_interval_ns = (
            send_started - previous_send_started
            if previous_send_started is not None
            else None
        )
        previous_send_started = send_started
        emit_stream(
            sys.stdout,
            new_event(
                "batch.send_started",
                component="endpoint",
                run_id=args.run_id,
                details={
                    "batch_index": index,
                    "endpoint_batch_id": endpoint_batch_id,
                    "payload_bytes": len(payload),
                    "image_count": len(selected),
                    "batch_build_duration_ns": build_duration_ns,
                    "send_start_interval_ns": send_start_interval_ns,
                    "batch_size_min": batch_size_min,
                    "batch_size_max": batch_size_max,
                    "random_seed": args.random_seed,
                },
            ),
        )
        request_started = time.monotonic_ns()
        try:
            receipt = send_batch(args.adapter_url, payload, endpoint_batch_id)
        except Exception as exc:
            emit_stream(
                sys.stdout,
                new_event(
                    "batch.send_failed",
                    component="endpoint",
                    run_id=args.run_id,
                    details={
                        "batch_index": index,
                        "endpoint_batch_id": endpoint_batch_id,
                        "payload_bytes": len(payload),
                        "image_count": len(selected),
                        "request_duration_ns": time.monotonic_ns() - request_started,
                        "error": str(exc),
                    },
                ),
            )
            raise
        request_duration_ns = time.monotonic_ns() - request_started
        emit_stream(
            sys.stdout,
            new_event(
                "batch.receipt_received",
                component="endpoint",
                run_id=args.run_id,
                request_id=receipt["request_id"],
                details={
                    "batch_index": index,
                    "endpoint_batch_id": endpoint_batch_id,
                    "job_name": receipt["job_name"],
                    "payload_bytes": len(payload),
                    "image_count": len(selected),
                    "batch_build_duration_ns": build_duration_ns,
                    "send_start_interval_ns": send_start_interval_ns,
                    "request_duration_ns": request_duration_ns,
                    "cycle_duration_ns": time.monotonic_ns() - cycle_started,
                },
            ),
        )
        if index + 1 < args.batches:
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
