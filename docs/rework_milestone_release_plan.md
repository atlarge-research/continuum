# Continuum Pre-Main Stabilization Policy

## 1. Authority and execution order

This is the policy authority approved on 2026-10-27, including the explicit
normal-user migration amendment. It supersedes the earlier full old-main parity
release gate and speculative future-work queues. The authority map is
`docs/rework_plan_stack.md`; factual certification rows and evidence remain in
`docs/release_certification_matrix.md`. This policy does not renew those rows.

Execute in order: preserve failure evidence and one source-unchanged baseline;
synchronize policy and the amended runner boundary; narrow result inspection;
minimal QEMU cache repair; exact multi-host OpenFaaS validation; bounded support
inventories; approved slimming; exact-candidate acceptance. Each nontrivial
packet needs a bounded exact-file plan, independent read-only plan review,
proportional tests, full independent uncommitted diff review, and resolution of
actionable findings before a local commit. No later gate is waived by an earlier
static or runtime success.

## 2. Approved consolidated policies

1. **Required reproductions.** Before main, preserve and validate the
   Continuum/FastContinuum 2023 framework reproduction, the SPEC-RG 2023 artifact
   path, the Columbo ICPE 2025 minimal local-QEMU `call_1` full control-plane
   trace slice, and the exact documented local-QEMU Kata startup slice.
   Columbo does not require every figure or parameter sweep. Kata is not
   assigned to an inferred thesis. All other named papers, theses, student
   projects, and legacy replicate/config families are preservation candidates
   until the complete reproduction inventory and the user's final scope
   confirmation. Full old-main parity is no longer the pre-main release gate.
2. **Product boundary.** No new core product features before main. Limit work
   to stabilization, approved reproduction, narrow diagnostics, safety and
   meaningful tests. Do not introduce databases, frontends, package hubs,
   content-addressed cache generations, generalized inspectors or recovery,
   cross-commit resume tracking, or broad host-management machinery.
3. **Stop/resume v1.** QEMU only; same revision, same base path, same topology
   and software contract; linear infrastructure → software → application.
   Same revision is an operator precondition, not new Git-tracking machinery.
   Cross-commit resume, arbitrary software replacement on mutated VMs, and
   concurrent runs sharing a base path remain unsupported.
4. **Application sweeps.** Sequential same-application runs with changed
   benchmark parameters remain candidate-only until actual cleanup and
   idempotence evidence proves safe reuse. This does not authorize unsupported
   multi-stage benchmark pipelines.
5. **Cache and ownership.** Keep one mutable current QEMU cache per stable
   runner/host/profile-tokenized owner slot. Runtime runs as the normal user
   (`matthijs` on the approved node4/node3 hosts), never as root. Sharing one
   cache between Unix users is unsupported. The approved one-time migration
   preserves compact evidence and numeric metadata before bounded conversion;
   it is not runtime permission repair. Remove old accounts and installed
   wrappers only after replacement runtime verification and an exact UID/ACL
   retirement audit. For a valid peer, preserve QCOW2/cloud-init identity,
   owner/group/mode/ACL; coordinated reprovisioning may change disk contents
   and invalidate/republish only the ready marker. An invalid owner's exact
   sidecar, QCOW2 and derived cloud-init disk may be removed, never current-run
   YAML or unrelated peers. Access/cleanup failures must identify the path,
   operation and operator remedy, with no privilege escalation or automatic
   ownership repair.
6. **Configuration structure.** Keep experiment, environment profile and
   software profile as three composed YAML documents. Configuration and
   software semantic authorities remain their domain architecture documents;
   no configuration-library migration is authorized.
7. **Shipped inventory.** Every tracked `.yaml` under `configs/experiments/`
   and `configs/profiles/` is shipped inventory, including templates with
   an explicit template classification. Parser acceptance is not runtime
   support. Inventory legacy `.cfg` inputs and test-only fixtures separately.
   Each tracked file needs one classification/disposition and zero unaccounted
   rows before the configuration gate closes.
8. **Registry terminology.** The implemented approved hard cut is
   `run.registry_refresh: missing|all`, default `missing`, without aliases.
   Missing refreshes missing/invalid required registry images; all refreshes
   every required image. Parser, schema, runtime accessors, examples, tests
   and active docs change together; the removed image_prefetch key is rejected.
   Cache priming and guest preload are separate operations, not synonyms for
   this setting. Historical evidence is not migrated or renewed by the cutover.
9. **Retained inspection.** Permanently keep ordinary logs, raw stdout/stderr,
   metadata, state/lock, benchmark/network artifacts, storage/pruning controls,
   `latest-result-summary`, and narrowly indexed/full `latest-result-tail`.
   The temporary diagnostic replay surface is removed after completed diagnosis
   and exact multi-host verification. Its dedicated playbook/tests are removed;
   do not replace it with a generalized command runner.
10. **Evidence checks.** Provisionally preserve current checkers. In the
    slimming review, retain only mechanisms preventing a demonstrated false
    claim; consolidate proven duplication atomically with audit gates, tests,
    skills and docs. The current audit script, not an old skill summary,
    defines required gates. Historical evidence remains truthful and distinct
    from current runner commands; source freshness checks remain enforced.
11. **Acceptance evidence.** Require full unit and local-e2e/combined discovery,
    focused tests, applicable lint, documentation paths, release claims/matrix
    and all required canonical audit gates. Require exact runtime and manual
    evidence for the approved bounded matrix, not an unlimited cross-product.
    Since the baseline failed, require two clean post-fix operational runs,
    at least one on the exact final candidate. Also require exact multi-host
    OpenFaaS and every approved reproduction on the final candidate.
12. **Publication prohibition.** No merge, push, tag, release or publication
    until the final acceptance package and the user's explicit approval.
    Local reviewed commits do not grant publication authority.
13. **Deletion.** No reproduction-driven deletion before the complete candidate
    inventory and one final user scope confirmation. Delete only approved
    out-of-scope behavior or demonstrated duplication, through bounded
    independently reviewed packets; preserve required provenance and evidence.
    Do not remove meaningful tests merely to reduce size.
14. **Document authority.** The plan stack maps authority; this document owns
    policy; configuration and software plans own domain semantics; the
    certification matrix owns factual row status; the concise release handoff
    is subordinate operational context. Phase plans are historical. The old
    post-release roadmap and overhaul dispatcher are retired, not a work queue.

## 3. Core versus modules

The core owns validation, composition, selector/scope resolution, module
contracts, deterministic planning/runtime handoff, state/lock and evidence
contracts. Provider/software/application stacks are modules. In particular,
`qemu` is a provider module and must not be described as core.

Runtime claims require VM-backed or cloud-backed evidence (or host-backed
evidence where the particular gate permits it). Static/parser checks cannot
certify runtime. Intermediate rework milestones may certify bounded module sets
but are not final main replacement releases.

## 4. Factual certification labels

| Label | Meaning |
| --- | --- |
| `core-ready` | Static, unit, parser/repository and runner-contract evidence only. |
| `certified` | The exact row has the evidence required by its matrix gate; candidate freshness is checked separately. |
| `certified-candidate` | Passed previously; needs a fresh candidate run. |
| `ported-unverified` | Code/config exists without current full runtime evidence. |
| `historical` | Preserved legacy input, not a runtime support claim or final scope decision. |
| `deprecated-proposed` | Proposed demotion/removal, requiring scope approval and rationale. |

Do not change row statuses merely because policy or runner identity changed.
Historical old-main config rows and `docs/old_main_parity_issue_seed.md` remain
a complete transitional candidate inventory until the bounded scope review.
Existing local `origin/main` inventory checking stays in place to prevent
unaccounted legacy files, not to require every historical feature before main.

## 5. Exact-candidate acceptance

Freeze one clean locally committed candidate after approved packets/reviews.
Record HEAD, empty status, `git diff main...HEAD --stat` and shortstat.
Before each physical-host run, record source revision/status and verify the
normal-user host prerequisites; there is no dedicated repository sync step.

An operational run must create four new JSONs with six successful executions:
three single-entry smoke results and one three-entry benchmark result. Every
exit code is zero; no timeout, failed or unreachable Ansible host is acceptable.
`operational_regression` has no retained root: inspect its real children
`infra_one_vm`, `software_k8s_two_vm`, `network_netperf_two_vm` and
`benchmark_k8s_resume`.

The exact `qemu_openfaas_image_parity` run must be 1/1 successful, request the
full 26-vCPU shape, select node3 as external physical host, produce the expected
OpenFaaS/benchmark artifacts and retain its VMs. No missing current YAML,
QCOW2 permission error or broad permission repair is acceptable.

Inspect every JSON and every result index: complete stdout/stderr, metadata,
state/lock, benchmark/network artifacts, multi-host placement and limitations.
Present the final branch delta, reproduction/config inventories with zero
unaccounted rows, supported/unsupported boundaries, commands/results,
artifact locations and independent final review. Await explicit publication
approval. The final reproduction inventory still requires user confirmation
before any reproduction-driven deletion; autonomous execution does not waive it.
