# Image batch demo

Run image-classification Jobs on Kubernetes, capture their workload and resource use, forecast arrivals, and compare OpenDC simulations with observations. Results stay cloud-side. The demo supports manual simulation and evaluation; automatic scaling is not connected.

Run commands from the repository root with Python 3.10+. Use new output directories to preserve previous results. See [DESIGN](DESIGN.md) for scientific reasoning and [HANDOFF](OPENDT_HANDOFF.md) for deployment details, current evidence and continuation notes.

## Local smoke run

Start a local adapter with a lightweight checksum worker; no cluster or inference model is needed:

```bash
python3 -m pip install -r application/image_batch/requirements-adapter.txt
python3 application/image_batch/src/adapter.py \
  --submitter local --data-dir /tmp/fns-image-batch
```

In a second terminal, send one seeded workload cycle:

```bash
python3 application/image_batch/src/endpoint.py \
  --adapter-url http://127.0.0.1:8080 \
  --images application/image_classification/src/images \
  --batch-size 4 --arrival-pattern periodic --period-seconds 60 \
  --minimum-rate 0.2 --peak-rate 1 --max-concurrency 16 --random-seed 42
```

The endpoint prints request receipts and a final schedule summary. Inspect a request using its printed ID:

```bash
curl http://127.0.0.1:8080/v1/batches/REQUEST_ID
curl http://127.0.0.1:8080/v1/metrics
```

## Kubernetes demo deployment

Use `configuration/fns_demo_v1.cfg` with Continuum's [provisioning instructions](../../README.md). It provisions one endpoint, a Kubernetes control plane and three workers. Before deployment, follow the [cluster setup notes](OPENDT_HANDOFF.md#cluster-setup-reference) to load images, enable worker packing and check network replay.

Build the application images:

```bash
docker build -f application/image_batch/docker/adapter.Dockerfile -t continuum/image-batch-adapter:fns-v1 .
docker build -f application/image_batch/docker/worker.Dockerfile -t continuum/image-batch-worker:fns-v1 .
docker build -f application/image_batch/docker/endpoint.Dockerfile -t continuum/image-batch-endpoint:fns-v1 .
```

With Kubernetes and monitoring ready:

```bash
python3 application/image_batch/src/configure_cadvisor_scrape.py
kubectl apply -f application/image_batch/manifests/adapter.yaml
```

Run the endpoint against `http://<cloud-node-ip>:30080`. Keep the calibrated four-image batches and 128 inference repetitions. Use 120-second cycles for functional checks and 240-second cycles for evaluation, with `--arrival-cycles 6 --minimum-rate 0.02 --peak-rate 0.30`. Keep the adapter at one replica and restart the experiment if it or the observer crashes or is replaced.

## Save observations and generate a run report

Save the endpoint's stdout as `endpoint.jsonl`. Copy the observer files before removing its Pod:

```bash
kubectl cp -n fns-demo \
  -c opendt-observer image-batch-adapter-POD:/var/lib/opendt ./opendt-audit
```

Generate a PDF from those files:

```bash
python3 -m venv /tmp/fns-analysis-venv
/tmp/fns-analysis-venv/bin/pip install -r application/image_batch/requirements-analysis.txt
/tmp/fns-analysis-venv/bin/python application/image_batch/src/analyze_run.py \
  --endpoint-log ./endpoint.jsonl --observer-dir ./opendt-audit \
  --output-dir ./logs/image-batch-report
```

Open `logs/image-batch-report/report.pdf`. Repeat `--endpoint-log` to compare runs with matching planned arrivals, or add `--run-id ID` to select one.

## Arrival forecasting

Install the forecasting dependencies and generate a forecast plus simulation inputs:

```bash
python3 -m venv /tmp/fns-forecast-venv
/tmp/fns-forecast-venv/bin/pip install -r application/image_batch/requirements-forecast.txt
/tmp/fns-forecast-venv/bin/python application/image_batch/src/forecast_workload.py \
  --observer-dir ./opendt-audit --run-id WORKLOAD_RUN_ID --period-seconds 240 \
  --phase-origin ORIGIN_UTC --cutoff CUTOFF_UTC \
  --horizon-seconds 60 --scenarios 10 --simulation-inputs \
  --output-dir ./logs/forecast-one
```

Match `--period-seconds` to the workload. Set `ORIGIN_UTC` from the endpoint's `schedule.ready.details.schedule_start_timestamp`; `CUTOFF_UTC` is the forecast time. Check `forecast.json` and `simulation/manifest.json` for readiness. Ready forecasts contain sampled arrivals and simulator input bundles. For repeated forecasts, replace `--cutoff` with `--interval-seconds 10` and use live observer files.

## Direct controlled OpenDC execution

Build the pinned simulator image:

```bash
docker build -f application/image_batch/docker/opendc.Dockerfile \
  -t continuum/opendc:master-7db7e1a2331fd .
```

The [controlled-run instructions](OPENDT_HANDOFF.md#controlled-opendc-run-reference) cover an empty-cluster smoke test and the optional Kubernetes integration test. To simulate captured workload, use the workflow below.

## Manual provisional scenario workflow

Prepare scenarios with `opendc_scenarios.py prepare`, run them with `opendc_batch.py`, then generate an action report:

```bash
python3 application/image_batch/src/opendc_evaluate.py \
  --batch-dir ./logs/scenarios-one-cluster --output-dir ./logs/scenarios-one-report
```

Each command provides `--help`; the [handoff](OPENDT_HANDOFF.md#manual-run-reference) gives the preparation and execution commands. To redraw saved action results, replace `--batch-dir` with `--metrics-file ./logs/scenarios-one-report/metrics.json`.

For the combined action and forecast-validation PDF:

```bash
python3 application/image_batch/src/opendc_report.py \
  --metrics SAVED_REPORT/metrics.json --split validation \
  --output-dir NEW_REPORT_DIRECTORY
```

Open `NEW_REPORT_DIRECTORY/report.pdf`; plotted comparison values are in `comparison.json`. Repeat `--metrics` to combine saved evidence. Omit `--split validation` to include all supplied validation runs; use `--forecast-seed` to choose a scenario seed. Only sections with supplied evidence are included.

## Observation validation

Use `opendc_validation.py prepare` for replay inputs and `evaluate` for measured comparisons. Follow the [recorded experiment commands](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md) to reproduce the chronological validation and held-out evaluation. This remains a manual experiment with approximate initialization, partial scale-down accounting and uncalibrated energy assumptions.
