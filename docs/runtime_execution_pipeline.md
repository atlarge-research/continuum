# Runtime Execution Pipeline

The [rework plan](rework_kickoff.md) sets release scope and the [certification matrix](release_certification_matrix.md) records factual evidence. The current checkout uses infrastructure → software → application. The [agreed target](#br23-benchmark-procedure-and-results) calls the final phase benchmark. Both use the QEMU resume boundary of same revision, base path, topology and software contract. Cross-commit resume, arbitrary software replacement and concurrent shared-base-path runs are unsupported. Use one active Continuum invocation per Unix account per physical host, even across base paths. Same-application parameter sweeps remain candidate-only. Although the current schema uses a pipeline list, `input/configuration/benchmark_domain_validation.py` rejects more than one executable stage.

This document describes the runtime execution pipeline that Continuum follows for YAML-driven runs, and ties each phase to the code that currently owns it.

The earlier Ansible restructuring phases are documented separately as a historical record. [Ansible restructuring](ansible_restructuring_design.md)

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

The user-visible `run.targets` values map to phases 1 to 3, but phase 0 and phase 4 are real execution boundaries and matter for both correctness and operational testing.

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
7. resolved experiment lock writing with the resume contract used by later state checks.

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
4. resolved lock file at `<base_path>/.continuum/experiment_lock.yaml`, including `resume_contract` metadata.

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
4. resume contract is stable across compatible retained phases,
5. runtime target resolution reports the expected executable phases.

## 4. Phase 1: Infrastructure Deployment

### Scope

This phase is responsible for turning normalized infrastructure intent into real machines, IPs, registry state, and optional network emulation.

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
4. optional network-validation NDJSON results under `<base_path>/.continuum/logs/network_validation/`,
5. schema-v2 state file at `<base_path>/.continuum/state.json` with `phase_completed=infrastructure` and matching `resume_contract`.

### Operational success evidence

1. `machines` is non-empty,
2. SSH targets exist in config/state,
3. provider resources are reachable,
4. network emulation or netperf artifacts appear when requested,
5. phase state file is written atomically with schema and resume-contract metadata.

## 5. Phase 2: Software Deployment

### Scope

This phase installs and configures the orchestrator and addon modules through the centralized software planner boundary.

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

The implemented hooks are resource-manager `build_phase_plan(config)` and optional `post_phase_hook(runner)`, with centralized addon entries and shared `PlanEntry` dispatch. See `docs/software_module_architecture_plan.md` §7–§9 for the current adapter contract, its fixed execution order and snapshot fields, distinguished from proposed module APIs.

### Outputs

1. installed orchestrator/addon software,
2. software execution order and assignment metadata already captured in `planner_snapshot`,
3. schema-v2 state file with `phase_completed=software`.

### Operational success evidence

1. all software plan entries execute successfully,
2. no direct module start path bypasses centralized planner execution,
3. post-phase hook completes,
4. state file advances from `infrastructure` to `software` without changing the resume contract.

## 6. Phase 3: Benchmark/Application Execution

### Scope

This phase launches benchmark workload logic and waits for completion.

### Current status

Application execution is now reachable for YAML runs. Phase D role consolidation moved benchmark launch and completion behavior under application-owned helpers and roles. `run.targets: application` no longer stops at runtime-target resolution and no longer silently skips when a runnable application module is missing.

### Primary code surfaces

1. `continuum.py` -> `application.start(runner)`
2. `application/application.py`
3. application modules under `application/`
4. `application/runtime_helpers.py`
5. application roles under `roles/application/`

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
5. host-backed benchmark smoke completes on the intended resume path with lightweight application-leg result evidence visible in stdout and in structured benchmark metric artifacts under `<base_path>/.continuum/logs/benchmark/`.

### BR23 benchmark procedure and results

The agreed target is one benchmark procedure per benchmark run and a portable result directory. The procedure is the final execution phase after infrastructure and software. It may deploy several workload components, drive traffic and collect several measurements. Bundled workload assets live in `applications/`. A project can supply its own assets or point to a pinned upstream workload. The benchmark module in `modules/benchmarks/` owns the procedure. A project under `projects/<study>/` runs cases through the CLI and produces cross-run analysis, tables and figures from saved results. The preceding sections describe current behavior.

The proposed first procedure for ordinary runs executes a finite workload and reports the observed outcome, workload logs and available start, readiness and completion timings. Include CPU and memory observations when the selected runtime exposes measurements attributable to the workload. Label their source, scope, units and sampling window. A missing observation is unavailable, and a required measurement missing from a study case makes its data incomplete. Use a procedure-defined measurement window for a service that has no natural completion. Specialized procedures keep workload-specific checks and outputs such as classification throughput and latency or instrumented startup traces. Extract common lifecycle and collection code where retained procedures use the same semantics.

#### Implementation sketch

1. **Resolve one procedure and its inputs.** Use the [configuration and module contract](configuration_restructuring_design.md#71-br23-configuration-and-module-cutover) to bind a locally registered benchmark and validate its module-owned workload options before provisioning. A proposed YAML shape is one `benchmark` mapping with `id`, `type`, `assign_to`, optional namespaced `tags` and `config`, with workload inputs under `config`. An ordinary run selects its procedure explicitly. The first external path accepts a digest-pinned OCI image. Feed that reference through the verified image requirements and launch path using module-declared inputs so each new image can be used without editing a central catalog. Add asset forms when a procedure needs them, such as checked project manifests with pinned image identities. Resolve source-relative inputs at configuration time. External asset references select inputs for the installed procedure.
2. **Launch and collect within the planned scope.** Start from the launch, wait and output-collection paths in `application/application.py` and `application/runtime_helpers.py`. Move procedure-specific logic to benchmark modules. Keep the single exact-match benchmark selector and bind any extra participants, such as cross-tier request drivers and control-plane actions, through explicit planned assignments or already bound software capabilities. Check the retained cross-tier cases when mapping their participants. Use the plan for launch, observation and cleanup of owned resources. Give the procedure the resolved inputs, scoped runtime context and result location.
3. **Finish a self-contained run record.** Adapt the existing JSON manifest and CSV writer to one directory per benchmark invocation with a versioned result manifest, run and procedure IDs, a snapshot of non-secret resolved inputs and their lock identity, pinned and observed asset identities where available, outcome, and relative paths to measurements and logs inside the directory. Keep native outputs such as CSV, NDJSON and trace files. Capture available evidence before releasing resources, including on failures, and finalize the manifest atomically after recording data completeness and any requested teardown result. Preserve the primary failure and distinguish it from cleanup failure. Expose the exact result directory in the CLI output. Update the smoke verifier and selected project readers to use that invocation's manifest.
4. **Prove both input paths and offline use.** Run a retained bundled case and a small digest-pinned external case through the same supported CLI on QEMU. Verify the launched image identity, placement, outcome and required artifacts. Move a result directory and read it offline without the deployment or original checkout. Exercise invalid workload inputs and out-of-scope placement before provisioning. Verify that missing required data and requested teardown failures are recorded separately and cannot pass the run's acceptance check. Use the external case to prove the workload-input boundary.

#### Reuse for measurement and analysis

Start with the existing file writer and use pandas and Matplotlib for study analysis where they fit. DuckDB is an optional offline study tool for querying many result files directly. A rebuildable SQLite index would be a separate future proposal if repeated cross-run lookup warrants a catalog. The run directory remains the record of the run and can be analyzed without a service. For live measurements, first check the runtime's existing sources, including Prometheus when an experiment selects the BR23 Kubernetes observability add-on. A procedure can query its measurement window and export the result before teardown. Evaluate additional collectors on a selected case using its metric semantics, completeness and measurement overhead. [BR23 monitoring scope](rework_kickoff.md#agreed-merge-scope) · [DuckDB file queries](https://duckdb.org/docs/stable/data/multiple_files/overview.html) · [SQLite use cases](https://sqlite.org/whentouse.html) · [Kube-burner time-windowed collection](https://kube-burner.github.io/kube-burner/latest/observability/metrics/)

### BR23 workload image release

Build each Continuum-owned release image when its workload source and build inputs are final. An existing immutable build can be reused when its provenance matches those inputs. Publish first-party images under `redplanet00` on Docker Hub and record the final repositories and digests in the frozen candidate. Publish finalized images earlier when authorized, or supply the unchanged final references through a verified staging mirror for acceptance. In the staging path, promote the exact tested index and platform manifests to Docker Hub before merge. Verify a clean public pull by digest and the image actually used after local registry staging. Give each released artifact a versioned reference and keep acceptance keyed to its digest. A change to a pinned repository or digest in the candidate follows the candidate replacement rules. [Docker digest semantics](https://docs.docker.com/dhi/explore/security-concepts/digests/) · [Existing translation build receipts](../application/text_translation/PROVENANCE.md)

Keep the build source revision distinct from the candidate commit that consumes the digest. Inventory the build context and Dockerfile, upstream base and lock inputs, model and data identities and distribution terms, platform, OCI index and platform manifest/config digests where applicable, registry path, and consuming cases. Verify cold pulls, mirror/cache identity and actual workload image identity from the planned cases. If an image changes, record its new identity and rerun the affected validation on the applicable frozen candidate. Verify repository access and upload authority for the selected namespace before publication. [Current image catalog](../input/configuration/image_requirements.py) · [Current cache verification](../infrastructure/image_registry.py)

| Inventory IDs | Current inputs and pre-merge disposition |
| --- | --- |
| `image-{combined,publisher,subscriber}` | `redplanet00/kubeedge-applications:image_classification_{combined,publisher,subscriber}` are mutable references. Use the combined, publisher and subscriber contexts under `application/image_classification/src/` with pinned base/dependencies, the reviewed image fixture and MobileNet model/labels as applicable. The paper cases, the DSL example, local processing, Mist and operational image runs reuse this set. Verify permission to distribute embedded assets or qualify replacements with documented provenance. |
| `image-{publisher,function}-{backend}` | For OpenFaaS use `image_classification_{publisher,subscriber}_serverless` in the same historical repository and port the `publisher_serverless` and `subscriber_serverless` builds. For Knative use a matched HTTP publisher and function wrapper with the same underlying classification inputs. Produce the pair for the selected backend and verify the image and route through Figure 7 and the retained operational case. |
| `empty-columbo`, `empty-kata`, `stress-cpu` | Current references are `redplanet00/kubeedge-applications:empty`, `ansk/empty:empty` and `ansk/empty:stress`. Inspect `application/empty/src` and `application/stress/src` for the Columbo and CPU build inputs. Both Kata build contexts are candidates. The historical helper publishes to `redplanet00`, so recover the exact `ansk/empty:empty` identity or qualify a documented replacement against R04. Verify trace markers for Columbo and Kata. The existing memory workload uses `app.empty`. Share a qualified image only where its workload and markers agree. |
| `translation-{publisher,subscriber}` | Start with the existing `redplanet00/continuum-text-translation-{publisher,subscriber}:en-nl-8aad73b-r1` CPU/amd64 builds. The index and local config pins are already recorded. Verify the platform manifests, locked model and dependencies, and reuse the pair if final inputs match. Otherwise build and publish new digests. [Translation provenance](../application/text_translation/PROVENANCE.md) |
| `tomato-function-{backend}` and any `tomato-driver` build | The current signal-classification files are a scaffold. Pin the fixture, preprocessing, model and expected outputs, then build the selected function and any containerized request driver. Reuse one artifact where the implementation uses the same image. Check the data, model and code terms separately. [R06 scope](reproduction_inventory.md#additional-nominated-workflows) |
| `wasm-workload`, `wasm-python-baseline` | Historical references are `macko99vu/wasmrust:latest` and `macko99vu/pythonbase:latest`. Recover pinned source and build inputs or qualify documented equivalents. Keep the same workload image across compatible Wasm handlers and the same Python image across Python arms. Record a separate verified artifact when a shim requires different packaging. Pin engine binaries and shims as guest dependencies. [Wasm matrix](reproduction_inventory.md#r12-webassembly-paper) |
| `mpi-array` | Build the array workload from the pinned tutorial Dockerfile and source. The historical `redplanet00/mpi-demo:array` tag serves launcher and workers. Pin the MPI base, and qualify the resulting image with the course operator. Keep the separate historical hello-world image as provenance unless the selected lesson needs it. [MPI source](https://github.com/atlarge-research/continuum/tree/db466d9ee50b771d411d18de17e3dcb720540ffa/application/mpi) |
| `external-proof` and upstream stack dependencies | Use one explicitly pinned external image for the ordinary benchmark contract. Expand the qualified rendered manifests into exact refs for Kubernetes, CNI, metrics, local registry, Jaeger, observability, the selected serverless stack and MPI Operator. Document which control-plane images are mirrors and which are instrumented builds. Track the node binary archive separately from the image pins and qualify both inputs for the affected cases. Pin Kata, KubeEdge, Wasm and Mahimahi guest artifacts as appropriate. Upstream dependencies are pinned in place. [Columbo build and artifacts](columbo_on_continuum.md#br23-instrumented-kubernetes) |

Retired provider or Mist-only paths and deferred projects stay outside the publication set. The inventory names current source references and target roles. Namespace access, final platform manifests and fresh published digests are checked during execution.

## 7. Phase 4: Artifact Capture, Resume, And Teardown

This is a cross-cutting runtime concern rather than a separately requested `run.targets` phase, but it is part of the pipeline.

### Owned behaviors

1. experiment lock writing during bootstrap before infrastructure or resume execution,
2. schema-v2 state persistence after each executable phase,
3. explicit resume validation by state schema, phase ordering, resume-contract hash, and an authenticated SSH marker from every recorded managed guest when skipping infrastructure,
4. final SSH access hints,
5. optional provider teardown when `delete_on_exit` is enabled, while retaining `state.json` as a last-known deployment snapshot and post-mortem artifact.

### Primary code surfaces

1. `input/configuration/experiment_lock_writer.py`
2. `infrastructure/state.py`
3. `continuum.py`
4. provider `delete_vms(...)` implementations
5. `scripts/test/run_tests.py` and `scripts/test/support/e2e_utils.py` for operational evidence checks

### Operational success evidence

1. the lock and persistent `state.json` are present and have matching `resume_contract` hashes,
2. resume is requested only by `run.targets` that omit infrastructure and rejects legacy, malformed, incompatible, or currently unreachable state cleanly,
3. final artifact/log locations are discoverable,
4. SSH preflight failure preserves `state.json` and occurs before Ansible, software, application, or new phase-state saves,
5. QEMU E2E success classification first binds `state.json` to the current run by requiring its timezone-aware save timestamp not to predate the freshly written experiment lock, then checks that teardown leaves no expected owner-scoped domains behind,
6. benchmark smoke reports a stable `teardown_failure` when retained QEMU domains remain after a delete-on-exit application leg.

The presence of `state.json` does not assert that infrastructure currently exists. It remains available after successful or failed teardown. A later explicit resume is currently supported only for QEMU, and may proceed only when all recorded guests are reachable. AWS, GCP, and bare-metal resume paths fail closed until their retained-provider lifecycle is supported and verified. Bare-metal remains release-unsupported independently of resume handling. The SSH marker proves authenticated command execution but does not provide stronger guest identity attestation.

## 8. Mapping To `run.targets`

`run.targets` is a request surface, not the full internal pipeline.

Current mapping:

1. `infrastructure` -> phases 0, 1, and 4
2. `software` -> phases 0, 1 or QEMU resume-from-1, 2, and 4
3. `application` -> phases 0, 1 or QEMU resume-from-1, 2 or QEMU resume-from-2, 3, and 4

Current runtime note:

1. `application` is parsed, planned, and executable,
2. benchmark smoke/teardown has a concrete runner evidence path,
3. Phase-E resume integrity uses the same contract in the lock and state artifacts.

## 9. Operational Testing Implications

The runtime pipeline should be tested at phase boundaries, not just by final pass/fail output.

Minimum assertions per phase:

1. Phase 0: parser succeeds or fails with the expected invariant error.
2. Phase 1: state file, SSH/IP materialization, and optional network artifacts exist and pass the structured netperf verifier when network validation is enabled.
3. Phase 2: centralized software plan executes and state advances to `software`.
4. Phase 3: benchmark artifacts and metrics are emitted, with runner-visible functional markers, stdout metric-table evidence, and structured metric-artifact sanity checks on the resumed K8s benchmark smoke path.
5. Phase 4: lock/state resume contracts match, explicit resume passes all-guest reachability, and teardown classification behaves consistently.

Use `docs/operational_testing_strategy.md` for the test strategy that sits on top of this phase model.

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
5. teardown only after the final phase, while retaining logs, lockfiles, and the last-known state snapshot.
