# Kube Kata On Continuum

## Purpose

This document records the first rework slice for the legacy Kata startup
experiments. The slice is intentionally narrow: local QEMU, `kube_kata`,
`empty_kata`, `kata-qemu`, `overlayfs`, two cloud VMs, and the minimal startup
benchmark shape from:

```text
configuration/experiment_kata/1_startup_performance/strong_scalability/node_1_kata_qemu_overlayfs.cfg
```

It is not evidence for every legacy Kata experiment, every runtime/filesystem
combination, or broader resource-usage sweeps.

## Module Mapping

| Legacy Concern | Rework Surface |
| --- | --- |
| Local QEMU VM infrastructure with CPU pinning and cleanup | `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml` |
| Kata-enabled Kubernetes resource manager | `configs/profiles/software/kube-kata.yaml` |
| Runtime selection | `runtime: kata-qemu` |
| Runtime filesystem | `runtime_filesystem: overlayfs` |
| Synthetic startup workload | `empty_kata` benchmark stage |
| Structured experiment | `configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml` |
| Candidate suite and wrapper scenario | `qemu_kube_kata_empty_startup_parity` |

The YAML keeps the legacy candidate shape: two cloud VMs, 8 cores per VM, 64 GB
memory per VM, CPU quota `1.0`, Kubernetes `v1.27.0`, pod deployment mode,
`applications_per_worker: 100`, and `sleep_time: 180`.

## Host Prerequisites

The candidate suite requires the dedicated local runner model from
`docs/smoke_runner_isolation.md`:

1. `continuum-smoke` through `/usr/local/bin/run-continuum-smoke`,
2. `/dev/kvm` and nested KVM enabled on the physical host,
3. local QEMU/libvirt and SSH access,
4. enough local capacity for two 8-core / 64 GiB guests plus host overhead,
5. control-plane images, `ansk/empty:empty`, and
   `jaegertracing/all-in-one:1.47` in the local registry cache,
6. guest containerd/Kata setup through `playbooks/resource_manager/kata_setup.yml`,
7. guest network access to download the Kata static release unless separately cached.

`kata-fc` with `overlayfs` is explicitly excluded. The `kube_kata` verifier
rejects that combination and requires `runtime_filesystem: devmapper` for
future `kata-fc` work.

## Evidence Contract

The row remains a candidate until a retained wrapper run proves all of these:

1. `phase_completed = application` in the test-result summary,
2. experiment lock and state artifacts,
3. Kubernetes cluster readiness,
4. RuntimeClass objects for `kata-qemu`, `kata-fc`, and `runc`,
5. guest `/dev/kvm`, Kata runtime binary, and containerd `kata-qemu` runtime stanza,
6. `empty_kata` application success,
7. runtime CSVs including `*_dataframe.csv`, `*_dataframe_resources.csv`,
   `*_dataframe_resources_os.csv`, and `*_dataframe_kata.csv`,
8. benchmark metric manifest with `CLOUD OUTPUT` and `KATA OUTPUT`, each with
   at least 100 rows,
9. teardown proof from the wrapper suite.

Before the VM run, use:

```bash
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_kube_kata_empty_startup_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_kube_kata_empty_startup_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  check-prereqs --suite qemu_kube_kata_empty_startup_parity
```

Run the candidate only through:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kube_kata_empty_startup_parity
```

## Current Status

The structured profile, experiment, suite contract, wrapper scenario, cache
mapping, host prerequisite check, Jaeger setup, and artifact contract exist. The
matrix row `M2-QEMU-KUBE-KATA-EMPTY` is certified for the exact local-QEMU
`kata-qemu` plus `overlayfs` slice by:

```text
docs/release_evidence_qemu_kube_kata_empty_2026-07-09.md
```

Retained wrapper attempts on 2026-07-09 narrowed the remaining blocker:

1. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_14-16-25.json`
   failed because the exact 100-pod Kata workload did not reach Running within
   the original 900-second readiness window.
2. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_14-55-06.json`
   used `worker_ready_timeout_seconds: 2400`; the workload reached benchmark
   completion, but `kube_kata.get_kata_timestamps()` failed to connect to the
   worker Jaeger API at `192.168.100.3:16686`.
3. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_19-35-42.json`
   verified the worker Jaeger API was reachable and collected 171 traces, but
   the legacy parser still assumed every trace had exactly two `StartVM` spans.
4. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_20-09-09.json`
   skipped incomplete Jaeger traces and completed Continuum cleanup, but the
   retained artifact check rejected `KATA OUTPUT` because only 61 complete rows
   were available immediately after benchmark output collection.
5. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_20-46-27.json`
   added bounded Jaeger trace retries. The run reached 100 complete Kata
   timestamp rows after five fetches, then failed later in `empty_kata`
   control-plane output formatting with many rows missing kubelet/application
   timestamps.
6. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_21-25-22.json`
   passed after `empty_kata` preserved partial control-plane metrics while still
   writing `CLOUD OUTPUT` and Jaeger-derived `KATA OUTPUT` artifacts. The
   retained benchmark manifest is
   `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/logs/benchmark/2026-07-09_20_51_51_empty-kata-pod_metrics_manifest.json`.

The certified slice proves host prerequisites, cluster readiness, RuntimeClass
installation, guest Kata runtime setup, a working Jaeger query API, the exact
100-pod application path, cleanup, and accepted `CLOUD OUTPUT` and
`KATA OUTPUT` benchmark artifacts in the same retained wrapper result.

Jaeger trace support is part of the certification contract. The legacy Kata
path used `jaegertracing/all-in-one:1.47` with the query API on TCP `16686`,
collector ports `14250`, `14268`, `14269`, Zipkin `9411`, OTLP `4317`/`4318`,
agent UDP `6831`/`6832`, and `--query.max-clock-skew-adjustment=20s`. The
reviewed rework role now starts that service on each Kata worker from the
primed local registry and verifies `http://<worker-ip>:16686/api/services`
during the software post hook. The current `kube_kata` code retries Jaeger trace
fetches until it sees the expected complete row count or exhausts the bounded
retry window.

This candidate does not claim `kata-fc`, devmapper, non-QEMU providers,
multi-host physical capacity, Columbo rows, resource-usage sweeps, or every
legacy Kata parameter sweep.
