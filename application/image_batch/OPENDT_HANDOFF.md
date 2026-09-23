# OpenDT handoff

## Where to resume

The accepted compact report now has a repository entry point, [opendc_report.py](src/opendc_report.py), which combines optional action pages from `opendc_evaluate.py` and forecast-comparison pages from `opendc_report_validation.py`. Review the [regenerated four-page PDF](../../logs/fns-provisional/packing-validation-20260921/report-source-20260923/report.pdf). The existing validation evaluator uses the same composition layer. The temporary report renderer and README have been removed from the report logs; rendering needs only repository code and saved metrics. See [README](README.md#manual-provisional-scenario-workflow) for usage and [DESIGN](DESIGN.md) for the optional-section and shared-window conventions. The user reviewed this milestone and authorized committing and pushing it on 2026-09-24; use Git for its final revision.

Final review removed the obsolete `report_phases()` helper and the optional `_plot_input_comparison()` renderer, their dedicated tests, and the latter's CLI option and endpoint override. The compact report still has five tests for optional sections, split/seed selection, shared windows, missing values and input preservation. All 202 remaining image-batch tests pass, including the socket-dependent HTTP test. Pinned Black passes; Pylint on this final cleanup reports only the existing test-class method-count finding (21/20), with no errors or warnings. The evaluator no longer exceeds the module-size limit; observation evaluation's five previously reviewed refactor findings remain accepted. The four-page PDF was regenerated separately and matches the approved pages pixel for pixel and its numerical comparison exactly. See [final review verification](../../logs/fns-provisional/packing-validation-20260921/document-scope-20260924/VALIDATION.md) and the [preceding cleanup verification](../../logs/fns-provisional/packing-validation-20260921/report-cleanup-20260923/VALIDATION.md).

[AGENTS.md](../../AGENTS.md) now defines documentation audiences: README provides concise run instructions, DESIGN explains scientific/system reasoning, and this handoff carries implementation and continuation detail. Deployment and advanced execution material moved into the reference sections below; per-run results remain in experiment evidence. User review is complete; commit and push are authorized.

These report follow-ups remain future work, outside this commit's PDF scope:

- Repeated-seed configuration evaluation remains future work. The compact comparison currently uses six usable, overlapping windows from capture A, not six independent runs. Compare all candidates over a shared pool of workload seeds; the renderer does not yet pool multiple runs.
- The opening action illustration uses three futures, while the saved forecast choice uses ten. Eventually replace that opening illustration with actual closed-loop results generated with the chosen settings; do not present the current illustration as that evidence.
- The shared renderer currently supports action and forecast-validation sections. Add a leading closed-loop performance section when its measurements exist. Ordinary runs should reuse configured settings rather than automatically repeat configuration experiments.

The packing and observation-validation milestone is implemented and measured as one reviewed change on `codex/fns-2026-10-08`, based on `f3c52dac5a01102633bf73bd8fe47e785f8244cd`. Review the [original milestone evaluation PDF](../../logs/fns-provisional/packing-validation-20260921/evaluation/report.pdf), [findings](../../logs/fns-provisional/packing-validation-20260921/FINDINGS.md), [numerical summary](../../logs/fns-provisional/packing-validation-20260921/evaluation/summary.csv) and [reproduction commands](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md). All 592 matrix cases and nine illustrative action cases succeeded; the original milestone's 199-test suite passed before report integration. The user authorized committing and pushing this milestone on 2026-09-24.

Application Jobs now select the existing scheduler's `fns-packing` profile with CPU MostAllocated; live tests measured packing, CPU/memory fit and control-plane runner isolation. OpenDC's existing fitting-host policy already packs, and four configured cores remain three modeled cores. Evaluation uses 240-second cycles; functional checks use 120 seconds. H60/N10 was selected on A before capture B. Held-out completion-curve MAE is 0.785 Jobs with forecasts versus 0.190 with known arrivals; paired replay response MAE is 2.007 seconds. The [findings](../../logs/fns-provisional/packing-validation-20260921/FINDINGS.md) distinguish matched cohorts, two A coverage exclusions, four snapshot-membership omissions, exhausted work and censoring. These are compressed-cycle demo results, not a general calibration claim.

The likely next commit integrates the OpenDC lead's updated implementation. Verify its actual initialization/job-pinning and scale-down APIs, then repeat the preserved known-arrival comparisons before drawing conclusions from forecasts. Current running remainders still restart without restored placement/startup occupancy; partial scale-down and uncalibrated power remain unresolved. Snapshot/event timing also leaves four observed backlog Jobs absent from their cutoff snapshots, including two whose arrival events were already available; treat observation/reconstruction alignment as a targeted follow-up. Do not repeat broad lint cleanup or introduce an action policy.

### Soon-following commit: rebuild with current Kubernetes

Upgrade Kubernetes through Continuum's offline provisioning in a separate future commit, not through an in-place upgrade of the running 1.27.16 cluster. Update the relevant Ansible installation files and compatible Kubernetes, container-runtime, networking and monitoring packages, then provision a fresh cluster and debug/validate the complete deployment. Preserve current captures, logs, images and source artifacts before rebuilding. Revalidate application timing, observation metrics, worker packing, resource admission and control-plane runner isolation against the new stack. The inspected `pr-23-curated` branch still targets Kubernetes 1.27 and is not an already-validated upgrade source. Keep this work separate from the upcoming OpenDC integration and from the current measurement milestone.

The user-accepted [simplified three-page PDF](../../logs/fns-provisional/report-polish-20260921/final/report.pdf) remains the historical presentation baseline. The current milestone combines packing with [all three validation stages](#next-milestone-validate-the-twin-against-observations), superseding older wording that treated scheduling as separate. Verify the branch and preserve subsequent working-tree changes before resuming. Earlier reports and captures remain in their original locations.

The branch-wide formatting and lint cleanup is complete and approved by the user; see [the cleanup report](LINT_CLEANUP.md). The manual provisional scenario workflow below is implemented, including the agreed worker-capacity and control-plane runner placement. Review its validation evidence before proceeding to faithful initialization or complete scale-down accounting. Do not repeat the branch-wide lint pass.

Simulator inputs and direct controlled OpenDC execution are implemented. The execution milestone precedes assigned-work integration and bypasses OpenDT entirely: use `opendc_run.py` and the container built from pinned upstream master commit `7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad`. It retains synthetic empty-state fixtures and now accepts separately prepared `opendc-provisional-v1` experiments. Raw live simulation bundles are still rejected. Provisional replay retains placement evidence but deliberately does not restore placement or startup occupancy.

The pinned OpenDC revision lacks initial-state restoration. The lead's forthcoming update is expected to provide relevant placement and scale-down features, but it has not been integrated or validated here. Continue to label the current initialization provisional; evaluation-window decisions do not depend on that integration.

The manual `opendc_scenarios.py` → `opendc_batch.py` → `opendc_evaluate.py` path implements the worker-capacity and control-plane decisions below. Historical synthetic fixtures and validation evidence remain intact; explicit legacy worker-hosted fixture execution remains supported.

The [worker-packing decision](#scheduling-decision-prefer-worker-packing) is implemented and verified by the current milestone. The original demo's data/source were archived before its adapter image was refreshed, and a real calibrated Job completed with the packing profile. Kubernetes remains at 1.27.16; the deferred offline upgrade above is separate work.

The entry point is [forecast_workload.py](src/forecast_workload.py) with `--simulation-inputs`; [simulation_input.py](src/simulation_input.py) builds the shared initial state and combined scenarios. Use the [README](README.md#arrival-forecasting) for invocation and [DESIGN](DESIGN.md#simulation-input-semantics) for modeling decisions. Scope and delivery priorities remain in the [Notion demo task](https://app.notion.com/p/374dc985c5868055a157df2a6d95f1bb).

## Formatting and lint cleanup completed

The cleanup covers all 52 surviving Python files changed since recorded branch creation at `39022508131df910a2a92562e5528d234b34a7c9`, plus one new registry regression. The starting workspace was clean at reviewed commit `f47b36a39b01dcca8fcf83d3f6c282aca07bdab6`. See [LINT_CLEANUP.md](LINT_CLEANUP.md) for the scope rationale, actual tool versions, full finding-type counts, narrow exceptions and saved validation evidence.

Black 22.12.0 checks pass at 100 characters. With the user's version allowance, Pylint 3.3.9 replaced 2.15.8 after the latter crashed on existing code. Final Pylint has no errors or fatal findings; 468 reviewed convention/refactoring/warning messages remain, so the strict lint gate still exits nonzero. No broad rule changes or metric-driven refactors were made. The small behavioral fix gives unsupported Kubernetes image versions an explicit ValueError instead of undefined-variable failure.

All 141 image-batch tests pass. Infrastructure discovery passes 27 tests and skips four existing opt-in checks. The new registry regression reproduced the old failure before the fix. The diff and executable AST changes received independent review and the user approved the cleanup for commit and push. Existing evidence and the packaging simplifications remain intact; no VM, deployment or workload changes were made.

Pre-commit verification also corrected a test-only process-disappearance race in the timeout regression. The process suite passed five consecutive runs and the full image-batch suite passed afterward; production process cleanup behavior is unchanged.

The remaining lint findings are accepted for the demo; no further lint milestone is planned. During future implementation, improve documentation when touching functions whose input contracts, modeling assumptions or failure behavior need clarification. Investigate new correctness-related lint findings and concrete test failures as they arise, and run regressions appropriate to each change. These are ongoing development practices, not prerequisites before the next feature; the persistent rules are in [AGENTS.md](../../AGENTS.md).

The persistent [repository agent rule](../../AGENTS.md) applies Black, Pylint and useful docstrings to future Python changes. Routine tasks check their changed files; this completed milestone deliberately covered the broader branch. Documentation-only and read-only work do not trigger formatting changes. Markdown paragraphs remain unwrapped.

## Evidence and OpenDT compatibility

| Demo evidence | Source | OpenDT use |
| --- | --- | --- |
| Request/demo/workload-run lineage | Job labels and annotations | State/run lineage |
| Submission/start/finish | Job metadata and worker-container state | Task timing |
| Requested CPU/memory | Job Pod specification | Task capacity |
| Observed CPU usage | Prometheus/container metrics | Task fragments |
| Image count and payload bytes | Job annotations and adapter JSONL | Explanatory workload metadata |
| Endpoint batch ID | Endpoint/adapter events and Job annotation | Pre-adapter request correlation |
| Queued/starting/running Jobs and worker state | Kubernetes Jobs, Pods, and Nodes | Simulation initial state at cutoff |
| Classification result | Adapter `result.json` only | Proof of real work; not simulator input |

Adapter events preserve application lineage; resource observations come from the observer. The observer's completed-work contract follows upstream commit `c3e1f8cd56918d8c10c4013a8b8733011323f9d7`, specifically the Task/Fragment models and Kubernetes workload producer. [opendt_observer.py](src/opendt_observer.py) captures classifier timing independently of Job/Pod scheduling state. Preserve that distinction when connecting the runner; scheduler waiting is not execution time.

## Controlled runner operation

Use the [controlled-run reference](#controlled-opendc-run-reference) for the container and isolated integration test. `opendc_run.py prepare` writes source/adapted traces, topology, fixture expectations and provenance; `run` writes `execution.json`, `resources.json`, logs and native simulator output. Always choose new directories. Inspect both the process exit and output validation; OpenDC exit zero alone is insufficient.

`opendc_kubernetes.py manifest` renders one Job for a preloaded image and pre-created node-local directory. Stage inputs under `REMOTE/inputs` and create `REMOTE/results` owned by UID/GID 1000 with mode 0755; `REMOTE` must be a unique `/var/tmp/fns-opendc-NAME`. Apply the rendered Job in a dedicated namespace. After the Job reaches Complete or Failed, `collect` verifies its source and copies artifacts over SSH into a new local directory. Inspect `collection.json` before deleting the Job or remote directory. Failed collection leaves the source intact. The opt-in integration test implements this full sequence and saves commands, manifests and cleanup evidence.

The Dockerfile and Python requirements define build pins; execution manifests record the OpenDC commit and runtime versions without a separate version JSON file. The pinned SDK trace loader still divides memory by 1,000, so the memory adaptation remains necessary; revalidate it before each upgrade. The new upstream CLI is `opendc --strict run`; it no longer emits `trackr.json`. Use the resolved experiment, execution manifest and native Parquet records for provenance and validation. Prepare fresh controlled inputs after a version change. Docker scratch mounts must allow executable mappings for the upstream compression library. A successful controlled run proves direct execution and its artifact path; it does not prove live-state initialization, forecast validity or a working closed loop.

## Follow-up: worker capacity and control-plane runner

These decisions are implemented by the provisional workflow and remain its modeling and validation contract. The controlled fixture and historical evidence remain intact. No VM resizing is required.

1. Convert each configured C-core worker VM into a C - 1 core OpenDC host. Four cores become three, eight become seven; three current workers give nine one-CPU application slots. Retain configured and modeled counts plus the one-core rule in provenance. Apply the deduction once, without additionally subtracting system Pod requests or observed utilization. Reject a modeled topology that needs work on a worker with no positive application capacity. Automated per-Pod capacity accounting is not required.
2. Omit daemon/observability workload and separate daemon energy overhead. The deducted core is a capacity allowance, not a continuously running task. Preserve the configured worker idle-power baseline; label outputs as simplified modeled worker energy. Exclude the control plane and runner from simulated topology and energy, while continuing to collect actual runner CPU, memory and time separately.
3. Use the frozen representative application profile and its measured fragments for scenario inputs, preserving one-CPU requests. Do not replace it with the artificial ten-second fixture or assume constant full utilization. Keep the twelve-slot synthetic fixture as a regression test and validate the nine-slot application model separately.
4. Inspect current control-plane labels, taints, allocatable resources, existing Pod requests and observed CPU/memory load. The saved master-validation snapshot identifies cloudcontrollermatthijs with four CPUs and a node-role.kubernetes.io/control-plane:NoSchedule taint; it does not establish current headroom. Verify that one runner with one-CPU/two-GiB requests and limits and a one-GiB heap cap can coexist with control-plane services. Run candidates sequentially.
5. Target the control plane through a required node selector or affinity and give only the OpenDC application Pod a toleration for the matching control-plane taint. Keep that taint in place; retain or add worker-only placement constraints to generated application Jobs and check they have no broad toleration allowing control-plane placement. Keep scheduler resource checks active rather than binding with nodeName. See Kubernetes guidance on [taints and tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) and [node selection](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/).
6. Adapt manifests, exact-image staging, node-local input/output paths, SSH collection and identity verification for the control-plane host. Continue excluding the control plane from worker state and scaling candidates. With OpenDC there, subtract no extra runner core from any modeled worker. Do not silently fall back to workers. If worker placement is chosen later, reserve one additional core on that worker in both Kubernetes and the model; use a capacity deduction rather than a synthetic runner Job in the trace.
7. Validate in isolation that OpenDC starts and completes while application worker slots are full, application Jobs remain off the control plane, and API responsiveness and runner CPU/memory stay acceptable. Record scheduling delay separately from simulation duration. Verify success, failure, evidence retrieval and cleanup on the new host. This placement removes competition for worker Job slots; headroom and shared-host contention still require measurement before claiming reliable loop timing.

Use [DESIGN](DESIGN.md#planned-worker-capacity-and-runner-placement) for the rationale. This follow-up does not require fixed initial placement from the OpenDC developer, and it does not itself add automatic forecasting execution or actuation.

## Scheduling decision: prefer worker packing

Agreed with the user on 2026-09-21: prefer packing application Jobs onto already allocated eligible workers over spreading them evenly across workers. This supports node scale-down by making whole workers available to stop after their assigned work finishes. For example, six one-CPU Jobs on three workers with three application slots each can occupy workers as 3/3/0 instead of 2/2/2, retaining the same application concurrency while leaving one worker empty.

Prefer configuring the existing Kubernetes scheduler's `NodeResourcesFit` plugin with the `MostAllocated` scoring strategy; replacing the scheduler is not required for this preference. It scores allocated resource requests, not instantaneous CPU utilization, and combines with other scheduling scores and constraints. Inspect the deployed Kubernetes version and scheduler configuration before choosing exact settings and weights. Preserve resource-fit checks, worker-only application placement, the control-plane runner isolation and the agreed C - 1 worker-capacity model. See [Kubernetes resource bin packing](https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/).

Packing is a placement preference, not the scaling decision itself. The future scaling controller still decides when extra capacity is needed. For scale-down, stop assigning new Jobs to the selected worker, allow its existing Jobs to finish without migration or eviction, then stop or remove the worker when eligible. Packing does not itself move existing Jobs or power off empty workers; an idle or cordoned worker still contributes idle energy while it remains on.

Align OpenDC's placement behavior for queued Jobs and future arrivals with the Kubernetes packing preference, and validate the effective behavior using the same workload, starting state and sampled futures. Check that packing creates empty workers when capacity permits, added workers accept work when needed, and a worker selected for scale-down receives no new Jobs while finishing its assigned work. Retain measured resource headroom and assess response times alongside worker occupancy. Until placement behavior is aligned and initial-state restoration is supported, label any simulation-to-cluster scheduling mismatch explicitly. Provisional initialization and partial scale-down accounting remain limitations; this decision does not make those results faithful live predictions.

Status: the scheduling preference is agreed and recorded; no scheduler or cluster change is made by this documentation update. Implementation and experiments remain follow-up work, with no new automatic actuation, scoring policy or SLO thresholds introduced here.

## Next milestone: provisional scenario workflow

The manually invoked path now covers scenario preparation, OpenDC execution, verified result collection and a preliminary evaluation PDF, using the worker-capacity and runner-placement decisions above. Keep initialization and the isolated scale-down component replaceable; reuse the surrounding workflow when supported placement becomes available. Do not add automatic forecasting execution, scoring thresholds or actuation in this step.

1. Prefer an explicit provisional trace mode: release already-running Jobs' remaining profiles at time zero without enforcing their observed worker assignments. Include queued/starting work and sampled future arrivals, preserving existing profile semantics. Retain assignments, phases, identities, original arrival times and source traces in evidence. Empty-state fixtures remain available for simpler checks; they are not the only permitted interim experiments.
2. Record the initialization mode in manifests and reports. Trace replay does not restore startup occupancy or prevent already-running Jobs from waiting again or moving to different workers, including an added worker. Treat results as provisional modeling experiments, not validated live predictions. Never silently fall back from requested fixed placement to this approximation.
3. Use the same sampled futures for unchanged, scale-up and scale-down simulated topologies. Select a scale-down candidate using the heuristic below. For now, omit that worker and its assigned starting/running Jobs from the main simulation, retaining an inventory of omitted Jobs and profiles for the later isolated simulation. Keep all unassigned queued work and future arrivals in the main simulation.
4. Report scale-down output as the remaining workers' component only. The omitted worker's completion and energy results are unavailable, not zero. Do not migrate its assigned Jobs, invent their completion, or compare partial totals as if they covered the same whole-cluster work. Add the isolated execution and result combination later.
5. Produce the preliminary evaluation-window PDF from small synthetic or explicitly approximate replay experiments. Use consistent modeled scope when comparing window strategies, label missing components, and revisit findings after supported initialization and complete scale-down accounting are available.

When adding replay of schema-2 bundles, retain the readiness, freshness and exhausted-profile rules below. Bundle readiness confirms input completeness, not fidelity of provisional initialization. Keep the existing representative workload profile, Poisson generation, three-second freshness default and physical topology unchanged. The provisional workflow validation is recorded separately from the historical controlled-execution reports below.

## Future live-state runner input contract

Any future schema-2 replay, including the provisional mode above, must consume bundles only when `simulation/manifest.json` reports `ready`. The runner rejects raw bundles; `opendc_scenarios.py prepare` validates and adapts ready bundles into the explicit provisional contract. The manifest is written last; its absence means an incomplete export. Not-ready manifests list rejection reasons and have no executable scenario export. The table below describes the target responsibilities with supported initialization; provisional mode retains assignment evidence but does not enforce placement, and temporarily retains the selected worker's component without executing it.

| Artifact under `simulation/` | Runner responsibility |
| --- | --- |
| `manifest.json` | Read requested/effective cutoffs, horizon, readiness, provenance, Job UID mapping, and per-scenario future lineage. |
| `initial-state.json`: `workers` | Preserve worker identities and capacities. For the selected scale-down candidate, partition its assigned work into the isolated simulation and exclude that worker from the simulations receiving queued work and future arrivals. |
| `initial-state.json`: `tasks` | Restore each `{task, metadata}` entry using its phase, worker assignment, resource requests, and queue order. Queue only unassigned work. |
| `initial-state.json`: `model_exhausted_jobs` | Retain as evidence only. These observed-running Jobs have zero modeled execution left; allocate no capacity and invent no completion record. |
| `scenarios/NNNN/tasks.parquet` and `fragments.parquet` | Execute the shared remaining backlog plus that scenario's sampled future. Tables use the existing non-nullable Task/Fragment schema. |

Task IDs join the traces to lineage. Submission times are milliseconds relative to the effective cutoff; backlog releases at zero. Original creation times remain in metadata, so simulated completion can later be related to original arrival. All scenarios share the same initial work and worker state. Future arrivals stop at the horizon; included execution is not truncated there.

The effective cutoff is the latest complete snapshot at or before the requested cutoff, subject to `--max-gap-seconds` (default three seconds). Unknown running timing, conflicting state, or missing assigned workers blocks readiness. `model_exhausted_jobs` retains `task_id`, original lineage/timing, `template_duration_ms`, `remaining_execution_ms: 0`, and `observed_completed: false`; the manifest adds a `running_profile_exhausted` diagnostic. This assumption never changes real Job state.

For reproducible replay, retain the observer files, `boundaries.json`, and `template.json`; pass the latter two through `--boundaries` and `--template`. Source hashes and dependency versions identify the implementation/runtime used. History, original state, and arrival-only traces remain outside `simulation/` for audit and comparison.

## Remaining closed-loop work

The provisional workflow and first PDF can proceed before the following initialization and full scale-down work. These remain requirements for faithful live-state evaluation.

1. Implement correct initial placement with the OpenDC developer's help. Already-running Jobs must resume their remaining profiles on their observed workers, with resources occupied before ordinary scheduling begins. Queued Jobs and sampled future arrivals remain subject to normal scheduling. A submission time of zero alone does not identify an already-running Job. Verify unchanged-worker-count and scale-up cases, including that existing Jobs cannot move onto an added worker. Preserve assigned/starting Job distinctions and the existing exhausted-profile treatment.
2. Replace the provisional first-observed assignment proxy with authoritative assignment timing when available. The implemented deterministic selection chooses one scale-down candidate per observed cutoff. Prefer an empty eligible worker; otherwise choose the worker whose most recent Job assignment is oldest. This is the initial common-duration heuristic for selecting the worker expected to finish its assigned work soonest. Include starting Jobs when identifying recent assignments and use worker identity to break ties.
3. Evaluate scale-down using separate simulations. For each sampled future, simulate the remaining workers with their assigned work, all unassigned queued work, and that future's arrivals. Separately simulate the selected worker with only its assigned remaining work and no future arrivals. Run that isolated simulation once per cutoff and reuse its output across the scale-down scenarios. Preserve initial placement in both components.
4. Combine component results using the same time origin and evaluation boundaries. Keep task identities disjoint and retain each Job exactly once per combined scenario. Sum additive quantities such as energy and completion counts; compute response-time distributions and percentiles from the combined task records rather than averaging component summaries. Explicitly define energy accounting after the selected worker finishes; cordoning alone does not imply that the machine is powered off.
5. Revisit the preliminary PDF once initialization and complete candidate simulations are available. Review the effects before selecting the demo's evaluation policy. Then connect candidate selection and actuation.

Use the same sampled futures across unchanged, scale-up and scale-down candidates. Keep the current workload and physical topology. The split simulation assumes the selected worker's remaining execution does not contend with the other workers through resources represented in the model.

## Evaluation approach review

Exported simulator records provide the technical basis for choosing evaluation windows. Window selection, unfinished-Job treatment and post-horizon arrivals are deferred project decisions, not prerequisites awaiting another answer from the OpenDC developer.

The implemented preliminary PDF compares the fixed evaluation window and cohort-through-completion approaches using the same starting inputs and sampled arrivals. Post-horizon arrival sensitivity remains deferred. Begin with small synthetic or explicitly approximate replay experiments; revisit with faithfully initialized observed states later. The fixed window reports unfinished work; the cohort view follows included work through completion. Extending arrivals beyond the evaluation boundary remains a possible later sensitivity check. Keep the evaluation boundary separate from the arrival-generation horizon.

Keep cumulative energy, completed and unfinished work, and response-time metrics, with arrival and evaluation boundaries recorded. The simplified PDF plots energy and completed work only, retaining unfinished counts in JSON; it adds an overall response curve with future/backlog companions. Explain which Jobs, workers and time intervals each metric includes. Explicitly distinguish omitted Jobs from simulated unfinished Jobs, and label initialization approximations. Examine candidate preference only when results cover comparable complete work and energy accounting; partial scale-down output cannot establish a preferred candidate. Select a practical, defensible approach for the demo after review; do not introduce a scoring policy or SLO thresholds beforehand.

The user agreed to the three-stage validation direction below. Retain the observed backlog in every competing model configuration. The current synthetic inputs alone do not validate parameter quality, and incomplete scale-down accounting cannot establish full-system action preference.

## Next milestone: validate the twin against observations

The three stages below record the agreed method implemented by the packing/validation milestone linked above. They remain the method for assessing the forthcoming OpenDC changes: establish where prediction error comes from before building the automatic closed loop. Successful native execution or visually plausible synthetic curves alone are not evidence of predictive accuracy.

### 1. Simulation versus observations

Start by auditing existing captures for matching forecast cutoffs, initial Job/worker state, subsequent arrivals and observed completions. Begin with the unchanged action, for which a real unchanged run can provide outcomes. Replay the observed backlog and subsequently observed arrivals through OpenDC, retaining the existing workload/profile and recording the simulator, capacity and scheduling configuration. This is a retrospective diagnostic using known arrivals, not a forecast; label it accordingly. It removes arrival-forecast error from the comparison while exposing runtime, remainder, scheduling and initialization discrepancies.

Compare simulated and observed cumulative completions and response distributions for the same Jobs and time windows. Include overall modeled-Job response with backlog/future breakdowns. Match Jobs by saved lineage and preserve original creation times. Record capture gaps, unmatched Jobs, model-exhausted work and unfinished observations explicitly; do not silently drop them or report them as zero. Check whether the capture continues long enough to observe the chosen cohort's completion. If not, use an explicit observation window and identify censored responses, or obtain a new controlled capture.

The current replay restarts running remainders at time zero without restoring placement or startup occupancy. Measure and describe the resulting discrepancy; this stage must not claim faithful initialization. Existing captures are the starting point, but inspect their actual coverage before promising an offline-only validation. Record the real scheduler configuration, including whether it predates or implements worker packing; do not mix configurations as if they were identical.

### 2. Forecast versus observations

At those same cutoffs, replace known subsequent arrivals with forecasts generated only from evidence available at the cutoff. Fit/select profiles and forecast parameters without post-cutoff information; future observations are evaluation targets only. Evaluate several chronologically held-out cutoffs covering quiet, rising, busy and recovering periods where the captures support them. Keep the observed initial backlog, topology, action, workload model and observation windows matched to stage 1 so differences are interpretable.

Compare predicted arrival counts/timing and downstream completion/response curves against observations. Present sampled-future medians and ranges alongside the observed outcome, and record errors and range coverage across cutoffs. A min–max scenario envelope is not a calibrated confidence interval, and three sampled futures do not establish coverage quality. Use the known-arrival replay as a diagnostic reference to distinguish forecast effects from simulation/initialization effects; do not assume the two errors add independently.

### 3. Controlled comparisons of assumptions

Once the first two stages provide a measured baseline, vary one assumption at a time: forecast horizon, sampled-future count (for example 3, 10 and 20), or runtime/remainder estimation. Treat those values as candidate experiments, not newly agreed defaults. Keep the same cutoffs, initial backlog and remaining settings, and reuse seeds/shared sampled futures where applicable. When changing the arrival horizon, declare how the evaluation window and Job cohort stay comparable rather than comparing different amounts of work as if they were the same experiment.

Use adjacent panels for meaningful model/configuration comparisons, with common metric scales and clear parameter labels. Assess prediction error, stability as scenario count increases, empirical coverage and execution cost. Existing backlog is present in every configuration; empty versus nonempty starting workloads remain test fixtures, not alternative policies for representing a nonempty cluster. Select parameters using validation cutoffs and assess the selected configuration on separate held-out cutoffs.

### Evidence and limits for the follow-up

Produce a reproducible evaluation command, frozen input/configuration provenance, machine-readable matched observations/predictions, comparison plots and a short findings document identifying supported conclusions and remaining gaps. Preserve existing reports, captures, logs, packaging simplifications and workload. The accepted PDF is a presentation baseline, not a request to reopen line styling or simplify its cover during this milestone. Run regressions relevant to the changed contracts and apply the existing changed-file lint/documentation rules; do not repeat branch-wide cleanup.

Actual scaling-action validation needs controlled executions with comparable starting work; an unchanged run does not supply observed counterfactual scale-up/down outcomes. Complete scale-down accounting for the omitted worker and its assigned Jobs is necessary before making full-system action-preference claims. Current worker power assumptions are uncalibrated, so energy accuracy requires suitable measured power evidence. Keep C−1 worker capacity, control-plane runner placement and current provisional limitations explicit. This milestone combines worker packing with validation evidence; it adds no automatic scaling action, action-scoring policy or SLO threshold.

## Testing priorities

The direct container-execution milestone has sufficient validation. Additional OOM/abrupt-kill hardening, broad stress testing and the four skipped infrastructure opt-in checks are not current priorities. Add tests when implementing new behavior or when a concrete failure or deployment decision requires them. Retain the existing regression and controlled integration coverage.

## Validation evidence

The [code-simplification validation](../../logs/fns-provisional/simplification-20260921/VALIDATION.md) covers removal of repeated evaluator validation, the obsolete formatted reference table, duplicated plotting code and overlapping scenario checks. The evaluator now verifies each completed batch once and uses the runner's saved validated completions and clock correction; scenario preparation retains one complete reconstruction check. `--metrics-file` regenerates the report without raw experiments. All 24 case results and action aggregates match the accepted report, and both graph pages are pixel-identical. The [regenerated PDF](../../logs/fns-provisional/simplification-20260921/from-batches/report.pdf) retains the same modeling limitations. No simulator, cluster or workload changes were required; earlier artifacts remain intact.

The [simplified simulation PDF](../../logs/fns-provisional/report-polish-20260921/final/report.pdf) retains the selected 10-Job backlog, three sampled futures and unchanged line styling. Page two shows Cumulative Cluster Energy Use and Completed Jobs. Page three shows overall modeled-Job response with future/backlog companions. Axis endpoints use evenly spaced round ticks. Explanations live on page one; scale-down remains marked partial in the legend. The numerical reference summary and all exact case metrics remain in JSON. The no-backlog comparison is removed from the main PDF; the former `--include-input-comparisons` option and its renderer were removed during final review because the current report no longer uses them. See the [polish validation](../../logs/fns-provisional/report-polish-20260921/final/VALIDATION.md). Earlier PDFs and executions remain preserved.

The [reference-first comparison PDF](../../logs/fns-provisional/report-layout-20260921/final/report.pdf) leads with the user-selected 10-Job initial backlog and then compares it beside the no-backlog input using shared axes. Both use the same two-worker model settings and sampled futures. Action curves use bold medians, thin min–max outlines and faint fills; count curves apply two-second Gaussian display smoothing per scenario without changing exact metrics. Future and backlog response are consistently separated, and an absent cohort is explicit. The [previous comparison PDF](../../logs/fns-provisional/report-comparison-20260921/final/report.pdf) and original report remain preserved. This revision reuses verified executions without a cluster rerun. Batches without scale-up remain in raw metrics but are omitted from three-action graphs; scale-down accounting remains explicitly partial. See the [layout validation](../../logs/fns-provisional/report-layout-20260921/final/VALIDATION.md).

The [provisional workflow validation](../../logs/fns-provisional/implementation-20260918/VALIDATION.md) records the fresh six-cycle Continuum run, control-plane candidate execution, synthetic capacity cases, native timing correction, offline PDF, regressions and review. The [preliminary PDF](../../logs/fns-provisional/implementation-20260918/preliminary-evaluation/report.pdf) compares two evaluation windows while keeping scale-down accounting partial and the power assumptions uncalibrated. Changes remain uncommitted pending user authorization.

The [final review validation](../../logs/fns-opendc-execution/final-review-20260918T152410Z/VALIDATION.md) covers the reviewed implementation after packaging simplification and documentation cleanup: 141 image-batch tests pass, the current Dockerfile builds without the removed version JSON or checksum catalogues, and both offline simulator fixtures reproduce the earlier native records. The final review changed no executable Python statements. The subsequent [branch-wide cleanup](LINT_CLEANUP.md) records its own checks and reviewed remaining lint findings.

The reports below describe the images tested at the time. During review, the Gradle dependency checksum catalogue, compiled JAR inventory and archive-normalization script were removed; dependency verification is disabled. The OpenDC source revision remains pinned. The [simplified-build validation](../../logs/fns-opendc-execution/simplified-build-20260918T125614Z/VALIDATION.md) covers the rebuilt image, 41 passing OpenDC tests, and offline controlled/memory smoke runs whose native records match the earlier validated image. Kubernetes integration was not repeated for this packaging simplification.

The [pinned master validation report](../../logs/fns-opendc-execution/master-20260918T103347Z/VALIDATION.md) covers commit `7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad`: a clean source build with strict dependency verification and 84 reproducible JAR hashes, 141 passing image-batch regressions, three matching local/Kubernetes controlled repetitions, memory admission, malformed input, timeout handling, verified retrieval and cleanup. Kubernetes controlled execution took 8.54–8.63 seconds with 147–148 MiB peak container memory under the unchanged 1-CPU/2-GiB limits. All 139,840 prior evidence files were verified unchanged. This replaces the old runtime pin; initial placement and the planned split scale-down simulation remain unimplemented.

The earlier [v2.4u validation report](../../logs/fns-opendc-execution/validation-20260918T074000Z/VALIDATION.md) records three matching local/Kubernetes controlled repetitions, memory-admission validation, Kubernetes malformed-input and timeout cases, verified artifact retrieval and cleanup, 139 passing image-batch regressions, and infrastructure discovery with four opt-in skips. Kubernetes controlled execution took 9.66–10.22 seconds with 160–161 MiB peak container memory under 1-CPU/2-GiB limits. These are small-fixture measurements, not saturation-capacity estimates. Validation images remain cached on the worker; test Jobs, namespaces and run directories were removed. The historical report and prior simulator-input captures remain preserved separately.

The [simulator-input validation report](../../logs/fns-simulation-inputs/review-validation-20260917T170423Z/VALIDATION.md) covers the refactored builder and schema-2 zero-remaining model: passing regressions, forecast-image checks, offline replay of 148 historical cutoffs, and a fresh six-cycle live run with 141 completed Jobs and no container restarts. It records every rejected cutoff and byte reproduction checks. Packaging and live source validation were checked separately, as detailed in the report.

The earlier [six-cycle live capture](../../logs/fns-simulation-inputs/validation-20260917/) used schema 1's five-second tail; preserve it as historical evidence, not live validation of the zero-remaining model. Source hashes in each capture identify the exact revision tested.

## Cluster setup reference

Before applying `manifests/adapter.yaml`, install [scheduler-packing.yaml](manifests/scheduler-packing.yaml) as `/etc/kubernetes/fns-packing.yaml` on the control plane. Back up the existing kube-scheduler static Pod manifest outside `/etc/kubernetes/manifests`, add `--config=/etc/kubernetes/fns-packing.yaml` and mount that file read-only. Keep the existing scheduler kubeconfig mount. Wait for readiness and verify actual application placement; this manual setup is required before Jobs can use the `fns-packing` profile.

Build images on the host, then make the specified tags available to the VM runtimes before deploying. Preserve the calibrated `WORKER_IMAGE` setting and verify loaded image IDs when refreshing an existing cluster; use a new adapter/observer tag. The deployment assumptions and the validated image-refresh commands are recorded with the [milestone evidence](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md). Do not perform a live Kubernetes version upgrade; use the separate offline provisioning plan above.

Preserve the node3 calibration: four images, 128 inference repetitions and five-second resource sampling. Changing these breaks timing comparability. Keep the adapter and observer healthy and unchanged throughout a measured run.

Network replay uses pinned KPN 5G access traces plus static core settings. Provisioning compiles MahiMahi into endpoint base images; rebuild an older base before enabling replay. On the endpoint, run `sudo python3 /home/mahimahi/continuum_replay.py check` before the workload.

### Evidence to preserve

Copy `/var/lib/opendt` from the observer before removing or rebuilding its Pod: its `emptyDir` is ephemeral. The four streams are `workload.jsonl` (completed profiles), `resource-snapshots.jsonl` (raw samples), `cluster-state.jsonl` (unfinished Jobs and workers), and `observer-events.jsonl` (arrival/emission timing and diagnostics). Capture endpoint stdout separately and preserve adapter results and `events.jsonl` under `/data`. HTTP contracts are defined in [adapter.py](src/adapter.py).

## Controlled OpenDC run reference

Build the pinned image using the [README](README.md#direct-controlled-opendc-execution). This empty-state smoke example retains the required local hostname mapping and executable `/tmp` for native Parquet compression. Choose a new evidence directory:

```bash
mkdir -p "$PWD/logs/opendc-local"
docker run --rm --user "$(id -u):$(id -g)" --network none --read-only \
  --hostname opendc-controlled --add-host opendc-controlled:127.0.0.1 \
  --tmpfs /tmp:rw,exec,nosuid,size=256m --cpus=1 --memory=2g \
  -v "$PWD/logs/opendc-local:/evidence" continuum/opendc:master-7db7e1a2331fd \
  prepare --fixture controlled --output-dir /evidence/inputs
docker run --rm --user "$(id -u):$(id -g)" --network none --read-only \
  --hostname opendc-controlled --add-host opendc-controlled:127.0.0.1 \
  --tmpfs /tmp:rw,exec,nosuid,size=256m --cpus=1 --memory=2g \
  -v "$PWD/logs/opendc-local:/evidence" continuum/opendc:master-7db7e1a2331fd \
  run --input-dir /evidence/inputs --output-dir /evidence/result
```

Check native output validation as well as process success. Prepare fresh inputs after changing OpenDC versions. For optional Kubernetes checks, use [run_opendc_integration.py](tests/run_opendc_integration.py) and its `--help`. After failure, resume artifact collection with `opendc_kubernetes.py collect`; delete remote evidence only after `collection.json` reports `collected` and `artifacts_verified: true`.

## Manual run reference

Use a ready forecast with `--simulation-inputs`, its original observer directory and a worker configuration JSON. Each `workers` entry needs `node_name`, `configured_cores` and `memory_mib`; supply configured VM cores, not already-reduced application cores. An optional `active_workers` list identifies the starting pool. Include a reserve worker to make a scale-up candidate available. Install `requirements-analysis.txt` in the forecasting environment for PDF generation.

```bash
python3 application/image_batch/src/opendc_scenarios.py prepare \
  --forecast-dir ./logs/forecast-one --observer-dir ./opendt-audit \
  --workers workers.json --initialization-mode provisional-trace \
  --output-dir ./logs/scenarios-one
python3 application/image_batch/src/opendc_batch.py \
  --suite-dir ./logs/scenarios-one --output-dir ./logs/scenarios-one-local \
  --image continuum/opendc:master-7db7e1a2331fd --backend local
python3 application/image_batch/src/opendc_evaluate.py \
  --batch-dir ./logs/scenarios-one-local --output-dir ./logs/scenarios-one-report
```

For Kubernetes execution, follow the [recorded matrix commands](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md) and keep the runner on the control plane. Those commands also cover known-arrival replay and chronological validation; select parameters on validation evidence and reuse the saved selection for held-out evaluation.

## Evaluation and reporting conventions

Preserve the compact report's shared six-window denominator across configurations and metrics, and its chronological detail selection. Use [COMMANDS](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md) and [FINDINGS](../../logs/fns-provisional/packing-validation-20260921/FINDINGS.md) for the exact experiment design and interpretation; the current review state and reporting follow-ups are at the top of this handoff.

Recheck the simulator-specific memory conversion when updating OpenDC: inputs multiply memory by 1,000 to compensate for the pinned reader. Original observer exports must remain unchanged.
