# Smoke Runner Isolation

This document describes the canonical host setup for letting an agent run real
VM-backed Continuum smoke and benchmark paths without granting broad shell
access.

This is an operator workflow document, not a release-support matrix. Exact
supported module combinations and certification status are tracked in
`docs/release_certification_matrix.md`.

## 1. Goal

The desired operating model is:

1. Continuum can reach real host QEMU/libvirt and `/dev/kvm`.
2. The agent cannot execute arbitrary host commands.
3. The executed Continuum checkout is as immutable as practical.
4. All runtime logs and test artifacts live under the selected `base_path`,
   currently `/mnt/sdc/continuum_smoke`, not inside the repository checkout.

## 2. Canonical Model

The preferred design is:

1. a dedicated local account such as `continuum-smoke`,
2. a root-owned installed wrapper such as `/usr/local/bin/run-continuum-smoke`,
3. a root-owned maintenance helper such as `/usr/local/bin/continuum-hostctl`,
4. a dedicated synced repo copy at `/srv/continuum/repo`,
5. that dedicated repo copy owned by `root:continuum-smoke` and not writable by
   the runner user,
6. one setup script that provisions the full model:
   - [setup_agent_host.sh](/home/matthijs/continuum/scripts/test/setup_agent_host.sh)

The repo-local development wrapper is still:

- [run_smoke_host.sh](/home/matthijs/continuum/scripts/test/run_smoke_host.sh)

That file is useful for local/manual runs, but it should not be the external
allowlisted command when it lives in a mutable checkout.

## 3. Why This Boundary Is Tight

The smoke path actually needs:

1. host `virsh` / libvirt access,
2. `/dev/kvm` access,
3. host bridge and route inspection commands,
4. write access to the dedicated runtime workspace
   `/mnt/sdc/continuum_smoke/`,
5. read access to the executed Continuum checkout.

It does not need:

1. a general unsandboxed shell,
2. write access to the executed repo copy,
3. repo-local runtime logs,
4. repo-local test-result artifacts.

That last point matters. Continuum now writes runtime logs and smoke-test result
artifacts under `base_path/.continuum/...`, and the wrapper exports
`PYTHONDONTWRITEBYTECODE=1` with cache paths under the retained smoke root, so
the dedicated execution checkout can stay read-only for the runner.

The current retained root is `/mnt/sdc/continuum_smoke`. The legacy
`/home/continuum-smoke/continuum_smoke` path remains a compatibility symlink to
that larger disk and should not be removed independently.

## 4. Single-Script Setup

The default and recommended setup is the dedicated read-only repo mode:

```bash
./scripts/test/setup_agent_host.sh show-config
./scripts/test/setup_agent_host.sh install
./scripts/test/setup_agent_host.sh verify
./scripts/test/setup_agent_host.sh print-agent-command benchmark_k8s_resume
```

`install` defaults to `dedicated`. That flow:

1. creates or verifies the `continuum-smoke` account,
2. adds it to `libvirt` and `kvm`,
3. creates `/srv/continuum/repo`,
4. syncs the current workspace into that repo copy,
5. locks that repo copy down as non-writable for the runner,
6. prepares the retained smoke root,
7. installs host prerequisites,
8. creates the dedicated runner venv,
9. installs the root-owned wrapper,
10. installs the root-owned maintenance helper,
11. installs the narrow `sudoers` rules,
12. verifies libvirt, `/dev/kvm`, repo readability, and wrapper prereqs.

`sync-repo` now also writes a small sync marker inside the dedicated repo. That
marker records which live checkout was synced and when. `show-config` prints the
marker path and contents when present, and `verify` now fails fast if:

1. the installed wrapper points at the wrong repo root,
2. the dedicated sync marker is missing,
3. the dedicated repo was synced from a different live checkout, or
4. a curated set of critical files differs between the live checkout and the
   dedicated repo copy,
5. the installed maintenance helper interface is older than the live checkout
   expects.

If you update the live workspace later, refresh the dedicated execution copy
with:

```bash
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated /mnt/sdc/continuum_smoke
sudo -n /usr/local/bin/continuum-hostctl verify
sh scripts/test/setup_agent_host.sh verify
```

The root-owned helper treats `/home/matthijs/continuum` as untrusted mutable
input. It may sync data out of the checkout, but it must not execute repo
scripts, import Continuum Python modules, or preserve unsafe ownership or
special-file metadata as root.

When `LIBVIRT_URI=qemu:///system`, membership in `libvirt`/`kvm` makes
`continuum-smoke` a high-trust automation user rather than a strong sandbox.
Prefer narrower libvirt modes only when they do not break the Continuum scenario
being certified.

If `verify` reports that the maintenance helper itself is stale, replacing
`/usr/local/bin/continuum-hostctl` is a manual reviewed operator action.
Agents should keep using the installed allowlisted helper until it is replaced.
Do not add sudoers access to `scripts/test/setup_agent_host.sh` directly,
because that file lives in a mutable checkout.

The repo-side content intended for `/usr/local/bin/continuum-hostctl` is exactly
the output of:

```bash
sh /home/matthijs/continuum/scripts/test/setup_agent_host.sh print-hostctl-script
```

An operator can replace the installed helper after review with:

```bash
tmp=$(mktemp /tmp/continuum-hostctl.XXXXXX)
sh /home/matthijs/continuum/scripts/test/setup_agent_host.sh print-hostctl-script > "$tmp"
sha256sum "$tmp"
less "$tmp"
sudo install -o root -g root -m 0755 "$tmp" /usr/local/bin/continuum-hostctl
rm -f "$tmp"
```

Do not reintroduce `/usr/local/sbin/continuum-refresh-hostctl` or any sudoers
rule that lets an agent regenerate the root-owned helper from repo-controlled
code.

For pre-tag release checks, run both verification commands in the order shown
above. An older installed helper can pass its own `verify` command before it
knows about a newer helper-interface contract; the live setup-script verifier
is the check that catches that drift. The live verifier uses noninteractive
`sudo -n` for root-owned read checks, so missing sudo privileges fail fast
instead of prompting during release checks.

```bash
sudo -n /usr/local/bin/continuum-hostctl verify
```

The exact command the agent should use after installation is:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume
```

To run only the three phase-boundary smoke scenarios in one wrapper call, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke phase_smoke_matrix
```

To run the full local operational regression baseline in one wrapper call, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression
```

To validate retained release-evidence artifacts with the same user that owns
the smoke state, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit
```

To run the dedicated network-validation suite through the same allowlisted
wrapper, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation
```

To run the QEMU infrastructure parity suite for the old infra-only QEMU rows,
use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity
```

To run the QEMU Kubernetes no-benchmark parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity
```

To run the QEMU Kubernetes image-classification parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_image_parity
```

This full application suite uses `image_prefetch: "off"` and therefore expects
the required application images to exist in the local registry cache before VM
provisioning starts:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_k8s_image_parity
```

To run the QEMU KubeEdge software-only parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity
```

To preflight the full QEMU KubeEdge image-classification parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity
```

This full application suite uses `image_prefetch: "off"`, so the dedicated
smoke user only needs the required application images to exist in the local
registry cache before VM provisioning starts. Prime that cache as a
Docker-capable user:

```bash
python3 scripts/test/prime_local_registry_cache.py --suite qemu_kubeedge_image_parity
```

After refreshing the installed host maintenance helper, operators can also use:

```bash
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_kubeedge_image_parity
```

To run the QEMU Mist software-only parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity
```

To preflight the full QEMU Mist image-classification parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_image_parity
```

This full application suite also uses `image_prefetch: "off"` and therefore
expects a primed local registry cache rather than Docker daemon access for the
dedicated smoke user:

```bash
python3 scripts/test/prime_local_registry_cache.py --suite qemu_mist_image_parity
```

To run the QEMU endpoint-runtime software-only parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity
```

To preflight the full QEMU endpoint image-classification parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_image_parity
```

This full application suite uses the same cache-backed registry model as the
other certified application parity rows:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_endpoint_image_parity
```

To run the QEMU OpenFaaS software-only suite on the single-host CPU-capped
variant, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity
```

To preflight the full QEMU OpenFaaS image-classification parity suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_parity
```

This full application suite uses the cache-backed registry model. It still
requires the local registry cache to be primed before starting VMs, and it is
not release-certified until the exact resource/capacity boundary is resolved
and retained VM/application evidence passes.

After installing the `2026-07-03-columbo-empty-cache` hostctl interface, prime
the OpenFaaS application image cache with the reviewed root-owned helper:

```bash
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_openfaas_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_openfaas_image_parity
```

To run the Columbo-style QEMU kubecontrol plus `empty` application suite, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_parity
```

This suite uses the same cache-backed registry model for
`redplanet00/kubeedge-applications:empty`. After installing the
`2026-07-03-columbo-empty-cache` hostctl interface, prime and verify the cache
before starting VMs:

```bash
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_kubecontrol_empty_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_kubecontrol_empty_parity
```

To advance the retained benchmark state one phase at a time, use:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_infra
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_software
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application
```

For phase-level Ansible replay after a retained-state failure, the installed
wrapper also supports:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  debug-playbook benchmark_k8s_resume_software playbooks/resource_manager/k8s_cluster.yml
```

That reuses the retained benchmark workspace, inventory, and Ansible temp-path
settings, and adds `-vvv` automatically.

The maintenance helper exists so future agents do not need a broad root shell
just to refresh the dedicated repo copy or reinstall the fixed wrapper. It is a
separate command from the runner wrapper on purpose:

1. `run-continuum-smoke` executes Continuum as the unprivileged runner user,
2. `continuum-hostctl` performs only a tiny allowlisted maintenance surface as
   root,
3. the helper never shells out to the mutable repo setup script, so root does
   not execute arbitrary checkout code.

## 4a. Current Access Shape

At the repo level, this model is now in place.

The intended agent boundary is narrow host-command access, not a broad root
shell. When the surrounding harness has approved the exact prefixes below, an
agent can verify/sync the dedicated repo and run the smoke wrapper without a
human copy/paste step:

1. `sudo -n /usr/local/bin/continuum-hostctl`
2. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke`

If those exact prefixes are not available in a future harness, the
environment-side fix should still be:

1. allow the harness to execute only:
   - `sudo -n /usr/local/bin/continuum-hostctl`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke`
2. do not broaden that to arbitrary `sudo`, `bash`, or `python3`
3. once that is working, the human copy/paste step should disappear entirely

## 5. Weaker Live-Repo Mode

If you want the wrapper to execute the current working tree directly, the setup
script still supports:

```bash
./scripts/test/setup_agent_host.sh install live
```

That mode is weaker because the executed code remains mutable by the caller. It
is still tighter than before because the runner only receives read/traverse ACLs
to the live checkout, not write access.

Use live mode only when you explicitly want zero sync friction and accept that
weaker code-integrity boundary.

## 6. Wrapper Contract

The installed wrapper supports only these values:

1. `phase_smoke_matrix`
2. `operational_regression`
3. `infra_one_vm`
4. `software_k8s_two_vm`
5. `network_netperf_two_vm`
6. `network_validation`
7. `qemu_infra_parity`
8. `qemu_k8s_nobench_parity`
9. `qemu_k8s_image_parity`
10. `qemu_kubeedge_software_parity`
11. `qemu_kubeedge_image_parity`
12. `qemu_mist_software_parity`
13. `qemu_mist_image_parity`
14. `qemu_endpoint_software_parity`
15. `qemu_endpoint_image_parity`
16. `qemu_openfaas_software_parity`
17. `qemu_openfaas_image_parity`
18. `qemu_openfaas_image_local_parity`
19. `qemu_kubecontrol_empty_parity`
20. `benchmark_k8s_resume_infra`
21. `benchmark_k8s_resume_software`
22. `benchmark_k8s_resume_application`
23. `benchmark_k8s_resume`
24. `release-artifact-audit`
25. `check-prereqs`
26. `list-suites`
27. `storage-report`
28. `prune-scenario <scenario> --yes-delete-retained-state`
29. `debug-playbook <scenario> <playbook> [ansible args...]`

The wrapper contract is:

1. whitelists those scenarios and the dedicated debug-playbook entrypoint,
2. forces a fixed `base_path` per scenario under the runner home,
3. uses `env -i`,
4. forces a minimal `PATH` with the dedicated venv first,
5. forces `PYTHONPATH=.`,
6. forces `PYTHONDONTWRITEBYTECODE=1`,
7. forces `LIBVIRT_DEFAULT_URI=qemu:///system` unless overridden at install
   time,
8. forwards only the explicitly whitelisted bridge overrides:
   - `CONTINUUM_QEMU_BRIDGE_NAME`
   - `CONTINUUM_QEMU_BRIDGE_GATEWAY`
9. writes runtime logs, matplotlib state, and test artifacts under
   `<base_path>/.continuum/...`,
10. runs with `umask 027` and explicit chmods for generated runtime paths.
11. exposes `storage-report` and `prune-scenario` as unprivileged retained-state
    maintenance commands,
12. `debug-playbook` is for bounded replay only; it should not become a shell
    escape hatch.

## 7. Retained State And Disk Use

The smoke runner intentionally uses one retained workspace per scenario under
`SMOKE_BASE_ROOT`, for example:

```text
/home/continuum-smoke/continuum_smoke/qemu_kubeedge_image_parity/.continuum/
```

This is useful while debugging failed VM-backed runs because `debug-playbook`
can reuse the scenario inventory, SSH keys, Ansible paths, logs, state, and VM
image cache. It should not be treated as permanent archival storage. A retained
scenario can contain large qcow2 base images, per-run overlay images, cloud-init
disks, logs, and test-result artifacts.

Use the unprivileged wrapper to inspect retained storage:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke storage-report
```

Use explicit scenario pruning after evidence has been recorded or a failure has
been diagnosed:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prune-scenario qemu_kubeedge_image_parity --yes-delete-retained-state
```

`prune-scenario` only accepts known retained scenario names and only removes the
selected scenario root below `SMOKE_BASE_ROOT`. It is deliberately implemented
in `run-continuum-smoke` rather than `continuum-hostctl` so retained-state
cleanup does not require a root-level delete command.

Recommended retention policy:

1. keep the active failed scenario until the failure is understood,
2. keep base-image caches for scenarios that are still being iterated,
3. preserve compact release evidence in docs and test-results artifacts,
4. prune superseded scenario roots after the evidence is captured,
5. move `SMOKE_BASE_ROOT` to a large disk for sustained parity certification.

To move retained smoke state to a larger disk such as `/mnt/sdc`, prepare the
target as root/operator work and regenerate the installed wrapper with the new
base root. Existing retained state migration is an operator action; wrapper
installation and verification stay inside the narrow `continuum-hostctl`
surface:

```bash
sudo -n /usr/local/bin/continuum-hostctl \
  relocate-smoke-root /mnt/sdc/continuum_smoke --replace-source-with-symlink
sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated /mnt/sdc/continuum_smoke
sudo -n /usr/local/bin/continuum-hostctl verify
```

`relocate-smoke-root` copies retained state to the target, replaces the old
`/home/continuum-smoke/continuum_smoke` directory with a symlink after the copy
has succeeded, and only then removes the old root-backed copy. The confirmation
flag is required because this is the step that frees root filesystem space.

After verifying the relocated runner, the old
`/home/continuum-smoke/continuum_smoke` evidence paths should still resolve
through the symlink. Do not leave agents with broad sudo access to remove
arbitrary host paths.

## 8. Host Requirements

The dedicated smoke user should have:

1. membership in `libvirt`,
2. membership in `kvm`,
3. read access to the executed repo copy,
4. write access to the selected `base_path`,
5. access to host commands used by the smoke path.

The scripted host-prereq step currently installs:

1. `acl`
2. `curl`
3. `qemu-utils`
4. `cloud-image-utils`

## 9. Sudoers Shape

If direct login as `continuum-smoke` is not desirable, prefer a narrow wrapper
rule over broad shell access.

The installed setup writes rules shaped like:

```text
Cmnd_Alias CONTINUUM_SMOKE = /usr/local/bin/run-continuum-smoke *
Cmnd_Alias CONTINUUM_HOSTCTL = /usr/local/bin/continuum-hostctl *
your-user ALL=(continuum-smoke) NOPASSWD: CONTINUUM_SMOKE
your-user ALL=(root) NOPASSWD: CONTINUUM_HOSTCTL
```

The important part is not the alias names. The important part is that the
caller can invoke only the approved runner and maintenance helpers, not an
arbitrary shell.

## 10. External Allowlisting

If the surrounding harness supports external-command allowlisting, the allowed
prefixes should be only:

1. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke`
2. `sudo -n /usr/local/bin/continuum-hostctl`

Do not allow broader prefixes such as `/bin/bash`, `python3`, or `sudo` more
generally.

## 11. Operational Advice

For first real host runs:

1. start with `infra_one_vm`,
2. then `software_k8s_two_vm`,
3. then `benchmark_k8s_resume_infra` if you want only the retained infrastructure step,
4. then `benchmark_k8s_resume_software` and `benchmark_k8s_resume_application` to advance the retained state one phase at a time,
5. or use `benchmark_k8s_resume` to run the full three-step suite end-to-end,
6. inspect retained artifacts under
   `/home/continuum-smoke/continuum_smoke/<scenario>/.continuum/`,
7. keep failed VM state until the failure is understood,
8. run the unprivileged `storage-report` command periodically during parity
   certification,
9. prune superseded scenario roots after release evidence has been captured,
10. run `sudo -n /usr/local/bin/continuum-hostctl verify` before reruns if the
   live workspace changed,
11. resync the dedicated repo before reruns if `verify` reports drift.

For operational reruns:

1. run `sudo -n /usr/local/bin/continuum-hostctl verify` before reruns,
2. resync/install the wrapper only if `verify` reports drift,
3. rerun the narrow scenario affected by the current patch, or
   `operational_regression` when a change affects shared runner behavior,
4. the benchmark launch playbooks no longer use `kubernetes.core.k8s`; they now
   use `kubectl apply -f`, so future retained application failures should be
   benchmark/runtime failures rather than remote Python dependency failures,
5. `infrastructure/ansible.py` now logs the failing stdout/stderr tail on
   nonzero Ansible exits, so the main run should usually be enough to diagnose
   a retained-run failure.
