# Continuum Rework Release Handoff

## Purpose And Authority

This is the live operational restart point for release-readiness work. It
records the completed runtime-remediation checkpoint and the next decision
boundary; it does not define policy or duplicate certification rows, finding
reports, or release evidence.

Use these authorities:

1. `docs/rework_plan_stack.md` for planning precedence and locked decisions,
2. `docs/rework_milestone_release_plan.md` for the active release-readiness
   phase and release policy,
3. `docs/release_certification_matrix.md` as the sole authority for current
   certification status, claim boundaries, evidence, and row actions.

Use the commit history and those governing documents for detail beyond this
compact restart checkpoint.

## Current Checkpoint

Start in `/home/matthijs/continuum` on branch `pr-23-curated`. Commit
`e6aa3a2df043cacbe8b58e5f70a536e859ff8dfe` (`e6aa3a2`) is the completed
final runtime-remediation checkpoint.

The checkpoint advances from the N-02 endpoint and records two remediation
ranges:

1. N-02 endpoint:
   `1c8042376ae9f7f53ce7c24dda60a2f2a108de31`.
2. First final-review remediation range, exactly six linear commits:
   `1c8042376ae9f7f53ce7c24dda60a2f2a108de31..7f322c96a0545f866dc5efda183930701463c5d5`.
3. Closure-review follow-up range, exactly seven linear commits:
   `7f322c96a0545f866dc5efda183930701463c5d5..e6aa3a2df043cacbe8b58e5f70a536e859ff8dfe`.
4. Complete post-N-02 remediation range, exactly 13 linear commits:
   `1c8042376ae9f7f53ce7c24dda60a2f2a108de31..e6aa3a2df043cacbe8b58e5f70a536e859ff8dfe`.

The original six branch-wide findings and the subsequent closure-review
findings have been addressed in those ranges. This statement records the
implementation checkpoint; it does not claim renewed runtime validation or a
new review verdict.

The earlier six-packet closure of R-01 through R-15 at `71d29b7b1a53`, from
baseline `41b0418`, remains closed historical context. It is not the current
checkpoint and is not reopened by the later remediation work. Consult commit
history for the detailed finding-to-commit maps rather than extending this
handoff into a cumulative changelog.

## Resulting Runtime Invariants

The post-N-02 remediation ranges establish these implementation boundaries:

1. benchmark execution authorization fails closed,
2. image requirements, caches, and runtime launches preserve immutable image
   identity,
3. network validation requires current-run, complete, attributable, structured
   evidence,
4. phase dependencies and numeric validity are enforced parser-first,
5. zero-work text-translation configurations are rejected,
6. resume support is limited to the provider path validated by the
   implementation: QEMU.

## Certification And Evidence Boundary

This documentation synchronization changes no certification row, evidence
claim, or release status. Do not promote or demote any matrix row because of
the remediation checkpoint. `docs/release_certification_matrix.md` remains the
sole certification authority.

Existing retained VM-backed evidence predates the later runtime-affecting
changes in the remediation ranges. As already required by the certification
matrix and milestone release plan, affected evidence must be refreshed on the
exact, clean publication candidate before tagging. Static, unit, and
documentation checks do not renew VM, Kubernetes, application, network,
provider, or cloud certification.

## Next Decision Boundary

1. After this synchronization is committed and the tree is clean, decide
   whether to begin the M1 evidence refresh on that exact revision as the
   publication candidate. Any evidence used for publication must name and run
   against the exact clean publication candidate.
2. Do not select or update work from the retired
   `.codex/OVERHAUL_EXECUTION_PLAN.md`; `.codex/NEXT_AGENT.md` remains the
   pointer away from that completed historical dispatcher.
3. Defer Phase-G architecture work until a separate RFC/ADR and an explicit
   scope decision authorize it.

## Operational Boundaries

Do not start certification-host or VM-backed work from this documentation
synchronization. Do not commit generated audit reports, runtime logs, VM
artifacts, credentials, service keys, local `.tmp` files, or machine-specific
overrides.
