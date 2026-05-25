# Continuum Post-Release Roadmap

## 1. Purpose

This document captures work that should follow the first final rework release.
It should not block the first certified module-set milestone or the old-main
parity release unless one of those releases explicitly claims the feature.

The release-readiness path is tracked in
`docs/rework_milestone_release_plan.md`, with exact release support claims in
`docs/release_certification_matrix.md`. This roadmap starts after that path has
produced a stable release that can replace old `main`.

## 2. Guiding Principles

1. Keep the Continuum core focused on structured planning, module contracts,
   runtime handoff, state, and evidence.
2. Add new research and teaching capabilities through modules, profiles,
   reproducibility packages, and optional services.
3. Prefer small release trains after the final rework release.
4. Do not add a database, frontend, or packaging system as a shortcut around
   missing module certification.
5. Treat paper claims as engineering claims: they need runnable evidence.

## 3. Stable Extension Model

Long-term goal:

1. make Continuum a robust hub for education and research packages without
   letting the core grow into project-specific code.

Possible work:

1. module manifests with declared capabilities, requirements, config schema,
   artifact outputs, and test fixtures,
2. a versioned Python hook interface for non-Ansible behavior,
3. clearer Ansible role conventions for install, launch, collect, and teardown,
4. compatibility checks between providers, software modules, and applications,
5. packaging/discovery rules for out-of-tree modules,
6. a small RFC/ADR process for changes that affect shared planning semantics.

Success criteria:

1. a new module can be added without editing core planner logic,
2. tests can certify a module set using declared contracts,
3. release notes can name module compatibility precisely.

## 4. Reproducibility Package Hub

Long-term goal:

1. present Continuum as a hub of reproducible distributed-systems experiments,
   course exercises, theses, and papers.

Possible work:

1. define a package format for experiments, profiles, scripts, docs, and
   expected artifacts,
2. catalog historical Continuum projects with status labels,
3. distinguish runnable packages, archived historical packages, and packages
   that require external credentials or hardware,
4. include citation, license, dataset, and artifact-badge metadata,
5. add package-level smoke tests where practical,
6. publish a documentation page that maps projects to certified module sets.

Success criteria:

1. users can find which package reproduces which project,
2. each package states whether it is currently runnable,
3. package docs point to exact configs and expected outputs.

## 5. Structured Experiment Data

Long-term goal:

1. move beyond ad hoc metric files while preserving simple local usage.

Possible work:

1. define a normalized run/experiment/result schema,
2. keep a local-first backend such as SQLite as the first implementation,
3. add optional external storage later only when a real workflow needs it,
4. import current CSV/manifest outputs into the schema,
5. record provenance: commit, config digest, module versions, host/provider
   metadata, and artifact locations,
6. support paper-ready exports without requiring a server.

Success criteria:

1. benchmark results can be queried across runs,
2. raw artifacts remain available,
3. users can reproduce how a table or figure was produced.

## 6. Visual Frontend

Long-term goal:

1. provide a usable frontend for configuration, monitoring, and results without
   replacing the CLI or hiding certification status.

Possible work:

1. configuration builder for experiments, environments, and software profiles,
2. module compatibility and certification-status view,
3. run launcher that shows prerequisites before provisioning,
4. live phase monitor using the runtime phase model,
5. artifact and result browser,
6. project/package browser for reproducibility packages.

Success criteria:

1. common workflows are easier than hand-editing YAML,
2. advanced users can still inspect and edit the generated YAML,
3. the UI makes uncertified module combinations visible.

## 7. Expanded Certification And CI

Long-term goal:

1. increase confidence in providers and modules without making every change wait
   for every expensive environment.

Possible work:

1. keep cloud-safe tests mandatory for every change,
2. run local VM smoke on a dedicated schedule or protected runner,
3. run cloud-provider tests on scheduled or release-candidate workflows,
4. store release evidence in durable artifacts,
5. track performance regressions separately from functional regressions,
6. maintain a small representative matrix instead of an unbounded cross product.

Success criteria:

1. each release knows exactly what was tested,
2. expensive provider tests are predictable and budget-aware,
3. failures point to provider, planner, software, application, or artifact layer.

## 8. Paper Track

Long-term goal:

1. publish the reworked Continuum as a higher-TRL framework for education and
   research across the digital continuum.

Possible work:

1. architecture section centered on the core/module split,
2. evaluation section based on certified module-set evidence,
3. case studies from reproducibility packages,
4. maintainability story comparing old ad hoc growth with structured planning,
5. testing story covering cloud-safe, VM-backed, and provider-backed evidence,
6. limitations section that names uncertified or deprecated paths honestly.

Success criteria:

1. paper claims map to runnable configs and recorded evidence,
2. case studies are packaged for external reproduction,
3. the repository docs and paper terminology match.

## 9. Suggested Release Train

1. R1: stabilization after final rework release
   - bug fixes, docs corrections, certification matrix maintenance.
2. R2: reproducibility package hub
   - package metadata, historical project catalog, package smoke checks.
3. R3: structured experiment data
   - local schema, imports, query/export workflow.
4. R4: visual frontend
   - configuration builder, run monitor, results browser.
5. R5: community and paper polish
   - external packaging docs, examples, case studies, and publication artifacts.
