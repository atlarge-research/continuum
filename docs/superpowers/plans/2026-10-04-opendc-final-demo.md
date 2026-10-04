# Final OpenDC Demo Implementation Plan

**Execution stopped; positive outcome unmet.** The latest current-source fixed-five capture failed service (189/278 within 120 seconds, 68.0%). The primary launch window was missed: capture finished 18:02 UTC but the next launch decision at 20:59 UTC was after the 20:02:59 UTC latest start. Forecast qualification and six held-out captures were not executed. New launches are prohibited under this campaign's complete-budget gate. Preserve evidence and finish restoration/delivery; a new campaign needs new authorization and an explicit budget. The [outcome and exact evidence](/mnt/sdb/matthijs/fns-evidence/opendc-final-20261004T124609Z/FINDINGS.md) are authoritative. The steps and schedule below preserve the approved protocol, not a current launch instruction.

> **For agentic workers:** Use `superpowers:executing-plans` for native inline execution, with targeted independent runtime and evidence reviewers. The user approved execution on October 4, 2026, with service first and allocation saving second. Lower within-deadline latency alone does not justify higher allocation.

**Goal:** Preserve the 95%/120-second service requirement, then demonstrate at least 5% conservative application-allocation savings against adequate static capacity and a useful service/allocation tradeoff against a reasonable reactive policy, with an explanatory operational-analysis example.

**Architecture:** Keep the existing observation, causal forecasting, native simulation and guarded worker-admission loop. Correct redundant response scoring where the native clock contract justifies it and implement the agreed reactive target/stabilization rule. Use existing 420-second evidence for diagnosis, make 840 seconds the first new physical candidate, and confirm the chosen configuration on two fresh seeds overnight.

**Tech stack:** Existing Python 3.10 environments, Kubernetes/FIFO admission, retained OpenDC native image, two-host/eight-VM platform and existing Matplotlib/PDF reporting.

**Spec:** [Approved design and preservation constraints](../../../application/image_batch/OPENDT_HANDOFF.md#agreed-final-demo-plan), [scientific design](../../../application/image_batch/DESIGN.md), and the user's October 4 discussion decisions recorded below. This is the single current implementation plan; do not create another design specification or overlapping campaign plan.

## Approved campaign and savings-first acceptance criteria

- The cumulative execution limit is **18 hours**. Initial plan-approval waiting does not consume it; execution deadlines persist across resumptions.
- Start new physical development at **period 840**, replacing the previous requirement to run a new 420 pilot first. Existing 420 cases support targeted timing checks. There is no additional period, rate, policy or seed search.
- Required physical development compares fixed and forecast with **two warm-up cycles and one evaluated cycle**. These shortened probes are explicitly development evidence.
- Minimum presentation acceptance is **5% conservative allocation saving on each fresh seed** against the same development-selected adequate static count. Aim for 5–8% or better; 10% is a stretch goal rather than a freeze gate.
- Forecast and static must each achieve **at least 95% within 120 seconds of original API creation on both fresh seeds**. Failed and unfinished Jobs stay in the denominator.
- On each seed, forecast must either use less allocation than reactive when both meet service, or meet service that reactive misses while still saving against adequate static. If reactive meets service more cheaply, the intended advantage is unestablished. Use conservative matched allocation bounds.
- The user corrected the earlier latency/allocation tradeoff at execution approval: service is the first priority, then allocation. Lower latency within the service deadline does not justify higher allocation. Show response distributions as diagnostics and all three policies' service and allocation openly.
- Preserve at least one **forecast-selected, physically observed scaling action** with the state, predicted alternatives, safety decision, subsequent capacity and service outcome. Report fallback separately; fallback-only performance does not establish simulation control.
- Demonstrate the framework's operational visibility through that control example. The comparison evaluates forecasting plus simulation together; it does not isolate simulation's incremental contribution. Application allocation is not measured physical energy or a cloud bill.

## Global constraints

- Start execution from freshly verified `codex/fns-2026-10-08`; local and remote were verified at `a99ab54ae538373f79d00018d2059bdeb6f030b6` during planning. Preserve that branch and all historical worktrees/evidence. Create `codex/opendc-final-demo-20261004` in an isolated worktree only after approval.
- Keep six workers/four application slots each, dynamic initial four/bounds 2..6, homogeneous four-image/128-repeat Jobs, periodic Poisson rates 0.03/0.70 Jobs/s, forecast/reactive cadences 90/30 seconds, horizon 240 seconds and three sampled futures.
- Keep physical acquisition 60 seconds, modeled request/acquisition/admission offsets 60/60/30 seconds, original pending due clocks, decision freshness 60 seconds, strict observation freshness three seconds, residual occupancy margin three seconds, native timeout 45 seconds and native allocation window 180 seconds.
- Keep the same one-pending-acquisition restriction, empty-worker reactive removal, guards, uncertain-action recovery and FIFO/resource contracts. Forecasts receive observed arrival evidence, never held-out schedules or workload seeds.
- Retain native image `continuum/opendc:fns-acquisition-20261003-v3`, verified during planning as `sha256:5147d22cbc1c63fb81c06541bec7343f60428ad7441dbdf3bb3a1b73cfe0eb98`. Seal fresh deployment/image/source identities before primary execution.
- Original and study CPU pins overlap: never run both pools simultaneously. Use exact UUIDs, original hosts, authoritative diagnostics RAM saves, private new save destinations and the handoff's preservation records. No historical save overwrite, username-wide cleanup, host reset or unrelated-container changes.
- Use pinned Black 22.12.0 at line length 100 and Pylint 2.15.8 with `sysconfig/pylintrc` on changed Python. Keep task-owned cleanup and consistent docstrings. No broad compatibility framework, refactor, simulator change, autoscaling integration or extra studies.

## Review focus

1. Double-counted response clocks versus genuinely unmodeled delay: prove the new scoring contract without losing original backlog waiting or rewriting historical exports.
2. A same-tick fallback or restart losing high-demand history: persist original recommendation timestamps and retain the preceding 120-second maximum.
3. Cheap partial totals or disappearing failed Jobs: preserve complete service cohorts, pending/draining allocation and observation bounds.
4. A proposed action being reported as physical success: preserve request, acknowledgement, observation and decision origin separately.
5. Recovery consuming reserved primary/restoration time: supervise complete process groups and reconcile actual infrastructure state rather than repeating operations.

## Tasks and intended commits

### Task 1: Establish campaign ownership and checkpoint

**Files/artifacts:** This plan, a fresh campaign evidence directory, checkpoint, exact-owned operation manifests and immutable source archives. Evidence commands/logs belong beside artifacts, not in README or DESIGN.

- [ ] After approval, record actual start, the 18-hour hard end and all absolute deadline boundaries before other execution actions. Create the execution branch/worktree from the verified demo tip and carry this plan there; leave the main demo branch unchanged.
- [ ] Declare development seed **70001**, fresh held-out seeds **71001/71002**, reserved live seed **53001**, and scenario seed **20261003** before generation. Planning metadata searches found no prior use of the three new workload seeds; verify that declaration at execution start.
- [ ] Inspect actual guests, UUIDs, saves, disks/pins, namespaces and owned process groups. Preserve fresh original presentation/API/source/RBAC/observer/adapter archives before switching pools. Use authoritative latest same-host diagnostics saves; preserve earlier RAM and backing chains.
- [ ] Record the exact closure plan and fresh private save destinations before advancing study disks. Verify the original pool inactive before restoring study guests. Check idle clocks with strict transport brackets; correct only established idle skew.
- [ ] Keep a durable checkpoint with completed/pending tasks, elapsed time, deadlines, source identities, evidence paths, process handles and ownership. On resumption, reconcile actual state and expired deadlines before acting.
- [ ] Commit `docs: record the approved final demo implementation plan`.

### Task 2: Correct the validated response-time contract

**Files:** `application/image_batch/src/closed_loop_policy.py`, native case/score adapters in `opendc_scenarios.py` and `closed_loop_runner.py`, shared diagnostics/counterfactual/report consumers, and their existing timing/policy/runner/diagnostic tests.

**Interfaces:** Keep `summarize_candidate(candidate, decision_age, *, scenarios=3, deadline_seconds=120)` and `select_action(...)`. Newly generated delayed cases and their scores carry `response_time_contract="original_creation_with_modeled_action_offsets_v1"`. Unmarked historical/zero-offset cases retain legacy scoring. Unknown or inconsistent markers fail closed. Use one response-adjustment helper for policy and diagnostic percentiles.

- [ ] Read preserved cases and prove the original-creation reconstruction plus modeled action offsets. Retrospective inspection found seven of sixteen recorded native decisions become cheaper without the blanket age margin; this is a hypothesis, not a measured alternate trajectory.
- [ ] Add failing tests for new-contract response 110 seconds staying 110 at decision ages 0/15/60, future Jobs avoiding pre-birth delay, preserved pre-cutoff backlog waiting, and decision age above 60 preventing action.
- [ ] Add/retain acquisition tests: new reserve availability 150000 ms; pending due 125/cutoff 100 plus margin 30 yielding 55000 ms; request charging once; original due time surviving recovery; synthetic occupancy excluded from Job cohorts.
- [ ] Run these tests RED, then make the minimal correction. Only validated newly generated delayed cases omit the redundant blanket addition. Keep unrepresented action delay and legacy zero-offset behavior explicit; do not infer the new marker from historical cases that happen to contain similar offset values.
- [ ] Ensure controller scoring, diagnostic p95, counterfactual ranking and captions share the contract. Check legacy reexports remain numerically unchanged and use fresh destinations for every analysis output.
- [ ] Run relevant tests GREEN, pinned tools and inspect the diff. Commit `fix: avoid duplicate response delay in validated native timing cases`.

### Task 3: Freeze the reasonable reactive baseline and fallback

**Files:** `closed_loop_guards.py`, `demo_configuration.py`, `closed_loop_controller.py`, `closed_loop_journal.py`, and existing configuration/guard/controller/journal/recovery tests.

**Interfaces:** Add optional experiment settings `reactive_target_fraction` and `reactive_downscale_stabilization_seconds`; absent/disabled settings preserve legacy behavior. This campaign explicitly selects 0.80 and 120 seconds. Keep `reactive_action(view, history, *, now_seconds, fallback, tick_id)` and retain durable recommendation history in the journal.

- [ ] Add failing tests for desired workers `ceil(unfinished_requested_cpu / (0.80 * 4))`, clipped to 2..6, including queued work and resources still held after classifier termination.
- [ ] Add failing tests for eager single-worker up, a high recommendation preventing down for 120 seconds, expiry after that window, empty-worker-only removal, shared pending-acquisition blocking, same-tick fallback retaining the earlier high recommendation, and restart before `cycle.end` retaining durable history.
- [ ] Run RED, implement the minimal policy, and seed the initial four-worker recommendation at controller start. Record each valid recommendation before dependent native/action work. Retain entries at the 120-second lower boundary; expire older entries. Do not reset history after actions or restart.
- [ ] Use identical reactive settings and logic for forecast fallback; preserve physical guards and uncertain-action reconciliation. Label this a custom worker-capacity policy, not actual HPA/Cluster Autoscaler.
- [ ] Run GREEN, pinned tools and inspect the diff. Commit `feat: stabilize the frozen reactive worker-capacity policy`.

### Task 4: Runtime verification and today's development comparison

- [ ] Run the complete application suite with `OPENDC_RUNTIME` unset, single-thread limits and the recorded Python/PYTHONPATH. The previous full suite took about 40 seconds; retain this inexpensive gate. Run relevant infrastructure regressions and one bounded native timing probe using the retained image.
- [ ] Use one targeted fresh runtime reviewer for clock/accounting, stabilization and action/recovery changes. Resolve Important/Critical findings before physical development/source sealing; accepted lint complexity findings do not require a separate cleanup milestone.
- [ ] Commit `test: verify final demo contracts and campaign safeguards` before freezing development source.
- [ ] Run fixed five first at period 840 on seed 70001 with three total cycles, two warm-up cycles, one evaluated cycle and 180-second follow-up. If five meets service, select five; do not substitute six. If five fails, use the reserved extra capture to establish six's service before running forecast. If six fails, the candidate is unqualified. Preserve the failed five result as development evidence.
- [ ] Run forecast against the selected adequate count on the same development seed/settings/source. Give the adequate fixed and forecast captures the same complete per-arm initial-allocation declaration; do not pair a fixed-six capture with a forecast declaration that still names fixed five. Preserve exact matching workloads, evaluated sender gate, complete cohorts, allocation bounds and warm-up backlog. Do not label these captures primary evidence.
- [ ] If fixed five and forecast qualify, the extra capture may instead test reactive on the same development workload. It is optional; do not consume the extra slot on both an adequacy check and reactive unless fresh complete remaining bounds prove that additional work fits. If a reactive development capture meets service more cheaply than forecast, report that before proceeding and do not retune the baseline to erase it.
- [ ] Export a compact preliminary table and plots immediately after the matched fixed/forecast pair. Explain whether forecast meets service, conservative savings, physical action origins and any unresolved comparator adequacy. Deliver an update today; further captures need not wait for graph polish.
- [ ] Proceed to primary only with adequate static, forecast service and at least 5% conservative developmental savings. Choose the smallest tested adequate static count and freeze it for both fresh seeds. No static-four stress trial or further period search.
- [ ] Today's feedback may select the adequate count, clarify the presentation/control example and address concrete task defects before sealing. Runtime changes require affected regression/review checks and matching new-source recaptures; old-source fixed data cannot silently be paired with new-source forecast data. Retest only when the complete remaining budget fits. Do not promise discretionary retuning.

### Task 5: Seal and run final data overnight

- [ ] Seal reviewed source/archive hashes, settings, selected static count, deployment/native/worker image identities, seeds, acceptance rules and rotated order: **71001 fixed/reactive/forecast; 71002 forecast/fixed/reactive**. Include actual start/end/restoration boundaries and complete-budget requirement.
- [ ] Run six complete captures at period 840 with **four cycles, two warm-up plus two evaluated cycles and 180-second follow-up**. Fixed starts at the selected adequate count; dynamic arms start four/bounds 2..6. Preserve 90/30-second forecast/reactive cadences.
- [ ] Verify identities/clocks and remaining complete bounds before every launch. All evaluated sender requirements remain at least 95% within 250 ms. Keep rejected attempts separate and visible; do not retune from held-out outcomes or silently replace unfavorable runs.
- [ ] Collect all raw streams, receipts, terminal inventories, journals, native cases and source/image records before exact-owned cleanup. Evaluate service and conservative allocation over the common two-cycle arrival window; completion follow-up does not enlarge the cost window.
- [ ] Stop on primary validation failure, lost ownership, unsafe/unverified state, unqualified development or insufficient complete remaining budget. Preserve unsuccessful evidence and restore. Outcome-dependent searching after primary is not authorized.

### Task 6: Explain, verify, restore and deliver

- [ ] Produce a compact approximately six-page presentation report: three-policy service; absolute allocation and conservative static savings; arrivals/capacity/queues; an explanatory forecast-selected action; reliability/limits; configuration/reproduction. Export slide-ready plots plus complete JSON/CSV metrics. Detailed raw evidence stays alongside its artifacts.
- [ ] For the control example, show what was observed, forecast uncertainty, native alternatives, selected action, safety checks, request/availability and subsequent outcome. Identify later controller actions that prevent isolated counterfactual interpretation.
- [ ] Use a fresh independent evidence/claims reviewer. Resolve Important/Critical analysis defects; distinguish physical source from later analysis changes. Do not deploy runtime fixes against sealed results.
- [ ] Render and inspect every new PDF page. Reproduce all plotted numerical metrics offline from the self-contained payload without raw-capture access and retain proof.
- [ ] Archive owned study state, verify sender/controller/native/job absence, save all eight guests to new private same-host paths, and verify all shut off before resuming exact originals. Verify clocks, baseline checks, presentation UID/spec/readiness, source/RBAC, preserved data/stream prefixes, backing chains and unrelated containers. A wrapper exit status alone is insufficient proof.
- [ ] Provide the changed-code/commit review guide, concise final comparison, honest readiness verdict and user review checklist. Update audience-scoped DESIGN, README only where necessary, and current HANDOFF with authoritative evidence links.
- [ ] Commit delivery changes in focused commits; retire this completed plan from the active tree while preserving its Git history. Push to `git@github.com:atlarge-research/continuum.git` without merging. End with explicit completed/pending status, unmet targets and restoration/preservation proof.

## Whole-workflow budget and deadlines

The approved runner reserves `period_seconds * cycles + 1550` seconds per complete run workflow at follow-up 180. This includes capture setup/collection, verification, archive, metrics, possible recovery and process-group termination. Each matrix reserves another 130 seconds for initial verification. Reserve that initial verification separately for each development capture so adequacy can be checked before selecting the next capture; the primary matrix shares one initial verification. Healthy-run estimates below use the preserved diagnostics status logs, not weakened supervision bounds.

| Reserved phase | Maximum |
| --- | ---: |
| Implementation, focused regressions, lint and native checks | 1h30m |
| Preservation, pool switch and clock preflight | 30m |
| Runtime review and resolution | 30m |
| Required fixed/forecast development pair | 2h20m |
| One extra adequacy or reactive capture, including verification | 1h10m |
| Six full primary captures, including initial verification | 8h13m10s |
| Rejected attempts, follow-up and today's feedback | 30m |
| Compact report, offline verification and evidence review | 1h |
| Verified restoration and preservation | 1h30m |
| Remaining contingency | 46m50s |
| **Total** | **18h** |

The final pre-launch budget proof reserved two matching-source development captures, six primary captures, 20 minutes for remaining feedback/selection and the unchanged 2h30m reporting/restoration reserve. Runtime review and source sealing were completed before this repaired pair; their work is not reserved again afterwards. Optional extra development execution was unavailable under that proof. The extra development capture is a reserve, not permission to expand the search. Restore immediately when safety/search stop conditions arise; unused reserves can absorb authorized delays only. Run heavy analysis after measured captures, not beside them. Supervise stage deadlines so a setup overrun cannot consume the protected closure reserve.

Actual execution start: **October 4, 2026, 14:46:09 Europe/Amsterdam (CEST)**:

| Milestone | Target or protected deadline |
| --- | --- |
| First fixed/forecast development comparison when fixed five is adequate | Final pre-launch estimate: approximately **20:50**; reserved development bound closed **21:42:59**, followed by 20 minutes feedback/selection; comparison was not completed |
| Optional extra capture complete, including fixed-six adequacy if required | Unavailable in the current remaining bound after confirmed observer defects and matching-source recapture |
| Development feedback, final selection/source seal | 20 minutes remaining after pair qualification; runtime/source review and sealing completed before the repaired pair |
| Primary start | Aim **21:00–22:00**; latest **22:02:59** |
| Final primary data, archival and per-run metrics complete | Expected approximately **03:00–04:00 October 5** if started 21:00–22:00; protected through **06:16:09 October 5** |
| Latest restoration start | **07:16:09 October 5** |
| Verified restoration and delivery hard end | **08:46:09 October 5** |

These exact absolute deadlines derive from the start plus 18 hours and remain binding across resumptions. The protected post-capture boundary is hard end minus 2h30m, and latest primary start is that boundary minus 8h13m10s. Record them in the checkpoint and seal; never inherit the previous campaign's expiry. Aim for earlier restoration when reporting is ready or the campaign stops. Initial approval waiting is excluded, but overnight supervision, resumptions, later feedback and recovery do not reset the execution clock.

## Evidence basis and limits

Planning verified the demo tip, current pool state, retained image ID and sample authoritative RAM permissions. Full preservation checks remain execution prerequisites. The preceding [primary summary](/mnt/sdb/matthijs/fns-evidence/opendc-diagnostics-20261003T213920Z/evaluation/primary-summary.json) and immutable cases show forecast using approximately 5.6–5.7 charged-worker equivalents, with little useful downscaling during evaluated 420-second cycles. Read-only reranking of the sixteen recorded native decisions changes seven toward cheaper choices when the extra age margin is omitted. These fixed-state rerankings cannot be summed into physical savings.

Measured mean slot occupancy is approximately 38 seconds. Workload-shape arithmetic suggests roughly 290 seconds of low offered demand at period 840 versus 145 at 420, before backlog and controller effects. This motivates the selected physical candidate but does not establish that it meets the new acceptance rules. A successful demo claim requires the fresh physical comparison; simulation rankings or proposed actions alone are insufficient.
