# QEMU OpenFaaS Local Application Evidence - 2026-06-02

## Scope

This evidence certifies the local application subset row
`P-QEMU-10-APP-LOCAL` in `docs/release_certification_matrix.md`.

It proves that the rework stack can provision a single-host QEMU variant of the
legacy P-QEMU-10 node counts and complete the Kubernetes, OpenFaaS,
endpoint-runtime, and image-classification application phases. The variant
keeps three cloud VMs and four endpoint VMs, but lowers cloud VM cores from the
legacy value of 6 to 4 so the suite fits the dedicated runner's 20-core
single-host limit.

It does not certify the exact legacy CPU shape or parent row `P-QEMU-10` from
`configuration/tests/qemu/10_kubernetes-openfaas.cfg`.

## Source And Command

| Field | Value |
| --- | --- |
| Matrix row ID | `P-QEMU-10-APP-LOCAL` |
| Git commit | `1fa9e893e4a977d172680b550f2a0b31278b53a6` |
| Tree state | Dirty source tree synced to the dedicated runner; includes the local OpenFaaS application subset, OpenFaaS role-resolution hardening, gateway accessibility, endpoint Docker argv, and cached publisher compatibility fixes. |
| Date | 2026-06-02 |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_local_parity` |
| Runner context | Dedicated `continuum-smoke` wrapper after `continuum-hostctl sync-repo` and `verify`; retained state root `/mnt/sdc/continuum_smoke`. |
| Config | `configs/experiments/parity/qemu_openfaas_image_local/10_openfaas_image_classification_local.yaml` |
| Suite | `qemu_openfaas_image_local_parity` |
| Software profile | `configs/profiles/software/k8s-openfaas.yaml` |
| Provider profile | `configs/profiles/environment/local-qemu-cpupin.yaml` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, enough local CPU capacity for the capped single-host OpenFaaS shape, a primed local registry cache for OpenFaaS application images, and no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application` |
| Required artifacts checked | Test-results summary, experiment lock, state file, stdout/stderr/metadata artifacts, infrastructure phase evidence, software phase evidence, Kubernetes readiness, OpenFaaS function deployment, endpoint publisher output, benchmark metric artifacts, and benchmark metrics manifest. |
| Result summary path | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_local_parity/.continuum/test_results/test_results_2026-06-02_11-56-12.json` |
| Artifact root | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_local_parity/.continuum/` |
| Benchmark metric manifest | `/mnt/sdc/continuum_smoke/qemu_openfaas_image_local_parity/.continuum/logs/benchmark/2026-06-02_11_28_05_classify-images_metrics_manifest.json` |

## Result

| Config | Result | Duration | Success Reason |
| --- | --- | --- | --- |
| `configs/experiments/parity/qemu_openfaas_image_local/10_openfaas_image_classification_local.yaml` | PASS | 1688.2s | `exit_code=0`, SSH output found, experiment lock written, state file written, state phase `application`, resume contract matched, benchmark evidence found, benchmark metric tables found |

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

1. QEMU can provision the P-QEMU-10-style node counts on a single host when
   cloud VM cores are capped to fit the runner.
2. Kubernetes installs and reaches Ready on the three-cloud-node topology.
3. OpenFaaS installs, deploys the image-classification function, and exposes it
   through the gateway path used by endpoint publishers.
4. Endpoint publishers complete the image-classification application phase.
5. The runner observes standard release artifacts and structured benchmark
   metric artifacts through the application phase.

## Limitations

This evidence does not certify:

1. the exact legacy P-QEMU-10 resource shape with three cloud VMs at 6 cores
   each,
2. multi-host QEMU scheduling for the exact 26-core legacy shape,
3. parent row `P-QEMU-10`,
4. cloud-provider OpenFaaS behavior,
5. OpenFaaS behavior without the primed local registry cache.

The exact legacy application shape selected external host `matthijs@node3` on
2026-06-02 and failed before provisioning because SSH returned `No route to
host`. Keep parent row `P-QEMU-10` unclaimed until reachable external QEMU
capacity or a larger local runner can produce retained VM/application evidence
for the exact shape.
