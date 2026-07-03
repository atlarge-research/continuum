# QEMU KubeEdge Image Evidence - 2026-07-02

## Scope

This evidence certifies old-main parity row `P-QEMU-06` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy P-QEMU-06-style local
QEMU topology, complete the KubeEdge software phase with endpoint runtime
present for endpoint resources, and run the image-classification application
benchmark to metric-artifact completion.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-06` |
| Git commit | `01c18b5dd26b561b5b81b2d83cdf28649267b1c2` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-02 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo` and local registry cache priming; refreshed after later Mist runtime-helper changes made the earlier P-QEMU-06 evidence stale for pre-tag purposes |
| Config | `configs/experiments/parity/qemu_kubeedge_image/06_kubeedge_image_classification.yaml` |
| Suite | `qemu_kubeedge_image_parity` |
| Software profile | `configs/profiles/software/kubeedge-endpoint-runtime.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, local registry cache primed for the suite, and enough disk space under `/mnt/sdc/continuum_smoke`; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, KubeEdge software-phase evidence, application phase evidence, benchmark metrics manifest |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_kubeedge_image_parity/.continuum/test_results/test_results_2026-07-02_15-52-17.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_kubeedge_image_parity/.continuum/` |

## Result

The final synced-tree refresh run passed on the current runtime source after
the KubeEdge runtime-prerequisite fixes and later Mist runtime-helper fixes:

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_kubeedge_image/06_kubeedge_image_classification.yaml` | PASS | 2679.0s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, benchmark evidence found, benchmark metric tables found |

Benchmark metric artifact:

```text
/mnt/sdc/continuum_smoke/qemu_kubeedge_image_parity/.continuum/logs/benchmark/2026-07-02_15_02_44_classify-images_metrics_manifest.json
```

The passing run followed an earlier failed 2026-06-01 attempt that exposed two
runtime issues:

1. the KubeEdge base-image prerequisites did not explicitly load and persist the
   `vxlan` kernel module required by flannel on the edge nodes,
2. the edge-node host `mosquitto` service conflicted with the KubeEdge broker
   pod on port 1883.

Commit `c4f034715459d5a7199bac1789b5115699848afb` fixed those issues before the
first passing evidence run. This document now references the later
`65d3e193ca29249c1ca33b5aa364367c16911006` refresh run so P-QEMU-06 evidence
includes the current Mist runtime-helper source.

## What This Claims

This row may be described as:

1. QEMU can provision the P-QEMU-06-style topology of one cloud controller, two
   edge nodes, and two endpoint nodes.
2. The KubeEdge software phase completes on that topology.
3. The endpoint runtime module is present for endpoint resources in the same
   software phase.
4. The image-classification application runs on the KubeEdge edge topology and
   emits benchmark metric artifacts.
5. The runner observes the standard release artifacts: SSH output, experiment
   lock, state file, `phase_completed = application`, matching resume contract,
   and benchmark metrics manifest.

## Limitations

This evidence does not certify:

1. GCP, AWS, or bare-metal KubeEdge behavior,
2. broad KubeEdge version compatibility beyond the configured profile,
3. full OpenFaaS application parity, which still needs root-helper cache
   priming, exact-resource capacity resolution, and retained application
   evidence,
4. teardown behavior, because the legacy row and rework config retain VMs,
5. broader KubeEdge applications beyond the image-classification path.
