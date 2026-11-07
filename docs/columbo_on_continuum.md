# Columbo On Continuum

The [agreed case manifest](reproduction_inventory.md#br23-projects-and-case-manifest) requires the minimal `call_1` full control-plane trace slice. Factual row status is in `docs/release_certification_matrix.md`. Dated results describe their recorded source. [Normal-user host procedure](smoke_runner_isolation.md)

## Purpose

This document explains how the Columbo paper functionality is represented on the reworked Continuum stack. Columbo is the ICPE 2025 paper "Columbo: A Reasoning Framework for Kubernetes' Configuration Space". The paper studies Kubernetes workload deployment, measures control-plane pipeline stages, and uses those measurements to reason about configuration bottlenecks.

For Continuum, the important engineering lesson is that this research workflow should be implemented as a composition of modules, profiles, experiments, and evidence checks. It should not require Columbo-specific code in the Continuum core.

## Module Mapping

The first certified Columbo slice is intentionally small and maps the legacy configuration `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg` to structured YAML:

| Paper/Experiment Concern | Continuum Surface |
| --- | --- |
| Local VM infrastructure for a controlled experiment | `qemu` provider profile `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Kubernetes control-plane deployment and metrics collection | `kubecontrol` software module in `configs/profiles/software/kubecontrol.yaml` |
| Synthetic benchmark workload for deployment-pipeline timing | `empty` application module |
| Per-call deployment method | `kube_deployment: call` in the `kubecontrol` module config |
| Reproducible experiment declaration | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` |
| Required release evidence | strict trace suite and wrapper scenario `qemu_kubecontrol_empty_trace_parity` |

The YAML experiment keeps the exact local-QEMU shape of the legacy `call_1` configuration: two cloud VMs, 8 cores per VM, 32 GB memory per VM, CPU pinning, Kubernetes `v1.27.0`, cached worker image setup, and one `empty` application worker.

## Core Boundary

The expected implementation boundary for this Columbo slice is:

1. provider/configuration data under `configs/`,
2. resource-manager behavior under `resource_manager/kubecontrol/`,
3. application behavior under `application/empty/`,
4. suite and wrapper metadata under `scripts/test/`,
5. release and research documentation under `docs/`.

The Continuum core should not grow Columbo-specific concepts such as Columbo rules, Columbo pipeline names, or paper-specific benchmark assumptions. If this work reveals a missing core capability, the change must be implemented as a generic framework fix, covered by focused tests, and described separately from the Columbo module work.

In the first structured slice, the shared benchmark-metrics manifest writer is part of the application runtime helper layer. The `empty` module uses that existing artifact contract to make its deployment dataframe machine-checkable; this is a module-level use of a generic evidence API, not a Columbo-specific core extension.

## BR23 instrumented Kubernetes

The current install consumes two distinct inputs. The binary override role copies a Kubernetes node tarball from a personal path under `/mnt/sdb` and installs the binaries in the guests. The control plane uses separately staged images that currently have mutable tags. The shared Kubernetes base playbook also selects the override for Kata, so review both consumers before replacing the input. [Binary override defaults](../roles/resource_manager/k8s_binary_override/defaults/main.yml) · [Shared base playbook](../playbooks/resource_manager/k8s_base_install.yml) · [Image catalog](../input/configuration/image_requirements.py)

The historical node archive at `/mnt/sdb/matthijs/kubernetes-node-linux-amd64-v1270.tar.gz` has SHA-256 `bbae85b5c1c7a5bc288adcc0289d13b2a8923b000031dfac0e0e65e5b487786d`. It contains `kubernetes/kubernetes-src.tar.gz`, SHA-256 `8d2d2d4c5c8cd57a2ad5c4b47714abd5c1127d4c7543a092e4344eb9a0cd5a38`, with the instrumented source. In a later read-only check for BR23, the archived kubelet, kubeadm and kubectl hashes and the four component image config digests in `/mnt/sdb/matthijs/archive-kube-compiled/v1270-optimized/` matched the saved identities from the strict `a1e5db2` development run. These are recovery locations and identities. The link between the recovered source and the built binaries still needs a build record. [Original run assessment](rework_release_handoff.md#packet-d-columbo--development-checkpoint)

Preserve the recovered source and exact artifacts. Identify the upstream revision and recover the instrumentation and tuning changes as a pinned source revision or patch series. Perform and document a clean build with pinned toolchain and dependencies, and record the node archive checksum and image digests. Publish or provide an approved durable acquisition path for the source and artifacts used by the public recipe. Make the selected archive and images explicit software-module inputs, verify them before installation and include their identities in base-cache validation. Keep the stock Kubernetes profile on its own inputs. Determine which artifacts Kata needs and qualify them for its selected cases. If source-to-build provenance or distribution cannot be established, bring that specific gap back for a release decision.

For acceptance, run `qemu_kubecontrol_empty_trace_parity` for the strict `call_1` case from a clean checkout with an empty eligible cache and no personal mount. Verify the installed node binaries and running control-plane image identities. Require six finite timing columns in `CLOUD OUTPUT` and the metrics artifact, tied to the current pod and its raw markers. Check that an unavailable or mismatched artifact fails before installation. Record the acquisition or build commands and verified artifacts in the Columbo project.

## Evidence Contract

The historical `qemu_kubecontrol_empty_parity` integration check used the cached `redplanet00/kubeedge-applications:empty` workload. Its documented priming command was `sh scripts/test/run_smoke_host.sh prime-registry-cache --suite qemu_kubecontrol_empty_parity`. The retained VM-backed integration evidence required:

1. Continuum reaches `phase_completed = application`,
2. experiment lock and state artifacts are written,
3. Kubernetes reaches the kubecontrol software phase and passes cluster readiness checks,
4. the `empty` benchmark finishes,
5. deployment timing output includes `CLOUD OUTPUT` and `started_application (s)`,
6. runtime logs include the kubecontrol CSV artifacts: `*_dataframe.csv`, `*_dataframe_resources.csv`, and `*_dataframe_resources_os.csv`,
7. benchmark logs include a `ContinuumBenchmarkMetrics` manifest for `CLOUD OUTPUT`.

Retained certification evidence now exists for the exact local-QEMU profile:

| Field | Value |
| --- | --- |
| Date | 2026-07-03 |
| Result | PASS |
| Duration | 948.8s |
| Result summary | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/test_results/test_results_2026-07-03_16-58-03.json` |
| Benchmark manifest | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/logs/benchmark/2026-07-03_16_42_16_empty-call_metrics_manifest.json` |
| Evidence note | `docs/release_evidence_qemu_kubecontrol_empty_2026-07-03.md` |

The July 3 retained image exposed kubelet, worker, application, and resource-utilization evidence. The legacy Columbo trace points for `apiserver`, `controller-manager`, and `scheduler` are absent from the retained control-plane logs, so the generated dataframe leaves those phase columns empty and skips the full control-plane phase plot. This row therefore certifies the Continuum module/profile/suite integration and retained evidence contract for the Columbo-style workflow, not a reproduction of every instrumented control-plane event used in the paper.

The stricter `qemu_kubecontrol_empty_trace_parity` suite is reserved for full trace evidence. It uses the same experiment directory and cache model as `qemu_kubecontrol_empty_parity`, but its success criteria require populated control-plane, kubelet, and application timing columns in both `CLOUD OUTPUT` and the benchmark metrics manifest.

Retained trace evidence now exists for the exact local-QEMU trace profile:

| Field | Value |
| --- | --- |
| Date | 2026-07-06 |
| Result | PASS |
| Duration | 742.9s |
| Result summary | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/test_results/test_results_2026-07-06_10-19-09.json` |
| Benchmark manifest | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/logs/benchmark/2026-07-06_10_06_48_empty-call_metrics_manifest.json` |
| Evidence note | `docs/release_evidence_qemu_kubecontrol_trace_2026-07-06.md` |

That row certifies the minimal local-QEMU `call_1` control-plane trace reproduction through Continuum modules, profiles, suites, and generic benchmark evidence contracts. It still does not certify every Columbo paper figure, parameter sweep, or non-QEMU provider topology.

## Reusing The Pattern

A future paper-specific Continuum integration should follow the same shape:

1. identify the provider, software/resource-manager, and application modules,
2. add or reuse profiles for those modules,
3. add one minimal experiment YAML that captures the smallest meaningful paper claim,
4. expose a named suite and retained wrapper scenario,
5. add artifact checks that validate the paper-specific output through generic Continuum evidence contracts,
6. document which files are modules/configs/docs and whether any core fixes were necessary.

This keeps Continuum marketable as a platform for distributed-systems research and education: papers can bring their own module logic and experiment profiles while the core stays focused on planning, validation, runtime handoff, state, and evidence.
