# QEMU Kubernetes No-Benchmark Parity Evidence - 2026-06-01

## 1. Scope

This snapshot records VM-backed evidence for old-main QEMU parity row
`P-QEMU-09`, derived from
`configuration/tests/qemu/09_kubernetes-nobench.cfg`.

Exact release support boundaries are tracked in
`docs/release_certification_matrix.md`.

It covers QEMU infrastructure, Kubernetes software installation, endpoint
runtime placement required by the rework selector contract, and the
observability addon. It does not certify the remaining QEMU application,
KubeEdge, Mist, endpoint-only application, or OpenFaaS rows.

## 2. Source And Runner Context

| Field | Value |
| --- | --- |
| Live checkout | `/home/matthijs/continuum` |
| Git commit | `cf1e4d27a3745c6aab80353c5ac93a927cc56974` |
| Tree state | Clean source tree synced to the dedicated runner |
| Dedicated repo | `/srv/continuum/repo` |
| Runner user | `continuum-smoke` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Runner base root | `/mnt/sdc/continuum_smoke` |
| Host wrapper | `/usr/local/bin/run-continuum-smoke` |
| Host maintenance helper | `/usr/local/bin/continuum-hostctl` |
| Matrix row ID | `P-QEMU-09` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, and SSH access for Kubernetes/observability software execution; no cloud credentials. |
| Runtime targets | `infrastructure`, `software` |
| Provider profile | `configs/profiles/environment/local-qemu.yaml` |
| Software profile | `configs/profiles/software/k8s-observability-endpoint-runtime.yaml` |
| Date | 2026-06-01 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity` |
| Config | `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml` |
| Suite | `qemu_k8s_nobench_parity` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Kubernetes node-ready and observability software-phase evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_k8s_nobench_parity/.continuum/test_results/test_results_2026-06-01_16-01-12.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_k8s_nobench_parity/.continuum/` |

Before the final passing execution, the dedicated repo was synced from the live
checkout and verified:

1. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
2. `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`
3. `sudo -n /usr/local/bin/continuum-hostctl verify`

## 3. YAML Parity Mapping

| Matrix Row | Legacy Config | YAML Config |
| --- | --- | --- |
| `P-QEMU-09` | `configuration/tests/qemu/09_kubernetes-nobench.cfg` | `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml` |

The rework YAML profile is
`configs/profiles/software/k8s-observability-endpoint-runtime.yaml`.

The profile includes `endpoint_runtime` because the reworked selector contract
requires endpoint resources in a software-phase run to have an endpoint runtime
module placement. The old `.cfg` expressed this row as
`resource_manager_only = True` with endpoint nodes and `observability = True`.

## 4. Defects Exposed Before Certification

The row initially failed twice before the earlier 2026-05-31 certification run:

1. Endpoint base-image installation reused
   `playbooks/resource_manager/endpoint_install.yml`, whose host pattern also
   targeted live endpoint VMs. During base-image creation those VMs were not
   reachable yet. The fix split base-image endpoint preparation into
   `playbooks/resource_manager/endpoint_base_install.yml` and kept
   `endpoint_install.yml` scoped to live `endpoints`.
2. The observability role applied `/kube-prometheus/...` manifests without
   ensuring the kube-prometheus checkout existed. After adding a pinned
   `release-0.13` checkout, client-side CRD apply failed on annotation-size
   limits. The fix uses server-side apply for the setup manifests.

These fixes remain part of the evidence scope for this row.

## 5. VM-Backed Run

Command:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity
```

Result summary:

```text
/mnt/sdc/continuum_smoke/qemu_k8s_nobench_parity/.continuum/test_results/test_results_2026-06-01_16-01-12.json
```

| Matrix Row | YAML Config | Result | Evidence |
| --- | --- | --- | --- |
| `P-QEMU-09` | `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml` | PASS, 1622.8s | `exit_code=0`, `ssh_output_found`, `experiment_lock_written`, `state_file_written`, `state_phase=software`, `resume_contract_match` |

## 6. Certification Result

`P-QEMU-09` is certified for the current rework branch and local QEMU/libvirt
runner.

If QEMU infrastructure, Kubernetes software planning, endpoint-runtime base/live
installation, observability role behavior, or this YAML parity config changes
before publication, rerun `qemu_k8s_nobench_parity`.
