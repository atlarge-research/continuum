# Image batch demo application

This application is the first vertical slice for the October 8 FNS demo. It
keeps Continuum's endpoint-to-cloud image traffic, but changes the cloud side
from a long-running MQTT subscriber into one finite Kubernetes Job per batch.

```text
endpoint -- image tar --> adapter -- creates --> Kubernetes Job
                              ^                      |
                              |-- cloud-side result--|
```

The endpoint receives only an HTTP `202` receipt containing a request ID and
Job name. Classification output remains in the adapter data directory.

## Contracts

- `POST /v1/batches` accepts an uncompressed tar containing JPEG files.
- `GET /v1/batches/{request_id}/payload` is used by the Job.
- `PUT /v1/batches/{request_id}/result` records the Job result cloud-side.
- `GET /v1/batches/{request_id}` is an operator/debug endpoint.
- `GET /v1/metrics` reports live adapter concurrency and aggregate stage timings.
- The adapter writes append-only events to `events.jsonl`.
- The worker writes compatible JSON events to stdout.
- Jobs carry `continuum.atlarge.nl/request-id` and
  `continuum.atlarge.nl/workload=image-batch` labels.
- Completed Jobs are retained for `JOB_TTL_SECONDS` (default: one hour), so a
  later OpenDT observer can consume terminal Job and resource evidence.

## Local vertical-slice smoke run

The local submitter runs the worker as a child process with a deterministic
checksum classifier. This validates endpoint, payload, receipt, worker, result,
and event contracts without requiring Kubernetes or TensorFlow Lite.

```bash
python3 application/image_batch/src/adapter.py \
  --submitter local --data-dir /tmp/fns-image-batch
```

In a second terminal:

```bash
python3 application/image_batch/src/endpoint.py \
  --adapter-url http://127.0.0.1:8080 \
  --images application/image_classification/src/images \
  --batch-size-min 2 --batch-size-max 10 \
  --batches 20 --interval-seconds 1 --random-seed 42
```

The endpoint chooses a new uniformly distributed batch size and a fresh image
selection for every send. `--random-seed` makes the choices reproducible. Use
the backwards-compatible `--batch-size 4` option when a fixed size is desired;
fixed and ranged size options cannot be combined. The sender remains
synchronous in version 1, so the actual start-to-start interval is the request
duration plus `--interval-seconds`. The emitted timing fields make that
limitation measurable before an open-loop sender is introduced.

Inspect cloud-side state with the printed request ID:

```bash
curl http://127.0.0.1:8080/v1/batches/REQUEST_ID
curl http://127.0.0.1:8080/v1/metrics
tail -f /tmp/fns-image-batch/events.jsonl
```

## Measurement contract

Every event contains an ISO timestamp and `timestamp_unix_ns`. Durations ending
in `_duration_ns` use a monotonic clock and are safe for measuring a stage
within one process. Wall-clock timestamps correlate events between endpoint,
adapter, and workers, but cross-host latency differences require synchronized
VM clocks. `endpoint_batch_id` joins the endpoint send to the adapter request;
the adapter-generated `request_id` joins storage, Job, and worker evidence.

The emitted measurements separate:

- endpoint payload construction, request/receipt latency, and complete cycle;
- adapter body read, validation, storage, Kubernetes submission, and active
  request concurrency;
- adapter payload reads and response writes for concurrent workers;
- worker payload fetch, extraction, classifier setup, image preprocessing,
  inference, result serialization/upload, and total Job execution;
- adapter result-body read, JSON parsing, and result storage.

`GET /v1/metrics` exposes count, total, maximum, and average values for adapter
measurements plus current and peak active requests. Detailed per-batch evidence
remains in JSONL and worker logs. Job annotations retain image count and payload
size so later queue/resource observations can be related to workload size.

## Kubernetes deployment

Build the three images from the repository root. The worker Dockerfile reuses
the existing pinned MobileNet model and labels.

```bash
docker build -f application/image_batch/docker/adapter.Dockerfile \
  -t continuum/image-batch-adapter:fns-v1 .
docker build -f application/image_batch/docker/worker.Dockerfile \
  -t continuum/image-batch-worker:fns-v1 .
docker build -f application/image_batch/docker/endpoint.Dockerfile \
  -t continuum/image-batch-endpoint:fns-v1 .
kubectl apply -f application/image_batch/manifests/adapter.yaml
```

The manifest exposes the adapter on node port `30080`. The endpoint container
must receive `ADAPTER_URL=http://<cloud-node-ip>:30080`; that traffic is the
path to route through MahiMahi when trace replay is enabled.

The image names are deliberately local placeholders for version 1. Before a
recorded run, pin registry digests and record them in `provenance.yaml`.

## Current boundary

This slice does not yet import OpenDT/OpenDC. It intentionally produces the
native terminal Kubernetes Jobs that Edward's observer already understands.
MahiMahi assets are also not included in Gleb's Continuum commit, so trace
replay remains a separate gated step.
