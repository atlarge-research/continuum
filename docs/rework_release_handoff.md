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

Release evidence refresh checkpoint:

```text
58802ab refresh release evidence for exact openfaas parity
```

VM-backed evidence source checkpoint:

```text
f9ab421 fix qemu image permissions for external host
```

After the July 8 release-documentation refresh, the worktree was clean and
these gates passed:

1. `python3 scripts/test/check_release_pretag.py`
   - `TOTAL_RELEASE_PRETAG_ISSUES=0`
2. `python3 scripts/test/check_release_matrix.py`
   - `TOTAL_RELEASE_MATRIX_ISSUES=0`
3. `python3 scripts/test/check_release_claims.py`
   - `TOTAL_RELEASE_CLAIM_ISSUES=0`
4. `python3 scripts/test/check_docs_paths.py`
   - `TOTAL_MISSING_REFERENCES=0`
5. `python3 -m unittest scripts.test.unit.test_check_release_pretag scripts.test.unit.test_check_release_evidence_artifacts`
   - rerun after the July 8 evidence refresh before tagging
6. `git diff --check`
   - clean
7. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
   - synced `/home/matthijs/continuum` to `/srv/continuum/repo`
8. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit`
   - `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0`

The current M1 evidence snapshot is:

```text
docs/release_evidence_m1_2026-07-08.md
```

It records VM-backed evidence from source commit
`f9ab4217c40604dc145692664667a13e8cc2a994` and the latest cloud-safe audit
report:

```text
logs/cloud_static_audit/cloud_static_audit_2026-07-08T211159Z.md
```

That audit recorded required gates passing, 644 unit unittest tests, 100 local
e2e unittest tests, 744 combined unittest tests, and a 744-test pytest mirror.
Generated `logs/cloud_static_audit/*.md` reports stay uncommitted unless a
maintainer explicitly asks for a dated audit snapshot.

The July 8 refresh reran the M1 and old-main QEMU certified wrapper scenarios
on source commit `f9ab4217c40604dc145692664667a13e8cc2a994` after fixing
remote QEMU image permissions for the external host. The exact parent
`qemu_openfaas_image_parity` suite passed on local plus `continuum-smoke@node3`
external QEMU capacity.

## Certified Scope

Claim only what is marked `core-ready` or `certified` in
`docs/release_certification_matrix.md`.

Current certified/core-ready highlights:

1. M1 cloud-safe core checks and local QEMU/libvirt vertical slices.
2. QEMU old-main rows `P-QEMU-01` through `P-QEMU-10`.
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

## Exact OpenFaaS Parent Row

The exact QEMU OpenFaaS parent row is now certified:

```text
P-QEMU-10
```

It corresponds to:

```text
configuration/tests/qemu/10_kubernetes-openfaas.cfg
configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml
suite qemu_openfaas_image_parity
```

The retained clean-source run is:

```text
/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/test_results/test_results_2026-07-08_16-34-03.json
```

Benchmark metric manifest:

```text
/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/logs/benchmark/2026-07-08_16_13_25_classify-images_metrics_manifest.json
```

`P-QEMU-10-SW-LOCAL` and `P-QEMU-10-APP-LOCAL` remain certified only as local
single-host, CPU-capped subset rows. Keep them scoped that way when discussing
single-host runner behavior.

## Next Recommended Slice

First fix any new release gate, docs, or checker issue that appears in the
current tree. If the tree is still clean and release gates pass, the next work
is non-QEMU/historical parity disposition or module-backlog certification; do
not rework the already certified Columbo trace or exact OpenFaaS row unless a
new requirement appears.

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

Then inspect the updated release boundary:

```bash
sed -n '130,145p' docs/release_certification_matrix.md
sed -n '150,175p' docs/release_certification_matrix.md
sed -n '280,325p' docs/smoke_runner_isolation.md
```

Before any VM-backed run, verify the dedicated host wrapper and cache state:

```bash
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_openfaas_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke \
  prime-registry-cache --check-only --suite qemu_openfaas_image_parity
```

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
