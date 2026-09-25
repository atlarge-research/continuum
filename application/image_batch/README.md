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

From the repository root, generate a PDF from those files:

```bash
python3 -m venv /tmp/fns-analysis-venv
/tmp/fns-analysis-venv/bin/pip install -r application/image_batch/requirements-analysis.txt
export PYTHONPATH="$PWD/application/image_batch/src"
/tmp/fns-analysis-venv/bin/python -m reporting.analyzer \
  --endpoint-log ./endpoint.jsonl --observer-dir ./opendt-audit \
  --output-dir ./logs/image-batch-report
```

Open `logs/image-batch-report/report.pdf`. Repeat `--endpoint-log` to compare captured runs, or add `--run-id ID` to select one. The report preserves separate run distributions; different arrival plans are not aligned by batch index. Numerical CSVs, summaries and a self-contained `metrics.json` accompany the PDF.

To preserve complete measured series for later combined reports, run `/tmp/fns-analysis-venv/bin/python -m reporting.measured --endpoint-log CAPTURE/endpoint.jsonl --observer-dir CAPTURE/observer --output NEW_MEASURED.json` using the analysis environment and `PYTHONPATH` above. Repeat `--endpoint-log` for execution repetitions. Pass the saved payload to `/tmp/fns-analysis-venv/bin/python -m reporting.assembly --metrics NEW_MEASURED.json --output-dir NEW_REPORT`; additional `--metrics` files can supply saved `forecast-report.json`, simulator or combined evidence. The new report retains all plotted numbers in `metrics.json` for offline regeneration. Combined and standalone commands use the same topic-oriented landscape style. Supply only the evidence sections available; study selection and held-out roles come from explicit study metadata. Optional supplementary evidence adds causal forecast illustrations and matched scenario-seed sensitivity. See the [current report and reproduction evidence](OPENDT_HANDOFF.md#reports-and-preserved-evidence).

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

For the updated FNS-demo source-build compatibility experiment, build a separate image:

```bash
docker build -f application/image_batch/docker/opendc.Dockerfile \
  --build-arg OPENDC_COMMIT=cf10c06eb73c7e60e1076e376922b1201caf12d1 \
  --build-arg OPENDC_SOURCE_SHA256=b60208e517037eaeae10f5ef32f36716bda5500de9c9a89f4e8cfc240f5ccb25 \
  --build-arg OPENDC_RUNTIME=fns-demo \
  -t continuum/opendc:fns-cf10c06 .
OPENDC_RUNTIME=fns-demo python3 application/image_batch/src/opendc_run.py prepare \
  --fixture memory --output-dir /tmp/fns-memory-inputs
```

Use new output directories and the matching image when running those inputs. Host-side preparation defaults to the preserved engine; `OPENDC_RUNTIME=fns-demo` selects the new topology/trace contract. Manifests record the engine separately from [Dante's example](https://github.com/atlarge-research/FNS-demo), pinned at `41aaa9e20a4e299329924454316e6c91eb39f42f`. The example supplies no updated runtime JARs or engine source pin, so this source build does not establish equivalence to the developer's unavailable binary.

For assigned-task placement and native cordon, add `--initialization-mode pinned-trace` when preparing scenarios or observation-validation inputs with `OPENDC_RUNTIME=fns-demo`. Run those inputs with the matching FNS image. Results distinguish validated task placement from the remaining startup-delay, exhausted-work and observation gaps.

Compatible pinned suites can run in one native process using `python /app/opendc_native_batch.py --suite-dir /inputs --output-dir /results/batch` inside the matching FNS image (override its default entrypoint). Mount the prepared suite read-only and a new results directory writable, retaining the usual runner resource limits. The resulting `batch.json` works with the action evaluator. Shared process cost is reported once; empty or incompatible suites retain individual execution.

## Manual provisional scenario workflow

Prepare scenarios with `opendc_scenarios.py prepare`, run them with `opendc_batch.py`, then generate an action report:

```bash
python3 application/image_batch/src/opendc_evaluate.py \
  --batch-dir ./logs/scenarios-one-cluster --output-dir ./logs/scenarios-one-report
```

Each command provides `--help`; the [handoff](OPENDT_HANDOFF.md#manual-run-reference) gives the preparation and execution commands. To redraw saved action results, replace `--batch-dir` with `--metrics-file ./logs/scenarios-one-report/metrics.json`.

For the combined action and forecast-validation PDF:

```bash
PYTHONPATH=application/image_batch/src /tmp/fns-analysis-venv/bin/python -m reporting.assembly \
  --metrics SAVED_REPORT/metrics.json --split validation \
  --output-dir NEW_REPORT_DIRECTORY
```

Open `NEW_REPORT_DIRECTORY/report.pdf`; plotted comparison values are in `comparison.json`. Repeat `--metrics` to combine saved evidence. Omit `--split validation` to include all supplied validation runs; use `--forecast-seed` to choose a scenario seed. Only sections with supplied evidence are included.

## Observation validation

Use `opendc_validation.py prepare` for replay inputs and `evaluate` for measured comparisons. Follow the [recorded experiment commands](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md) to reproduce the historical chronological validation and held-out evaluation. That provisional study retains partial scale-down accounting. The optional pinned path uses native cordon with complete represented-work accounting; both remain manual experiments with approximate initialization and uncalibrated energy assumptions.

For independent validation workload runs, use `opendc_study.py --metrics RUN_A.json --metrics RUN_B.json --output NEW_SELECTION.json` to freeze an equally weighted configuration choice. Each metrics file must identify its distinct `workload_seed`. Preserve that selection before held-out execution and restrict the held-out preparation index's `forecast_counts` to the selected count.

For a controlled physical cordon or reserve-admission capture, `opendc_intervention.py --intervention CAPTURE/intervention.json --final-pods CAPTURE/pods-final.json --output NEW_VERDICT.json` checks preserved placement and drain evidence. It reports API-boundary ambiguities explicitly; a successful API command alone is insufficient.

Append controlled-action validation to the main PDF with `/tmp/fns-analysis-venv/bin/python -m reporting.assembly --metrics MAIN_METRICS.json --metrics CONTROLLED_METRICS.json --output-dir NEW_REPORT`. The controlled input can be an individual comparison or a saved controlled report's `metrics.json`; the combined payload redraws offline through the same command. Validation pages appear last and show worker assignments, completion counts, start/runtime errors, per-Job responses and detailed arrival/wait/execution timelines against the action actually observed. Different workloads remain separate. The standalone `/tmp/fns-analysis-venv/bin/python -m reporting.controlled --comparison COMPARISON.json --output-dir NEW_REPORT` entry point remains available.
