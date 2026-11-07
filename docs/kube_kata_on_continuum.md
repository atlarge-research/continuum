# Kube Kata On Continuum

Current policy is `docs/rework_milestone_release_plan.md`; factual status is `docs/release_certification_matrix.md`. Use the normal-user exports/procedure in `docs/smoke_runner_isolation.md`. Dated results below remain historical; they do not certify the migrated candidate or every legacy Kata variant.

## Purpose

This document records the first rework slice for the legacy Kata startup experiments. The slice is intentionally narrow: local QEMU, `kube_kata`, `empty_kata`, `kata-qemu`, `overlayfs`, two cloud VMs, and the minimal startup benchmark shape from:

```text
configuration/experiment_kata/1_startup_performance/strong_scalability/node_1_kata_qemu_overlayfs.cfg
```

It is not evidence for every legacy Kata experiment, every runtime/filesystem combination, or broader resource-usage sweeps.

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

The YAML keeps the legacy candidate shape: two cloud VMs, 8 cores per VM, 64 GB memory per VM, CPU quota `1.0`, Kubernetes `v1.27.0`, pod deployment mode, `applications_per_worker: 100`, and `sleep_time: 180`.

## Host Prerequisites

The candidate suite requires the normal-user physical-host workflow from `docs/smoke_runner_isolation.md`:

1. the normal user through `sh scripts/test/run_smoke_host.sh`,
2. `/dev/kvm` and nested KVM enabled on the physical host,
3. local QEMU/libvirt and SSH access,
4. enough local capacity for two 8-core / 64 GiB guests plus host overhead,
5. control-plane images, `ansk/empty:empty`, and `jaegertracing/all-in-one:1.47` in the local registry cache,
6. guest containerd/Kata setup through `playbooks/resource_manager/kata_setup.yml`,
7. guest network access to download the Kata static release unless separately cached.

`kata-fc` with `overlayfs` is explicitly excluded. The `kube_kata` verifier rejects that combination and requires `runtime_filesystem: devmapper` for the selected `kata-fc` cases. [Thesis reproduction](#br23-thesis-reproduction)

## Evidence Contract

The row remains a candidate until a retained wrapper run proves all of these:

1. `phase_completed = application` in the test-result summary,
2. experiment lock and state artifacts,
3. Kubernetes cluster readiness,
4. RuntimeClass objects for `kata-qemu`, `kata-fc`, and `runc`,
5. guest `/dev/kvm`, Kata runtime binary, and containerd `kata-qemu` runtime stanza,
6. `empty_kata` application success,
7. runtime CSVs including `*_dataframe.csv`, `*_dataframe_resources.csv`, `*_dataframe_resources_os.csv`, and `*_dataframe_kata.csv`,
8. benchmark metric manifest with `CLOUD OUTPUT` and `KATA OUTPUT`, each with at least 100 rows,
9. teardown proof from the wrapper suite.

Before the VM run, use:

```bash
sh scripts/test/setup_agent_host.sh verify
sh scripts/test/run_smoke_host.sh prime-registry-cache --suite qemu_kube_kata_empty_startup_parity
sh scripts/test/run_smoke_host.sh \
  prime-registry-cache --check-only --suite qemu_kube_kata_empty_startup_parity
sh scripts/test/run_smoke_host.sh \
  check-prereqs --suite qemu_kube_kata_empty_startup_parity
```

Run the candidate only through:

```bash
sh scripts/test/run_smoke_host.sh qemu_kube_kata_empty_startup_parity
```

## Current Status

The structured profile, experiment, suite contract, wrapper scenario, cache mapping, host prerequisite check, Jaeger setup, and artifact contract exist. The matrix row `M2-QEMU-KUBE-KATA-EMPTY` is certified for the exact local-QEMU `kata-qemu` plus `overlayfs` slice by:

```text
docs/release_evidence_qemu_kube_kata_empty_2026-07-09.md
```

Retained wrapper attempts on 2026-07-09 narrowed the remaining blocker:

1. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_14-16-25.json` failed because the exact 100-pod Kata workload did not reach Running within the original 900-second readiness window.
2. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_14-55-06.json` used `worker_ready_timeout_seconds: 2400`; the workload reached benchmark completion, but `kube_kata.get_kata_timestamps()` failed to connect to the worker Jaeger API at `192.168.100.3:16686`.
3. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_19-35-42.json` verified the worker Jaeger API was reachable and collected 171 traces, but the legacy parser still assumed every trace had exactly two `StartVM` spans.
4. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_20-09-09.json` skipped incomplete Jaeger traces and completed Continuum cleanup, but the retained artifact check rejected `KATA OUTPUT` because only 61 complete rows were available immediately after benchmark output collection.
5. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_20-46-27.json` added bounded Jaeger trace retries. The run reached 100 complete Kata timestamp rows after five fetches, then failed later in `empty_kata` control-plane output formatting with many rows missing kubelet/application timestamps.
6. `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_21-25-22.json` passed after `empty_kata` preserved partial control-plane metrics while still writing `CLOUD OUTPUT` and Jaeger-derived `KATA OUTPUT` artifacts. The retained benchmark manifest is `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/logs/benchmark/2026-07-09_20_51_51_empty-kata-pod_metrics_manifest.json`.

The certified slice proves host prerequisites, cluster readiness, RuntimeClass installation, guest Kata runtime setup, a working Jaeger query API, the exact 100-pod application path, cleanup, and accepted `CLOUD OUTPUT` and `KATA OUTPUT` benchmark artifacts in the same retained wrapper result.

Jaeger trace support is part of the certification contract. The legacy Kata path used `jaegertracing/all-in-one:1.47` with the query API on TCP `16686`, collector ports `14250`, `14268`, `14269`, Zipkin `9411`, OTLP `4317`/`4318`, agent UDP `6831`/`6832`, and `--query.max-clock-skew-adjustment=20s`. The reviewed rework role now starts that service on each Kata worker from the primed local registry and verifies `http://<worker-ip>:16686/api/services` during the software post hook. The current `kube_kata` code retries Jaeger trace fetches until it sees the expected complete row count or exhausts the bounded retry window.

This candidate does not claim `kata-fc`, devmapper, non-QEMU providers, multi-host physical capacity, Columbo rows, resource-usage sweeps, or every legacy Kata parameter sweep.

## BR23 thesis reproduction

Reproduce the published experiments from Antonios Sklavos's *Exploring the Performance of Kubernetes-Deployed Containers* on local QEMU before merge. The three main runtime configurations are runc, Kata-QEMU/overlayfs and Kata-Firecracker/devmapper. Use the thesis for experiment shapes and archived inputs for unspecified settings. Use one physical host per run as in the thesis and bring any proposed distributed adaptation to review. Record disagreements, especially guest sizing and pinning, before comparing arms. Keep R04 as its exact operational gate and retain the separately agreed one-worker QEMU/devmapper comparison. [Evaluation](https://atlarge-research.com/pdfs/2023-asklavos-msc_thesis.pdf#page=33) · [Archived configurations](../configuration/experiment_kata)

| Published result | BR23 runs and outputs |
| --- | --- |
| Startup, Figs. 5.1 and 5.6 | Run all three runtime configurations with one, two and four workers. Strong scaling uses 100 pods total, split 100/50/25 per worker. Weak scaling uses 25 pods per worker. Measure from workload submission until the last requested pod reaches Running and verify worker assignments. The four-worker inputs coincide in the archive. Share a run only if the effective configuration and measurement protocol agree. |
| Startup breakdown, Figs. 5.2–5.5 | Produce per-pod timing breakdowns from the two-worker, 100-pod runs for the three main configurations. Add the two-worker Kata-QEMU/devmapper run at 50 pods per worker. Join Kubernetes and applicable runtime trace records to each current pod identity on both workers. Flag missing phases and reject unrelated traces. Retain the previously agreed one-worker Kata-QEMU/devmapper case at 100 pods for the same-hypervisor storage comparison and the same-snapshotter hypervisor comparison. |
| Memory, Tables 5.1 and 7.1 | Use 100 pods on one worker for each of the three main runtime configurations. Regenerate the per-pod footprint estimate and its comparison with runc. Use the published count of 100 where the archive specifies 50. |
| CPU, Figs. 5.8 and 5.9 | For each main runtime, run 60-second stress workloads across one, two and four workers. Strong scaling uses eight pods total, split 8/4/2 per worker. Weak scaling uses eight pods per worker. Start from `b_cpu_micro`, reconcile the two-worker Kata-QEMU CPU allocation difference and share identical one-worker cases when both protocols agree. Plot end-to-end Job duration. Keep the pinned equivalent of the stress image listing in Fig. 5.7. |
| Derived results, Figs. 7.1 and 7.2 | Regenerate the startup and CPU overhead comparisons from the fresh runs and their corresponding runc baselines. Record the source cases and calculation behind each plotted value. |
| Reported capacity limit, §5.2 | Attempt the reported single-worker, 1,000-replica setup with a 128-GiB worker when capacity permits, using a disposable allocation and a bounded observation window. Record configured pod slots, background pods, observed Running and Pending counts and scheduler reasons. Document the effect of the run's collector where it can be isolated. The observed limit is the result. Record any capacity constraint that prevents the attempt. |

Put the case manifest and figure generation in `projects/<kata-study>/`. Use canonical YAML and the normal CLI to run cases. Let benchmark procedures capture portable per-run data, and have project analysis read those artifacts, validate coverage, and generate the figures, tables and a comparison with the thesis. Pilot the runtimes and largest shapes before the sweep. Record effective placement, physical-core pinning, limits, versions, image digests and trace coverage. Keep failed and incomplete attempts visible, and bring any case that cannot be reproduced to release review with the observed blocker and its effect on the figures. Additional archived runtime and workload combinations remain provenance. [Published comparison](https://atlarge-research.com/pdfs/2023-asklavos-msc_thesis.pdf#page=46) · [Benchmark and result design](runtime_execution_pipeline.md#br23-benchmark-procedure-and-results)

## BR23 devmapper startup cases

Restore `kata-fc/devmapper` and `kata-qemu/devmapper` for the published cases and the one-worker R07 comparison. The active Kata playbook already installs both shims and registers their RuntimeClasses. Use the historical playbook as a reference for the thin-pool setup removed during role extraction. Provision a separate guest pool for each case with the same role and settings. Configure containerd before workload image pulls and pod launch. Reuse the pool on retries only when its live device mappings match the guest-owned backing files, and fail on an ownership conflict. Restore the pool before containerd starts after a guest reboot. [R07 scope](reproduction_inventory.md#additional-nominated-workflows) · [Historical playbook](https://github.com/atlarge-research/continuum/blob/a9cf8e114e7862dedd8e84599d9ceffaed37bc5d/resource_manager/kube_kata/cloud/install_kata_containers.yml) · [Active Kata playbook](../playbooks/resource_manager/kata_setup.yml)

Start with a one-pod pilot on a fresh QEMU allocation for each variant. Verify nested KVM, worker readiness and pool capacity. Tie each pod's RuntimeClass and startup evidence to the actual VMM process and devmapper-backed sandbox. Repeat the role and check the pool and pod path after a guest reboot. Use a fresh QEMU allocation for each full run. Match the workload image, worker sizing and cache conditions, collect startup milestones for all requested pods, retain Kata-specific traces, and verify teardown. Use runc as the baseline. Compare the two Kata-QEMU runs to assess the storage change and the two devmapper runs to compare the hypervisor configurations with storage held constant. [One-worker QEMU/devmapper input](../configuration/experiment_kata/1_startup_performance/strong_scalability/kata_qemu_devmapper/node_1_kata_qemu_devmapper.cfg) · [Two-worker QEMU/devmapper input](../configuration/experiment_kata/1_startup_performance/strong_scalability/kata_qemu_devmapper/node_2_kata_qemu_devmapper.cfg) · [Upstream Firecracker setup](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-kata-containers-with-firecracker.md)

## BR23 memory comparison

Run 100 pods per runtime for runc, Kata-QEMU/overlayfs and Kata-Firecracker/devmapper, using one worker in a fresh QEMU allocation per case. Port `mem_usage` to one terminating benchmark procedure for all three configurations, with one workload deployment, a bounded wait for its own pods and cleanup of its own resources. Verify the effective runtime, snapshotter and image digest. Match worker sizing, effective resource requests and limits, cache state and measurement conditions. Check allocatable resources and pod slots after system pods and runtime overhead. [Current memory workload](../application/mem_usage/mem_usage.py) · [Thesis method](https://atlarge-research.com/pdfs/2023-asklavos-msc_thesis.pdf#page=36)

Sample whole-worker `MemFree` after setup has settled, then sample again using the same window once all 100 owned pods are simultaneously Ready on that worker. Retain the raw readings, observed pod count, timing and any background differences. Report the decrease in free memory per observed pod as a workload footprint estimate that includes runtime effects. Treat fewer than 100 Ready pods as an incomplete run. [Archived 50-pod runc input](../configuration/experiment_kata/3_resource_usage/a_memory/runc.cfg) · [Archived 50-pod Kata input](../configuration/experiment_kata/3_resource_usage/a_memory/kata_qemu_overlayfs.cfg)
