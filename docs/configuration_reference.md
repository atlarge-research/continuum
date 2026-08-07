# YAML Configuration Reference

This is the user-facing reference for Continuum's YAML input model.

Continuum uses three YAML document kinds:

1. `ContinuumExperiment`: the runnable experiment file
2. `ContinuumEnvironment`: the provider/environment profile
3. `ContinuumSoftware`: the software/orchestrator profile

The active examples live under `configs/experiments/`.

This reference documents the schema and module identifiers accepted by the
rework parser. It is not a release-support matrix. Runtime support claims are
limited to the rows marked `certified` in `docs/release_certification_matrix.md`.

## File Model

An experiment references one environment profile and one software profile:

```yaml
schema_version: 1
kind: ContinuumExperiment

use:
  environment: local-qemu
  software: k8s-endpoint-runtime
```

Profile references resolve in this order:

1. relative to the experiment file,
2. relative to the repository root,
3. `configs/profiles/<kind>/`,
4. `~/.continuum/configs/profiles/<kind>/`.

## Experiment Schema

Top-level keys for `ContinuumExperiment`:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema_version` | integer | yes | Must be `1` |
| `kind` | string | yes | Must be `ContinuumExperiment` |
| `use` | mapping | yes | Profile references |
| `run` | mapping | yes | Phase selection and runtime flags |
| `infrastructure` | mapping | yes | Cluster topology and network |
| `benchmark` | mapping | only when `run.targets` includes `application` | Must be omitted otherwise |

### `use`

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `environment` | string | yes | Environment profile reference |
| `software` | string | yes | Software profile reference |

### `run`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `targets` | list of strings | yes | none | Non-empty, no duplicates |
| `image_prefetch` | string | no | `"off"` | Allowed: `"off"`, `"on"` |
| `prepare_for_resume` | boolean | no | `false` | Only valid with `targets: [infrastructure]`; prepares retained infra for later resume |
| `dry_run` | boolean | no | `false` | Parser-owned default |
| `clean` | boolean | no | `false` | Parser-owned default |

Allowed `run.targets` values:

- `infrastructure`
- `software`
- `application`

`application` enables phase-3 benchmark/application execution and requires a `benchmark.pipeline` definition.

`prepare_for_resume: true` keeps selected later-phase software prerequisites available during an infrastructure-only retained run. Use it only for retained-resume workflows such as the benchmark smoke infrastructure leg; generic infrastructure-only runs should leave it omitted or `false`.

Use quotes for `image_prefetch` values in YAML examples. Plain `off`/`on` can be loaded as booleans by YAML parsers.

## Infrastructure Schema

Top-level `infrastructure` keys:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `clusters` | list | yes | Non-empty |
| `network` | mapping | no | Defaults are materialized by parser |

### `infrastructure.clusters[]`

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Unique across clusters |
| `tier` | string | yes | `cloud`, `edge`, or `endpoint` |
| `resources` | mapping | yes | Currently only `vms` |

### `infrastructure.clusters[].resources.vms`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `count` | integer | yes | none | `>= 0` |
| `spec` | mapping | no | parser fills defaults | VM resource specification |

### `infrastructure.clusters[].resources.vms.spec`

| Key | Type | Required | Default when `count > 0` | Notes |
| --- | --- | --- | --- | --- |
| `cores` | integer | no | `1` | Must be `>= 1` when `count > 0` |
| `memory_gb` | number | no | `1.0` | Must be `>= 0` |
| `cpu_quota` | number | no | `1.0` | Must be `>= 0` |
| `storage_read_mbps` | number | no | `0.0` | Must be `>= 0` |
| `storage_write_mbps` | number | no | `0.0` | Must be `>= 0` |

### `infrastructure.network`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `emulation` | boolean | no | `false` | Enable network emulation |
| `wireless_preset` | string | no | `4g` | Non-empty string |
| `overrides` | mapping | no | `{}` | Only supported override keys allowed |

Supported network override keys:

- Numeric: `cloud_latency_avg`, `cloud_latency_var`, `cloud_throughput`, `edge_latency_avg`, `edge_latency_var`, `edge_throughput`, `cloud_edge_latency_avg`, `cloud_edge_latency_var`, `cloud_edge_throughput`, `cloud_endpoint_latency_avg`, `cloud_endpoint_latency_var`, `cloud_endpoint_throughput`, `edge_endpoint_latency_avg`, `edge_endpoint_latency_var`, `edge_endpoint_throughput`
- String: `cloud_location`, `edge_location`

## Environment Profile Schema

`ContinuumEnvironment` currently defines `provider`.

Top-level keys:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema_version` | integer | yes | Must be `1` |
| `kind` | string | yes | Must be `ContinuumEnvironment` |
| `provider` | mapping | yes | Provider selection and config |

### `provider`

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | Non-empty provider name |
| `config` | mapping | no | Defaults filled by parser |

### `provider.config`

| Key | Type | Required | Default |
| --- | --- | --- | --- |
| `base_path` | string | no | `$HOME` |
| `cpu_pin` | boolean | no | `false` |
| `external_physical_machines` | list of strings | no | `[]` |
| `ip` | mapping | no | `{prefix: "192.168", middle: 100, middle_base: 90}` |
| `netperf` | boolean | no | `false` |
| `delete_on_exit` | boolean | no | `false` |

### `provider.config.ip`

| Key | Type | Required | Default |
| --- | --- | --- | --- |
| `prefix` | string | no | `"192.168"` |
| `middle` | integer | no | `100` |
| `middle_base` | integer | no | `90` |

## Software Profile Schema

Top-level keys for `ContinuumSoftware`:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema_version` | integer | yes | Must be `1` |
| `kind` | string | yes | Must be `ContinuumSoftware` |
| `software` | mapping | yes | Contains `modules` |

### `software.modules[]`

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Unique module instance id |
| `type` | string | yes | Accepted module type |
| `assign_to` | mapping | yes | Exhaustive resource authorization envelope |
| `config` | mapping | yes | Module-local config |

Software `assign_to` accepts exactly one of `match` or `any_of`. `match` is one
exact-match clause with implicit AND across its key/value predicates:

```yaml
assign_to:
  match:
    cluster: cloud-1
```

`any_of` is the set union of exact-match AND clauses:

```yaml
assign_to:
  any_of:
    - cluster: cloud-1
    - cluster: edge-1
```

The resolved resources are the module's exhaustive authorization envelope. Module roles,
capabilities, and topology rules may partition or validate resources inside that envelope, but
must never implicitly add resources outside it. `any_of` is software-only; benchmark-stage
selectors remain match-only.

Accepted module types:

- Orchestrators: `none`, `kubernetes`, `kubeedge`, `kubecontrol`, `kube_kata`, `mist`
- Addons: `endpoint_runtime`, `openfaas`, `observability`

Current module config keys:

| Module Type | Keys |
| --- | --- |
| `none` | none |
| `kubernetes` | `cache_worker`, `kube_version`, `kube_deployment` |
| `kubeedge` | `cache_worker`, `kube_version` |
| `kubecontrol` | `cache_worker`, `kube_version`, `kube_deployment` |
| `kube_kata` | `cache_worker`, `kube_version`, `kube_deployment`, `runtime`, `runtime_filesystem` |
| `mist` | none |
| `endpoint_runtime` | none |
| `openfaas` | none |
| `observability` | none |

Current enumerated module values:

- `kube_version`
  - `kubernetes`, `kubeedge`: `v1.27.0`
  - `kubecontrol`, `kube_kata`: `v1.27.0`, `v1.26.0`, `v1.25.0`, `v1.24.0`, `v1.23.0`
- `kube_deployment`: `pod`, `container`, `file`, `call`
- `runtime`: `runc`, `kata-qemu`, `kata-fc`
- `runtime_filesystem`: `overlayfs`, `devmapper`

## Benchmark Schema

`benchmark` is only valid when `run.targets` includes `application`.

Top-level keys:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `pipeline` | list | yes when benchmark is present | Exactly one stage currently |

The pipeline-shaped schema is retained for future ordered multi-stage execution. The current
execution boundary supports exactly one executable stage, so configurations and experiment locks
containing two or more stages fail validation instead of silently executing only the first stage.

### `benchmark.pipeline[]`

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Unique stage id |
| `type` | string | yes | Stage implementation name |
| `assign_to` | mapping | yes | Exact-match selector |
| `tags` | mapping | yes | Must use `benchmark.*` namespacing for benchmark-owned tags |
| `config` | mapping | yes | Stage-local contract |

Benchmark `assign_to` supports only one exact-match `match` clause. Software-only `any_of` is
not accepted for benchmark stages.

Known benchmark stage config contracts:

| Stage Type | Required Config Keys |
| --- | --- |
| `image_classification` | `frequency`, `duration`, `applications_per_worker`, `application_worker_cpu`, `application_worker_memory`, `application_endpoint_cpu`, `application_endpoint_memory` |
| `text_translation` | `frequency`, `duration`, `applications_per_worker`, `application_worker_cpu`, `application_worker_memory`, `application_endpoint_cpu`, `application_endpoint_memory` |
| `empty` | `sleep_time`, `applications_per_worker`, `application_worker_cpu`, `application_worker_memory` |
| `empty_kata` | `sleep_time`, `applications_per_worker`, `application_worker_cpu`, `application_worker_memory` |
| `mem_usage` | `applications_per_worker`, `application_worker_cpu`, `application_worker_memory` |
| `stress` | `stress_app_timeout`, `applications_per_worker`, `application_worker_cpu`, `application_worker_memory` |

Value rules:

- `applications_per_worker`, `duration`, `sleep_time`, `stress_app_timeout`: integer `>= 1`
- `frequency`
  - `image_classification`: integer `>= 1`
  - `text_translation`: number `> 0`
- CPU and memory sizing keys: number `>= 0.001`

Unknown config keys for known stage types fail fast.

## Shipped Examples and Profiles

These shipped examples and profiles are regression-validated from disk by
`scripts/test/e2e/test_example_configs.py`. A listed example is parser/profile
coverage; release-certified runtime support is tracked separately in
`docs/release_certification_matrix.md`.

Runnable experiment examples:

- `configs/experiments/bench_cloud.yaml`
- `configs/experiments/bench_cloud_openfaas.yaml`
- `configs/experiments/bench_edge.yaml`
- `configs/experiments/bench_endpoint.yaml`
- `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`
- `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`
- `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`
- `configs/experiments/infra_only.yaml`
- `configs/experiments/network_validation/bench_net_4g.yaml`
- `configs/experiments/parity/qemu/01_infraonly_cloud.yaml`
- `configs/experiments/parity/qemu/02_infraonly_edge.yaml`
- `configs/experiments/parity/qemu/03_infraonly_endpoint.yaml`
- `configs/experiments/parity/qemu/04_infraonly_all.yaml`
- `configs/experiments/parity/qemu_endpoint_image/08_endpoint_image_classification.yaml`
- `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml`
- `configs/experiments/parity/qemu_k8s_image/05_kubernetes_image_classification.yaml`
- `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml`
- `configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml`
- `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml`
- `configs/experiments/parity/qemu_kubeedge_image/06_kubeedge_image_classification.yaml`
- `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml`
- `configs/experiments/parity/qemu_mist_image/07_mist_image_classification.yaml`
- `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml`
- `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml`
- `configs/experiments/parity/qemu_openfaas_image_local/10_openfaas_image_classification_local.yaml`
- `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml`
- `configs/experiments/smoke/infra_one_vm.yaml`
- `configs/experiments/smoke/network_netperf_two_vm.yaml`
- `configs/experiments/smoke/software_k8s_two_vm.yaml`
- `configs/experiments/template.yaml`

Shipped environment and software profiles:

- `configs/profiles/environment/local-qemu-cpupin-delete-on-exit.yaml`
- `configs/profiles/environment/local-qemu-cpupin.yaml`
- `configs/profiles/environment/local-qemu-delete-on-exit.yaml`
- `configs/profiles/environment/local-qemu-netperf-ip101.yaml`
- `configs/profiles/environment/local-qemu-netperf.yaml`
- `configs/profiles/environment/local-qemu.yaml`
- `configs/profiles/environment/template.yaml`
- `configs/profiles/software/endpoint-runtime.yaml`
- `configs/profiles/software/k8s-endpoint-runtime.yaml`
- `configs/profiles/software/k8s-observability-endpoint-runtime.yaml`
- `configs/profiles/software/k8s-openfaas.yaml`
- `configs/profiles/software/k8s.yaml`
- `configs/profiles/software/kube-kata.yaml`
- `configs/profiles/software/kubecontrol.yaml`
- `configs/profiles/software/kubeedge-endpoint-runtime.yaml`
- `configs/profiles/software/kubeedge.yaml`
- `configs/profiles/software/mist-endpoint-runtime.yaml`
- `configs/profiles/software/none-edge.yaml`
- `configs/profiles/software/none-endpoint.yaml`
- `configs/profiles/software/none.yaml`
- `configs/profiles/software/template.yaml`

## Related Docs

- Planning/status: `docs/rework_kickoff.md`
- Parser/runtime design: `docs/configuration_restructuring_design.md`
- Software semantics: `docs/software_module_architecture_plan.md`
- Ansible/software install design: `docs/ansible_restructuring_design.md`
- Runtime phase flow: `docs/runtime_execution_pipeline.md`
- Operational test strategy: `docs/operational_testing_strategy.md`
