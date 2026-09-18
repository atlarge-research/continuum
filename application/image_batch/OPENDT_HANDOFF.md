# OpenDT handoff

## Where to resume

Simulator inputs are implemented; OpenDC execution, candidate selection, and worker actuation are next. Start by integrating restoration of assigned work: the pinned `closed-loop-opendt` v1.0.0 wrapper accepts Tasks and topology but does not expose this capability. Feeding it only the Parquet traces would lose existing placement and startup occupancy.

The entry point is [forecast_workload.py](src/forecast_workload.py) with `--simulation-inputs`; [simulation_input.py](src/simulation_input.py) builds the shared initial state and combined scenarios. Use the [README](README.md#arrival-forecasting) for invocation and [DESIGN](DESIGN.md#simulation-input-semantics) for modeling decisions. Scope and delivery priorities remain in the [Notion demo task](https://app.notion.com/p/374dc985c5868055a157df2a6d95f1bb).

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

## Runner input contract

Consume schema-2 bundles only when `simulation/manifest.json` reports `ready`. The manifest is written last; its absence means an incomplete export. Not-ready manifests list rejection reasons and have no executable scenario export.

| Artifact under `simulation/` | Runner responsibility |
| --- | --- |
| `manifest.json` | Read requested/effective cutoffs, horizon, readiness, provenance, Job UID mapping, and per-scenario future lineage. |
| `initial-state.json`: `workers` | Restore worker availability and schedulability, including cordoned workers with assigned work. |
| `initial-state.json`: `tasks` | Restore each `{task, metadata}` entry using its phase, worker assignment, resource requests, and queue order. Queue only unassigned work. |
| `initial-state.json`: `model_exhausted_jobs` | Retain as evidence only. These observed-running Jobs have zero modeled execution left; allocate no capacity and invent no completion record. |
| `scenarios/NNNN/tasks.parquet` and `fragments.parquet` | Execute the shared remaining backlog plus that scenario's sampled future. Tables use the existing non-nullable Task/Fragment schema. |

Task IDs join the traces to lineage. Submission times are milliseconds relative to the effective cutoff; backlog releases at zero. Original creation times remain in metadata, so simulated completion can later be related to original arrival. All scenarios share the same initial work and worker state. Future arrivals stop at the horizon; included execution is not truncated there.

The effective cutoff is the latest complete snapshot at or before the requested cutoff, subject to `--max-gap-seconds` (default three seconds). Unknown running timing, conflicting state, or missing assigned workers blocks readiness. `model_exhausted_jobs` retains `task_id`, original lineage/timing, `template_duration_ms`, `remaining_execution_ms: 0`, and `observed_completed: false`; the manifest adds a `running_profile_exhausted` diagnostic. This assumption never changes real Job state.

For reproducible replay, retain the observer files, `boundaries.json`, and `template.json`; pass the latter two through `--boundaries` and `--template`. Source hashes and dependency versions identify the implementation/runtime used. History, original state, and arrival-only traces remain outside `simulation/` for audit and comparison.

## Remaining closed-loop work

1. Add assigned-work restoration to the runner. Verify that queued Jobs are placed once, starting/running Jobs stay on their assigned worker, cordoned workers accept no new work, and exhausted-profile evidence reserves no simulated capacity.
2. Package OpenDC as one Kubernetes runner executing candidates sequentially. Measure and reserve its CPU/memory and ensure it remains available under saturation and scale-down. Recalibrate application capacity: observed allocatable resources are not calibrated Job capacity, and startup also occupies a slot.
3. Reuse the same X futures and observed state for each valid current-worker-count + {-1, 0, +1} candidate within one to three workers. Measure total cycle cost before choosing cadence; define timeout handling so cycles cannot overlap or use stale state.
4. Resolve evaluation policy with the OpenDC lead, then agree SLO thresholds and scenario acceptance confidence. Only then connect candidate selection and verify cordon/uncordon outcomes, including completion of remaining work before returning worker capacity to the modeled provider pool.

Keep the current workload and single-host topology until this loop works. OpenDC execution and restoration still require integration validation; input-bundle validation alone does not establish runner compatibility.

## Evaluation policy discussion with the OpenDC lead

**Resolve before scoring or candidate selection:**

- Which time window contributes energy and throughput?
- How do unfinished Jobs affect performance and SLO evaluation?
- Are post-horizon arrivals needed for meaningful completion predictions?

Simulation completion does not decide whether to score the entire drain period. Original arrivals, full profiles, and separate backlog/future lineage support a later fixed-window or cohort-based choice. Poisson scenarios continue to sample different counts and timings from the same fitted model; SLO thresholds and acceptance confidence are separate decisions.

## Validation evidence

The [current validation report](../../logs/fns-simulation-inputs/review-validation-20260917T170423Z/VALIDATION.md) covers the refactored builder and schema-2 zero-remaining model: passing regressions, forecast-image checks, offline replay of 148 historical cutoffs, and a fresh six-cycle live run with 141 completed Jobs and no container restarts. It records every rejected cutoff and byte reproduction checks. Packaging and live source validation were checked separately, as detailed in the report.

The earlier [six-cycle live capture](../../logs/fns-simulation-inputs/validation-20260917/) used schema 1's five-second tail; preserve it as historical evidence, not live validation of the zero-remaining model. Source hashes in each capture identify the exact revision tested.
