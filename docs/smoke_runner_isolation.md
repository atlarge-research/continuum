# Normal-User QEMU Smoke Host Workflow

The separate `continuum-smoke` execution account, installed wrappers and
dedicated repository copy are retired as the active workflow by the approved
2026-10-27 migration. This is a high-trust physical-host workflow, not a sandbox.
Current policy is `docs/rework_milestone_release_plan.md`; factual claims and
historical runs are in `docs/release_certification_matrix.md`.

## Setup and verification

Run repository scripts as your normal Unix user, never through sudo. Host
package installation and group membership are operator prerequisites:
libvirt/KVM access, read/write `/dev/kvm`, `virsh`, QEMU/cloud-image tools,
ACL tools, networking tools, SSH and the Python/Ansible dependencies in
`requirements.txt`. Docker access is needed only for cache priming and is
itself high trust. Do not add blanket sudo or run repository code as root.

The generic defaults are `$HOME/continuum_smoke` and
`$HOME/venvs/continuum/bin/python3`. HOME and runtime roots must be canonical
absolute paths; root execution and missing/noncanonical HOME are rejected.

```bash
sh scripts/test/setup_agent_host.sh show-config
sh scripts/test/setup_agent_host.sh create-venv
$HOME/venvs/continuum/bin/python3 -m pip install -r requirements.txt
sh scripts/test/setup_agent_host.sh verify
```

`create-venv` uses the host `/usr/bin/python3`, refuses existing destinations
and does not install packages. A historical-run migration should instead
install the reviewed matching freeze to preserve attribution, not silently
upgrade dependencies. `verify` checks the venv, KVM/libvirt and smoke/benchmark
prerequisites; it does not start VMs. It may create prerequisite artifact dirs.

For the approved node4 migration, run from `/home/matthijs/continuum` with:

```bash
export CONTINUUM_SMOKE_BASE_ROOT=/mnt/sdc/continuum_smoke
export CONTINUUM_SMOKE_PYTHON=/home/matthijs/venvs/continuum/bin/python3
sh scripts/test/setup_agent_host.sh verify
```

Keep these exports for every command in the same operator session. The existing
`/home/matthijs/continuum_smoke` directory is not replaced by a symlink.
On node3, use canonical `/mnt/sdb/continuum_smoke` when referring to its
retained root; `/mnt/sdc` there is a symlink. Physical external execution is
`matthijs@node3`, configured in `scripts/test/test_config.json`, not special
framework code. The controller runs from the live reviewed checkout; no
installed wrapper or dedicated-repo sync/install step remains.

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

Defaults are stdout, one-based result index 1, and the final 120 lines.
`--full` prints the complete selected artifact without decoding or truncation;
it must be last. Kind and index may be omitted. For example, inspect every
entry in a three-phase benchmark result with indexes 1, 2 and 3:

```bash
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume stdout 2 --full
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume stderr 2 --full
sh scripts/test/run_smoke_host.sh latest-result-tail benchmark_k8s_resume metadata 2 --full
```

Only the selected entry of the latest summary JSON supplies the artifact path.
The inspector rejects invalid indexes/order, arbitrary path arguments, parent
traversal, symlink escapes and missing/unreadable/nonregular artifacts. Canonical
artifact paths must stay inside that child's canonical test-results directory.

The script retains the existing named suite/scenario mapping, including local
and multi-host OpenFaaS, Columbo trace and Kata startup paths. `list-suites`
describes configured suites; availability is not runtime certification.
`operational_regression` chains the three smoke children and
`benchmark_k8s_resume`. It has no retained root of its own. Inspect
`infra_one_vm`, `software_k8s_two_vm`, `network_netperf_two_vm` and
`benchmark_k8s_resume` beneath the selected root. Benchmark phase aliases map
to that same benchmark child directory.

Registry priming runs as the normal user with existing Docker access:

```bash
sh scripts/test/run_smoke_host.sh prime-registry-cache --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh prime-registry-cache --check-only --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh check-prereqs --suite qemu_openfaas_image_parity
sh scripts/test/run_smoke_host.sh qemu_openfaas_image_parity
```

For the foundation family, use the existing `qemu_infra_parity`,
`network_validation`, `qemu_k8s_image_parity`, `qemu_endpoint_image_parity` and
`qemu_k8s_nobench_parity` scenarios alongside `operational_regression`.
Image scenarios require their checked local registry images; tc/netperf and the
guest package/image repositories must be available where configured. The
no-benchmark scenario installs Kubernetes, endpoint runtime and observability;
it supplies no image-classification application evidence. Most profiles retain
guests; endpoint image, all-tier infrastructure parity and the final benchmark
resume phase request teardown. Scenario directories preserve files but guest
names and QEMU startup cleanup are scoped to the Unix username. Preserve prior
evidence and settle retained-guest disposition before starting another scenario.

When observability is enabled, its software role waits up to 20 minutes each
for Grafana deployment availability and both replicas of `Prometheus/k8s` in
`monitoring`. It checks Grafana `/api/health` (HTTP 200 and database `ok`) and
Prometheus `/-/ready` (HTTP 200) through their guest-local port-forwards on every
distinct advertised controller address. Each HTTP check uses a five-second
socket timeout and at most thirteen attempts with five-second retry delays.
Response reads and overhead mean this is not a total HTTP elapsed-time deadline;
the existing runner timeout and owned-process cleanup bound the workflow.
Success records the health responses and verifies the selected forwarding PID's
UID and exact command. This proves readiness at that point, not continued
availability, complete scrape coverage or accurate cross-guest timing.

Forwarding runs inside the cloudcontroller guest under the playbook's become
identity. The role reuses one exact same-UID process or starts a missing forward;
duplicates, identity changes and failed health checks fail without killing or
restarting other processes. Guest logs append to
`/var/log/continuum-observability/grafana-port-forward.log` and
`/var/log/continuum-observability/prometheus-port-forward.log` with mode 0600
inside a 0700 directory. Failure output preserves the original error and bounded
resource/pod/PID diagnostics plus the final 80 log lines. Inspect and preserve
those logs before diagnosing a retry; an older reused forward may have no earlier
log because the previous role discarded its output. Record the actual installed
kube-prometheus checkout and Kubernetes versions; historical evidence and the
configured release branch do not establish their exact installed revisions.

Run only the exact scenario authorized by the active packet. Before host
execution, record clean HEAD/status and verify prerequisites. No concurrent
runs may share one base path. A cache belongs to one stable runner identity.

For raw Ansible task and recap evidence, optionally export the standard
`ANSIBLE_LOG_PATH` to an absolute path outside the checkout before a suite or
single-config run. Use a private pre-existing `0700` evidence directory and a
precreated `0600` log file. The runner forwards only a nonempty value through
its otherwise unchanged cleared environment; unset/empty values are omitted.
Ansible logs can contain secrets: never commit them. Verify the log is nonempty
and contains the expected play recaps before recording its hash as evidence;
an empty file proves no host outcome. Default logging behavior is unchanged.

QEMU validates each owning host/profile slot and decides reuse or rebuilding.
The runner does not delete guessed base images: `--rebuild-base-images`,
`--use-cache`, and the root/suite test-config keys `base_image_rebuild_frequency`,
`rebuild_base_images`, `use_cache` are retired and rejected. The retained result
field `base_images_rebuilt: []` makes no claim about QEMU's runtime decisions.
Invalid-cache cleanup removes only its ready sidecar, QCOW2 and derived cloud-init
disk, not the current run's user-data YAML. Inspection/access failures abort with
path, numeric ownership/mode and ACL context; no permission repair is automatic.
Existing peer disks skipped by creation keep their mode and ACLs unchanged.

Keep failed state until diagnosis. Before pruning, preserve compact evidence
outside the child root, identify excluded disks and show the exact target.
Deletion requires the explicit confirmation flag:

```bash
sh scripts/test/run_smoke_host.sh prune-scenario benchmark_k8s_resume --yes-delete-retained-state
```

This removes that child's retained state, including disks, not an aggregate
suite. Evidence excluded from a snapshot cannot be claimed as preserved.

## Direct diagnostics and completed retirement

The temporary framework-owned diagnostic replay command and its dedicated
playbook are removed after the completed QEMU diagnosis and exact multi-host
verification. Use the summary/indexed-full tail above, retained logs/state/lock,
and ordinary SSH/operator tools against the exact affected host. See
`docs/vm_debugging_runbook.md`; no replacement command runner is provided.

Historical evidence documents retain their original account and commands.
Their runs are not renewed by this migration. Both old accounts/private groups
and installed helpers are retired after verified normal-user local/external
validation, private snapshots and exact UID/GID/ACL auditing. Old data/helpers
remain recoverable in root-private /var/lib/continuum-retired-20261027-node4 and
the node3 counterpart; normal identities and preexisting grants are unchanged.
See `docs/rework_release_handoff.md` for the evidence checkpoint. Never use runtime
recursive chown, broad permission repair or an automatic fallback to sudo.
