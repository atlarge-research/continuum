# YAML Migration Notes

This note covers the hard-cut migration from legacy config paths to the canonical YAML model.

## Scope

Runtime input-format support is separate from module-set release support. Exact
release-supported combinations are tracked in
`docs/release_certification_matrix.md`.

Supported runtime input formats:

- `.yaml`
- `.yml`

Removed runtime input formats:

- `.cfg`
- `.ts`

The CLI now fails fast on legacy input formats instead of projecting them into the active runtime.

## File Layout Migration

Old model:

- one legacy `.cfg` file with mixed sections

New model:

1. one `ContinuumExperiment`
2. one `ContinuumEnvironment`
3. one `ContinuumSoftware`

Example:

```yaml
schema_version: 1
kind: ContinuumExperiment

use:
  environment: local-qemu
  software: k8s-endpoint-runtime
```

## Removed Legacy Paths

### 1. `workload` -> `benchmark.pipeline`

Removed:

```yaml
workload:
  name: image_classification
  config: {}
```

Replacement:

```yaml
benchmark:
  pipeline:
    - id: classify
      type: image_classification
      assign_to: { match: { cluster: cloud-1 } }
      tags: { benchmark.role: classify }
      config:
        frequency: 2
        duration: 120
        applications_per_worker: 2
        application_worker_cpu: 0.5
        application_worker_memory: 1.0
        application_endpoint_cpu: 0.5
        application_endpoint_memory: 1.0
```

Important rules:

- `benchmark` must be present when `run.targets` includes `application`
- `benchmark` must be omitted otherwise
- stage ids must be unique
- benchmark-owned tags must stay namespaced, for example `benchmark.role`

### 2. `software.orchestrator` / `software.addons` -> `software.modules[]`

Removed:

- split orchestrator/addon runtime shape

Replacement:

```yaml
software:
  modules:
    - id: k8s-main
      type: kubernetes
      assign_to: { match: { cluster: cloud-1 } }
      config:
        kube_version: "v1.27.0"
        cache_worker: false
    - id: endpoint-runtime
      type: endpoint_runtime
      assign_to: { match: { cluster: endpoint-1 } }
      config: {}
```

Important rules:

- module ids must be unique
- module placement is explicit through `assign_to.match`
- module-local `config` is required even when empty

### 3. `infrastructure.image_prefetch` -> `run.image_prefetch`

Removed:

```yaml
infrastructure:
  image_prefetch: on
```

Replacement:

```yaml
run:
  image_prefetch: "on"
```

Allowed values:

- `off`
- `on`

Quote those values in YAML. Plain `off`/`on` may be parsed as booleans instead of strings.

### 4. Legacy benchmark sizing helper surface

Removed runtime helper concepts:

- `workload_*`
- ad hoc benchmark wrappers such as `applications_per_worker`, `worker_cpu_cores`, `worker_memory_gb`, `endpoint_cpu_cores`, `endpoint_memory_gb`

Replacement:

- canonical benchmark stage config fields under `benchmark.pipeline[].config`
- generic runtime reads through `config_access.benchmark_param*`

Examples:

- old `duration_s` fallback: removed
- canonical key: `duration`
- worker sizing keys:
  - `application_worker_cpu`
  - `application_worker_memory`
- endpoint sizing keys:
  - `application_endpoint_cpu`
  - `application_endpoint_memory`

### 5. Addon/orchestrator boolean wrappers

Removed:

- `openfaas_enabled`
- `observability_enabled`
- `endpoint_runtime_enabled`
- `orchestrator_is`

Replacement:

- `has_addon(config, "<addon>")`
- `orchestrator_name(config) == "<type>"`

## Fail-Fast Behavior to Expect

The YAML path is intentionally strict. Common migration failures now stop immediately:

- legacy `workload` key present
- `benchmark` present without `application` target
- `application` target present without `benchmark.pipeline`
- duplicate cluster/module/stage ids
- missing `software.modules[*].config`
- unknown benchmark config keys for known stage types
- unsupported provider/module/network override keys
- `endpoint_runtime` declared but assigned away from endpoint resources

## Practical Migration Pattern

1. Split the old config into experiment, environment, and software concerns.
2. Move provider defaults into the environment profile.
3. Move orchestrator and addon intent into `software.modules[]`.
4. Replace `workload` with `benchmark.pipeline`.
5. Replace legacy benchmark sizing names with canonical stage config keys.
6. Validate with a YAML experiment under `configs/experiments/`.

## Verified Example Baseline

The repository examples under `configs/experiments/` are regression-tested against the active parser. Start from one of those when migrating.
