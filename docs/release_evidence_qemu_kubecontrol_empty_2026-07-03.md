# QEMU Kubecontrol Empty Evidence - 2026-07-03

## Scope

This evidence certifies research case-study row
`M2-QEMU-KUBECONTROL-EMPTY` in `docs/release_certification_matrix.md`.

It proves that the rework stack can provision the Columbo-style local QEMU
`kubecontrol` profile, complete the software phase, run the `empty`
application in per-call deployment mode, and emit retained benchmark evidence
without adding Columbo-specific concepts to the Continuum core.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `M2-QEMU-KUBECONTROL-EMPTY` |
| Git commit | dirty source tree based on `8cc99c3 refresh release evidence for pretag` |
| Tree state | Source tree with the Columbo/kubecontrol port synced to the dedicated runner before this evidence bundle was committed |
| Date | 2026-07-03 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, wrapper install, host verification, and registry-cache preflight |
| Config | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` |
| Suite | `qemu_kubecontrol_empty_parity` |
| Software profile | `configs/profiles/software/kubecontrol.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host, `/dev/kvm` access, SSH access, local registry cache primed for the suite, and enough CPU/RAM/disk under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, kubecontrol software-phase readiness, application phase evidence, benchmark metric table, and benchmark metrics manifest |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/test_results/test_results_2026-07-03_16-58-03.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/` |

## Result

The retained VM-backed run passed:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml` | PASS | 948.8s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, benchmark evidence found, benchmark metric tables found |

Benchmark metric artifact:

```text
/mnt/sdc/continuum_smoke/qemu_kubecontrol_empty_parity/.continuum/logs/benchmark/2026-07-03_16_42_16_empty-call_metrics_manifest.json
```

## What This Claims

This row may be described as:

1. Continuum can run the Columbo-style `kubecontrol` plus `empty` module
   composition on the exact two-cloud-VM local-QEMU profile.
2. The `kubecontrol` software phase reaches Kubernetes cluster readiness.
3. The `empty` application completes in per-call deployment mode.
4. The run reaches `phase_completed = application` and writes the standard
   experiment lock, state, resume-contract, stdout, and benchmark evidence
   artifacts.
5. The benchmark metric artifact records the `CLOUD OUTPUT` table with
   `started_application (s)`.
6. The implementation uses profiles, resource-manager/application modules,
   suite metadata, and docs; it does not introduce Columbo-specific core
   framework concepts.

## Limitations

This evidence does not certify:

1. a full reproduction of all Columbo paper figures or parameter sweeps,
2. GCP, AWS, or bare-metal behavior for this workflow,
3. legacy `.cfg` execution of `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`,
4. retained legacy trace points for `apiserver`, `controller-manager`, or
   `scheduler`; the retained image exposes kubelet, worker, application, and
   resource-utilization evidence, and the generated dataframe leaves the
   unavailable control-plane phase columns empty,
5. `empty_kata` or broader kube_kata behavior.
