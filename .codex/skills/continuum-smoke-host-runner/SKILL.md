---
name: continuum-smoke-host-runner
description: Use when installing, verifying, syncing, or running Continuum's dedicated QEMU/libvirt smoke host runner, setup_agent_host.sh, run_smoke_host.sh, /usr/local/bin/run-continuum-smoke, /usr/local/bin/continuum-hostctl, benchmark_smoke retained runs, or debug-playbook diagnostics.
---

# Continuum Smoke Host Runner

Use this skill for VM-backed local smoke work. These workflows can create VMs,
touch libvirt/KVM state, mutate retained base images, and require narrow sudo
wrappers.

## Safety Boundary

Do not run arbitrary `sudo`, shell, or host maintenance commands. The intended
agent boundary is only:

```bash
sudo -n /usr/local/bin/continuum-hostctl ...
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...
```

If those prefixes are not available to the harness, ask the user to run the
exact command or to approve the exact local action. Do not widen the allowlist.

## First Read

1. `AGENTS.md`
2. `docs/smoke_runner_isolation.md`
3. `scripts/test/setup_agent_host.sh`
4. `scripts/test/run_smoke_host.sh`
5. `scripts/test/test_config.json`
6. `docs/phase_d_handoff.md` when resuming Phase-D retained benchmark work

## Host Setup Model

The preferred setup is dedicated mode:

- runner user: `continuum-smoke`
- installed runner: `/usr/local/bin/run-continuum-smoke`
- installed maintenance helper: `/usr/local/bin/continuum-hostctl`
- dedicated repo copy: `/srv/continuum/repo`
- retained state root: `/home/continuum-smoke/continuum_smoke`

Repo-local setup entrypoint:

```bash
sh scripts/test/setup_agent_host.sh show-config
sh scripts/test/setup_agent_host.sh install dedicated
```

After installation, prefer the root-owned maintenance helper:

```bash
sudo -n /usr/local/bin/continuum-hostctl show-config
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated
sudo -n /usr/local/bin/continuum-hostctl verify
```

`sync-repo` writes a `.continuum-smoke-sync` marker in the dedicated repo.
`verify` checks wrapper target, libvirt/KVM access, repo readability, dedicated
repo drift, and runner prereqs.

## Runner Scenarios

Use the installed runner for VM-backed scenarios:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke list-suites
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke check-prereqs
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke infra_one_vm
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke software_k8s_two_vm
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_netperf_two_vm
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_infra
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_software
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume
```

For retained benchmark work, run one phase at a time unless the user asks for
the full suite. Sync the dedicated repo first if the live checkout changed.

## Debug Playbook

`debug-playbook` reuses the retained scenario base path, inventory, Ansible
config, local temp path, remote temp path, runner venv, and bridge environment:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  debug-playbook benchmark_k8s_resume_software playbooks/debug/run_command.yml \
  -e debug_hosts=cloudcontroller0 \
  -e debug_command='kubectl get nodes -o wide'
```

Use `playbooks/debug/run_command.yml` only for bounded diagnostics. Get explicit
approval for the exact diagnostic command when it is not obviously read-only.

## Artifacts

Inspect retained artifacts under:

```text
/home/continuum-smoke/continuum_smoke/<scenario>/.continuum/
```

Common subdirectories include inventories, Ansible temp files, test results, VM
state, logs, and benchmark outputs. Keep failed retained state until the failure
is understood.

## When Not To Use This

For cloud-safe checks that must not start VMs, use `continuum-test-workflows` or
`continuum-cloud-static-audit` instead.
