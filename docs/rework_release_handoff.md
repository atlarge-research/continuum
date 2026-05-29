# Continuum Rework Release Handoff

## Purpose

This file is the restart point for the paused release-readiness goal. It records
the current execution state so a future agent can resume without reconstructing
the goal from chat history.

Policy authority remains in `docs/rework_milestone_release_plan.md` and
`docs/release_certification_matrix.md`. This document is a checkpoint and
handoff only.

## Active Goal

Prepare the reworked Continuum branch for an intermediate M1 milestone release,
then continue toward a final replacement release only after old-main parity is
certified or explicitly deprecated.

The release direction is:

1. keep Continuum core limited to structured planning, validation, selector and
   scope resolution, module contracts, runtime handoff, state, and evidence
   contracts,
2. treat providers, resource managers, addons, execution helpers, and
   applications as modules or module families,
3. describe `qemu` as an infrastructure provider module, not Continuum core,
4. publish M1 only as an intermediate milestone or pre-release,
5. claim only rows marked `core-ready` or `certified` in
   `docs/release_certification_matrix.md`,
6. require fresh VM-backed or cloud-backed evidence before any runtime support
   claim is broadened,
7. keep the final `main` replacement blocked until old public functionality is
   certified or intentionally deprecated with migration guidance.

## Current Checkpoint

The branch contains the M1 release plan, certification matrix, release-note
draft, release evidence docs, old-main parity issue seed, post-release roadmap,
release-claim checkers, release-matrix drift checks, release-evidence artifact
checks, and M1 pre-tag checks.

The current M1 cloud-safe evidence table points to:

`/home/matthijs/continuum/logs/cloud_static_audit/cloud_static_audit_2026-05-29T183813Z.md`

That audit recorded:

1. required cloud-safe gates: PASS,
2. unit unittest discovery: 601 tests OK,
3. e2e unittest discovery: 76 tests OK,
4. combined unittest discovery: 677 tests OK,
5. pytest mirror: 677 passed,
6. release claim issues: 0,
7. release matrix issues: 0,
8. docs path missing references: 0,
9. release evidence artifact issues: 0,
10. pre-tag issues: 15 expected blockers.

No VM-backed tests were run during the final checkpoint-wrap work.

Post-checkpoint host-runner state:

1. live worktree state after this handoff update: clean,
2. dedicated runner repo: resynced from `/home/matthijs/continuum` with
   `sudo -n /usr/local/bin/continuum-hostctl sync-repo`,
3. installed wrapper: refreshed with
   `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`,
4. `sudo -n /usr/local/bin/continuum-hostctl verify`: PASS,
5. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke
   check-prereqs`: PASS,
6. `sh scripts/test/setup_agent_host.sh verify`: FAIL because the installed
   `/usr/local/bin/continuum-hostctl` does not declare
   `HOSTCTL_INTERFACE_VERSION`.

The dedicated runner is therefore no longer blocked by repo drift. M1 tagging
is still blocked until the root-owned maintenance helper is refreshed and all
claimed VM-backed evidence is regenerated from the exact clean commit being
tagged. Re-run `sudo -n /usr/local/bin/continuum-hostctl show-config` after any
new commit to confirm that `LIVE_HEAD` and the dedicated sync marker refer to
the tree intended for VM-backed evidence.

## Current Certified Scope

The certified or core-ready scope is exactly the set named in
`docs/release_certification_matrix.md` and summarized in
`docs/release_notes_m1_draft.md`:

1. M1 cloud-safe core checks,
2. local QEMU/libvirt M1 smoke rows,
3. the M1 network-validation row,
4. the resumed Kubernetes image-classification benchmark smoke row,
5. QEMU old-main infrastructure-only parity rows `P-QEMU-01` through
   `P-QEMU-04`,
6. QEMU Kubernetes no-benchmark row `P-QEMU-09`,
7. software-only subset rows `P-QEMU-06-SW`, `P-QEMU-07-SW`,
   `P-QEMU-08-SW`, and `P-QEMU-10-SW-LOCAL`.

Do not claim full old-main parity, cloud-provider support, full QEMU
application parity, or full KubeEdge/Mist/OpenFaaS application parity from this
checkpoint.

## Known Blockers

`python3 scripts/test/check_release_pretag.py` currently reports 15 expected
blockers after the checkpoint commit:

1. `pretag-host-helper-not-ready`: M1 evidence still records
   `Verify result='FAIL before VM execution'` where pre-tag readiness expects
   `PASS`.
2. seven `pretag-source-commit-mismatch` findings because all listed release
   evidence docs still name the previous evidence commit
   `653ae7b3c7481c46cb26ca8676ac8fbfa94f7d22`, not the current checkpoint
   commit.
3. seven `pretag-evidence-tree-not-clean` findings because all listed release
   evidence docs record dirty-tree evidence.

These are not accidental regressions. Clearing them requires a clean source
tree, refreshed host-helper verification, fresh VM-backed evidence from the
exact source tree being tagged, and rerunning the pre-tag checker until it
reports zero issues.

## Next Agent Checklist

1. Review the latest worktree with `git status --short` and `git log --oneline
   -5`.
2. Run the cloud-safe checks before making release claims:
   - `python3 scripts/test/check_release_claims.py`
   - `python3 scripts/test/check_release_matrix.py`
   - `python3 scripts/test/check_docs_paths.py`
   - `python3 scripts/test/check_release_evidence_artifacts.py`
   - `python3 scripts/test/check_release_pretag.py`
3. If source changed, run `scripts/test/run_cloud_static_audit.sh` and update
   `docs/release_evidence_m1_2026-05-23.md` with the new report path and
   counts.
4. Keep generated `logs/cloud_static_audit/*.md` files uncommitted unless a
   maintainer explicitly asks for a dated audit snapshot.
5. Before tagging M1 on the certification host, refresh the installed host
   helper and run the pre-tag command sequence in
   `docs/release_notes_m1_draft.md`.
6. Rerun affected VM-backed rows after any runtime, runner, verifier, profile,
   or playbook changes.
7. Only after `check_release_pretag.py` reports zero issues should M1 be tagged
   or published.

## Suggested Commit Grouping

The current branch is suitable for one checkpoint commit if time is short. If
splitting is practical, use these groups:

1. release planning and certification guardrails,
2. parity suites and host-runner support,
3. QEMU parity module execution support.

Each commit message should include the cloud-safe commands run, whether
VM-backed tests were skipped, and the remaining pre-tag blockers.
