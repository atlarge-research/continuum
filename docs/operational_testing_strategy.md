# Operational Testing Strategy

This document defines how Continuum should be tested beyond unit tests.

The goal is to make operational tests phase-aware, reproducible, and useful
both for engineering handoff and for later research/reporting work.

## 1. Why Operational Tests Need A Separate Design

Unit tests cover parser helpers, selector logic, planner metadata, and narrow
runtime contracts. They do not prove that a real Continuum run:

1. provisions the expected resources,
2. persists the right artifacts between phases,
3. installs the requested software stack,
4. launches and measures a benchmark correctly,
5. resumes or tears down cleanly.

Operational tests must therefore be organized around the runtime phase model in
`docs/runtime_execution_pipeline.md`.

## 2. Test Layers

Continuum should keep four testing layers:

1. unit tests:
   - pure Python validation/planner/accessor behavior,
   - fast and mandatory for every change.
2. parser and repository regression tests:
   - shipped examples, profiles, manifests, runner metadata, and lockfile flow,
   - still local and fast.
3. operational smoke tests:
   - real executions on a minimal supported environment,
   - one or a few representative scenarios per runtime phase boundary.
4. scenario regressions:
   - broader provider/network/stack coverage,
   - slower and more environment-dependent.

## 3. Runtime Phases To Test

Operational testing should follow this pipeline:

0. bootstrap and planning,
1. infrastructure deployment,
2. software deployment,
3. benchmark/application execution,
4. artifact validation and teardown.

This extends the simpler user view of:

1. configuration,
2. infrastructure,
3. software,
4. benchmarking.

The extra pieces matter:

1. bootstrap/planning is where most fail-fast guarantees live,
2. artifact validation and teardown are required for resume correctness and
   reproducible reruns.

## 4. Phase-Specific Operational Assertions

### Phase 0: Bootstrap And Planning

Assert:

1. the YAML triplet composes successfully,
2. the lock file is written,
3. the planner snapshot exists,
4. invalid configs fail before provisioning starts.

Artifacts:

1. `<base_path>/.continuum/experiment_lock.yaml`
2. parser/runtime logs

### Phase 1: Infrastructure Deployment

Assert:

1. provider resources are created,
2. SSH/IP values are usable,
3. state file is written with `phase_completed=infrastructure`,
4. registry and netperf/network artifacts appear when requested.

Artifacts:

1. `<base_path>/.continuum/state.json`
2. provider logs
3. optional `logs/network_validation/netperf_results_<timestamp>.ndjson`

### Phase 2: Software Deployment

Assert:

1. centralized planner entries execute in deterministic order,
2. the requested orchestrator/addons are reachable after install,
3. state file advances to `phase_completed=software`.

Artifacts:

1. software-phase logs
2. persisted state after software completion

### Phase 3: Benchmark/Application Execution

Assert:

1. benchmark deployment launches on the intended platform,
2. worker and endpoint outputs are collected,
3. formatted benchmark metrics are emitted,
4. state file advances to `phase_completed=application`.

Current note:

1. runtime application execution is now ungated,
2. benchmark smoke and teardown remain the next operational closure step.

### Phase 4: Artifact Validation And Teardown

Assert:

1. resume works from saved state when earlier phases are skipped,
2. artifacts match the executed phase,
3. teardown removes resources at the end of the operational run,
4. rerunning from a clean environment remains deterministic.

## 5. Minimum Smoke Matrix

When a VM-capable test environment is available, the minimum smoke matrix
should cover one representative case for each active phase boundary.

Current recommended baseline:

1. parser/bootstrap only:
   - repository-wide shipped YAML parse and profile validation
   - already covered by unit/repository regression tests
2. infrastructure-only:
   - `configs/experiments/smoke/infra_one_vm.yaml`
   - proves phase 0 -> phase 1 -> phase 4
   - target shape: one cloud VM only
3. infrastructure plus software:
   - `configs/experiments/smoke/software_k8s_two_vm.yaml`
   - proves phase 0 -> phase 1 -> phase 2 -> phase 4
   - target shape: two cloud VMs with a lightweight Kubernetes install
4. network-validation infrastructure:
   - `configs/experiments/smoke/network_netperf_two_vm.yaml`
   - proves infra plus network emulation and netperf artifact collection
   - target shape: two VMs with simple netperf verification across the emulated link
5. benchmark/application:
   - `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`
   - `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`
   - `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`
   - proves the resumed infrastructure -> software -> application path on one shared base path
   - target shape: two cloud VMs plus one endpoint VM using the supported
     `kubernetes + endpoint_runtime + image_classification` path

Preferred execution shape:

1. Kubernetes benchmark smoke should use one resumed pipeline:
   - bootstrap on the benchmark-capable smoke config,
   - infrastructure verification,
   - resume into software verification on the same VMs,
   - resume into benchmark verification on the same VMs,
   - teardown only at the end via the final application-step environment profile.
2. Network validation remains a separate smoke path because it uses a different environment/profile
   and validates the networking subsystem rather than the Kubernetes benchmark path.

## 6. Success Evidence And Artifact Contract

Operational tests should record success through artifacts, not just exit code.

Required evidence classes:

1. command exit status,
2. Continuum log file,
3. experiment lock file,
4. phase state file,
5. provider-specific provisioning evidence,
6. software platform readiness evidence,
7. benchmark result evidence once application execution is enabled.

The existing runner stores summary JSON under `logs/test_results/`.
That should remain the top-level operational test index.
Each saved summary should also point at a sibling artifact directory containing
per-test `stdout.txt`, `stderr.txt`, and `metadata.json`, so failed VM-backed
smoke runs can be debugged without extracting blobs from one aggregate JSON file.
For YAML runs, the runner now also treats the resolved lockfile and saved state
file as part of the baseline success contract instead of relying only on exit
code and SSH output heuristics.

Concrete smoke success criteria currently agreed:

1. bootstrap:
   - the internal Continuum state accurately reflects the input configuration
   - lockfile and planner artifacts are written when expected
2. infrastructure:
   - provisioned VMs are reachable and can execute a trivial command such as `ls`
3. software:
   - the target platform is usable, for example `kubectl get nodes` returns both nodes in the
     two-VM Kubernetes smoke
   - Kubernetes is the canonical smoke-software target because it is the highest-value and most
     operationally complex software setup supported by Continuum
4. benchmark:
   - benchmark output/logs show a successful execution path and results are emitted
   - benchmark-smoke design should prioritize functional success over rich metrics for now
5. teardown/resume:
   - intermediate phases should reuse saved state rather than reprovisioning from scratch
   - all VMs should be cleaned up only at the end of the smoke run
   - exported state should remain available for inspection after the run
6. network validation tolerance:
   - observed latency and throughput should be within 25% of the expected profile values,
     or within 10 ms / 10 mbit respectively, whichever tolerance is larger

Suite behavior policy currently agreed:

1. smoke runs should fail fast,
2. artifact retention should be additive rather than cleanup-first,
3. benchmark and infrastructure/software smoke should prefer reusing the same VMs through phase
   resume where the runtime path supports it.
4. when an operational smoke fails, retained logs and SSH reachability should be used for diagnosis
   before attempting speculative reruns; direct VM inspection is an acceptable debugging step.
5. `docs/vm_debugging_runbook.md` is the standard first debugging reference for retained-VM
   inspection after smoke failures.
6. the e2e runner should reject a run as successful when the expected
   `experiment_lock.yaml` or `state.json` artifacts are missing, unreadable,
   or saved with the wrong `phase_completed` value for the requested target set.
7. failed runs should be classified into stable debugging buckets such as
   `timeout`, `missing_lock`, `missing_state`, `wrong_state_phase`,
   `missing_ssh`, `nonzero_exit`, or `ansible_failure` so smoke triage can
   focus on the right layer first.

## 7. Environment Matrix

"Required environments" means the execution contexts needed to exercise each operational test
layer. Different layers need different capabilities.

Operational testing should distinguish between:

1. local parser-only environments,
2. local VM-capable QEMU environments,
3. cloud-provider-capable environments,
4. specialized network-validation environments.

Not every environment can run every test layer.
The test design should therefore declare prerequisites explicitly for each suite.

Practical interpretation for the current smoke baseline:

1. parser/bootstrap regression:
   - any local dev environment
2. infrastructure and software smoke:
   - a local QEMU-capable environment with SSH/libvirt support
3. network-validation smoke:
   - a QEMU-capable environment with the extra host capabilities needed for emulated networking
4. benchmark smoke:
   - a QEMU-capable environment with the benchmark-specific runtime prerequisites; this remains the pending Phase-D operational slice

The runner should encode those prerequisites directly rather than rely only on
human-readable docs. The active suite contract is now:

1. `smoke` preflights host `virsh` and `ssh`,
2. `network_validation` preflights host `virsh`, `ssh`, and `tc`,
3. missing prerequisites fail before config discovery or VM provisioning starts.
4. operators can inspect the configured suite contract with
   `python3 scripts/test/run_tests.py --list-suites`.
5. operators can validate a specific host before a long smoke run with
   `python3 scripts/test/run_tests.py --suite <name> --check-prereqs`.
6. for least-privilege host execution, prefer a dedicated smoke user plus the
   wrapper documented in `docs/smoke_runner_isolation.md`.

## 8. Current Repository State

What is already covered:

1. parser and planner unit coverage,
2. shipped experiment/profile repository regression coverage,
3. YAML-only e2e runner metadata and suite selection coverage,
4. dedicated YAML network-validation suite selection in the runner,
5. suite-level prerequisite preflights for VM-backed smoke paths.
6. CLI inspection of suite metadata and prerequisite readiness.
7. real host-backed infrastructure smoke via `configs/experiments/smoke/infra_one_vm.yaml`,
8. real host-backed infrastructure-plus-software smoke via `configs/experiments/smoke/software_k8s_two_vm.yaml`,
9. real host-backed network/netperf smoke via `configs/experiments/smoke/network_netperf_two_vm.yaml`.

What remains open:

1. real host-backed execution of the resumed Kubernetes benchmark smoke pipeline,
2. teardown verification in real environments beyond the final-run delete contract,
3. benchmark/application artifact assertions tuned from real run output instead of design-only expectations.

## 9. Suggested Next Operational Work

Recommended order:

1. run the dedicated `benchmark_smoke` suite on a host-backed QEMU environment,
2. add explicit teardown verification to the real host-backed smoke path,
3. keep network-validation artifact checks aligned with the existing host-backed smoke runner output,
4. tighten benchmark-smoke artifact assertions once the first real host-backed run is green.

Cache-integrity note:

1. `.continuum` image reuse must not trust file existence alone,
2. QEMU base images are now considered reusable only when companion success metadata exists and
   matches the expected guest-user contract,
3. interrupted or partial base-image builds should therefore be invalidated and rebuilt instead of
   being silently reused on the next operational run.

## 10. How A User Or Research Collaborator Can Help

The most useful external input is not more ad hoc test cases. It is explicit
test policy.

High-value decisions:

1. which environments are considered required for release-quality smoke runs,
2. what counts as success evidence for each runtime phase,
3. which scenarios are mandatory for local development vs. CI vs. paper figures,
4. what failure taxonomy should be reported in test summaries,
5. which metrics and artifacts should be retained for reproducibility.

That policy can later be turned into:

1. concrete smoke manifests,
2. CI jobs,
3. operator runbooks,
4. methods sections for a paper.
