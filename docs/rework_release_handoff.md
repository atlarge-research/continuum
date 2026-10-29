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
pre-main goal is not complete. Packet D's foundation development checkpoint below
combines five accepted cases on clean `73a30b7` with the accepted fresh endpoint
recovery on clean `e3fcdf0`; the failed original endpoint case remains a failure.
The KubeEdge mixed-source, Mist and Columbo development checkpoints and committed
Kata source checkpoint are recorded below.
Next is exact Kata runtime validation, then OpenFaaS last, serially, subject to
actual future clean HEAD/source-diff and accepted Columbo normal-receipt binding, fresh guards,
independent review and separate coordinator release. The independently accepted
pilot enables only its fixed node4/node5 development allocation below; it does
not replace final serial acceptance.

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

## Packet D foundation — development checkpoint

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
directory were hash-verified unchanged before/after preservation. Historical inventory v9
is bound to clean `2f969bb`: 358 rows/135 exclusions, unchanged input set and
classifications/dispositions, all source hashes/raw declarations/normalizations and
45 carrier AST facts verified. Exactly the role-test carrier and observability-task
exclusion changed. All 47 previous inventory snapshot/receipt files remain unchanged;
see `docs/configuration_inventory.md` for exact inventory hashes.

Five subsequent whole-suite foundation cases have independent/root DEVELOPMENT
acceptance on clean `73a30b72aae67267adaf5b979bf3b1a1a9f78061`:
`qemu_k8s_nobench_parity`, `operational_regression`, `qemu_infra_parity`,
`network_validation` and `qemu_k8s_image_parity`. They ran serially on node4 as
matthijs with pinned Python 3.8.10/Ansible 2.13.2 and an explicit empty external-host
override. Their separate `accepted-development-manual.json`/`finished.json` receipts
and complete results are under `development-foundation-73a30b72aae6-<suite>` in the
private evidence root below. The no-benchmark case includes an immutable sibling
version-attribution correction; operational includes an immutable source-binding
addendum. Original seals/reports remain unchanged. Do not repeat these five cases
or the completed normal-account retirement to renew this checkpoint.

| Accepted case on `73a30b7` | Actual development result and disposition | `accepted-development-manual.json` SHA-256 |
| --- | --- | --- |
| `qemu_k8s_nobench_parity` | 1/1; Grafana deployment and both Prometheus replicas available, 13 monitoring/8 system pods and two nodes Ready; four guests retained, then explicitly replaced by operational startup after preservation. | `bb0e7057341e6ef2559dbb38a4714f70ab53e8d44fca5528f7b247a1307807c0` |
| `operational_regression` | Four result JSONs/six successful entries; 30 sent/processed/returned image outcomes, finite RTT/processing tables and final teardown; one development operational pass. | `5a03a3ac073f077e2601d949e386a0b2f22ccdd5045cb0195ffba891c1682bad` |
| `qemu_infra_parity` | All four ordered cloud/pinned-edge/four-endpoint/all-tier members passed; 11 healthy recaps and final teardown. | `6bc24548c74e86ea0d9220e1d46897d731f7ac21f6445e622640509b7737c1b8` |
| `network_validation` | 1/1; current 13-row NDJSON covers 12 invocations/six directed pairs; existing verifier passed on attributed static Python 3.12.7. Three guests retained, then explicitly replaced by case5. | `958ed61530f607b1db8f39d5079503806f275b289ebbf80af5aec68a0977c9e7` |
| `qemu_k8s_image_parity` | 1/1; each publisher sent/returned 150, worker processed 300; finite CLOUD1/ENDPOINT2 rows and current 21-row NDJSON/ten directed pairs passed the existing verifier. Four retained guests were replaced by the failed endpoint startup. | `94160ab8d8c0a1f82f5091c969abdb4ff0104d225caa73574024f8d0fa6ca3a9` |

For each suite, its `finished.json` lists the exact result paths and UTC interval;
its accepted receipt and sealed report retain commands, artifact hashes, raw recaps
and preservation details. Acceptance provenance is the independent/root transcript
record, not a newly invented reviewer log. Whole-suite intermediate state/lock bytes
were overwritten; final files and per-entry detectors/full logs were inspected.

These are bounded development results. Observed Kubernetes API server v1.27.0
differs from client/kubelet/proxy v1.27.16; endpoint Docker versions varied.
Operational's late publisher-image query missed teardown, and the pinned-edge
live XML query missed its window; no generated pinned-edge XML survives, so there
is no direct vcpupin or hardware-isolation proof. Observed Netperf 2.7.0 does not
establish a fetched/build commit pin. For expected rates above 100 Mbps, network
verification requires finite positive throughput, not configured 1000-Mbps fidelity. Point-in-time
observability health and functional image outcomes do not establish complete
scraping, sustained frequency or synchronized one-way timing. The case5 accepted
review provenance records one accidental read/hash of the failed-B disk, matching
unchanged bytes without mutation; no repeat is needed. Compact evidence excludes
disks/private keys; retained-backing existence/current sizes are not live-byte
invariance. Retention and startup-replacement dispositions remain case-specific.

The sixth `qemu_endpoint_image_parity` case failed on the same `73a30b7` source before
new base/guest/application launch: entry exit 1 without timeout after 40.833s,
driver exit 2. Its failed `finished.json` SHA-256 is
`4905c28b62791e6caca433db071273816a9329569a4ca5f699bde6e347de6ce7`;
the 247-file failure/diagnostic SHA256SUMS SHA-256 is
`2dfa174279806d9f9cfd6d9efdc2017b56aab6774366d51c551b5ec876550bcf`.
This packet is accepted for preservation/diagnosis only, not runtime success.
Normal startup had removed the four authorized own case5 guests; no new own node4
guests remained and the physical window returned. No endpoint image outcomes,
current metrics or final application teardown were demonstrated.

Bounded later HEAD/GET requests for the same immutable digest returned a valid
2,392-byte, 66-line OCI manifest. `Machine.process` splits stdout into lines;
the registry consumer parsed only its first line. That reproduces a source defect
against the current same-digest response, not the unavailable original HTTP bytes.
The independently reviewed two-file repair is committed locally at
`ba5e50f05c22a5118a83ea1412aaf7141c15df60`. Its only product change joins all
manifest output lines before JSON parsing; immutable-digest lookup and every
strict schema/media/config/layer/digest/size validator are unchanged. The existing
test helper now models the real line-list transport. Two new methods cover real
Machine processing with mocked subprocess bytes for both OCI/Docker families and
complete-body acceptance/rejection, including trailing garbage or a second JSON
value. No network, VM or cache bypass is part of those tests.

The two methods first reproduced six assertion failures and two production
RuntimeErrors on old source, then passed. Focused registry/QEMU-cache checks passed
138/138; 961 unit, 173 local-e2e and final combined 1,134 tests all passed on separately
attributed static Python 3.12.7. The final combined run binds the exact reviewed
source hashes after the scoped test-lint comment. Changed-file pylint retained
6/6 product and 419/419 test findings with no added finding identities; existing
module/class size diagnostics changed numerically. Product lint used pinned
Python 3.8.10, the large test carrier used static Python 3.12.7 due the documented
pinned-tool limitation. Raw RED/GREEN, focused/full-suite, lint and complete review
records are saved in `.superpowers/sdd/2026-10-28-local-module-closure/` as the
`endpoint-manifest-*` artifacts. Static tests do not establish a physical endpoint
pass or recover the failed request's original response.

Fresh configuration inventory v10 is bound to clean `ba5e50f`: 358 rows/135 exclusions,
all 493 source hashes, 259 cfg/51 YAML raw declarations, 30 normalizations and 45 carrier
AST facts verified. Only the existing runtime-test carrier changed, including the
two new methods; no input, exclusion hash, classification or disposition changed.
All 54 v2–v9 snapshot/receipt files and historical manifest bytes remain unchanged.
The v10 manifest SHA-256 is
`cb95a2daeee50b00295d2a728d150d002b56ad40d660e2a6dd2028c08f8e2304`;
the 2,128,885-byte inventory SHA-256 is
`6ae68286372c3ef731bef8607116c4d756e44aa3c707ddabe24debc82ad03834`.
See `docs/configuration_inventory.md` for the new receipt and preserved histories.

The fresh whole-suite endpoint recovery has independent/root DEVELOPMENT acceptance
on clean `e3fcdf05b832624416e4908a53170530668c9ce1`, containing the unchanged repair
and v10 source checkpoint above. It ran as matthijs/UID1002 on singleton node4 with
pinned Python 3.8.10/Ansible 2.13.2 and an explicit empty external-host override:

```bash
/home/matthijs/venvs/continuum/bin/python3 scripts/test/run_tests.py \
  --suite qemu_endpoint_image_parity \
  --base-path /mnt/sdc/continuum_smoke/foundation_e3fcdf05b832_qemu_endpoint_image_parity_recovery \
  --external-physical-machines '' --stop-on-failure
```

This command used the attributed pinned physical-runner environment;
`step-01/planned-command.json` in the recovery evidence preserves the exact argv
and environment, including normal HOME and the explicit Ansible temporary path.
The driver ran from 2026-10-28 21:35:40.358050Z to 21:58:05.859138Z. Result
`test_results_2026-10-28_21-57-56.json` records 1/1 success, exit zero, no timeout
and empty stderr; the entry took 1321.4976 seconds. Seven Ansible recaps/eight host
rows have no failed/unreachable host. Each combined endpoint container has 1,500
actual processing and 1,500 actual latency records, establishing 3,000 completed
image outcomes independently of configured completion markers. Current ENDPOINT2
CSV rows are finite, their manifest is current, final state/lock agree and actual
final teardown left no own node4 guest. Eleven protected domains remain unchanged.
Combined containers have no MQTT publisher/send/reply count contract.

Evidence is under
`development-foundation-e3fcdf05b832-qemu_endpoint_image_parity-recovery` in the
private durable root below. Its separate `accepted-development-manual.json`
SHA-256 is `c2a19ed7785e4ecf8a0d824432372738ebd0f3648601d941cba710925a0322b4`.
It binds `finished.json` SHA-256
`8ce7c221d8909e102e5d2643a5b80a9937b70b5151042c27c709d16c3deb8d10` and the
241-file SHA256SUMS SHA-256
`0e56551f11434edcf22a4c9dc9826d3dff278f8f8be4b76bf0036094cc99c5b9`.
`manual-evidence-report.json`, `manual-assessment.md` and `evidence-index.json`
retain the detailed counts, hashes and limits. Their earlier pending-assessment
wording is immutable; the separate acceptance receipt records the later decision
and is excluded from the prior seal. This recovery renews none of the five older
cases for its source and does not turn the failed original endpoint case into a pass.

Six bounded live captures ran once at 21:53:08–11Z: both containers were running
without observed OOM, with Docker 26.1.3/containerd 1.7.24 and the same observed
combined-image config `40eb5ff222362c90b338e6ddf959ee72a14dae867b18bccab99408a75d31d507`
and manifest digest `03fe3d1382b6b140a2f2d6f5f909c696e6b35145e5f04472d7ffff44f19841b8`.
These are executed-image identities, not fresh-source-build proof. The observations
are point-in-time with non-atomic phase/deletion checks. Saved XML/current launch
commands demonstrate the requested two VMs, each two vCPUs/3 GiB/quota 0.75; no
independent live XML resource sampler was added. Raw spans were 309.695920 and
308.924207 seconds with one and two cadence warnings respectively, so configured
5 Hz/300 seconds does not establish sustained 5 Hz. Finite processing/latency
does not establish synchronized timing or accurate one-way delay. `netperf:false`
and no endpoint-pair shaping proof supply no network NDJSON/fidelity claim.

Six compact archive maps verified before/current/after counts of 1160/9, 24/0 and
1184/9 local/remote files; all 4,044 prior non-disk evidence files were preserved.
Review preparation mechanically excluded disk/private-key paths before content
reads/hashes; the inherited failed-B disk-content guard belongs solely to the
reviewed runtime driver. The failed endpoint base was not reused or warmed and
its metadata comparison is stat-only. Eight older case5 backing records establish
recorded current existence/size, not live-byte or size invariance. Compact archives
also exclude Ansible temporary trees and full journals. The physical window is
returned. No new runtime workflow is released by this documentation checkpoint.

Next is Kata, then OpenFaaS last, serially in approved order. The
KubeEdge mixed-source, Mist and accepted Columbo development checkpoints below
preserve their distinct source and acceptance bindings. Kata's approved two-file
retry repair is committed at `b7c51977cd165820082f720624f8439a033b5f76`;
exact runtime validation remains pending, requiring actual future
clean HEAD/source-diff and accepted Columbo normal-receipt binding, fresh guards,
independent review and separate coordinator release; this checkpoint releases
no later runtime workflow.
Packet E's demonstrated CLI tunnel-hint defect remains open: the printed forward
destination uses the worker IP although the service binds the controller; fix and
regress it before freeze. No final candidate is frozen. Two complete operational
passes, all exact suite checks and the reuse proof on that later candidate, the
twelve canonical static gates and final human review package remain required.

## Packet D KubeEdge — mixed-source development checkpoint

Independent evidence/source/replay reviews and root adjudication accepted only
MIXED-SOURCE DEVELOPMENT: the full `qemu_kubeedge_image_parity` VM workflow ran
on clean `07e2c4f02768b45db2bece3d91dd0ac90345f476`; corrected host-side metric
parsing and offline replay ran on clean `3812449c0d04a3b2c9fe189e2e9b5bff11bf9409`.
This is no VM pass on the repair revision or frozen-candidate acceptance. The
original invocation used matthijs/UID1002, singleton node4, pinned Python
3.8.10/Ansible 2.13.2 and the attributed environment in its immutable
`planned-command.json`:

```bash
/home/matthijs/venvs/continuum/bin/python3 scripts/test/run_tests.py \
  --suite qemu_kubeedge_image_parity \
  --base-path /mnt/sdc/continuum_smoke/kubeedge_07e2c4f02768_image_parity \
  --external-physical-machines '' --middle-ip 180 --middle-ip-base 181 --stop-on-failure
```

The product result records 1/1 success, exit zero and no timeout, with 3,000 actual
completed image outcomes: each worker processed/replied to 1,500, and each
publisher sent/received 1,500. Both publishers/subscribers exited zero, without observed
publisher OOM. Three Kubernetes nodes/Flannel nodes were Ready and CloudCore had
one available replica at observation. Requested resources were 12 vCPUs/16 GiB;
five workload guests were intentionally retained, not finally torn down, and eleven
protected domains were unchanged. The physical window returned. None of this
releases a later runtime workflow.

The original driver stopped after its Docker-version capture hit a guest socket
permission error; its `finished.json` remains `accepted:false`. Original endpoint
metrics were corrupt: two values silently merged and four warned/dropped. The
257-file original seal and 577-file supplement remain immutable; the supplement's
`capture-completion.json` also remains `capture-failed`, `accepted:false`. It
contains 41 successful safe observations, one unsafe `edgecore --version` attempt
that started a secondary process/initialized SQLite and MQTT code before panic,
and one omitted unsafe query. Later observations found the original edgecore
unit PIDs 4233/5259 active; guest filesystem/SQLite/MQTT effects remain UNKNOWN,
with no global immutability or uninterrupted-health claim. Actual subscriber Pod
specs were Always (CloudCore IfNotPresent), correcting the original sealed report's
ARGV-to-rendered-policy inference; no cache-policy product change was made.

The bounded parser repair separates each field's own integer/unit. Seven new
regressions passed with all 10 focused tests on pinned Python 3.8.10; static
Python 3.12.7 passed 968 unit/173 local-e2e/1,141 combined tests. Changed-file lint
retained exactly six baseline findings and added none. The separately sealed
offline replay recovered all six demonstrated anomalies, with 1,500 latency,
preparation and sending records per publisher and zero new warnings; ordinary
observations were unchanged, and the old parser reproduced the original CSV
exactly. Corrected metrics exist only in the replay sibling; original logs, CSV,
manifest, results, state/lock and failed driver records remain unchanged.

All following directories are under the private durable evidence root below.
The separate manual receipt records the later acceptance; it replaces neither
failed record and invents no completed `finished.json`.

| Evidence | Directory / exact binding |
| --- | --- |
| Mixed-source manual acceptance | `development-kubeedge-07e2c4f02768-development-assessment-3812449c0d04/accepted-development-manual.json`, SHA-256 `2db3666c4d3a614e1fc5cadb06a282eb4ab601b231633995aa4dac07ab7deee7`; one-member seal `5e8f214f9b16fd945ee0837432fe29ef155f83289993a08e6c5f0f5063fc7b8d`. Binds original `development-kubeedge-07e2c4f02768-qemu_kubeedge_image_parity` and its `-capture-completion` supplement. |
| Corrected offline replay | Original directory plus `-metric-replay-3812449c0d04`; `replay.json` SHA-256 `28b9d8117a8eb7502e24488de689e02c26b7c1fbd51feb1746d298b83794227f`, five-member seal `e88e2e95888f566cf927e34f9b8b274ac389eaab8b492affaa174ca759ecaed8`. |
| Source/static durability | `development-packet-d-endpoint-metrics-3812449c0d04-static/preservation-receipt.json`, SHA-256 `63280bd9a22ec0d05f1c6b2ebde85d1115994f0206903c3d372cc9b2fbc9c3d9`; 26 explicit source/review/diff/RED/GREEN/test/lint/baseline artifacts, exact copies with private 0700/0600 modes. Source-review adjudication is attributed to the coordinator transcript, not an invented report. |

At that checkpoint, configuration inventory v11 was bound to clean `3812449`:
358 rows/135 exclusions, all 493 source hashes, 259 cfg/51 YAML raw declarations,
30 normalizations and 45 carrier
AST facts verified. Only the existing publisher-test carrier changed, adding the
seven tests/two helpers; no input, exclusion hash, classification or disposition
changed. All 61 v2–v10 snapshot/receipt files remain unchanged. Exact v11 hashes,
generation receipt and historical bindings are in `docs/configuration_inventory.md`.

Readiness/version captures are point-in-time. Actual controller kubelet/client
was v1.27.16, server v1.27.0, edge embedded kubelet v1.31.12-kubeedge-v1.22.0 and
keadm v1.22.0; Docker/containerd versions differed between worker/controller and
endpoint guests. This establishes no uniform patch pin or fresh-source image
build. Configured 5 Hz/300 seconds and finite corrected averages establish neither
sustained 5 Hz nor synchronized/accurate cross-host one-way timing; ten negative
worker one-way values remain. Compact archives omit disks/keys, Ansible temporary
trees and full journals; no backing-byte invariance, KubeEdge reuse, alternate
topology, broad support or final teardown is established. Exact Kata runtime
validation, Packet E's CLI fix, the full final frozen matrix/twelve static gates,
two operational passes, final-source reuse proof and human review remain OPEN.

## Packet D Mist — development checkpoint

Independent evidence review and coordinator adjudication accepted one development
Docker/MQTT image-classification workflow: the full `qemu_mist_image_parity` suite
ran on clean `46e7a29606c1ba4175b50b92964ac350b57ed587`. This is not frozen-candidate
acceptance. It ran as normal matthijs on singleton node4 with inherited Python
3.8.10/Ansible core 2.13.2 and the exact existing environment retained in its
immutable `planned-command.json`:

```bash
/home/matthijs/venvs/continuum/bin/python3 scripts/test/run_tests.py \
  --suite qemu_mist_image_parity \
  --base-path /mnt/sdc/continuum_smoke/mist_46e7a29606c1_image_parity \
  --external-physical-machines '' --middle-ip 180 --middle-ip-base 181 --stop-on-failure
```

The suite passed 1/1, wrapper exit zero without timeout, with 6,000 completed
image outcomes: two workers each processed/replied to 3,000, and four publishers
each sent/received 1,500. Two EDGE and four ENDPOINT metric rows are finite. The
existing `3812449` parser handled all fifteen merged numeric records with zero
parser warnings; no new repair or offline-replay substitute was needed. Nine
Ansible recaps contain fourteen host rows, all zero failed/unreachable. Generated
XML requests six workload VMs, eight vCPUs and 16 GiB, not independently sampled
live resources. Delete-on-exit left zero owned workload/base domains; all eleven
protected domains were unchanged and all 5,131 prior non-disk evidence files
were preserved. The physical workflow returned.

Configured 5 Hz/300 seconds remains nominal. Raw publisher spans were approximately
314.76/314.42/324.41/324.37 seconds; the whole suite took 2165.264539 seconds.
These measure different intervals, with no clock-cause diagnosis inferred.
Finite summaries and no observed negative one-way values establish neither
sustained 5 Hz nor synchronized/accurate cross-host one-way timing. No guest
observer or edgecore invocation occurred. Actual workload Docker server,
containerd, OS/package versions, image IDs/repo digests and OOM state were not
independently inspected; saved pull/registry output is not runtime inspection.
Saved worker status-command invocations precede publishers and reviewed source
requires `Up`, but actual Docker response bytes are unavailable. Completed replies
establish the application path. Final application state/lock are retained;
overwritten intermediate infrastructure/software state bytes are unavailable.
Compact evidence excludes disks/private keys, Ansible temporary trees and full
journals; no backing-byte invariance is established.

Under the private durable evidence root below, the accepted packet is
`development-mist-46e7a29606c1-qemu_mist_image_parity`. The separate normal manual
receipt records the later decision outside the original 249-member seal. Original
`finished.json` remains `completed-unassessed`, `accepted:false`; it and the
report's pending-assessment wording remain immutable. Neither this acceptance nor
the existing parser turns preceding KubeEdge evidence into a VM pass on this source.

| Evidence | Exact binding |
| --- | --- |
| Development acceptance | `accepted-development-manual.json`, SHA-256 `9889c2f2e6da954674fe5ef6a16c10a159171fea74025e784f478759ee2c5125`; original `SHA256SUMS` SHA-256 `d86ca3e3798e542e7cca12fe0f3ce614e413612c082ddeca88f8b79f863e32d7`. |
| Original completion | `finished.json`, SHA-256 `ca5132b3aea7642f1a68b7a5cea8ca0c2c43c1dab66da89a51da03316d568a49`. |
| Product result | Original run base above: `.continuum/test_results/test_results_2026-10-29_01-29-58.json`, SHA-256 `510e6943f439ef447733bf585949c298b2ace20768d0eddfec2bffcc7eb1e22d`; detailed counts, metadata and limits remain in the packet's `manual-evidence-report.json` and receipt. |

This establishes no sequential reuse, alternate topology, broad support or release
certification and releases no later runtime. Packet E's CLI fix, exact Kata runtime
validation, the full final frozen matrix, twelve canonical static gates, two
complete operational passes, final-source reuse proof and human review remain OPEN.

## Packet D Columbo — development checkpoint

Independent evidence review and root adjudication accepted one strict `call_1`
development workflow: the full `qemu_kubecontrol_empty_trace_parity` suite ran on
clean `a1e5db24d9b68d28883398a715eebd60af556763`. It ran as normal matthijs on
singleton node4 with inherited Python 3.8.10/Ansible core 2.13.2 and the custom
local Kubernetes archive. Its immutable `planned-command.json` retains the exact
environment and historical argv:

```bash
/home/matthijs/venvs/continuum/bin/python3 scripts/test/run_tests.py \
  --suite qemu_kubecontrol_empty_trace_parity \
  --base-path /mnt/sdc/continuum_smoke/columbo_a1e5db24d9b6_empty_trace_parity \
  --external-physical-machines '' --stop-on-failure
```

The suite passed 1/1, wrapper exit zero without timeout, in 1576.7825138568878
seconds. The single current Pod `empty-1-qslt7` Succeeded with exit zero and zero
observed restarts; its actual pull policy was `Never`. All six current required
trace columns are finite and agree across CSV/stdout, five raw instrumented
markers and the unique current Pod application start modulo 3600, within the
unchanged 0.00001-second tolerance. Deployment/resource/resource-OS CSVs contain
1/18/58 rows. This agreement and the source's whole-hour adjustment establish
neither synchronized clocks nor accurate cross-host one-way timing.

All 26 saved bounded guest queries exited zero without timeout; both nodes were
Ready at observation. No additional observer ran. Twelve Ansible recaps contain
fifteen host rows, all failed/unreachable zero. XML requests two VMs, each eight
vCPUs/32 GiB, rather than independently sampled live resources. Both workload
domains remain running intentionally; all eleven protected domains were unchanged
and all 5,382 prior non-disk evidence files were preserved. The physical workflow
returned; no final teardown or later runtime release is implied.

Point-in-time guest observations show Ubuntu 20.04.6, kernel 5.4.0-216-generic,
containerd 1.7.27 and custom Kubernetes `v1.27.0-16+1b4ffff113e941` clients,
kubelets and server, not stock v1.27.16. Archive SHA-256
`bbae85b5c1c7a5bc288adcc0289d13b2a8923b000031dfac0e0e65e5b487786d` matches the
copied-input fingerprint; no archive-member comparison to installed binaries or
build-origin proof was performed. The detailed saved binary/image identities
remain point-in-time observations in the report/receipt.

The first offline assessment helper failed by choosing a cached same-name Job
`0028` event as its anchor; its exact helper, traceback and command receipt remain
preserved. Independently reviewed correction `93641e13...` selects the unique
actual Pod application start with unchanged tolerance and passed on the same VM
evidence. No VM retry or product-source repair occurred. One binary-journal match
and five stop-after-required-Pod debug messages remain preserved; eight kubectl
captures contain instrumented `0400/0402` stderr, so no blanket empty-stderr claim
is made. Final application state/lock and complete compact evidence are retained;
overwritten intermediate phase-state bytes are unavailable. Compact evidence
excludes disks/private keys, Ansible temporary trees and full journals; backing
stat metadata establishes no byte invariance.

Under the private durable evidence root below, the packet is
`development-columbo-a1e5db24d9b6-qemu_kubecontrol_empty_trace_parity`. Its separate
normal manual receipt records later development acceptance outside the original
320-member seal. Original `finished.json` remains `completed-unassessed`,
`accepted:false`; it and the report's pending wording remain immutable. Detailed
counts, metadata and limits remain in `manual-evidence-report.json` and the receipt.

| Evidence | Exact binding |
| --- | --- |
| Development acceptance | `accepted-development-manual.json`, SHA-256 `f26745f0cadfd0853477596f81788a4b7ed163d445866b2ac89e502e3c49375c`; original `SHA256SUMS` SHA-256 `d20e0909e70c85c188a1ef7d68c17e20acc5fa452d3c04121dab6165d58f33b9`. |
| Original completion | `finished.json`, SHA-256 `2738254547fa41083755475d3b571ef32c94e832f02bb74ab7466e4310990823`. |
| Product result | Original base above: `.continuum/test_results/test_results_2026-10-29_02-12-58.json`, SHA-256 `c3e6d7b0d340d73113737e9eeadc00dd69a38099430e68b9877b476d5f8c3ed3`. |

This establishes no sequential reuse, alternate topology/provider/mode, paper
sweep, broad support or frozen-candidate/release acceptance. Kata's approved
two-file retry repair is committed at `b7c51977cd165820082f720624f8439a033b5f76`;
exact Kata runtime validation remains next, with OpenFaaS last and serial.
Packet E's CLI repair/presentation, final source freeze, the full
final matrix, twelve canonical static gates, two complete operational passes,
final-source reuse proof and human review remain OPEN.

## Packet D Kata — committed source checkpoint, runtime pending

The independently reviewed two-file retry repair is committed locally at clean
`b7c51977cd165820082f720624f8439a033b5f76`, parent/baseline
`cb6e334c7054b63264a722f33f37c75dd83cfb04`. It adds an explicit `allow_empty`
parser option, default false, used only inside the existing bounded fetch loop.
Valid zero-complete responses can reach the next attempt; strict default/final
parsing, the twelve-fetch/eleven-delay bounds, cache-trace exclusion and fatal malformed/
transport behavior remain unchanged. No lifecycle, topology or runtime change
was made beyond that bounded repair.

Pinned Python 3.8.10 evidence records the original regression RED exit1 and
GREEN 1/1, focused Kata 10/10 and whole carrier 36/36. The original RED test source
was reconstructed after execution from exact reviewed patches and matched the
execution receipt's source hash; it was not an original pre-execution copy.
The RED run used unchanged baseline product code. GREEN/focused/carrier and
required static runs used uncommitted repaired bytes on cb6 that match the
now-committed b7c source. Separately attributed Python 3.12.7 proof passed all
twelve canonical REQUIRED static gates: 973 unit, 173 local-e2e and 1,146 combined
tests, all exit0. Optional/informational checks and the full audit script were
not run. Scoped baseline/current lint added no symbol/object findings;
the existing SoftwarePhasePlanTests too-many-public-methods warning changed
21/20 to 26/20.

Independent evidence review and root verification accepted the finite source/static
preservation under the private durable evidence root below:
`development-packet-d-kata-b7c51977cd16-static/preservation-receipt.json`, SHA-256
`6a4c327d4ed99330bf3358addaac28f3bf60e283209d1c13d2392f776d85f71b`.
Its 84 exact copied artifacts comprise 81 source/proof members, the complete
artifact manifest as metadata and two reviewed plans, plus the new receipt
(85 files total), with normal UID1002 and private 0700/0600 modes. The 26 font-cache
payloads named by the manifest were excluded. Original uncommitted receipts and
reconstruction provenance remain unchanged; source-review/local-commit
adjudication is attributed to the coordinator transcript.

Current configuration inventory v12 is bound to clean b7c: 358 rows/135 exclusions,
all 493 source hashes, 310 raw inputs, 30 normalizations and 45 carrier AST facts
verified. Only `scripts/test/unit/test_resource_manager_plans.py` changed,
adding five tests and `_kata_trace_config`; all 68 v2–v11 snapshot/receipt files
remain unchanged. Exact new hashes/size/receipt and historical bindings are in
`docs/configuration_inventory.md`.

This is source/static proof; exact Kata runtime acceptance remains pending.
Next is that exact workflow, then OpenFaaS LAST and SERIAL, requiring actual clean
HEAD/source-diff, accepted Columbo normal-receipt binding, fresh guards,
independent driver/evidence review and separate coordinator release. This
checkpoint releases no runtime workflow and advances no runtime acceptance.
Packet E's CLI repair/presentation, final source freeze/full frozen matrix,
twelve fresh final-candidate static gates, two complete operational passes,
final-source reuse proof and final human review remain OPEN.

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
   `b7c51977cd165820082f720624f8439a033b5f76` in inventory v12, after the reviewed
   Kata retry repair; all ten earlier snapshots, including v11 at source `3812449`,
   v10 at source `ba5e50f` and v9 at source `2f969bb`, remain unchanged. Final
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
