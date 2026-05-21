# Continuum Rework Plan Stack (Canonical)

## 1. Purpose

This is the single map for planning authority, sequencing, and synchronization across active refactor docs.

Fast onboarding brief: `docs/rework_kickoff.md`.

## 2. Planning Authority

1. `docs/ansible_restructuring_design.md`
   - Program-level architecture and phase roadmap (A-G).
2. `docs/phase_c_implementation_plan.md`
   - Execution plan for Phase C.
3. `docs/configuration_restructuring_design.md`
   - YAML composition, parsing, validation, normalization contracts.
4. `docs/software_module_architecture_plan.md`
   - Software semantics (module graph, tags, registry constraints, planner behavior).

## 3. Conflict Rules

1. Narrower scope overrides broader scope.
2. Software semantic conflicts resolve to `docs/software_module_architecture_plan.md`.
3. Parser/runtime semantic conflicts resolve to `docs/configuration_restructuring_design.md`.
4. Parent docs must be synchronized after child-plan decision changes.

## 4. Locked Global Decisions

1. Hard cutover:
   - no long-lived dual runtime schema mode,
   - no warning-first compatibility strategy.
2. Infrastructure is cluster-first:
   - `infrastructure.clusters[]` is the canonical topology abstraction,
   - each cluster contains resources and emits `cluster=<id>` on all contained resources.
3. Resource identity is generic and tag-based:
   - resources are identified by numeric ID + tag map,
   - base infra tags are `tier` and `cluster`.
4. Benchmark phase participates in placement:
   - benchmark execution units must use selectors/tags for assignment,
   - benchmark can consume software-produced tags/artifacts via resolved runtime metadata.
5. Internal-first dependency handling:
   - dependency/capability wiring is internal registry logic,
   - user schema has no dependency edge field,
   - dependency strategy is explicit-only (missing requirements hard-fail; no auto-injection).
6. Fail-fast validation:
   - reserved tag collisions are hard errors,
   - selector/cycle/conflict violations are hard errors.
7. Selector/scope semantics are locked:
   - selector language is exact-match only (`match: {k:v}` with implicit AND),
   - selectors use canonical normalized representation + deterministic `selector_id`,
   - scope identities are structured objects for `vm`, `cluster`, `selector`.
8. Target software model:
   - `software.modules[]`,
   - tag-based resource identity,
   - scoped constraints are part of target model semantics (details in software architecture plan).
9. Tag governance includes benchmark lifecycle rule:
   - benchmark must not overwrite `role`,
   - benchmark role semantics use namespaced keys (for example `benchmark.role`).
10. Image prefetch intent is run-scoped with infra execution:
   - user knob is `run.image_prefetch` (`off|on`, default `off`),
   - `infrastructure.image_prefetch` is invalid (hard cutover, no alias),
   - local registry lifecycle stays internal and is activated only when required image pulls exist.
11. Validation boundary is single-pass and early:
   - exhaustive schema/default/type validation happens at parser/bootstrap boundaries,
   - runtime config-access paths should be thin reads over canonical keys (no fallback aliasing/default patching),
   - runtime key/type failures are treated as invariant violations and should crash fast.
12. Config access surface is layered (avoid both magic-index access and getter explosion):
   - keep dedicated helpers for stable structural semantics (for example run targets, orchestrator identity, module/stage lookup),
   - use generic typed parameter access for dynamic config bags (benchmark stage config, module-local config) instead of one function per key,
   - allow key-specific helpers only when they encode cross-cutting semantic meaning (not simple key forwarding).
13. Config-library migration is deferred until post-rework stabilization:
   - no Hydra/OmegaConf or Pydantic migration during active PR-3/PR-4/Phase C delivery,
   - parser/runtime work remains decomposition-first on the current stack,
   - any future library adoption requires a dedicated RFC/ADR and plan-stack synchronization before implementation.
14. Parser decomposition guardrail:
   - `input/configuration/yaml_parser.py` remains an orchestration facade,
   - domain validation logic belongs in dedicated modules,
   - avoid reintroducing monolithic parser growth when extending schema/runtime contracts.

## 5. Execution Dependency Chain

1. Keep software model authoritative (`docs/software_module_architecture_plan.md`).
2. Align configuration/parser/runtime contracts (`docs/configuration_restructuring_design.md`).
3. Execute Phase C against those contracts (`docs/phase_c_implementation_plan.md`).
4. Continue remaining phases (`docs/ansible_restructuring_design.md`).

## 6. Execution Status and Next PRs

1. PR-1 (completed): Parser schema pivot to canonical `infrastructure.clusters[]` + `software.modules[]` validation.
2. PR-2 (completed): Module registry + explicit-only dependency/capability validation baseline is landed; parser/runtime conflict and exclusivity validation coverage is landed with targeted tests.
3. PR-3 (completed): Selector resolution + tag governance + scoped constraint engine baseline.
4. PR-4 (completed): Runtime/planner integration for software placement plus benchmark assignment plumbing that Phase D later consumed when application execution was ungated.
5. PR-5 (completed): Example/profile finalization + tests/smokes + documentation closure, with user-facing schema/migration docs, host-runner isolation, and real host-backed smoke closure landed.

## 7. Decision Traceability Matrix

| ID | Decision | Main Spec | Primary Code Surface | Verification |
| --- | --- | --- | --- | --- |
| D1 | Hard cutover | `docs/rework_plan_stack.md` | `input/input.py`, `input/configuration/yaml_parser.py` | parser/runtime tests |
| D2 | Cluster-first infra topology (`clusters[]`) | `docs/configuration_restructuring_design.md` | infra parser + normalized model | parser + normalization tests |
| D3 | Benchmark placement via selectors/tags | `docs/configuration_restructuring_design.md` | benchmark parser + planner assignment | planner/benchmark tests |
| D4 | Internal dependency wiring, explicit-only strategy | `docs/software_module_architecture_plan.md` | module registry + dependency validator | missing-requirement tests |
| D5 | No user dependency edges | `docs/software_module_architecture_plan.md` | `input/configuration/yaml_parser.py` | schema validation tests |
| D6 | Reserved tag collisions hard-fail | `docs/software_module_architecture_plan.md` | placement/tag validation layer | planner constraint tests |
| D7 | Scoped constraints (`vm/cluster/selector`) | `docs/software_module_architecture_plan.md` | scoped constraint engine | scoped conflict tests |
| D8 | Deterministic planning | `docs/software_module_architecture_plan.md` | selector sort + toposort | deterministic ordering tests |
| D9 | Exact-match selector language + canonical selector identity | `docs/software_module_architecture_plan.md` | selector canonicalizer | parser/planner determinism tests |
| D10 | Structured scope identity records | `docs/software_module_architecture_plan.md` | scoped diagnostic/lockfile writer | scoped diagnostics tests |
| D11 | Benchmark cannot overwrite `role` (`benchmark.role` namespacing) | `docs/software_module_architecture_plan.md` | benchmark tag mutation validator | cross-domain tag governance tests |
| D12 | Run-scoped image prefetch + internal registry lifecycle | `docs/configuration_restructuring_design.md` | `input/configuration/yaml_parser.py`, `infrastructure/image_registry.py`, `infrastructure/infrastructure.py` | parser/runtime registry tests |
| D13 | Layered config access (semantic helpers + generic parameter readers) | `docs/configuration_restructuring_design.md` | `input/configuration/config_access.py`, runtime callers | config-access/runtime regression tests |
| D14 | Hydra/Pydantic migration is post-rework only (deferred policy) | `docs/rework_plan_stack.md` | planning stack (`docs/rework_plan_stack.md`, `docs/ansible_restructuring_design.md`) | post-rework RFC/ADR gate |
| D15 | Parser decomposition guardrail (`yaml_parser` orchestration-only) | `docs/rework_plan_stack.md` | `input/configuration/yaml_parser.py`, `input/configuration/software_domain_validation.py`, `input/configuration/benchmark_domain_validation.py`, `input/configuration/selector_assignment_validation.py`, `input/configuration/run_schema_validation.py`, `input/configuration/infrastructure_schema_validation.py`, `input/configuration/provider_schema_validation.py` | parser decomposition regression tests |

## 8. Synchronization Gate (Per PR)

Before merge:

1. Update the authoritative doc first.
2. Update dependent docs in Section 2.
3. Verify no contradiction with Section 4 decisions.

## 9. Compression Rule for Planning Docs

1. Keep detail once in the authoritative doc; reference elsewhere.
2. Prefer checklists/tables over repeated prose.
3. Keep examples minimal and move edge cases to tests.

## 10. Selector/Scope Closure Status

1. Selector language locked to exact-match `match: {k:v}` with implicit AND.
2. Canonical selector normalization and `selector_id` strategy locked.
3. Canonical structured scope identity format locked for `vm`, `cluster`, and `selector`.

## 11. Current Snapshot (Updated May 20, 2026)

1. PR-1 implementation landed with strict modules-only parser/runtime access (no orchestrator/addons projection path).
2. Config examples and parser/runtime test fixtures are migrated to canonical `clusters[]` + `modules[]` schema.
3. PR-2 implementation is complete with registry-backed dependency/capability validation in parser/runtime and dedicated unit tests.
4. PR-2 incremental hardening includes parser/runtime parity for exclusive-capability/conflict validation with targeted regression tests.
5. PR-3 selector/scope, PR-3A image-prefetch, PR-4 runtime/planner integration, PR-5 docs/smokes, and Phase D application-role consolidation baselines are closed; active follow-up is Phase E resume/state integrity plus operational hardening.
6. The explicit application-runtime gate was removed in Phase D: `run.targets: application` now executes benchmark/application runtime paths, and the resumed benchmark smoke/teardown path has since reached runner-visible closure.
7. Current PR-3A baseline includes deterministic control-plane image requirement resolution for `kubecontrol`/`kube_kata` and internal benchmark-stage mappings for `empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, and `text_translation`, with stack-aware `image_classification` selection and fail-fast unknown-stage handling.
8. PR-4 prep baseline progressed: core then-gated runtime/planner surfaces (including `application/*`) now use generic `benchmark_param*` config accessors instead of removed `workload_*`/legacy sizing helpers, and legacy benchmark/workload helper API stubs are removed from `config_access`.
9. Runtime endpoint env wiring now reads canonical benchmark keys directly (`duration`), with no runtime fallback aliasing from legacy `duration_s`.
10. Parser hardening now includes strict stage-type benchmark config contracts for known stage types, with fail-fast required-key, value-type/range, and unknown-key validation.
11. Config-access strictness is tightened for canonical run/software paths: runtime access now requires `domains.run.image_prefetch` and `domains.software.modules` (no silent fallback defaults), with invariants enforced via fail-fast errors.
12. One-key orchestrator access wrappers are removed (`cache_worker_enabled`, `kube_deployment_mode`, `kube_version`, `runtime_name`) and runtime callers are migrated to generic orchestrator accessors (`orchestrator_value` / `orchestrator_bool`), maintaining parser/bootstrap as the only defaulting boundary.
13. Addon-specific config-access wrappers are removed (`openfaas_enabled`, `observability_enabled`, `endpoint_runtime_enabled`); callsites now use generic addon queries (`has_addon(config, "<addon>")`).
14. Orchestrator comparison wrapper `orchestrator_is(...)` is removed; callsites compare `orchestrator_name(config)` directly.
15. Image-requirement resolver strictness is tightened: no runtime default for control-plane `kube_version`, and canonical normalized infra resources (`normalized.infrastructure.resources`) are required for discovery.
16. Active infra/planner helper surfaces remove remaining runtime fallback defaults (`base`, `ssh_key`, `mode`, `username`, `timestamp`) and now rely on parser/bootstrap invariants with fail-fast behavior; endpoint-runtime install gating uses canonical module assignment metadata rather than aggregate `infrastructure.endpoint_nodes`.
17. Registry endpoint/migration helpers remove infrastructure/SSH fallback maps and now read canonical keys directly (`infrastructure`, `cloud_ssh`/`edge_ssh`/`endpoint_ssh`) with fail-fast errors on missing wiring.
18. Registry prefetch payload handling is tightened as a runtime invariant: registry flows require canonical `prefetch_image_requirements` structure, fail fast on malformed entries, and normalize accepted entries (trimmed/deduplicated owners and tier targets).
19. Image requirement tier-target derivation now depends strictly on parser-derived `resolved_vm_ids` and normalized resource records; missing/invalid VM mappings fail fast (no selector fallback in runtime discovery).
20. Lockfile parsing now enforces derived selector metadata consistency (`selector`, `selector_id`, `resolved_vm_ids`, `scope_identities`) against recomputed selector resolution; missing or mismatched fields fail fast.
21. Lockfile writing for YAML runs now fails fast on missing canonical `normalized`/`infrastructure.base_path` or malformed `normalized.sources` instead of runtime fallback behavior.
22. Decomposition-first parser cleanup has started: legacy runtime projection helpers were extracted from `input/configuration/yaml_parser.py` into `input/configuration/legacy_projection.py` with dedicated unit coverage (`scripts/test/unit/test_legacy_projection.py`), preserving behavior while reducing parser surface area.
23. Benchmark stage config-contract validation was extracted from `input/configuration/yaml_parser.py` into `input/configuration/benchmark_stage_contract.py` with focused unit coverage (`scripts/test/unit/test_benchmark_stage_contract.py`), reducing parser-specific custom logic while preserving fail-fast schema diagnostics.
24. Shared module capability/exclusive/conflict contract evaluation was extracted into `input/configuration/module_contract_validation.py` and adopted by both parser (`yaml_parser`) and runtime wiring surfaces (`runtime_option_validation`), with focused unit coverage in `scripts/test/unit/test_module_contract_validation.py`.
25. Selector-resolution helper extraction expanded in `input/configuration/selector_resolution.py`: it now centralizes `assign_to.match` normalization/canonical selector-id derivation, derived metadata reconciliation (`resolved_vm_ids` + `scope_identities`), and selector-derived field validation/formatting helpers, with focused unit tests (`scripts/test/unit/test_selector_resolution.py`).
26. Run/infrastructure/provider schema validation extraction is in progress: shared validators for `run`, infrastructure topology/network, and provider config moved to dedicated modules (`run_schema_validation.py`, `infrastructure_schema_validation.py`, `provider_schema_validation.py`) with focused coverage in `scripts/test/unit/test_schema_validation.py`.
27. Parser decomposition advanced: software/benchmark/selector-resolution domain checks moved from `input/configuration/yaml_parser.py` into dedicated modules (`software_domain_validation.py`, `benchmark_domain_validation.py`, `selector_assignment_validation.py`), shared validation primitives moved to `input/configuration/validation_utils.py`, and `yaml_parser` is reduced to orchestration wrappers for these domains.
28. Decomposed domain validation now has focused unit coverage in `scripts/test/unit/test_domain_validation.py` for benchmark phase-domain gating and module-type contract failures.
29. Domain-validation decomposition is now direct-by-concern: parser wiring uses `input/configuration/software_domain_validation.py`, `input/configuration/benchmark_domain_validation.py`, and `input/configuration/selector_assignment_validation.py` directly (no extra compatibility facade layer).
30. Runtime wiring decomposition progressed to direct modules: active callsites now use `runtime_phase_targets.py`, `runtime_module_loader.py`, and `runtime_option_validation.py` directly, and the transient `runtime_config.py` compatibility facade was removed.
31. Schema-validation decomposition progressed: parser wiring now uses dedicated modules (`run_schema_validation.py`, `infrastructure_schema_validation.py`, `provider_schema_validation.py`) directly with no behavior drift in parser/runtime regression coverage.
32. YAML parser source/lock plumbing decomposition progressed: YAML I/O and profile resolution moved to `input/configuration/yaml_io.py`, profile composition moved to `input/configuration/profile_composition.py`, and lockfile writing moved to `input/configuration/experiment_lock_writer.py`, with `yaml_parser` retaining orchestration wrappers.
33. Focused unit coverage now includes extracted YAML/profile/lock plumbing modules (`scripts/test/unit/test_yaml_io.py`, `scripts/test/unit/test_profile_composition.py`, `scripts/test/unit/test_experiment_lock_writer.py`) to keep decomposition slices regression-safe.
34. Post-stabilization dead-code audit pass for `input/configuration` removed the transient `runtime_config.py` facade and found no additional unreferenced modules/functions in the active configuration stack.
35. Runtime option normalization now enforces canonical domain scope invariants (`domains.provider.config`, orchestrator module `config`) and no longer mutates missing paths at runtime (`setdefault` fallback removed).
36. Provider option unknown-key rejection is now contract-driven without embedding provider module catalogs in core: `runtime_option_validation` admits core-owned provider keys plus provider-declared keys from `provider.add_options(...)`, while parser schema validation hard-fails unknown `provider.config.ip.*` subkeys.
37. Shared runtime option contracts are now centralized in `input/configuration/runtime_option_contract.py` (core provider keys + provider IP keys), and parser/runtime validators consume those declarations to keep schema/runtime checks discoverable and aligned.
38. Provider schema strictness is tightened at parser boundary: `provider` now rejects unknown top-level keys (allowed: `name`, `config`), while provider config unknown-key enforcement remains interface-driven at runtime option validation.
39. Parser-boundary defaulting now owns canonical `run` and `provider` defaults (`run.dry_run`, `run.clean`, provider core/IP defaults), and `infrastructure.network` is normalized to explicit keys (`emulation`, `wireless_preset`, `overrides`) during schema validation.
40. `legacy_projection.to_legacy_config` now runs as invariant-only projection: it requires canonical normalized paths (no fallback/default patching) and fails fast with explicit missing-path errors when parser/bootstrap invariants are violated.
41. Selector-assignment reconciliation no longer applies normalized-domain fallbacks: `selector_assignment_validation` now requires canonical `run`, `software`, and `infrastructure.resources` paths and fails fast on missing keys instead of substituting empty dict/list defaults.
42. Selector-assignment validation now explicitly enforces benchmark-domain presence for `run.targets` including `application`, preserving the parser-first invariant policy in post-domain reconciliation paths as well.
43. `config_access` now enforces canonical stage/module shape invariants (`id`, `type`, `config` mappings) for benchmark pipeline and software modules, removing silent `.get(...)` fallback behavior from runtime accessors.
44. Config-access callers now fail fast on malformed canonical domain payloads with explicit path errors, while retaining parser-owned defaulting and legacy-helper removal boundaries.
45. Selector-assignment reconciliation now requires canonical selector metadata on each entity (`assign_to.match` and `selector_id`) and no longer falls back to empty selector inputs in post-parse paths.
46. Selector VM resolution now enforces canonical normalized resource records (`vm_id`, `tags`) and fails fast on malformed entries instead of silently skipping them.
47. Software runtime projection/contract validation now requires module `config` mappings at reconciliation time (no post-parse `{}` fallback for orchestrator/addon module configs).
48. Image requirement discovery now enforces canonical module/stage identifiers and normalized infrastructure resource shape, with fail-fast errors for unknown module types and malformed resource records.
49. Parser software-schema validation now requires explicit `software.modules[*].config` presence (mapping), removing parser-side fallback injection for missing module config blocks.
50. Runtime option-scope resolution now fails fast without `None` sentinel fallbacks: provider/resource-manager option paths require canonical domain mappings with explicit missing-scope diagnostics.
51. `config_access.benchmark_param(...)` now fails with explicit canonical-path `ValueError` diagnostics on missing stage config keys (no raw `KeyError` leakage from runtime reads).
52. `config_access.orchestrator_bool(...)` now enforces strict boolean semantics (`bool` or string `true|false`) and fails fast on invalid values instead of permissive truthy coercion.
53. Parser defaulting strictness is tightened for optional mapping fields: explicit `null` in provider/infrastructure/benchmark mapping objects is now rejected (defaults only apply when keys are omitted).
54. Experiment lock/planner snapshots now persist deterministic software execution order, owner-tagged software plan entries, software module assignments, and application-gated benchmark stage assignments.
55. Assignment snapshots now include `resolved_resources` handoff records derived from `normalized.infrastructure.resources`, with each record carrying `vm_id`, `cluster_id`, `tier`, `index_in_cluster`, and tags.
56. Planner snapshot validation is fail-fast for malformed or missing normalized resource records and for assignments that reference unknown `resolved_vm_ids`.
57. PR-4 runtime helper wiring now exposes benchmark-stage planner assignments through `config_access` and passes planner-derived stage handoff metadata through the former gated Kubernetes helper paths without inferring application role topology from a single selector.
58. Software phase endpoint-runtime install gating now uses canonical `endpoint_runtime` module placement (`resolved_vm_ids` mapped through `normalized.infrastructure.resources`) instead of aggregate endpoint node counts.
59. Endpoint-runtime placement is now contract-validated: endpoint resources require an `endpoint_runtime` provider whose assignment resolves to endpoint VM resources, and base-image endpoint install planning uses the same placement predicate as the software phase.
60. Module `requires` checks are now scope-aware in normalized planner validation: a required capability must be provided by a module whose resolved scope overlaps the consumer module, not merely exist elsewhere in the config.
61. Runtime software-phase and base-image endpoint-runtime gating now read software-module placement from `planner_snapshot.software_module_assignments[*].resolved_resources`; deterministic planner snapshot construction still uses canonical pre-snapshot module assignment metadata to avoid circular reads.
62. Parser regression tests mock host-IP socket discovery, keeping full unit/pytest runs sandbox-safe while leaving production host-IP discovery unchanged.
63. Host-IP discovery failure handling is deterministic for OS-level socket denial as well as DNS/socket lookup errors.
64. Planner handoff accessor strictness is tightened: runtime reads reject mismatched `resolved_vm_ids`/`resolved_resources` and malformed scope identity records in planner snapshot assignments.
65. Resolved resource handoff records now enforce base-tag consistency for `tier` and `cluster` tags against the serialized `tier`/`cluster_id` fields.
66. Benchmark handoff consumption now uses canonical primary and pipeline-ordered runtime bundles (`benchmark_stage_handoff` / `benchmark_stage_handoffs`) and passes ids, pipeline indexes, deep-copied stage config, resolved resources, scope identities, tags, and tier counts through the Kubernetes launch-variable path first prepared before Phase D activated application execution.
67. Software-module handoff consumption now uses canonical single-module and module-ordered runtime bundles (`software_module_assignment_handoff` / `software_module_assignment_handoffs`) for planner snapshot reads, and endpoint-runtime install gating consumes tier counts from the single-module bundle instead of raw resource-list counts; software handoffs also carry module indexes and deep-copied module config for Phase-D template preparation, with module-ordered construction keyed by module instance id rather than module type relookup and id-based accessors available for exact module-instance consumers.
68. Runtime structural accessors now reject duplicate benchmark stage ids and duplicate software module ids, so exact-id handoff reads cannot silently select the first duplicate entry when consuming normalized/locked config.
69. Resource-manager module and endpoint helper `start()` hooks now delegate to the centralized `resource_manager.start()` entrypoint, closing the remaining direct-start software execution and endpoint-install bypasses.
70. The former gated Kubernetes launch-variable path now carries a combined `planner_runtime_handoff` payload for ordered software-module and benchmark-stage config/placement metadata, and Phase-D role consolidation consumed that handoff while moving application-specific launch/timing/runtime concerns out of `resource_manager/kubernetes/kubernetes.py`.
71. Historical PR-4 handoff point: PR-5 was the closure slice for examples/smokes/documentation alignment and has since landed.
72. PR-5 now publishes `docs/configuration_reference.md` and `docs/migration_notes.md` as the user-facing canonical-schema and hard-cut migration references, and `docs/cheatsheet.md`, `README.md`, and `configuration/README.md` point to them as the first documentation stops for YAML users.
73. Shipped experiment examples and shipped environment/software profiles are now regression-validated from disk by `scripts/test/e2e/test_example_configs.py`, tightening the example/profile synchronization commitment in this plan stack.
74. PR-5 doc/example cleanup normalized quoted `run.image_prefetch` values in shipped YAML examples and docs, avoiding YAML boolean coercion in the canonical reference baseline.
75. PR-5 e2e-runner cleanup now resolves available suite names from `scripts/test/test_config.json` instead of a hard-coded CLI list, keeping future suite additions configuration-driven.
76. The dedicated `network_validation` suite is now scoped to `configs/experiments/network_validation/`, and the runner docs/manifests/examples are YAML-only rather than split across stale `.cfg` references.
77. PR-5 now publishes dedicated developer-facing docs for the actual runtime execution pipeline and for operational testing strategy, giving the rework a reusable phase model for smoke design, handoff, and later paper/report writing.
78. PR-5 now introduces a dedicated lightweight smoke scenario set under `configs/experiments/smoke/`, making the smoke suite intentionally small and phase-oriented rather than a broad sample of all shipped experiments.
79. PR-5 operational policy now prefers fast-fail smoke execution, retained artifacts, Kubernetes as the canonical software smoke target, and a future resumed benchmark smoke pipeline that reuses VMs across phases instead of reprovisioning for each check.
80. PR-5 now includes a VM debugging runbook and early runtime SSH-hint logging so failed smoke runs can be debugged through retained VMs and host-level QEMU inspection instead of blind reruns.
81. PR-5 now makes VM-backed suite prerequisites executable in the runner itself: `scripts/test/test_config.json` declares required host commands per suite, and `scripts/test/run_tests.py` rejects unsupported local environments before discovery or provisioning starts.
82. PR-5 now exposes that suite contract through the runner CLI as well, so operators can list suite expectations or validate prerequisite readiness before starting a long smoke run.
83. PR-5 now persists runner artifacts in a smoke-debug-friendly shape: each saved run has per-test stdout/stderr/metadata files plus stable failure-class tagging to shorten the triage loop once real VM-backed smoke starts failing.
84. PR-5 now documents and ships a dedicated-user smoke-wrapper model for host execution, making least-privilege VM-backed smoke runs a first-class operational path instead of an undocumented local workaround.
85. PR-5 real host-backed smoke closure is now complete for the currently runnable Phase-C boundaries: `infra_one_vm`, `software_k8s_two_vm`, and `network_netperf_two_vm` all pass through the dedicated `continuum-smoke` wrapper path.
86. The host-backed smoke loop hardened several real runtime seams: parser-backed base-path override success detection, deterministic bounded guest login names, controller-side repo asset paths after the YAML handoff move, flannel manifest sourcing, and YAML-era network-emulation/TC shell-command handling.
87. `.continuum` QEMU base-image reuse is now integrity-gated by companion success metadata, so interrupted or partial base-image builds are invalidated and rebuilt rather than being silently trusted on the next run.
88. PR-5 is complete for its intended scope; the next slice after PR-5 was Phase D application-role consolidation plus resumed K8s benchmark smoke/teardown validation, and that slice is now closed.
89. Early Phase-D prep plus the explicit runtime ungate are now landed in the working tree: application bootstrap/module wiring is enabled again for YAML runs, application-specific launch/timing and Mist/Baremetal worker-runtime helpers began moving from `resource_manager/kubernetes/kubernetes.py` into `application/runtime_helpers.py`, `run.targets: application` now resolves into executable phase-3 runtime flow, and focused runtime tests cover application-only and software-plus-application control flow.
90. Phase-D application-role consolidation and retained K8s benchmark smoke closure are landed: application launch playbooks are thin application-role wrappers, application-owned runtime helpers handle benchmark launch/completion/output, and the dedicated host-backed `benchmark_k8s_resume` path has passed through infrastructure, software, application, and teardown evidence.
91. Phase-E resume integrity now adds a canonical `resume_contract` shared by `experiment_lock.yaml` and `state.json`; the contract covers provider identity/config excluding base/delete intent, normalized topology/resources/network, software modules, software placement, and software execution plan metadata.
92. Lock writing now happens during bootstrap before infrastructure or resume execution, and `state.json` is schema v2 with `kind: ContinuumState`, timestamp, atomic writes, machine data, phase, and persisted resume-contract hash/details.
93. Resume-state loading rejects legacy state, malformed machine data, invalid phase values, incompatible topology/software, and stale resume-contract hashes before resumed software/application work starts.
94. E2E runner success detection now validates lock/state schema and matching resume-contract hashes, adding `state_schema_mismatch` and `resume_contract_mismatch` failure buckets while preserving teardown verification.
95. Network-validation artifacts now follow the base-path runtime artifact
    contract: structured netperf NDJSON is written under
    `<base_path>/.continuum/logs/network_validation/`, and the
    `network_validation` suite validates those results against expected
    latency/throughput profile tolerances.
96. Benchmark-smoke application-leg success detection now requires both
    functional stdout markers and lightweight metric-table evidence, including
    at least one numeric endpoint metric row.
97. Benchmark metric evidence is now persisted as structured Phase-E runtime
    artifacts under `<base_path>/.continuum/logs/benchmark/`, and the
    `benchmark_smoke` suite validates the metric manifest plus CSV table
    sanity before accepting the resumed application leg as successful.

## 12. End-of-Rework Test Closure Commitments

Closed May 21, 2026:

1. Major-function coverage is audited and tracked by
   `scripts/test/coverage_manifest.json`, with the maintenance contract
   documented in `docs/major_function_test_coverage.md`.
2. `scripts/test/unit/test_coverage_manifest.py` keeps the audit live by
   validating audited source paths, major function names, referenced tests, and
   success/fail-fast coverage notes.
3. Test suites are split into dedicated unit and local e2e-regression
   directories:
   - `scripts/test/unit/`
   - `scripts/test/e2e/`
   - shared helpers under `scripts/test/support/`
4. `scripts/test/run_cloud_static_audit.sh` now runs unit and e2e discovery as
   separate required gates before the combined suite.

## 13. End-of-Rework Documentation Closure Commitments

1. Publish consolidated user-facing configuration docs for canonical YAML schema (`run`, `infrastructure`, `provider`, `software.modules`, `benchmark.pipeline`) with complete key/type/default/required semantics.
2. Publish migration notes from removed legacy paths (`workload`, legacy benchmark keys, legacy config-access helpers) with fail-fast equivalents and examples.
3. Publish developer-facing architecture docs for parser/runtime decomposition boundaries and module contracts (including selector/scope identity and image requirement interfaces).
   - landed incrementally via `docs/runtime_execution_pipeline.md` and `docs/operational_testing_strategy.md` in addition to the parser/software design docs.
4. Ensure runnable examples/templates are synchronized with final docs and pass parser validation.
5. Add a final doc-audit pass before rework closure:
   - every major runtime/parser surface has a matching doc reference,
   - no contradictory semantics across planning/design docs,
   - no stale references to removed legacy interfaces.
   - current path-reference enforcement is covered by
     `scripts/test/check_docs_paths.py` and the cloud static audit.
6. After the active rework stabilizes, revisit observability/reproducibility
   packaging as a dedicated design topic:
   - decide whether structured run packages should replace scattered per-feature
     metric files,
   - evaluate durable metric retention and optional time-series database support
     without making the current Phase-E CSV/manifest artifacts the final design.
