# Issues and Troubleshooting

This document lists common operational problems when running Continuum. For the active input model, use YAML experiments under `configs/experiments/` and profiles under `configs/profiles/`. Legacy `.cfg` files under `configuration/` are kept for historical reproduction and migration reference only.

Start debugging in this order:

1. inspect the main log under `<base_path>/.continuum/logs/`,
2. inspect `<base_path>/.continuum/experiment_lock.yaml`,
3. inspect `<base_path>/.continuum/state.json`,
4. use the SSH hints logged after infrastructure or resume-state loading,
5. use `docs/vm_debugging_runbook.md` before rerunning a retained smoke path.

## QEMU, Libvirt, and KVM

### Existing or stale domains

If provisioning fails because a domain already exists, list domains and remove only the stale Continuum domains you intend to discard:

```bash
virsh list --all
virsh destroy <domain-name>
virsh undefine <domain-name>
```

For smoke runs, prefer the runner teardown path when possible. Manual cleanup is best reserved for broken retained states after artifacts have been inspected.

### Missing default network or bridge problems

Continuum's local QEMU path expects usable libvirt and bridge networking. If VMs cannot reach the network, first check:

```bash
virsh net-list --all
ip route
ip addr
```

See `docs/NETWORK.md` for the current bridge guidance. The QEMU smoke wrapper also supports explicit bridge overrides through `CONTINUUM_QEMU_BRIDGE_NAME` and `CONTINUUM_QEMU_BRIDGE_GATEWAY`; the repository runner forwards explicit values.

### Permission denied for QEMU or libvirt storage

Verify that the runner user belongs to the required groups and that the selected `base_path` is writable by that user:

```bash
groups
ls -ld <base_path> <base_path>/.continuum
```

For agent-run smoke work, use the normal-user repository-script workflow in `docs/smoke_runner_isolation.md`. Never run the framework or Ansible as root.

### CPU pinning fails

CPU pinning can only use cores exposed by the host cgroup configuration. Check `/sys/fs/cgroup/cpuset/cpuset.cpus` and related machine-slice cpuset files before treating this as a Continuum scheduling bug.

### Fresh VM SSH key discovery times out

Fresh-VM host-key discovery has one 600-second monotonic budget shared across the selected addresses, with each keyscan subprocess limited to at most five seconds or the remaining budget. A server banner alone does not establish success. On failure, inspect the reported address, elapsed time and last scan error alongside VM console, bridge and routing state. Key discovery remains unauthenticated and does not establish authenticated guest readiness; known-host handling and the existing trust policy still apply.

## Docker and Local Registry

If a guest reports `server gave HTTP response to HTTPS client`, the local Docker registry is being contacted over HTTP without an insecure-registry entry. Check Docker daemon configuration on the involved VM and restart Docker after changes.

The local registry is now internal runtime behavior. User intent is only `run.registry_refresh: missing|all` in YAML. Both infrastructure-level registry settings and the removed run.image_prefetch key are rejected; there is no alias.

### Kubernetes subscriber image retrieval or readiness fails

Current-execution MQTT subscribers must be `Running` with the pod condition `Ready=True` before publishers start. Missing readiness conditions and completed subscribers cannot satisfy startup; `Succeeded` still satisfies completion polling. Readiness does not establish application-level MQTT subscription. The existing `worker_ready_timeout_seconds` deadline applies, and primary Kubernetes API/transport errors still fail immediately.

Watch the changing pod conditions and init/container waiting reasons in the main log. Kubernetes performs its own image-pull retries; Continuum waits within the existing deadline without restarting deployments. On timeout or terminal pod failure, the log includes a best-effort event excerpt for up to three selected pod UIDs, at most ten events per pod and 500 message characters per event, with a five-second API request timeout. Event collection failure is secondary to the original error; absent pod UIDs produce no unscoped event query.

When image retrieval fails, inspect DNS, routes and registry reachability from the affected guest and read the actual container-runtime error. Successful host access does not establish guest access. Docker forwarding rules can interfere with connectivity, but inspect the actual path before changing them. Check advertised HTTP endpoints separately from pod health. Preserve failed state and logs before a reviewed rerun; avoid blanket retries or automatic firewall changes.

## Ansible

If an Ansible playbook appears to hang, first confirm the VM is reachable and has working outbound network access. The most useful first checks are:

```bash
ssh user@ip -i key ls
systemctl --failed
journalctl -xe --no-pager | tail -n 100
```

Continuum now pins controller and guest Ansible temp directories for the active runner paths. Permission failures are usually host setup, base-path ownership, or VM reachability problems rather than a request to run Continuum with `sudo`.

For retained benchmark failures, use the repository runner's `latest-result-summary` and indexed/full `latest-result-tail`, then inspect the retained state, lock and logs. Use standard SSH, systemctl and journalctl against the exact affected host; see `docs/smoke_runner_isolation.md`. Preserve evidence before a reviewed rerun.

## Resume-State Problems

Schema-v2 `state.json` must match the resolved lock's `resume_contract`. If a resumed run fails before software or application execution, compare:

- `<base_path>/.continuum/experiment_lock.yaml`
- `<base_path>/.continuum/state.json`

Old retained state without schema-v2 metadata is invalid for the active rework baseline. Regenerate it by rerunning the infrastructure leg with the intended YAML and profile set.
