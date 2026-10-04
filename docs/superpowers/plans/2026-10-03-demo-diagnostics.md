# OpenDC Demo Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and improve sender/timing reliability, measure constant5 against fresh dynamic comparisons and deliver serious cumulative reviews plus an integration decision guide within nine hours.

**Architecture:** Reuse the existing endpoint, controller, sealed workflow and reporting contracts. Diagnose preserved component timings before narrowly modifying existing flows. Add explicit evaluated-window fidelity and freeze supported temporal modeling changes before new physical evaluation.

**Tech Stack:** Existing Python3.10, unittest, pinned OpenDC FNS/Kubernetes/libvirt, Black22.12.0/Pylint2.15.8 and Matplotlib/PyMuPDF report environments.

**Spec:** docs/superpowers/specs/2026-10-03-demo-diagnostics-design.md

## Global Constraints

- Original checkout40e9b8b, ready1bd3f1a and acquisitionf79f99c remain unchanged; new branch pushes without merge.
- Start1791063560, hard end1791095960, protected closure1791090560; whole-workflow launch bounds never restart.
- Fixed comparator5; dynamic initial4/bounds2..6; six5-CPU workers/four application slots; physical delay60 seconds.
- F workload0.03/0.70 Jobs/s, period420, four cycles/two warm-up, deadline95% within120, follow-up180; reactive30/forecast90.
- Development61001/61002, held-out62001/62002, live53001 untouched; seal before held-out generation; retain every failure and omitted cell.
- Existing FIFO, guard, all-Job denominator, full native identity and pending-cost contracts remain required.
- New evaluated-window fidelity gates use250ms/95%; old sealed acceptance and numerical exports remain immutable.
- Black22.12.0 line-length100 and Pylint2.15.8 sysconfig/pylintrc on owned Python, with consistent Args/Returns/Raises documentation.

## Review Focus

- High HTTP tail latency must remain distinguishable from sender queue delay; increasing concurrency must not hide transport failures or change offered-work timing semantics.
- Planned arrivals on evaluation boundaries, failed/missing sends and old captures without new settings must not produce a falsely accepted comparison or retroactively rewrite historical evidence.
- New modeled availability must not shorten original pending due clocks, introduce synthetic Jobs into application cohorts or silently change physical acquisition semantics.
- Fixed5 must actually admit on five workers while both dynamic arms start at four; sealed settings and pairing must disclose this intentional baseline difference.
- Cumulative branch guidance must match Git ancestry and actual empirical evidence; final restore/save claims need current exact-owned identity/data checks, not inherited assertions.

### Task 1: Reconstruct the actual bottlenecks

**Files:** New evidence diagnosis scripts/results beside artifacts; no product-code mutation before diagnosis.

**Interfaces:** Consumes preserved endpoint events, adapter-data metadata/events, stage/collection timing and activation journals from the prior campaign. Produces `diagnosis/sender.json`, `diagnosis/timing.json` and a cause/limits note identifying observed versus hypothesized mechanisms.

- [x] Read the task brief and record BASE; preserve baseline507-test result and authoritative original/extension states.
- [x] Reconstruct sender request lifetimes and16-slot saturation against adapter body/storage/API stages, retaining raw identities and evaluated-window clocks.
- [x] Reconstruct cutoff→prepare→native→request→observed timing, compare working/problematic captures and document model assumptions.
- [x] Use minimal controlled tests/probes to distinguish competing causes; stop speculative fixes and record remaining uncertainty.
- [x] Run pinned tooling on preserved diagnostic scripts, validate counts against raw captures and commit only audience-scoped design amendments necessary for the selected correction.

### Task 2: Reliable evaluated-window evidence and focused sender correction

**Files:** Modify application/image_batch/src/closed_loop_evidence.py, demo_workflow.py, capture_run.py, reporting/closed_loop.py and endpoint/storage paths only where Task1 establishes a defect; relevant tests under application/image_batch/tests.

**Interfaces:** Consumes Task1 diagnosis and existing whole-capture sender identity validation. Produces `sender_window_fidelity(events, *, start_offset_seconds, end_offset_seconds) -> dict`, explicit capture/protocol `require_evaluated_sender_fidelity` defaultFalse, per-run `sender_evaluated_window` metadata and required acceptance for new campaign captures. Source corrections must preserve offered schedule/receipt/Job semantics.

- [x] Write/run RED tests for planned-window boundary inclusion, a timely warm-up hiding late evaluated sends, missing/failed identities and old default compatibility.
- [x] Implement exact planned-window counts,250ms/95% fidelity, exported reporting metadata and sealed forwarding; do not retrospectively change old acceptance.
- [x] Reproduce any confirmed sender/storage defect with a meaningful regression; implement only the demonstrated fix and verify at unchanged workload semantics.
- [x] Run relevant sender/storage/evidence/workflow/report tests, pinned format/lint and full regressions; inspect diff and commit.

### Task 3: Timing fidelity and physical comparators

**Files:** Existing opendc_acquisition.py/closed_loop_controller.py/configuration/tests only for a supported temporal correction; demo_workflow.py/tests for per-arm initial allocation; evidence operations and protocols.

**Interfaces:** Consumes diagnosis timing distributions and existing acquisition_seconds/pending due clocks. Produces explicit validated temporal model metadata if a correction is supported, preserving physical minimum60 and original pending due clocks. Produces sealed `arm_active_workers` mapping for fixed5 versus dynamic4, constrained within common worker bounds, and truthful per-run protocol/configuration exports.

- [x] Record a precise temporal design amendment from Task1 before implementation; if no correction is supportable, retain diagnostics and explicitly report the model limit.
- [x] For an implemented temporal correction, write/run RED tests for new reserve timing, existing pending absolute due clocks, zero-delay/backward compatibility and synthetic exclusion; run a real bounded native probe.
- [x] Write/run RED command tests for fixed5/dynamic4 and invalid per-arm bounds, then implement strict sealed forwarding without changing reactive thresholds/cadence.
- [x] Snapshot/archive current originals and host ownership, pause exact originals, restore newest eight same-host RAM saves, verify readiness/resources/images/template/network and clocks.
- [x] Run bounded development61001/61002, select first suitable settings independently of forecast benefit, freeze exact tested source/deployment and seal the new rotated matrix.
- [x] Run complete six-capture bounds for62001/62002 fixed5/reactive/forecast, or prospectively ledger a smaller matrix if necessary; preserve every failure and stop on operational/restoration defects.

### Task 4: Results and cross-branch decision report

**Files:** Existing reporting/evidence helpers only as needed, application/image_batch/OPENDT_HANDOFF.md and DESIGN/README where audience requires; campaign FINDINGS/VALIDATION/COMMANDS/BRANCH_DECISIONS.md and PDFs beside artifacts.

**Interfaces:** Consumes frozen new captures and Git ancestry from40e9b8b through ready/acquisition/new tips. Produces comparative PDF/self-contained metrics/offline redraw plus Markdown/PDF branch decision guide with exact commit groups, dependencies, claim evidence, unresolved limitations and integration options.

- [x] Verify raw pairing, actual fixed5/dynamic4 allocation, evaluated sender fidelity, complete Job denominators and charged-capacity bounds before claims.
- [x] Render all new outcomes, separate development/rejection roles, inspect every page and verify offline numerical reproduction.
- [x] Construct branch decision guide from actual Git diffs/logs and authoritative campaign evidence; distinguish functional readiness from attractive results and explain what should be integrated or deferred.
- [x] Update current handoff without duplicating experiment logs in README/DESIGN; preserve all evidence and current operations in durable checkpoints.

### Task 5: Serious reviews, restoration and delivery

**Files:** Review packages/resolutions and verification beside campaign artifacts; final current-state handoff/checkpoint.

**Interfaces:** Consumes cumulative diff40e9b8b..HEAD, new-branch diff, all three studies and reports. Produces independent cumulative-code and scientific/evidence reviews, one author Important/Critical fix pass, full verification and pushed unmerged source with exact original infrastructure restored.

- [ ] Run full relevant image-batch/infrastructure regressions and pinned tooling with actual outputs and explicit accepted warnings/skips.
- [ ] Dispatch fresh independent cumulative-code review and independent scientific/report/branch-guide review; preserve every verdict and caveat.
- [ ] Re-grade findings, reproduce Critical/Important issues with RED/GREEN regressions, fix in one author pass and verify full suite; ledger deferred minors and every declined-to-judge ruling.
- [ ] Archive idle extension/API/streams/native state, save all eight privately to new same-host paths, verify exact identities and shutoff, then resume exact five originals.
- [ ] Verify new original baseline, clocks, presentation/source/RBAC/frozen stream prefixes, immutable backing hashes and unrelated containers.
- [ ] Commit/push without merge; verify remote SHA, original/prior checkout preservation, every report/review/decision-guide artifact and the completion audit before marking the goal achieved.
