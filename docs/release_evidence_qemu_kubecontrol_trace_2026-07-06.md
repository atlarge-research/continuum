# QEMU Kubecontrol Trace Evidence - 2026-07-06

## Scope

This evidence certifies research case-study row
`M2-QEMU-KUBECONTROL-TRACE` in `docs/release_certification_matrix.md`.

It proves that the rework stack can run the strict Columbo-style local QEMU
`kubecontrol` plus `empty` application workflow and satisfy the full
control-plane trace evidence contract for the minimal per-call deployment
experiment.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `M2-QEMU-KUBECONTROL-TRACE` |
| Git commit | `ccc8e92e328f973bda72332236cc1315f06613bb` |
| Tree state | Clean source tree synced to the dedicated runner after the retained-wrapper prerequisite fix. |
| Date | 2026-07-06 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_trace_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, host verification, trace-suite prerequisite check, and registry-cache preflight. |
| Config | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` |
| Suite | `qemu_kubecontrol_empty_trace_parity` |
| Software profile | `configs/profiles/software/kubecontrol.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host, `/dev/kvm` access, SSH access, local registry cache primed for the suite, a current root-owned `continuum-hostctl` helper, a healthy noninteractive sudo path for the operator checks, and enough CPU/RAM/disk under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, kubecontrol software-phase readiness, application phase evidence, strict `CLOUD OUTPUT` timing table, and benchmark metrics manifest with required control-plane, kubelet, and application timing columns. |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/test_results/test_results_2026-07-06_10-19-09.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/` |
| Benchmark metric manifest | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/logs/benchmark/2026-07-06_10_06_48_empty-call_metrics_manifest.json` |

## Result

The retained VM-backed run passed:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` | PASS | 742.9s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, benchmark evidence found, benchmark metric tables found, benchmark metric artifacts found |

The strict suite success criteria require the `CLOUD OUTPUT` table and benchmark
metric artifact to contain populated numeric values for:

1. `controller_read_workload (s)`,
2. `controller_unpacked_workload (s)`,
3. `scheduler_read_pod (s)`,
4. `kubelet_pod_received (s)`,
5. `kubelet_applied_sandbox (s)`,
6. `started_application (s)`.

The runner reported the benchmark metric manifest at:

```text
/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_trace_parity/.continuum/logs/benchmark/2026-07-06_10_06_48_empty-call_metrics_manifest.json
```

## What This Claims

This row may be described as:

1. Continuum can run the strict Columbo-style `kubecontrol` plus `empty`
   control-plane trace workflow on the local-QEMU profile.
2. The run reaches `phase_completed = application` and writes the standard
   lock, state, resume-contract, stdout, and benchmark evidence artifacts.
3. The suite-level evidence gate confirms populated controller, scheduler,
   kubelet, and application timing columns in both retained stdout and
   benchmark metric artifacts.
4. The implementation remains a composition of Continuum modules, profiles,
   experiments, suites, and docs; it does not add Columbo-specific concepts to
   the Continuum core.

## Limitations

This evidence does not certify:

1. every Columbo paper parameter sweep or figure,
2. GCP, AWS, bare-metal, or multi-host behavior for this workflow,
3. legacy `.cfg` execution of
   `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`,
4. broader `kubecontrol` application coverage outside this minimal `empty`
   per-call experiment,
5. `empty_kata`, `kube_kata`, or resource-usage applications.
