# QEMU Mist Software Evidence - 2026-05-23

## Scope

This evidence certifies the software-only subset row `P-QEMU-07-SW` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-07-style local
QEMU topology and complete the Mist software phase with endpoint runtime present
for endpoint resources. It does not certify the full image-classification
application benchmark from `configuration/tests/qemu/07_mist-img.cfg`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-07-SW` |
| Git commit | `653ae7b3c7481c46cb26ca8676ac8fbfa94f7d22` |
| Tree state | Dirty working tree synced intentionally to the dedicated runner |
| Date | 2026-05-23 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo` and `verify` |
| Config | `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml` |
| Suite | `qemu_mist_software_parity` |
| Software profile | `configs/profiles/software/mist-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, and SSH access for Mist software execution and teardown; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, teardown |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Mist software-phase evidence, teardown evidence |
| Result summary path | `/home/continuum-smoke/continuum_smoke/qemu_mist_software_parity/.continuum/test_results/test_results_2026-05-23_20-51-17.json` |
| Artifact root | `/home/continuum-smoke/continuum_smoke/qemu_mist_software_parity/.continuum/` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml` | PASS | 580.4s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched, teardown verified |

The run exercised two edge VMs and four endpoint VMs with CPU pinning enabled,
matching the legacy Mist topology shape from `configuration/tests/qemu/07_mist-img.cfg`.
The log also records that no local Docker registry was started because the
software-only run has no image requirements.

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

The full `qemu_mist_image_parity` suite is ported but not certified. At the
time this software-only evidence was captured, its preflight failed for the
`continuum-smoke` user because local-registry application image staging
required Docker daemon access:
`Docker socket access: exit code 1; Docker daemon access: permission denied`.
The suite now gates on a primed local registry cache instead; keep full
`P-QEMU-07` unclaimed until that cache is primed and a full VM-backed
application run passes.
