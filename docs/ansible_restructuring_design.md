---
name: Ansible restructuring design
overview: "Program-level roadmap for Continuum restructuring: role-driven Ansible execution, phase-based orchestration, and alignment with YAML + software-module architecture."
todos:
  - id: phase-a-foundation
    content: "Phase A: foundation boundaries and shared orchestration helpers"
    status: completed
  - id: phase-b-infra-roles
    content: "Phase B: infrastructure role extraction and repo-driven execution"
    status: completed
  - id: phase-c-rm-roles
    content: "Phase C: software/resource-manager orchestration refactor"
    status: completed
  - id: phase-d-app-roles
    content: "Phase D: application deployment role consolidation"
    status: completed
  - id: phase-e-phase-resume
    content: "Phase E: phase-resume and state integrity hardening"
    status: in_progress
  - id: phase-f-cleanup
    content: "Phase F: legacy removal and CI hardening"
    status: pending
  - id: phase-g-hardening
    content: "Phase G: optional image/build lifecycle hardening"
    status: pending
isProject: false
---

# Ansible Restructuring Design for Continuum

## 0. Authority and Scope

This is the program-level roadmap.
Plan precedence and locked decisions are defined in `docs/rework_plan_stack.md`.

This file owns:

1. phase sequencing (A-G),
2. program-level outcomes,
3. cross-phase dependency boundaries.

## 1. Program Objectives

1. Role-driven Ansible execution from repo sources.
2. Deterministic phase flow (`infrastructure -> software -> application`) with resumable state.
3. Centralized software planning aligned with module-graph architecture.
4. Fail-fast and hard-cutover migration posture.

## 2. Program-Level Problems

1. Legacy cross-layer coupling (infra/software/app).
2. Duplicated Ansible and runtime orchestration logic.
3. Hidden behavior in ad-hoc branches.
4. Planning/code drift across architecture tracks.

## 3. Target Program Architecture

1. Python resolves intent; Ansible executes declarative plans.
2. Clear ownership boundaries:
   - `infrastructure/` for machine provisioning,
   - software planner/runtime boundary for software phase,
   - `application/` for benchmark logic.
3. `roles/` + `playbooks/` are canonical execution assets.
4. Configuration and software semantics are consumed from:
   - `docs/configuration_restructuring_design.md`
   - `docs/software_module_architecture_plan.md`

## 4. Migration Phases

## Phase A: Foundation (Completed)

Done criteria:

1. shared orchestration/state boundaries established,
2. no new ad-hoc orchestration paths.

## Phase B: Infrastructure Roles (Completed)

Done criteria:

1. infra executes from repo assets,
2. infrastructure role/playbook extraction complete,
3. idempotency/lintability baseline established.

## Phase C: Software/Resource Manager Refactor (Completed)

Objectives:

1. centralize software-phase planning/execution,
2. remove legacy software coupling,
3. align runtime behavior with config/software architecture docs.

Execution detail: `docs/phase_c_implementation_plan.md`.

Status snapshot (updated May 20, 2026):

1. PR-1 completed for canonical parser/runtime schema cutover (`infrastructure.clusters[]` + `software.modules[]`).
2. Modules-only software config path is active (no runtime projection for legacy `orchestrator/addons` keys).
3. PR-2 is complete with module registry and explicit-only dependency/capability validation baseline in parser/runtime, including an incremental parser/runtime exclusivity-conflict validation hardening pass with tests.
4. PR-3A aligns image-prefetch intent to `run.image_prefetch` while keeping registry bootstrap/prefetch execution in infrastructure phase.
5. PR-3A baseline includes infra-consumable control-plane image requirement resolution for `kubecontrol`/`kube_kata` plus internal benchmark-stage mappings for `empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, and `text_translation`, including stack-aware `image_classification` selection.
6. Registry/prefetch execution ownership is centralized in `infrastructure/image_registry.py` and consumed directly by provider call sites, including provider-side registry endpoint selection and cache migration.
7. PR-4 runtime software-phase endpoint-runtime gating now consumes planner snapshot software-module resolved-resource metadata, while deterministic planner snapshot construction still uses canonical pre-snapshot module assignment metadata.
8. PR-4 benchmark launch-variable preparation forwarded primary and pipeline-ordered planner-stage handoff metadata (scope identities, tags, resolved resources, and tier counts) through the then-gated Kubernetes path as Phase-D role/template input preparation.
9. PR-4 software launch/base-image preparation now reads endpoint-runtime planner placement through a canonical software-module handoff bundle with tier counts, and software handoff also has a module-ordered bundle for later orchestration consumers.
10. Kubernetes launch-variable preparation forwards a combined `planner_runtime_handoff` payload with ordered software and benchmark config/placement handoff metadata; Phase D has since consumed that handoff with application execution active.
11. Resource-manager module and endpoint helper `start()` hooks now delegate to the centralized `resource_manager.start()` entrypoint, keeping software execution on the planner-mediated playbook layer even for direct module-hook callers.
12. PR-5 now has user-facing configuration and migration reference docs (`docs/configuration_reference.md`, `docs/migration_notes.md`) linked from `docs/cheatsheet.md`, `README.md`, and `configuration/README.md`.
13. PR-5 regression coverage now validates shipped experiment examples plus shipped environment/software profiles from disk, and the example/doc baseline quotes `run.image_prefetch` values to avoid YAML boolean coercion.
14. PR-5 e2e-runner cleanup keeps suite selection configuration-driven (`scripts/test/test_config.json`) and scopes the dedicated network-validation suite to the YAML scenarios under `configs/experiments/network_validation/`.
15. PR-5 now documents the actual runtime execution pipeline and operational testing model in `docs/runtime_execution_pipeline.md` and `docs/operational_testing_strategy.md`, so smoke design and later Phase-D benchmarking work can target explicit runtime boundaries instead of ad hoc end-to-end expectations.

## Phase D: Application Role Consolidation

Objective: standardize application deployment roles/templates and remove remaining duplication.

Phase-D cleanup target: keep benchmark/application launch, timing, worker-output,
and completion concerns under application-owned Python helpers and application
Ansible roles. Resource-manager modules should own platform installation and
generic readiness checks, not benchmark-specific job/runtime behavior.

Current implementation snapshot (updated May 20, 2026):

1. application bootstrap/module wiring is no longer fully gated:
   - the application module now imports during YAML bootstrap for `run.targets: application`,
   - application image selection and benchmark-stage option validation now run again at bootstrap.
2. helper extraction is now application-owned:
   - application-specific Kubernetes launch timing, worker-output collection, pod completion, Mist/Baremetal worker runtime helpers, and shared MQTT worker env/var shaping live in `application/runtime_helpers.py`,
   - `resource_manager/kubernetes/kubernetes.py` is limited to Kubernetes software installation and cluster readiness.
3. runtime execution is now ungated:
   - `input/configuration/runtime_phase_targets.py` no longer blocks Phase-3 execution,
   - `continuum.py` always enters `application.start(runner)` when `run.targets` includes `application`, so missing runnable application modules fail fast instead of becoming a logged skip,
   - the dedicated host-backed benchmark path reached resumed software execution and exposed a retained-topology bug where infra-only QEMU runs had omitted the control-plane VM,
   - that topology bug is now fixed in-repo,
   - guest-side Ansible temp-path handling is now hardened with pinned `ANSIBLE_REMOTE_TMP`,
   - infra-only bootstrap now keeps the orchestrator resource-manager module loaded only when `run.prepare_for_resume: true`, so orchestrator base-image prep is explicit retained-resume intent,
   - retained-resume behavior should not become the long-term meaning of generic infra-only execution,
   - the K8s retained benchmark infrastructure/software/application path has passed on the dedicated host-backed runner.
4. application launch playbooks are now thin role wrappers:
   - `roles/application/k8s_job_deploy` owns Kubernetes Job rendering and optional launch,
   - `roles/application/openfaas_deploy` owns OpenFaaS function rendering, DNAT setup, and deploy execution,
   - legacy `application/*/launch_benchmark_*.yml` paths remain stable for runtime playbook resolution.
5. benchmark-smoke teardown evidence is now runner-visible:
   - `benchmark_smoke` can opt into suite-level success detection with `require_teardown`,
   - when the final application config uses `delete_on_exit: true`, the runner verifies saved QEMU domain names are absent after teardown and reports `teardown_failure` on drift.
6. continuation note:
   - the active resume point is `docs/phase_d_handoff.md`,
   - Phase-E work hardens broader resume/state integrity without reintroducing application behavior into resource-manager modules.

## Phase E: Resume and State Integrity Hardening

Objective: finalize robust phase resume and state validation boundaries.

Current implementation snapshot (updated May 20, 2026):

1. `experiment_lock.yaml` and `state.json` share a canonical `resume_contract`
   derived from provider identity/config, normalized infrastructure topology and
   resources, network settings, software modules, software assignments, and
   software execution plan metadata.
2. The resume contract intentionally excludes phase-local request fields:
   `run.targets`, `run.prepare_for_resume`, cleanup/delete intent, base path,
   and benchmark pipeline content.
3. `continuum.py` writes the resolved lock during bootstrap before provisioning
   or state resume begins, so lock/contract failures stop before VM work.
4. `state.json` is now schema v2 with `kind: ContinuumState`, timestamp,
   `phase_completed`, atomic writes, machine data, and the persisted
   `resume_contract`.
5. Resume rejects legacy state, malformed machine data, invalid phases, and
   stale contract hashes before software/application execution starts.
6. The e2e runner validates lock/state schema and matching resume-contract
   hashes, with `state_schema_mismatch` and `resume_contract_mismatch` failure
   buckets for smoke triage.
7. The e2e runner now also validates structured network-validation NDJSON under
   `<base_path>/.continuum/logs/network_validation/` and lightweight
   benchmark-smoke metric-table evidence for the resumed application leg.

## Phase F: Cleanup and CI Hardening

Objective: remove dead legacy paths and enforce quality gates consistently.

Phase-F test architecture closure tasks:

1. run a unit-test coverage audit for major runtime/planner/parser/infrastructure functions and ensure each major function has one or more unit scenarios (at minimum one success path and one key fail-fast/error path where applicable),
2. separate unit and end-to-end suites into distinct folders for clarity (target structure: `scripts/test/unit/` and `scripts/test/e2e/`),
3. keep shared fixtures/helpers in a common test-support module and wire CI jobs so unit suite is first-class and fast, with e2e as explicit/gated execution.

## Phase G: Optional Lifecycle Hardening

Objective: additional image/build lifecycle robustness after core stabilization.
Forward-looking scope: consolidate module/core extension-point contracts (including image requirement exposure) to avoid interface drift as new internal capabilities are added.
Deferred library track: evaluate optional configuration-library adoption (Pydantic for schema validation and Hydra/OmegaConf for composition) only after Phase C/Phase D/Phase F stabilization, and only via explicit RFC/ADR design review before implementation.

## 5. Program Deliverables

1. Stable role-driven orchestration architecture.
2. Deterministic, resumable runtime phases.
3. Fully synchronized planning stack.
4. Legacy-path removal aligned with locked decisions.
5. Test architecture closure with documented major-function unit coverage and clear unit/e2e suite separation.

## 6. Program Risks and Controls

1. Risk: implementation drift from architecture decisions.
   - Control: plan-stack synchronization gate per PR.
2. Risk: hidden coupling reintroduced incrementally.
   - Control: centralized planning boundaries + strict review checks.
3. Risk: partial migration ambiguity.
   - Control: hard-cutover and fail-fast contracts.

## 7. Program Exit Criteria

1. Active runtime paths use refactored role/planner boundaries.
2. Legacy config/software assumptions are removed from active flow.
3. Planning docs are mutually consistent and reflect implemented behavior.
4. Unit-test coverage audit for major functions is complete and tracked.
5. Unit and e2e tests are organized in separate suite folders.
