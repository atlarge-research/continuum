# QEMU Kube Kata Empty Evidence - 2026-07-09

## Scope

This evidence certifies research case-study row
`M2-QEMU-KUBE-KATA-EMPTY` in `docs/release_certification_matrix.md`.

It proves that the rework stack can run the minimal legacy Kata startup
benchmark shape on local QEMU with `kube_kata`, `empty_kata`, `kata-qemu`, and
`overlayfs`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `M2-QEMU-KUBE-KATA-EMPTY` |
| Git commit | `2f78df31af51b8fff67356c0888a865505dddf2b` |
| Tree state | Clean committed source tree matching the `kube_kata`/`empty_kata` implementation synced to the dedicated runner. |
| Date | 2026-07-09 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kube_kata_empty_startup_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `continuum-hostctl verify`, local registry cache priming, and suite prerequisite checks. |
| Config | `configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml` |
| Suite | `qemu_kube_kata_empty_startup_parity` |
| Software profile | `configs/profiles/software/kube-kata.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host, `/dev/kvm` access, nested virtualization, SSH access, local registry cache primed with Kubernetes control-plane images, `ansk/empty:empty`, and `jaegertracing/all-in-one:1.47`, a current root-owned `continuum-hostctl` helper, and enough CPU/RAM/disk under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, software phase evidence including Kubernetes readiness, RuntimeClass installation, guest Kata runtime setup, and Jaeger query readiness, application phase evidence, teardown, and benchmark metrics manifest with `CLOUD OUTPUT` and `KATA OUTPUT`. |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/test_results/test_results_2026-07-09_21-25-22.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/` |
| Benchmark metric manifest | `/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/logs/benchmark/2026-07-09_20_51_51_empty-kata-pod_metrics_manifest.json` |

## Result

The retained VM-backed run passed:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml` | PASS | 2013.6s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, teardown verified, benchmark evidence found, benchmark metric tables found, benchmark metric artifacts found |

The wrapper reported:

```text
benchmark_metric_artifacts=/mnt/sdc/continuum_smoke/qemu_kube_kata_empty_startup_parity/.continuum/logs/benchmark/2026-07-09_20_51_51_empty-kata-pod_metrics_manifest.json
```

The suite evidence contract requires the retained benchmark metric manifest to
contain both:

1. `CLOUD OUTPUT` with at least 100 rows,
2. `KATA OUTPUT` with at least 100 rows and the Kata phase columns
   `kata_create_runtime (s)`, `kata_create_vm (s)`,
   `kata_connect_to_vm (s)`, and
   `kata_create_container_and_launch (s)`.

The run reached the Jaeger trace contract before writing artifacts:

```text
Collected 100 complete Kata timestamp row(s), expected 100
```

## What This Claims

This row may be described as:

1. Continuum can run the minimal local-QEMU Kata startup benchmark using
   `kube_kata`, `empty_kata`, `kata-qemu`, and `overlayfs`.
2. The run reaches `phase_completed = application` and writes the standard
   lock, state, resume-contract, stdout, metadata, and benchmark evidence
   artifacts.
3. The software phase installs RuntimeClass objects for `kata-qemu`, `kata-fc`,
   and `runc`, verifies the guest Kata runtime, and exposes the legacy Jaeger
   query endpoint on the worker.
4. The application phase produces retained benchmark metric artifacts for both
   cloud-level startup timing and Jaeger-derived Kata timing.

## Limitations

This evidence does not certify:

1. `kata-fc`, `devmapper`, or runtime/filesystem combinations beyond
   `kata-qemu` plus `overlayfs`,
2. GCP, AWS, bare-metal, multi-host, edge, or endpoint Kata topologies,
3. every legacy Kata startup parameter sweep,
4. resource-usage, stress, memory-usage, or non-`empty_kata` applications,
5. every figure or claim from legacy Kata experiments.
