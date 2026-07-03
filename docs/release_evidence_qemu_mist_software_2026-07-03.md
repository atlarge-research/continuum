# QEMU Mist Software Evidence - 2026-07-03

## Scope

This evidence certifies the software-only subset row `P-QEMU-07-SW` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-07-style local
QEMU topology and complete the Mist software phase with endpoint runtime present
for endpoint resources. It does not certify the full image-classification
application benchmark from `configuration/tests/qemu/07_mist-img.cfg`; that
parent row is tracked in `docs/release_evidence_qemu_mist_image_2026-07-03.md`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-07-SW` |
| Git commit | `01c18b5dd26b561b5b81b2d83cdf28649267b1c2` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-03 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, Mosquitto apt-lock retry hardening, and corrected Ansible retry-noise success detection |
| Config | `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml` |
| Suite | `qemu_mist_software_parity` |
| Software profile | `configs/profiles/software/mist-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, and SSH access for Mist software execution and teardown; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, teardown |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Mist software-phase evidence, teardown evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_mist_software_parity/.continuum/test_results/test_results_2026-07-03_09-58-06.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_mist_software_parity/.continuum/` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml` | PASS | 1310.2s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched, teardown verified |

The run exercised two edge VMs and four endpoint VMs with CPU pinning enabled,
matching the legacy Mist topology shape from
`configuration/tests/qemu/07_mist-img.cfg`. The log also records that no local
Docker registry was started because the software-only run has no image
requirements.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-07-style topology of two edge nodes and four
   endpoint nodes.
2. The Mist software phase completes on that topology.
3. The endpoint runtime module is present for endpoint resources in the same
   software phase.
4. The runner observes the standard release artifacts: experiment lock, state
   file, `phase_completed = software`, matching resume contract, and teardown.

## Limitations

This evidence does not certify:

1. the full Mist image-classification application benchmark,
2. image-classification metric artifacts on Mist,
3. cloud-provider Mist behavior,
4. a lean Mist-specific base-install path, because Mist currently reuses the
   KubeEdge base prerequisite playbook.

This software-only evidence does not certify parent row `P-QEMU-07`.
