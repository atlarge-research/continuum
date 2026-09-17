# OpenDT handoff contract

Edward's pinned `closed-loop-opendt` `v1.0.0` observes native Kubernetes Jobs. Its `K8sResourceTerminalStream` waits for a Job to become terminal, and its `K8sWorkloadProducer` combines Job timing metadata with stored resource-usage snapshots. The resulting OpenDT workload message contains an OpenDC `Task` and zero or more CPU-utilization `Fragment` records.

The image-batch application preserves that contract:

| Demo evidence                        | Source                                   | Later OpenDT input                      |
| ------------------------------------ | ---------------------------------------- | --------------------------------------- |
| request/demo/workload-run lineage    | Job labels and annotations               | state/run lineage                       |
| submission/start/finish              | Job metadata and worker-container state  | Task timing                             |
| requested CPU/memory                 | Job Pod specification                    | Task capacity                           |
| observed CPU usage                   | Prometheus/container metrics             | Task fragments                          |
| image count and payload bytes        | Job annotations + adapter JSONL          | explanatory workload metadata           |
| endpoint batch ID                    | endpoint/adapter events + Job annotation | pre-adapter request correlation         |
| queued/running Jobs and worker state | Kubernetes Jobs, Pods, and Nodes         | simulation initial state at cutoff      |
| classification result                | adapter `result.json` only               | proof of real work; not simulator input |

The adapter's `events.jsonl` is application lineage, not a substitute for Edward's resource observer. The demo sidecar now implements the minimum compatible behavior from commit `c3e1f8cd56918d8c10c4013a8b8733011323f9d7`:

1. `libs/common/odt_common/models/task.py` and `fragment.py` for the trace model.
2. The Job event extractor and terminal stream from `libs/k8s-observability`.
3. A Prometheus resource-usage collector that maps cAdvisor Pods to Jobs using Kubernetes owner references, constructs fragments from source timestamps, and preserves short Jobs with an empty fragment list otherwise.
4. The workload producer's conversion logic, targeting append-only JSONL rather than requiring Kafka and the full OpenDT compose deployment.
5. A one-second full-state collector, independent of the five-second resource cadence, for non-terminal Jobs, their Pods, and worker availability. This state is intentionally not encoded as completed Tasks because unfinished Jobs have no authoritative duration or fragments.

The sidecar writes `workload.jsonl`, `resource-snapshots.jsonl`, `cluster-state.jsonl`, and `observer-events.jsonl` under its dedicated `/var/lib/opendt` `emptyDir`. The bounded reader uses Kubernetes Job UIDs to deduplicate history, select the last complete cluster snapshot at or before the cutoff, and create `tasks.parquet` and `fragments.parquet`. JSONL is ephemeral audit evidence, not a permanent service transport.

Application duration fields use process-local monotonic clocks, while `timestamp_unix_ns` supports cross-component ordering when VM clocks are synchronized. The observer uses Job creation as submission time, the worker container's Kubernetes start/finish timestamps as its execution interval, and Job completion as fixed-cutoff provenance. This keeps scheduler queueing out of the Task's compute duration.

The operator-focused usage instructions are in `README.md`. The stable design rationale and experiment limitations are in `DESIGN.md`; update that document when later implementation decisions change the meaning of collected evidence. Persistent scope, priorities, and delivery gates live in the [Notion demo task](https://app.notion.com/p/374dc985c5868055a157df2a6d95f1bb).

## Validated current state

The implementation described here has been exercised on node3 with one control plane, three workers, and one endpoint. Three identical seeded runs each attempted and completed all 34 planned requests. All sends began within about 1.1 milliseconds of their planned time, sender queue depth remained zero, and all 102 successful Kubernetes Jobs produced a unique workload record with nonempty Fragments. Worker container execution was approximately 30--35 seconds. The manifest's 128 inference repetitions are a synthetic calibration mechanism, not realistic application behavior.

The runtime baseline has focused unit and integration-style tests. They cover topology and CPU pinning, schedule generation and open-loop release, lineage, HTTP behavior, observer conversion and deduplication, Prometheus/Pod correlation, cluster-state completeness, timing semantics, and manifest/RBAC constraints.

Arrival forecasting already samples multiple futures (`--scenarios`, default 100), bounds future arrivals with `--horizon-seconds` (default 60), and supports periodic forecasting with `--interval-seconds`. Each ready cutoff exports historical and per-scenario `tasks.parquet`/`fragments.parquet`, plus separate `state.json`. These are not yet complete simulator inputs for queued/running work, and the interval does not invoke OpenDC or actuate.

The September 17 capture matches the current application source: 141/141 Jobs completed with unique workload records and nonempty Fragments, no sidecar restarts, and 50 ready forecasts after warm-up. It exercises the observer-finalization and retrospective-evaluation fixes with cellular replay. Evidence is under `logs/fns-network-review/logging-20260917/fresh-forecast/`; earlier unshaped runs remain baseline evidence.

## Remaining closed-loop work

1. Combine queued work, remaining running work, and future arrivals into simulator inputs at one cutoff. Use observed container start times and the fixed execution profile; never encode scheduler waiting as computation. Bound new arrivals by the forecast horizon, and define how completion beyond that horizon is scored.
2. Package OpenDC as a Kubernetes runner, initially one long-lived container executing traces sequentially. Measure CPU/memory and reserve placement/capacity before workload saturation, including when only one worker is schedulable. Recalibrate workload capacity after this reservation: the existing deployment fits three whole one-CPU Jobs per worker, despite four allocatable CPUs; startup also occupies a slot.
3. Extend periodic forecasting into a complete control cycle. Reuse the same X futures and observed state for each valid current-worker-count + {-1, 0, +1} candidate within one to three workers: 3X simulations at two workers, 2X at either boundary. Measure total cycle cost to choose X and cadence; define timeout/overrun handling so decisions do not overlap or use stale state.
4. Agree the performance SLO and required confidence, process results, then apply and verify cordon/uncordon and observe the outcome. Model running Jobs finishing on a cordoned worker; cordoning does not evict them or physically power off the VM. Account consistently for this transition when returning capacity to the modeled provider pool.

Keep the single-host topology until the loop works. Later two-host exploration remains five six-vCPU workers, one six-vCPU control plane, and a two-vCPU endpoint, with workload/capacity recalibration. Defer varying cycle shapes and cAdvisor migration into Ansible until the functional loop is dependable. Cellular replay is already integrated; richer network modeling remains outside the demo's compute-focused loop.
