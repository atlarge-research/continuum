# Issues and Troubleshooting

This document lists common operational problems when running Continuum. For the
active input model, use YAML experiments under `configs/experiments/` and
profiles under `configs/profiles/`. Legacy `.cfg` files under `configuration/`
are kept for historical reproduction and migration reference only.

Start debugging in this order:

1. inspect the main log under `<base_path>/.continuum/logs/`,
2. inspect `<base_path>/.continuum/experiment_lock.yaml`,
3. inspect `<base_path>/.continuum/state.json`,
4. use the SSH hints logged after infrastructure or resume-state loading,
5. use `docs/vm_debugging_runbook.md` before rerunning a retained smoke path.

## QEMU, Libvirt, and KVM

### Existing or stale domains

If provisioning fails because a domain already exists, list domains and remove
only the stale Continuum domains you intend to discard:

```bash
virsh list --all
virsh destroy <domain-name>
virsh undefine <domain-name>
```

For smoke runs, prefer the runner teardown path when possible. Manual cleanup is
best reserved for broken retained states after artifacts have been inspected.

### Missing default network or bridge problems

Continuum's local QEMU path expects usable libvirt and bridge networking. If VMs
cannot reach the network, first check:

```bash
virsh net-list --all
ip route
ip addr
```

See `docs/NETWORK.md` for the current bridge guidance. The QEMU smoke wrapper
also supports explicit bridge overrides through `CONTINUUM_QEMU_BRIDGE_NAME` and
`CONTINUUM_QEMU_BRIDGE_GATEWAY` when the installed host setup forwards them.

### Permission denied for QEMU or libvirt storage

Verify that the runner user belongs to the required groups and that the selected
`base_path` is writable by that user:

```bash
groups
ls -ld <base_path> <base_path>/.continuum
```

For agent-run smoke work, prefer the dedicated-user model in
`docs/smoke_runner_isolation.md` instead of broad root shell access.

### CPU pinning fails

CPU pinning can only use cores exposed by the host cgroup configuration. Check
`/sys/fs/cgroup/cpuset/cpuset.cpus` and related machine-slice cpuset files
before treating this as a Continuum scheduling bug.

## Docker and Local Registry

If a guest reports `server gave HTTP response to HTTPS client`, the local Docker
registry is being contacted over HTTP without an insecure-registry entry. Check
Docker daemon configuration on the involved VM and restart Docker after changes.

The local registry is now internal runtime behavior. User intent is only
`run.image_prefetch` in YAML; do not add `infrastructure.image_prefetch` to new
configs.

## Ansible

If an Ansible playbook appears to hang, first confirm the VM is reachable and has
working outbound network access. The most useful first checks are:

```bash
ssh user@ip -i key ls
systemctl --failed
journalctl -xe --no-pager | tail -n 100
```

Continuum now pins controller and guest Ansible temp directories for the active
runner paths. Permission failures are usually host setup, base-path ownership, or
VM reachability problems rather than a request to run Continuum with `sudo`.

For retained benchmark smoke debugging, use the installed wrapper's bounded
`debug-playbook` entrypoint documented in `docs/smoke_runner_isolation.md`.

## Resume-State Problems

Schema-v2 `state.json` must match the resolved lock's `resume_contract`. If a
resumed run fails before software or application execution, compare:

- `<base_path>/.continuum/experiment_lock.yaml`
- `<base_path>/.continuum/state.json`

Old retained state without schema-v2 metadata is invalid for the active rework
baseline. Regenerate it by rerunning the infrastructure leg with the intended
YAML and profile set.
