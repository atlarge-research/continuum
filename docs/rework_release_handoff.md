# Continuum Rework Release Handoff

This is a subordinate operational restart point, not policy or certification.
Use `docs/rework_plan_stack.md`, `docs/rework_milestone_release_plan.md` and
`docs/release_certification_matrix.md` for authority, policy and factual rows.

## Current checkpoint — 2026-10-27

Source baseline: clean `2f11e62347ea04aca137a07b540ef3234f080820`,
branch `pr-23-curated`, checkout `/home/matthijs/continuum`.
All fourteen policies and the exceptional baseline action were approved.
The user then amended execution to normal-user `matthijs` on node4 and node3;
preserve evidence and retire the smoke accounts/obsolete installed wrappers
only after replacement verification. Continue the same goal until
2026-10-28 10:00 Europe/Amsterdam (09:00 UTC), without bypassing approval gates.
No merge/push/tag/release/publication is authorized.

Compact original evidence, private old-home material and installed-boundary
snapshots are verified outside Git under
`/mnt/sdc/continuum_migration_evidence/20261027T173000Z-node4`;
node3 evidence is under
`/mnt/sdb/continuum_migration_evidence/20261027T173000Z-node3`.
Large disks were not copied. Only the approved benchmark child was pruned.
Other retained child roots were not emptied.

The one source-unchanged operational baseline as matthijs failed at its first
infrastructure child, result `test_results_2026-10-27_17-41-13.json` under
`infra_one_vm/.continuum/test_results/`. The cache cleanup deleted freshly
copied current-run YAML before cloud-localds. Generated source YAML remains in
tmp; no successful state.json was produced. Full output and failure artifacts
are separately preserved. No targeted retry was performed.
Attribution is unchanged source/config with migrated execution identity and
filesystem metadata, not an unchanged historical runner boundary.

## Resume sequence

1. Complete atomic policy/current-runner synchronization, independent diff
   review and local commit. Use `docs/smoke_runner_isolation.md` for current
   normal-user commands, not installed legacy helpers.
2. Implement the approved narrow indexed/full result-tail interface.
3. Record exact host cache metadata, implement/test/review the minimal QEMU
   cleanup and creation-only mode/ACL fix, and resolve forced-rebuild drift.
4. Run exact multi-host OpenFaaS validation as matthijs. Preserve valid peer
   disk metadata and all evidence. Only then perform a separately reviewed
   exact UID/ACL/account/helper retirement packet.
5. Complete bounded reproduction/config/support inventories; obtain final user
   reproduction-scope confirmation before reproduction-driven deletions.
6. Complete approved slimming and final exact-candidate acceptance.

The failed baseline counts as zero clean operational runs: two clean post-fix
runs remain required, at least one on the exact final candidate. Historical
matrix evidence is not renewed by source tests or identity migration.
Old named/default ACLs and excluded disk UID ownership still need the bounded
retirement audit; do not delete the accounts prematurely or perform blanket
recursive ownership repair.

Historical remediation through `e6aa3a2` remains in Git; it is not the current
runtime acceptance result. Do not resume the retired
`.codex/OVERHAUL_EXECUTION_PLAN.md`. Phase-G and speculative architecture work
are not authorized. Keep generated logs, credentials and private archives out
of commits.
