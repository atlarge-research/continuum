# Normal-User QEMU Smoke Host Workflow

The separate `continuum-smoke` execution account, installed wrappers and dedicated repository copy are retired as the active workflow by the approved 2026-10-27 migration. This is a high-trust physical-host workflow, not a sandbox. Current policy is `docs/rework_milestone_release_plan.md`; factual claims and historical runs are in `docs/release_certification_matrix.md`.

## Setup and verification

Run repository scripts as your normal Unix user, never through sudo. Host package installation and group membership are operator prerequisites: libvirt/KVM access, read/write `/dev/kvm`, `virsh`, QEMU/cloud-image tools, ACL tools, networking tools, SSH and the Python/Ansible dependencies in `requirements.txt`. Docker access is needed only for cache priming and is itself high trust. Do not add blanket sudo or run repository code as root.

The generic defaults are `$HOME/continuum_smoke` and `$HOME/venvs/continuum/bin/python3`. HOME and runtime roots must be canonical absolute paths; root execution and missing/noncanonical HOME are rejected.

```bash
sh scripts/test/setup_agent_host.sh show-config
sh scripts/test/setup_agent_host.sh create-venv
$HOME/venvs/continuum/bin/python3 -m pip install -r requirements.txt
sh scripts/test/setup_agent_host.sh verify
```

`create-venv` uses the host `/usr/bin/python3`, refuses existing destinations and does not install packages. A historical-run migration should instead install the reviewed matching freeze to preserve attribution, not silently upgrade dependencies. `verify` checks the venv, KVM/libvirt and smoke/benchmark prerequisites; it does not start VMs. It may create prerequisite artifact dirs.

For the approved node4 migration, run from `/home/matthijs/continuum` with:

```bash
export CONTINUUM_SMOKE_BASE_ROOT=/mnt/sdc/continuum_smoke
export CONTINUUM_SMOKE_PYTHON=/home/matthijs/venvs/continuum/bin/python3
sh scripts/test/setup_agent_host.sh verify
```

Keep these exports for every command in the same operator session. The existing `/home/matthijs/continuum_smoke` directory is not replaced by a symlink. On node3, use canonical `/mnt/sdb/continuum_smoke` when referring to its retained root; `/mnt/sdc` there is a symlink. Physical external execution is `matthijs@node3`, configured in `scripts/test/test_config.json`, not special framework code. The controller runs from the live reviewed checkout; no installed wrapper or dedicated-repo sync/install step remains.

## Scenarios and retained results

```bash
sh scripts/test/run_smoke_host.sh list-suites
sh scripts/test/run_smoke_host.sh check-prereqs --suite smoke
sh scripts/test/run_smoke_host.sh check-prereqs --suite benchmark_smoke
sh scripts/test/run_smoke_host.sh operational_regression
sh scripts/test/run_smoke_host.sh storage-report
sh scripts/test/run_smoke_host.sh latest-result-summary benchmark_k8s_resume
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume stdout
```

Artifact inspection accepts exactly this order:

```text
latest-result-tail <scenario> [stdout|stderr|metadata] [result-index] [--full]
```

Defaults are stdout, one-based result index 1, and the final 120 lines. `--full` prints the complete selected artifact without decoding or truncation; it must be last. Kind and index may be omitted. For example, inspect every entry in a three-phase benchmark result with indexes 1, 2 and 3:

```bash
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume stdout 2 --full
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume stderr 2 --full
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume metadata 2 --full
```

Only the selected entry of the latest summary JSON supplies the artifact path. The inspector rejects invalid indexes/order, arbitrary path arguments, parent traversal, symlink escapes and missing/unreadable/nonregular artifacts. Canonical artifact paths must stay inside that child's canonical test-results directory.

The script retains the existing named suite/scenario mapping, including local and multi-host OpenFaaS, Columbo trace and Kata startup paths. `list-suites` describes configured suites; availability is not runtime certification. `operational_regression` chains the three smoke children and `benchmark_k8s_resume`. It has no retained root of its own. Inspect `infra_one_vm`, `software_k8s_two_vm`, `network_netperf_two_vm` and `benchmark_k8s_resume` beneath the selected root. Benchmark phase aliases map to that same benchmark child directory.

Registry priming runs as the normal user with existing Docker access:

```bash
sh scripts/test/run_smoke_host.sh prime-registry-cache --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh prime-registry-cache --check-only --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh check-prereqs --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh qemu_openfaas_image_parity
```

The available foundation scenarios include `qemu_infra_parity`, `network_validation`, `qemu_k8s_image_parity`, `qemu_endpoint_image_parity` and `qemu_k8s_nobench_parity` scenarios alongside `operational_regression`. Select release runs from the [agreed case manifest](reproduction_inventory.md#br23-projects-and-case-manifest). Image scenarios require their checked local registry images; tc/netperf and the guest package/image repositories must be available where configured. The no-benchmark scenario installs Kubernetes, endpoint runtime and observability; it supplies no image-classification application evidence. Most profiles retain guests; endpoint image, all-tier infrastructure parity and the final benchmark resume phase request teardown. Scenario directories preserve files. Fresh infrastructure startup stops verified old transient Continuum guests of the Unix account on the controller and scheduled workers, including guests from earlier base paths. A protected name collision or protected guest disk in the new run's image directory stops startup. Preserve earlier workspace files and use resume to continue an existing deployment. The composite phase smoke matrix requests and verifies teardown for each of its three children. Standalone child commands still retain guests by default.

When observability is enabled, its software role waits up to 20 minutes each for Grafana deployment availability and both replicas of `Prometheus/k8s` in `monitoring`. It checks Grafana `/api/health` (HTTP 200 and database `ok`) and Prometheus `/-/ready` (HTTP 200) through their guest-local port-forwards on every distinct advertised controller address. Each HTTP check uses a five-second socket timeout and at most thirteen attempts with five-second retry delays. Response reads and overhead mean this is not a total HTTP elapsed-time deadline; the existing runner timeout and owned-process cleanup bound the workflow. Success records the health responses and verifies the selected forwarding PID's UID and exact command. This proves readiness at that point, not continued availability, complete scrape coverage or accurate cross-guest timing.

Forwarding runs inside the cloudcontroller guest under the playbook's become identity. The role reuses one exact same-UID process or starts a missing forward; duplicates, identity changes and failed health checks fail without killing or restarting other processes. Guest logs append to `/var/log/continuum-observability/grafana-port-forward.log` and `/var/log/continuum-observability/prometheus-port-forward.log` with mode 0600 inside a 0700 directory. Failure output preserves the original error and bounded resource/pod/PID diagnostics plus the final 80 log lines. Inspect and preserve those logs before diagnosing a retry; an older reused forward may have no earlier log because the previous role discarded its output. Record the actual installed kube-prometheus checkout and Kubernetes versions; historical evidence and the configured release branch do not establish their exact installed revisions.

Inspect complete result JSONs, stdout/stderr/metadata and raw Ansible recaps; verify final state/lock source and resume bindings. For application cases, count actual per-publisher outcomes (or processing and latency records for combined endpoint containers) and inspect current CSVs/manifests. For enabled network checks, inspect timestamped NDJSON and the existing verifier result; for observability, retain point-in-time HTTP health and exact forwarding identity evidence. Whole suites overwrite intermediate state/lock bytes, so inspect final files together with each entry's detectors and full logs. Current development results, sources, receipts and guest-retention transitions are in `docs/rework_release_handoff.md`.

Record observed versions: configured Kubernetes versions are not an exact patch pin, guest Docker versions can differ and Netperf version output does not pin its build commit. The network verifier's expected-rate rule above 100 Mbps requires finite positive throughput, so a pass alone does not prove configured 1000-Mbps fidelity. The foundation pinned-edge live XML query missed its window and no generated XML survives; there is no direct vcpupin/hardware-isolation proof. Compact evidence excludes disks, private keys, Ansible temporary trees and full journals. Backing existence/current sizes do not establish live-byte invariance. Functional counts and finite metrics do not certify sustained frequency or synchronized cross-guest timing.

Use the active packet's scenario and resource boundaries. For the group's MCS cluster, a user-authorized task time budget activates the [standing physical validation approval](../AGENTS.md#mcs-physical-validation). Before host execution, record clean HEAD/status and verify prerequisites, workspace ownership, address availability and existing guest inventory. Run only one active Continuum invocation per Unix account on each physical host, even across base paths. Concurrent runs must use distinct base paths. A cache belongs to one stable runner identity.

For raw Ansible task and recap evidence, optionally export the standard `ANSIBLE_LOG_PATH` to an absolute path outside the checkout before a suite or single-config run. Use a private pre-existing `0700` evidence directory and a precreated `0600` log file. The runner forwards only a nonempty value through its otherwise unchanged cleared environment; unset/empty values are omitted. Ansible logs can contain secrets: never commit them. Verify the log is nonempty and contains the expected play recaps before recording its hash as evidence; an empty file proves no host outcome. Default logging behavior is unchanged.

QEMU validates each owning host/profile slot and decides reuse or rebuilding. The runner does not delete guessed base images: `--rebuild-base-images`, `--use-cache`, and the root/suite test-config keys `base_image_rebuild_frequency`, `rebuild_base_images`, `use_cache` are retired and rejected. The retained result field `base_images_rebuilt: []` makes no claim about QEMU's runtime decisions. Invalid-cache cleanup removes only its ready sidecar, QCOW2 and derived cloud-init disk, not the current run's user-data YAML. Inspection/access failures abort with path, numeric ownership/mode and ACL context; no permission repair is automatic. Existing peer disks skipped by creation keep their mode and ACLs unchanged.

Keep failed state until diagnosis. Before pruning, preserve compact evidence outside the child root, identify excluded disks and show the exact target. Deletion requires the explicit confirmation flag:

```bash
sh scripts/test/run_smoke_host.sh prune-scenario benchmark_k8s_resume --yes-delete-retained-state
```

This removes that child's retained state, including disks, not an aggregate suite. Evidence excluded from a snapshot cannot be claimed as preserved.

## Artifact retention review

Review retention when a checkpoint closes, a workflow or relevant implementation is superseded, or storage pressure requires a cleanup. Use relevance and dependencies rather than age alone. A different commit does not make every historical result useless, but a run whose relevant code or configuration has been replaced and which has no remaining research, diagnostic or provenance value need not be kept indefinitely. Keeping historical evidence never makes it validation of a newer revision.

| Disposition | Guideline |
| --- | --- |
| Keep | The minimum complete evidence supporting current claims; active or hash-bound inputs; useful unresolved failures; and unique historical material required by a paper, reproduction scope, audit or still-open human decision. Preserve the source, configuration, environment and limitations needed to interpret it. |
| Archive | Useful superseded milestones and unique historical failures that are no longer daily working material. Use the existing durable evidence location or reachable Git history for tracked text, and keep one canonical copy rather than repeated working copies. |
| Eligible for removal | Unused temporary checkouts, duplicate exports and staging, intermediate helper revisions, and obsolete run data with no retained claim, scope obligation or unique diagnostic value. Confirm their consumers are finished and required canonical copies are complete before selecting them for removal. |

Before removal, identify the exact paths and owner, check that no active workflow or retained evidence depends on them, and preserve the required reference closure or explicitly record retirement of the dependent claim. Do not leave kept receipts pointing to files silently deleted by cleanup. Record the batch decision and reason in the existing handoff or evidence index, not a new Markdown file for every artifact.

Temporary development files belong in the existing ignored execution workspace or appropriate outside-repository artifact storage, not the tracked source tree. Use the [navigation page's storage map](rework_kickoff.md#local-artifacts-outside-the-tracked-documentation) to distinguish source documentation, scratch, durable evidence, VM disks and Codex-wide application data. Do not create another storage hierarchy merely to organize old copies.

This guideline introduces no automatic age-based purge, cleanup script or permission to delete current artifacts. Keep failed state until diagnosis, preserve unrelated users' files, and use the existing owner-scoped pruning command and required authorization for retained VM state. Review obsolete material at each completed milestone instead of either keeping everything forever or deleting all older commits' results indiscriminately.

## Direct diagnostics and completed retirement

The temporary framework-owned diagnostic replay command and its dedicated playbook are removed after the completed QEMU diagnosis and exact multi-host verification. Use the summary/indexed-full tail above, retained logs/state/lock, and ordinary SSH/operator tools against the exact affected host. See `docs/vm_debugging_runbook.md`; no replacement command runner is provided.

Historical evidence documents retain their original account and commands. Their runs are not renewed by this migration. Both old accounts/private groups and installed helpers are retired after verified normal-user local/external validation, private snapshots and exact UID/GID/ACL auditing. Old data/helpers remain recoverable in root-private /var/lib/continuum-retired-20261027-node4 and the node3 counterpart; normal identities and preexisting grants are unchanged. See `docs/rework_release_handoff.md` for the evidence checkpoint. Never use runtime recursive chown, broad permission repair or an automatic fallback to sudo.
