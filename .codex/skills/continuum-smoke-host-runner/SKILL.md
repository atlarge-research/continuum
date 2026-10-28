---
name: continuum-smoke-host-runner
description: Use when preparing or running Continuum QEMU/libvirt host suites, normal-user setup_agent_host.sh or run_smoke_host.sh, or inspecting retained benchmark runs.
---

# Continuum Physical-Host Runner

Use only on an explicitly authorized physical host. These runs create VMs and
mutate retained caches. This is high-trust normal-user execution, not a sandbox.

Read `AGENTS.md`, `docs/smoke_runner_isolation.md`,
`docs/rework_release_handoff.md`, both scripts under `scripts/test/` named in
the description, and `scripts/test/test_config.json`.

## Current command contract

Run from the reviewed live checkout as the normal user, never root:

```bash
sh scripts/test/setup_agent_host.sh show-config
sh scripts/test/setup_agent_host.sh verify
sh scripts/test/run_smoke_host.sh check-prereqs --suite smoke
sh scripts/test/run_smoke_host.sh check-prereqs --suite benchmark_smoke
sh scripts/test/run_smoke_host.sh operational_regression
```

Defaults are `$HOME/continuum_smoke` and
`$HOME/venvs/continuum/bin/python3`. Preserve explicit
`CONTINUUM_SMOKE_BASE_ROOT`/`CONTINUUM_SMOKE_PYTHON` exports for a migrated
root; use the concrete exports documented in the host workflow. Setup offers
`create-venv` for a new destination, not account/package/helper installation.
Verify prerequisites and record clean source revision/status before runtime.

The installed hostctl/wrapper and separate-account workflow is retired.
Do not sync a dedicated repo, reinstall wrappers, sudo repository code, widen
sudoers, or repair ownership automatically. A missing host capability is an
operator issue, not permission to add privileges. Follow explicit approved
migration gates before retiring old accounts, private homes or UID/ACL entries.

## Retained evidence

Inspect `latest-result-summary` and `latest-result-tail` through
`sh scripts/test/run_smoke_host.sh`. `operational_regression` has no retained
root: its children are infra_one_vm, software_k8s_two_vm,
network_netperf_two_vm and benchmark_k8s_resume. Benchmark phase aliases share
the benchmark root. Keep failure artifacts before diagnosis; no blind retries.
Prune only an explicitly approved exact child after evidence preservation and
disk-exclusion disclosure, using `--yes-delete-retained-state`.

Use the result summary to choose the exact entry, then indexed/full tail for
stdout, stderr and metadata. Inspect retained logs/state/lock and use standard
SSH/operator tools on the exact affected host. The temporary diagnostic replay
command/playbook is removed; no replacement command runner or inspector exists.
Historical evidence keeps its original runner commands and does not certify
the current candidate.

For cloud-safe validation use continuum-test-workflows and
continuum-cloud-static-audit; this skill does not authorize VM execution from
a cloud/sandbox-only environment.
