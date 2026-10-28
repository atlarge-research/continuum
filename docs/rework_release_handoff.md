# Continuum Rework Release Handoff

This is a subordinate operational restart point, not policy or certification.
Use `docs/rework_plan_stack.md`, `docs/rework_milestone_release_plan.md` and
`docs/release_certification_matrix.md` for authority, policy and factual rows.

## Current checkpoint — 2026-10-28

Branch `pr-23-curated`, checkout `/home/matthijs/continuum`.
All fourteen policies, the exceptional baseline and the normal-user migration
amendment are approved. The prior execution window ended on 2026-10-28 at
10:00 Europe/Amsterdam (09:00 UTC); it is not silently renewed.
No merge/push/tag/release/publication is authorized.

The approved continuation is
`docs/superpowers/plans/2026-10-28-local-module-closure.md`, a subordinate,
outcome-bounded execution plan. It targets a review-ready core and the selected
local-QEMU modules, not completion of every historical reproduction or a
merge-ready release. Start one new coordinator task, with fresh-context
implementation agents and independent read-only reviewers. Keep one checkout
writer and one physical-host workflow at a time. Additional-node concurrency
has only been discussed; it is not enabled or authorized by that discussion.

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
passed. At retirement, all seven workload VMs and eight unrelated shutoff domains were
unchanged. Container-store numeric IDs/copied ACLs remain deliberately
untouched behind the inspected protective ancestors; no global zero-ID claim.

The later clean `6bc0d86145890917680811ea9cbfeb85ef8bd5e2` candidate completed
two manually inspected functional operational runs. Cross-guest one-way timing
was invalid in those runs; finite endpoint RTT, processing and image completion
do not certify synchronized one-way delay. Evidence remains under
final-candidate-6bc0d86 in the private evidence root below.

Its separate changed-parameter sweep completed 30 images once, but the repeat
sent 60 and received none: the old completed Kubernetes Job was reused without
a new subscriber. The repeat was safely stopped and assessed accepted:false;
sweeps remain candidate-only, not supported. Strict Columbo then failed before
the benchmark because the readiness classifier rejected the actual instrumented
return trace. The reviewed narrow correction is committed at
`fb2e8f8810784507ae42d226d89ede8bf10ce8eb`. It accepts only that full return form,
not arbitrary stderr, and requires a new clean candidate and complete runtime
sequence reset. Neither older operational pass counts for that new candidate.

## Continuation restart point and carried changes

The pre-bootstrap committed checkpoint is
`cca9feecd01b99cd7b40b12624532498051a12b4`. At bootstrap, exactly two carried
source files are modified: `roles/resource_manager/docker_setup/tasks/main.yml`
and `scripts/test/unit/test_role_contracts.py`. They add a bounded retry only
for the observed complete apt frontend-lock error from unattended-upgr, plus
inert actual-Ansible regression tests. These edits are not part of the
documentation bootstrap commit. Packet A preserved these source bytes, independently
reviewed the complete diff and committed them locally at
`1d0e9de1750f3378b5134e51462111246da6fbf8`. They have not received VM-backed
validation. Do not recreate the account migration, rerun retired executors or
start a third unchanged cca9fee retry.

Two operational attempts on clean cca9fee, including its single fresh unchanged
retry, failed during benchmark software installation with apt rc100. The
benchmark application did not execute. Each produced four result summaries with
five execution entries: four passed, one failed. Neither is an operational pass.
Both complete failures and their accepted:false assessments are preserved under
final-candidate-cca9fee/operational-1 and operational-1-retry in the private
durable evidence root below. Local compact snapshots contain 427 and 452 files,
respectively; no guest updater was killed, lock deleted or privilege widened.

The latest pre-bootstrap static report is
`logs/cloud_static_audit/cloud_static_audit_2026-10-28T064756Z.md`: all twelve
required gates passed, with 934 unit and 171 local-e2e tests, 1,105 combined.
It includes the carried dirty Docker/test changes; it is not a clean committed
candidate or fresh runtime certification. The five focused Docker-role tests
and all 38 role tests passed on the pinned runtime, relevant cache tests and
changed-file lint passed, and the complete two-file change received an
independent read-only review. Repeat applicable verification before committing.
Retain Python 3.8.10/Ansible 2.13.2 physical-runner attribution and the separately
attributed Python 3.12.7 static environment; do not silently upgrade either.

Fresh packet-A source checks passed: five focused Docker tests and all 38 role
tests on Python 3.8.10/Ansible 2.13.2; 79 relevant QEMU cache tests on the separately
attributed Python 3.12.7 static environment; YAML/Ansible lint and scoped Python
lint. Unfiltered Python lint retains convention-only findings, including three
new test-method docstring findings; no unrelated style rewrite was made. The
cache test module uses newer syntax and cannot run under Python 3.8. An additional
temporary-fixture check using the actual old/new Docker-role bytes confirmed
recipe-fingerprint invalidation with unchanged image bytes, without manual disk
deletion. None of these source checks proves a VM-backed rebuild or runtime pass.

The new v6 configuration inventory is bound to clean 1d0e9de. It refreshes the
role-test carrier row and Docker-role hashed exclusion, verifies all source hashes
and preserves v2/v3/v4/v5 unchanged; see `docs/configuration_inventory.md`.
The next packet-A gate is one clean operational_regression development run as
matthijs with the migrated root and pinned venv, after the documentation review
and commit. Require four new child JSONs and six successful executions (three
smoke singletons plus three benchmark entries), zero exit codes/timeouts and no
failed or unreachable Ansible hosts. Preserve and inspect complete artifacts,
state/locks and unrelated domains. This development run is not final-candidate
acceptance; diagnose any failure before retrying. The later application
reuse defect, module closure, interface polish and frozen-candidate acceptance
follow the approved continuation plan. Historical scope and final dispositions
remain open; do not mark the original pre-main goal complete at this checkpoint.

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
   1d0e9de1750f3378b5134e51462111246da6fbf8, after the reviewed Docker-install
   repair; all four earlier snapshots remain unchanged. Final historical
   dispositions, required equivalents and
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
   two new clean post-fix operational runs on that exact candidate;
   exact final-candidate multi-host OpenFaaS and every approved reproduction;
   bounded support matrix and zero unaccounted inventory rows.
5. Present the final package and await explicit publication approval.

Historical matrix evidence is not renewed by source tests or migration.
Do not resume the retired overhaul dispatcher or speculative Phase-G work.
Keep generated logs, credentials, private archives and images out of commits.
