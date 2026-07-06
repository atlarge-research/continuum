# Columbo On Continuum

## Purpose

This document explains how the Columbo paper functionality is represented on
the reworked Continuum stack. Columbo is the ICPE 2025 paper "Columbo: A
Reasoning Framework for Kubernetes' Configuration Space". The paper studies
Kubernetes workload deployment, measures control-plane pipeline stages, and
uses those measurements to reason about configuration bottlenecks.

For Continuum, the important engineering lesson is that this research workflow
should be implemented as a composition of modules, profiles, experiments, and
evidence checks. It should not require Columbo-specific code in the Continuum
core.

## Module Mapping

The first certified Columbo slice is intentionally small and maps the legacy
configuration
`configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`
to structured YAML:

| Paper/Experiment Concern | Continuum Surface |
| --- | --- |
| Local VM infrastructure for a controlled experiment | `qemu` provider profile `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Kubernetes control-plane deployment and metrics collection | `kubecontrol` software module in `configs/profiles/software/kubecontrol.yaml` |
| Synthetic benchmark workload for deployment-pipeline timing | `empty` application module |
| Per-call deployment method | `kube_deployment: call` in the `kubecontrol` module config |
| Reproducible experiment declaration | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` |
| Retained release evidence | suite and wrapper scenario `qemu_kubecontrol_empty_parity` |

The YAML experiment keeps the exact local-QEMU shape of the legacy `call_1`
configuration: two cloud VMs, 8 cores per VM, 32 GB memory per VM, CPU pinning,
Kubernetes `v1.27.0`, cached worker image setup, and one `empty` application
worker.

## Core Boundary

The expected implementation boundary for this Columbo slice is:

1. provider/configuration data under `configs/`,
2. resource-manager behavior under `resource_manager/kubecontrol/`,
3. application behavior under `application/empty/`,
4. suite and wrapper metadata under `scripts/test/`,
5. release and research documentation under `docs/`.

The Continuum core should not grow Columbo-specific concepts such as Columbo
rules, Columbo pipeline names, or paper-specific benchmark assumptions. If this
work reveals a missing core capability, the change must be implemented as a
generic framework fix, covered by focused tests, and described separately from
the Columbo module work.

In the first structured slice, the shared benchmark-metrics manifest writer is
part of the application runtime helper layer. The `empty` module uses that
existing artifact contract to make its deployment dataframe machine-checkable;
this is a module-level use of a generic evidence API, not a Columbo-specific
core extension.

## Evidence Contract

The `qemu_kubecontrol_empty_parity` suite is the evidence gate for this slice.
Because the dedicated smoke user does not access Docker directly, the local
registry cache must first contain `redplanet00/kubeedge-applications:empty`
through the reviewed `continuum-hostctl prime-registry-cache --suite
qemu_kubecontrol_empty_parity` path. A retained VM-backed run must prove:

1. Continuum reaches `phase_completed = application`,
2. experiment lock and state artifacts are written,
3. Kubernetes reaches the kubecontrol software phase and passes cluster
   readiness checks,
4. the `empty` benchmark finishes,
5. deployment timing output includes `CLOUD OUTPUT` and
   `started_application (s)`,
6. runtime logs include the kubecontrol CSV artifacts:
   `*_dataframe.csv`, `*_dataframe_resources.csv`, and
   `*_dataframe_resources_os.csv`,
7. benchmark logs include a `ContinuumBenchmarkMetrics` manifest for
   `CLOUD OUTPUT`.

Retained certification evidence now exists for the exact local-QEMU profile:

| Field | Value |
| --- | --- |
| Date | 2026-07-03 |
| Result | PASS |
| Duration | 948.8s |
| Result summary | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/test_results/test_results_2026-07-03_16-58-03.json` |
| Benchmark manifest | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/logs/benchmark/2026-07-03_16_42_16_empty-call_metrics_manifest.json` |
| Evidence note | `docs/release_evidence_qemu_kubecontrol_empty_2026-07-03.md` |

The retained image currently exposes kubelet, worker, application, and
resource-utilization evidence. The legacy Columbo trace points for
`apiserver`, `controller-manager`, and `scheduler` are absent from the
retained control-plane logs, so the generated dataframe leaves those phase
columns empty and skips the full control-plane phase plot. This row therefore
certifies the Continuum module/profile/suite integration and retained evidence
contract for the Columbo-style workflow, not a reproduction of every
instrumented control-plane event used in the paper.

The stricter `qemu_kubecontrol_empty_trace_parity` suite is reserved for full
trace evidence. It uses the same experiment directory and cache model as
`qemu_kubecontrol_empty_parity`, but its success criteria require populated
control-plane, kubelet, and application timing columns in both `CLOUD OUTPUT`
and the benchmark metrics manifest. That suite is the next VM-backed gate for
claiming paper-level trace reproduction; the July 3 retained evidence above
remains the certified module/profile/suite integration slice.

## Reusing The Pattern

A future paper-specific Continuum integration should follow the same shape:

1. identify the provider, software/resource-manager, and application modules,
2. add or reuse profiles for those modules,
3. add one minimal experiment YAML that captures the smallest meaningful paper
   claim,
4. expose a named suite and retained wrapper scenario,
5. add artifact checks that validate the paper-specific output through generic
   Continuum evidence contracts,
6. document which files are modules/configs/docs and whether any core fixes were
   necessary.

This keeps Continuum marketable as a platform for distributed-systems research
and education: papers can bring their own module logic and experiment profiles
while the core stays focused on planning, validation, runtime handoff, state,
and evidence.
