# Continuum Rework Kickoff (First-Read Brief)

## 1. Read Order

1. `docs/rework_kickoff.md` (this file)
2. `docs/rework_plan_stack.md`
3. `docs/software_module_architecture_plan.md`
4. `docs/configuration_restructuring_design.md`
5. `docs/phase_c_implementation_plan.md`
6. `docs/ansible_restructuring_design.md`
7. `docs/runtime_execution_pipeline.md`
8. `docs/operational_testing_strategy.md`
9. `docs/vm_debugging_runbook.md`
10. `docs/phase_d_handoff.md` (current implementation handoff for the active Phase-D prep slice)

If you are resuming active implementation rather than reconstructing the full stack, the minimum continuation set is:

1. `docs/rework_kickoff.md`
2. `docs/phase_d_handoff.md`
3. `docs/runtime_execution_pipeline.md`

## 2. Current Phase Focus

Primary execution focus has moved from Phase-D closure to Phase E (resume and
state integrity), but implementation must stay aligned with:

1. cluster-first infrastructure model (`infrastructure.clusters[]`),
2. final software model (`software.modules[]`, tag-based resource identity),
3. benchmark assignment by selectors/tags,
4. YAML parser/runtime configuration contracts,
5. hard-cutover and fail-fast policy,
6. explicit retained-resume intent via `run.prepare_for_resume`.

## 3. Locked Decisions (Do Not Drift)

1. Hard cutover:
   - no long-lived dual runtime schema mode,
   - no warning-first compatibility strategy.
2. Cluster-first infrastructure:
   - clusters are first-class and emit `cluster=<id>` tags to all contained resources,
   - base infra tags are `tier` and `cluster`.
3. Benchmark assignment is mandatory:
   - benchmark execution units are assigned via selectors/tags, not benchmark name only.
4. Internal-first dependency wiring:
   - dependency/capability graph is internal registry logic,
   - user schema has no dependency edge field.
5. Dependency strategy is explicit-only:
   - missing required capabilities/modules are hard failures,
   - no auto-injection of dependency modules.
6. Fail-fast constraints:
   - reserved tag collisions are hard errors,
   - selector/cycle/conflict violations are hard errors.
7. Selector/scope semantics are locked:
   - selectors are exact-match only (`match: {k:v}` with implicit AND),
   - selectors are canonicalized and get deterministic `selector_id`,
   - scope identities use structured objects (`vm`, `cluster`, `selector`).
8. Benchmark tag governance:
   - benchmark must not overwrite `role`,
   - benchmark role intent uses namespaced keys (for example `benchmark.role`).
9. Image prefetch contract:
   - user intent is `run.image_prefetch` (`off|on`, default `off`),
   - local registry lifecycle is internal and infra-executed when required images exist,
   - no compatibility alias for `infrastructure.image_prefetch`.
10. Validation architecture:
   - validate/default once at parser/bootstrap boundaries,
   - runtime config reads use canonical keys directly and avoid fallback patching,
   - runtime read failures indicate invariant bugs and must fail fast.
11. Config-access maintainability balance:
   - avoid raw deep-index runtime config access outside `config_access`,
   - avoid one-getter-per-parameter proliferation for dynamic config bags,
   - use semantic structural helpers plus generic typed parameter readers.

## 4. Canonical Ownership

1. Software semantics: `docs/software_module_architecture_plan.md`
2. Config/parser/runtime contracts: `docs/configuration_restructuring_design.md`
3. Phase C execution sequencing: `docs/phase_c_implementation_plan.md`
4. Program-level roadmap: `docs/ansible_restructuring_design.md`

If two docs conflict, follow `docs/rework_plan_stack.md` conflict rules.

Software semantic details (including constraint-scope model) live in:

- `docs/software_module_architecture_plan.md`

## 5. Immediate Implementation Sequence

1. PR-1 (completed): parser schema pivot to canonical `infrastructure.clusters[]` + `software.modules[]`.
2. PR-2 (completed): module registry + explicit-only dependency/capability validation baseline is landed; parser/runtime conflict and exclusivity validation coverage is landed with targeted tests.
3. PR-3 (completed): selector resolution + scoped constraint engine baseline.
4. PR-4 (completed): runtime/planner software-phase integration + benchmark assignment plumbing + legacy path removal, with deterministic handoff metadata prepared for Phase-D consumers.
5. PR-5 (completed): example/profile migration finalization + tests/smokes + documentation closure; user-facing config/migration docs, host-runner isolation, and real host-backed smoke closure are now landed.

## 6. Quick Start Checklist for an Agent

1. Confirm the change touches the correct authority document first.
2. Implement against the locked decisions above.
3. Update tests/examples in the same PR when semantics change.
4. Synchronize sibling planning docs before finalizing the PR.

## 7. PR-2 Code Touchpoints (Completed Baseline)

Start with these surfaces for module-registry and dependency-validator work:

1. `input/configuration/yaml_parser.py`
2. `input/configuration/module_registry.py`
3. `input/configuration/config_access.py`
4. `input/configuration/runtime_phase_targets.py`
5. `input/configuration/runtime_module_loader.py`
6. `input/configuration/runtime_option_validation.py`
7. `resource_manager/plans.py`
8. `resource_manager/resource_manager.py`
9. `resource_manager/orchestrator_options.py`
10. `scripts/test/test_yaml_parser.py`
11. `scripts/test/test_config_access.py`
12. `scripts/test/test_continuum_runtime.py`
13. `scripts/test/test_module_registry.py`

## 8. Planning Closure Status

1. Selector/scope decisions are locked and moved into authoritative software/config plans.
2. No remaining open architecture TODOs are required before implementation PR-1 to PR-5.
3. PR-1 parser/runtime cutover is complete, including modules-only config access and YAML fixture migration.
4. PR-2 parser/runtime closure is complete with registry-backed capability/dependency checks and dedicated unit tests.
5. PR-2 incremental hardening includes parser/runtime parity for exclusive-capability/conflict validation with targeted regression tests.
6. PR-3A baseline introduces run-scoped image-prefetch with internal control-plane image requirement resolution for `kubecontrol`/`kube_kata` and baseline benchmark-stage mappings (`empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, `text_translation`), including stack-aware `image_classification` image selection.
7. PR-4 prep progressed by replacing core then-gated runtime uses of removed `workload_*`/legacy benchmark sizing helpers with generic benchmark-pipeline parameter access helpers (`benchmark_param*`), including `application/*` module callsites.
8. Runtime fallback aliasing for endpoint benchmark duration has been removed (`duration_s` is no longer accepted in execution paths; canonical key is `duration`).
9. Active runtime orchestrator checks use direct `config_access.orchestrator_name(config)` comparisons; `orchestrator_is(...)` is removed to keep the accessor surface minimal.
10. Runtime option normalization now treats canonical option scopes as required invariants (`domains.provider.config`, `domains.software.modules[*].config`) and no longer mutates missing paths via `setdefault`.
11. PR-4 planner handoff now includes `planner_snapshot` assignment records for software modules and benchmark stages with deterministic `resolved_resources` metadata (`vm_id`, `cluster_id`, `tier`, `index_in_cluster`, and resource tags).
12. Phase-D runtime ungating is now landed; current work shifts from prep-only handoff metadata to finishing role consolidation plus benchmark smoke/teardown validation.
13. PR-4 runtime helper plumbing now includes `config_access` readers for benchmark-stage planner assignments, and the former gated Kubernetes helper paths pass planner-derived stage handoff metadata forward without inferring application role topology from a single selector.
14. PR-4 software planner plumbing now uses canonical `endpoint_runtime` module placement on endpoint resources for endpoint install gating, replacing aggregate endpoint-node gating in the software phase.
15. PR-4 endpoint-runtime validation now rejects endpoint topologies where the `endpoint_runtime` capability exists but its assignment resolves away from endpoint VM resources; base-image endpoint install planning uses the same placement check.
16. PR-4 module requirement validation is now assignment-scope-aware, so required capabilities must be provided in an overlapping resolved scope rather than anywhere globally in the software module set.
17. PR-4 software-phase runtime gating now consumes `planner_snapshot.software_module_assignments[*].resolved_resources` for endpoint-runtime placement, while deterministic planner snapshot construction keeps using canonical pre-snapshot module assignment metadata to avoid circular handoff reads.
18. Parser regression tests now mock host-IP socket discovery, so full unit and pytest runs pass in sandboxed environments without requiring network/socket permission.
19. Runtime host-IP discovery now fails fast through parser diagnostics on OS-level socket denial (`OSError`/`PermissionError`) instead of leaking raw socket tracebacks.
20. PR-4 planner handoff accessors now enforce resolved-resource and scope-identity invariants at runtime instead of trusting malformed `planner_snapshot` assignment records.
21. PR-4 planner handoff validation now enforces resolved resource base-tag consistency (`tags.tier`/`tags.cluster` matching record `tier`/`cluster_id`) in both runtime accessors and snapshot construction.
22. PR-4 benchmark handoff access now exposes canonical runtime bundles (`benchmark_stage_handoff` / `benchmark_stage_handoffs`) with planner assignment ids, pipeline indexes, deep-copied stage config, resolved resources, scope identities, tags, and tier counts; the former gated Kubernetes launch variables pass primary and pipeline-ordered handoff data forward into the now-ungated Phase-D runtime path.
23. PR-4 software handoff access now exposes canonical single-module and module-ordered software assignment bundles with planner assignment ids, module indexes, deep-copied module config, resolved resources, scope identities, and tier counts; endpoint-runtime install gating consumes the single-module bundle while planner snapshot construction stays on pre-snapshot metadata. Module-ordered handoff construction is instance-id based internally rather than type-relookup based, with id-based accessors available for consumers that need a specific module instance.
24. Runtime structural accessors now reject duplicate benchmark stage ids and duplicate software module ids, keeping exact-id handoff reads aligned with parser/domain invariants.
25. PR-4 Kubernetes launch variables now forward a combined `planner_runtime_handoff` payload containing ordered software-module and benchmark-stage config/placement metadata, giving Phase-D role/template work one planner-derived input surface.
26. Resource-manager module and endpoint helper `start()` hooks now delegate to the centralized `resource_manager.start()` entrypoint, closing the remaining direct-start software execution and endpoint-install bypasses.
27. Historical PR-4 handoff point: next work at that time was PR-5 examples/smokes/documentation closure while the Phase-D application execution gate was still closed; PR-5 and Phase D have both since landed.
28. PR-5 now publishes `docs/configuration_reference.md` and `docs/migration_notes.md` as the user-facing YAML-schema and hard-cut migration references, and `docs/cheatsheet.md`, `README.md`, and `configuration/README.md` now point readers at those YAML docs instead of legacy runtime entrypoints.
29. PR-5 regression coverage now validates shipped experiment examples plus shipped environment/software profiles directly from disk via `scripts/test/test_example_configs.py`, and the shipped/doc examples now quote `run.image_prefetch` values to avoid YAML boolean coercion.
30. PR-5 e2e-runner cleanup now validates `--suite` names against `scripts/test/test_config.json` instead of a hard-coded CLI list, and the `network_validation` suite is correctly scoped to `configs/experiments/network_validation/` with YAML-only runner docs/manifests refreshed.
31. PR-5 now documents the runtime phase model and operational test strategy in `docs/runtime_execution_pipeline.md` and `docs/operational_testing_strategy.md`, explicitly separating bootstrap/planning and artifact/resume validation from the user-visible infrastructure/software/application targets.
32. PR-5 now defines dedicated lightweight smoke configs under `configs/experiments/smoke/` for infrastructure-only, infrastructure-plus-software, and network/netperf validation, and the smoke suite points there instead of sweeping all experiments.
33. PR-5 smoke policy is documented as fast-fail, artifact-retaining, and phase-oriented: Kubernetes is the canonical software smoke target, netperf/network validation stays separate, and the Phase-D benchmark smoke path now uses a resumed multi-phase run on reused VMs.
34. PR-5 now adds `docs/vm_debugging_runbook.md` and logs VM access hints immediately after infrastructure completion or resume-state load, making retained-VM debugging practical even when later phases fail.
35. PR-5 now hardens the YAML e2e-runner success contract: successful runs must leave behind `.continuum/experiment_lock.yaml`, `.continuum/state.json`, and the expected `phase_completed` value for the executed target set, instead of relying only on exit code and SSH-output heuristics.
36. PR-5 suite metadata now includes machine-readable prerequisite host commands for VM-backed operational paths, and the runner rejects `smoke` / `network_validation` early when the local host does not expose the required tools.
37. PR-5 suite metadata is now directly usable from the CLI as well: `scripts/test/run_tests.py --list-suites` exposes the configured suite contract, and `--check-prereqs` validates host readiness before any config discovery or VM provisioning begins.
38. PR-5 runner result persistence is now better suited for smoke debugging: each saved test summary has a sibling artifact directory with per-test stdout/stderr/metadata, and failures are tagged with stable `failure_class` values to speed triage.
39. PR-5 now includes a concrete least-privilege host-execution path for VM-backed smoke work: `scripts/test/run_smoke_host.sh` whitelists approved smoke scenarios, `scripts/test/setup_agent_host.sh` is the canonical single-script host bootstrap path, and `docs/smoke_runner_isolation.md` documents the dedicated-user/wrapper model plus the expected external allowlisting shape.
40. PR-5 real host-backed smoke closure is now complete for the currently active Phase-C runtime boundaries: `infra_one_vm`, `software_k8s_two_vm`, and `network_netperf_two_vm` all pass through the dedicated `continuum-smoke` wrapper path.
41. The host-backed smoke work fixed several real runtime defects rather than only test harness issues, including bounded guest login names for QEMU guests/base images, controller-side repo asset path assumptions after the YAML handoff move, flannel manifest sourcing, and YAML-era network-emulation compatibility plus TC shell-command assembly in `infrastructure/network.py`.
42. `.continuum` image-cache reuse is now safer: QEMU base images are reused only when companion success metadata marks them complete, so interrupted or partial base-image builds are invalidated and rebuilt instead of being silently trusted on later runs.
43. PR-5 is now complete for its scoped objective; Phase-D benchmark/application smoke plus resumed K8s pipeline/teardown verification has since landed, and Phase-E resume/state integrity is the active follow-up.

## 9. Resume Point

If resuming after May 20, 2026:

1. Treat PR-3A registry/image-prefetch slice as closed and green.
2. Treat PR-4 as closed and green: `resource_manager/plans.py` emits `software_execution_order`, owner-tagged `software_plan_entries`, `software_module_assignments`, and application-gated `benchmark_stage_assignments`; runtime handoff bundles add ordering indexes plus deep-copied stage/module config around those planner assignment records.
3. Treat software-module planner assignment readers as available for runtime handoff consumers; use pre-snapshot module assignment metadata only inside deterministic planner snapshot construction.
4. Treat PR-5 as closed and green from the PR-4 baseline: user-facing schema/migration docs are landed, shipped examples/profiles have parser-regression coverage, and the real host-backed Phase-C smoke matrix was green before Phase D enabled `run.targets: application`.
5. Treat Phase D as landed:
   - application bootstrap/module wiring is enabled again for benchmark stages with runnable application modules,
   - application-specific Kubernetes launch, worker-output, Mist/Baremetal runtime helpers, and shared MQTT worker env/var shaping now live under `application/runtime_helpers.py`,
   - infra-only QEMU topology for resumable Kubernetes cloud layouts now preserves a control-plane VM instead of emitting worker-only cloud inventory,
   - Ansible runner env now pins guest-side `ANSIBLE_REMOTE_TMP` as well as controller-side `ANSIBLE_LOCAL_TEMP`,
   - infra-only bootstrap now loads the orchestrator resource-manager module only when `run.prepare_for_resume: true`, so orchestrator base-image preparation is explicit for retained infrastructure setup,
   - runtime execution is ungated for YAML runs,
   - the first retained `benchmark_k8s_resume` infrastructure state exposed a missing-control-plane bug during resumed software execution; that topology bug is fixed,
   - the next retained-software attempt exposed missing `kubelet` because infra-only bootstrap had still skipped orchestrator base-image prep; that bootstrap seam is now fixed in-repo,
   - the retained infrastructure/software/application path has passed on the dedicated host-backed benchmark-smoke runner,
   - do not interpret that fix as “always install kubelet in base images”; retained-resume preparation is now explicit via `run.prepare_for_resume`, while generic infrastructure-only runs should leave later-phase prerequisites untouched.
   - See `docs/phase_d_handoff.md`.
6. Treat Phase E resume/state integrity as active:
   - `experiment_lock.yaml` and schema-v2 `state.json` carry matching `resume_contract` metadata,
   - old retained state without schema-v2 metadata is invalid and should be regenerated by rerunning the infrastructure leg,
   - lock writing happens before provisioning or resume execution,
   - e2e success detection validates lock/state schema and matching contract hashes,
   - network-validation success detection validates structured netperf NDJSON
     under `<base_path>/.continuum/logs/network_validation/`,
   - benchmark-smoke success detection validates lightweight metric-table
     evidence in addition to stdout markers.
7. Latest validation baseline is green:
   - `python3 -m py_compile infrastructure/qemu/qemu.py infrastructure/ansible.py input/configuration/runtime_module_loader.py application/runtime_helpers.py application/image_classification/image_classification.py application/text_translation/text_translation.py scripts/test/test_application_runtime_helpers.py scripts/test/test_continuum_runtime.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers scripts.test.test_continuum_runtime` (`102 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test/test_application_runtime_helpers.py scripts/test/test_continuum_runtime.py` (`102 passed`)
   - `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime` (`94 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test/test_continuum_runtime.py` (`94 passed`)
   - `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`307 tests OK`)
   - `env PYTHONPATH=. pytest -q scripts/test` (`307 passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke infra_one_vm` (`passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke software_k8s_two_vm` (`passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_netperf_two_vm` (`passed`)
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume` (`passed` in the Phase-D closure baseline; rerun after Phase-E state changes when host access is available)
8. Use this quick validation set before handing off again:
   - `python3 -m py_compile input/configuration/config_access.py resource_manager/kubernetes/kubernetes.py resource_manager/plans.py continuum.py infrastructure/network.py scripts/test/test_config_access.py scripts/test/test_kubernetes_runtime.py scripts/test/test_resource_manager_plans.py scripts/test/test_experiment_lock_writer.py scripts/test/test_example_configs.py scripts/test/run_tests.py scripts/test/test_run_tests.py scripts/test/test_continuum_runtime.py scripts/test/test_network.py scripts/test/verify_network_profiles.py scripts/test/test_verify_network_profiles.py`
   - `env PYTHONPATH=. pytest -q scripts/test`
   - `PYTHONPATH=. python3 -m unittest scripts.test.test_yaml_io scripts.test.test_profile_composition scripts.test.test_experiment_lock_writer scripts.test.test_domain_validation scripts.test.test_schema_validation scripts.test.test_selector_resolution scripts.test.test_module_contract_validation scripts.test.test_benchmark_stage_contract scripts.test.test_legacy_projection scripts.test.test_yaml_parser scripts.test.test_example_configs scripts.test.test_run_tests scripts.test.test_continuum_runtime scripts.test.test_config_access scripts.test.test_kubernetes_runtime scripts.test.test_module_registry scripts.test.test_resource_manager_plans scripts.test.test_e2e_test_utils scripts.test.test_network scripts.test.test_verify_network_profiles`
9. Focused validation from the Phase-D prep slice is also green:
   - `python3 -m py_compile input/configuration/runtime_module_loader.py input/configuration/runtime_option_validation.py scripts/test/test_continuum_runtime.py application/runtime_helpers.py resource_manager/kubernetes/kubernetes.py scripts/test/test_application_runtime_helpers.py`
   - `env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers scripts.test.test_kubernetes_runtime scripts.test.test_continuum_runtime` (`84 tests OK`)
