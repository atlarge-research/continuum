# QEMU Infrastructure Parity Evidence - 2026-05-31

## 1. Scope

This snapshot records VM-backed evidence for the first four old-main QEMU
infrastructure-only rows from `configuration/tests/qemu/`.

Exact release support boundaries are tracked in
`docs/release_certification_matrix.md`.

It covers only QEMU infrastructure/topology parity. It does not certify the
remaining old-main QEMU software rows for Kubernetes image/build, KubeEdge,
Mist, endpoint image/runtime, Kubernetes without benchmark, or OpenFaaS.

## 2. Source And Runner Context

| Field | Value |
| --- | --- |
| Live checkout | `/home/matthijs/continuum` |
| Git commit | `9b380abed1909aa0afad8ef32bc71a1d203941ea` |
| Tree state | Clean source tree synced to the dedicated runner |
| Dedicated repo | `/srv/continuum/repo` |
| Runner user | `continuum-smoke` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Runner base root | `/mnt/sdc/continuum_smoke` |
| Host wrapper | `/usr/local/bin/run-continuum-smoke` |
| Host maintenance helper | `/usr/local/bin/continuum-hostctl` |
| Matrix row ID | `P-QEMU-01`, `P-QEMU-02`, `P-QEMU-03`, `P-QEMU-04` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, and tc support for parity network setup; no cloud credentials. |
| Runtime targets | `infrastructure` |
| Profile IDs | Environment profiles: `local-qemu`, `local-qemu-cpupin`, `local-qemu-delete-on-exit`; software profiles: `none`, `none-edge`, `none-endpoint` |
| Date | 2026-05-31 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity` |
| Suite | `qemu_infra_parity` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_infra_parity/.continuum/test_results/test_results_2026-05-31_18-40-30.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_infra_parity/.continuum/` |

Before execution, the dedicated repo was synced from the live checkout and
verified:

1. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
2. `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`
3. `sudo -n /usr/local/bin/continuum-hostctl verify`

## 3. YAML Parity Mapping

| Matrix Row | Legacy Config | YAML Config |
| --- | --- | --- |
| `P-QEMU-01` | `configuration/tests/qemu/01_infraonly-cloud.cfg` | `configs/experiments/parity/qemu/01_infraonly_cloud.yaml` |
| `P-QEMU-02` | `configuration/tests/qemu/02_infraonly-edge.cfg` | `configs/experiments/parity/qemu/02_infraonly_edge.yaml` |
| `P-QEMU-03` | `configuration/tests/qemu/03_infraonly-endpoint.cfg` | `configs/experiments/parity/qemu/03_infraonly_endpoint.yaml` |
| `P-QEMU-04` | `configuration/tests/qemu/04_infraonly-all.cfg` | `configs/experiments/parity/qemu/04_infraonly_all.yaml` |

The edge-only and endpoint-only rows require no-op software profiles that target
the available cluster because the reworked parser validates module selectors
even when only the infrastructure phase is requested:

1. `configs/profiles/software/none-edge.yaml`
2. `configs/profiles/software/none-endpoint.yaml`

The edge-only row uses `configs/profiles/environment/local-qemu-cpupin.yaml` to
preserve the old `cpu_pin = True` provider intent.

## 4. VM-Backed Run

Command:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity
```

Result summary:

```text
/mnt/sdc/continuum_smoke/qemu_infra_parity/.continuum/test_results/test_results_2026-05-31_18-40-30.json
```

| Matrix Row | YAML Config | Result | Evidence |
| --- | --- | --- | --- |
| `P-QEMU-01` | `configs/experiments/parity/qemu/01_infraonly_cloud.yaml` | PASS, 68.7s | `experiment_lock_written`, `state_file_written`, `state_phase=infrastructure`, `resume_contract_match` |
| `P-QEMU-02` | `configs/experiments/parity/qemu/02_infraonly_edge.yaml` | PASS, 99.0s | `experiment_lock_written`, `state_file_written`, `state_phase=infrastructure`, `resume_contract_match` |
| `P-QEMU-03` | `configs/experiments/parity/qemu/03_infraonly_endpoint.yaml` | PASS, 129.5s | `experiment_lock_written`, `state_file_written`, `state_phase=infrastructure`, `resume_contract_match` |
| `P-QEMU-04` | `configs/experiments/parity/qemu/04_infraonly_all.yaml` | PASS, 153.7s | `experiment_lock_written`, `state_file_written`, `state_phase=infrastructure`, `resume_contract_match` |

Total suite time: 450.9s.

## 5. Certification Result

The following old-main parity rows are certified for the current rework branch
and local QEMU/libvirt runner:

1. `P-QEMU-01`
2. `P-QEMU-02`
3. `P-QEMU-03`
4. `P-QEMU-04`

If QEMU infrastructure runtime, parser selector behavior, provider profiles, or
these YAML parity configs change before publication, rerun
`qemu_infra_parity`.
