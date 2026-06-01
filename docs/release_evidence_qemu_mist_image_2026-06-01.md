# QEMU Mist Image Evidence - 2026-06-01

## Scope

This evidence certifies old-main parity row `P-QEMU-07` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-07-style local
QEMU edge/endpoint topology, complete the Mist software phase, run the
image-classification application benchmark, verify teardown, and emit benchmark
metric artifacts.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-07` |
| Git commit | `44ed14bcb2cffb224352ba219b9ade5b62b24e6a` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-06-01 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_image_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, local registry cache priming, retained failed-run diagnostics, and Mist Docker startup/runtime-helper fixes |
| Config | `configs/experiments/parity/qemu_mist_image/07_mist_image_classification.yaml` |
| Suite | `qemu_mist_image_parity` |
| Software profile | `configs/profiles/software/mist-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, local registry cache primed for the suite, and enough disk space under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application`, cleanup |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, Mist software-phase evidence, application phase evidence, benchmark metrics manifest, teardown evidence |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_mist_image_parity/.continuum/test_results/test_results_2026-06-01_12-47-57.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_mist_image_parity/.continuum/` |

## Result

The final synced-tree run passed after fixing Mist Docker startup warning
handling and the Mist worker readiness Docker status command:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_mist_image/07_mist_image_classification.yaml` | PASS | 818.9s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, teardown verified, benchmark evidence found, benchmark metric tables found |

Benchmark metric artifact:

```text
/mnt/sdc/continuum_smoke/qemu_mist_image_parity/.continuum/logs/benchmark/2026-06-01_12_34_19_classify-images_metrics_manifest.json
```

The passing run followed two failed 2026-06-01 attempts that exposed Mist
application runtime issues:

1. Mist Docker worker startup treated nonfatal SSH/Docker warning stderr as
   fatal even when Docker returned a container id.
2. Mist worker readiness used over-escaped Docker status formatting, causing
   `docker container ls` to reject the command.

Commits `a5aeaf7` and `44ed14b` fixed those issues before this passing evidence
run.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-07-style topology of two edge nodes and four
   endpoint nodes.
2. The Mist software phase completes on that topology.
3. The endpoint runtime module is present for endpoint resources in the same
   software phase.
4. The image-classification application runs on the Mist edge/endpoint topology
   and emits benchmark metric artifacts.
5. The runner observes the standard release artifacts: SSH output, experiment
   lock, state file, `phase_completed = application`, matching resume contract,
   teardown verification, and benchmark metrics manifest.

## Limitations

This evidence does not certify:

1. GCP, AWS, or bare-metal Mist behavior,
2. broad Mist version compatibility beyond the configured profile,
3. forced image-prefetch rows that still require Docker daemon access,
4. broader Mist applications beyond the image-classification path,
5. the longer-term architecture cleanup needed to split Mist from the shared
   KubeEdge base-install path.
