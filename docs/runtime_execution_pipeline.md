# Runtime Execution Pipeline

This document describes the runtime execution pipeline that Continuum follows
for YAML-driven runs, and ties each phase to the code that currently owns it.

It is intentionally separate from the program-level rework phases in
`docs/ansible_restructuring_design.md`.

## 1. Purpose

Use this document when you need to answer:

1. what happens between `python3 continuum.py <experiment>.yaml` and the final run output,
2. which artifacts are produced at each runtime phase boundary,
3. where operational smoke tests should assert success or failure,
4. how phase resume maps to the actual control flow.

## 2. Runtime Phase Model

Continuum's runtime pipeline currently has five practical phases:

0. bootstrap and planning,
1. infrastructure deployment,
2. software deployment,
3. benchmark/application execution,
4. artifact capture, state persistence, and optional teardown.

The user-visible `run.targets` values map to phases 1 to 3, but phase 0 and
phase 4 are real execution boundaries and matter for both correctness and
operational testing.

## 3. Phase 0: Bootstrap And Planning

### Scope

This phase happens before any VM provisioning or Ansible execution.

It covers:

1. YAML loading and profile composition,
2. schema validation and default materialization,
3. selector resolution and dependency/constraint checks,
4. module loading and runtime option validation,
5. deterministic planner snapshot construction,
6. runtime target gating,
7. resolved experiment lock writing.

### Primary code surfaces

1. `input/input.py`
2. `input/configuration/yaml_parser.py`
3. `input/configuration/profile_composition.py`
4. `input/configuration/runtime_option_validation.py`
5. `input/configuration/runtime_phase_targets.py`
6. `resource_manager/plans.py`
7. `input/configuration/experiment_lock_writer.py`

### Inputs

1. experiment YAML,
2. environment profile YAML,
3. software profile YAML,
4. local runtime environment needed for provider/module loading.

### Outputs

1. canonical `config` object,
2. `config["normalized"]`,
3. `config["planner_snapshot"]`,
4. resolved lock file at `<base_path>/.continuum/experiment_lock.yaml`.

### Failure classes

1. schema/key/type/default violations,
2. selector resolution or scope conflicts,
3. dependency/capability errors,
4. invalid provider/module option contracts,
5. invalid runtime target or resume-state prerequisites for the requested phases.

### Operational success evidence

1. config parses without `parser.error(...)`,
2. lock file is written,
3. planner snapshot exists and matches canonical config,
4. runtime target resolution reports the expected executable phases.

## 4. Phase 1: Infrastructure Deployment

### Scope

This phase is responsible for turning normalized infrastructure intent into
real machines, IPs, registry state, and optional network emulation.

### Primary code surfaces

1. `continuum.py` -> `infrastructure.start(config)`
2. `infrastructure/infrastructure.py`
3. `infrastructure/image_registry.py`
4. provider modules under `infrastructure/<provider>/`
5. `infrastructure/network.py`
6. `infrastructure/state.py`

### Responsibilities

1. physical-machine discovery and scheduling,
2. cleanup of old VMs and temp data,
3. `.continuum` workspace preparation,
4. VM naming and IP assignment,
5. required image resolution and local registry setup,
6. provider-side provisioning,
7. optional network emulation,
8. optional netperf collection,
9. infrastructure state persistence.

### Outputs

1. live machine inventory,
2. SSH/IP materialized in runtime config,
3. optional local registry content,
4. optional network-validation NDJSON results,
5. state file at `<base_path>/.continuum/state.json` with `phase_completed=infrastructure`.

### Operational success evidence

1. `machines` is non-empty,
2. SSH targets exist in config/state,
3. provider resources are reachable,
4. network emulation or netperf artifacts appear when requested,
5. phase state file is written.

## 5. Phase 2: Software Deployment

### Scope

This phase installs and configures the orchestrator and addon modules through
the centralized software planner boundary.

### Primary code surfaces

1. `continuum.py` -> `resource_manager.start(runner)`
2. `resource_manager/resource_manager.py`
3. `resource_manager/plans.py`
4. resource-manager modules under `resource_manager/`
5. `playbooks/resource_manager/`
6. `infrastructure/state.py`

### Responsibilities

1. derive ordered software plan entries,
2. execute RM/addon playbooks through the shared runner,
3. enforce endpoint-runtime placement gating,
4. run resource-manager post-phase hooks,
5. persist software-phase resume state.

### Outputs

1. installed orchestrator/addon software,
2. software execution order and assignment metadata already captured in `planner_snapshot`,
3. state file with `phase_completed=software`.

### Operational success evidence

1. all software plan entries execute successfully,
2. no direct module start path bypasses centralized planner execution,
3. post-phase hook completes,
4. state file advances from `infrastructure` to `software`.

## 6. Phase 3: Benchmark/Application Execution

### Scope

This phase launches benchmark workload logic and waits for completion.

### Current status

Application execution is now reachable for YAML runs.
Phase D still owns the remaining role consolidation and the operational
benchmark smoke/teardown closure, but `run.targets: application` no longer
stops at runtime-target resolution.

### Primary code surfaces

1. `continuum.py` -> `application.start(runner)`
2. `application/application.py`
3. application modules under `application/`
4. resource-manager launch helpers, especially `resource_manager/kubernetes/kubernetes.py`

### Responsibilities

1. deploy workers/endpoints/functions,
2. wait for benchmark completion,
3. collect raw worker and endpoint output,
4. convert raw output into metrics,
5. format final benchmark results.

### Operational success evidence

1. benchmark deployment starts on the intended platform,
2. worker and endpoint outputs are collected,
3. benchmark metrics are formatted without runtime fallback aliases,
4. state file advances to `phase_completed=application`,
5. host-backed benchmark smoke and teardown complete on the intended resume path.

## 7. Phase 4: Artifact Capture, Resume, And Teardown

This is a cross-cutting runtime concern rather than a separately requested
`run.targets` phase, but it is part of the pipeline.

### Owned behaviors

1. experiment lock writing before infrastructure/software/application execution,
2. state persistence after each executable phase,
3. resume validation when skipping earlier phases,
4. final SSH access hints,
5. optional infrastructure teardown when `delete` is enabled.

### Primary code surfaces

1. `input/configuration/experiment_lock_writer.py`
2. `infrastructure/state.py`
3. `continuum.py`
4. provider `delete_vms(...)` implementations

### Operational success evidence

1. lock and state files are present and internally compatible,
2. resume rejects incompatible state cleanly,
3. final artifact/log locations are discoverable,
4. teardown leaves no unexpected provider resources behind when requested.

## 8. Mapping To `run.targets`

`run.targets` is a request surface, not the full internal pipeline.

Current mapping:

1. `infrastructure` -> phases 0, 1, and 4
2. `software` -> phases 0, 1 or resume-from-1, 2, and 4
3. `application` -> phases 0, 1 or resume-from-1, 2 or resume-from-2, 3, and 4

Current runtime note:

1. `application` is parsed, planned, and executable,
2. benchmark smoke/teardown remains the active operational closure step.

## 9. Operational Testing Implications

The runtime pipeline should be tested at phase boundaries, not just by final
pass/fail output.

Minimum assertions per phase:

1. Phase 0: parser succeeds or fails with the expected invariant error.
2. Phase 1: state file, SSH/IP materialization, and optional network artifacts exist.
3. Phase 2: centralized software plan executes and state advances to `software`.
4. Phase 3: benchmark artifacts and metrics are emitted once ungated.
5. Phase 4: lock/state/resume/teardown artifacts behave consistently.

Use `docs/operational_testing_strategy.md` for the test strategy that sits on
top of this phase model.

Current lightweight smoke baseline:

1. infrastructure-only: `configs/experiments/smoke/infra_one_vm.yaml`
2. infrastructure plus software: `configs/experiments/smoke/software_k8s_two_vm.yaml`
3. network validation: `configs/experiments/smoke/network_netperf_two_vm.yaml`
4. benchmark smoke:
   - `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`
   - `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`
   - `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`

Preferred operational shape for the Kubernetes path:

1. bootstrap and planning on the benchmark-capable smoke config,
2. infrastructure deployment and verification,
3. resume into software deployment and verification on the same VMs,
4. resume into benchmark execution on the same VMs,
5. teardown only after the final phase, while retaining logs, lockfiles, and state artifacts.
