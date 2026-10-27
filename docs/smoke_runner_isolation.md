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

Run only the exact scenario authorized by the active packet. Before host
execution, record clean HEAD/status and verify prerequisites. No concurrent
runs may share one base path. A cache belongs to one stable runner identity.

Keep failed state until diagnosis. Before pruning, preserve compact evidence
outside the child root, identify excluded disks and show the exact target.
Deletion requires the explicit confirmation flag:

```bash
sh scripts/test/run_smoke_host.sh prune-scenario benchmark_k8s_resume --yes-delete-retained-state
```

This removes that child's retained state, including disks, not an aggregate
suite. Evidence excluded from a snapshot cannot be claimed as preserved.

## Temporary diagnostics and retirement

`debug-playbook` remains temporary through the current QEMU diagnosis and
multi-host verification. Use it only for bounded approved diagnostics; see
`docs/vm_debugging_runbook.md`. It is removed later, not expanded.

Historical evidence documents retain their original account and commands.
Their runs are not renewed by this migration. The installed old helpers,
old homes and accounts remain inactive during verification; remove them only
after real normal-user local/external validation, verified private snapshots,
and an exact old UID/GID/named/default ACL retirement audit. Never use runtime
recursive chown, broad permission repair or an automatic fallback to sudo.
