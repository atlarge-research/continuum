# QEMU Endpoint Image Evidence - 2026-07-06

## Scope

This evidence certifies old-main parity row `P-QEMU-08` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-08-style local
QEMU endpoint-only topology, complete the endpoint-runtime software phase, run
the image-classification application benchmark, verify teardown, and emit
benchmark metric artifacts.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-08` |
| Git commit | `c6a7bd8db167833593d110cbd45b89d7a2afd86c` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-06 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_image_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`; suite uses cache-backed local registry preflight rather than Docker daemon access for `continuum-smoke` |
| Config | `configs/experiments/parity/qemu_endpoint_image/08_endpoint_image_classification.yaml` |
| Suite | `qemu_endpoint_image_parity` |
| Software profile | `configs/profiles/software/endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, `tc` support, local registry cache primed for the suite, and enough disk space under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application`, cleanup |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, endpoint-runtime software phase evidence, application phase evidence, benchmark metrics manifest, and teardown evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_endpoint_image_parity/.continuum/test_results/test_results_2026-07-06_17-36-16.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_endpoint_image_parity/.continuum/` |

## Result

The clean-source run passed after cache-backed image parity preflights were
added and the already-certified VM evidence set was refreshed on the same
release-evidence source line:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_endpoint_image/08_endpoint_image_classification.yaml` | PASS | 1393.5s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, teardown verified, benchmark evidence found, benchmark metric tables found |

Benchmark metric artifact:

```text
/mnt/sdc/continuum_smoke/qemu_endpoint_image_parity/.continuum/logs/benchmark/2026-07-06_17_28_10_classify-images_metrics_manifest.json
```

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-08-style endpoint-only topology of two endpoint
   VMs with 4g network emulation enabled.
2. The endpoint runtime software phase completes on that topology.
3. The image-classification application runs on the endpoint-only topology and
   emits benchmark metric artifacts.
4. The runner observes the standard release artifacts: SSH output, experiment
   lock, state file, `phase_completed = application`, matching resume contract,
   teardown verification, and benchmark metrics manifest.

## Limitations

This evidence does not certify:

1. GCP, AWS, or bare-metal endpoint runtime behavior,
2. broad endpoint-runtime version compatibility beyond the configured profile,
3. forced image-prefetch as a public runner requirement for `continuum-smoke`,
4. Kubernetes, KubeEdge, Mist, or OpenFaaS application rows,
5. broader image-classification parameter sweeps beyond the configured
   frequency, duration, and resource values.
