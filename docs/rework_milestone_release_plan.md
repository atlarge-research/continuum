# Continuum Rework Milestone Release Plan

## 1. Purpose

This document defines the release path from the current rework branch toward a
stable Continuum release that can eventually replace the old `main` branch.

The plan deliberately separates:

1. core framework readiness,
2. provider and software-module certification,
3. old-main feature parity,
4. future product/research extensions.

The rework should ship through intermediate milestone releases first. A final
replacement release should happen only after the old public Continuum feature
surface is either VM-tested on the reworked stack or explicitly deprecated with
documented rationale and migration guidance.

## 2. Core Versus Modules

The Continuum core is the structured planning and runtime framework. It owns:

1. YAML/profile composition and schema validation,
2. normalized infrastructure, software, and benchmark domains,
3. selector and scope resolution,
4. module registry contracts and dependency/capability validation,
5. deterministic planner snapshots and runtime handoff metadata,
6. runtime phase gating, state, lock, and resume contracts,
7. test-runner success detection and artifact contracts.

Everything that deploys a concrete platform or workload is a module or module
family. This includes:

1. infrastructure providers such as `qemu`, `gcp`, `aws`, and `baremetal`,
2. resource-manager/software modules such as `kubernetes`, `kubeedge`, `mist`,
   `kubecontrol`, `kube_kata`, and `none`,
3. addons and execution modules such as `endpoint_runtime`, `openfaas`, and
   `observability`,
4. benchmark and application stages such as `image_classification`,
   `text_translation`, `stress`, `mem_usage`, `empty`, and `empty_kata`.

Important release boundary: `qemu` is an infrastructure provider module. It is a
high-value certification target because it enables local VM-backed testing, but
it is not part of the Continuum core.

## 3. Release Principles

1. Intermediate releases are milestone or pre-release artifacts, not final
   replacements for old `main`.
2. No public support claim is release-ready without full VM-backed evidence for
   that exact claim.
3. Static checks, unit tests, parser tests, and dry-run checks are mandatory,
   but they are not sufficient for runtime support claims.
4. A module combination is certified only for the provider, topology, software
   modules, benchmark stage, environment, and runtime targets that were tested.
5. The final replacement release must preserve old-main public functionality or
   document intentional removals before merge.
6. Evidence beats prose: every certified row needs a config, command, host or
   cloud prerequisites, artifacts, latest run date, and success criteria.
7. Keep the core small. New research or teaching features should arrive as
   modules, profiles, or reproducibility packages unless they change shared
   planning semantics.

## 4. Certification Labels

Use these labels consistently in docs, release notes, and issue planning.

| Label | Meaning |
| --- | --- |
| `core-ready` | Non-VM core behavior is covered by static checks, unit tests, parser/repository regressions, and runner metadata tests. |
| `certified` | The exact module set has fresh full VM-backed evidence for the release being prepared. |
| `certified-candidate` | The module set has passed before, but needs a fresh release-certification run before publication. |
| `ported-unverified` | Code/configs exist in the rework branch, but no current full VM-backed evidence is recorded. |
| `historical` | Legacy `.cfg` or research artifact exists, but the path is not yet ported or certified on the rework stack. |
| `deprecated-proposed` | Candidate for removal or demotion. Requires rationale, owner review, and migration/deprecation notes. |

Concrete row status is tracked in `docs/release_certification_matrix.md`.

## 5. Current Baseline

The current branch is being certified row by row for the structured planning
engine and first local module sets:

1. canonical YAML/profile parsing is implemented,
2. selector and scoped-planner behavior is covered by focused tests,
3. runtime handoff metadata is represented in lock/planner snapshots,
4. resume-state integrity is validated by lock/state contracts,
5. the local runner has phase-aware success detection and artifact checks,
6. cloud-safe unit/e2e-runner discovery is broad enough to catch many regressions.

The current M1 evidence snapshot certifies the first local QEMU/libvirt module
set in `docs/release_evidence_m1_2026-06-01.md`. The first old-main QEMU
infrastructure parity rows are recorded separately in
`docs/release_evidence_qemu_infra_parity_2026-06-01.md`, and the first
old-main QEMU Kubernetes no-benchmark parity row is recorded in
`docs/release_evidence_qemu_k8s_nobench_2026-06-01.md`. The KubeEdge
software-only subset row is recorded in
`docs/release_evidence_qemu_kubeedge_software_2026-06-01.md`, and the full
KubeEdge image-classification row is recorded in
`docs/release_evidence_qemu_kubeedge_image_2026-06-01.md`. The Mist
software-only subset row is recorded in
`docs/release_evidence_qemu_mist_software_2026-06-01.md`, and the full Mist
image-classification row is recorded in
`docs/release_evidence_qemu_mist_image_2026-06-01.md`. The endpoint-runtime
software-only subset row is recorded in
`docs/release_evidence_qemu_endpoint_software_2026-06-02.md`. The OpenFaaS
software-only single-host variant is recorded in
`docs/release_evidence_qemu_openfaas_software_2026-06-02.md`. If code, configs,
or runner semantics change before a tag is cut, the affected rows need fresh
evidence.

The M1 release-note wording is drafted in `docs/release_notes_m1_draft.md`.
Keep it synchronized with `docs/release_certification_matrix.md` before
publishing an intermediate release.

Certified local M1 module set:

1. provider module: `qemu`,
2. environment: local libvirt/KVM host,
3. software module: `kubernetes`,
4. addon/execution module: `endpoint_runtime`,
5. benchmark stage: `image_classification`,
6. network validation through the dedicated netperf path,
7. phase coverage: infrastructure, software, application, resume, artifact
   validation, and teardown.

Currently ported or present but not release-certified across the old-main public
surface:

1. provider modules: `gcp`, `aws`, `baremetal`,
2. software/resource-manager modules: `kubeedge`, `mist`, `openfaas`,
   `kubecontrol`, `kube_kata`,
3. addons and observability paths,
4. application and benchmark stages beyond the certified M1 path,
5. legacy research/demo configurations under `configuration/` that have not yet
   been mapped to YAML profiles and VM-backed evidence.

## 6. Old-Main Parity Inventory

Before the final replacement release, build a parity matrix from the old public
surface. The initial inventory comes from the old documentation and test
configuration tree:

1. provider coverage:
   - `configuration/tests/qemu/`,
   - `configuration/tests/gcp/`,
   - `configuration/tests/aws/01_infraonly-cloud.cfg`.
2. topology coverage:
   - cloud-only,
   - edge-only,
   - endpoint-only,
   - combined cloud/edge/endpoint.
3. software/resource-manager coverage:
   - Kubernetes image/build path,
   - KubeEdge application parity is certified only for `P-QEMU-06`; the
     software-only subset also remains certified for one QEMU topology,
   - Mist application parity is certified only for `P-QEMU-07`; the
     software-only subset also remains certified for one QEMU topology,
   - endpoint-only runtime path is certified for one QEMU topology, while the
     full endpoint image/build path still needs application evidence,
   - Kubernetes without benchmark,
   - Kubernetes plus OpenFaaS has a certified single-host software-only variant,
     while the exact legacy CPU shape and full application path still need
     evidence.
4. public feature coverage:
   - MQTT/operating service behavior,
   - Docker/containerd-backed resource-manager deployment,
   - benchmark/application execution and result collection,
   - machine-learning example workloads,
   - provider-specific cloud prerequisites and credentials.

For each parity row, decide one of three outcomes:

1. port and certify on the YAML rework stack,
2. keep as historical artifact only with clear user-facing wording,
3. deprecate/remove with explicit rationale and migration guidance.

The release-matrix checker treats this as checked planning state: every legacy
test config present in the current worktree or in the local `origin/main`
`configuration/tests/` inventory must have a row disposition in
`docs/release_certification_matrix.md`, and a git worktree must have the local
`origin/main` ref available for that inventory check. This keeps final
replacement planning anchored to the old public test surface even if files move
during the rework.

## 7. Evidence Required For A Certified Row

Every `certified` row must name:

1. the YAML experiment and profile files,
2. the exact runner suite or command,
3. provider, host, and credential prerequisites,
4. runtime targets covered: infrastructure, software, application, cleanup,
5. expected artifacts:
   - `<base_path>/.continuum/experiment_lock.yaml`,
   - `<base_path>/.continuum/state.json`,
   - relevant provider logs,
   - relevant software readiness logs,
   - relevant benchmark or network result artifacts.
6. success criteria beyond exit code,
7. latest run date and operator/runner context,
8. known limitations and skipped assertions.

Release notes should claim only rows that have this evidence.
The working row checklist and evidence template live in
`docs/release_certification_matrix.md`.

## 8. Milestones

### M0: Release-Readiness Documentation

Goal:

1. define the core/module boundary,
2. define certification labels,
3. document old-main parity as the final replacement gate,
4. connect operational testing policy to release claims.

Exit criteria:

1. this document exists and is linked from the planning stack,
2. future-release scope is separated from first-milestone release scope,
3. the docs avoid calling provider modules part of the core,
4. no milestone is presented as a final `main` replacement.

### M1: First Certified Module-Set Milestone

Goal:

1. publish a pre-release or milestone branch/tag for the structured core plus one
   fully tested vertical slice,
2. prove the planning engines, module contracts, runner, state, and artifacts can
   support a real end-to-end VM execution.

Target certified rows:

1. `core-ready` non-VM checks,
2. local `qemu` infrastructure-only smoke,
3. local `qemu + kubernetes` software smoke,
4. local `qemu` network-validation smoke,
5. local `qemu + kubernetes + endpoint_runtime + image_classification`
   benchmark smoke with resume and teardown.

Required work:

1. run the cloud-safe audit from a clean tree,
2. run the full local VM smoke matrix on the dedicated QEMU/libvirt host,
3. record evidence and artifact locations in release notes,
4. mark all other modules as `ported-unverified`, `historical`, or
   `deprecated-proposed`,
5. ensure pre-tag evidence names the exact commit being tagged and records a
   clean source-tree state,
6. publish as an intermediate release only.

### M2: Provider Parity Milestone

Goal:

1. close the provider gap between the rework branch and old `main`.

Target rows:

1. QEMU old-main parity rows,
2. GCP old-main parity rows,
3. AWS infra-only row,
4. bare-metal retained or deprecated based on explicit policy.

Required work:

1. port or validate YAML equivalents for the old provider test configs,
2. define cloud credential and quota prerequisites,
3. run full VM/cloud tests for each claimed row,
4. document provider-specific limitations and costs.

### M3: Software And Application Parity Milestone

Goal:

1. close old-main functionality gaps above the provider layer.

Target rows:

1. Kubernetes without benchmark,
2. Kubernetes plus OpenFaaS, where a single-host software-only variant is
   certified but exact-resource and application evidence remain open,
3. KubeEdge,
4. Mist,
5. endpoint-only runtime paths,
6. MQTT/operating-service behavior,
7. machine-learning benchmark/application paths that were public in old `main`.

Required work:

1. convert legacy configs to YAML profiles or declare them historical,
2. add scenario tests and success detection for each supported stack,
3. keep cross-product coverage bounded by certifying representative module sets,
4. avoid expanding the core to absorb per-project behavior.

### M4: Final Release Candidate

Goal:

1. prepare the first replacement candidate for old `main`.

Exit criteria:

1. every old-main public claim is `certified`, `historical`, or intentionally
   deprecated,
2. all release notes, README text, config docs, and migration notes agree,
3. the cloud-safe audit passes,
4. the certified VM/cloud matrix passes,
5. known limitations are documented in user-facing language,
6. upgrade and rollback guidance exists.

### M5: Main Merge And Final Release

Goal:

1. merge the reworked framework into `main` without surprising users with a
   smaller public feature surface.

Exit criteria:

1. M4 is complete,
2. old-main parity decisions are accepted by maintainers,
3. final release notes name certified module sets precisely,
4. post-release work is moved into issues or a project board.

## 9. Near-Term Work Queue

1. Keep `docs/release_certification_matrix.md` current as certification rows
   move from `ported-unverified` or `certified-candidate` to `certified`.
2. Keep the M1 cloud-safe audit fresh on the exact source tree being tagged.
3. Continue old-main QEMU software/application parity after the certified
   infra-only and Kubernetes no-benchmark rows.
4. Decide whether the final release should preserve every old provider/software
   row or explicitly deprecate some of them.
5. Add missing success detectors before claiming additional modules.
6. Keep README and docs language tied to certified rows rather than broad
   historical support statements.

## 10. Deferred Future Work

These are not blockers for M1 unless a release claim depends on them:

1. visual frontend,
2. structured experiment database,
3. durable reproducibility-package format,
4. public project/research package catalog,
5. paper-specific evaluation and figures,
6. major config-library migration,
7. long-term plugin/package distribution model.

The future roadmap is tracked separately in `docs/post_release_roadmap.md`.
