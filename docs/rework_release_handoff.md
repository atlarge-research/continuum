# Continuum Rework Release Handoff

## Purpose And Authority

This is the live restart point for release-readiness work. It records only the
current repository checkpoint and next decision boundary; it does not duplicate
certification rows or release policy.

Use these authorities:

1. `docs/rework_plan_stack.md` for architecture precedence and locked decisions,
2. `docs/rework_milestone_release_plan.md` for release policy and milestones,
3. `docs/release_certification_matrix.md` for current certification status,
   claim boundaries, evidence, and row actions.

## Current Checkpoint

Start in `/home/matthijs/continuum` on branch `pr-23-curated`. The source
checkpoint before the documentation-authority reset is:

```text
c2f089b3fe625a626d1be1b0c5d847f93e590ec5 document remaining parity backlog
```

The authority reset is docs-only. It does not change runtime code, configs,
profiles, playbooks, roles, runner behavior, or any certification row status.
Inspect `git status --short` and the current diff rather than relying on a
persisted clean/dirty claim in this file.

The completed `.codex/OVERHAUL_EXECUTION_PLAN.md` task graph is historical. All
of its tasks are done, so its old certification statements, blockers, and
next-agent scheduling prompts are not current state.

## Release Boundary

Claim only exact rows marked `certified`, plus non-runtime core behavior marked
`core-ready`, in `docs/release_certification_matrix.md`. In particular:

1. do not infer support from provider or module code alone,
2. do not broaden a certified row beyond its recorded provider, topology,
   module set, application, runtime targets, or evidence,
3. keep GCP/AWS historical and other unverified surfaces unclaimed until a
   maintainer nominates a concrete target and provider-appropriate runtime
   evidence exists,
4. treat retained `M2-*` research row IDs as evidence identifiers, not as the
   M2 Provider Parity milestone name.

## Current Validation Contract

The documentation-authority reset was validated with
`logs/cloud_static_audit/cloud_static_audit_2026-08-05T152606Z.md`; all required
gates passed. The release-matrix, public-claims, and docs-path checks report zero
issues. Before commit, the pre-tag checker reports only the expected dirty-tree
finding.

For a docs-only release update, run:

```bash
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_docs_paths.py
python3 scripts/test/check_release_pretag.py
git diff --check
```

Run `scripts/test/run_cloud_static_audit.sh` for the cloud-safe release gate.
It writes an ignored report under `logs/cloud_static_audit/`; inspect the newest
report and keep the M1 evidence pointer synchronized with it. An uncommitted
docs patch may leave only the expected dirty-worktree pre-tag finding. Before a
tag, the committed tree must produce zero pre-tag issues and the certification
host must pass the retained artifact audit.

Do not start VM-backed suites for docs-only work. If runtime, runner, verifier,
profile, playbook, or config code changes, refresh every affected row through
its documented host wrapper before preserving the claim.

## Next Decision Boundary

The remaining parity backlog is already documented in
`docs/old_main_parity_issue_seed.md`. Historical rows are unresolved and remain
there under the current checked contract. The next milestone is target
nomination, not another inventory pass:

1. nominate an exact GCP, AWS, bare-metal, or uncertified application target,
   including credentials/capacity, cost guardrails, YAML/profile scope, suite,
   success criteria, and evidence requirements.

If maintainers choose to close an unsupported historical provider without
certification, handle that later as a separate atomic change introducing an
explicit checked terminal disposition and updating the matrix checker,
certification matrix, and parity seed together. Do not treat `historical` as
that terminal disposition.

Until a target is nominated, keep this work docs-only and do not create public
support claims.

## Operational Boundaries

Do not use arbitrary `sudo`. Do not commit generated audit reports, runtime
logs, VM artifacts, credentials, service keys, local `.tmp` files, or
machine-specific overrides. Use the reviewed host wrappers only when a future
task explicitly requires retained VM-backed certification work.
