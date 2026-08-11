# Continuum Rework Release Handoff

## Purpose And Authority

This is the live restart point for release-readiness work. It records the
completed runtime-remediation checkpoint and next decision boundary; it does
not duplicate certification rows, finding analysis, or release policy.

Use these authorities:

1. `docs/rework_plan_stack.md` for architecture precedence and locked decisions,
2. `docs/rework_milestone_release_plan.md` for release policy and milestones,
3. `docs/release_certification_matrix.md` for current certification status,
   claim boundaries, evidence, and row actions.

## Current Checkpoint

Start in `/home/matthijs/continuum` on branch `pr-23-curated`. Commit `71d29b7`
is the completed six-packet remediation checkpoint from baseline `41b0418`.
Independent review closed all 15 runtime findings, R-01 through R-15.

The compact fixing-commit map, grouped by the packets actually reviewed, is:

| Packet | Findings and fixing commits |
| --- | --- |
| 1 | R-13 `34bac3c51e31`; R-10 `6494d2a39002` |
| 2 | R-07 and R-12 `e61d16ed01d3`; R-15 `8fa61f096469` |
| 3 | R-11 `aec59588f4da`; R-08 `9f2c9caf3352`; R-01 `030cb5577af5` |
| 4 | R-03 `c14c137a9658`; R-14 `e27df6fcce28`, `58ead34239de` |
| 5 | R-05 `b47d53a7f442`; R-04 `e28ee7984200`; R-02 `ebec74c9bc2a` |
| 6 | R-09 `1a97fc64ffd8`; R-06 `71d29b7b1a53` |

This closure synchronization is docs-only. It does not change runtime behavior,
release evidence, or any certification row status. Inspect the current diff and
worktree rather than relying on a persisted clean/dirty claim here.

## Release Boundary

Claim only exact rows marked `certified`, plus non-runtime core behavior marked
`core-ready`, in `docs/release_certification_matrix.md`. In particular:

1. do not infer support from provider or module code alone,
2. do not broaden a certified row beyond its recorded provider, topology,
   module set, application, runtime targets, or evidence,
3. keep GCP/AWS historical and other unverified surfaces unclaimed until all
   matrix-defined certification prerequisites are satisfied,
4. treat retained `M2-*` research row IDs as evidence identifiers, not as the
   M2 Provider Parity milestone name.

These are certification backlog items, not reopened R-ID implementation
defects; all R-01 through R-15 remain CLOSED.
`docs/release_certification_matrix.md` is the sole authority for the complete
prerequisites and current certification status of scopes that have been
nominated and represented there:

1. AWS and GCP require maintainer-nominated scope, credentials and cost
   guardrails, suitable YAML profiles and suites, and provider-appropriate
   evidence.
2. `text_translation` and `mem_usage` require nominated configurations and
   targets, the matrix-defined success and artifact contracts, and
   provider-appropriate evidence.
3. Live external-owner QEMU cache validation remains uncertified. Its exact
   scope and closure requirements must be nominated and added to the
   certification matrix before making any certification claim.

This closure does not renew or imply certification for any of those surfaces.

## Preserved Runtime Decisions

1. R-01 currently accepts exactly one executable benchmark stage.
2. R-08 assignments are exhaustive authorization envelopes; broad legacy
   inventories remain guarded by the temporary adapter.
3. R-09 `state.json` is persistent last-known and postmortem state. Resume is
   explicit and requires fail-closed reachability validation.

## Current Validation Contract

The August 11 runtime-closure validation recorded 787 unit tests, 112 local E2E
tests, and 899 combined tests, with all required cloud-static gates passing.
The report is
`logs/cloud_static_audit/cloud_static_audit_2026-08-11T133142Z.md`.

That report validates runtime checkpoint `71d29b7`. It does not certify this
later documentation-only diff. Do not start VM-backed suites or infer renewed
runtime evidence for this synchronization.

## Next Decision Boundary

After this closure synchronization, choose the next roadmap or milestone task
using the existing authoritative plans and the release certification matrix.
Do not turn certification backlog items into implementation findings or create
public support claims beyond the matrix.

## Operational Boundaries

Do not use arbitrary `sudo`. Do not commit generated audit reports, runtime
logs, VM artifacts, credentials, service keys, local `.tmp` files, or
machine-specific overrides. Use the reviewed host wrappers only when a future
task explicitly requires retained VM-backed certification work.
