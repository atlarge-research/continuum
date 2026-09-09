# Image batch demo application

This application is the first endpoint-to-cloud vertical slice for the October 8 FNS demo. The endpoint sends a batch of images to an adapter, the adapter creates one finite Kubernetes Job, and the Job returns its classifications to the adapter. An observer sidecar records completed workload and live cluster state for later OpenDT/OpenDC use.

```text
endpoint -- image tar --> adapter -- creates --> Kubernetes Job
                              ^                      |
                              |-- cloud-side result--|
                              |
                        observer sidecar
                     -- watches Jobs --> OpenDT JSONL
```

See [DESIGN.md](DESIGN.md) for the reasoning behind the workload schedule, sender concurrency, synthetic inference duration, and observer data model.

## HTTP and data contracts

- `POST /v1/batches` accepts an uncompressed tar containing JPEG files and returns an HTTP `202` receipt with a request ID and Job name.
- `GET /v1/batches/{request_id}/payload` serves the stored batch to its Job.
- `PUT /v1/batches/{request_id}/result` stores the Job result cloud-side.
- `GET /v1/batches/{request_id}` exposes request state for debugging.
- `GET /v1/metrics` exposes live adapter concurrency and aggregate timings.
- The adapter writes application lineage and timing to `/data/events.jsonl`.
- The observer writes its own ephemeral JSONL files under `/var/lib/opendt` and has no access to the adapter's `/data` directory.

## Local smoke run

The local submitter runs the worker as a child process with a deterministic checksum classifier. It validates the endpoint, payload, receipt, worker, result, and event contracts without a cluster or TensorFlow Lite.

Use Python 3.10+ and install `requirements-adapter.txt` first. The Kubernetes client package is required; the checksum run needs no cluster or worker packages.

Start the adapter:

```bash
python3 application/image_batch/src/adapter.py \
  --submitter local --data-dir /tmp/fns-image-batch
```

In a second terminal, run one seeded low-peak-low arrival cycle:

```bash
python3 application/image_batch/src/endpoint.py \
  --adapter-url http://127.0.0.1:8080 \
  --images application/image_classification/src/images \
  --batch-size 4 --arrival-pattern periodic \
  --period-seconds 60 \
  --minimum-rate 0.2 --peak-rate 1 \
  --max-concurrency 16 --random-seed 42
```

The endpoint prepares the complete schedule and all payloads before the timed run. It emits `schedule.planned` records, starts HTTP submissions through a bounded sender pool, and finishes with `schedule.summary`. The pool prevents a slow blocking HTTP response from shifting later open-loop arrivals unless all senders are occupied.

The October invocation fixes the batch at four images. Use `--batch-size-min` and `--batch-size-max` instead when heterogeneous batch sizes are required. For a constant-rate smoke run, omit `--arrival-pattern periodic` and use `--batches` with `--interval-seconds`.

Inspect a request with the ID printed by the endpoint:

```bash
curl http://127.0.0.1:8080/v1/batches/REQUEST_ID
curl http://127.0.0.1:8080/v1/metrics
tail -f /tmp/fns-image-batch/events.jsonl
```

## Kubernetes demo deployment

`configuration/fns_demo_v1.cfg` provisions one two-vCPU endpoint, one four-vCPU Kubernetes control plane, and three four-vCPU workers. CPU pinning assigns 18 distinct host CPUs.

Build the images from the repository root:

```bash
docker build -f application/image_batch/docker/adapter.Dockerfile \
  -t continuum/image-batch-adapter:fns-v1 .
docker build -f application/image_batch/docker/worker.Dockerfile \
  -t continuum/image-batch-worker:fns-v1 .
docker build -f application/image_batch/docker/endpoint.Dockerfile \
  -t continuum/image-batch-endpoint:fns-v1 .
```

When updating an existing cluster, preserve its calibrated `WORKER_IMAGE` setting and verify loaded image IDs. Use a new adapter/observer tag rather than reusing a cached tag.

After Kubernetes and its monitoring stack are available, configure cAdvisor sampling and deploy the adapter and observer:

```bash
python3 application/image_batch/src/configure_cadvisor_scrape.py
kubectl apply -f application/image_batch/manifests/adapter.yaml
```

The cAdvisor setup changes only that scrape endpoint to a five-second interval with a one-second timeout and verifies the result. The adapter Deployment must remain at one replica and must not be scaled or updated during a run. If the adapter or observer is replaced or crashes, stop and restart the complete demo.

The manifest's `WORKER_INFERENCE_REPETITIONS=128` setting is a deliberately synthetic, node3-calibrated load multiplier. It keeps the four-image network payload fixed while producing roughly 30--35 seconds of compute for useful sampling; 128 repeated inferences should not be interpreted as realistic application behavior. Use one repetition for a basic smoke test.

The adapter is exposed on node port `30080`. Configure the endpoint with `ADAPTER_URL=http://<cloud-node-ip>:30080`.

## Observer output

The observer continuously flushes four audit streams in its dedicated `emptyDir`:

- `workload.jsonl`: completed OpenDT-compatible Tasks and Fragments.
- `resource-snapshots.jsonl`: accepted per-Job CPU and memory samples.
- `cluster-state.jsonl`: queued/running Jobs and worker availability.
- `observer-events.jsonl`: first-observed Job arrivals, emission times, failures, and collection diagnostics.

Copy them after a run:

```bash
kubectl cp -n fns-demo \
  -c opendt-observer image-batch-adapter-POD:/var/lib/opendt ./opendt-audit
```

The endpoint audit stream is structured stdout and should be captured from its container logs. The adapter result and events remain under its `/data` mount.

These JSONL files are ephemeral experiment evidence, not a durable transport between OpenDT components. Forecasting consumes bounded prefixes; OpenDC execution, policy selection, actuation, and MahiMahi remain separate phases.

## Offline run report

Generate a report from saved endpoint and observer logs using Python 3.10+:

```bash
python3 -m venv /tmp/fns-analysis-venv
/tmp/fns-analysis-venv/bin/pip install -r application/image_batch/requirements-analysis.txt
/tmp/fns-analysis-venv/bin/python application/image_batch/src/analyze_run.py \
  --endpoint-log ./endpoint.jsonl \
  --observer-dir ./opendt-audit \
  --output-dir ./logs/image-batch-report
```

`--endpoint-log` is the endpoint's captured stdout; `--observer-dir` contains the four streams copied above. Repeat `--endpoint-log` to compare runs with matching planned arrivals, or use `--run-id ID` to select one. Choose a new output directory.

Open `logs/image-batch-report/report.pdf` in VS Code or a desktop PDF reader.

## Arrival forecasting

Forecasting reads observer logs and produces future arrival scenarios as OpenDC-compatible Parquet files. Use Python 3.10+:

```bash
python3 -m venv /tmp/fns-forecast-venv
/tmp/fns-forecast-venv/bin/pip install -r application/image_batch/requirements-forecast.txt
/tmp/fns-forecast-venv/bin/python application/image_batch/src/forecast_workload.py \
  --observer-dir ./opendt-audit --run-id WORKLOAD_RUN_ID --period-seconds 120 \
  --phase-origin ORIGIN_UTC --cutoff CUTOFF_UTC --output-dir ./logs/forecast-one
```

Set `ORIGIN_UTC` to the endpoint's `schedule.ready.details.schedule_start_timestamp` and `CUTOFF_UTC` to the UTC forecast time. Choose a new output directory; `forecast.json` reports readiness.

For calibration, start the endpoint with `--period-seconds 120 --arrival-cycles 6 --minimum-rate 0.02 --peak-rate 0.30`. Keep endpoint and forecast periods equal.

For periodic forecasts, replace `--cutoff CUTOFF_UTC` with `--interval-seconds 10` and read live observer files.

Use `evaluate_forecasts.py` to score saved forecasts, or add forecast pages with `analyze_run.py`. Their `--help` lists the required inputs; specify the arrival-run end to exclude shutdown time.

See [DESIGN.md](DESIGN.md#arrival-forecasting-and-calibration) for model and calibration decisions, and `forecast_workload.py --help` for other options.
