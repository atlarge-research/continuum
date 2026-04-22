# Continuum Configuration Restructuring Design (YAML + Module Graph Aligned)

## 0. Authority and Boundary

This document is authoritative for YAML composition, parsing, validation, and runtime normalization.

Precedence and locked decisions are defined in `docs/rework_plan_stack.md`.
Software-model semantics are authoritative in `docs/software_module_architecture_plan.md`.

## 1. Goals

1. YAML-only runtime input (replace legacy INI/CFG path).
2. Keep volatility split between experiments and stable profiles.
3. Make infrastructure clusters first-class (`infrastructure.clusters[]`).
4. Encode target software model via `software.modules[]`.
5. Support benchmark-stage assignment via selectors/tags.
6. Enforce fail-fast validation + hard-cutover policy.
7. Produce deterministic normalized runtime config for execution code.

## 2. Configuration Model

Continuum composes three YAML documents:

1. ExperimentSpec (volatile)
2. EnvironmentProfile (stable)
3. SoftwareProfile (stable)

## 2.1 ExperimentSpec

Defines:

1. profile references (`use.environment`, `use.software`),
2. run targets (`run.targets`),
3. infrastructure clusters/resources/network intent,
4. benchmark/application domains with explicit assignment (where applicable).

## 2.2 EnvironmentProfile

Defines provider/environment settings (paths, provider options, network/IP settings).

## 2.3 SoftwareProfile

Defines software module instances (`software.modules[]`) with selectors and module-local config.

## 3. Directory and Resolution

Directory shape:

```text
configs/
  experiments/
  profiles/
    environment/
    software/
```

Resolution order:

1. explicit CLI path,
2. repo-local `configs/`,
3. optional `~/.continuum/configs/`.

## 4. Canonical YAML Shapes

## 4.1 ExperimentSpec (example)

```yaml
schema_version: 1
kind: ContinuumExperiment

use:
  environment: local-qemu
  software: cloud-k8s

run:
  targets: [infrastructure, software, application]
  image_prefetch: "off"
  dry_run: false
  clean: false

infrastructure:
  clusters:
    - id: cloud-1
      tier: cloud
      resources:
        vms:
          count: 2
          spec:
            cores: 4
            memory_gb: 16
    - id: endpoint-1
      tier: endpoint
      resources:
        vms:
          count: 1
          spec:
            cores: 2
            memory_gb: 4
  network:
    emulation: false
    wireless_preset: 4g
    overrides: {}

benchmark:
  pipeline:
    - id: classify-images
      type: image_classification
      assign_to: { match: { cluster: endpoint-1 } }
      tags: { benchmark.role: classify }
      config: { frequency: 2, duration: 120 }
    - id: translate-text
      type: text_translation
      assign_to: { match: { cluster: cloud-1, role: worker } }
      tags: { benchmark.role: translate }
      config: { frequency: 2, duration: 120 }
```

## 4.2 EnvironmentProfile (example)

```yaml
schema_version: 1
kind: ContinuumEnvironment

provider:
  name: qemu
  config:
    base_path: /home/user
    cpu_pin: false
    netperf: false
    delete_on_exit: false
    ip: { prefix: 192.168, middle: 100, middle_base: 90 }
```

## 4.3 SoftwareProfile (example)

```yaml
schema_version: 1
kind: ContinuumSoftware

software:
  modules:
    - id: k8s-main
      type: kubernetes
      assign_to: { match: { cluster: cloud-1 } }
      config: { kube_version: "v1.29.0" }

    - id: endpoint-runtime
      type: endpoint_runtime
      assign_to: { match: { cluster: endpoint-1 } }
      config: {}
```

Schema note:

1. user schema has no dependency edge field,
2. dependency/capability wiring is internal.

## 5. Composition and Normalization

Composition flow:

1. load ExperimentSpec,
2. resolve/load referenced EnvironmentProfile and SoftwareProfile,
3. validate all docs,
4. compose normalized object.

Normalized object includes resolved domains, targets, and derived fields needed by active runtime migration paths.
Cluster-level infra intent is normalized to concrete resource records with base tags (`tier`, `cluster`).

## 6. Validation Contracts

## 6.1 Global

1. `schema_version` + `kind` required and type-safe.
2. unknown/unexpected shapes fail fast.
3. validation/defaulting is front-loaded at parse/bootstrap boundaries; runtime config access paths read canonical keys directly and must not reintroduce fallback alias/default patching.
4. parser defaults apply only to omitted optional fields; explicit `null` for optional mapping objects is treated as invalid input and fails fast.

## 6.2 Run Targets

1. `run.targets` required and non-empty.
2. allowed targets: `infrastructure`, `software`, `application`.
3. invalid combinations fail fast.
4. `run.image_prefetch` is optional with allowed values `off` and `on`.
5. default `run.image_prefetch` is `off`.
6. parser/defaulting writes canonical `domains.run.image_prefetch`; runtime accessors treat this path as required and fail fast if missing.

## 6.3 Phase-Aware Domains

1. If `application` is selected, benchmark execution intent must be present (`benchmark.pipeline` minimum).
2. If `application` is not selected, `benchmark` must be omitted.
3. Benchmark stages use selector assignment and participate in the same deterministic placement model.
4. Runtime application execution now consumes canonical `benchmark.pipeline` intent directly; parser/normalization contracts remain authoritative.
5. Runtime config wiring must not project legacy `domains.workload.*`; application option wiring/verification runs against canonical `benchmark.pipeline[*].config`.

## 6.4 Infrastructure Clusters/Resources

1. `infrastructure.clusters[]` is required for infrastructure-capable runs.
2. cluster `id` is unique.
3. cluster `tier` limited to `cloud`, `edge`, `endpoint`.
4. resource counts are non-negative integers.
5. numeric resource constraints enforced.
6. all resources in a cluster receive base tags: `tier=<tier>`, `cluster=<id>`.
7. optional omitted resource fields receive documented defaults.
8. `infrastructure.image_prefetch` is invalid; image prefetch intent is modeled at `run.image_prefetch`.

## 6.5 Software Modules

1. `software.modules[]` must be a list of objects.
2. `id` unique within document.
3. `type` must resolve in module registry.
4. `assign_to.match` must be valid exact-match selector mapping (`{k: v}` equality predicates).
5. module-local `config` is required and must be a mapping, validated by module validator.
6. addon module config keys are registry-validated (unknown keys fail fast).

Selector canonicalization contract:

1. normalize selector to canonical object form: `{"match":[["k1","v1"], ...]}`.
2. sort selector pairs lexicographically by key, then value.
3. derive deterministic `selector_id` from canonical serialized representation.

## 6.6 Cross-Domain Consistency

1. selectors must resolve to at least one candidate VM.
2. internal dependency graph must be resolvable and acyclic.
3. scoped constraint conflicts fail with precise diagnostics.
4. benchmark selectors may depend on software-emitted tags and must resolve after software placement tags are available.
5. benchmark tags must not overwrite `tier`, `cluster`, or `role`; benchmark identity tags are namespaced (for example `benchmark.role`).
6. when endpoint resources exist and `run.targets` includes `software` or `application`, software modules must provide endpoint-runtime capability (currently via `endpoint_runtime` module).

## 6.7 Registry Prefetch Runtime Semantics

1. Local registry behavior is internal runtime implementation detail (not user-configurable schema).
2. Required images are derived internally from software/benchmark execution intent.
3. `run.image_prefetch: off` means pull/push only required images missing from local registry cache (repo + tag aware).
4. `run.image_prefetch: on` means force refresh pull/push for all required images.
5. Missing required images are always pulled regardless of prefetch mode.
6. Local registry is created/started only when required image pulls exist.
7. Initial software image-catalog coverage includes Kubernetes control-plane images for `kubecontrol`/`kube_kata`, resolved from orchestrator `kube_version`.
8. Baseline benchmark-stage catalog coverage includes `empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, and `text_translation`; `image_classification` mapping is stack-aware (`openfaas` => serverless publisher/subscriber images, otherwise container publisher/subscriber/combined images).
9. Unknown benchmark stage types fail fast during image requirement resolution.
10. `prefetch_image_requirements` is treated as a required, validated runtime invariant for registry flows; malformed payloads fail fast (missing key, wrong shape, invalid entries), and accepted entries are canonicalized (trimmed/deduplicated owners and tier targets).
11. Control-plane image resolution requires explicit orchestrator module config key `kube_version`; missing key is a hard failure (no runtime default fallback).
12. Image requirement discovery requires canonical normalized infrastructure resources at `normalized.infrastructure.resources`; missing path is a hard failure.
13. Registry migration/endpoint selection uses canonical infrastructure and SSH paths directly (`infrastructure.*_nodes`, `cloud_ssh`/`edge_ssh`/`endpoint_ssh`) with fail-fast errors on missing keys.
14. Image requirement tier-target derivation requires canonical selector-resolution metadata (`resolved_vm_ids`) and matching normalized resource records; missing/invalid mappings are hard failures.
15. Catalog expansion remains internal and is expected to continue alongside Phase D application execution integration.

## 6.8 Config Access Contract (Maintainability Balance)

1. Runtime config access must not use raw deep-index lookups outside `config_access` helpers.
2. Keep dedicated helpers for stable structural semantics only (for example: run-target resolution, orchestrator identity, module/stage lookup, capability predicates).
3. Dynamic parameter bags (`domains.benchmark.pipeline[].config`, module-local `config`) must use generic keyed accessors with explicit type conversion instead of one helper per individual key.
4. Generic keyed accessors are thin canonical reads (no runtime defaulting, no alias fallback, no schema repair).
5. Key-specific helpers are allowed only when they encode semantic behavior reused across multiple runtime surfaces.
6. Parser/bootstrap remains the single validation/default boundary; runtime accessor failures are invariant violations and must fail fast.
7. Maintain discoverability with one centralized key-catalog reference for dynamic parameter names to avoid implicit string scattering.
8. New accessor additions should follow a review rule: if the helper only forwards one key read, prefer a generic accessor call.
9. One-key orchestrator forwarders (`cache_worker_enabled`, `kube_deployment_mode`, `kube_version`, `runtime_name`) are removed; runtime callsites use generic `orchestrator_value` / `orchestrator_bool` reads directly.
10. Addon-specific booleans (`openfaas_enabled`, `observability_enabled`, `endpoint_runtime_enabled`) are removed; runtime callsites use `has_addon(config, "<addon>")` directly.
11. Orchestrator comparison helper `orchestrator_is(...)` is removed; callsites compare `orchestrator_name(config)` directly.

## 7. Parser/Runtime Pipeline

1. parse YAML docs,
2. validate schema + references,
3. normalize infrastructure clusters/resources into tagged resource records,
4. resolve dynamic module options/config access,
5. resolve selector-based software and benchmark assignments,
6. run compatibility checks,
7. persist lock metadata.

## 8. Lockfile

Write resolved lock artifact with:

1. source paths + hashes,
2. normalized config snapshot,
3. final resource list with tags,
4. software module assignments,
5. canonical selector objects + `selector_id` mappings,
6. canonical scope identity records for `vm`, `cluster`, `selector`,
7. benchmark stage assignments (or canonical selector identities for deterministic re-resolution),
8. software-produced artifacts/facts consumed by benchmark execution (when applicable),
9. reproducibility metadata.
10. lockfile re-validation requires derived selector fields (`selector`, `selector_id`, `resolved_vm_ids`, `scope_identities`) and enforces equality against recomputed selector resolution results.
11. planner handoff assignment records include `resolved_resources` derived from `normalized.infrastructure.resources`; each record contains `vm_id`, `cluster_id`, `tier`, `index_in_cluster`, and tags.

## 9. Migration Policy

1. YAML-only runtime support.
2. legacy INI/CFG path removed from active runtime.
3. no warning-based dual-format compatibility mode.

Optional tooling: one-shot converters outside runtime path.

## 10. Implementation Focus (Config Track)

1. canonical `infrastructure.clusters[]` parser/domain validation,
2. canonical `software.modules[]` parser/domain validation,
3. phase-aware benchmark-domain enforcement,
4. deterministic normalization compatible with active runtime callers,
5. selector plumbing shared by software and benchmark assignment,
6. example/profile YAML migration,
7. parser test expansion for IDs/types/selectors/cross-domain failures,
8. config-access rationalization to layered helpers + generic typed parameter readers.

## 10.1 Current Status Snapshot (Updated April 11, 2026)

1. PR-1 config-track cutover completed for canonical `clusters[]` + `modules[]` parser validation.
2. Active runtime now uses modules-only software config access (no compatibility projection for `software.orchestrator` / `software.addons`).
3. Repository software profiles and experiment fixtures are migrated to canonical schema and covered by parser/runtime tests.
4. PR-2 is completed with registry-backed dependency/capability checks in parser/runtime (including explicit dependency-edge rejection, endpoint-runtime capability enforcement, and exclusive-capability/conflict validation parity across parser/runtime).
5. PR-3 selector/scope hard cutover and PR-4 runtime/planner integration are complete; current focus moves beyond PR-5 closure into Phase D application-role consolidation and benchmark smoke/teardown validation now that runtime application execution is ungated.
6. PR-3A introduces `run.image_prefetch` (`off|on`) as the only user knob for registry prefetch intent; registry lifecycle remains internal and infra-executed.
7. PR-3A implementation includes deterministic control-plane image requirement resolution for `kubecontrol` and `kube_kata` with fail-fast unsupported-version validation.
8. PR-3A baseline now includes internal benchmark-stage catalog mappings for `empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, and `text_translation`, including stack-aware `image_classification` selection and fail-fast unknown-stage validation.
9. Legacy benchmark/workload compatibility helper stubs were removed from `config_access`; runtime callsites now use structural helpers plus generic benchmark parameter access (`benchmark_param*`) only.
10. `config_access` was additionally slimmed by removing unused wrapper helpers (`benchmark`, `orchestrator`, `orchestrator_config`) in favor of direct minimal-value access paths.
11. Parser-side benchmark stage config contracts are now enforced for known stage types (`empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, `text_translation`) with fail-fast required-key, type/range, and unknown-key validation.
12. Lockfile parsing now fails fast on missing/tampered/mismatched derived selector metadata (`selector`, `selector_id`, `resolved_vm_ids`, `scope_identities`) instead of silently recomputing over inconsistent values.
13. Lockfile writing is also invariant-driven for YAML runs: missing canonical `normalized`, invalid `normalized.sources`, or missing `infrastructure.base_path` now fail fast instead of silently skipping/falling back.
14. Planner snapshot lock metadata now includes software execution order, owner-tagged plan entries, software module assignments, and benchmark stage assignments when `run.targets` includes `application`.
15. Software and benchmark assignment records now include resolved resource handoff records from `normalized.infrastructure.resources`, and planner snapshot construction fails fast when assignment `resolved_vm_ids` do not map to normalized resource records.
16. Runtime helper access now includes fail-fast `config_access` readers for benchmark-stage planner assignments and resolved resource lists/counts, keeping benchmark handoff reads on canonical `planner_snapshot` metadata.
17. Runtime helper access now includes canonical software-module resolved-resource readers, allowing software-phase decisions to use module placement metadata instead of aggregate tier counts.
18. Endpoint-runtime validation is placement-aware: endpoint resources require an `endpoint_runtime` module whose resolved VM ids include endpoint resources, preventing configs that declare the capability on non-endpoint VMs from reaching runtime planning.
19. Module requirement validation now uses resolved selector scope: required provider capabilities must overlap the consumer module assignment, keeping module compatibility checks aligned with placement metadata.
20. Runtime software-phase endpoint-install and base-image gating now consume software-module planner snapshot assignment records for resolved-resource handoff, while planner snapshot construction itself uses canonical pre-snapshot module assignment metadata.
21. Benchmark-stage runtime handoff now has canonical primary and pipeline-ordered accessor bundles with assignment ids, pipeline indexes, deep-copied stage config, resolved resources, scope identities, benchmark tags, and deterministic tier counts; Kubernetes launch-variable preparation forwards this metadata through the application runtime path.
22. Software-module runtime handoff now has canonical single-module and module-ordered accessor bundles with assignment ids, module indexes, deep-copied module config, resolved resources, scope identities, and deterministic tier counts; endpoint-runtime install/base-image gating reads planner snapshot placement through this bundle, module-ordered construction matches planner assignments by module instance id, and id-based accessors are available for exact module-instance reads.
23. Kubernetes launch-variable preparation now forwards both benchmark and software handoff bundles through a combined `planner_runtime_handoff` payload, preserving one planner-derived config/placement object for Phase-D role/template consolidation.
24. Runtime accessors now mirror parser/domain duplicate-id invariants for `domains.benchmark.pipeline[].id` and `domains.software.modules[].id`, so exact-id handoff reads fail fast on malformed normalized/locked config.
25. Resource-manager module and endpoint helper `start()` hooks now delegate to the centralized `resource_manager.start()` entrypoint, preserving the PR-4 planner boundary even if a module hook is invoked directly.
26. PR-4 is complete; PR-5 owns examples/smokes/documentation closure before Phase D application-role consolidation.
27. PR-5 now publishes `docs/configuration_reference.md` and `docs/migration_notes.md` as the user-facing canonical-schema and hard-cut migration references, with `docs/cheatsheet.md` linking to them for first-line operator guidance.
28. Shipped experiment examples and shipped environment/software profiles are now regression-validated from disk by `scripts/test/test_example_configs.py`, and the example/doc baseline quotes `run.image_prefetch` values to avoid YAML boolean coercion.
29. The YAML e2e runner (`scripts/test/run_tests.py`) now validates `--suite` names against the loaded `scripts/test/test_config.json` content instead of a hard-coded CLI list, so config-declared suites such as `network_validation` are reachable without code changes.
30. The `network_validation` test suite is now correctly scoped to `configs/experiments/network_validation/`, and the test-runner/manifests/docs are updated to describe YAML-only suite discovery instead of legacy `.cfg` inputs.

## 11. Acceptance Criteria

1. active experiments parse through YAML pipeline,
2. invalid configs fail with precise key-path errors,
3. runtime behavior matches normalized contracts,
4. examples/tests stay aligned with parser/runtime semantics,
5. planning stack remains synchronized.
