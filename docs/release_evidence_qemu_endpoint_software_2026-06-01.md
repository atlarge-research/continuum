# QEMU Endpoint Runtime Evidence - 2026-06-01

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
| Git commit | `4d1a72f7bf3d3f4a806faef22b5640b932ce2d69` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-06-01 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Config | `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml` |
| Suite | `qemu_endpoint_software_parity` |
| Software profile | `configs/profiles/software/endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, and tc support for endpoint network emulation and teardown; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, teardown |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, endpoint-runtime software-phase evidence, teardown evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_endpoint_software_parity/.continuum/test_results/test_results_2026-06-01_15-01-40.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_endpoint_software_parity/.continuum/` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml` | PASS | 153.3s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched, teardown verified |

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

This software-only evidence does not certify parent row `P-QEMU-08`.

The full `qemu_endpoint_image_parity` suite is ported but not certified. Its
preflight currently fails for the `continuum-smoke` user because the legacy
`docker_pull = True` behavior maps to forced local-registry image prefetch:
`Docker socket access: exit code 1; Docker daemon access: permission denied`.
