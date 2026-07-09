# QEMU OpenFaaS Image Evidence - 2026-07-08

## Scope

This evidence certifies exact old-main parity row `P-QEMU-10` in
`docs/release_certification_matrix.md`.

It proves that the rework stack can provision the legacy QEMU OpenFaaS
image-classification topology on local plus external QEMU capacity, complete
the Kubernetes, OpenFaaS, endpoint-runtime, and image-classification
application phases, and emit benchmark metric artifacts.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-10` |
| Git commit | `f9ab4217c40604dc145692664667a13e8cc2a994` |
| Tree state | Clean source tree synced to the dedicated runner |
| Date | 2026-07-08 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo`, `continuum-hostctl verify`, and cache preflight; retained state root `/mnt/sdc/continuum_smoke`; external QEMU host `continuum-smoke@node3`. |
| Config | `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml` |
| Suite | `qemu_openfaas_image_parity` |
| Software profile | `configs/profiles/software/k8s-openfaas.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Provider / host prerequisites | Local and external QEMU/libvirt/KVM hosts with libvirt access, `/dev/kvm` access, SSH access as `continuum-smoke`, enough combined CPU capacity for the exact 26 requested vCPU legacy shape, a primed local registry cache for OpenFaaS application images, and no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, software phase evidence, Kubernetes readiness, OpenFaaS function deployment, endpoint publisher output, application phase evidence, benchmark metric artifacts, and benchmark metrics manifest. |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/test_results/test_results_2026-07-08_16-34-03.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/` |
| Benchmark metric manifest | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/logs/benchmark/2026-07-08_16_13_25_classify-images_metrics_manifest.json` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml` | PASS | 1238.5s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, benchmark evidence found, benchmark metric tables found |

The retained runner summary records:

1. `exit_code=0`,
2. `ssh_output_found`,
3. `experiment_lock_written`,
4. `state_file_written`,
5. `state_phase=application`,
6. `resume_contract_match`,
7. `benchmark_evidence_found`,
8. `benchmark_metric_tables_found`,
9. benchmark metric artifact manifest written at the path above.

## What This Claims

This row may be described as:

1. QEMU can provision the exact P-QEMU-10 legacy resource shape using local plus
   external QEMU capacity.
2. Kubernetes installs and reaches Ready on the three-cloud-node topology.
3. OpenFaaS installs, deploys the image-classification function, and exposes it
   through the gateway path used by endpoint publishers.
4. Endpoint publishers complete the image-classification application phase.
5. The runner observes standard release artifacts and structured benchmark
   metric artifacts through the application phase.

## Limitations

This evidence does not certify:

1. cloud-provider OpenFaaS behavior,
2. OpenFaaS behavior without the primed local registry cache,
3. every Columbo paper figure, parameter sweep, cloud provider, non-QEMU
   topology, `kube_kata`, or broader `kubecontrol` behavior,
4. behavior outside the exact YAML config and profile set listed above.
