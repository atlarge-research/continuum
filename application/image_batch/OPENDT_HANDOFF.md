# OpenDT handoff contract

Edward's pinned `closed-loop-opendt` `v1.0.0` observes native Kubernetes Jobs.
Its `K8sResourceTerminalStream` waits for a Job to become terminal, and its
`K8sWorkloadProducer` combines Job timing metadata with stored resource-usage
snapshots. The resulting OpenDT workload message contains an OpenDC `Task` and
zero or more CPU-utilization `Fragment` records.

The image-batch application preserves that contract:

| Demo evidence | Source | Later OpenDT input |
| --- | --- | --- |
| request/run lineage | Job labels and annotations | state/run lineage |
| submission/start/finish | Kubernetes Job status | Task timing |
| requested CPU/memory | Job Pod specification | Task capacity |
| observed CPU usage | Prometheus/container metrics | Task fragments |
| image count and payload bytes | Job annotations + adapter JSONL | explanatory workload metadata |
| endpoint batch ID | endpoint/adapter events + Job annotation | pre-adapter request correlation |
| classification result | adapter `result.json` only | proof of real work; not simulator input |

The adapter's `events.jsonl` is application lineage, not a substitute for
Edward's resource observer. The next OpenDT slice should import and simplify
these units from commit `c3e1f8cd56918d8c10c4013a8b8733011323f9d7`:

1. `libs/common/odt_common/models/task.py` and `fragment.py` for the trace model.
2. The Job event extractor and terminal stream from `libs/k8s-observability`.
3. The resource-usage collector/persistence path needed to construct fragments.
4. The workload producer's conversion logic, initially targeting a local JSONL
   sink instead of requiring Kafka and the full OpenDT compose deployment.

That gives the demo a live, inspectable trace before introducing OpenDC and the
decision/actuation services. Kafka can remain an adapter at the boundary rather
than becoming a prerequisite for the first integrated run.

All duration fields use process-local monotonic clocks. `timestamp_unix_ns`
supports cross-component ordering when VM clocks are synchronized; Kubernetes
timestamps should remain authoritative for Job creation/start/completion when
deriving queue delay for the closed loop.
