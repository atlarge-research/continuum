# Phase C Implementation Plan (Authoritative Execution Plan)

## 0. Authority and Scope

This is the execution plan for Phase C.
Authority/precedence is defined in `docs/rework_plan_stack.md`.

When conflicts occur, follow:

1. software semantics: `docs/software_module_architecture_plan.md`
2. parser/runtime semantics: `docs/configuration_restructuring_design.md`

## 1. Objective

Finalize software-phase orchestration boundaries and remove legacy coupling while staying aligned with target cluster-first configuration/software architecture, including selector-based benchmark assignment plumbing.

## 2. Scope

In scope:

1. centralized software planner/executor hardening,
2. RM/software role-playbook cleanup,
3. legacy software-path removal,
4. runtime/config contract alignment needed for Phase C correctness.

Out of scope:

1. full Phase D application-role consolidation,
2. broad non-software cleanup beyond Phase C needs,
3. feature expansion unrelated to software-phase architecture.

## 3. Phase C Definition of Done

1. Software phase executes through one centralized planner boundary.
2. No implicit endpoint software installation side path remains.
3. No standalone legacy execution-model phase path remains.
4. Software behavior is driven by canonical config contracts.
5. Phase-C tests/smokes cover active software scenarios.

## 4. Workstreams

## A. Planner Boundary Consolidation

Tasks:

1. finalize centralized plan construction/execution ownership,
2. remove software execution shortcuts bypassing planner,
3. keep post-phase hooks planner-mediated.

Exit criteria:

1. single runtime entrypoint for software execution,
2. no hidden install side paths.

## B. Resource Manager Role/Playbook Cleanup

Tasks:

1. keep `playbooks/resource_manager/` as canonical software install layer,
2. remove stale legacy playbook references,
3. verify idempotent/lintable software playbooks.

Exit criteria:

1. software phase no longer calls deprecated playbook paths.

## C. Runtime/Config Contract Hardening

Tasks:

1. keep runtime decisions on canonical config access boundaries,
2. enforce phase-aware validation semantics,
3. normalize `infrastructure.clusters[]` into generic tagged resource records,
4. ensure provisioning output includes base tags (`tier`, `cluster`) for all resources,
5. enforce explicit endpoint-runtime software intent,
6. model image prefetch intent at `run.image_prefetch` (`off|on`, default `off`) with hard-cut validation,
7. reject `infrastructure.image_prefetch` without compatibility aliases,
8. keep image registry lifecycle internal and infrastructure-executed based on resolved required images.
9. keep registry/prefetch orchestration centralized in `infrastructure/image_registry.py` and referenced directly by provider flows.
10. remove dormant runtime `workload` option plumbing; application module option wiring/verification remains explicit Phase-D gate only.
11. harden runtime/bootstrap fail-fast paths (invalid provider, host-IP discovery, and missing provider-side registry endpoint IPs) so misconfiguration exits are deterministic and test-covered.
12. enforce single-pass validation architecture: parser/bootstrap performs schema/default/type checks; runtime accessors use canonical keys directly without fallback/default patching.
13. enforce layered config-access architecture: use semantic structural helpers for stable domains and generic typed parameter readers for dynamic config bags; block new per-key forwarding getters unless they add semantic meaning.

Exit criteria:

1. invalid phase/config combinations fail fast,
2. runtime behavior matches parser contract,
3. cluster/resource tagging is deterministic and complete,
4. image prefetch mode semantics are deterministic (`off` if-missing with repo+tag checks, `on` force refresh) with no legacy branches.
5. registry endpoint migration commands fail fast on pull/save/load/push errors to avoid partial cache state.
6. new runtime config access additions follow layered-access rules (no one-helper-per-key growth for dynamic parameter spaces).

## D. Legacy Coupling Removal

Tasks:

1. remove remaining execution-model coupling,
2. remove obsolete compatibility branches conflicting with hard-cutover policy.

Exit criteria:

1. no active software path depends on retired architecture concepts.

## E. Verification and Regression Safety

Tasks:

1. maintain focused unit tests for config/parser/runtime/software planning,
2. maintain targeted software smoke checks,
3. keep examples/fixtures aligned with active semantics.

Exit criteria:

1. Phase-C relevant tests pass,
2. core software scenarios parse and trigger expected planner behavior.

## F. Selector and Benchmark Assignment Plumbing

Tasks:

1. share selector resolution plumbing across software and benchmark domains,
2. implement selector canonicalization and deterministic `selector_id` generation,
3. emit structured scope identity records (`vm`, `cluster`, `selector`) for diagnostics/lock metadata,
4. ensure benchmark assignment can consume software-generated tags/artifacts,
5. enforce benchmark tag governance (`benchmark.role` namespacing; no `role` overwrite),
6. persist assignment-relevant metadata in lock artifacts.

Exit criteria:

1. benchmark selector resolution is deterministic,
2. scoped diagnostics use canonical scope identity records,
3. software-to-benchmark handoff is test-covered at parser/planner level.

## 5. PR Slice Sequence

1. Slice 1: planner boundary consolidation + test stabilization.
2. Slice 2: runtime/config contract hardening for `clusters[]` normalization, base tagging, and `run.image_prefetch` cutover.
3. Slice 3: selector plumbing for software + benchmark assignment.
4. Slice 4: RM role/playbook cleanup + legacy coupling removal.
5. Slice 5: final regression + lockfile/doc synchronization.

## 6. Quality Gates (Per Slice)

1. `py_compile` passes for touched Python files.
2. relevant parser/config/runtime/software tests pass.
3. selector/assignment determinism tests pass for changed planner surfaces.
4. no new legacy config-path dependencies are introduced.
5. planning docs are synchronized for contract changes.
6. image prefetch logic has no compatibility path for removed legacy knobs.
7. changed runtime surfaces avoid ad-hoc deep config indexing and avoid introducing key-forwarder helper proliferation.
8. parser changes keep `input/configuration/yaml_parser.py` orchestration-focused; domain validators are decomposed into dedicated modules.
9. each structural refactor slice updates design/handoff docs so final documentation closure is incremental, not deferred to a single end burst.

## 7. Risks and Controls

1. Risk: regressions from centralization.
   - Control: incremental slices + focused tests.
2. Risk: stale examples/templates.
   - Control: update fixtures/examples in same PR as semantic changes.
3. Risk: architecture drift.
   - Control: enforce plan-stack synchronization gate.
4. Risk: benchmark assignment semantics diverge from software placement semantics.
   - Control: shared selector resolver and combined planner tests.

## 8. Exit Checklist

1. Section 3 Definition of Done satisfied.
2. No contradictory software/config semantics in code or docs.
3. Planning docs synchronized:
   - `docs/ansible_restructuring_design.md`
   - `docs/configuration_restructuring_design.md`
   - `docs/software_module_architecture_plan.md`
4. Cluster and benchmark assignment contracts are reflected in parser/runtime tests.

## 9. Immediate Alignment with Global PR Plan

Track `docs/rework_plan_stack.md` Section 6:

1. shared ownership: PR-2 and PR-5,
2. primary Phase-C ownership: PR-3 then PR-4,
3. current historical snapshot (February 17, 2026): PR-2 is complete with module registry and explicit-only dependency/capability validation baseline in parser/runtime, plus incremental exclusivity/conflict validation hardening and tests.
4. historical Phase-C note after PR-2 closure: the next focus at that point was PR-3 selector/scope hard cutover (benchmark pipeline + scoped diagnostics) plus PR-3A run-scoped image-prefetch cutover, with application runtime deferred to a later Phase-D slice.
5. PR-3A implementation baseline now includes deterministic image requirement resolution for `kubecontrol`/`kube_kata` control-plane images from `kube_version` and internal benchmark-stage mappings for `empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, and `text_translation`, including stack-aware `image_classification` selection.

## 10. Session Handoff (Updated April 11, 2026)

Current closure status:

1. PR-3A registry/image-prefetch hard-cutover behavior is implemented and test-covered.
2. Baseline benchmark-stage image mappings are implemented with fail-fast unknown-stage handling.
3. `image_classification` image mapping is now stack-aware (`openfaas` serverless pair vs container trio).
4. Runtime/bootstrap fail-fast branches for registry endpoint selection and migration are test-covered.
5. Earlier focused regression baseline was green:
   - `python3 -m unittest discover scripts/test/unit`
   - `python3 -m unittest discover scripts/test/e2e`
6. PR-4 prep progressed: core then-gated runtime surfaces (`application/application.py`, `resource_manager/kubernetes/kubernetes.py`, `resource_manager/endpoint/endpoint.py`) now consume `domains.benchmark.pipeline` via generic `config_access.benchmark_param*` helpers instead of removed `workload_*` and legacy benchmark sizing helpers.
7. Runtime fallback aliasing in endpoint env generation is removed (`duration_s` -> `duration`); runtime access is now direct canonical-key lookup and no longer patches missing config with fallback defaults.
8. Orchestrator comparison helper `config_access.orchestrator_is(...)` is removed; callsites now use direct comparisons on `config_access.orchestrator_name(config)` to keep the accessor interface minimal.
9. Endpoint runtime resource limits are corrected to benchmark-stage endpoint sizing keys (`application_endpoint_cpu`, `application_endpoint_memory`) rather than infrastructure VM capacity keys.
10. Legacy benchmark/workload helper stubs are removed from `config_access`; active application/runtime callsites now use generic benchmark parameter access (`benchmark_param*`) with no compatibility wrappers.
11. `config_access` wrapper surface is reduced further by removing unused passthrough helpers (`benchmark`, `orchestrator`, `orchestrator_config`) to keep the runtime accessor API minimal.
12. Parser now enforces strict benchmark stage config contracts for known stage types (required keys, type/range constraints, unknown-key rejection), moving additional failure modes from runtime reads to parse/bootstrap time.
13. `config_access` canonical read paths are further tightened: `domains.run.image_prefetch` and `domains.software.modules` are now required at runtime access (no fallback defaults), with malformed/missing structures treated as invariant violations.
14. Remaining one-key orchestrator wrappers are removed from `config_access` (`cache_worker_enabled`, `kube_deployment_mode`, `kube_version`, `runtime_name`); active runtime callsites now use generic `orchestrator_value` / `orchestrator_bool`, and parser tests were adjusted to avoid synthetic OpenFaaS-side effects in scoped-conflict fixtures.
15. Addon-specific config-access wrappers are also removed (`openfaas_enabled`, `observability_enabled`, `endpoint_runtime_enabled`); active runtime/planner/image-requirement callsites now use `has_addon(config, "<addon>")` directly.
16. Image requirement discovery no longer applies runtime defaults for control-plane versions: `kubecontrol`/`kube_kata` mappings require explicit module `config.kube_version`; missing key now fails fast, and normalized infra resources path is required (`normalized.infrastructure.resources`).
17. Remaining fallback defaults in active infra/planner helpers are removed: `AnsibleRunner`/group-vars generation, software phase endpoint-install gating, netperf result path stamping, and Mahimahi source-path resolution now read canonical required keys directly (`base`, `ssh_key`, `mode`, `username`, `timestamp`), with endpoint install gating driven by canonical module assignment metadata.
18. Registry endpoint selection/migration helpers now read canonical infrastructure and SSH keys directly (no `config.get` fallback maps), preserving deterministic fail-fast behavior for missing runtime wiring.
19. Registry prefetch payload handling is now explicitly invariant-driven: infrastructure registry flows require canonical `prefetch_image_requirements`, fail fast on malformed payloads, and normalize accepted entries (trimmed/deduplicated owners and tier targets).
20. Image requirement tier-target derivation now requires canonical `resolved_vm_ids` metadata and matching normalized resource records; missing/invalid VM mappings fail fast instead of applying fallback selector heuristics.
21. Lockfile re-validation now enforces derived selector-metadata integrity (`selector`, `selector_id`, `resolved_vm_ids`, `scope_identities`) by requiring field presence and equality with recomputed selector resolution outputs.
22. Lockfile writing now applies the same fail-fast invariant policy for YAML runs: canonical `normalized` and `infrastructure.base_path` are required, and malformed `normalized.sources` is rejected.
23. Parser decomposition-first cleanup has begun: legacy runtime projection logic was extracted from `input/configuration/yaml_parser.py` into `input/configuration/legacy_projection.py`, and regression coverage now includes focused helper tests (`scripts/test/unit/test_legacy_projection.py`).
24. Benchmark stage config-contract validation is now decomposed into `input/configuration/benchmark_stage_contract.py` with focused unit coverage (`scripts/test/unit/test_benchmark_stage_contract.py`), preserving parser fail-fast diagnostics while reducing monolithic parser logic.
25. Shared module capability/exclusive/conflict contract evaluation is now decomposed into `input/configuration/module_contract_validation.py` and reused by both parser and runtime, with focused unit coverage (`scripts/test/unit/test_module_contract_validation.py`) to keep behavior aligned across both surfaces.
26. Selector-resolution decomposition is expanded in `input/configuration/selector_resolution.py`: it now covers `assign_to.match` normalization/canonical selector-id derivation, derived metadata reconciliation (`resolved_vm_ids`, `scope_identities`), and selector-derived field validation/formatting helpers, with focused unit coverage (`scripts/test/unit/test_selector_resolution.py`), reducing duplication across parser selector passes.
27. Run/infrastructure/provider schema validation is partially decomposed into dedicated modules (`run_schema_validation`, `infrastructure_schema_validation`, `provider_schema_validation`) with focused unit coverage in `scripts/test/unit/test_schema_validation.py`.
28. Parser orchestration decomposition progressed further: software/benchmark/selector-resolution validation logic moved from `input/configuration/yaml_parser.py` to dedicated modules (`software_domain_validation`, `benchmark_domain_validation`, `selector_assignment_validation`), shared validation primitives moved to `input/configuration/validation_utils.py`, and parser behavior remained regression-stable.
29. Focused parser decomposition coverage now includes `scripts/test/unit/test_domain_validation.py` for phase-domain benchmark gating and module-type schema-contract failure paths.
30. Domain-validation internals are further decomposed by concern into `software_domain_validation`, `benchmark_domain_validation`, and `selector_assignment_validation`, and parser/tests now consume those modules directly.
31. Runtime configuration wiring is now decomposed into focused modules (`runtime_phase_targets`, `runtime_module_loader`, `runtime_option_validation`) and active callsites now import these directly (no compatibility facade layer); existing runtime regression suite remains green.
32. Documentation-closure is explicitly locked as an end-of-rework gate in `docs/rework_plan_stack.md` (schema docs, migration notes, architecture docs, synchronized examples, and final doc-audit pass).
33. Schema validation is now decomposed into focused modules (`run_schema_validation`, `infrastructure_schema_validation`, `provider_schema_validation`) with direct parser/test wiring; focused schema tests and full parser/runtime regression remain green.
34. YAML parser support plumbing is decomposed into focused modules (`yaml_io`, `profile_composition`, `experiment_lock_writer`) while `yaml_parser` preserves orchestration-only flow and lock/profile behavior under regression.
35. Focused unit tests now cover the extracted YAML/profile/lock modules directly (`test_yaml_io`, `test_profile_composition`, `test_experiment_lock_writer`) in addition to parser integration regression.
36. Runtime wiring facade cleanup is complete: `runtime_config.py` was removed after direct-call migration, and a dead-code/reference audit of `input/configuration` found no additional unreferenced modules/functions in active paths.
37. Runtime option validation now enforces canonical scope invariants without runtime path mutation: missing `domains.provider.config` or missing orchestrator `config` scope is treated as fail-fast miswiring (no `setdefault` fallback behavior).
38. Provider unknown-option enforcement is now interface-driven: runtime validation admits core-owned provider keys plus provider module option descriptors (no provider-specific key catalog in core), and parser schema validation now rejects unknown `provider.config.ip.*` subkeys.
39. Runtime/provider shared contract declarations are centralized in `input/configuration/runtime_option_contract.py` to mirror benchmark-stage contract discoverability and keep parser/runtime option validation aligned from one source.
40. Provider schema parsing now rejects unknown top-level provider keys (`provider.{name,config}` only), keeping structural validation strict at parser boundary while leaving provider-module option ownership to module contracts.
41. Parser schema validation now materializes canonical defaults for run/provider/network domains (`run.dry_run`, `run.clean`, provider core+IP defaults, normalized `infrastructure.network` object), moving remaining defaulting out of runtime projection paths.
42. Legacy projection is now strict invariant projection with required-path checks (no fallback patching for `run`, `provider`, or network keys), so missing canonical fields surface as explicit fail-fast invariant errors.
43. Selector-assignment reconciliation (`selector_assignment_validation`) is now strict on normalized domain paths and no longer defaults missing `run`/`software`/`infrastructure.resources` containers to empty structures.
44. Selector-assignment reconciliation now explicitly enforces benchmark-domain presence when `run.targets` includes `application`, aligning reconciliation-stage failures with parser-phase benchmark domain contracts.
45. `config_access` canonical readers now enforce benchmark-stage/software-module structural invariants (`id`, `type`, `config`) and no longer rely on permissive `.get(...)` fallback paths.
46. Config-access regression now includes malformed stage/module structure tests to ensure runtime reads fail fast when parser/bootstrap invariants are violated.
47. Selector-reconciliation strictness is further tightened: `selector_resolution.reconcile_assignment(...)` now requires canonical entity selector metadata (`assign_to.match`, `selector_id`) and no longer defaults missing selector inputs.
48. Selector scope VM resolution now fails fast on malformed normalized infrastructure resource entries (`vm_id`, `tags`) rather than silently skipping invalid records.
49. Software-domain runtime projection and contract checks now require module `config` mappings in reconciliation paths (no post-parse `{}` fallbacks for orchestrator/addon modules).
50. Image requirement discovery now enforces canonical module/stage identity and normalized resource-record invariants, including fail-fast handling for unknown module types and malformed `normalized.infrastructure.resources` entries.
51. Software parser validation now hard-requires explicit module config blocks (`software.modules[*].config` mapping), eliminating parser-side fallback defaults for omitted module config.
52. Runtime option validation now resolves provider/resource-manager config scopes with explicit fail-fast path diagnostics (no `None` sentinel fallback branch in scope resolution).
53. `config_access.benchmark_param(...)` now reports missing stage-config keys as explicit canonical-path `ValueError` failures (no raw `KeyError` propagation in runtime callsites).
54. `config_access.orchestrator_bool(...)` now enforces strict boolean parsing (`true|false` for strings) and fails fast on invalid values instead of permissive truthy coercion.
55. Parser defaulting now treats explicit `null` as invalid for optional mapping fields in provider/infrastructure/benchmark domains (defaults apply only when fields are omitted).
56. Experiment lock writing now persists an additive `planner_snapshot` with deterministic software execution order, owner-tagged plan entries, and benchmark-stage assignment metadata that supported PR-4 benchmark handoff preparation before Phase D ungated application execution.
57. Lock parsing now validates persisted `planner_snapshot` against a recomputed deterministic planner snapshot when present, catching tampered software-plan or benchmark-assignment handoff metadata before runtime use.
58. Planner snapshot assignment records now include resolved resource handoff metadata (`resolved_resources` with `vm_id`, `cluster_id`, `tier`, `index_in_cluster`, and tags) for software modules and benchmark stages, with fail-fast validation against `normalized.infrastructure.resources`.
59. Earlier handoff validation baseline was green:
   - `python3 -m py_compile input/configuration/module_contract_validation.py input/configuration/software_domain_validation.py input/configuration/selector_assignment_validation.py input/configuration/runtime_option_validation.py resource_manager/plans.py scripts/test/unit/test_module_contract_validation.py scripts/test/unit/test_resource_manager_plans.py scripts/test/unit/test_continuum_runtime.py scripts/test/unit/test_yaml_parser.py`
   - `python3 -m unittest discover scripts/test` (`217 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test` (`217 passed`)
60. Benchmark handoff helper wiring now exposes planner-stage assignments and resolved resources through `config_access`, and the former gated Kubernetes helper paths pass planner-derived stage handoff metadata forward without inferring application role topology from a single selector.
61. Software handoff helper wiring now exposes canonical software-module resolved resources through `config_access`, and the software phase uses `endpoint_runtime` module placement on endpoint resources to decide whether to run endpoint install.
62. Endpoint-runtime contract validation now requires the `endpoint_runtime` provider to resolve onto endpoint VM resources when endpoint resources are present, and base-image endpoint install planning uses that same placement predicate.
63. Module requirement validation now respects resolved assignment scope: providers for required capabilities must overlap the requiring module's scope, preventing addon modules from binding to capabilities declared only on unrelated resources.
64. Runtime software-phase endpoint-install and base-image gating now use software-module planner snapshot assignment readers (`planner_snapshot.software_module_assignments[*].resolved_resources`) when executing runtime paths; planner snapshot construction opts out of that reader and uses canonical pre-snapshot module assignment metadata to keep the snapshot deterministic and acyclic.
65. Parser regression tests now mock host-IP socket discovery, keeping `runtime_module_loader.add_constants` production behavior intact while making the parser/unit suite sandbox-safe.
66. Host-IP discovery failure handling now catches OS-level socket failures such as `PermissionError` and reports deterministic parser errors instead of leaking raw socket tracebacks.
67. Planner handoff accessors now validate resolved-resource invariants at runtime: each `resolved_resources[*].vm_id` must match the corresponding `resolved_vm_ids[*]`, and scope identities are validated through the shared selector scope contract.
68. Resolved resource handoff validation now also enforces base-tag consistency: `resolved_resources[*].tags.tier` and `tags.cluster` must match the record `tier` and `cluster_id`, and planner snapshot construction rejects mismatched normalized resource tags before persisting handoff metadata.
69. Benchmark handoff access now has canonical runtime bundles (`config_access.benchmark_stage_handoff` and `benchmark_stage_handoffs`) carrying assignment ids, pipeline indexes, deep-copied stage config, resolved VM ids/resources, scope identities, benchmark tags, and deterministic resource counts by tier.
70. Kubernetes launch-variable preparation forwards the primary benchmark handoff bundle, pipeline-ordered handoff bundles, and flattened compatibility fields, preparing Phase-D role/template consumers without deriving application role topology from a single selector.
71. Software-module planner handoff access now has canonical runtime bundles (`config_access.software_module_assignment_handoff` and `software_module_assignment_handoffs`) carrying assignment ids, module indexes, deep-copied module config, resolved VM ids/resources, scope identities, and deterministic resource counts by tier; endpoint-runtime software/base-image gating uses the single-module bundle for planner snapshot reads.
72. Kubernetes launch-variable preparation now forwards a combined `planner_runtime_handoff` payload alongside compatibility fields so Phase-D role/template consumers can read ordered planner-derived software and benchmark config/placement from one runtime object.
73. Phase-D application role consolidation has since split application-specific launch/timing/runtime concerns out of `resource_manager/kubernetes/kubernetes.py` (`launch_with_starttime`, MQTT environment injection, and Mist/Baremetal worker-output handling).
74. PR-4 runtime handoff bundles now preserve their original ordering via explicit `pipeline_index` / `module_index` fields and include deep-copied stage/module config, making the Phase-D template handoff self-contained.
75. Module-ordered software handoff construction is now instance-id based internally, so handoff ordering follows `domains.software.modules[]` entries without re-looking up assignments by module type.
76. Software-module runtime access now exposes id-based helpers (`software_module_by_id`, `software_module_assignment_by_id`, and `software_module_assignment_handoff_by_id`) for Phase-D consumers that need a specific module instance without relying on module-type uniqueness.
77. Runtime structural accessors now reject duplicate benchmark stage ids and duplicate software module ids, aligning handoff-reader invariants with parser/domain validation before Phase-D consumers depend on exact id lookup.
78. Resource-manager module and endpoint helper `start()` hooks now delegate to the centralized `resource_manager.start()` entrypoint, so direct module calls no longer bypass planner owner metadata, endpoint-runtime placement gating, or post-phase hook mediation.
79. PR-4 is complete for the Phase-C runtime/planner integration slice: software execution is planner-mediated, endpoint-runtime install/base-image gating uses planner placement, benchmark/software handoff bundles are available for Phase-D preparation, and legacy benchmark/workload helper paths are removed from active runtime code. Phase D has since removed the explicit `run.targets: application` runtime gate.
80. Earlier PR-4 baseline validation was green:
   - `python3 -m py_compile scripts/test/e2e/test_example_configs.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_example_configs scripts.test.unit.test_yaml_parser` (`37 tests OK`)
   - `python3 -m py_compile scripts/test/support/e2e_utils.py scripts/test/e2e/test_e2e_test_utils.py scripts/test/run_tests.py scripts/test/e2e/test_run_tests.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_run_tests scripts.test.e2e.test_e2e_test_utils` (`16 tests OK`)
   - `python3 -m py_compile continuum.py scripts/test/unit/test_continuum_runtime.py scripts/test/verify_network_profiles.py infrastructure/network.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime scripts.test.e2e.test_verify_network_profiles` (`68 tests OK`)
   - `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`253 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test` (`253 passed`)
81. PR-5 user-facing documentation is now published in `docs/configuration_reference.md` and `docs/migration_notes.md`, with `docs/cheatsheet.md`, `README.md`, and `configuration/README.md` updated to point operators at the canonical YAML and migration references instead of legacy runtime entrypoints.
82. PR-5 regression coverage now validates shipped experiment examples plus shipped environment/software profiles directly from the repository tree via `scripts/test/e2e/test_example_configs.py`, keeping examples, templates, and profile fixtures synchronized with parser validators.
83. PR-5 example/doc cleanup also fixed the YAML boolean pitfall around `run.image_prefetch` by quoting `"off"`/`"on"` in shipped experiment examples and user-facing docs.
84. PR-5 e2e-runner cleanup now validates `scripts/test/run_tests.py --suite <name>` against suite names declared in `scripts/test/test_config.json` rather than a hard-coded CLI list, restoring config-declared suites such as `network_validation`.
85. PR-5 test metadata/docs are now YAML-aligned end-to-end: `scripts/test/test_config.json` scopes `network_validation` to `configs/experiments/network_validation/`, `scripts/test/test_manifest.json.example` uses YAML include patterns, and the `configuration/tests/` and `configuration/network_validation/` READMEs no longer point new users at removed `.cfg` runtime entrypoints.
86. PR-5 now has explicit developer-facing docs for runtime execution boundaries (`docs/runtime_execution_pipeline.md`) and operational smoke strategy (`docs/operational_testing_strategy.md`), clarifying that real end-to-end validation spans bootstrap/planning, infra, software, application, and artifact/resume/teardown concerns.
87. PR-5 now defines a dedicated lightweight smoke-config set under `configs/experiments/smoke/` and scopes the runner smoke suite to that directory, aligning the operational baseline with one minimal scenario per active runtime phase boundary.
88. PR-5 smoke policy is now explicit: smoke and network-validation suites are fast-fail by default, Kubernetes is the canonical software smoke target, network validation remains a separate operational path, and the Phase-D benchmark smoke shape is a resumed multi-phase pipeline that tears down only at the end.
89. PR-5 runner success detection now validates YAML runtime artifacts in addition to exit code and SSH hints: the e2e runner requires `.continuum/experiment_lock.yaml`, `.continuum/state.json`, and a matching `state.json.phase_completed` value for the requested runtime target, bringing the operational contract closer to the documented phase model.
90. PR-5 suite execution is now environment-aware at runner startup: `scripts/test/test_config.json` declares suite-level prerequisite host commands, and `scripts/test/run_tests.py` fails fast when VM-backed suites such as `smoke` or `network_validation` are invoked on a host without the required local tools.
91. PR-5 suite metadata is now directly inspectable from the CLI: `scripts/test/run_tests.py --list-suites` prints configured suites and prerequisite summaries, and `--check-prereqs` validates host readiness for a selected suite without discovering configs or starting VMs.
92. PR-5 runner result persistence is now smoke-debug-friendly: saved summary JSON points at per-test stdout/stderr/metadata artifacts, and failed runs carry stable `failure_class` buckets so the first broken VM-backed smoke run is easier to triage.
93. PR-5 now includes a dedicated least-privilege host-execution design for real VM-backed smoke runs via `scripts/test/run_smoke_host.sh` and `docs/smoke_runner_isolation.md`, documenting the recommended dedicated-user and wrapper model instead of relying on broad unsandboxed shell access.
94. PR-5 real host-backed smoke execution is now closed for the currently runnable Phase-C runtime boundaries: `infra_one_vm`, `software_k8s_two_vm`, and `network_netperf_two_vm` all pass through the dedicated `continuum-smoke` wrapper path.
95. The host-backed smoke closure surfaced and fixed real runtime issues across the QEMU path, including parser-backed override success detection, deterministic bounded guest login names, controller-side repo asset paths after the Phase-C handoff move, flannel manifest sourcing, and YAML-era network-emulation compatibility in `infrastructure/network.py`.
96. QEMU base-image cache reuse is now integrity-gated: a base image is reused only when companion success metadata exists and matches the expected guest-user contract, so interrupted `.continuum` image builds are invalidated and rebuilt instead of being silently trusted on the next run.
97. Latest validation is green:
   - `python3 -m py_compile infrastructure/network.py scripts/test/unit/test_network.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_network scripts.test.e2e.test_verify_network_profiles` (`6 tests OK`)
   - `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`273 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test` (`273 passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke infra_one_vm` (`passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke software_k8s_two_vm` (`passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_netperf_two_vm` (`passed`)

Next clean start point:

1. Treat PR-4 as closed and green.
2. Treat PR-5 as closed and green for its intended scope: examples/profiles/docs are synchronized, the least-privilege host runner is documented and scripted, and all currently runnable host-backed smoke slices pass.
3. Phase D application-role consolidation plus resumed K8s smoke pipeline/teardown verification, Phase E resume/state integrity, and Phase F test architecture closure have since closed.
4. Preserve Phase-D cleanup ownership for application-specific Kubernetes launch/timing/runtime code (`launch_with_starttime`, MQTT env injection, and Mist/Baremetal worker-output handling); do not move or ungate it outside an explicit Phase-D slice.
5. Current Phase-D state:
   - application bootstrap/module wiring is enabled again,
   - helper extraction started in `application/runtime_helpers.py`,
   - runtime execution is ungated in `input/configuration/runtime_phase_targets.py`,
   - benchmark smoke/teardown validation has closed on the dedicated host-backed runner.
   - See `docs/phase_d_handoff.md`.
