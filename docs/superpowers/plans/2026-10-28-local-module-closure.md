# Continuum continuation: a polished core and validated local modules

Approved on 2026-10-28. This is a bounded execution plan subordinate to
the policies and domain authorities mapped in `docs/rework_plan_stack.md`.
It defines an intermediate engineering checkpoint, not release certification.

## 1. Goal and boundaries

Reach a coherent, review-ready engineering checkpoint before reconsidering the architecture.

The checkpoint includes the existing core, QEMU, Kubernetes, endpoint runtime,
KubeEdge, Mist, OpenFaaS, observability, and the approved Columbo and Kata slices.
Application coverage is image classification, `empty`, and `empty_kata`.

Preserve the longer-term destination: one main branch with historical functionality
integrated through understandable interfaces. This milestone does **not** require
restoring every historical feature.

Continue the current design. Fix demonstrated defects, incomplete integration,
misleading interfaces and missing validation; do not introduce a new plugin
architecture, frontend, configuration system or orchestration framework.

Translation, stress/memory benchmarks, cloud providers, baremetal and other
historical research families remain explicit restoration backlog items—not deleted
or declared supported.

## 2. Execution across fresh agents

After approval:

- Save this plan as
  /home/matthijs/continuum/docs/superpowers/plans/2026-10-28-local-module-closure.md.
  Update the existing [handoff](../../rework_release_handoff.md) with the actual
  checkpoint, carried changes, evidence locations and next task. Keep it subordinate
  to existing policy.
- You open **one new coordinator task** pointing to that saved plan. This long
  conversation stops being the implementation workspace.
- The coordinator delegates each bounded implementation task to a fresh-context
  agent. Separate read-only agents review its plan and complete uncommitted changes.
- Allow only one writer to the integration checkout and one physical-host workflow
  at a time. Parallelize independent read-only investigation and review.
- Each task hands back its commits, exact tests and results, evidence paths,
  limitations and next action. The coordinator verifies these rather than accepting
  a "done" report.
- Use existing documents and runner artifacts for durable progress. Do not build
  another tracking or evidence framework.

Use a measurable coordinator goal: **deliver the checkpoint and human review package
below**, not "keep improving Continuum." This follows the bounded, evidence-based
[Codex Goals model](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

The previous 10:00 execution window is expired, not silently renewed. The new
milestone ends at the review checkpoint or a genuine authority/design blocker.

## 3. Ordered work packets

### A. Close the carried Docker-installation repair

Preserve the existing two-file change and both failed runtime attempts; do not
recreate completed migration work.

Verify the narrow updater-lock retry, fatal-error preservation, retry bounds,
pinned-runner compatibility, changed-file lint and cache regressions. Independently
review and commit it locally.

Refresh affected configuration-inventory source bindings in a new snapshot without
overwriting earlier evidence. Obtain one clean operational development run before
expanding module work. Do not count it automatically as final-candidate acceptance.

### B. Repair repeated application execution

Fix the demonstrated Kubernetes Job-reuse defect in a separate packet.

Limit cleanup/replacement to benchmark-owned resources. Preserve failed output before
replacement, wait for a fresh subscriber, and keep each execution's output separate.

Acceptance requires:

- A regression that reproduces the existing failure.
- Tests protecting unrelated Jobs and preserving cleanup/readiness errors.
- Actual same-revision, same-base-path runs at frequency **1 → 2 → 2**, each lasting
  30 seconds.
- Fresh executions completing **30 → 60 → 60** image outcomes, distinct retained
  results, and verified final teardown.

This establishes only the tested sequential application-reuse contract—not a generic
sweep engine or multi-stage pipeline.

### C. Close existing core-contract gaps

Perform one bounded, gap-driven pass over:

- YAML composition/defaulting and selector semantics.
- Deterministic module planning, dependencies and execution authorization.
- Lock/state consistency, phase ordering and rejected resume cases.
- Artifact capture, errors and teardown.

Fix demonstrated defects with focused regressions. Preserve the current execution
adapter and supported resume boundary.

Correct known documentation drift, including software `any_of` selectors and the
difference between proposed module APIs and the implemented execution interface.
Larger architectural concerns go into the later review package.

### D. Complete the selected module integrations

Use one fresh task per module family. Start with existing YAML profiles and suites;
implement only missing connections needed by those workflows.

Order: foundation/Kubernetes/endpoint/observability → KubeEdge → Mist → Columbo →
Kata → OpenFaaS.

Each task must leave a usable configuration, understandable prerequisites, defined
success/artifact checks and truthful support limits. Diagnose failures before retrying;
do not substitute software-only checks for application validation.

### E. Polish presentation and freeze the candidate

Make the existing CLI, YAML and module interfaces understandable through a concise
walkthrough covering configuration, execution, resume, results and troubleshooting.

Distinguish implemented modules from validated configurations. Do not add discovery
services, new commands or a GUI merely for presentation.

Finish reviewed functional and substantive documentation changes before freezing one
clean acceptance candidate.

## 4. Validation and acceptance

Run focused regressions, applicable lint, full unit/local-e2e/combined tests and all
twelve required canonical static-audit gates. Preserve the explicitly attributed
static environment and pinned physical-runner environment; do not silently upgrade
dependencies.

Then validate this bounded matrix on the frozen candidate:

| Coverage | Required runtime validation |
| --- | --- |
| Foundation | Two complete `operational_regression` passes; `qemu_infra_parity`; `network_validation` |
| Kubernetes, endpoints, observability | `qemu_k8s_image_parity`, `qemu_endpoint_image_parity`, `qemu_k8s_nobench_parity`, including actual observability readiness |
| KubeEdge and Mist | Their full image-classification parity suites |
| Application reuse | Repeat the 1 → 2 → 2 proof on final source |
| Columbo | Exact strict trace suite; all six required timing columns |
| Kata | Exact two-VM, 8-core/64-GiB-per-VM, kata-qemu/overlayfs, 100-application workflow; required artifacts and teardown |
| OpenFaaS—last | Exact 26-vCPU, node3 multi-host workflow; four publishers and 600 completed outcomes; intended VM retention |

Inspect complete results, stdout/stderr, metadata, state/locks, network and benchmark
artifacts. Require independent evidence review before accepting a workflow.

Run as `matthijs`; preserve unrelated domains and prior evidence. No restored smoke
accounts, privileged repository execution, automatic ownership repair or broad pruning.

On failure, preserve and diagnose it before proceeding. Apply existing affected-source
freshness rules and mandatory final-candidate gates; never relabel old evidence or
weaken validators. Functional completion must not be presented as proof of accurate
cross-host timing.

## 5. Finish line: your critical review

Deliver:

- A clean, reviewed checkpoint with no unresolved blocking defect in the selected
  workflows.
- The updated [support matrix](../../release_certification_matrix.md), refreshed
  configuration accounting and explicit unsupported boundaries.
- Exact commands, results, revisions, artifact locations and remaining limitations.
- A short component/runtime explanation and runnable walkthrough.
- Prioritized architectural questions and the historical-module restoration backlog.

Then stop for your broader code/design review.

This is **review-ready, not automatically merge-ready**. The original Continuum/SPEC-RG
reproduction scope and historical dispositions remain open where unresolved. Bring
those historical choices together in one consolidated decision packet; do not invent
equivalence or delete preserved functionality.

No merge, push, tag, release, publication, cloud spending or privilege expansion is
authorized by this plan.
