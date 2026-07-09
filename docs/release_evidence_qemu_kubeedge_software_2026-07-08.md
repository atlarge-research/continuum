# QEMU KubeEdge Software Evidence - 2026-07-08

## Scope

This evidence certifies the software-only subset row `P-QEMU-06-SW` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-06-style local
QEMU topology and complete the KubeEdge software phase with endpoint runtime
present for endpoint resources. It does not certify the full
image-classification application benchmark from `configuration/tests/qemu/06_kubeedge-img.cfg`;
that parent row is certified separately by
`docs/release_evidence_qemu_kubeedge_image_2026-07-08.md`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-06-SW` |
| Git commit | `f9ab4217c40604dc145692664667a13e8cc2a994` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-08 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `install-wrapper dedicated`, and `verify` |
| Config | `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml` |
| Suite | `qemu_kubeedge_software_parity` |
| Software profile | `configs/profiles/software/kubeedge-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, and SSH access for KubeEdge software execution; no cloud credentials. |
| Runtime targets | `infrastructure`, `software` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, KubeEdge software-phase evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kubeedge_software_parity/.continuum/test_results/test_results_2026-07-08_18-41-03.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kubeedge_software_parity/.continuum/` |

## Result

The final synced-tree run passed after the host-wrapper and KubeEdge role
hardening:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml` | PASS | 1720.2s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `software`, resume contract matched |

Earlier 2026-05-31 runs passed while the certification harness was still being
tightened. This evidence supersedes the older software-only evidence for release
claim purposes because it was captured on the current synced runtime source used
by the refreshed full KubeEdge image-classification evidence.

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

1. the full KubeEdge image-classification application benchmark, which is
   certified separately by the full `P-QEMU-06` evidence,
2. image-classification metric artifacts on KubeEdge,
3. teardown behavior, because the legacy row and rework config retain VMs,
4. cloud-provider KubeEdge behavior,
5. broad KubeEdge version compatibility beyond the configured profile,
6. edge-node readiness beyond successful software-phase completion.

This software-only evidence does not certify parent row `P-QEMU-06`.
