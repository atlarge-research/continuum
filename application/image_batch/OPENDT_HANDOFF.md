# OpenDT handoff contract

Edward's pinned `closed-loop-opendt` `v1.0.0` observes native Kubernetes Jobs. Its `K8sResourceTerminalStream` waits for a Job to become terminal, and its `K8sWorkloadProducer` combines Job timing metadata with stored resource-usage snapshots. The resulting OpenDT workload message contains an OpenDC `Task` and zero or more CPU-utilization `Fragment` records.

The image-batch application preserves that contract:

| Demo evidence                        | Source                                   | Later OpenDT input                      |
| ------------------------------------ | ---------------------------------------- | --------------------------------------- |
| request/demo/workload-run lineage    | Job labels and annotations               | state/run lineage                       |
| submission/start/finish              | Kubernetes Job status                    | Task timing                             |
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

The sidecar writes `workload.jsonl`, `resource-snapshots.jsonl`, `cluster-state.jsonl`, and `observer-events.jsonl` under its dedicated `/var/lib/opendt` `emptyDir`. The records carry Kubernetes Job UIDs so a later OpenDC reader can take a bounded workload trace, deduplicate it, select the last complete cluster snapshot at or before the cutoff, and create `tasks.parquet` and `fragments.parquet`. JSONL is ephemeral audit evidence, not a permanent service transport.

Application duration fields use process-local monotonic clocks, while `timestamp_unix_ns` supports cross-component ordering when VM clocks are synchronized. The observer uses Job creation as submission time, the worker container's Kubernetes start/finish timestamps as its execution interval, and Job completion as fixed-cutoff provenance. This keeps scheduler queueing out of the Task's compute duration.

The operator-focused usage instructions are in `README.md`. The stable design rationale and experiment limitations are in `DESIGN.md`; update that document when later implementation decisions change the meaning of collected evidence.

## Validated current state

The implementation described here has been exercised on node3 with one control plane, three workers, and one endpoint. Three identical seeded runs each attempted and completed all 34 planned requests. All sends began within about 1.1 milliseconds of their planned time, sender queue depth remained zero, and all 102 successful Kubernetes Jobs produced a unique workload record with nonempty Fragments. Worker container execution was approximately 30--35 seconds. The manifest's 128 inference repetitions are a synthetic calibration mechanism, not realistic application behavior.

The committed runtime baseline has 30 focused unit and integration-style tests. They cover topology and CPU pinning, schedule generation and open-loop release, lineage, HTTP behavior, observer conversion and deduplication, Prometheus/Pod correlation, cluster-state completeness, timing semantics, and manifest/RBAC constraints.

## Agreed follow-up order

### 1. Repeated arrival cycles, deferred

When forecasting work requires a longer recurring workload, add an `--arrival-cycles` parameter with a default of one. Repeat the cosine-shaped expected intensity over the full run and sample one continuous seeded Poisson process. Do not duplicate one cycle's exact sends or timestamps; stochastic arrivals should differ between cycles even when the expected pattern repeats.

Defer varying peak heights, phases, or cycle lengths until the complete demo works. Do not implement repeated cycles merely as speculative functionality if the prediction experiment can proceed without them.

### 2. Remaining closed-loop features

Continue with the current Notion plan for bounded JSONL reading, deterministic Parquet generation, forecasting, OpenDC execution, policy selection, and actuation. Preserve the fixed-cutoff and Job UID deduplication rules described above.

Do not spend demo time moving the cAdvisor configuration script into Ansible. The current small, idempotent, self-verifying script is sufficient unless it later becomes shared infrastructure.

Keep the current single-node topology until a functional closed loop is available. The user's deferred capacity direction is two 20-core physical hosts: five worker VMs and one control-plane VM at six vCPUs each, plus a two-vCPU endpoint (38 assigned vCPUs). Three cloud VMs would use 18 cores per host, with the endpoint using two remaining cores on one host. Revisit workload/capacity calibration then so queue buildup occurs later without disappearing entirely. No infrastructure or arrival parameters have been changed for the report feature.
