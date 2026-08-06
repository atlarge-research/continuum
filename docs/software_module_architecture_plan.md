# Software Module Architecture Plan (Final Target)

## 0. Authority

This document is the single source of truth for software schema and planner semantics.
Precedence/locking rules are defined in `docs/rework_plan_stack.md`.

## 1. Objective

Define a deterministic software execution model where:

1. infrastructure provides cluster-scoped base tags to resources,
2. software is a module-instance graph,
3. resource identity is tag-based,
4. dependency/capability wiring is internal registry logic,
5. software output is consumable by benchmark assignment/execution,
6. constraint validation is fail-fast.

## 2. Core Principles

1. User declares intent; system enforces semantics.
2. `id` = module instance, `type` = module implementation.
3. User controls assignment + module-local config only.
4. Dependencies are internal; no user dependency edges.
5. Deterministic placement, ordering, and execution.
6. Infra-owned tags are immutable from software modules.
7. A module assignment is an exhaustive authorization envelope: execution may not modify a
   resource outside its resolved assignment.

## 3. User-Facing Software Schema

```yaml
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

    - id: openfaas-main
      type: openfaas
      assign_to: { match: { cluster: cloud-1 } }
      config: {}
```

As an alternative to the Kubernetes orchestrator above, a KubeEdge deployment can declare its
complete cloud-and-edge authorization envelope with `any_of`:

```yaml
software:
  modules:
    - id: kubeedge-main
      type: kubeedge
      assign_to:
        any_of:
          - cluster: cloud-1
          - cluster: edge-1
      config: { kube_version: "v1.27.0" }
```

Schema rules:

1. `id` unique,
2. `type` registered,
3. `assign_to` contains exactly one of `match` or `any_of`,
4. `config` is required and must be a mapping (use `{}` when no keys are needed),
5. no user dependency edge field,
6. `match` is one exact-match AND clause,
7. `any_of` is the set union of exact-match AND clauses and is available only to software
   modules; benchmark-stage selectors remain match-only,
8. the resolved assignment is the module's exhaustive authorization envelope.

## 4. Resource Identity and Tag Contract

Each VM/resource record has:

1. `vm_id` (numeric unique ID),
2. `tags` (key-value identity map).

Required base tags:

1. `tier=cloud|edge|endpoint`
2. `cluster=<cluster-id>`

Base tags originate from `infrastructure.clusters[]` normalization and are applied to all resources in each cluster.

Reserved keys: `tier`, `cluster`, `role`.

Ownership and lifecycle:

1. Infrastructure owns `tier` and `cluster` (overwrite is a hard error).
2. Software may set `role` and module-scoped tags.
3. Benchmark may set namespaced benchmark tags (for example `benchmark.role`) and must not overwrite `role`.
4. Tag mutations must be deterministic and idempotent (re-runs cannot drift tags).

## 5. Module Registry (Internal Semantics)

Registry defines per-module static truths:

1. `requires`
2. `provides`
3. `exclusive_provides`
4. `conflicts`
5. config validation contract (including addon config allowlist keys)
6. optional deterministic placement strategy

User config does not redefine these semantics.

Registry may also expose internal image-catalog references for prefetch planning.
These are runtime-internal contracts (not user schema fields) and must remain deterministic.

Dependency strategy is explicit-only:

1. planner validates `requires` against user-declared module instances/capabilities,
2. missing requirements are hard failures with precise diagnostics,
3. planner does not auto-inject module instances.

## 6. Selector and Constraint Scope Semantics (Locked)

Selector language:

1. software selectors contain exactly one of `match: {key: value}` or
   `any_of: [{key: value}, ...]`.
2. each clause uses exact equality with implicit AND across pairs.
3. `any_of` is the set union of its clauses.
4. benchmark-stage selectors remain match-only.
5. no negation, range, regex, or implicit topology expansion is supported in this phase.

Canonical selector representation:

1. normalize to object form: `{"match":[["k1","v1"],["k2","v2"]]}`.
2. sort pairs lexicographically by key, then value.
3. normalize software unions to `{"any_of":[{"match":[...]}, ...]}` and sort clauses by
   canonical JSON.
4. serialize as canonical JSON for identity and lockfile use.
5. derive `selector_id` as `sel_<sha256-prefix>` from canonical JSON.

Authorization semantics:

1. the union of resolved VM ids is exhaustive: a module may not modify an unselected resource,
2. roles, capabilities, cardinality, and topology may partition or validate resources inside the
   envelope but may never expand it,
3. the current legacy Ansible group check is a temporary execution adapter, not canonical
   module-to-tier semantics; it is removable when execution consumes resolved assignments,
4. current post-phase hooks are verification-only and do not expand the mutation envelope.

Constraint scopes:

Target architecture supports:

1. `vm` scope,
2. `cluster` scope,
3. `selector` scope.

Canonical scope identity object:

1. `{"kind":"vm","vm_id":<int>}`
2. `{"kind":"cluster","cluster_id":"<id>"}`
3. `{"kind":"selector","selector_id":"sel_<hash>"}`

Violation diagnostics must include:

1. module instance IDs,
2. canonical scope identity object,
3. violated capability/constraint.

## 7. Module Runtime Contract

Expected module interface:

1. `validate_config(instance.config)`
2. `place(ctx, instance, candidate_vms) -> PlacementResult` (optional)
3. `apply(ctx, instance, selected_vms)`
4. `post_hook(ctx, instance)` (optional)

## 7.1 Contract Evolution Note (Post-Implementation)

1. Additional internal extension points (for example image requirement exposure for registry prefetch) should be standardized centrally after current PR-3/PR-4 delivery.
2. Keep module burden minimal by preferring core-managed catalogs/resolvers over ad-hoc module-side pull logic.
3. Any new extension point must preserve deterministic planning and fail-fast diagnostics.

## 8. Planner Semantics

Planner flow:

1. parse `software.modules[]`,
2. validate IDs/types/config shape,
3. canonicalize selectors and compute `selector_id` values,
4. resolve selectors to candidate VMs,
5. apply deterministic placement hooks,
6. build internal dependency graph,
7. validate graph (cycles, unresolved internal refs),
8. validate constraints at declared scope,
9. deterministic topological ordering,
10. execute `apply(...)` in order,
11. emit resolved software placement tags/artifacts for benchmark-stage resolver use.

Until assignment-scoped execution replaces the broad legacy inventory, planner validation maps
each software playbook's declared legacy target groups to normalized VM ids and rejects plans that
would exceed the owning module's authorization envelope. This adapter describes current executor
behavior only; literal legacy groups are not module requirements.

Determinism requirements:

1. candidate VMs sorted by `vm_id`,
2. stable tie-break by `instance.id`,
3. deterministic placement rules.

## 9. Lockfile

Persist resolved software artifact with:

1. final VM tags,
2. resolved module instances,
3. module-to-VM assignments,
4. resolved dependency edges,
5. execution order,
6. canonical selector objects + `selector_id` mappings,
7. canonical scope identity records for scoped diagnostics/replay,
8. software artifacts/facts exported for benchmark-stage execution,
9. benchmark-stage assignment snapshot (or canonical selector identity for deterministic re-resolution).

## 10. Migration Policy

1. hard cutover,
2. no long-lived dual runtime schema mode,
3. no warning-first compatibility policy.

Optional converters may exist outside runtime path.

## 11. Test Strategy

Unit tests:

1. schema validation (`software.modules[]`),
2. duplicate IDs / unknown types,
3. selector-empty failures,
4. cycle detection,
5. scoped constraint conflicts (`vm/cluster/selector`),
6. deterministic placement behavior.

Planner tests:

1. deterministic execution ordering,
2. dependency-respecting execution,
3. precise conflict diagnostics.

E2E smoke tests:

1. endpoint-only,
2. kubernetes + endpoint runtime,
3. kubernetes + openfaas + endpoint runtime,
4. incompatible module conflict must fail.

## 12. Decisions Locked

1. Internal-first dependency handling.
2. No user dependency edge field.
3. Explicit-only dependency strategy (no auto-injection).
4. Cluster-first base tagging from infrastructure (`cluster=<id>` for all resources in cluster).
5. Benchmark stages must support selector/tag assignment and software-tag handoff.
6. Selector language is exact-match only (`match: {k:v}` with implicit AND).
7. Selector identity uses canonical normalized JSON + `selector_id` hash.
8. Scope identity is structured (`vm`, `cluster`, `selector` objects).
9. Hard-fail reserved tag collisions.
10. Benchmark may not overwrite `role`; use benchmark namespaced tags.
11. Hard-cutover migration strategy.
12. Constraint scopes (`vm`, `cluster`, `selector`) are part of target architecture.

## 13. Immediate Implementation Focus (Software Track)

1. PR-1 completed: canonical `software.modules[]` parser enforcement with selector canonicalization baseline.
2. PR-2 completed: registry schema and explicit-only dependency/capability validation baseline are implemented in parser/runtime; incremental hardening includes exclusive-capability accounting and runtime conflict/exclusivity validation tests.
3. PR-3 completed: deterministic selector-resolution + scoped constraint engine (`vm`/`cluster`/`selector`) baseline is in place for software and benchmark assignment.
4. PR-4 completed: centralized software execution is planner-mediated, and benchmark handoff metadata is prepared for Phase-D runtime consumers.
5. PR-3A incremental baseline includes orchestrator image-catalog refs for `kubecontrol` and `kube_kata` plus baseline benchmark-stage catalog mappings (`empty`, `empty_kata`, `mem_usage`, `stress`, `image_classification`, `text_translation`) for internal registry prefetch resolution, including stack-aware `image_classification` image selection.
6. Current PR-4 handoff artifact: `planner_snapshot` assignment records include `resolved_resources` records derived from normalized infrastructure resources for software modules and benchmark stages.
7. Runtime helpers now pass benchmark `planner_snapshot` resolved-resource metadata forward as handoff data, preparing Phase-D execution without overloading one selector with application-role topology semantics.
8. Software phase endpoint-runtime install is gated by `endpoint_runtime` module placement on endpoint resources, keeping software execution aligned with module assignment semantics rather than aggregate endpoint counts.
9. Endpoint-runtime capability validation is placement-aware: endpoint resources require the `endpoint_runtime` provider to resolve onto endpoint VM resources, and base-image endpoint install planning reuses that same placement predicate.
10. Module `requires` validation is assignment-scope-aware: required capabilities must be provided by modules with overlapping resolved scope, so compatibility semantics follow placement rather than global module presence.
11. Runtime consumers now have software-module planner snapshot assignment readers for resolved-resource handoff; planner construction remains pre-snapshot and uses canonical module assignment fields to avoid circular dependency on its own artifact.
12. Benchmark runtime consumers now have canonical primary and pipeline-ordered handoff bundles for planner-stage assignments, including pipeline indexes, deep-copied stage config, scope identities, benchmark tags, and resource tier counts; this was the PR-4 handoff surface that Phase D later consumed after application execution was ungated.
13. Software runtime consumers now have canonical single-module and module-ordered software handoff bundles for planner assignment metadata, including module indexes and deep-copied module config; endpoint-runtime placement checks use the single-module bundle's tier counts while retaining the acyclic planner-construction path, module-ordered handoff construction matches assignments by module instance id, and id-based helpers cover exact module-instance reads.
14. Kubernetes runtime payloads carry a combined `planner_runtime_handoff` object with benchmark and software config/placement handoff bundles as Phase-D role/template inputs, without treating selector placement as application-role topology.
15. Runtime structural accessors reject duplicate benchmark stage ids and duplicate software module ids before exact-id handoff reads, preserving parser/domain identity invariants in locked-config consumers.
16. Resource-manager module and endpoint helper `start()` hooks delegate to the centralized `resource_manager.start()` entrypoint, preserving one software planner boundary even for direct module-hook callers.
