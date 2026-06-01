# QEMU KubeEdge Software Evidence - 2026-05-31

## Scope

This evidence certifies the software-only subset row `P-QEMU-06-SW` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-06-style local
QEMU topology and complete the KubeEdge software phase with endpoint runtime
present for endpoint resources. It does not certify the full
image-classification application benchmark from `configuration/tests/qemu/06_kubeedge-img.cfg`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-06-SW` |
| Git commit | `9b380abed1909aa0afad8ef32bc71a1d203941ea` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-05-31 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Config | `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml` |
| Suite | `qemu_kubeedge_software_parity` |
| Software profile | `configs/profiles/software/kubeedge-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, and SSH access for KubeEdge software execution; no cloud credentials. |
| Runtime targets | `infrastructure`, `software` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, KubeEdge software-phase evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kubeedge_software_parity/.continuum/test_results/test_results_2026-05-31_19-38-15.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kubeedge_software_parity/.continuum/` |

## Result

The final synced-tree run passed after the host-wrapper and KubeEdge role
fixes:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml` | PASS | 1899.9s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched |

The same row also passed earlier in 729.3s, 299.4s, and 282.4s while the
certification harness was being tightened. The committed evidence should use the
final 1899.9s run above because it followed all final KubeEdge role and
host-wrapper edits.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-06-style topology of one cloud controller, two
   edge nodes, and two endpoint nodes.
2. The KubeEdge software phase completes on that topology.
3. The endpoint runtime module is present for endpoint resources in the same
   software phase.
4. The runner observes the standard release artifacts: SSH hints, experiment
   lock, state file, `phase_completed = software`, and matching resume contract.

## Limitations

This evidence does not certify:

1. the full KubeEdge image-classification application benchmark,
2. image-classification metric artifacts on KubeEdge,
3. teardown behavior, because the legacy row and rework config retain VMs,
4. cloud-provider KubeEdge behavior,
5. broad KubeEdge version compatibility beyond the configured profile,
6. edge-node readiness beyond successful software-phase completion.

This software-only evidence does not certify parent row `P-QEMU-06`.

The full `qemu_kubeedge_image_parity` suite is ported but not certified. At the
time this software-only evidence was captured, local-registry application image
staging still needed Docker daemon access for the `continuum-smoke` user. The
suite now gates on a host-primed local registry cache instead. A later full
application attempt reached the application phase, then failed under host disk
pressure while the endpoint publisher image was being pulled and while the test
runner was saving its JSON summary. Keep full `P-QEMU-06` unclaimed until
the relocated `/mnt/sdc/continuum_smoke` runner records a full VM-backed
application run that passes. `P-QEMU-05` remains Docker-gated because it models
a forced-prefetch row.
