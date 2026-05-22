# VM Debugging Runbook

This runbook describes how to inspect Continuum-managed VMs during failed
operational smoke runs.

The intended order is:

1. read Continuum logs first,
2. inspect saved state and lock artifacts,
3. SSH into retained VMs when logs are not enough,
4. fall back to host-level `virsh` inspection on QEMU when SSH hints are missing.

## 1. When To Use This

Use this document when:

1. a smoke run fails after infrastructure has been created,
2. software installation is incomplete or inconsistent,
3. network-validation output looks wrong,
4. you need to compare VM state against Continuum logs before attempting a rerun.

Do not use this as the primary success path for tests. It is a debugging path.

## 2. First Places To Look

Start with artifacts that Continuum already writes:

1. main log under `<base_path>/.continuum/logs/`
2. resolved lock file under `<base_path>/.continuum/experiment_lock.yaml`
3. resume state under `<base_path>/.continuum/state.json`
4. test summary JSON under `<base_path>/.continuum/test_results/` when the
   suite is run with a base-path override
5. network-validation NDJSON under `<base_path>/.continuum/logs/network_validation/` when netperf is enabled
6. benchmark metric manifests and CSV tables under `<base_path>/.continuum/logs/benchmark/` when the application leg runs

## 3. SSH Hints In Runtime Logs

Continuum now logs VM access hints as soon as infrastructure provisioning
completes and SSH targets are known.

Look for log lines like:

```text
VM access hints after infrastructure phase:
    ssh cloud0@... -i ...
```

For resumed runs, look for:

```text
VM access hints from resumed state:
    ssh cloud0@... -i ...
```

At the end of successful non-delete runs, Continuum still prints the final
access summary as well.

## 4. QEMU Fallback When SSH Hints Are Missing

If a run fails before the final summary or before you notice the SSH lines,
use the host-side QEMU tooling:

```bash
virsh list --all
```

This shows which Continuum VMs are still running.

Useful follow-up commands:

```bash
virsh domifaddr <vm-name>
virsh console <vm-name>
```

`virsh domifaddr` is often the fastest way to recover the guest IP when logs are
not enough.

## 5. Minimal First-Pass Checks Inside A VM

Once you can reach a VM, start with low-cost checks.

General reachability:

```bash
ls
uname -a
systemctl --failed
```

Kubernetes smoke path:

```bash
kubectl get nodes -o wide
kubectl get pods -A
systemctl status kubelet
```

Container/runtime debugging:

```bash
docker ps -a
docker images
journalctl -u docker --no-pager | tail -n 100
```

Network-validation path:

```bash
tc qdisc show
tc class show dev ens2
pgrep netserver
```

## 6. How To Correlate VM State With Continuum Artifacts

Use these mappings:

1. log file:
   - command ordering,
   - Ansible/runtime failures,
   - phase transitions
2. experiment lock:
   - canonical normalized config,
   - planner snapshot,
   - source profile references
3. state file:
   - last completed phase,
   - persisted machine metadata,
   - SSH target lists

If VM reality and the saved state disagree, treat that as a higher-priority bug
than the immediate phase failure.

## 7. Failure-Specific Guidance

Infrastructure failure after VM creation:

1. check the host log for provisioning step boundaries,
2. recover VM names with `virsh list --all`,
3. verify guest reachability with SSH or `virsh console`,
4. compare guest IPs to `state.json`.

Software failure:

1. check SSH access hints,
2. inspect platform services (`kubelet`, container runtime, control-plane pods),
3. run `kubectl get nodes -o wide` from the control node,
4. compare observed cluster membership against the smoke scenario topology.

Network-validation failure:

1. check `<base_path>/.continuum/logs/network_validation/netperf_results_*.ndjson`,
2. run `python3 scripts/test/verify_network_profiles.py --base-path <base_path>`,
3. inspect `tc` state inside the involved VMs,
4. verify that `netserver` is running.

Resume failure:

1. inspect `<base_path>/.continuum/state.json`,
2. confirm `phase_completed`,
3. compare the `resume_contract` hash/details with `<base_path>/.continuum/experiment_lock.yaml`,
4. compare provider/resource-manager identity in the state file with the current config,
5. only then inspect VMs directly.

Retained benchmark smoke failure:

1. keep the retained base path intact,
2. inspect benchmark stdout/stderr and `<base_path>/.continuum/logs/benchmark/`,
3. use the installed wrapper's bounded `debug-playbook` scenario from `docs/smoke_runner_isolation.md` when Ansible replay is needed,
4. rerun only the smallest relevant wrapper scenario after applying a fix.

## 8. Suggested Debugging Discipline

When a smoke run fails:

1. keep all artifacts,
2. inspect logs and state first,
3. inspect VMs second,
4. apply a concrete fix,
5. rerun the smallest relevant smoke path rather than the whole matrix.

The goal is to reduce expensive reruns that are based only on guesswork.
