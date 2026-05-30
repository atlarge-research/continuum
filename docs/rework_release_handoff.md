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

`/home/matthijs/continuum/logs/cloud_static_audit/cloud_static_audit_2026-05-29T202812Z.md`

That audit recorded:

1. required cloud-safe gates: PASS,
2. unit unittest discovery: 603 tests OK,
3. e2e unittest discovery: 76 tests OK,
4. combined unittest discovery: 679 tests OK,
5. pytest mirror: 679 passed,
6. release claim issues: 0,
7. release matrix issues: 0,
8. docs path missing references: 0,
9. release evidence artifact issues: 0,
10. pre-tag issues: 0.

Post-checkpoint host-runner and VM-evidence state:

1. VM evidence source commit: `67f49fa4f7af3b4f54912dabc8993ac923c8abdd`,
2. dedicated runner repo: resynced from `/home/matthijs/continuum` with
   `sudo -n /usr/local/bin/continuum-hostctl sync-repo`,
3. installed wrapper: refreshed with
   `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`,
4. `sudo -n /usr/local/bin/continuum-hostctl verify`: PASS,
5. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke
   check-prereqs`: PASS.

The dedicated runner is no longer blocked by repo drift or helper-interface
drift, and all currently claimed VM-backed wrapper scenarios listed in
`docs/release_notes_m1_draft.md` passed on 2026-05-29 from the clean evidence
source commit. `python3 scripts/test/check_release_pretag.py` reports zero
issues on the current docs/checker-only release head. Re-run
`sudo -n /usr/local/bin/continuum-hostctl show-config` and
`sudo -n /usr/local/bin/continuum-hostctl verify` after any new runtime commit
to confirm that `LIVE_HEAD` and the dedicated sync marker refer to the runtime
tree intended for VM-backed evidence.

The previous sandbox problems are resolved for the current session:

1. Git staging and committing work.
2. `sudo -n /usr/local/bin/continuum-hostctl verify` passes.
3. Agent sudo policy is documented in `docs/agent_sudo_boundaries.md`.

Generic sudo may still differ between the operator shell and an agent sandbox.
Do not broaden sudoers to compensate; use the root-owned wrapper pattern in
`docs/agent_sudo_boundaries.md`.

Post-M1 parity progress after this checkpoint:

1. The host-side local registry cache was primed for
   `qemu_kubeedge_image_parity` and `qemu_mist_image_parity` with
   `sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite ...`.
2. Direct registry probes from the agent sandbox cannot reach
   `192.168.1.104:5000`, so use the host helper result as the authoritative
   cache-readiness signal.
3. Multiple full `qemu_kubeedge_image_parity` wrapper runs were attempted. The
   earlier retained evidence source commit
   `67f49fa4f7af3b4f54912dabc8993ac923c8abdd` exposed the edge flannel
   `CrashLoopBackOff`; follow-up code now injects an explicit flannel
   kubeconfig and aligns KubeEdge/containerd runtime setup.
4. The latest post-fix wrapper attempt reached infrastructure, software, and
   the application phase with KubeEdge joined and flannel past the previous
   `CrashLoopBackOff`.
5. The latest run then failed under host disk pressure while endpoint Docker
   was pulling the image-classification publisher image. The runner also failed
   to save its JSON summary with `OSError: [Errno 28] No space left on device`.
6. Latest retained log:
   `/home/continuum-smoke/continuum_smoke/qemu_kubeedge_image_parity/.continuum/logs/2026-05-29_23:56:00_edge_kubeedge_classify-images.log`.
7. Current host storage evidence from the 2026-05-30 resume shows the installed
   smoke wrapper already points at `/mnt/sdc/continuum_smoke`, but the old
   retained root `/home/continuum-smoke/continuum_smoke` is still a real
   directory on `/` and still holds about 74G of retained state. `/` is still
   98% full while `/mnt/sdc` has about 2.1T free. Do not rerun full VM-backed
   application evidence until this is fixed.
8. The intended fix is to refresh the root-owned maintenance helper, then run:
   `sudo -n /usr/local/bin/continuum-hostctl relocate-smoke-root
   /mnt/sdc/continuum_smoke --replace-source-with-symlink`, followed by
   `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated
   /mnt/sdc/continuum_smoke` and `sudo -n /usr/local/bin/continuum-hostctl
   verify`. After this, `/home/continuum-smoke/continuum_smoke` should be a
   symlink to `/mnt/sdc/continuum_smoke`.
9. In the current agent session, every `sudo -n ...` command fails before
   sudoers evaluation because `/` is mounted `ro,nosuid,nodev`; `stat` reports
   `/usr/bin/sudo` as mode `4755`, but owned by `nobody:nogroup` inside the
   agent namespace. Treat this as an execution-environment blocker, not as a
   Continuum helper or sudoers-design failure. See
   `docs/agent_sudo_boundaries.md` for the diagnostic path.

`P-QEMU-06` remains unclaimed. The next useful action is to relocate/prune
retained smoke state, rerun `qemu_kubeedge_image_parity`, and then inspect any
remaining application-phase failure with the retained debug wrapper.

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

There are no current M1 pre-tag checker blockers on the committed
docs/checker-only release head. Runtime, config, profile, playbook, wrapper, or
runner changes after the evidence source commit require rerunning affected
VM-backed scenarios and refreshing the evidence documents.

Remaining blockers for a final replacement release are the non-certified
old-main parity rows in `docs/release_certification_matrix.md`, especially full
QEMU application parity, cloud-provider rows, bare-metal scope, and unverified
software/application modules.

For the next old-main parity step, start with the `P-QEMU-06` edge flannel
failure recorded above before rerunning the full application suite.

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
   `docs/release_evidence_m1_2026-05-29.md` with the new report path and
   counts.
4. Keep generated `logs/cloud_static_audit/*.md` files uncommitted unless a
   maintainer explicitly asks for a dated audit snapshot.
5. Before tagging M1 on the certification host, verify the installed host
   helper and run the pre-tag command sequence in
   `docs/release_notes_m1_draft.md`.
6. Rerun affected VM-backed rows after any runtime, runner, verifier, profile,
   or playbook changes.
7. Only after `check_release_pretag.py` reports zero issues should M1 be tagged
   or published.

## Suggested Commit Grouping

For future release-readiness commits, keep docs/checker-only changes separate
from runtime/config/profile/playbook changes when practical. Runtime-affecting
commits after the evidence source commit must name which VM-backed wrapper
scenarios were rerun, or explicitly state that the row remains unclaimed.
