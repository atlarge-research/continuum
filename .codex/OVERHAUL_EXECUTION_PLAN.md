# Continuum Overhaul Execution Plan

## Current Branch Snapshot

- Branch: `pr-23-curated`
- Worktree state at latest T10 completion: active uncommitted dispatcher, migration backlog docs, release-disposition docs, T08 docs/test, and proposed patch-bundle files
- Base comparison used for this plan: `main...HEAD`
- High-level changed areas in the current branch:
  - YAML/profile configuration and schema validation
  - runtime planning, state, lock, resume, and selector logic
  - QEMU provider and resource-manager refactors
  - application runtime helpers and module launch paths
  - release evidence, release-matrix, and claim checkers
  - smoke-host runner and cloud-static-audit machinery
  - repo-local Codex skills and rules
- Apparent intent of the overhaul:
  - finish the structured Continuum rework
  - preserve release discipline and evidence-backed claims
  - keep the remaining work split into small bounded tasks for fresh agents
- Already completed work:
  - core YAML/profile parsing and validation machinery exists
  - local M1 evidence and several QEMU parity rows are already recorded
  - dedicated suite catalog and cloud-safe audit entrypoints exist
  - release docs already separate certified, historical, and unverified rows
- Remaining risky or incomplete areas:
  - exact `P-QEMU-10` OpenFaaS parity remains unclaimed and likely blocked by external capacity
  - GCP/AWS rows remain historical without YAML provider profiles or cloud evidence
  - baremetal, kubecontrol, kube_kata, and several application modules remain ported or unverified
  - any runtime/config/playbook change can invalidate release evidence and matrix claims
- Uncommitted changes at latest T10 completion:
  - `.codex/NEXT_AGENT.md`
  - `.codex/OVERHAUL_EXECUTION_PLAN.md`
  - `configuration/README.md`
  - `docs/migration_notes.md`
  - `docs/old_main_parity_issue_seed.md`
  - `docs/release_certification_matrix.md`
  - `docs/smoke_runner_isolation.md`
  - `scripts/test/e2e/test_host_runner_scripts.py`
  - `proposed-codex-changes/`
- Known failing tests at latest T12 review: no required cloud-safe gates failing. Optional release evidence artifact audit and M1 pre-tag readiness checks still report tag-readiness findings because retained artifact paths need certification-host access, the worktree is dirty, and some VM-evidence commits predate runtime-affecting source changes.

## Task Status

| Task ID | Title | Priority | Model | Status | Depends on | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | release-doc-consistency | P0 | small | done | none | `python3 scripts/test/check_release_claims.py`; `python3 scripts/test/check_release_matrix.py` |
| T02 | openfaas-exact-parity-blocker | P0 | strong | done | none | `python3 scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_parity` |
| T03 | cloud-provider-disposition | P1 | medium | done | T01 | release claim/matrix checkers |
| T04 | baremetal-support-disposition | P1 | small | done | T01 | `python3 scripts/test/check_release_claims.py` |
| T05 | kubecontrol-cert-path | P1 | medium | done | T01 | release checkers; targeted tests if code later changes |
| T06 | kube-kata-cert-path | P1 | medium | done | T01 | release checkers; targeted tests if code later changes |
| T07 | uncertified-apps-backlog | P1 | small | done | T01 | `python3 scripts/test/check_release_claims.py` |
| T08 | host-runner-boundary-review | P0 | GPT-5.5 | done | T01 | shell syntax checks; host-runner tests |
| T09 | cloud-static-audit-drift | P1 | small | done | T01 | `scripts/test/run_cloud_static_audit.sh` or targeted audit tests |
| T10 | config-migration-backlog | P2 | small | done | T03 helpful | docs path checker; migration-script tests if touched |
| T11 | planning-file-maintenance | P0 | small | done | none | markdown review only |
| T12 | final-integration-review | P0 | GPT-5.5 | done | T01-T09 | Tier 2 plus Tier 3 only when requested |

## Agent Scheduling Policy

Use these deterministic rules to choose the next task:

1. Select the highest-priority task with status `not started` whose dependencies are all `done`.
2. Prefer `P0` over `P1` over `P2`.
3. Within the same priority, choose the task that unblocks the most other tasks.
4. If still tied, choose the task with the lowest token budget guidance.
5. If still tied, choose tests/docs cleanup before risky refactors.
6. If still tied, choose the smallest file scope.
7. Never choose a task marked `blocked`.
8. Never choose a review task before its implementation dependencies are complete.
9. Never choose final integration until all `P0` and `P1` tasks are done or explicitly deferred.

Recommended model and reasoning effort:

- `small + low`: tasks that read fewer than 4 files and have explicit done criteria
- `small + medium` or `medium + medium`: tasks touching 2 to 8 files with a clear path
- `medium + high` or `strong + high`: failing tests, cross-subsystem behavior, retained state roots, host setup, or compatibility questions
- `GPT-5.5 + high`: security-sensitive work, hard debugging after repeated failures, or cross-subsystem integration
- `GPT-5.5 + xhigh`: architecture, security boundary design, or final integration review only

Escalation rules:

- If the same validation fails twice, mark the task `blocked` and escalate the next attempt one level.
- If the task scope is larger than expected, stop and split it rather than expanding silently.
- If a fix looks suspicious or hacky, hand it to a review task instead of continuing to broaden the implementation.

Parallelization rules:

- Only run tasks in parallel when they edit disjoint files or clearly independent docs/tests.
- Do not run parallel agents on the same file unless one is review-only.
- Do not run parallel agents on security-boundary code and its tests at the same time.

## Validation Tiers

### Tier 0

Very cheap checks to run during local iteration:

- `python3 -m py_compile <changed-python-files>`
- `git diff --check`
- `PYTHONPATH=. python3 -m unittest scripts.test.unit.test_yaml_parser`
- `PYTHONPATH=. python3 -m unittest scripts.test.unit.test_config_access`
- `yamllint -c sysconfig/yamllint.yml <changed-yaml-files>`
- `bash -n scripts/test/run_cloud_static_audit.sh` when shell files change

### Tier 1

Subsystem-level checks and cheap e2e coverage:

- `python3 scripts/test/run_tests.py --list-suites`
- `python3 scripts/test/check_docs_paths.py`
- `python3 scripts/test/check_release_claims.py`
- `python3 scripts/test/check_release_matrix.py`
- focused `unittest` modules under `scripts/test/unit`
- focused `unittest` modules under `scripts/test/e2e`

### Tier 2

Broader validation after a coherent patch set:

- `PYTHONPATH=. python3 -m unittest discover scripts/test/unit`
- `PYTHONPATH=. python3 -m unittest discover scripts/test/e2e`
- `PYTHONPATH=. python3 -m unittest discover scripts/test`
- `scripts/test/run_cloud_static_audit.sh`

### Tier 3

Expensive smoke, host, integration, or release-dependent checks:

- `python3 scripts/test/run_tests.py --suite smoke`
- `python3 scripts/test/run_tests.py --suite benchmark_smoke`
- `python3 scripts/test/run_tests.py --suite network_validation`
- `python3 scripts/test/run_tests.py --suite qemu_infra_parity`
- `python3 scripts/test/run_tests.py --suite qemu_k8s_image_parity`
- `python3 scripts/test/run_tests.py --suite qemu_k8s_nobench_parity`
- `python3 scripts/test/run_tests.py --suite qemu_kubeedge_software_parity`
- `python3 scripts/test/run_tests.py --suite qemu_kubeedge_image_parity`
- `python3 scripts/test/run_tests.py --suite qemu_mist_software_parity`
- `python3 scripts/test/run_tests.py --suite qemu_mist_image_parity`
- `python3 scripts/test/run_tests.py --suite qemu_endpoint_software_parity`
- `python3 scripts/test/run_tests.py --suite qemu_endpoint_image_parity`
- `python3 scripts/test/run_tests.py --suite qemu_openfaas_software_parity`
- `python3 scripts/test/run_tests.py --suite qemu_openfaas_image_local_parity`
- host-backed wrapper scenarios from `docs/release_notes_m1_draft.md`

Future agents should normally run Tier 0 and Tier 1 during implementation, Tier 2 after a coherent patch set, and Tier 3 only when explicitly requested or when the task requires it.

## Task Graph

### Task ID: T01-release-doc-consistency

Status:
- done

Handoff:
- Dispatcher files were activated from `proposed-codex-changes/`.
- No release claim edits were needed; current tracked release docs already agree.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- VM-backed suites were not run.

Type:
- docs

Priority:
- P0

Recommended model:
- small

Scope:
- files/directories to inspect: `docs/release_certification_matrix.md`, `docs/release_notes_m1_draft.md`, `docs/rework_milestone_release_plan.md`, `scripts/test/check_release_claims.py`
- files/directories allowed to edit: the same docs plus `.codex/OVERHAUL_EXECUTION_PLAN.md`
- files/directories not allowed to edit: runtime code, configs, playbooks, roles

Objective:
- keep release claims, matrix rows, evidence docs, and known limitations synchronized

Context to read first:
- `docs/release_certification_matrix.md`
- `docs/release_notes_m1_draft.md`
- `docs/rework_milestone_release_plan.md`
- `scripts/test/check_release_claims.py`

Implementation constraints:
- claim only `certified` or `core-ready` rows
- keep exact `P-QEMU-10` parity unclaimed
- do not widen release scope without evidence

Validation:
- `python3 scripts/test/check_release_claims.py`
- `python3 scripts/test/check_release_matrix.py`
- Tier 1 maximum during normal iteration
- Done means the checker output matches the updated claims or any mismatch is explicitly documented as pre-existing

Expected output:
- docs/status updates only

Done criteria:
- release docs and matrix agree
- no unsupported public claim remains in the edited documents

Dependencies:
- none
- can run in parallel with T03, T04, T05, T06, T07, T09, T10 if they edit disjoint files

Token budget guidance:
- low
- use `rg` for row IDs and avoid broad docs reads

Scheduler metadata:
- Auto-rank: 1
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `small medium`
- Recommended next agent prompt: `Select T01 and synchronize release docs/checkers only.`

### Task ID: T02-openfaas-exact-parity-blocker

Status:
- done

Handoff:
- Exact `P-QEMU-10` remains unclaimed; no certification evidence was added.
- Exact config `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml` keeps the legacy shape: 3 cloud VMs at 6 cores plus 4 endpoint VMs at 2 cores.
- Certified local subsets remain CPU-capped to 4 cloud cores and do not certify parent row `P-QEMU-10`.
- Existing matrix and evidence docs already document the concrete blocker: retained VM/application evidence for the exact 26-core shape requires reachable external QEMU capacity or a larger local runner; the 2026-06-02 exact attempt selected `matthijs@node3` and failed before provisioning with `No route to host`.
- Validation passed: `python3 scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_parity` reported prerequisites satisfied, including the OpenFaaS application registry-cache preflight.
- VM-backed `qemu_openfaas_image_parity` execution was not run.

Type:
- planning
- tests

Priority:
- P0

Recommended model:
- strong

Scope:
- files/directories to inspect: `configs/experiments/parity/qemu_openfaas_image/`, `scripts/test/test_config.json`, `scripts/test/run_smoke_host.sh`, OpenFaaS evidence docs
- files/directories allowed to edit: docs and config files only if the blocker wording needs to be narrowed
- files/directories not allowed to edit: broad runtime refactors, unrelated modules

Objective:
- determine whether exact `P-QEMU-10` can be certified or must remain blocked

Context to read first:
- `docs/release_evidence_qemu_openfaas_software_2026-06-02.md`
- `docs/release_evidence_qemu_openfaas_image_local_2026-06-02.md`
- `docs/release_certification_matrix.md`

Implementation constraints:
- do not weaken the exact legacy resource-shape claim
- do not replace exact row with the local CPU-capped subset

Validation:
- `python3 scripts/test/run_tests.py --check-prereqs --suite qemu_openfaas_image_parity`
- Tier 3 only if host capacity is available
- Done means fresh evidence exists or the blocker is documented with a concrete capacity requirement

Expected output:
- blocker status or fresh evidence docs

Done criteria:
- exact row certified with evidence, or blocked with a concrete external-capacity requirement

Dependencies:
- none
- blocks T12

Token budget guidance:
- medium
- avoid reading all runner code

Scheduler metadata:
- Auto-rank: 2
- Blocks: T12
- Parallel-safe: no
- Escalation target: `GPT-5.5 high`
- Recommended next agent prompt: `Investigate only exact OpenFaaS parity blocker.`

### Task ID: T03-cloud-provider-disposition

Status:
- done

Handoff:
- Confirmed current YAML environment profiles under `configs/profiles/environment/` are local QEMU only; no GCP or AWS YAML environment profile exists.
- Confirmed legacy GCP/AWS test cfgs under `configuration/tests/gcp/` and `configuration/tests/aws/01_infraonly-cloud.cfg` still carry blank region/zone/project/credential fields and cannot support a release claim without external cloud setup.
- Kept all GCP rows `P-GCP-01` through `P-GCP-10` and AWS row `P-AWS-01` at `historical`.
- Tightened each GCP/AWS matrix Certification Action to a bounded path: remain unclaimed for M1; later certification requires a provider-specific YAML environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or a final historical/deprecated disposition.
- Updated `docs/old_main_parity_issue_seed.md` so the issue seeds are concrete and the matrix action snapshots exactly mirror the release matrix.
- Updated the GCP/AWS module backlog requirements to keep both providers release-unsupported for M1 until the same cloud-profile, docs, evidence, or final-disposition gate is satisfied.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `git diff --check`.
- No runtime code, credentials, cloud execution, or VM-backed suites were touched.

Type:
- planning
- docs

Priority:
- P1

Recommended model:
- medium

Scope:
- files/directories to inspect: provider docs, `configs/profiles/environment/`, GCP/AWS legacy config references, matrix rows
- files/directories allowed to edit: docs only unless a later implementation task is split
- files/directories not allowed to edit: runtime code

Objective:
- decide and document port versus historical versus deprecated disposition for GCP/AWS rows

Context to read first:
- `docs/release_certification_matrix.md`
- `configuration/tests/gcp/`
- `configuration/tests/aws/01_infraonly-cloud.cfg`

Implementation constraints:
- no public cloud support claim without credentials, cost, prerequisite docs, and cloud-backed evidence

Validation:
- release claim and matrix checkers
- Tier 1 maximum
- Done means every GCP/AWS row has a bounded next action or explicit historical status

Expected output:
- docs/status updates only

Done criteria:
- every GCP/AWS historical row has a next action and no unsupported claim remains

Dependencies:
- T01
- can run in parallel with T04, T05, T06, T07, T09

Token budget guidance:
- low

Scheduler metadata:
- Auto-rank: 4
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `medium medium`
- Recommended next agent prompt: `Resolve cloud-provider row dispositions only.`

### Task ID: T04-baremetal-support-disposition

Status:
- done

Handoff:
- Inspected `infrastructure/baremetal/baremetal.py` and the release matrix baremetal backlog row.
- Baremetal remains `ported-unverified`; no M1 host-support claim was added.
- Confirmed no baremetal YAML profile or legacy `configuration/tests/` row was identified.
- Documented the current implementation boundary in `docs/release_certification_matrix.md`: one physical-machine shape with one cloud role plus endpoint roles, and edge roles explicitly rejected.
- Tightened the public-claim gate: later certification needs an explicit supported topology, YAML config/profile, host prerequisites, host-backed evidence, documented limitations, or a final historical/deprecation decision.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `git diff --check`.
- No runtime code, host execution, or VM-backed suites were touched.

Type:
- planning
- docs

Priority:
- P1

Recommended model:
- small

Scope:
- files/directories to inspect: `infrastructure/baremetal/`, matrix docs
- files/directories allowed to edit: docs only unless a later split is approved
- files/directories not allowed to edit: runtime code

Objective:
- define whether baremetal is ported-unverified, historical, or a future certification target

Context to read first:
- `infrastructure/baremetal/baremetal.py`
- `docs/release_certification_matrix.md`

Implementation constraints:
- no host-support claim without explicit prerequisites and evidence

Validation:
- `python3 scripts/test/check_release_claims.py`
- Tier 1 maximum
- Done means the baremetal row has a clear bounded next action

Expected output:
- docs/status update

Done criteria:
- baremetal disposition is clear and bounded

Dependencies:
- T01
- parallel-safe yes

Token budget guidance:
- low

Scheduler metadata:
- Auto-rank: 5
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `small medium`
- Recommended next agent prompt: `Clarify baremetal disposition only.`

### Task ID: T05-kubecontrol-cert-path

Status:
- done

Handoff:
- Inspected `resource_manager/kubecontrol/kubecontrol.py`, `resource_manager/plans.py`, `application/empty/empty.py`, representative legacy cfg `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`, current YAML inventories, and related kubecontrol tests.
- Kept `kubecontrol` `ported-unverified`; no runtime support claim was added.
- Documented the smallest first certification target in `docs/release_certification_matrix.md`: a local-QEMU YAML equivalent of a minimal legacy control-plane benchmark such as `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`, scoped to `kubecontrol` plus `empty`, `cloud_nodes >= 2`, `edge_nodes = 0`, valid endpoint-to-worker distribution, documented control-plane image prefetch, and retained evidence for cluster readiness, metrics collection, application success, and artifacts.
- Confirmed no current kubecontrol YAML profile, suite, or retained release evidence was identified.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_module_registry scripts.test.unit.test_resource_manager_plans` ran 25 tests.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime.ImagePrefetchFlowTests.test_resolve_prefetch_requirements_kubecontrol_control_plane_images`.
- Validation passed: `git diff --check`.
- Two earlier targeted single-test invocations used incorrect unittest dotted paths and failed with loader `AttributeError`; the corrected `ImagePrefetchFlowTests` selector above passed.
- No runtime code, VM-backed suites, or host-backed wrapper execution were touched.

Type:
- planning
- tests

Priority:
- P1

Recommended model:
- medium

Scope:
- files/directories to inspect: `resource_manager/kubecontrol/`, `application/empty/`, related roles/playbooks/configs
- files/directories allowed to edit: docs or split follow-up tasks only
- files/directories not allowed to edit: unrelated Kubernetes core

Objective:
- define the smallest certifiable kubecontrol module set

Context to read first:
- `resource_manager/kubecontrol/kubecontrol.py`
- `resource_manager/plans.py`
- `docs/release_certification_matrix.md`

Implementation constraints:
- avoid broad runtime refactor
- preserve legacy compatibility unless explicitly deprecated

Validation:
- release checkers
- targeted tests if code later changes
- Tier 1 maximum for planning

Expected output:
- docs task split or implementation plan

Done criteria:
- an implementation/test task exists for kubecontrol, or the row remains explicitly unclaimed

Dependencies:
- T01
- parallel-safe yes with T06/T07 if file scopes do not overlap

Token budget guidance:
- medium

Scheduler metadata:
- Auto-rank: 6
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `strong high`
- Recommended next agent prompt: `Define kubecontrol certification path.`

### Task ID: T06-kube-kata-cert-path

Status:
- done

Handoff:
- Inspected `resource_manager/kube_kata/kube_kata.py`, `application/empty_kata/empty_kata.py`, `roles/resource_manager/kata_containers/tasks/main.yml`, `roles/resource_manager/kata_containers/defaults/main.yml`, `playbooks/resource_manager/kata_setup.yml`, representative legacy Kata cfg `configuration/experiment_kata/1_startup_performance/strong_scalability/node_1_kata_qemu_overlayfs.cfg`, and the release matrix.
- Kept `kube_kata` `ported-unverified`; no Kata runtime support claim was added.
- Documented the bounded certification path in `docs/release_certification_matrix.md`: a local-QEMU YAML equivalent of a minimal legacy Kata startup benchmark, scoped to `kube_kata` plus `empty_kata`, with `cloud_nodes >= 2`, `edge_nodes = 0`, explicit `runtime` and `runtime_filesystem`, host prerequisites for nested virtualization/containerd/Kata support, documented `kata-fc` plus `overlayfs` exclusion, control-plane image prefetch, and retained evidence for cluster readiness, Kata runtime-class installation, application success, Kata trace/artifact output, and cleanup.
- Confirmed no current kube_kata YAML profile, suite, host prerequisite doc, or retained release evidence was identified.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_module_registry scripts.test.unit.test_resource_manager_plans` ran 25 tests.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_application_runtime_helpers` ran 29 tests.
- Validation passed: `git diff --check`.
- No runtime code, Kata host setup, network downloads, VM-backed suites, or host-backed wrapper execution were touched.

Type:
- planning
- tests

Priority:
- P1

Recommended model:
- medium

Scope:
- files/directories to inspect: `resource_manager/kube_kata/`, `application/empty_kata/`, Kata roles/playbooks
- files/directories allowed to edit: docs or split follow-up tasks only
- files/directories not allowed to edit: unrelated Kubernetes core

Objective:
- define host prerequisites, minimal YAML config, and evidence path for kube_kata

Context to read first:
- `resource_manager/kube_kata/kube_kata.py`
- `roles/resource_manager/kata_containers/tasks/main.yml`
- `docs/release_certification_matrix.md`

Implementation constraints:
- Kata host/runtime requirements are security and host sensitive
- avoid unsupported claims

Validation:
- targeted unit tests or prereq docs if code later changes
- Tier 1 maximum during planning

Expected output:
- docs/task split

Done criteria:
- bounded cert path or documented deferral

Dependencies:
- T01
- parallel-safe yes

Token budget guidance:
- medium

Scheduler metadata:
- Auto-rank: 7
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `strong high`
- Recommended next agent prompt: `Define kube_kata certification path.`

### Task ID: T07-uncertified-apps-backlog

Status:
- done

Handoff:
- Inspected `application/text_translation/text_translation.py`, `application/stress/stress.py`, `application/mem_usage/mem_usage.py`, `application/empty/empty.py`, `application/empty_kata/empty_kata.py`, related legacy config references, and the release matrix.
- Kept all five app modules `ported-unverified`; no application support claim was added.
- Split the previous grouped app backlog row in `docs/release_certification_matrix.md` into individual rows for `text_translation`, `empty`, `empty_kata`, `stress`, and `mem_usage`.
- Documented `text_translation` as requiring a supported-orchestrator YAML config with endpoint resources, publisher/subscriber success checks, artifacts, and VM-backed evidence before any claim.
- Documented `empty` as tied to the future kubecontrol certification path and `empty_kata` as tied to the future kube_kata certification path.
- Documented unresolved `stress` and `mem_usage` scope: current validators require `kubecontrol`, while legacy resource-usage cfgs also reference Kata variants; certification must first decide kubecontrol-only versus a separate Kata-compatible implementation path.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `git diff --check`.
- No runtime code, VM-backed suites, or host-backed wrapper execution were touched.

Type:
- planning
- docs

Priority:
- P1

Recommended model:
- small

Scope:
- files/directories to inspect: app module dirs for `text_translation`, `stress`, `mem_usage`, `empty`, `empty_kata`
- files/directories allowed to edit: matrix/docs only
- files/directories not allowed to edit: runtime code

Objective:
- convert uncertified app modules into individual implementation or evidence tasks, or defer them explicitly

Context to read first:
- `docs/release_certification_matrix.md`
- app module entry files

Implementation constraints:
- no app support claim without config, success detector, and evidence

Validation:
- `python3 scripts/test/check_release_claims.py`
- Tier 1 maximum

Expected output:
- docs task split

Done criteria:
- every app has a disposition and next action

Dependencies:
- T01
- parallel-safe yes

Token budget guidance:
- low

Scheduler metadata:
- Auto-rank: 8
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `small medium`
- Recommended next agent prompt: `Classify uncertified application backlog.`

### Task ID: T08-host-runner-boundary-review

Status:
- done

Handoff:
- Reviewed `scripts/test/setup_agent_host.sh`, `scripts/test/run_smoke_host.sh`, `docs/agent_sudo_boundaries.md`, and `docs/smoke_runner_isolation.md` for the sudo helper boundary, retained state roots, hostctl replacement contract, and installed wrapper command surface.
- No boundary-code change was made; sudo allowlists and isolation behavior were not broadened.
- Fixed one docs ambiguity: `docs/smoke_runner_isolation.md` now lists the already-supported `qemu_openfaas_image_local_parity` wrapper value in the Section 6 installed-wrapper contract.
- Added a focused e2e guard so the wrapper contract keeps listing both OpenFaaS image parity wrapper values.
- Validation passed: `sh -n scripts/test/setup_agent_host.sh`.
- Validation passed: `sh -n scripts/test/run_smoke_host.sh`.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_host_runner_scripts` ran 39 tests.
- Validation passed: `python3 scripts/test/check_docs_paths.py` reported `TOTAL_MISSING_REFERENCES=0`.
- VM-backed suites and host-backed wrapper execution were not run.

Type:
- security
- review

Priority:
- P0

Recommended model:
- GPT-5.5

Scope:
- files/directories to inspect: `scripts/test/setup_agent_host.sh`, `scripts/test/run_smoke_host.sh`, `docs/agent_sudo_boundaries.md`, `docs/smoke_runner_isolation.md`
- files/directories allowed to edit: docs or tests only unless a smaller hardening task is split
- files/directories not allowed to edit: broad runtime code, unrelated runner areas

Objective:
- review privilege boundaries, sudo helper contracts, retained state roots, and host-runner isolation

Context to read first:
- the two scripts and two docs listed above

Implementation constraints:
- do not broaden sudo allowlists
- do not weaken isolation
- do not edit both the boundary code and its tests in parallel

Validation:
- shell syntax checks
- host-runner unit/e2e tests
- Tier 1 during normal iteration
- Tier 3 only on host-backed verification

Expected output:
- review findings or a small hardening task split

Done criteria:
- no untracked security ambiguity remains, or follow-up tasks are created

Dependencies:
- T01
- blocks T12

Token budget guidance:
- high

Scheduler metadata:
- Auto-rank: 3
- Blocks: T12
- Parallel-safe: no
- Escalation target: `GPT-5.5 xhigh`
- Recommended next agent prompt: `Security-review host runner boundaries only.`

### Task ID: T09-cloud-static-audit-drift

Status:
- done

Handoff:
- Inspected `scripts/test/run_cloud_static_audit.sh`, `scripts/test/e2e/test_cloud_static_audit_script.py`, `scripts/test/unit/test_check_release_pretag.py`, the audit skill, and release-matrix gate constants.
- No audit code/test/docs patch was needed: required gate titles in the script still match `check_release_matrix.REQUIRED_CLOUD_AUDIT_GATES`, and release evidence/pre-tag readiness checks remain informational rather than required.
- Full cloud-safe audit passed all required gates and wrote ignored report `logs/cloud_static_audit/cloud_static_audit_2026-07-02T094451Z.md`.
- Audit report required gates passed: compile sweep, cloud audit shell syntax, smoke wrapper shell syntax, host setup shell syntax, git diff whitespace, unit/e2e/combined unittest discovery, docs path check, public release-claims check, release certification matrix check, and configured suite catalog.
- Informational release evidence artifact audit and M1 pre-tag readiness check still reported findings, which is expected for this policy and did not fail the audit.
- Validation passed: `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_cloud_static_audit_script scripts.test.unit.test_check_release_pretag` ran 36 tests.
- Validation passed: `bash -n scripts/test/run_cloud_static_audit.sh`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `scripts/test/run_cloud_static_audit.sh` exited 0.
- Validation passed: `git diff --check`.
- No VM-backed suites or host-backed wrapper execution were run.

Type:
- tests
- cleanup

Priority:
- P1

Recommended model:
- small

Scope:
- files/directories to inspect: `scripts/test/run_cloud_static_audit.sh`, audit skill, related unit/e2e tests
- files/directories allowed to edit: audit/test docs if needed
- files/directories not allowed to edit: runtime code unless a drift fix is unavoidable

Objective:
- ensure static audit still matches release gate policy and does not overclaim optional findings

Context to read first:
- `scripts/test/run_cloud_static_audit.sh`
- `scripts/test/e2e/test_cloud_static_audit_script.py`
- `scripts/test/unit/test_check_release_pretag.py`

Implementation constraints:
- required gates remain compile, shell syntax, diff check, unittest discovery, docs path check, release claim check, release matrix check, and suite catalog

Validation:
- targeted audit tests
- optionally `scripts/test/run_cloud_static_audit.sh`
- Tier 2 maximum

Expected output:
- tests/docs update or summary

Done criteria:
- audit policy and script agree

Dependencies:
- T01
- parallel-safe yes

Token budget guidance:
- low

Scheduler metadata:
- Auto-rank: 9
- Blocks: T12
- Parallel-safe: yes
- Escalation target: `medium medium`
- Recommended next agent prompt: `Check cloud static audit drift.`

### Task ID: T10-config-migration-backlog

Status:
- done

Handoff:
- Inventoried legacy `.cfg` surfaces under `configuration/`: 259 files across root examples, parity tests, network/cellular/latency sweeps, kubecontrol, Kata, provider/serverless/observability, model, and research/demo groups.
- Added a grouped backlog to `docs/migration_notes.md` that keeps legacy files preserved, separates already-certified QEMU parity YAML from exact full `P-QEMU-10`, keeps GCP/AWS historical until provider profiles/docs/evidence exist, ties kubecontrol and kube_kata to their minimal future certification targets, and marks broad research/demo sweeps as historical unless a scoped release scenario is nominated.
- Documented that `scripts/migrate_cfg_to_yaml.py` remains a bootstrap/review aid only because it still emits legacy-shaped `workload`, `software.orchestrator`, and `software.addons` fields rather than canonical `benchmark.pipeline` and `software.modules[]`.
- Added a pointer from `configuration/README.md` to the new grouped backlog section.
- No legacy `.cfg` files, runtime code, converter code, configs, playbooks, roles, VM-backed suites, or release claims were changed.
- Validation passed: `python3 scripts/test/check_docs_paths.py` reported `TOTAL_MISSING_REFERENCES=0`.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `git diff --check`.

Type:
- cleanup
- docs

Priority:
- P2

Recommended model:
- small

Scope:
- files/directories to inspect: `configuration/`, `configs/`, `scripts/migrate_cfg_to_yaml.py`, migration docs
- files/directories allowed to edit: docs only unless a later implementation task is split
- files/directories not allowed to edit: runtime code

Objective:
- list remaining legacy `.cfg` surfaces needing YAML migration, historical preservation, or deprecation

Context to read first:
- `docs/migration_notes.md`
- `configuration/README.md`
- `scripts/migrate_cfg_to_yaml.py`

Implementation constraints:
- preserve legacy files unless removal is explicitly approved

Validation:
- docs path checker
- migration-script tests if touched
- Tier 1 maximum

Expected output:
- backlog docs/status

Done criteria:
- migration backlog is grouped and bounded

Dependencies:
- T03 helpful but not required
- parallel-safe yes

Token budget guidance:
- medium

Scheduler metadata:
- Auto-rank: 10
- Blocks: none
- Parallel-safe: yes
- Escalation target: `medium medium`
- Recommended next agent prompt: `Inventory legacy config migration backlog.`

### Task ID: T11-planning-file-maintenance

Status:
- done

Handoff:
- Confirmed completed tasks T01, T02, and T08 have explicit status and compact handoff notes.
- Updated the task table to mark T11 done for this maintenance pass.
- Updated the branch snapshot to reflect the current uncommitted dispatcher/T08/proposed-bundle state instead of the original clean inspection state.
- Validation passed: markdown review of `.codex/OVERHAUL_EXECUTION_PLAN.md` and `.codex/NEXT_AGENT.md`.
- Validation passed: `git diff --check`.
- No runtime code, release claims, or VM-backed suites were touched.

Type:
- planning

Priority:
- P0

Recommended model:
- small

Scope:
- files/directories to inspect: `.codex/OVERHAUL_EXECUTION_PLAN.md`, `.codex/NEXT_AGENT.md`
- files/directories allowed to edit: the same two files
- files/directories not allowed to edit: runtime code

Objective:
- keep task statuses, handoff notes, and auto-selection metadata current after each task

Context to read first:
- both `.codex` files

Implementation constraints:
- no runtime edits

Validation:
- markdown review
- no tests required unless a docs checker later covers `.codex`

Expected output:
- status/handoff update

Done criteria:
- each completed task has a status and compact handoff

Dependencies:
- none
- recurring

Token budget guidance:
- low

Scheduler metadata:
- Auto-rank: recurring
- Blocks: all coordination
- Parallel-safe: no
- Escalation target: `small medium`
- Recommended next agent prompt: `Update dispatcher files only.`

### Task ID: T12-final-integration-review

Status:
- done

Handoff:
- Final review selected under `GPT-5.5 + xhigh`; current model/effort was acceptable.
- Confirmed all T12 dependencies T01 through T09 are marked done. T10 remains `P2` and not a final-review dependency.
- Release claims remain evidence-bound: exact full `P-QEMU-10` stays `ported-unverified` and unclaimed, GCP/AWS rows stay historical and unclaimed, and baremetal, kubecontrol, kube_kata, `text_translation`, `empty`, `empty_kata`, `stress`, and `mem_usage` stay `ported-unverified` and unclaimed.
- Final blockers before any tag remain outside the docs consistency gate: the current source tree is dirty, retained artifact checks need certification-host access to `/mnt/sdc/continuum_smoke`, and pre-tag readiness still reports VM-evidence commit mismatches for runtime-affecting paths. Refresh affected VM-backed wrapper evidence and rerun `release-artifact-audit` plus `check_release_pretag.py` on the certification host before tagging.
- Validation passed: `env PYTHONPATH=. python3 -m unittest discover scripts/test/unit` ran 623 tests.
- Validation passed: `env PYTHONPATH=. python3 -m unittest discover scripts/test/e2e` ran 93 tests.
- Validation passed: `env PYTHONPATH=. python3 -m unittest discover scripts/test` ran 716 tests.
- Validation passed: `scripts/test/run_cloud_static_audit.sh` exited 0 and wrote ignored report `logs/cloud_static_audit/cloud_static_audit_2026-07-02T101440Z.md`; all required gates passed.
- Validation passed: `python3 scripts/test/check_release_claims.py` reported `TOTAL_RELEASE_CLAIM_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_release_matrix.py` reported `TOTAL_RELEASE_MATRIX_ISSUES=0`.
- Validation passed: `python3 scripts/test/check_docs_paths.py` reported `TOTAL_MISSING_REFERENCES=0`.
- Validation passed: `git diff --check`.
- Tier 3 VM-backed suites and host-backed wrapper scenarios were not run.

Type:
- review
- release
- security

Priority:
- P0

Recommended model:
- GPT-5.5

Scope:
- files/directories to inspect: final diffs, release docs, validation evidence, `.codex` plan
- files/directories allowed to edit: final docs/status only unless a smaller split is required
- files/directories not allowed to edit: broad runtime refactors

Objective:
- perform the final consistency pass before tagging or handoff

Context to read first:
- `git diff main...HEAD --stat`
- `docs/release_certification_matrix.md`
- `docs/release_notes_m1_draft.md`
- `.codex/OVERHAUL_EXECUTION_PLAN.md`

Implementation constraints:
- no broad refactors
- do not certify rows without evidence

Validation:
- Tier 2 plus Tier 3 only when explicitly requested

Expected output:
- review findings, final blockers, or a ready summary

Done criteria:
- all P0/P1 tasks are done or explicitly deferred
- validation evidence is recorded

Dependencies:
- T01, T02, T03, T04, T05, T06, T07, T08, T09

Token budget guidance:
- high

Scheduler metadata:
- Auto-rank: final only
- Blocks: release
- Parallel-safe: review only
- Escalation target: `GPT-5.5 xhigh`
- Recommended next agent prompt: `Run final integration review only.`

## Token Discipline Policy

- Avoid reading unrelated files.
- Avoid repeated full-suite runs.
- Avoid broad refactors when a bounded fix or docs update is enough.
- Prefer `rg`, `git diff`, and targeted tests over repo-wide scans.
- Summarize long logs with `tail`, `grep`, or selected excerpts instead of dumping everything.
- Update durable files such as this plan, release docs, and checkers instead of relying on chat memory.
- Ask the human only when blocked by real ambiguity, external credentials, or unavailable environment capacity.
- Otherwise make the best bounded change you can prove with targeted validation.
