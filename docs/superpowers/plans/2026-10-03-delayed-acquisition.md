# Delayed Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a fair multi-host comparison of fixed normal allocation, reactive control and forecast/native simulation with delayed capacity acquisition, within ten hours and without merging.

**Architecture:** A shared durable activation lifecycle enforces real admission delay and exposes pending allocation. Pinned synthetic occupancy models worker availability in native OpenDC while preserving real Job cohorts. Existing bounded capture, source freezing, protocol sealing and report workflows remain authoritative.

**Tech Stack:** Python3.10, pinned OpenDC FNS engine, Kubernetes1.27, libvirt/QEMU, existing Python unittest/Black/Pylint/Matplotlib.

**Spec:** docs/superpowers/specs/2026-10-03-delayed-acquisition-design.md

## Global Constraints

- Fixed and initial workers4; dynamic bounds2..6; controlled acquisition delay0 or60 seconds; workers5 configured/four application CPUs.
- Four-image/128-repetition Jobs, FIFO and all-Job deadline denominators; initial SLO95% within120 seconds.
- Source/deployment/settings freeze before held-out seeds52001/52002; development51001/51002; live53001 unused.
- No merge, no historical overwrite, no VM boot/energy claim, no held-out retuning or favorable replacement.
- Black22.12.0 line-length100; Pylint2.15.8 sysconfig/pylintrc; consistent Args/Returns/Raises docstrings on task-owned Python.
- Hard deadline1791055315; closure1791050515; use complete existing bounded per-run launch guards.

## Review Focus

- Lost acknowledgement or restart while activation pending must not shorten its delay or dispatch twice.
- UID replacement/nonempty target/changed bounds must prevent activation while preserving diagnostic evidence.
- Synthetic occupancy must never enter Job service denominators, real cohort pairing or observed results.
- Delayed native task placement must remain blocked through the activation boundary, including empty real cohorts.
- Allocation must charge pending capacity once, retain draining costs, and distinguish gaps from confidence intervals.

### Task 1: Shared physical activation lifecycle

**Files:** Create src/capacity_acquisition.py and tests/test_capacity_acquisition.py under application/image_batch; modify src/closed_loop_controller.py, src/closed_loop_journal.py as needed, src/closed_loop_guards.py, src/demo_configuration.py, src/capture_run.py and relevant existing tests.

**Interfaces:** Consumes validated snapshot_view and durable Journal. Produces acquisition_seconds setting (default0), durable activation request/due/observed records, pending acquisition status serviced on maybe_tick independently of policy cadence, and reserve exclusion. Retain existing zero-delay actuation semantics.

- [ ] Write and run failing tests for60-second lower bound,0-second compatibility, restart, UID replacement/nonempty target, no duplicate intent and no action during pending activation.
- [ ] Implement minimal shared lifecycle, CLI/config validation, pending-aware guards and model metadata.
- [ ] Run targeted controller/guard/journal/config/capture tests; inspect every failure.
- [ ] Run pinned Black/Pylint on task-owned files; fix concrete defects; commit.

### Task 2: Native delayed availability and accounting

**Files:** Create src/opendc_acquisition.py and tests/test_opendc_acquisition.py; modify src/opendc_scenarios.py, src/opendc_pinning.py, src/opendc_native_batch.py, src/opendc_inputs.py, src/closed_loop_runner.py and their tests.

**Interfaces:** Consumes acquisition_seconds and optional pending worker/due metadata from Task1. Produces case acquisition metadata, common synthetic full-slot occupancy records explicitly marked infrastructure, native admission cordons, and allocation-worker identities separate from modeled topology. Real cohort signatures and deadline denominators exclude infrastructure records; batch keeps all actual native task identities validated.

- [ ] Write/run failing native preparation/scoring tests for host unavailability, identical real cohorts, synthetic exclusion, zero-delay compatibility and pending cost.
- [ ] Implement pinned synthetic occupancy and explicit native cordons; preserve existing no-delay contracts.
- [ ] Build a separately tagged wrapper from the existing pinned native image if new wrapper code is required; retain engine and worker/adapter image IDs.
- [ ] Run controlled native availability probe and inspect per-task host/start/release output; fail if application admission precedes availability.
- [ ] Run relevant native/pinning/scenario/runner regressions; pinned formatting/lint; commit.

### Task 3: Evidence and reports

**Files:** Modify src/closed_loop_evidence.py, src/closed_loop_audit.py, src/closed_loop_diagnostics.py, src/reporting/closed_loop.py and relevant tests; add a focused reporting helper only if needed.

**Interfaces:** Consumes journal activation records and case metadata. Produces accepting/draining/pending allocation components, combined charged allocation, requested-versus-available capacity timelines, activation latency diagnostics, matching study keys and clear plotted labels.

- [ ] Write/run failing evidence tests for pending overlap, request-to-observation bounds, missed activation/failure and synthetic-excluded SLOs.
- [ ] Implement reports/audits preserving zero-delay historical redraw and all-Job service accounting.
- [ ] Run focused report/evidence tests and full image-batch suite; pinned Black/Pylint; commit.

### Task 4: Physical campaign

**Files:** Evidence operations/development/evaluation protocols beside generated artifacts; only task-owned reusable workflow corrections in src/demo_workflow.py if demonstrated necessary.

**Interfaces:** Consumes committed tested source and retained same-host VM manifest. Produces immutable baseline/archive, owned operation records, source freezes, development selection and six held-out captures plus zero-delay development comparison where bounded time permits.

- [ ] Archive original presentation and snapshot both hosts; verify exact saved UUIDs and private paths; restore only owned extension after suspending originals.
- [ ] Verify cluster readiness/resources/images/template/network, freeze candidate source and seal fresh development protocol before workload generation.
- [ ] Run bounded development, preserve every attempt, select/freeze first usable settings independently of forecast-versus-reactive advantage.
- [ ] Seal two-seed rotated fixed/reactive/forecast matrix and reserve full bounds; execute all six captures, collecting raw/native evidence and safety audits.
- [ ] Run zero-delay development comparison and any justified additional probe only if full bounds leave protected closure intact; record findings and limits.

### Task 5: Verification, review and delivery

**Files:** Update application/image_batch/DESIGN.md, README.md, OPENDT_HANDOFF.md; evidence FINDINGS.md, VALIDATION.md, COMMANDS.md, reports and delivery checkpoint.

**Interfaces:** Consumes tested implementation and sealed captured evidence. Produces readable PDF/self-contained metrics/offline redraw, independent branch review, resolved defects, original infrastructure restored and pushed unmerged branch.

- [ ] Run full relevant regressions and infrastructure tests; record pinned lint findings and accepted narrow exceptions.
- [ ] Generate report, inspect every page, verify offline numerical redraw; write audience-scoped docs and concise findings.
- [ ] Dispatch one fresh whole-branch reviewer with spec/plan/diff/evidence and review-focus requirements; resolve concrete Important/Critical findings with RED/GREEN regressions.
- [ ] Archive experiment/presentation state, verify no active owned work, save extension privately to new same-host paths, resume originals and compare authoritative baseline.
- [ ] Commit and push without merge; verify remote head, clean original checkout and restoration; audit every deliverable before claiming completion.
