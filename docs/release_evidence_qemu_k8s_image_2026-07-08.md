# QEMU Kubernetes Image Evidence - 2026-07-08

## Scope

This evidence certifies old-main parity row `P-QEMU-05` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-05-style local
QEMU cloud/endpoint topology, complete the Kubernetes and endpoint-runtime
software phases, run the image-classification application benchmark with
netperf enabled, and emit both benchmark metric and network-validation
artifacts.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-05` |
| Git commit | `f9ab4217c40604dc145692664667a13e8cc2a994` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-08 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_image_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`; suite uses cache-backed local registry preflight rather than Docker daemon access for `continuum-smoke` |
| Config | `configs/experiments/parity/qemu_k8s_image/05_kubernetes_image_classification.yaml` |
| Suite | `qemu_k8s_image_parity` |
| Software profile | `configs/profiles/software/k8s-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-netperf-ip101.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, `tc`/netperf support, local registry cache primed for the suite, and enough disk space under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Kubernetes software-phase evidence, endpoint-runtime evidence, application phase evidence, benchmark metrics manifest, and network NDJSON artifact |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_k8s_image_parity/.continuum/test_results/test_results_2026-07-08_18-12-15.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_k8s_image_parity/.continuum/` |

## Result

The clean-source run passed after cache-backed image parity preflights were
added and the already-certified VM evidence set was refreshed on the same
release-evidence source line:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_k8s_image/05_kubernetes_image_classification.yaml` | PASS | 1309.3s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, network-validation results found, benchmark evidence found, benchmark metric tables found |

Network-validation artifact:

```text
/mnt/sdc/continuum_smoke/qemu_k8s_image_parity/.continuum/logs/network_validation/netperf_results_2026-07-08_17:50:27.ndjson
```

Benchmark metric artifact:

```text
/mnt/sdc/continuum_smoke/qemu_k8s_image_parity/.continuum/logs/benchmark/2026-07-08_17_50_27_classify-images_metrics_manifest.json
```

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-05-style topology of two cloud VMs and two
   endpoint VMs with 4g network emulation enabled.
2. The Kubernetes software phase completes on the cloud resources.
3. The endpoint runtime module is present for endpoint resources in the same
   software phase.
4. The image-classification application runs on the Kubernetes/endpoint
   topology and emits benchmark metric artifacts.
5. The netperf/network-validation artifact is emitted for the configured
   network-emulated path.
6. The runner observes the standard release artifacts: SSH output, experiment
   lock, state file, `phase_completed = application`, matching resume contract,
   network-validation NDJSON, and benchmark metrics manifest.

## Limitations

This evidence does not certify:

1. GCP, AWS, or bare-metal Kubernetes image-classification behavior,
2. broad Kubernetes version compatibility beyond the configured profile,
3. forced image-prefetch as a public runner requirement for `continuum-smoke`,
4. OpenFaaS image-classification behavior,
5. endpoint-only image/runtime parity row `P-QEMU-08`, which is certified
   separately by `docs/release_evidence_qemu_endpoint_image_2026-06-02.md`,
6. broader image-classification parameter sweeps beyond the configured
   frequency, duration, and resource values.
