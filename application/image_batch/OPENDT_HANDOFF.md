# OpenDT handoff

## Where to resume

The branch-wide formatting and lint cleanup is complete and approved by the user; see [the cleanup report](LINT_CLEANUP.md). Resume the provisional scenario workflow below, including the agreed worker-capacity and control-plane runner placement. Do not repeat the branch-wide lint pass.

Simulator inputs and direct controlled OpenDC execution are implemented. The execution milestone precedes assigned-work integration and bypasses OpenDT entirely: use `opendc_run.py` and the container built from pinned upstream master commit `7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad`. It executes synthetic empty-state fixtures, not live simulation bundles. Feeding only live Parquet traces into this runner would lose existing placement and startup occupancy.

The OpenDC lead confirmed that initial-state restoration is not currently supported and suggested that a small targeted fix may be feasible. The follow-up requesting fixed initial placement and feedback on the split scale-down simulation has been sent; a solution is pending. Continue with the provisional scenario workflow below while the developer works on it. Evaluation-window decisions do not depend on another developer response.

The next implementation also uses the worker-capacity and control-plane runner decisions below. These are recorded for follow-up after review; the current synthetic fixtures, worker-hosted runner and validation evidence remain unchanged.

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

Use the [README](README.md#direct-controlled-opendc-execution) for the container and isolated integration test. `opendc_run.py prepare` writes source/adapted traces, topology, fixture expectations and provenance; `run` writes `execution.json`, `resources.json`, logs and native simulator output. Always choose new directories. Inspect both the process exit and output validation; OpenDC exit zero alone is insufficient.

`opendc_kubernetes.py manifest` renders one Job for a preloaded image and pre-created node-local directory. Stage inputs under `REMOTE/inputs` and create `REMOTE/results` owned by UID/GID 1000 with mode 0755; `REMOTE` must be a unique `/var/tmp/fns-opendc-NAME`. Apply the rendered Job in a dedicated namespace. After the Job reaches Complete or Failed, `collect` verifies its source and copies artifacts over SSH into a new local directory. Inspect `collection.json` before deleting the Job or remote directory. Failed collection leaves the source intact. The opt-in integration test implements this full sequence and saves commands, manifests and cleanup evidence.

The Dockerfile and Python requirements define build pins; execution manifests record the OpenDC commit and runtime versions without a separate version JSON file. The pinned SDK trace loader still divides memory by 1,000, so the memory adaptation remains necessary; revalidate it before each upgrade. The new upstream CLI is `opendc --strict run`; it no longer emits `trackr.json`. Use the resolved experiment, execution manifest and native Parquet records for provenance and validation. Prepare fresh controlled inputs after a version change. Docker scratch mounts must allow executable mappings for the upstream compression library. A successful controlled run proves direct execution and its artifact path; it does not prove live-state initialization, forecast validity or a working closed loop.

## Follow-up: worker capacity and control-plane runner

Implement this in a later change, alongside the provisional scenario workflow. No VM resizing or reprovisioning is planned. Keep the current controlled execution fixture and historical validation evidence intact.

1. Convert each configured C-core worker VM into a C - 1 core OpenDC host. Four cores become three, eight become seven; three current workers give nine one-CPU application slots. Retain configured and modeled counts plus the one-core rule in provenance. Apply the deduction once, without additionally subtracting system Pod requests or observed utilization. Reject a modeled topology that needs work on a worker with no positive application capacity. Automated per-Pod capacity accounting is not required.
2. Omit daemon/observability workload and separate daemon energy overhead. The deducted core is a capacity allowance, not a continuously running task. Preserve the configured worker idle-power baseline; label outputs as simplified modeled worker energy. Exclude the control plane and runner from simulated topology and energy, while continuing to collect actual runner CPU, memory and time separately.
3. Use the frozen representative application profile and its measured fragments for scenario inputs, preserving one-CPU requests. Do not replace it with the artificial ten-second fixture or assume constant full utilization. Keep the twelve-slot synthetic fixture as a regression test and validate the nine-slot application model separately.
4. Inspect current control-plane labels, taints, allocatable resources, existing Pod requests and observed CPU/memory load. The saved master-validation snapshot identifies cloudcontrollermatthijs with four CPUs and a node-role.kubernetes.io/control-plane:NoSchedule taint; it does not establish current headroom. Verify that one runner with one-CPU/two-GiB requests and limits and a one-GiB heap cap can coexist with control-plane services. Run candidates sequentially.
5. Target the control plane through a required node selector or affinity and give only the OpenDC application Pod a toleration for the matching control-plane taint. Keep that taint in place; retain or add worker-only placement constraints to generated application Jobs and check they have no broad toleration allowing control-plane placement. Keep scheduler resource checks active rather than binding with nodeName. See Kubernetes guidance on [taints and tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) and [node selection](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/).
6. Adapt manifests, exact-image staging, node-local input/output paths, SSH collection and identity verification for the control-plane host. Continue excluding the control plane from worker state and scaling candidates. With OpenDC there, subtract no extra runner core from any modeled worker. Do not silently fall back to workers. If worker placement is chosen later, reserve one additional core on that worker in both Kubernetes and the model; use a capacity deduction rather than a synthetic runner Job in the trace.
7. Validate in isolation that OpenDC starts and completes while application worker slots are full, application Jobs remain off the control plane, and API responsiveness and runner CPU/memory stay acceptable. Record scheduling delay separately from simulation duration. Verify success, failure, evidence retrieval and cleanup on the new host. This placement removes competition for worker Job slots; headroom and shared-host contention still require measurement before claiming reliable loop timing.

Use [DESIGN](DESIGN.md#planned-worker-capacity-and-runner-placement) for the rationale. This follow-up does not require fixed initial placement from the OpenDC developer, and it does not itself add automatic forecasting execution or actuation.

## Next milestone: provisional scenario workflow

This is agreed follow-up work, not functionality in the current controlled runner. Build a small, manually invoked path from scenario preparation through OpenDC execution and result collection to a preliminary evaluation PDF, using the worker-capacity and runner-placement decisions above. Keep initialization and the isolated scale-down component replaceable; reuse the surrounding workflow when supported placement becomes available. Do not add automatic forecasting execution, scoring thresholds or actuation in this step.

1. Prefer an explicit provisional trace mode: release already-running Jobs' remaining profiles at time zero without enforcing their observed worker assignments. Include queued/starting work and sampled future arrivals, preserving existing profile semantics. Retain assignments, phases, identities, original arrival times and source traces in evidence. Empty-state fixtures remain available for simpler checks; they are not the only permitted interim experiments.
2. Record the initialization mode in manifests and reports. Trace replay does not restore startup occupancy or prevent already-running Jobs from waiting again or moving to different workers, including an added worker. Treat results as provisional modeling experiments, not validated live predictions. Never silently fall back from requested fixed placement to this approximation.
3. Use the same sampled futures for unchanged, scale-up and scale-down simulated topologies. Select a scale-down candidate using the heuristic below. For now, omit that worker and its assigned starting/running Jobs from the main simulation, retaining an inventory of omitted Jobs and profiles for the later isolated simulation. Keep all unassigned queued work and future arrivals in the main simulation.
4. Report scale-down output as the remaining workers' component only. The omitted worker's completion and energy results are unavailable, not zero. Do not migrate its assigned Jobs, invent their completion, or compare partial totals as if they covered the same whole-cluster work. Add the isolated execution and result combination later.
5. Produce the preliminary evaluation-window PDF from small synthetic or explicitly approximate replay experiments. Use consistent modeled scope when comparing window strategies, label missing components, and revisit findings after supported initialization and complete scale-down accounting are available.

When adding replay of schema-2 bundles, retain the readiness, freshness and exhausted-profile rules below. Bundle readiness confirms input completeness, not fidelity of provisional initialization. Keep the existing representative workload profile, Poisson generation, three-second freshness default and physical topology unchanged. The current validation report continues to describe controlled execution only.

## Future live-state runner input contract

Any future schema-2 replay, including the provisional mode above, must consume bundles only when `simulation/manifest.json` reports `ready`. The current controlled runner rejects them. The manifest is written last; its absence means an incomplete export. Not-ready manifests list rejection reasons and have no executable scenario export. The table below describes the target responsibilities with supported initialization; provisional mode retains assignment evidence but does not enforce placement, and temporarily retains the selected worker's component without executing it.

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
2. Add deterministic selection of one scale-down candidate per observed cutoff. Prefer an empty eligible worker; otherwise choose the worker whose most recent Job assignment is oldest. This is the initial common-duration heuristic for selecting the worker expected to finish its assigned work soonest. Include starting Jobs when identifying recent assignments and use worker identity to break ties.
3. Evaluate scale-down using separate simulations. For each sampled future, simulate the remaining workers with their assigned work, all unassigned queued work, and that future's arrivals. Separately simulate the selected worker with only its assigned remaining work and no future arrivals. Run that isolated simulation once per cutoff and reuse its output across the scale-down scenarios. Preserve initial placement in both components.
4. Combine component results using the same time origin and evaluation boundaries. Keep task identities disjoint and retain each Job exactly once per combined scenario. Sum additive quantities such as energy and completion counts; compute response-time distributions and percentiles from the combined task records rather than averaging component summaries. Explicitly define energy accounting after the selected worker finishes; cordoning alone does not imply that the machine is powered off.
5. Revisit the preliminary PDF once initialization and complete candidate simulations are available. Review the effects before selecting the demo's evaluation policy. Then connect candidate selection and actuation.

Use the same sampled futures across unchanged, scale-up and scale-down candidates. Keep the current workload and physical topology. The split simulation assumes the selected worker's remaining execution does not contend with the other workers through resources represented in the model.

## Evaluation approach review

Exported simulator records provide the technical basis for choosing evaluation windows. Window selection, unfinished-Job treatment and post-horizon arrivals are deferred project decisions, not prerequisites awaiting another answer from the OpenDC developer.

Prepare a focused PDF comparing two or three approaches using the same starting inputs and sampled arrivals. Begin with small synthetic or explicitly approximate replay experiments; revisit with faithfully initialized observed states later. Possible approaches include a fixed arrival-window evaluation with unfinished work reported, following the arrival cohort through completion, and extending arrivals beyond the evaluation boundary to examine completion sensitivity. Keep the evaluation boundary separate from the arrival-generation horizon.

Show cumulative energy, completed and unfinished work, and response-time results, with arrival and evaluation boundaries marked. Explain which Jobs, workers and time intervals each metric includes. Explicitly distinguish omitted Jobs from simulated unfinished Jobs, and label initialization approximations. Examine candidate preference only when results cover comparable complete work and energy accounting; partial scale-down output cannot establish a preferred candidate. Select a practical, defensible approach for the demo after review; do not introduce a scoring policy or SLO thresholds beforehand.

## Testing priorities

The direct container-execution milestone has sufficient validation. Additional OOM/abrupt-kill hardening, broad stress testing and the four skipped infrastructure opt-in checks are not current priorities. Add tests when implementing new behavior or when a concrete failure or deployment decision requires them. Retain the existing regression and controlled integration coverage.

## Validation evidence

The [final review validation](../../logs/fns-opendc-execution/final-review-20260918T152410Z/VALIDATION.md) covers the reviewed implementation after packaging simplification and documentation cleanup: 141 image-batch tests pass, the current Dockerfile builds without the removed version JSON or checksum catalogues, and both offline simulator fixtures reproduce the earlier native records. The final review changed no executable Python statements. The subsequent [branch-wide cleanup](LINT_CLEANUP.md) records its own checks and reviewed remaining lint findings.

The reports below describe the images tested at the time. During review, the Gradle dependency checksum catalogue, compiled JAR inventory and archive-normalization script were removed; dependency verification is disabled. The OpenDC source revision remains pinned. The [simplified-build validation](../../logs/fns-opendc-execution/simplified-build-20260918T125614Z/VALIDATION.md) covers the rebuilt image, 41 passing OpenDC tests, and offline controlled/memory smoke runs whose native records match the earlier validated image. Kubernetes integration was not repeated for this packaging simplification.

The [pinned master validation report](../../logs/fns-opendc-execution/master-20260918T103347Z/VALIDATION.md) covers commit `7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad`: a clean source build with strict dependency verification and 84 reproducible JAR hashes, 141 passing image-batch regressions, three matching local/Kubernetes controlled repetitions, memory admission, malformed input, timeout handling, verified retrieval and cleanup. Kubernetes controlled execution took 8.54–8.63 seconds with 147–148 MiB peak container memory under the unchanged 1-CPU/2-GiB limits. All 139,840 prior evidence files were verified unchanged. This replaces the old runtime pin; initial placement and the planned split scale-down simulation remain unimplemented.

The earlier [v2.4u validation report](../../logs/fns-opendc-execution/validation-20260918T074000Z/VALIDATION.md) records three matching local/Kubernetes controlled repetitions, memory-admission validation, Kubernetes malformed-input and timeout cases, verified artifact retrieval and cleanup, 139 passing image-batch regressions, and infrastructure discovery with four opt-in skips. Kubernetes controlled execution took 9.66–10.22 seconds with 160–161 MiB peak container memory under 1-CPU/2-GiB limits. These are small-fixture measurements, not saturation-capacity estimates. Validation images remain cached on the worker; test Jobs, namespaces and run directories were removed. The historical report and prior simulator-input captures remain preserved separately.

The [simulator-input validation report](../../logs/fns-simulation-inputs/review-validation-20260917T170423Z/VALIDATION.md) covers the refactored builder and schema-2 zero-remaining model: passing regressions, forecast-image checks, offline replay of 148 historical cutoffs, and a fresh six-cycle live run with 141 completed Jobs and no container restarts. It records every rejected cutoff and byte reproduction checks. Packaging and live source validation were checked separately, as detailed in the report.

The earlier [six-cycle live capture](../../logs/fns-simulation-inputs/validation-20260917/) used schema 1's five-second tail; preserve it as historical evidence, not live validation of the zero-remaining model. Source hashes in each capture identify the exact revision tested.
