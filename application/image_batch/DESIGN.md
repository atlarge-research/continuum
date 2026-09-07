# Image batch demo design

This document records the architectural and experimental reasoning behind the image-batch demo. It complements the short operator-oriented [README](README.md) and preserves decisions that may later be needed for a paper or technical report. It describes the intended design rather than serving as a chronological change log.

## Experimental purpose and boundary

The demo is a scientific vertical slice of an eventual closed-loop digital twin. It must create real endpoint-to-cloud traffic, execute measurable work on Kubernetes, and preserve enough evidence to reconstruct completed work and the cluster state at a chosen cutoff. Later features can use that evidence to forecast workload, prepare OpenDC input, simulate policies, and scale workers.

This implementation deliberately stops before forecasting, OpenDC execution, policy selection, and Kubernetes actuation. It is designed for a controlled demo run rather than production operation. Reproducible timing and trace correctness are important; transparent recovery from infrastructure failures is not.

## Component and data flow

```text
endpoint
  |  image archive + workload/run lineage
  v
adapter
  |  persists request, creates one Job
  v
Kubernetes worker Job
  |  fetches images, runs inference, uploads result
  v
adapter data directory

observer sidecar
  |-- Kubernetes Jobs/Pods/Nodes
  |-- Prometheus cAdvisor samples
  `-- OpenDT and cluster-state JSONL
```

One endpoint batch maps to one finite Kubernetes Job. This boundary makes submission, queueing, execution, completion, and resource evidence directly correlatable. The endpoint batch ID, adapter request ID, workload run ID, Kubernetes Job UID, Pod UID, and worker name preserve lineage through the pipeline.

The adapter returns an HTTP `202` after accepting and submitting the request; classification results remain cloud-side. The endpoint therefore measures submission behavior rather than waiting for Job completion.

## Open-loop workload generation

### Why dispatch cannot use one blocking sender

An open-loop workload defines arrival times independently of response times. If request A is planned at zero seconds, request B is planned at five seconds, and A's blocking HTTP call lasts ten seconds, a single sender would incorrectly delay B until ten seconds. The measured workload would then depend on adapter latency and behave like a closed-loop generator.

The endpoint instead has one scheduler and a bounded pool of ordinary blocking HTTP senders. At each planned time the scheduler releases the prepared request without waiting for earlier responses. Slow responses affect future arrivals only if all sender slots are occupied; that saturation is recorded as queue depth and scheduling lag. A bounded standard-library pool is sufficient and avoids custom asynchronous networking code.

### Preparing work before the timed run

Image selection, archive construction, identifier allocation, and structured logging all consume time. Performing them between arrivals would contaminate the schedule. The endpoint therefore constructs every payload and emits every `schedule.planned` record before starting the experiment clock.

The planned schedule and actual send starts use the same monotonic clock for lag calculations. UTC timestamps are also recorded for correlation with other hosts, assuming their clocks are synchronized.

### Continuous low-peak-low process

The periodic workload is a non-homogeneous Poisson process with a continuous cosine-shaped expected rate. For a run of duration `T`, minimum rate `r_min`, and peak rate `r_peak`, the current single-cycle intensity is:

```text
r(t) = r_min + (r_peak - r_min) / 2 * (1 - cos(2*pi*t/T))
```

It starts at the minimum rate, reaches the peak halfway through the run, and returns to the minimum. Candidate arrivals are sampled at the peak rate and accepted with probability `r(t) / r_peak`. This standard thinning construction produces timestamps directly; schedule buckets are not involved.

A seed makes the sampled schedule and image selection reproducible. Batch IDs remain unique rather than being derived from the seed so independently executed runs cannot accidentally share lineage identifiers.

The endpoint records the complete plan, every actual send start and outcome, and a final fidelity summary. Fidelity passes only when every planned request was attempted and at least 95 percent began no more than 250 milliseconds late. A timing miss is reported separately from HTTP submission failures because a workload-fidelity problem and an application failure have different meanings.

### Future repeated cycles

A later forecasting experiment may repeat the expected low-peak-low intensity over a longer run to approximate a compressed diurnal pattern. It should add a cycle-count parameter to the continuous rate function and sample one stochastic process over the full duration. It must not copy and paste one cycle's request timestamps: repeated expected intensity plus independently sampled arrivals provides predictability without making every cycle identical.

Changing peak height or cycle length can add realism later, but it is deferred until the complete closed loop works. Beginning with a stable recurring mean separates forecasting or policy errors from unnecessary workload variation.

## Workload duration and network meaning

The October invocation uses four images per Job to keep endpoint-to-cloud data volume fixed and interpretable. Fixed and ranged batch-size modes are both retained so later experiments can introduce heterogeneous payloads without a redesign.

The MobileNet workload would otherwise finish too quickly for useful five-second Prometheus sampling. `INFERENCE_REPETITIONS` repeats model invocation on each already-preprocessed image while still returning one classification per image. This increases compute without increasing transferred data, which helps avoid hiding future latency and bandwidth effects behind an arbitrarily larger network payload.

The manifest value of 128 was calibrated specifically on node3 to produce roughly 30--35 seconds of worker execution and several resource samples. It is not a realistic application algorithm or generally meaningful parameter. It is a synthetic experimental load multiplier. A later credible FNS/6G workload or heavier model should replace this mechanism when available.

## Observability model

### Separate completed work from current state

Completed Jobs and unfinished Jobs answer different simulation questions.

- A completed Job has an authoritative execution interval and can be emitted as an OpenDT Task with zero or more resource Fragments.
- A queued or running Job is part of the current cluster state but does not yet have an authoritative duration or complete resource history.

The observer therefore writes completed Tasks to `workload.jsonl` and periodic full snapshots of non-terminal Jobs and worker capacity to `cluster-state.jsonl`. A future OpenDC reader can deduplicate completed records and combine them with the last complete state snapshot at or before a fixed trace cutoff.

### Kubernetes timing semantics

The relevant timestamps intentionally have different meanings:

- Job creation is Task submission time.
- The worker container's start and finish are the compute execution interval.
- Job completion is authoritative evidence that the outcome was terminal by a trace cutoff.

Kubernetes Job start time can include scheduler queueing. Using it as compute start would inflate execution duration under load, so the observer uses the terminated worker container interval for Task duration. Queueing remains visible through Job creation, Pod state, and the one-second cluster snapshots.

### Prometheus cadence and correlation

Only the kubelet cAdvisor endpoint is changed to a five-second scrape interval with a one-second timeout. Other monitoring targets retain their existing cadence. This provides several observations for a 20--40-second Job without needlessly increasing the entire monitoring stack's load.

cAdvisor identifies resource series by Pod but does not provide sufficiently timely Job ownership for these short-lived Pods. Rather than depending on a slower `kube_pod_owner` metric, the observer lists Pods through the Kubernetes API and follows their owner references to Job UIDs. This is the authoritative relationship used to associate CPU and memory samples with Jobs.

CPU uses a rate over a short counter window, so the first observation after Pod startup may not yet be calculable. CPU and memory series may also disappear at slightly different times during shutdown. The observer diagnoses and skips an incomplete combination instead of inventing a zero value. A successfully completed Job is still emitted with `fragments: []` and degraded sampling metadata if no valid samples exist.

Resource collection uses cAdvisor's source timestamp rather than the observer's query time for Fragment ordering and deduplication. Query time is retained as separate provenance.

### Trace storage and transport boundary

The observer sidecar owns a dedicated `emptyDir` mounted at `/var/lib/opendt`; it never uses the adapter's `/data` directory. Every JSONL record is appended as one flushed, newline-terminated object so a reader can consume only complete lines.

The files are ephemeral diagnostic and audit evidence:

- `workload.jsonl` contains completed Task/Fragment records.
- `resource-snapshots.jsonl` contains accepted raw Job samples.
- `cluster-state.jsonl` contains complete current-state snapshots.
- `observer-events.jsonl` contains failures and degraded observations.

JSONL is not intended as the permanent transport between separate OpenDT components. A later bounded reader may select complete lines up to a fixed file boundary, filter by authoritative completion time, deduplicate by Job UID, and generate OpenDC Parquet input. Kafka or a direct API should be introduced only when there is a concrete integration requirement.

## Offline run analysis

The analyzer reads saved endpoint and observer evidence independently of the runtime. A command-line script producing PNGs and a combined PDF keeps the demo reproducible and easy to review or use in slides, without a notebook or browser service. Input hashes, analysis settings, and exported values allow regeneration and inspection; invalid inputs fail explicitly, while incomplete evidence remains visible.

Arrival fidelity uses recorded monotonic send offsets, because endpoint log timestamps are written after the HTTP call returns. Cross-host alignment assumes synchronized clocks. Queue wait includes scheduling and container startup; execution uses worker-container start and finish. These distinctions avoid attributing startup or logging delays to computation or workload scheduling.

CPU plots use raw resource samples rather than simulator-oriented OpenDT Fragments, which may clamp or extend utilization. Samples are held forward for at most ten seconds within execution; missing values remain missing, and partial sums are distinguished from full coverage. This shows workload CPU and sampling coverage, not total node utilization or a direct reporting-latency measurement. Terminal Pods are excluded from pressure using captured Pod phases, including in older captures; corrections are documented without rewriting source logs.

Repetitions are compared only when their planned schedules match. Pressure curves show the median and observed range over their common captured interval, leaving gaps for missing state; the range is not a confidence interval. CPU traces remain individual. An execution timeline cannot meaningfully be averaged, so the report shows the first complete run alongside per-batch queue waits from all repetitions. Common distribution bins make runs comparable without repeating every figure. Detailed measurement conventions and evidence caveats belong in the generated report.

## Deployment and failure assumptions

The observer remains a sidecar in the adapter pod through the October demo. The Deployment has one replica because multiple adapter replicas would create duplicate observers without leader election.

The experiment assumes the adapter and sidecars remain healthy for one run. A container crash, Pod replacement, Deployment update, or fatal Job watch error invalidates the run; the operator stops and restarts the complete experiment. Accordingly, the implementation does not add persistent deduplication, watch reconnection, restart recovery, leader election, a PVC, or a generic sink framework.

This is a deliberate scientific-demo trade-off: detecting an invalid run is more important than keeping a partially corrupted run alive.

## Known limitations relevant to interpretation

- Repeated inference produces a useful compute profile but is not realistic application behavior.
- The current schedule contains one expected low-peak-low cycle; forecasting experiments may later require several stochastic cycles.
- Observed workload CPU covers the image-batch containers, not all Kubernetes and operating-system activity on each worker.
- The five-second cadence provides samples rather than a continuous ground-truth resource trace.
- JSONL and in-memory Job UID deduplication survive only for the lifetime of the current pod.
- A single adapter replica and no live rollout are operational assumptions, not production scaling behavior.
- Network trace replay, workload forecasting, OpenDC conversion/execution, policy selection, and worker actuation remain later features.

The current single-host cluster remains the development setup until the closed loop works. A later two-host setup could provide more time for active Jobs to build up before saturation. Capacity and arrival intensity will need to be calibrated together: adding capacity alone could eliminate the queue instead of producing a more informative rise and fall. This expansion is deferred and does not change the current workload or topology.
