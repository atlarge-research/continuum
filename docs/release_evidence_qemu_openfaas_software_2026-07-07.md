# QEMU OpenFaaS Software Evidence - 2026-07-06

## Scope

This evidence certifies the software-only local row `P-QEMU-10-SW-LOCAL` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision a single-host QEMU variant of the
legacy P-QEMU-10 node counts and complete the Kubernetes, OpenFaaS, and endpoint
runtime software phase. The variant keeps three cloud VMs and four endpoint VMs,
but lowers cloud VM cores from the legacy value of 6 to 4 so the suite fits the
dedicated runner's 20-core single-host limit.

It does not certify the exact legacy CPU shape or the full OpenFaaS
image-classification application benchmark from
`configuration/tests/qemu/10_kubernetes-openfaas.cfg`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-10-SW-LOCAL` |
| Git commit | `dfa3f6bb5a8faaf0c3955bb48e053fb8a5a1b102` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-07 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Config | `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml` |
| Suite | `qemu_openfaas_software_parity` |
| Software profile | `configs/profiles/software/k8s-openfaas.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, and enough local CPU capacity for the capped single-host OpenFaaS shape; no cloud credentials. |
| Runtime targets | `infrastructure`, `software` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Kubernetes node-ready and OpenFaaS software-phase evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_openfaas_software_parity/.continuum/test_results/test_results_2026-07-07_12-05-50.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_openfaas_software_parity/.continuum/` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml` | PASS | 1473.4s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched |

The experiment lock records:

1. three cloud VMs with 4 cores and 4 GB memory each,
2. four endpoint VMs with 2 cores and 2 GB memory each,
3. `cpu_pin: true`,
4. no network emulation,
5. `k8s-main`, `openfaas-main`, and `endpoint-runtime` software modules.

The retained runner summary records `exit_code=0`, `ssh_output_found`,
`experiment_lock_written`, `state_file_written`, `state_phase=software`, and
`resume_contract_match`. The retained stdout records the Kubernetes, OpenFaaS,
and endpoint-runtime playbook sequence and the Kubernetes node-ready runtime
check. It does not retain a gateway-specific OpenFaaS readiness snapshot.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-10-style node counts on a single host when
   cloud VM cores are capped to fit the runner.
2. Kubernetes installs and reaches Ready on the three-cloud-node topology.
3. The OpenFaaS software playbook completes on the Kubernetes topology.
4. The endpoint runtime software phase completes on the four endpoint VMs.
5. The runner observes the standard release artifacts: experiment lock, state
   file, `phase_completed = software`, and matching resume contract.

## Limitations

This evidence does not certify:

1. the exact legacy P-QEMU-10 resource shape with 3 cloud VMs at 6 cores each,
2. multi-host QEMU scheduling for the exact 26-core legacy shape,
3. the full OpenFaaS image-classification application benchmark,
4. image-classification metric artifacts on OpenFaaS,
5. local-registry cache behavior for OpenFaaS application images,
6. cloud-provider OpenFaaS behavior,
7. gateway-specific OpenFaaS readiness beyond software-phase completion.

This software-only evidence does not certify parent row `P-QEMU-10`.

The full `qemu_openfaas_image_parity` suite is ported but not certified. It now
uses cache-backed image preflight, and the local registry cache has been primed
on the certification host. The latest exact parent-row attempt selected legacy
external host `matthijs@node1` on 2026-07-07 and failed before provisioning
because the dedicated `continuum-smoke` runner could not authenticate to that
host. Exact parent-row evidence still requires authenticated external QEMU
capacity or a larger local runner before parent row `P-QEMU-10` can be claimed.
