# OpenDC closed-loop demo: approved overnight implementation plan

Approved by the user's active goal on 2026-09-25. This is the execution record of the complete in-task plan, not a replacement for its scope. Use Superpowers executing-plans, test-driven-development, systematic-debugging, requesting-code-review and verification-before-completion. One primary implementer owns code and cluster state; independent reviewers assess the controller and final branch. No routine checkpoint approvals, no merge.

## Goal and authority

Deliver an actual repeated observation → causal forecast → candidate simulation → policy decision → cordon/uncordon → outcome observation loop, matched physical evaluation and one inspected topic-oriented landscape PDF. Scheduling fidelity, functional actuation, independent workload repetitions and honest interpretation are core. Larger infrastructure is conditional. Work approximately eight hours, reserving the last hour for review, verification and delivery; unfinished requirements remain explicitly unfinished.

Base: verified local/remote `codex/fns-2026-10-08` at `c36758909e807d4d74e54516e7e4acfdffd2deda`. Branch: `codex/opendc-closed-loop-20260925`. Initial full suite: 298 passing tests. Original checkout and ignored evidence remain untouched.

Use OpenDC `cf10c06eb73c7e60e1076e376922b1201caf12d1`, initially image `continuum/opendc:fns-native-batch-20260924-cf10c06` (`sha256:7df350c45aca2041fb9b29250757502e4b0f18dec03fbfb3a59a355ffa998afe`). Preserve separately pinned example provenance, calibrated worker image, four images, 128 inference repetitions and five-second resource sampling. Preserve original Job times, backlog/future distinctions, initial assignments, causal availability, gaps, unmatched Jobs, exhausted work and censoring. Worker-only application placement, isolated control-plane runner with real admission and one CPU/two GiB limits, C−1 applied once.

Previous branch implementation, report consolidation, review, merge and broad lint cleanup are complete. Another developer JAR, physical power calibration and Kubernetes modernization are not blockers.

## Task 1: reproducible experiment harness and preservation

- [x] Reverify source/remotes, create isolated worktree/branch, record baseline and approval.
- [x] Parameterize fresh experiment namespaces, paths, workload/worker settings, provenance and cleanup. Preserve prior captures before replacing anything ephemeral.
- [x] Preserve workload plans, live observer prefixes, API inventories, source/configuration and image identities. Use unique evidence destinations under `/mnt/sdb/matthijs/fns-evidence/`.
- [x] Test output collision rejection, capture provenance and preservation boundaries. Commit and push the harness with verification.

## Task 2: physical admission alignment

- [x] Begin with unchanged known-arrival replays and matched queue pressure: seeds52/53, two accepting workers, four120-second cycles, rates0.02–0.30.
- [x] Compare current packing against verified-valid initial/max backoff1second. Retain configuration-only alignment only if acceptance is met.
- [x] Otherwise implement namespace-scoped FIFO admission: create Jobs immediately suspended; order creation timestamp then UID; release the oldest only when resources fit; wait for binding before releasing another; count outstanding reservations. Kubernetes still handles worker placement, affinity, taints and resource fit. Never suspend an already admitted Job. Admission timeout stops release and records the failure.
- [x] Measure at least20 Jobs with waits≥5seconds per contention run. Require ≥50% start-MAE reduction, final MAE≤5seconds, p95 absolute start error≤15seconds, zero placement/resource/cordon violations, ≤5% completion-count regression at common arrival end. Preserve ties and uncertainty, report startup/runtime/release residuals separately. Insufficient contention is not alignment evidence. Unmet accuracy targets do not block independent controller work.
- [x] Test FIFO head blocking, equal-time ties, outstanding reservations, cordon, resource fit, restart reconciliation and timeout. Verify, commit and push.

## Task 3: practical observation and live-state model

- [x] Add collection boundaries and bounded second-read membership reconciliation where needed; all newly collected evidence is available only at collection time.
- [x] Freeze startup/release estimates from eligible pre-cutoff evidence, preserving inference profiles and distinguishing lifecycle occupancy from classifier execution.
- [x] For exhausted running work, use labeled conditional residual estimates from eligible completed durations, with a5-second fallback when no longer observations exist. Preserve exhausted classification and original evidence; predictions never become observed completions. Block scale-down affected by exhausted/unresolved work.
- [x] Model accepting, draining and empty-reserve workers across cutoffs. Carry all existing cordons into every action, retain assignments and verify complete accounting. Permit at most one draining worker for this initial policy.
- [x] Replace the hard-coded three-worker ceiling with explicit bounds. Extend scenario metadata and update active producers, validators and reporting together; preserve historical readers without obsolete command wrappers.
- [x] Test causal membership, state gaps, startup occupancy, exhausted labels, draining pins across repeated cutoffs, configured/model cores, bounds and reserve eligibility. Verify, commit and push.

## Task 4: repeated controller

- [x] Add a direct controller module with shadow/live modes and separate pure policy selection from execution. Consume observer streams, worker configuration, policy and new evidence destination; use native action/sample batching on the control plane.
- [x] Journal frozen boundaries/cutoff, scenario identities, validity/scores, stage timing, proposal, guards, API interval and observed outcomes. Reconcile journal and actual Kubernetes state before actuation after restart. Do not blindly retry uncertain API outcomes.
- [x] Use H60/N3, a60-second nonoverlapping cadence, ≤3-second state age and ≤30-second cutoff-to-action age. Two valid shadow cycles precede live actuation. Start with3 accepting workers; bounds1–3. Hold/uncordon one empty Ready reserve/cordon one accepting worker without eviction.
- [x] Objective: minimize allocated application core-time subject to95% of Jobs finishing within120seconds of original creation. Score backlog plus future cohort through complete modeled completion, resources over120seconds. Add measured decision age to predicted response as a conservative margin; retain finite-arrival-horizon assumption.
- [x] Every sampled future must satisfy95%/120seconds for a candidate to qualify. Choose smallest mean allocation; require≥10% predicted savings and two consecutive wins for down. Ties favor hold;120-second action cooldown. If none qualifies, up only if it improves late fraction, then mean tardiness, versus hold; otherwise report infeasible and hold.
- [x] Reread readiness, cordons, assignments and queue before action. Changed topology, unknown membership, occupied/unready reserves or invalid outputs invalidate proposal. Newly queued work vetoes a down selected from an empty-queue state. Reject old decisions.
- [x] Explicit reactive fallback can up on fresh oldest queued wait>30seconds or queue length>accepting application slots; never down on invalid forecasts. Log separately. Reactive baseline uses these up conditions and down only with zero queue and an empty worker on two consecutive cycles, using the same bounds/cooldown.
- [x] Count allocation while accepting or draining; show powered-on VM time separately. No physical savings claim from warm reserve availability.
- [x] Test selection/ties/infeasibility/complete totals, stale state, hysteresis, uncertain API success, restart, changed identity, draining and reserve reuse. Independent controller review. Verify, commit and push.

Implementation and verification for Tasks1–4 are complete. The physical evaluation below distinguishes demonstrated functionality, an unmet benefit target and explicit observation limits. The authoritative [findings](/mnt/sdb/matthijs/fns-evidence/opendc-closed-loop-20260925T003413Z/FINDINGS.md) retain numerical results, limitations and failed attempts.

## Task 5: physical evaluation and forecast usefulness

- [x] Functional pilots: seed60 used four120-second cycles; seed61 was explicitly extended before held-out evaluation to six240-second cycles and three-cycle warm-up to exercise ten consecutive evaluation ticks and growing observation prefixes. Attempts and the duration decision remain separate selection evidence.
- [x] Freeze choices before held-out seed62. Main matrix seeds62/63/64 × fixed-full/reactive/forecast; six240-second cycles. Same planned arrival offsets/payloads within seed, unique Job identities. Rotate arm order: fixed/reactive/forecast; reactive/forecast/fixed; forecast/fixed/reactive.
- [x] Warm-up3cycles at full capacity; freeze eligible profiles; score final3cycles' arrivals with warm-up backlog separate. Follow work for up to10minutes after arrival end; preserve censored outcomes. Every planned request attempted,≥95% dispatched within250ms, zero adapter/observer restarts for accepted captures. Changes after a correctness defect require separately identified comparison runs; never retune held-out choices silently.
- [x] Functional target evaluated and demonstrated in seed64 (forecast-selected down followed by reactive-fallback up; not repeated in all three runs):≥10 consecutive valid evaluation cycles, measured down and subsequent up, full action/outcome journal, zero duplicate actions/evictions/placement or cordon violations outside explicit API uncertainty,≥90% otherwise eligible cycles within30-second decision limit.
- [x] Benefit target evaluated and not met (median paired savings0%; every forecast run passes the response constraint): median paired application core-time savings≥10% against fixed-full and every accepted forecast-policy run satisfies95%/120seconds. Report response median/p95, completion/deadline/censoring counts, allocation and controller wall/CPU/RSS for every run. Distinguish action success from useful choice and negative/inconclusive results.
- [x] Four chronological cutoffs per forecast run: compare primary futures, one alternate scenario seed and known-arrival replay. Counterfactual ranking is diagnostic only; actual matched arms establish physical benefit. Equal-run weighting, separate selection/held-out roles, no independent-sample claims for overlapping cutoffs/futures, descriptive ranges only.
- [x] Extend the existing reporting package/direct modules: physical outcomes lead; predictions adjacent to observations; retain forecast and detailed scheduling timelines. Shared scales, clear legends, short per-panel explanation and takeaway. Validation later in the same PDF. Verify, commit and push.

The completed comparison, exact outcomes, prescribed ranking diagnostics and qualified safety evidence are linked from [FINDINGS.md](/mnt/sdb/matthijs/fns-evidence/opendc-closed-loop-20260925T003413Z/FINDINGS.md). Functional success does not imply benefit, and no observed violation does not prove absence of unseen events. The optional supplementary seed65 gate was false after the main demonstration; no additional pilot was run.

## Task 6: conditional larger setup

Not executed. Core physical evaluation, prescribed diagnostics, restoration and review consumed the available window; these conditional extensions remain future scope, not a required unfinished core deliverable. The checked preflight inventory is preserved beside the evidence.

- [ ] Only after core evidence is secured and time permits restoration, measurements and delivery: node1/node3/node4, each20CPUs/~251GiB; six cloud VMs at8configured cores/16GiB each (one control plane plus5workers), two per host;2-core endpoint. Model7application cores per worker. Start3 accepting,2reserves; bounds2–5.
- [ ] Initial rates multiplied by35/9 versus existing maximum capacity; preserve calibrated images/repetitions. One sizing pilot then2fresh seeds × fixed-full/forecast; keep separate from original-topology results.
- [ ] Inventory/restorably archive all disk backing chains, VM definitions, source/configuration, image provenance and captures first. Continuum startup destroys matching user VMs even with delete=False. A new directory alone is not isolation. Do not overwrite archives or historical destinations.
- [ ] Kubernetes modernization, physical power calibration and detailed VM boot/shutdown/failure modeling remain deferred. Verify, commit and push any supported extension.

## Task 7: verification and delivery

- [x] Full image-batch suite, relevant infrastructure regressions if changed, pinned Black22.12.0 at100columns and Pylint2.15.8 with repository rcfile on task-owned Python; inspect diffs and docstrings. Accepted historical lint findings remain limitations, not another cleanup project.
- [x] Independent whole-branch review and focused rechecks after important fixes. Inspect every PDF page and verify numerical offline regeneration.
- [x] README: run instructions. DESIGN: long-lived rationale. HANDOFF: current state, evidence and continuation. Exact settings, commands, numerical results, failed attempts and logs stay beside evidence.
- [x] Restore experiment-owned scheduler/cordon/network state; drain/archive work and stop autonomous actuation. Report exact final cluster/VM/network/job/service state.
- [x] Deliver commit contributions; PDF/findings/data links; tests, numerical claims and limits; exact runtime/source/image identities; reproducible commands; fresh-task continuation. Push without merging. Unfinished scope stays unfinished; never mark the goal complete merely because the window elapsed.

Final evidence: 389 passing tests on the final executable tree; pinned Black/Pylint; independent implementation and all-page report review; byte-identical offline numerical payload; exact scheduler/network/VM restoration and stopped experiment processes. Delivery status and final commit/source identities are recorded in [VALIDATION.md](/mnt/sdb/matthijs/fns-evidence/opendc-closed-loop-20260925T003413Z/VALIDATION.md).

## Independent progress and review focus

If scheduling accuracy remains poor, continue state/controller/report work while preserving discrepancies. If physical execution is blocked, continue replay, policy tests, offline reporting and docs. If expansion is blocked, retain the core small-cluster result. Heavy unrelated computation must not contaminate physical measurements.

Review focus: causal boundary errors; lost draining or exhausted occupancy; partially valid candidate scoring; API timeout with an action already applied; false physical-benefit claims from unmatched cohorts or powered warm reserves.
