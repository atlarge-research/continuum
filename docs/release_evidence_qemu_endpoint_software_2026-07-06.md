# QEMU Endpoint Runtime Evidence - 2026-07-06

## Scope

This evidence certifies the software-only subset row `P-QEMU-08-SW` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-08-style local
QEMU endpoint topology and complete the endpoint runtime software phase. It does
not certify the full endpoint-only image-classification application benchmark
from `configuration/tests/qemu/08_endpoint_img.cfg`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-08-SW` |
| Git commit | `dfa3f6bb5a8faaf0c3955bb48e053fb8a5a1b102` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-07 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo` and corrected Ansible retry-noise success detection |
| Config | `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml` |
| Suite | `qemu_endpoint_software_parity` |
| Software profile | `configs/profiles/software/endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, and tc support for endpoint network emulation and teardown; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, teardown |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, endpoint-runtime software-phase evidence, teardown evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_endpoint_software_parity/.continuum/test_results/test_results_2026-07-07_11-33-02.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_endpoint_software_parity/.continuum/` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml` | PASS | 140.6s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched, teardown verified |

The run exercised two endpoint VMs with network emulation enabled, matching the
legacy endpoint-only topology shape from `configuration/tests/qemu/08_endpoint_img.cfg`.
The log records endpoint base-image preparation, endpoint VM launch, network
emulation setup, endpoint runtime installation, software-phase state
persistence, and teardown.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-08-style topology of two endpoint nodes.
2. Network emulation setup completes for that endpoint-only topology.
3. The endpoint runtime software phase completes on endpoint resources.
4. The runner observes the standard release artifacts: experiment lock, state
   file, `phase_completed = software`, matching resume contract, and teardown.

## Limitations

This evidence does not certify:

1. the full endpoint-only image-classification application benchmark,
2. image-classification metric artifacts on endpoint-only execution,
3. Docker image prefetch or local-registry behavior for endpoint application
   images,
4. cloud-provider endpoint-only behavior.

This software-only evidence does not certify parent row `P-QEMU-08`. The full
endpoint image/runtime parent row is certified separately by
`docs/release_evidence_qemu_endpoint_image_2026-07-06.md`.
