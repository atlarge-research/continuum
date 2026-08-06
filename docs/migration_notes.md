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
- module placement and its exhaustive authorization envelope are explicit through exactly one of
  `assign_to.match` or software-only `assign_to.any_of`; each clause is an exact-match AND and
  `any_of` is their set union
- module roles and topology may partition or validate the resolved envelope but may not expand it
- benchmark-stage placement remains match-only
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

## Legacy Configuration Backlog

The `configuration/` tree is retained as historical reproduction material and
migration reference, not as an active runtime entrypoint. As of the T10
inventory, it contains 259 legacy `.cfg` files. Keep the files in place unless
maintainers explicitly approve removal; migration work should add YAML examples,
release evidence, or historical/deprecation notes beside the existing records.

| Legacy Surface | Current YAML / Disposition | Next Action |
| --- | --- | --- |
| `configuration/tests/qemu/` | Old-main QEMU parity rows `P-QEMU-01` through `P-QEMU-10` have explicit YAML equivalents under `configs/experiments/parity/` and release status in `docs/release_certification_matrix.md`. | Maintain the certified parity YAML and evidence docs; rerun affected wrapper evidence before broadening or changing any certified QEMU claim. |
| `configuration/tests/gcp/` and `configuration/tests/aws/` | Historical only for M1. No provider YAML environment profiles, credential/cost docs, or cloud-backed evidence are present. | Decide per provider row whether to port, preserve as historical, or deprecate. Any certification needs provider-specific YAML profiles plus cloud prerequisites and evidence. |
| Root examples, `configuration/cellular_network/`, `configuration/network_validation/`, and `configuration/experiment_latency_variation/` | Representative local YAML examples and the dedicated network-validation YAML suite exist, but the broad legacy parameter sweeps are not one-for-one migrated. | Keep as historical sweeps unless a future release needs specific YAML coverage. Promote only selected cases with parser coverage, VM-backed evidence, and release-matrix rows when public support is intended. |
| `configuration/experiment_control/` | One minimal local-QEMU kubecontrol plus `empty` benchmark is certified as the M2 Columbo-style case-study row. The broader legacy control-plane microbenchmark sweeps remain unclaimed. | Keep the certified YAML/evidence row current. Before broader claims, restore or document the missing legacy control-plane trace points and add retained evidence for the selected deployment modes or sweeps. |
| `configuration/experiment_kata/` | The narrow local-QEMU `kube_kata` plus `empty_kata` startup row is certified as `M2-QEMU-KUBE-KATA-EMPTY`; broader startup variants and resource-usage sweeps remain unclaimed. | Keep the certified YAML/evidence row scoped to `kata-qemu` plus `overlayfs`. Decide separately whether remaining Kata runtimes, filesystems, topologies, or resource-usage sweeps become YAML examples, certified rows with fresh evidence, or historical artifacts. |
| `configuration/experiment_endpoint_scaling/`, `configuration/experiment_large_deployments/`, `configuration/experiment_provider/`, `configuration/experiment_serverless/`, and `configuration/observability/` | Some underlying modules have certified narrow YAML rows, but these legacy experiment families are not individually release-supported. | Group by intended public surface before porting. Either add scoped YAML examples and evidence for selected scenarios or record historical/deprecation disposition. |
| `configuration/kube_opencraft/` and `configuration/model/` | Research/demo artifacts only; no active YAML support claim. | Preserve as historical unless maintainers nominate a concrete release scenario with schema, config, and evidence requirements. |
| `scripts/migrate_cfg_to_yaml.py` converter output | The helper is a conservative bootstrap tool, but it still emits legacy-shaped fields such as `workload`, `software.orchestrator`, and `software.addons`. | Treat generated YAML as review material only. Before using converter output as an active example, update it to emit canonical `benchmark.pipeline` and `software.modules[]`, then validate with parser/unit coverage. |
