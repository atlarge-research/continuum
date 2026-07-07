# Continuum Rework Release Handoff

## Purpose

This file is the restart point for the next agent. It records the current
verified state and the recommended next slice without requiring chat-history
reconstruction.

Policy authority remains in `docs/rework_milestone_release_plan.md` and
`docs/release_certification_matrix.md`. This document is a checkpoint and
handoff only.

## Current Verified State

Start in `/home/matthijs/continuum` on branch `pr-23-curated`.

Latest committed checkpoint:

```text
0d5f8f2 refresh release evidence for july 6 runs
```

At that checkpoint, the worktree was clean and these gates passed:

1. `python3 scripts/test/check_release_pretag.py`
   - `TOTAL_RELEASE_PRETAG_ISSUES=0`
2. `python3 scripts/test/check_release_matrix.py`
   - `TOTAL_RELEASE_MATRIX_ISSUES=0`
3. `python3 scripts/test/check_release_claims.py`
   - `TOTAL_RELEASE_CLAIM_ISSUES=0`
4. `python3 scripts/test/check_docs_paths.py`
   - `TOTAL_MISSING_REFERENCES=0`
5. `python3 -m unittest scripts.test.unit.test_check_release_pretag scripts.test.unit.test_check_release_evidence_artifacts`
   - 143 tests OK
6. `git diff --check`
   - clean
7. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
   - synced `/home/matthijs/continuum` to `/srv/continuum/repo`
8. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit`
   - `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0`

The current M1 evidence snapshot is:

```text
docs/release_evidence_m1_2026-07-06.md
```

It records VM-backed evidence from source commit
`c6a7bd8db167833593d110cbd45b89d7a2afd86c` and the latest cloud-safe audit
report:

```text
logs/cloud_static_audit/cloud_static_audit_2026-07-06T140907Z.md
```

That audit recorded required gates passing, 639 unit unittest tests, 100 local
e2e unittest tests, 739 combined unittest tests, and a 739-test pytest mirror.
Generated `logs/cloud_static_audit/*.md` reports stay uncommitted unless a
maintainer explicitly asks for a dated audit snapshot.

## Certified Scope

Claim only what is marked `core-ready` or `certified` in
`docs/release_certification_matrix.md`.

Current certified/core-ready highlights:

1. M1 cloud-safe core checks and local QEMU/libvirt vertical slices.
2. QEMU old-main rows `P-QEMU-01` through `P-QEMU-09`.
3. Software-only subset rows `P-QEMU-06-SW`, `P-QEMU-07-SW`,
   `P-QEMU-08-SW`, and `P-QEMU-10-SW-LOCAL`.
4. Local CPU-capped OpenFaaS application subset `P-QEMU-10-APP-LOCAL`.
5. Research case-study rows:
   - `M2-QEMU-KUBECONTROL-EMPTY`
   - `M2-QEMU-KUBECONTROL-TRACE`

The Columbo/kubecontrol distinction matters:

1. `M2-QEMU-KUBECONTROL-EMPTY` certifies the Continuum
   module/profile/suite/docs integration for the Columbo-style workflow. Its
   retained July 3 evidence exposes kubelet, application, and resource evidence,
   but not every legacy control-plane trace point.
2. `M2-QEMU-KUBECONTROL-TRACE` certifies full control-plane trace reproduction
   for the minimal local-QEMU `empty` per-call profile. Its July 6 retained
   evidence requires populated controller, scheduler, kubelet, and application
   timing columns in both `CLOUD OUTPUT` and benchmark metric artifacts.
3. Neither row certifies every Columbo paper figure, parameter sweep, cloud
   provider, non-QEMU topology, `empty_kata`, `kube_kata`, or broader
   kubecontrol application coverage.

The implementation claim is architectural: the paper workflow is represented
through Continuum modules, profiles, experiments, suites, and docs. Do not add
Columbo-specific concepts to Continuum core. Any shared/core changes must be
treated as generic gaps and documented that way.

## Known Remaining Blocker

The next unclaimed QEMU parent row is:

```text
P-QEMU-10
```

It corresponds to:

```text
configuration/tests/qemu/10_kubernetes-openfaas.cfg
configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml
suite qemu_openfaas_image_parity
```

`P-QEMU-10-SW-LOCAL` and `P-QEMU-10-APP-LOCAL` are certified only as local
single-host, CPU-capped subset rows. They must not be used to claim exact
parent-row parity.

The exact parent row remains `ported-unverified` because its 26-core legacy
resource shape needs reachable external QEMU capacity that the dedicated
runner can authenticate to, or a larger local runner. The latest retained
failed run from 2026-07-07 selected legacy external host `matthijs@node1` and
failed before provisioning because `continuum-smoke` could not authenticate:

```text
/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/test_results/test_results_2026-07-07_08-11-02.json
```

That run followed a small runtime fix so remote physical-machine hardware
checks use Continuum's managed SSH path instead of bypassing its known-hosts
handling. Before that fix, `matthijs@node3` failed earlier with host-key
verification; after the fix, both `matthijs@node3` and `matthijs@node1`
reached SSH authentication and failed with `Permission denied`.

Do not reduce CPU or node shape and then certify `P-QEMU-10`. A reduced-shape
run is another subset row unless the matrix explicitly says otherwise.

## Next Recommended Slice

First fix any new release gate, docs, or checker issue that appears in the
current tree. If the tree is still clean and release gates pass, move to
dedicated-runner external-host authentication for exact `P-QEMU-10`, or use a
larger local runner.

Recommended start:

```bash
cd /home/matthijs/continuum
cat AGENTS.md
git status --short
git log --oneline -5
python3 scripts/test/check_release_pretag.py
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_docs_paths.py
```

Then inspect the exact parent-row inputs:

```bash
sed -n '130,145p' docs/release_certification_matrix.md
sed -n '150,175p' docs/release_certification_matrix.md
sed -n '280,325p' docs/smoke_runner_isolation.md
python3 scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_parity
```

Before any VM-backed run, verify the dedicated host wrapper and cache state:

```bash
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_openfaas_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_openfaas_image_parity
```

Run the exact suite only after the dedicated runner can authenticate to the
external host, or a larger local runner is available, and the operator has
agreed to spend the VM time:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_parity
```

If the exact suite passes, add a new evidence doc for the parent row, for
example:

```text
docs/release_evidence_qemu_openfaas_image_YYYY-MM-DD.md
```

Then update:

1. `docs/release_certification_matrix.md`
   - promote `P-QEMU-10` only if exact resource parity passed,
   - update the `qemu`, `kubernetes`, `openfaas`, and `endpoint_runtime`
     backlog rows if their claim boundaries broaden.
2. `docs/release_notes_m1_draft.md`
   - include the new ready row and evidence only if it is meant to be part of
     the current milestone publication.
3. `docs/old_main_parity_issue_seed.md`
   - remove or close the non-ready seed for `P-QEMU-10` once the matrix row is
     certified, or keep it synchronized if the row remains unclaimed.
4. `scripts/test/test_config.json` and checker tests only if the success
   detection or suite contract changes.

After evidence docs are updated, rerun:

```bash
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_docs_paths.py
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit
python3 scripts/test/check_release_pretag.py
git diff --check
```

If authenticated capacity for exact `P-QEMU-10` is not available, keep the row
unclaimed and either document the capacity/access blocker or choose a different
unclaimed module row.
Good fallback candidates are the explicit module-backlog rows such as
`kube_kata`/`empty_kata`, but they require new YAML profiles, host prerequisite
documentation, retained VM evidence, and careful scope wording.

## Operational Boundaries

Use only the reviewed host wrappers for retained smoke work:

```bash
sudo -n /usr/local/bin/continuum-hostctl ...
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...
```

Do not use arbitrary `sudo`. Do not commit generated logs, VM artifacts,
credentials, service keys, local `.tmp` files, or machine-specific overrides.

VM-backed suites can consume substantial CPU/RAM/time and mutate retained state.
Do not start them unless the task explicitly calls for that run and host
capacity is available.

## Suggested Commit Grouping

Keep docs/checker-only changes separate from runtime/config/profile/playbook
changes when practical. Runtime-affecting commits after the evidence source
commit must name which VM-backed wrapper scenarios were rerun, or explicitly
state that the affected row remains unclaimed.
