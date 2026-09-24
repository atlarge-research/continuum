# Image batch demo design

This document records the architectural and experimental reasoning behind the image-batch demo. It complements the short operator-oriented [README](README.md) and preserves decisions that may later be needed for a paper or technical report. It describes the intended design rather than serving as a chronological change log.

## Experimental purpose and boundary

The demo is a scientific vertical slice of an eventual closed-loop digital twin. It must create real endpoint-to-cloud traffic, execute measurable work on Kubernetes, and preserve enough evidence to reconstruct completed work and the cluster state at a chosen cutoff. Later features can use that evidence to forecast workload, prepare OpenDC input, simulate policies, and scale workers.

The current demo observes and forecasts workload, simulates worker-count alternatives, and compares predictions with measurements offline. Faithful live-state initialization and closed-loop scaling remain incomplete. Its purpose is to test modeling assumptions under controlled conditions; reproducible timing and trace correctness take priority over production fault tolerance.

## Component and data flow

```text
endpoint
  |  image archive + workload/run lineage
  v
adapter
  |  accepts request, creates one Job
  v
Kubernetes worker Job
  |  fetches images, runs inference, uploads result
  v
cloud-side result storage

observer sidecar
  |-- Kubernetes Jobs/Pods/Nodes
  |-- Prometheus cAdvisor samples
  `-- completed execution profiles and current cluster state
```

One endpoint batch maps to one finite Kubernetes Job. This boundary makes submission, queueing, execution, completion, and resource evidence directly correlatable. Stable identities preserve lineage across the endpoint, adapter, and cluster.

The adapter acknowledges accepted submissions without waiting for execution; classification results remain cloud-side. The endpoint therefore measures submission behavior rather than Job completion.

## Network emulation

Cellular access uses separate uplink and downlink traces, while cloud-to-cloud, cloud-to-edge, and edge-to-edge communication uses static latency and throughput. Endpoint-to-cloud traffic combines cellular access with the static core profile, including when there is no intervening edge VM. Cellular trace selection and destination location are independent choices. Static 4G/5G presets remain available as alternatives to replay, with manual network overrides preserved.

The inherited location and cellular profiles are accepted inputs from the student's benchmarking work. The [thesis](https://atlarge-research.com/pdfs/2025-gleb-network-simulation-bsc-thesis.pdf#page=35) describes wired client-to-datacenter RTT measurements and estimates one-way core delay as half the RTT, assuming symmetric paths. Deliberately high core throughput and minimal jitter are modeling defaults. These profiles approximate the selected paths rather than establishing universal properties of a region or provider. The demo combines KPN 5G access with the `eu_central_1` core profile.

The demo retains four cloud VMs and one endpoint on one physical host. Endpoint-to-endpoint communication is outside the network model. Trace repetition is independent of workload arrival periods and forecast cycles. Validation of replay behavior does not establish the representativeness of every network profile; unshaped captures remain a distinct baseline.

## Open-loop workload generation

### Why dispatch cannot use one blocking sender

An open-loop workload defines arrival times independently of response times. If request A is planned at zero seconds, request B is planned at five seconds, and A's blocking HTTP call lasts ten seconds, a single sender would incorrectly delay B until ten seconds. The measured workload would then depend on adapter latency and behave like a closed-loop generator.

A scheduler releases planned arrivals to a bounded pool of blocking HTTP senders without waiting for earlier responses. This separates scheduling from submission without requiring custom asynchronous networking. The pool bounds resource use; if every sender is occupied, saturation remains visible through queue depth and scheduling lag. This preserves open-loop behavior within the generator's measured capacity.

### Preparing work before the timed run

Image selection, archive construction, identifier allocation, and structured logging all consume time. Performing them between arrivals would contaminate the schedule. The endpoint therefore prepares payloads and records the full schedule before starting the experiment clock.

The planned schedule and actual send starts use the same monotonic clock for lag calculations. UTC timestamps are also recorded for correlation with other hosts, assuming their clocks are synchronized.

### Continuous low-peak-low process

The periodic workload is a non-homogeneous Poisson process with a continuous cosine-shaped expected rate. For a run of duration `T`, minimum rate `r_min`, and peak rate `r_peak`, the current single-cycle intensity is:

```text
r(t) = r_min + (r_peak - r_min) / 2 * (1 - cos(2*pi*t/T))
```

It starts at the minimum rate, reaches the peak halfway through the run, and returns to the minimum. Candidate arrivals are sampled at the peak rate and accepted with probability `r(t) / r_peak`. This standard thinning construction produces timestamps directly; schedule buckets are not involved.

A seed makes the sampled schedule and image selection reproducible. Batch IDs remain unique rather than being derived from the seed so independently executed runs cannot accidentally share lineage identifiers.

The endpoint records the complete plan, every actual send start and outcome, and a final fidelity summary. Fidelity passes only when every planned request was attempted and at least 95 percent began no more than 250 milliseconds late. A timing miss is reported separately from HTTP submission failures because a workload-fidelity problem and an application failure have different meanings.

### Repeated cycles for forecasting

Forecasting repeats the expected low-peak-low intensity over a longer run to approximate a compressed diurnal pattern. Cycle length and cycle count are explicit: adding cycles extends the run without changing its period or rate bounds. This keeps the period aligned with forecasting and Job execution time. The generator samples one continuous stochastic process over the full duration; it must not copy and paste one cycle's request timestamps.

Changing peak height or cycle length can add realism later, but it is deferred until the complete closed loop works. Beginning with a stable recurring mean separates forecasting or policy errors from unnecessary workload variation.

## Workload duration and network meaning

The calibrated workload uses four images per Job to keep endpoint-to-cloud data volume fixed and interpretable. Fixed and ranged batch-size modes are both retained so later experiments can introduce heterogeneous payloads without a redesign.

The MobileNet workload would otherwise finish too quickly for useful five-second Prometheus sampling. Repeated inference on each preprocessed image extends execution while still returning one classification per image. This increases compute without increasing transferred data, which helps avoid hiding future latency and bandwidth effects behind an arbitrarily larger network payload.

A repetition count of 128 was calibrated specifically on node3 to produce roughly 30--35 seconds of worker execution and several resource samples. It is not a realistic application algorithm or generally meaningful parameter. It is a synthetic experimental load multiplier. A later credible FNS/6G workload or heavier model should replace this mechanism when available.

## Observability model

### Separate completed work from current state

Completed Jobs and unfinished Jobs answer different simulation questions.

- A completed Job has an authoritative execution interval and can be emitted as an OpenDT Task with zero or more resource Fragments.
- A queued or running Job is part of the current cluster state but does not yet have an authoritative duration or complete resource history.

Completed execution profiles and periodic snapshots of unfinished work are separate evidence. Historical work must not be counted twice, and each simulation starts from the latest complete state observation available at its cutoff.

### Kubernetes timing semantics

The relevant timestamps intentionally have different meanings:

- Job creation is Task submission time.
- The worker container's start and finish are the compute execution interval.
- Job completion is authoritative evidence that the outcome was terminal by a trace cutoff.

Kubernetes Job start time can include scheduler queueing. Using it as compute start would inflate execution duration under load, so the observer uses the terminated worker container interval for Task duration. Queueing remains visible through Job creation, Pod state, and the one-second cluster snapshots.

### Prometheus cadence and correlation

Workload resource usage is sampled every five seconds. This provides several observations for a 20--40-second Job without needlessly increasing the entire monitoring stack's load. Other monitoring retains its existing cadence.

Resource metrics identify Pods, while the workload unit is a Job. Correlation therefore uses authoritative Kubernetes ownership rather than delayed monitoring metadata, which can miss the relationship for short-lived Pods.

CPU uses a rate over a short counter window, so the first observation after Pod startup may not yet be calculable. CPU and memory series may also disappear at slightly different times during shutdown. Incomplete observations remain missing rather than becoming invented zero values. Successful completion is retained even when resource sampling is inadequate; sampling quality and execution outcome are separate facts.

Resource observations are timed at their measurement source, separately from collection time, so query delays cannot shift the apparent execution profile.

A completed execution profile must describe a fixed set of accepted observations. Later stale cluster state must not change that profile or add resource evidence after finalization.

### Trace storage and transport boundary

Observer evidence is isolated from application results so that workload measurement does not depend on application logging. Completed execution profiles, raw resource samples, current state, and collection diagnostics remain distinguishable.

A forecast uses a frozen, complete evidence boundary and only observations available by its cutoff. This supports causal reconstruction and reproducibility while keeping retrospective analysis separate. Local audit files are sufficient for the demo; a durable transport between OpenDT components should be introduced only when integration requires it.

## Offline run analysis

Analysis uses saved observations so reporting does not perturb the workload. Submission lag, scheduler/startup delay and classifier execution are measured separately. Resource plots use observed samples rather than simulator-adjusted profiles, preserve missing data and distinguish workload utilization from total node utilization.

Comparisons use the same cohorts, observable windows and scales. Configuration summaries include accuracy, variability and execution cost; chronological examples are chosen independently of prediction quality. Overlapping windows are not independent repetitions, and scenario min–max bands are descriptive ranges rather than confidence intervals.

Reports distinguish illustrative action comparisons from validation against observations. Experimental sections appear only when supporting evidence is available; ordinary runs reuse selected settings. Measured closed-loop performance should lead when it exists. Exact measurements and interpretation caveats remain available alongside the compact presentation.

## Arrival forecasting and calibration

The service has homogeneous computational work and a known recurring period. Only arriving Job counts are predicted; response time may vary with queueing and contention. Poisson regression uses an intercept and sine/cosine features with fixed light regularization. It learns from observed creation times, never the planned schedule, generator rates, or seed. Future counts are sampled per bin, with uniform timestamps within bins. This represents arrival randomness conditional on the fitted model, not full model/parameter uncertainty. No second certainty weight is applied.

First-observation events preserve Job existence independently of terminal status. The reader accumulates these events and historical snapshots, including completed Jobs whose emission was observable by the cutoff. Zero bins require continuous state coverage; bins crossing gaps or incomplete at cutoff are excluded. Readiness requires the configured number of covered observations of every phase bin, an eligible template, and fresh state. Gap tolerance is configurable and evaluated during calibration. Not-ready and fitting failures remain distinct from zero demand.

Calibration selects the adequately sampled completed Job nearest the eligible median execution duration, breaking ties by UID. Its duration, CPU/memory requirements, and full fragment sequence stay together and are frozen. Every future Job copies this profile; only arrival times and counts vary. The template's selection cutoff must also precede each forecast cutoff, even if its selected Job completed earlier. Identical scenarios will be reused for capacity comparisons.

Current-state evidence distinguishes classifier execution from the surrounding Job and Pod lifecycle. A terminated classifier is no longer unfinished compute even if its Pod is still running; missing execution timing remains unknown.

Forecasts must be reproducible from frozen observations, the selected profile, and the sampling seed, with the numerical environment recorded for audit. Exact reproduction assumes the same runtime and CPU; other environments may differ in floating-point results. Overlapping predictive horizons are not independent experimental runs. Scenario count, arrival horizon, and control cadence are separate choices; cadence must account for the cost of OpenDC evaluation.

Capacity alternatives reuse the same observed state and sampled futures so their differences reflect the action rather than different demand. An eventual control loop must account for simulation time and preserve work on workers being removed. Action selection and actuation are outside the current evaluation.

### Simulation input semantics

Every scenario starts from the same observed state and uses one representative measured execution profile. A single fresh snapshot defines the cutoff for backlog, profile eligibility, and forecasting, avoiding a mixture of states from different times. Later observations cannot repair earlier uncertainty. A completed collector observation still approximates cluster state; it is not an atomic observation of every Kubernetes object.

Snapshot cadence and Job membership are separate checks. Arrival events can establish that a Job existed before the cutoff even when the latest snapshot omits it. They do not establish its execution phase, assignment or remaining work. Membership accounting therefore partitions known arrivals into represented backlog (including explicitly exhausted profiles), available completed profiles, observed finished work without an emitted profile, and unresolved state. Unresolved Jobs retain their original creation and observation times; they are never invented as queued tasks. Complete accounting of known arrivals does not prove that every physical Job was observable by the cutoff.

The observer retains finished classifiers and terminal Jobs in a separate inventory, outside queued/running pressure. A classifier may finish before its Job becomes terminal or its measured profile is emitted; excluding it from pressure must not erase that evidence or resurrect its compute. Terminal-state evidence alone is not an eligible training profile or proof of successful Job completion. Provisional traces can remain executable with unresolved membership, but that limitation travels into prepared cases and comparison diagnostics. Historical captures lacking this inventory can expose uncertainty without being repaired using later evidence.

Queued and starting Jobs retain their full execution profile. Starting work occupies its assigned resources, but this version makes no separate estimate of pre-container startup delay. Running work retains only the profile remaining after elapsed classifier execution; scheduler waiting is never subtracted as compute. Remaining execution is `max(0, template_duration - elapsed_classifier_execution)`. An observed-running Job whose modeled profile is exhausted consumes no further simulated capacity. That assumption does not establish observed completion or affect the real Job. More complex execution-duration modeling is outside the demo's scope.

The arrival horizon bounds new arrivals, not execution duration. A fixed observation window measures timely completion; following the same cohort to completion measures its eventual response distribution. These answer different questions. Backlog and future arrivals remain distinguishable, original creation times retain earlier waiting, and unfinished work is explicit. Neither boundary defines a scaling policy or an SLO threshold.

Initial placement and worker availability are part of the simulated state. Assigned work must remain on its worker, including during cordoning, until its modeled execution finishes. Observed allocatable resources are not calibrated application capacity; the planned worker model uses the explicit one-core allowance below. Runner capacity is separate and should be provided by the control plane. A simulation that starts with an empty cluster cannot represent this initial state faithfully.

Retrospective evaluation may use later observations to establish what happened and whether measurement coverage was complete. The experiment end bounds the evaluated arrival period, not when evidence became available; gaps and capture failures still exclude affected intervals. Forecast training and profile selection retain their causal cutoffs.

Node3 calibration uses 0.02–0.30 Jobs/second as a starting profile. Daemon and monitoring reservations leave three whole one-CPU Job slots per worker, and container startup occupies a slot too. Higher average demand can therefore accumulate queues despite the nominal twelve worker vCPUs. Recovery is checked across cycles; stochastic bursts can still carry a queue into the next cycle.

## Direct OpenDC execution boundary

The demo executes a fixed OpenDC version directly to isolate simulator behavior from orchestration. Controlled admission experiments check CPU and memory constraints before the simulator is used with application evidence. Passing these checks establishes an execution path, not faithful reconstruction of a live cluster.

Original observations remain separate from simulator-specific conversions. Reproducibility requires preserving inputs, native outputs and the numerical environment, and checking output validity as well as process success. Actual simulation cost is measured separately from modeled application resource use.

Reports lead with measured execution and arrival-forecast accuracy before simulator comparisons. Their saved numerical payload retains original Job times, worker assignments, snapshot occupancy, CPU coverage and gaps, so physical evidence remains usable without a successful simulation or access to the cluster. Matching arrival plans can support execution-repetition ranges; different workload seeds remain separate runs. Measured workload CPU, observed Kubernetes allocatable capacity and the configured application-capacity model are distinct quantities. Missing samples break plotted lines, and partial sample sums are explicitly marked.

Known-arrival old/new replay comparisons require the same run, cutoff, observed Job identities and observation window. Completion curves share axes; placement changes and response discrepancies remain separate diagnostics. Exhausted work, unmatched backlog and censored outcomes retain their own counts rather than disappearing into a completion error. Repeated Job–cutoff pairs are dependent observations. Forecast scenario ranges describe the sampled futures and are not calibrated confidence intervals; a saved report also retains its chosen scenario seed for offline regeneration.

## Planned worker capacity and runner placement

Model each C-core worker with C - 1 application cores, a deliberate allowance for fractional system reservations. Three four-core workers therefore offer nine one-CPU Job slots. Use the frozen measured application profile. Omit explicit daemon workload and energy overhead while retaining the worker power model's idle baseline.

Prefer the control-plane VM for OpenDC so it does not wait for worker Job slots. Keep application Jobs off the control plane and verify runner headroom there before relying on loop timing. The control plane and runner remain outside simulated worker capacity and energy; no additional worker-core deduction is needed with this placement.

## Provisional scenario workflow

The manual scenario and analysis workflow uses explicitly approximate trace replay of already-running Jobs' remaining work at time zero, retaining observed assignments for the later initialization adapter. These Jobs may move or wait again, so results do not establish faithful live-state predictions. Preserve existing profile, freshness and exhausted-work semantics.

The same sampled futures are used across worker-count candidates. The selected scale-down worker and its assigned Jobs are omitted and retained for later isolated execution; remaining-worker results are explicitly partial. The preliminary evaluation PDF compares a fixed window with following the same included cohort through completion. Revisit its findings with correct placement and complete results before selecting a policy. Scoring and actuation remain later work.

Worker selection prefers an observed-empty eligible worker, otherwise the worker whose most recent current assignment was first observed earliest, with worker identity breaking ties. Starting work and exhausted-but-observed-running Jobs count for selection. Saved captures lack exact assignment timestamps, so first-observed assignment time and left-censoring are retained as approximation evidence rather than replaced with Job creation or classifier start times.

Energy uses cumulative native worker joules, interpolated at evaluation boundaries. Included workers retain their configured idle-power baseline after execution ends; the omitted worker has no assumed power-off time. The illustrative linear defaults are 100 W idle and 200 W maximum, configurable and uncalibrated. Control-plane, runner and separate daemon energy are excluded. Actual runner cost is recorded separately. A fixed window counts only released work as completed or unfinished; arrivals beyond an earlier evaluation boundary remain not-yet-arrived. Backlog response time includes its original waiting time.

## Pinned initialization and native cordon

The optional pinned trace path requests each represented running remainder or starting profile on its observed worker at time zero. Assigned tasks precede ordinary work in the adapted native trace; original source ordering and timestamps remain preserved. Admission checks aggregate CPU and memory on each named worker before execution, because a placement override must not bypass resource fit. Native lifecycle validation then checks initial scheduling, host identity throughout execution, and capacity. This restores placement for represented work, not the entire observed state: startup delay is omitted, exhausted profiles create no allocation, and unresolved membership remains explicit.

Native cordon retains all executable tasks and initial workers. The selected worker finishes its assigned work without admitting queued or future tasks, then closes in the simulator. Selection keeps the same observed-empty/earliest-assignment heuristic as the provisional path. A candidate is unavailable when exhausted work on that worker leaves its drain duration unknown. A complete modeled task inventory still does not establish complete physical observation or validate the scaling counterfactual. Kubernetes cordon alone does not power off a VM.

Closing hosts may stop exporting host telemetry before their final energy interval. Complete cordon accounting therefore uses the native datacenter accumulator for the modeled worker pool, checks its identity, time coverage and configured power bounds, and adds idle energy after completion only for remaining workers. These are consistency checks on an uncalibrated model, not evidence of physical energy accuracy. A disjoint split simulation remains a possible diagnostic oracle if native behavior fails; it is not required for a supported native cordon run.

Compatible action/sample matrices can share one sequential native process. A common topology closes absent reserve hosts immediately; every action retains the same initial task inventory and each sampled future has an explicit identity, even when trace bytes coincide. This optimization requires agreement with individual execution on placement, timing and energy, not merely a successful exit. Shared wall time, CPU and peak memory belong to the whole experiment and cannot be divided into measured per-sample costs. Empty or incompatible matrices retain individual execution. Observation validation accepts unchanged cases only, preventing action variants from being pooled as if they were alternative forecasts of an unchanged observed run.

## Deployment and failure assumptions

Observation remains colocated with the adapter through the October demo, with one observation owner per run. This avoids duplicate collection and the need for coordination between observers.

The experiment assumes the adapter and observer remain healthy for one run. A crash, replacement, update, or loss of observation invalidates the run. Normal server-side watch closure resumes through the Kubernetes client's last resource version while preserving the same observer and sampler; an unrecoverable history error remains fatal. Restarting an invalid experiment preserves interpretable evidence; production fault tolerance is outside this demo's scope.

This is a deliberate scientific-demo trade-off: detecting an invalid run is more important than keeping a partially corrupted run alive.

## Known limitations relevant to interpretation

- Repeated inference produces a useful compute profile but is not realistic application behavior.
- Forecast calibration needs enough covered history across every cycle phase; elapsed warm-up alone is insufficient.
- Observed workload CPU covers the image-batch containers, not all Kubernetes and operating-system activity on each worker.
- The five-second cadence provides samples rather than a continuous ground-truth resource trace.
- Runtime evidence is ephemeral and must be captured before the observing deployment is removed.
- A single adapter replica and no live rollout are operational assumptions, not production scaling behavior.
- Controlled OpenDC execution does not restore initial live state, select policies, or actuate workers; these remain later features.

The current single-host cluster remains the development setup until the closed loop works. A later two-host setup could provide more time for active Jobs to build up before saturation. Capacity and arrival intensity will need to be calibrated together: adding capacity alone could eliminate the queue instead of producing a more informative rise and fall. This expansion is deferred and does not change the current workload or topology.

## Packing and observation validation

Application placement prefers already occupied workers that still have sufficient resources. Packing makes spare capacity visible for later capacity changes, while resource admission and worker eligibility remain mandatory. Real and simulated placement should follow the same principle; measured placement, rather than a scheduler preference alone, establishes whether they agree.

Validation separates three questions. First, replay the observed backlog and known subsequent arrivals to assess the simulator. Second, replace subsequent arrivals with forecasts based only on pre-cutoff evidence to assess the additional forecast error. Third, vary a small set of modeling assumptions while sharing seeds and futures where possible. Fit profiles and choose parameters chronologically, then assess the selected configuration on separate held-out observations.

Every comparison retains initial backlog and fixes the target cohort, cutoffs and evaluation windows. Longer arrival horizons may add competing work without enlarging the scored cohort. Compare completion counts, completed-Job response distributions, scenario variability, empirical coverage and execution cost. Missing snapshot membership, capture gaps, unmatched Jobs, exhausted profiles and unfinished work remain explicit; low average error cannot establish faithful initialization.

Compressed periodic workloads make functional experiments practical, but their horizon-to-cycle ratio and sample size differ from realistic diurnal demand. More training observations can stabilize fitting without removing randomness in a short prediction window. An unchanged observation validates neither scaling counterfactuals nor the uncalibrated power model. Partial scale-down totals cannot establish a winning action.
