"""Finite image-batch worker; one process maps to one Kubernetes Job."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from events import emit_stream, new_event


def fetch_payload(url: str) -> bytes:
    with urlopen(
        url, timeout=60
    ) as response:  # nosec: URL comes from trusted Job manifest
        return response.read()


def extract_images(payload: bytes, destination: Path) -> list[Path]:
    images: list[Path] = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for index, member in enumerate(archive.getmembers()):
            if not member.isfile() or member.size <= 0:
                raise ValueError("invalid member in trusted adapter payload")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("unable to read image member")
            target = destination / f"{index:04d}{Path(member.name).suffix.lower()}"
            target.write_bytes(source.read())
            images.append(target)
    return images


def classify_checksum(images: list[Path]) -> list[dict[str, Any]]:
    """Deterministic smoke classifier; never used by the Kubernetes manifest."""
    return [
        {"image": image.name, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
        for image in images
    ]


def classify_tflite(
    images: list[Path], model_path: Path, labels_path: Path
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    setup_started = time.monotonic_ns()
    import numpy as np
    from PIL import Image
    import tflite_runtime.interpreter as tflite

    labels = [
        line.strip() for line in labels_path.read_text(encoding="utf-8").splitlines()
    ]
    interpreter = tflite.Interpreter(model_path=str(model_path), num_threads=1)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    height, width = input_details["shape"][1:3]
    floating_model = input_details["dtype"] == np.float32
    classifier_setup_duration_ns = time.monotonic_ns() - setup_started
    output: list[dict[str, Any]] = []
    preprocessing_duration_ns = 0
    inference_duration_ns = 0

    for image_path in images:
        preprocessing_started = time.monotonic_ns()
        with Image.open(image_path) as image:
            pixels = np.expand_dims(
                image.resize((width, height)).convert("RGB"), axis=0
            )
        if floating_model:
            pixels = (np.float32(pixels) - 127.5) / 127.5
        preprocessing_duration_ns += time.monotonic_ns() - preprocessing_started
        inference_started = time.monotonic_ns()
        interpreter.set_tensor(input_details["index"], pixels)
        interpreter.invoke()
        scores = np.squeeze(interpreter.get_tensor(output_details["index"]))
        inference_duration_ns += time.monotonic_ns() - inference_started
        top = scores.argsort()[-5:][::-1]
        scale = 1.0 if floating_model else 255.0
        output.append(
            {
                "image": image_path.name,
                "predictions": [
                    {"label": labels[int(item)], "score": float(scores[item] / scale)}
                    for item in top
                ],
            }
        )
    return output, {
        "classifier_setup_duration_ns": classifier_setup_duration_ns,
        "image_preprocessing_duration_ns": preprocessing_duration_ns,
        "inference_duration_ns": inference_duration_ns,
    }


def put_result(url: str, result: dict[str, Any]) -> dict[str, int]:
    serialization_started = time.monotonic_ns()
    body = json.dumps(result, separators=(",", ":")).encode("utf-8")
    serialization_duration_ns = time.monotonic_ns() - serialization_started
    request = Request(
        url, data=body, method="PUT", headers={"Content-Type": "application/json"}
    )
    request_started = time.monotonic_ns()
    with urlopen(
        request, timeout=60
    ) as response:  # nosec: URL comes from trusted Job manifest
        if response.status != 200:
            raise RuntimeError(f"adapter rejected result with HTTP {response.status}")
    return {
        "result_serialization_duration_ns": serialization_duration_ns,
        "result_request_duration_ns": time.monotonic_ns() - request_started,
        "result_bytes": len(body),
    }


def main() -> None:
    request_id = os.environ["REQUEST_ID"]
    run_id = os.environ["RUN_ID"]
    payload_url = os.environ["PAYLOAD_URL"]
    result_url = os.environ["RESULT_URL"]
    endpoint_batch_id = os.getenv("ENDPOINT_BATCH_ID")
    adapter_accepted_at_unix_ns = os.getenv("ADAPTER_ACCEPTED_AT_UNIX_NS")
    mode = os.getenv("CLASSIFIER_MODE", "tflite")
    started = time.monotonic_ns()
    worker_started_at_unix_ns = time.time_ns()
    emit_stream(
        sys.stdout,
        new_event(
            "job.started",
            component="worker",
            run_id=run_id,
            request_id=request_id,
            details={
                "endpoint_batch_id": endpoint_batch_id,
                "worker_started_at_unix_ns": worker_started_at_unix_ns,
                "adapter_accepted_at_unix_ns": (
                    int(adapter_accepted_at_unix_ns)
                    if adapter_accepted_at_unix_ns is not None
                    else None
                ),
            },
        ),
    )

    fetch_started = time.monotonic_ns()
    payload = fetch_payload(payload_url)
    payload_fetch_duration_ns = time.monotonic_ns() - fetch_started
    with tempfile.TemporaryDirectory() as temporary:
        extraction_started = time.monotonic_ns()
        images = extract_images(payload, Path(temporary))
        extraction_duration_ns = time.monotonic_ns() - extraction_started
        classify_started = time.monotonic_ns()
        if mode == "checksum":
            outputs = classify_checksum(images)
            classifier_timings = {
                "checksum_duration_ns": time.monotonic_ns() - classify_started
            }
        elif mode == "tflite":
            outputs, classifier_timings = classify_tflite(
                images,
                Path(os.getenv("MODEL_PATH", "/model/model.tflite")),
                Path(os.getenv("LABELS_PATH", "/model/labels.txt")),
            )
        else:
            raise ValueError(f"unknown CLASSIFIER_MODE {mode}")
        classify_ns = time.monotonic_ns() - classify_started

    worker_timings_ns = {
        "payload_fetch_duration_ns": payload_fetch_duration_ns,
        "payload_extraction_duration_ns": extraction_duration_ns,
        "classification_duration_ns": classify_ns,
        **classifier_timings,
        "pre_result_duration_ns": time.monotonic_ns() - started,
    }
    result = {
        "schema_version": 1,
        "request_id": request_id,
        "run_id": run_id,
        "endpoint_batch_id": endpoint_batch_id,
        "classifier_mode": mode,
        "worker_started_at_unix_ns": worker_started_at_unix_ns,
        "image_count": len(outputs),
        "payload_bytes": len(payload),
        "classification_duration_ns": classify_ns,
        "job_duration_ns": time.monotonic_ns() - started,
        "worker_timings_ns": worker_timings_ns,
        "outputs": outputs,
    }
    result_timings = put_result(result_url, result)
    total_job_duration_ns = time.monotonic_ns() - started
    emit_stream(
        sys.stdout,
        new_event(
            "job.completed",
            component="worker",
            run_id=run_id,
            request_id=request_id,
            details={
                "image_count": len(outputs),
                "payload_bytes": len(payload),
                "endpoint_batch_id": endpoint_batch_id,
                "worker_timings_ns": {
                    **worker_timings_ns,
                    **result_timings,
                    "total_job_duration_ns": total_job_duration_ns,
                },
            },
        ),
    )


if __name__ == "__main__":
    main()
