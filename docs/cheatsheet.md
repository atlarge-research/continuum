# Cheat Sheet

This file lists quick operational references for the active Continuum runtime.
For the canonical YAML model, start with `docs/configuration_reference.md` and
`docs/migration_notes.md`.

## Files

Continuum runtime artifacts are rooted in the selected provider `base_path`.
For shipped local profiles, that usually means the current user's home
directory unless a runner override is used.

| What | Location | Notes |
| --- | --- | --- |
| YAML experiments | `configs/experiments/` | Active runnable examples and smoke configs |
| Environment profiles | `configs/profiles/environment/` | Provider, base path, IP, delete, and netperf settings |
| Software profiles | `configs/profiles/software/` | `software.modules[]` orchestration profiles |
| Resolved lock | `<base_path>/.continuum/experiment_lock.yaml` | Written during bootstrap before VM work |
| Resume state | `<base_path>/.continuum/state.json` | Schema-v2 state with `resume_contract` metadata |
| Runtime logs | `<base_path>/.continuum/logs/` | Includes benchmark and network-validation artifacts |
| Test summaries | `<base_path>/.continuum/test_results/` for runner overrides | Per-test stdout/stderr/metadata live beside summary JSON |
| QEMU images | `<base_path>/.continuum/images/` and host libvirt storage | Base-image reuse is guarded by success metadata |
| Legacy configs | `configuration/` | Historical reproduction and migration reference only |

## Containers

A Docker registry is created only when required image pulls exist for the
selected run targets. Continuum resolves required images from software/benchmark
intent, then prefetches into the local registry using `run.image_prefetch`:

- `off` (default): pull/push only required images missing from the local registry cache.
- `on`: force refresh pull/push for all required images.

All VMs get images from this registry when applicable. This avoids repeated
pulls across many VMs and helps prevent remote registry rate limits.

## Useful Commands

| Command | Description |
| --- | --- |
| `python3 continuum.py --help` | Show CLI options |
| `python3 continuum.py configs/experiments/infra_only.yaml` | Run a minimal YAML experiment |
| `python3 scripts/test/run_tests.py --list-suites` | Inspect configured suites and prerequisites |
| `python3 scripts/test/run_tests.py --suite smoke --check-prereqs` | Check host readiness without provisioning |
| `scripts/test/run_cloud_static_audit.sh` | Run cloud-safe compile, tests, docs, lint, and suite metadata checks |
| `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke phase_smoke_matrix` | Run the three phase-boundary host-backed smoke scenarios through the installed wrapper |
| `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression` | Run the phase matrix plus retained benchmark smoke |

## VM Debugging

Continuum logs SSH hints after infrastructure completion and when loading
retained state. If a smoke run fails after VM creation, inspect artifacts first,
then use `docs/vm_debugging_runbook.md`.

Common host-side commands:

| Command | Description |
| --- | --- |
| `virsh list --all` | List QEMU/libvirt domains |
| `virsh domifaddr <vm-name>` | Recover guest IPs when logs are incomplete |
| `ssh user@ip -i key` | SSH into a retained VM using logged hints |

Inside Kubernetes control-plane VMs:

| Command | Description |
| --- | --- |
| `kubectl get nodes -o wide` | Confirm cluster membership |
| `kubectl get pods -A` | Inspect application and system pods |
| `kubectl logs <pod>` | Read pod output |

## Network Validation

Network-validation smoke writes structured netperf NDJSON under
`<base_path>/.continuum/logs/network_validation/`. Validate an existing run with:

```bash
python3 scripts/test/verify_network_profiles.py --base-path <base_path>
```
