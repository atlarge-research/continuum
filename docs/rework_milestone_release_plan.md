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
surface is certified with provider-appropriate runtime evidence on the reworked
stack under the current checked model. Closing an unsupported surface without
certification first requires the separate atomic checked-disposition change
defined below.

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
2. No public runtime support claim is release-ready without the
   provider-appropriate runtime evidence required by its applicable gate in
   `docs/release_certification_matrix.md`. Depending on that explicit gate,
   the evidence may be VM-backed, cloud-backed, or host-backed.
3. Static checks, unit tests, parser tests, and dry-run checks are mandatory,
   but they are not sufficient for runtime support claims.
4. A module combination is certified only for the provider, topology, software
   modules, benchmark stage, environment, and runtime targets that were tested.
5. The final replacement release must preserve old-main public functionality
   under the current checked contract. An intentional unsupported closure first
   requires a separate atomic change adding an explicit checked terminal
   disposition.
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
| `certified` | The exact module set has fresh provider-appropriate runtime evidence required by its applicable certification-matrix gate. |
| `certified-candidate` | The module set has passed before, but needs a fresh release-certification run before publication. |
| `ported-unverified` | Code/configs exist in the rework branch, but no current full runtime evidence is recorded. |
| `historical` | A legacy `.cfg` or research artifact exists, but the path is not release-supported on the rework stack. This is not a final replacement disposition by itself. |
| `deprecated-proposed` | Candidate for removal or demotion. Requires rationale, owner review, and migration/deprecation notes. |

`docs/release_certification_matrix.md` is the sole authority for concrete row
status.

## 5. Current Baseline

The structured planning engine, canonical YAML/profile model, runtime handoff,
resume contract, phase-aware runner, and cloud-safe regression baseline are
implemented. This plan intentionally does not duplicate changing certification
statuses or dated evidence inventories.

`docs/release_certification_matrix.md` is the factual authority for current row
status, exact claim boundaries, and primary evidence. The current operational
checkpoint is `docs/rework_release_handoff.md`, and M1 publication wording is in
`docs/release_notes_m1_draft.md`.

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
3. software/resource-manager coverage, including Kubernetes, KubeEdge, Mist,
   endpoint runtime, observability, OpenFaaS, and application paths,
4. public feature coverage:
   - MQTT/operating service behavior,
   - Docker/containerd-backed resource-manager deployment,
   - benchmark/application execution and result collection,
   - machine-learning example workloads,
   - provider-specific cloud prerequisites and credentials.

For each parity row, the current checked outcomes are:

1. port and certify on the YAML rework stack, after which the row leaves
   `docs/old_main_parity_issue_seed.md`, or
2. remain unresolved under a non-terminal status and stay in that backlog.

If maintainers later choose to close an unsupported historical provider without
certification, that requires a separate atomic change introducing an explicit
checked terminal disposition and updating the matrix checker, certification
matrix, and parity seed together. This plan does not define that future
disposition.

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

This milestone name is independent of the retained `M2-*` identifiers used by
post-M1 research case-study rows in the certification matrix.

Goal:

1. close the provider gap between the rework branch and old `main`.

Target rows:

1. QEMU old-main parity rows,
2. GCP old-main parity rows,
3. AWS infra-only row,
4. bare-metal remains unclaimed unless certified; an unsupported terminal
   outcome requires the separate checked-disposition change described above.

Required work:

1. port or validate YAML equivalents for the old provider test configs,
2. define cloud credential and quota prerequisites,
3. satisfy the provider-appropriate runtime-evidence gate defined for each
   claimed row in `docs/release_certification_matrix.md`, using VM-backed,
   cloud-backed, or host-backed evidence only where that gate permits it,
4. document provider-specific limitations and costs.

### M3: Software And Application Parity Milestone

Goal:

1. close old-main functionality gaps above the provider layer.

Target rows:

1. remaining uncertified or historical software/application rows in the
   certification matrix,
2. MQTT/operating-service behavior,
3. machine-learning benchmark/application paths that were public in old `main`.

Required work:

1. convert legacy configs to YAML profiles or declare them historical,
2. add scenario tests and success detection for each supported stack,
3. keep cross-product coverage bounded by certifying representative module sets,
4. avoid expanding the core to absorb per-project behavior.

### M4: Final Release Candidate

Goal:

1. prepare the first replacement candidate for old `main`.

Exit criteria:

1. every old-main public claim is `certified` under the current checked model;
   any unsupported terminal closure first lands as a separate atomic checked-
   disposition change,
2. all release notes, README text, config docs, and migration notes agree,
3. the cloud-safe audit passes,
4. every certified row's provider-appropriate runtime-evidence gate in
   `docs/release_certification_matrix.md` passes,
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

1. Keep `docs/release_certification_matrix.md` as the sole current row-status
   and evidence ledger.
2. Keep the cloud-safe audit and affected runtime evidence fresh on the exact
   source tree being tagged.
3. Keep historical and other non-ready surfaces unresolved and in the parity
   backlog until certified; scope any unsupported terminal closure as a
   separate atomic checked-disposition change.
4. Keep public documentation tied to matrix claim boundaries.

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
