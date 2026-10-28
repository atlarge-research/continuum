# Continuum Rework Release Handoff

This is a subordinate operational restart point, not policy or certification.
Use `docs/rework_plan_stack.md`, `docs/rework_milestone_release_plan.md` and
`docs/release_certification_matrix.md` for authority, policy and factual rows.

## Current checkpoint — 2026-10-28

Branch `pr-23-curated`, checkout `/home/matthijs/continuum`.
All fourteen policies, the exceptional baseline and the normal-user migration
amendment are approved. Continue the same goal until 2026-10-28 10:00
Europe/Amsterdam (09:00 UTC); midnight does not extend that deadline.
No merge/push/tag/release/publication is authorized.

Policy/current-runner synchronization, indexed/full retained-result inspection
and the minimal host-owned QEMU cache repair were independently reviewed,
validated and committed locally. Runtime verification below used clean
`2baea151783b22b50d6afb22babc349c39019b50`; it is not evidence for a later
final candidate. Use the normal-user procedure and explicit migrated-root/venv
exports in `docs/smoke_runner_isolation.md`, not installed legacy helpers.

The unchanged-source baseline on `2f11e62347ea04aca137a07b540ef3234f080820`
failed at its first infrastructure child, result
`test_results_2026-10-27_17-41-13.json`. Cleanup deleted freshly copied YAML
before cloud-localds; no successful state.json was produced. Evidence is
preserved, and this counts as zero clean operational runs. Attribution was
unchanged source/config with migrated identity/metadata, not an unchanged
historical runner boundary.

The exact multi-host OpenFaaS run completed 1/1 successfully on clean 2baea15:
26 requested vCPUs, node3 external host, no failed/unreachable Ansible host,
four completed endpoint publishers and retained benchmark artifacts.
Result: `test_results_2026-10-27_20-53-27.json` under the OpenFaaS image scenario.
Full stdout/stderr/metadata, state/lock and compact artifacts were inspected
and archived. The run was functional evidence, not a sustained 5-Hz claim:
150 images per endpoint took roughly 87–93 seconds. Actual Kubernetes was
v1.27.16 versus the configured v1.27.0 minor-repository setting; do not claim
an exact patch pin.

The reviewed one-time retirement completed with full verified backups and
16,671 captured commands: both continuum-smoke accounts/private groups are
absent; old active homes, node4 dedicated repo/tmp paths, installed helpers
and old sudoers fragment are removed from active paths. Data/helpers remain
recoverable under root-private
`/var/lib/continuum-retired-20261027-node4` and the node3 counterpart.
Normal matthijs identities, groups and preexisting ALL sudo grants are unchanged.
Exact old-principal metadata/ACL deltas, normal setup/prerequisites/results
access, three Ready Kubernetes nodes and ready OpenFaaS/function containers
passed. All seven workload VMs and eight unrelated shutoff domains were
unchanged. Container-store numeric IDs/copied ACLs remain deliberately
untouched behind the inspected protective ancestors; no global zero-ID claim.

## Archived completed planning records

The completed dispatcher, Phase-C/Phase-D records and frozen implementation
ledger are preserved verbatim at clean source
`b484f120f81c437f29d61b19ff5fec4e3790c58e`. Current files provide archive/current
navigation, not another execution queue. Use `git show <commit>:<path>` to read
the originals. Complete independent copies were byte/hash-verified before edits
under the private migration evidence root, in planning-records-b484f120f81c
(0700 directory, 0600 files). The plan-stack authority prefix and Sections12–14
remain byte-for-byte unchanged.

| Original path at that commit | Lines | Original SHA-256 |
| --- | ---: | --- |
| `.codex/OVERHAUL_EXECUTION_PLAN.md` | 974 | `93600b5823d6c90374cbefddbbc236a3155d6f922801361993b0da5b9e79b362` |
| `docs/phase_c_implementation_plan.md` | 320 | `5104fc6dc44cc3626232acd0929c0157c3488ae7cb0abd4c5204e21e75cd4be2` |
| `docs/phase_d_handoff.md` | 599 | `ae516e9e306838624ce13b187495793a352844c68d3591d11563b7e3116b6ba7` |
| `docs/rework_plan_stack.md` | 248 | `6beb7b1df42b0d8d0f471403ca4f2321a0b0dec5026207e0c00629df104d0b3a` |

Historical commands, counts, failures and source bindings remain recoverable;
they are not rewritten into current certification. Dated release evidence and
candidate research functionality/inputs remain untouched.

## Evidence and remaining work

Private durable evidence is outside Git under
`/mnt/sdc/continuum_migration_evidence/20261027T173000Z-node4`;
original node3 evidence is under
`/mnt/sdb/continuum_migration_evidence/20261027T173000Z-node3`.
The retirement-prepared/applied directories include exact manifests, private
backups and command captures; the mutation journal is separately durable.
Large retained disks were not copied. No recursive old-home deletion occurred,
and the retirement packet performed no VM operation or benchmark rerun.

1. Complete the bounded reproduction/configuration/support reviews.
   `docs/reproduction_inventory.md` records the complete candidate survey and
   remaining historical associations; obtain one final scope confirmation
   before reproduction-driven deletions. `docs/configuration_inventory.md`
   accounts for 310 inputs and 47 fixture/support/metadata sources; its preserved
   refreshed per-file evidence is bound to clean
   e3af54dc2642ab50ce9e47365976108bdf2ff2ee, with the earlier b22cadc snapshot
   preserved unchanged. Final historical dispositions, required equivalents and
   fresh runtime acceptance remain open; recheck affected rows and exact binding
   after later schema/example/test changes.
2. The approved registry_refresh missing/all hard cut replaces image_prefetch
   without aliases; historical locks/evidence are not renewed. The bounded cache
   repair covers baked recipe inputs and actual preload identities, with limits
   in `docs/qemu_cache_contract.md`; it does not renew runtime evidence. Validate the narrow
   same-revision QEMU resume contract. Sweeps remain candidate-only.
3. The temporary diagnostic replay command/playbook and their dedicated tests
   are removed; narrow result interfaces and direct operator diagnostics remain.
   Complete the remaining branch-wide slimming audit without deleting required
   provenance or weakening freshness checks.
   `docs/branch_slimming_audit.md` maps the major additions and checker rationale;
   historical runtime-source waivers and duplicate pretag command-policy checks
   are removed. Completed-ledger provenance consolidation is preserved above;
   active navigation replaces the superseded execution queues.
4. Create a clean final candidate and complete static/runtime/manual acceptance:
   two clean post-fix operational runs, at least one on that exact candidate;
   exact final-candidate multi-host OpenFaaS and every approved reproduction;
   bounded support matrix and zero unaccounted inventory rows.
5. Present the final package and await explicit publication approval.

Historical matrix evidence is not renewed by source tests or migration.
Do not resume the retired overhaul dispatcher or speculative Phase-G work.
Keep generated logs, credentials, private archives and images out of commits.
