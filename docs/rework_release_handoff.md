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
writer. The bounded node4/node5 setup and cold/warm isolation pilot is explicitly
approved under the linked amendment below. Its two cold and two warm runs passed
independent evidence review and coordinator adjudication. Only that fixed
two-singleton-host development allocation is enabled, with one workflow per host
and fresh per-task guards. Final acceptance and OpenFaaS workflows remain serial.

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

## Packet A closure and continuation restart point

The pre-bootstrap committed checkpoint is
`cca9feecd01b99cd7b40b12624532498051a12b4`. At bootstrap, exactly two carried
source files are modified: `roles/resource_manager/docker_setup/tasks/main.yml`
and `scripts/test/unit/test_role_contracts.py`. They add a bounded retry only
for the observed complete apt frontend-lock error from unattended-upgr, plus
inert actual-Ansible regression tests. These edits are not part of the
documentation bootstrap commit. Packet A preserved these source bytes, independently
reviewed the complete diff and committed them locally at
`1d0e9de1750f3378b5134e51462111246da6fbf8`. The development run below supplies
their first post-fix VM-backed evidence. Do not recreate the account migration,
rerun retired executors or
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
independent read-only review. Fresh committed-source checks are recorded below.
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
Packet A's operational_regression development gate passed on clean
`333e5afb0aaf36cd62f5a1e84aad448d1d23cadd`, as matthijs with migrated root and
Python 3.8.10/Ansible 2.13.2. Four new child JSONs contain six successful executions:
three smoke singletons and all three benchmark phases. All exit codes were zero,
with no timeouts and no failed/unreachable hosts across 12 Ansible recaps/14 host
rows. The benchmark sent, processed and returned 30 images, saved application
state and completed teardown. Full stdout/stderr/metadata, state/locks, network
records and metric artifacts were manually inspected and independently reviewed.
Evidence is under `development-packet-a-333e5afb0aaf` in the private durable root
below; `accepted-development-manual.json` binds the results and limitations.
Its benchmark JSON is `test_results_2026-10-28_12-47-40.json`; `finished.json`
lists all four. The 66 older JSONs, both cca9fee failure packets and eight
unrelated shutoff domains' inactive XMLs remain unchanged. Compact snapshots
contain 812 local and nine remote files; disks/private keys are excluded.

Docker installation succeeded without an observed lock retry; retry behavior is
covered by inert actual-Ansible tests. Source-driven cache invalidation was proved
in a temporary fixture, not a physical rebuild. The publisher's measured span was
30.31 seconds; the full application phase took 184.2 seconds. Printed one-way
delay lacks synchronization validation. Finite RTT,
processing and image completion do not certify one-way timing. This is functional
development evidence, not final-candidate acceptance or an exact Kubernetes patch
pin. No failed state was pruned and no updater/lock was killed or removed.

Packet B's sequential 1 → 2 → 2 development proof and packet C's later static
core-contract closure are recorded below. Historical
scope, final dispositions and frozen-candidate acceptance remain open; the original
pre-main goal is not complete. Packet D foundation/Kubernetes/endpoint/observability
is next, subject to coordinator release. The independently accepted pilot enables
only its fixed node4/node5 development allocation below; it does not replace final
serial acceptance.

## Packet B — sequential development proof

The bounded Kubernetes image-classification Job-reuse repair is independently
reviewed and committed locally at
`aa7a438ee914cc60a0902ec1908be9c57b89982f`. It labels benchmark-owned Jobs/pods,
archives terminal owned resources and individual logs before exact-name replacement,
and waits for fresh Running subscribers. Readiness, completion and log queries use
the current execution selector; individual command failures propagate. Unrelated
or unlabeled same-name Jobs and active owned Jobs fail closed. Traced/short-lived
benchmark and other orchestrator paths retain their existing behavior.

The demonstrated regression failed on the original source with an unchanged
completed Job UID, then passed with the repair. All 14 new lifecycle tests and
nine launch tests passed on pinned Python 3.8.10/Ansible 2.13.2, including an inert
actual-role test of ownership labels and exact-file application despite a stale
manifest. The complete combined static suite passed 1,120 tests on separately
attributed Python 3.12.7. YAML/Ansible lint passed; Python lint adds no findings
relative to the inspected baseline. The older static pylint/astroid combination
cannot inspect Python 3.12 typealias nodes; that tool failure is not a passing
lint claim. The physical evidence below is separately attributed.

New configuration inventory v7 is bound to clean
`4b1878e28cd07a44b4ad8f267c3a69506f3214b3`, which contains this unchanged repair.
It accounts for 358 rows, including the new test carrier, and verifies every
source hash; all v2–v6 evidence remains unchanged. See
`docs/configuration_inventory.md`.

The reviewed five-invocation serial proof passed on clean
`a6846eb82d183e5e1f044a7deae470d4df6ce380`, as matthijs using pinned Python
3.8.10/Ansible 2.13.2 and one unchanged base,
`/mnt/sdc/continuum_smoke/packet_b_sequential_a6846eb82d18_attempt2`.
Infrastructure and software were followed by three 30-second application runs:

| Frequency | Images sent / processed / returned | Fresh Job UID |
| --- | --- | --- |
| 1 Hz | 30 / 30 / 30 | `6c53c71f-69c7-4056-bc93-4fa855ca2e72` |
| 2 Hz | 60 / 60 / 60 | `abe94436-5be8-4b49-8c39-5af6ef89c84b` |
| 2 Hz | 60 / 60 / 60 | `c011fc7c-2d44-49f8-9f96-8a23da530e77` |

Each run had a distinct execution label and pod UID, with a fresh Running
subscriber observed before publication. Both prior terminal Jobs/pods and their
individual 30/60-image logs were archived before replacement. All five result
JSONs record success, zero exit codes and no timeouts; their full result and
command stderr streams are empty. Eleven Ansible recaps/12 host rows have zero
failed/unreachable hosts.
Final teardown is verified. All 836 prior local compact files and nine remote
files, eight unrelated shutoff domains and three prior running node3 domains,
including inactive XMLs, remain unchanged. Full stdout/stderr/metadata, all five
state/lock pairs, raw logs, six metric tables and 96 captures were manually
inspected and independently reviewed.

Evidence is under `development-packet-b-a6846eb82d18-attempt2` in the private
durable root below. `finished.json` lists all five result paths;
`accepted-development-manual.json` records the assessment and limitations
(SHA-256 `51391d7426626bccd16a5d250eb0580b5ee8c38de0c9ef7af0601fd920d18fd5`).
The first attempt remains intact under `development-packet-b-a6846eb82d18`:
infrastructure failed before any application because the temporary raw-runner
harness created its base ancestor with mode0700. Independently reviewed harness
preparation created only fresh attempt2 traversal directories with wrapper-equivalent
0755 modes; no failed path or production source was repaired. All 216 first-attempt
evidence files and its failed QCOW2 remain unchanged.

The first application retains two parser diagnostics from interleaved data-size
and preprocessing log lines, omitting one sample from each of those summaries.
Its 30 worker ML records and 30 endpoint result receipts still match the complete
image counts; required RTT/processing summaries are finite. Printed one-way delay
has no synchronization validation. This proves the tested sequential reuse only,
not generic sweeps, multi-stage execution, exact Kubernetes patch pinning or
final-candidate acceptance. Compact archives exclude disks, private SSH keys,
Ansible temporary trees and full host journals.

The separately reviewed
[development-only two-host pilot amendment](superpowers/plans/2026-10-28-development-parallel-validation.md)
has explicit user approval for the bounded node4/node5 allocation, preparation and
cold/warm isolation pilot. Both cold and both warm infra-only runs completed with
exit code zero without timeout; each result reports teardown verified and both overlap
samplers passed. Independent evidence review verified all 402 indexed entries with no
material unresolved isolation finding, and the coordinator accepted the bounded pilot.

All four runs use immutable, detached clean snapshots of
`445270eed59e3808a408c40f9826b74617937f44`, not packet-C or foundation source.
Each singleton host runs one 2-vCPU/2-GiB workload guest with software:none and built-in
`delete_on_exit`, reusing only its own root/pools for the warm round:

| Slot / host | Canonical allocation root | Workload pool | Base-image pool |
| --- | --- | --- | --- |
| A / node4 | `/mnt/sdc/matthijs/continuum_parallel_pilot/slot-a` | 192.168.180.2–192.168.180.251 | 192.168.181.2–192.168.181.251 |
| B / node5 | `/mnt/sdc/matthijs/continuum_parallel_pilot/slot-b` | 192.168.182.2–192.168.182.251 | 192.168.183.2–192.168.183.251 |

Only .2 is used in each pool. Node4 uses its attributed
`/home/matthijs/venvs/continuum/bin/python3`; node5 uses slot-b's new own `venv`.
Both are Python 3.8.10/Ansible core2.13.2 with the identical 74-line freeze
(SHA-256 `a00adebafbd6e1fd9e71b5f6800a3deed7f17e64623fbf376c21261f13ad9c50`).
Native pkg-resources source/metadata bytes matched before installation; node5 used
71 hash-recorded wheels. The preparation addendum distinguishes retrospective
public-PyPI byte agreement from the unrecorded original download endpoint.

Complete cold/warm results, streams, metadata, locks/state and overlap/preservation
captures are sealed under slot-a's `evidence/cold-review` and `evidence/warm-review`
(including their node5 subdirectories). The final assessment/index are in
`evidence/final-addendum/{assessment.md,final-index.json}`; SHA256SUMS SHA-256 is
`909ab2501eb8ab96e39289ef3b009b33d54477fd7ee6c6956beef21e48579e6b`.
Cold overlap was observed during the temporary 1-vCPU/1-GiB base builds; warm overlap
captured the live 2-vCPU/2-GiB workload XML. Cold rebuilt each base; warm reused it.
Original disks remain in their own slot roots. Final surveys report unchanged
protected node3/node4/node5 domains and HOME baselines, clean unchanged snapshots
and freezes, and no active pilot domain; the physical window is returned.

Cold workload live MACs and direct guest `ip -j addr` were not captured. Warm live
XML, fixed inventory and host-neighbor MAC/address mapping corroborate the reserved
addresses. Infrastructure-only workload readiness used SSH-keyscan, not authenticated
workload login; cold base installation did demonstrate authenticated Ansible SSH.
Node5's actual client/socket had exited before observation; configured private options
are retained. The approved physical Ansible HOME temp exception remains explicit,
with preexisting HOME baselines preserved. These limits are not repaired by extra runs.

Acceptance enables only this fixed two-singleton-host development allocation, with
one workflow per host. A new task still needs identical clean snapshots, fresh capacity and
allocation/preservation guards, and separate coordinator release. It cannot enable
shared-host or concurrent multi-host workflows, timing comparisons, final-candidate
acceptance or concurrent OpenFaaS. Final acceptance stays serial; exact OpenFaaS stays
last under its separate node3 approval. No core, wrapper or scheduler change was made.

Approval receipt `development-parallel-pilot-approved-20261028.json` has SHA-256
`7c7ea4a3d5a14f2cc9c77945268dfe30e097a35611dbfb04cfcbbf79c060bbfd`.
Durable proposal/survey evidence is under
`development-parallel-pilot-proposal-20261028` in the private evidence root below;
its SHA256SUMS SHA-256 is
`e690168b73fa7623d3b19946a5704d1b32a36a9e25583ee3151ec4b0484e87df`.

The approved amendment remains unchanged; pilot results do not renew later source
or static evidence.

## Packet C — static core-contract closure

The independently reviewed bounded core repair is committed locally at
`31d62c044d1cf073c3f942700a99c28476a91c9a`. Lock replay now rejects missing or invalid
normalized kind/schema metadata. Persisted resume contracts, state and E2E lock/state/
metric envelopes reject boolean or float schema versions, preserving valid integer
versions. Selector documentation consistently describes software-only `any_of` unions
and single-`match` benchmark assignment; module documentation distinguishes the current
`PlanEntry` execution adapter from proposed graph/module APIs. Execution authorization,
resume hashes, phases, supported QEMU resume and artifact retention are unchanged.

Five new test methods first produced 17 expected malformed-input assertion failures,
then passed with the repair. Focused regressions passed 223/223 and complete combined
unit/local-e2e discovery passed 1,125/1,125 on separately attributed Python 3.12.7.
Docs paths and whitespace checks passed. Per-file Python lint comparison adds no
findings to the existing baseline; static Python 3.12 lint covered the two test carriers
whose existing syntax the pinned Python 3.8 linter cannot parse. Root independently
reran the five new methods successfully and verified the complete twelve-file review.
The pinned physical-runner environment was not changed or used for runtime validation.

Primary saved source/test/lint logs, the reviewed diff/hash manifest, report and v8
generation checks are preserved in `development-packet-c-31d62c044d1c-static` under the
private evidence root below: 91 files, 0700/0600 directories/files, with SHA256SUMS
SHA-256 `80805caacd51331711d345656b7b85ce12a542466c00fb6171f4cff026c837c2`.
The independent rerun/review attribution is in the coordinator transcript, not an
invented saved stdout artifact. Both complete packet-B evidence directories, 590 files,
were hash-verified unchanged before/after the new preservation copy.

Configuration inventory v8 is bound to clean `31d62c0`: 358 rows/135 exclusions,
all source hashes and raw declarations checked. Exactly five existing fixture/support
rows changed; their current static fixture facts include the five new methods.
No input or exclusion changed, no path was added/removed, and all forty v2–v7 snapshot/
receipt files remain unchanged. See `docs/configuration_inventory.md` for exact hashes.

This is a reviewed source/static checkpoint, not VM-backed core or final-candidate
acceptance. C performed no VM/remote/host workflow. Next is packet D's existing
foundation/Kubernetes/endpoint/observability integration slice after coordinator release,
followed by the selected module order in the approved closure plan. Individual broader
static gates and the final frozen-candidate runtime sequence remain required at their
designated checkpoints; B's earlier development evidence is not renewed for this source.

## Packet D foundation — source checkpoint, runtime pending

The independently reviewed three-file observability repair is committed locally at
`2f969bb34de37060dc19bba7cc50d9b06e16136e`. Existing YAML suites and planner wiring
were retained. The role now requires Grafana deployment availability, two available
Prometheus replicas, healthy HTTP services on each distinct advertised controller
address and the selected forwarding processes' exact UID/command identities.
Private guest logs append without automatic process replacement; bounded diagnostics
preserve the original readiness failure. Defaults, versions, configs, core/runner
interfaces and the pinned runtime environment are unchanged.

The actual original role returned success despite a simulated Prometheus readiness
failure; the new regression first failed, then passed with the repair. Root separately
saved the raw original-role RED reproduction and passed the distinct-address probe.
Pinned Python 3.8.10/Ansible 2.13.2 checks passed seven new inert-policy methods and
the complete 46-test role suite; stronger final assertions in those seven methods also
passed. Planner tests passed 31/31 on pinned Python and separately attributed static
Python 3.12.7. YAML/Ansible lint and whitespace passed; Python lint retained exactly
the baseline's 72 findings, with no added symbol/message findings. The complete
three-file uncommitted review was CLEAN and root verified the exact diff/file hashes
before releasing the local commit.

Primary static logs, root raw RED/probe artifacts, reviewed source diff/manifest,
frozen reports and drivers are preserved under
`development-packet-d-foundation-2f969bb34de3-static` in the private evidence root:
32 files with 0700/0600 directory/file modes; SHA256SUMS SHA-256
`b78504719893b2091a4f15293a9361def5df1005646094ad40ee96a2bfdf3ca8`.
All 681 files in the two complete packet-B evidence directories and packet-C static
directory were hash-verified unchanged before/after preservation. New inventory v9
is bound to clean `2f969bb`: 358 rows/135 exclusions, unchanged input set and
classifications/dispositions, all source hashes/raw declarations/normalizations and
45 carrier AST facts verified. Exactly the role-test carrier and observability-task
exclusion changed. All 47 previous inventory snapshot/receipt files remain unchanged;
see `docs/configuration_inventory.md` for exact inventory hashes.

No foundation VM/remote/host validation has run on this source. The separate pilot is
independently accepted and its physical window returned; it does not release foundation
execution. This static checkpoint does not certify a frozen candidate. After the
coordinator separately releases the serial node4 foundation physical window, first validate
actual observability readiness with exact
`qemu_k8s_nobench_parity`, then the approved serial foundation development suites:
`operational_regression`, `qemu_infra_parity`, `network_validation`,
`qemu_k8s_image_parity` and `qemu_endpoint_image_parity`. Preserve failures before
diagnosis; require real image outcomes and complete artifacts, not software-only
success. Two operational passes and all exact suite checks on the later frozen
candidate remain separate obligations before broader review. KubeEdge follows only
after this first family's closure under the approved module order.

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
   accounts for 310 inputs and 48 fixture/support/metadata sources; its preserved
   refreshed per-file evidence is bound to clean
   2f969bb34de37060dc19bba7cc50d9b06e16136e, after the reviewed foundation
   observability source repair; all seven earlier snapshots remain unchanged. Final
   historical
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
