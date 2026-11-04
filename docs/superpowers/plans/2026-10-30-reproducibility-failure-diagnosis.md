# Continuum: overnight reliability and runtime validation

## Expanded overnight plan — proposed November 3, 2026

The user requested a more ambitious plan after the first packet finished with live validation deferred. This proposal continues from local commit `22c92b8534a60a781eb8c76a3d1b29d404d03343`, retaining that packet and its evidence. The hard deadline is **Wednesday, November 4, 2026 at 09:00 CET**. **07:00–09:00 CET is reserved for closeout.** The substantive target is a reviewed improvement to the complete publisher/subscriber execution path, supported by actual subprocess tests and task-owned VM experiments.

**Status: overnight evidence preserved, teardown follow-up validated.** The user explicitly approved commit `6dbd1e5`, opt-in `Machine.process` deadlines and isolated task-local dependency installation, and started a new execution goal on November 3. The historical first-packet record follows this plan. The approved overnight extension capped production changes at two additional fixes. The user separately approved a third fix after the original deadline.

### Approach and requested scope

The recommended approach combines deeper host qualification, two related runtime fixes, real-process/public-helper tests and one focused live workflow. A validation-only extension would preserve the shared-process restriction but leave known false-success and hanging-query risks. A broad host/framework overhaul would consume the overnight window without establishing the selected execution contract. The recommended approach addresses the evidenced gaps while retaining one integration writer and independent read-only plan, allocation and complete-change review.

Approval would explicitly replace two earlier restrictions: allow an **opt-in deadline in `Machine.process`**, and allow a **task-local Python environment with dependency installation if no compatible existing environment is available**. Environment setup is limited to an isolated directory on the selected host, a compatible existing interpreter and the existing requirements, with a 45-minute cap and recorded package versions; no system packages, privilege installation or changes to existing environments. Approval also covers an ordinary isolated remote source checkout/export at the reviewed revision when the native worktree tool cannot create on that host, plus evidence-preserving cleanup of exact task-created VM domain names and UUIDs after failures. The integration writer continues in the existing isolated worktree; the selected host runs a frozen source snapshot without modifying its existing checkout.

All other boundaries remain: no VM mutations on node3/node4; no merge, push, tag, publication, cloud spending, historical cleanup, shared registry restart/reconfiguration, daemon/firewall/network/trust changes, registry endpoint option, remote-only scheduler, production fault-injection interface or general recovery framework. Killing local SSH does not prove remote work stopped; inspect and clean up the task-owned remote resources separately. Existing checkpoint evidence keeps its original source and limitations.

### Evidence motivating the extension

The first host audit established only that no host qualified under the checks performed. It did not search alternate existing Python environments on node2 or identify the protocol/service behind node1's unexpected registry response. A missing default venv alone is insufficient grounds to stop qualification.

Read-only execution-path review reproduced two publisher-completion false successes in `resource_manager/endpoint/endpoint.py::wait_endpoint_completion`: a requested `endpoint0` accepts only an unrelated `endpoint00` row, and a nonempty container list paired with an empty SSH list returns success without querying anything. The same function can poll an `Up` container indefinitely. This function is called by `application.application.kube` before subscriber completion and results processing; these are selected-path defects, not unrelated legacy cleanup.

The first packet's SSH timeout test injects `TimeoutExpired`; it does not observe a real child being killed. Kubernetes event API/excerpt limits likewise do not bound the underlying `Machine.process.communicate()` or host-key repair. A responsive SSH transport with a hung remote command can hold a primary status query or failure diagnostic indefinitely. The new tests must distinguish configured timeout arguments from actual process termination and preserved errors.

### Schedule and hard gates — all times CET

| Window | Work and required output |
| --- | --- |
| Approval–22:15, November 3 | Complete bounded host qualification, record exact individual probe outcomes and review a candidate allocation; reproduce the selected endpoint/process gaps. Existing-environment qualification is capped at 45 minutes; optional isolated environment setup adds at most 45 minutes. |
| 22:15–00:30 | Implement and independently review the opt-in process deadline and publisher completion fixes, with RED→GREEN focused tests, real child-process evidence and public lifecycle composition tests. No VM launch on unreviewed runtime bytes. |
| 00:30–04:30, November 4 | Run infrastructure/software, isolated negative probes and two same-base healthy application executions. Investigate any unexpected failure once before deciding on a scoped correction; preserve failed attempts and their source bindings. |
| 04:30–06:00 | Admit no new feature work. Stabilize the selected changes and run any affected final-source validation still needed; retain earlier runs under their original revisions. Decide each launch against its worst-case timeout, diagnostic and cleanup budget. |
| 06:00–07:00 | No new live phase, probe or application repeat starts after 06:00. Begin exact task-owned cleanup by 06:30; stop live work and freeze implementation by 07:00. Skip any launch whose worst-case runtime plus cleanup cannot meet these gates. |
| 07:00–08:00 | Reconcile source/test/runtime evidence, inspect complete logs and image counts, verify VM/pod disposition, finish documentation and independent complete-change review. |
| 08:00–08:45 | Resolve factual review issues, create local commits and verify the exact diff/source/evidence receipt and final handoff. Runtime defects discovered during closeout are unresolved findings unless an already validated correction fits the hard deadline. |
| 08:45–09:00 | Delivery buffer; publish the human review package in this chat by 09:00, including an explicit partial handoff if a required experiment or cleanup remains unresolved. |

The schedule is a ceiling and decision structure. Completion requires the substantive acceptance evidence below; passing static tests alone does not complete the expanded runtime objective. If a host remains unavailable after the full qualification/setup budget, continue with the reviewed code and real-process/composition evidence and label the live objective incomplete. Do not spend the night building infrastructure around the blocker or repeating unchanged checks.

### Task 1: qualify a host and review the allocation

- [x] Inspect node1 first: identify the port-5000 listener, registry container port mapping and selected nonsecret HTTP/TLS settings. Use bounded HTTP and TLS probes and test the actual host address Continuum derives, not only loopback. Preserve each exit status separately. Do not relax HTTP parsing or restart/reconfigure the service to obtain a nominal pass. Cap this diagnosis at 15 minutes.
- [x] If node1 cannot qualify, inspect node2's likely existing interpreter roots (`venvs`, `.virtualenvs`, Anaconda/Miniconda environments, repository `.venv` and its user-owned storage root) with bounded depth. Test a small number of candidate interpreters for `yaml,jinja2,ansible,numpy,pandas,matplotlib,requests`, and record the corresponding `ansible-playbook` interpreter/version. If explicitly approved and necessary, attempt the isolated environment allowance once, preserving installation failures without system repair. Node6/node8 remain unavailable unless existing authorized access/trust evidence resolves their prior failures.
- [x] Run live commands directly on the qualified host with `--external-physical-machines ""`. Do not run from node4 with an external-host override: `make_machine_objects` always includes local, and scheduling would allocate a VM on excluded node4. The native worktree tool currently lacks a destination-host option; use the approved isolated remote checkout/export only after verifying the frozen source manifest, dependency environment and runner source attribution.
- [x] Before any infrastructure command, independently review the exact host, canonical new task base, guest/base address blocks, all active/inactive domains, available storage/capacity, active framework processes and username-wide startup/teardown cleanup scope. Require no other `_matthijs` guest or concurrent same-user Continuum workflow. A unique base directory alone does not isolate domain cleanup. Preserve node2's `_dha` guests and edited checkout.
- [x] Record how each task-created domain name, UUID and image path will be identified. On failure, preserve evidence first, then stop/remove only exact owned domains after rechecking UUIDs; do not use username-wide provider cleanup as a fallback. VM teardown does not authorize deleting failed disks or historical evidence. If safe cleanup/ownership cannot be established, do not launch.

### Task 2: bounded single-command process execution and scoped callers

**Files:** modify `infrastructure/machine.py` and `application/runtime_helpers.py`; create `scripts/test/unit/test_machine_deadlines.py`; extend `scripts/test/unit/test_kubernetes_job_reuse.py` and the existing SSH discovery regressions. Preserve the first packet's source/evidence attribution.

**Interface:** propose `Machine.process(..., timeout_seconds=None)` with current behavior unchanged when omitted. A supplied value must be finite and positive; bounded mode accepts exactly one effective command with `wait=True`, validated **after SSH target expansion and before any subprocess or host-key work**. Unsupported combinations fail before launch. Bounded mode performs one attempt with no automatic retry or host-key repair. It retains the existing nested stdout/stderr result shape, including partial output, original stderr and an explicit timeout error. This is a narrow opt-in execution mode, not a replacement for ordinary process execution.

- [x] Write failing regressions for a genuinely sleeping child, partial output followed by a hang, inherited stdout/stderr held open by a descendant, cancellation, invalid/nonfinite timeout, `wait=False`, multi-command/multi-target expansion, and normal success/nonzero results. Verify that the deadline prevents another launch after exhaustion and that omitted timeout retains existing retry, host-key and background behavior.
- [x] Implement one execution budget plus a separately documented fixed cleanup grace, provisionally two seconds. Terminate/reap the locally started process group and close held pipes without an unbounded final `communicate`; preserve cancellation. If cleanup cannot complete, surface a cleanup failure rather than claim termination. No threads, duplicate SSH-option construction or remote `timeout` workaround. If this cannot stay bounded without broader refactoring, stop this task and record the design gap.
- [x] Forward an optional timeout through `_checked_kubectl`, `_kubectl_items` and `_execution_pods`, preserving defaults for preparation, deletion and output paths. Current-execution polling checks its remaining budget before a status request, uses `min(10, remaining)` seconds and caps its retry sleep. A status-query timeout is an immediate primary error with original stderr; do not delay it with event collection.
- [x] Event diagnostics use one shared 15-second execution budget across at most three UID queries, each at most five seconds, plus the explicitly bounded cleanup grace. Preserve the existing ten-event/message-length caps and original readiness/terminal error if diagnostics fail. Describe observed waits as polling budget plus diagnostic/cleanup overhead; do not claim all provisioning or legacy paths now have wall-clock bounds.
- [x] Add real-process SSH discovery checks using disposable PATH-first fake executables and a generated disposable host key: delayed key success, banner-only output and a sleeping keyscan must exercise real subprocess behavior and verify no fixture process remains. Test-only drivers/fixtures stay under existing test support or private task artifacts; add no production fault-injection setting.

### Task 3: publisher identity and completion correctness

**Files:** modify `resource_manager/endpoint/endpoint.py::wait_endpoint_completion`; extend `scripts/test/unit/test_endpoint_runtime.py`; reuse the existing stateful Kubernetes fake in `scripts/test/unit/test_kubernetes_job_reuse.py` for public orchestration composition. Ruling: keep composition regressions with that existing lifecycle fixture instead of creating a second fixture/file; this exercises the same planned public `application.kube` acceptance with less duplicated setup. Use Task 2's opt-in mode for the single status query; the existing default process callers remain unchanged.

**Interface:** preserve the public completion function signature and successful return behavior. Validate target/container cardinality before polling, retaining legitimate empty/empty behavior. Query/match the exact expected container name, require its successful exit code and reject missing/malformed/nonzero results. Use one monotonic completion budget across all selected containers: propose `max(900, duration + 300)` seconds, where benchmark `duration` is seconds. Charge initial/retry sleeps and transient/empty-result waits to this budget, cap each status subprocess at `min(10, remaining)`, and report the target/container, elapsed time and last error/status on exhaustion. Add no public timeout configuration knob. Before implementation, verify this conservative budget against existing long-duration callers and document any evidence requiring a different fixed policy.

- [x] Reproduce exact-name collision and mismatched target/name false success before fixing them. Add healthy Up→Exited(0), empty/empty, missing container, malformed status, nonzero exit, forever-Up, shared multiple-container deadline and transient/empty-output cases that cannot reset the clock. Preserve real transport failures.
- [x] Run public `application.kube` composition regressions using actual readiness/completion helpers and test-only machine/CLI fixtures: an unready or terminal subscriber prevents publisher launch; publisher completion failure prevents subscriber-completion processing, metrics and successful publication. These tests must fail on the old behavior rather than merely assert a mocked helper call.
- [x] Independently review both runtime fixes together before live execution. At most these two additional production fixes enter this extension; an unrelated legacy wait, scheduler, recovery mechanism or configuration redesign is deferred.

### Task 4: live failure probes and two healthy executions

Use the existing direct `run_tests.py --config` workflow: `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`, then `02_software_k8s_three_vm.yaml`, with reviewed explicit `--base-path`, `--middle-ip`, `--middle-ip-base` and empty external-host overrides. Capture exact source, normalized config/lock, environment, argv, timing, streams and Ansible recaps for each phase. The shell wrapper does not forward these overrides.

- [x] After software, create inert direct Pods with unique task/probe names and labels, `restartPolicy: Never`, small resource requests and recorded UIDs. Invoke the actual public readiness/completion helpers with **copied** configurations selecting only that probe; preserve the healthy workflow's configuration. Use an explicit outer driver/process-group deadline as a final experiment bound, with helper timeout and observed elapsed time recorded separately.
- [x] Bad image: use one nonexistent task-specific image reference, exercise readiness with a 60-second polling budget, and retain the expected timeout, changed waiting reason, scoped events and elapsed time. Delete only the exact owned Pod after evidence capture. Unexpected failure or success is a failed probe, not grounds for a blind retry.
- [x] Running but unready: use the exact already-cached worker image with `imagePullPolicy: Never`, an overridden inert command and a failing readiness probe. First observe Running plus Ready=False; then require the helper to time out within its documented budget/overhead. This must not silently become another image-pull test. Preserve evidence and delete exactly that Pod.
- [x] Successful terminal Pod: override a cached image's command to exit zero, observe Succeeded, then require startup readiness rejection and first-poll completion success against that same UID. Delete exactly that Pod. API failure is exercised through the real local helper/process chain with a disposable test CLI/kubeconfig adapter, clearly labeled as adapter evidence; do not change a shared API server, firewall or production kubeconfig.
- [x] Before healthy applications, verify probe Pod absence and benchmark-selector isolation. Run the first 30-second, frequency-one application using an otherwise identical private retain-on-exit variant. This is supported because the resume contract excludes `delete_on_exit`. Preserve the complete first result/logs/metrics/state/lock and Job/pod/execution identities before later current pointers change.
- [ ] Without rerunning infrastructure/software, run the existing final application config with teardown enabled and the same reviewed overrides. Require **30 sent, processed and received images on each execution**, fresh Job/pod UIDs and execution labels, archived first subscriber output, successful second results and exact task-owned domain absence after teardown. A cumulative total cannot substitute for two correct individual results. No thirteen-group certification rerun or optional topology expansion is part of this plan.

### Task 5: final validation, independent review and morning package

- [x] Run focused tests after each material fix; on the completed code run `PYTHONPATH=. python3 -B -m unittest discover scripts/test` once, then changed-file pylint and applicable whitespace/docs-path/release-claims/release-matrix checks. Re-run a gate only when changed source, a failure or an unresolved concern justifies it. Separate baseline lint findings from new findings.
- [x] Bind each successful/failed live result to its actual revision. If a later correction affects an earlier run, repeat only the affected validation within the launch/cleanup gates; otherwise explicitly retain the source-attribution limitation. Preserve unexpected failures before investigation; no blind retries or rewriting failed evidence as successful evidence.
- [ ] Independently review the complete uncommitted extension, adjudicate material findings, and re-review materially revised parts. Update this existing proposal, `docs/ISSUES.md` and `docs/rework_release_handoff.md` without a new plan/report hierarchy. Keep the completed first packet separately attributable.
- [ ] Deliver exact local commits and diff, commands/environments, test and negative-probe results, per-run 30-image counts, before/after execution identities, VM/pod disposition, independent reviews, unresolved items and a short keep/simplify/fix/defer table. Commit locally only. By 09:00 deliver either the completed expanded pass or a partial handoff identifying any live, correctness or cleanup requirement still unmet.

### Independent plan review and primary adjudication

Read-only reviewers `/root/expanded_plan_review` and `/root/host_preflight` examined this expansion before documentation or implementation. Their material findings were incorporated: single effective command after SSH expansion; no bounded-mode host-key repair; explicit cleanup grace and inherited-pipe/cancellation tests; primary status-query bounds as well as event bounds; conservative endpoint duration policy; fuller environment qualification; no node4-controller workaround; username-wide cleanup inspection; exact failure teardown; and precise isolated-probe/two-run acceptance. The revised caller scope was re-reviewed and accepted as one narrow process-deadline fix with three selected callers. These reviews assess the proposal; they do not constitute user approval of the changed implementation/setup boundaries or a live host allocation.

### Execution record — November 3

The user subsequently approved the full plan and started the expanded execution goal. Node1's registry diagnosis established TLS on port 5000 and an expired/self-signed certificate; HTTP on the actual route address still fails. No registry/trust change was made. Node2 has an existing compatible `/home/matthijs/anaconda3/envs/opt/bin/python3` (Python 3.10.14, Ansible 2.13.2, NumPy 1.26.4, pandas 2.2.3); no dependency installation is needed. Its registry works over the required plain HTTP on `192.168.1.102:5000`.

The two runtime fixes and real-process/composition regressions are implemented. Independent read-only runtime review by `/root/runtime_change_review` found no actionable findings and independently passed 59 focused tests; the broader focused selection including existing runtime helper tests passed 105. Endpoint duration is already a validated integer number of seconds for image classification and translation, including long-duration callers; the floor-plus-duration policy therefore does not truncate the configured publishing period. Process/caller tests retain the distinction between execution budget and cleanup/diagnostic overhead. Final code validation passed 105 focused tests and 1,197 combined tests. A second combined run was justified by correcting the public composition test fixture after its historical-baseline check reached a missing fixture key; the corrected negative check now exposes premature publisher launch directly, and the final run binds the corrected test bytes. Changed-file lint reports existing findings only, with their baseline outputs preserved; both new/expanded process, Job reuse and SSH test files have no new findings. Allocation review conditionally approved node2 after correcting phase 01 to generic `base0_matthijs`, distinguishing the Ansible launcher interpreter, and verifying the proposed address evidence. Source export and fresh prelaunch checks were verified. Both healthy 30-image executions and all negative probes passed; final automatic teardown failed on node2 because the default libvirt session was empty while guests ran in the system connection. Exact approved manual cleanup verified actual task-domain absence. The separately approved correction and its evidence are recorded below.

### Live evidence and teardown follow-up

Both 30-image workloads and all negative probes passed on `c9c9910`. Automatic teardown inspected the default session and missed the task VMs in the system connection. Exact UUID cleanup established task domain absence. After 09:00 CET on November 4, the user approved the additional libvirt correction and paused VM validation. Commit `ad166bf` uses the creation connection explicitly for deletion and verification. The empty-session regression and separately owned paused transient VM check passed. The historical Task 4 checkbox stays open because the original application teardown failed. The follow-up receipt and scope are recorded in the [handoff](../../rework_release_handoff.md#teardown-follow-up--november-4-2026).

## Completed first packet — November 3, 2026

The November 3 overnight goal explicitly authorizes this audit and the two fixes, starting from `364a63ffbf7d59bcf05c2e46fc432612289d7f98` in an isolated worktree. Deliver by November 4 at 09:00 CET, reserving 07:00–09:00 for closeout; stop earlier when finished. One integration writer implements and independent reviewers remain read-only. Node3/node4 are excluded from VM mutations. No merge, push, publication, historical cleanup, privilege/dependency installation or architecture work. Preserve accepted checkpoint evidence and attribution.

The requirements below retain the original proposal's scope; the completed coverage audit and execution record follow them.

## Goal and effort limit

Improve how Continuum handles slow startup and explains networking/container failures, while keeping maintenance costs small.

**Limit: one to two engineer-days total, including the initial coverage audit, tests and documentation. At most two small implementation changes.** Stop early with zero fixes if existing rework coverage is sufficient. Record larger gaps for later.

This follow-up is separate from the accepted checkpoint. It does not promise deterministic performance or eliminate failures caused by unavailable infrastructure.

## 1. Check existing coverage first — maximum two hours

The tutorial-mpi demo used the older `tutorial-mpi` branch. The proposal identifies phase/state tracking, constrained resume, image/cache verification, failure propagation, and several readiness checks as existing rework mechanisms to verify and reuse.

Map these four observed problems to existing code and tests:

| Demo observation | Contract to check |
|---|---|
| Failed provisioning could return exit code zero | Failed required operations produce a nonzero result and retain the underlying error. |
| Guest DNS failed although host access worked | Failures preserve guest-side/runtime evidence; host connectivity is not treated as proof of guest connectivity. |
| Controller and monitoring startup exceeded waits | Waits have finite budgets and check the condition required by the next operation. |
| Monitoring pods were ready but an HTTP endpoint was unreachable | Existing observability verification checks the advertised endpoint. |

Produce a short **covered / missing / deferred** table with test references. Do not duplicate working mechanisms or backport the tutorial recovery scripts.

## 2. Make only these small fixes where still needed

### First priority: bound fresh-VM SSH discovery

Confirmed gap at the starting commit: `infrastructure/infrastructure.py::add_ssh` contained an indefinite keyscan loop.

- Give each invocation one **600-second monotonic budget**, shared across its selected guest addresses.
- Give every keyscan subprocess an actual execution timeout of at most **five seconds**, capped by remaining time. Checking a deadline between attempts alone cannot bound a hung subprocess.
- Require actual host-key output; a server banner alone is insufficient.
- Preserve existing known-host handling and host-trust policy.
- On exhaustion, fail nonzero with the guest address, elapsed time, and last probe error in the existing logs.
- Keep this change local to SSH discovery. Preserve the shared execution API. Key discovery must not be described as authenticated guest readiness.

### Second priority: improve the existing Kubernetes workload wait

Confirmed gap at the starting commit: `application/runtime_helpers.py::_wait_kubernetes_execution` checked pod phase but missed readiness and useful image-pull explanations.

- For subscriber startup, require the expected execution’s pods to be `Running` with `Ready=True`.
- Preserve completion behavior: `Succeeded` remains successful during completion polling, even on its first poll.
- Preserve existing execution selectors, timeout settings, and immediate API/transport failure propagation.
- From already-fetched pod JSON, report condition changes and init/container waiting reasons and messages.
- On timeout or terminal failure, collect a bounded, best-effort event excerpt scoped to those pods. Diagnostic collection must not replace the original error.
- Let Kubernetes perform its existing image-pull retries. Do not introduce deployment restarts or handlers for individual error messages. Kubernetes already retries image pulls with backoff. [Kubernetes image documentation](https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff)

Pod readiness improves health verification; it does not prove application-level MQTT subscription without a corresponding application probe.

## 3. Verify with focused tests

Use existing test utilities and smoke artifacts.

- SSH discovery: delayed success, unreachable guest, banner without a key, hung subprocess, and multiple guests sharing one deadline.
- Kubernetes: absent pods that later appear; `Running` but unready; ready subscribers; transient image-pull failure that recovers; persistent pull failure with useful timeout evidence.
- Preserve existing tests for prematurely completed subscribers, successful completion, and API/transport failures.
- Run one healthy supported QEMU/Kubernetes workflow exercising the changed workload path, plus one isolated invalid-image case using the existing harness.
- Use an approved test allocation. Do not alter shared-host firewall rules for fault injection.

Completion requires passing affected tests, retained logs, and an updated coverage table. Deferred gaps must remain explicit.

## 4. Keep the maintenance boundary small

Add a short troubleshooting note to existing documentation: inspect guest DNS/routing and the actual container-runtime error when image retrieval fails; inspect endpoint reachability separately from pod health. Docker forwarding rules are a known possible interference source, not a diagnosis to assume automatically. [Docker networking documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/)

**No new CLI commands, result schemas, recovery framework, automatic firewall changes, dependency-packaging project, or resource scheduler.** Preserve existing state, lock, and smoke-result contracts.

If either fix requires broader execution changes or would exceed the two-day cap, defer it. Delivering one verified fix—or confirming that existing coverage is sufficient—is an acceptable outcome.

## Bounded execution plan — November 3

- [x] Audit existing coverage within two hours and obtain independent read-only plan review before implementation. Review confirmed both gaps and existing selector/error/completion/observability coverage.
- [x] Add focused SSH regressions in `scripts/test/unit/test_ssh_discovery.py`, run RED, then change only `infrastructure/infrastructure.py::add_ssh` to implement the specified shared deadline, local subprocess timeouts and actual-key validation. Preserve key removal and configured known-host destination. Run GREEN.
- [x] Extend `scripts/test/unit/test_kubernetes_job_reuse.py`, run RED, then change current-execution waiting in `application/runtime_helpers.py` to require Running and Ready=True at startup, log changed waiting reasons and collect bounded UID-scoped events on terminal/timeout errors. Preserve selectors, completion and immediate primary API errors. Run GREEN.
- [x] Inspect node1, node2, node6 and node8 in order; independently review first qualified allocation before launch. Run direct three-phase benchmark configs with explicit base/address overrides, inserting one uniquely named/labeled bad-image pod and a 60-second real-helper probe between software/application. Preserve negative evidence, delete only that pod, complete healthy 30-image application and verify task-owned teardown. Otherwise document concrete deferral. Outcome: deferred because none qualified; no allocation or launch occurred.
- [x] Run focused tests, the combined Python suite once on completed changes, changed-file lint and applicable docs checks. Obtain independent read-only review of the complete uncommitted change and resolve material findings. Update this proposal, `docs/ISSUES.md` and `docs/rework_release_handoff.md`; prepare the local-commit review package with exact diff/commands/results/reviews/VM disposition plus keep/simplify/fix/defer decisions.

Pre-flight: code tasks share no implementation interfaces. Keep `Machine.process` unchanged and add no configuration knobs. Review focus: missing Ready conditions, unrelated/old pod events, diagnostic failures, hung keyscan cleanup and multi-guest budget exhaustion. Plan reviewer: `/root/coverage_plan_review`, read-only; accepted advice includes capping sleeps, UID event scoping and explicitly testing first-poll completion.

## Coverage audit — November 3, 2026

The audit completed within its two-hour cap. Both proposed implementation gaps were confirmed; existing mechanisms below are reused. Test paths are relative to `scripts/test/`.

| Area | Disposition | Evidence and action |
| --- | --- | --- |
| Required-operation failure propagation | Covered | `unit/test_continuum_runtime.py::test_process_surfaces_silent_nonzero_return_code`, `test_process_appends_nonzero_return_code_to_warning_stderr`, `test_failed_readiness_and_software_stages_prevent_publication`; `e2e/test_run_tests.py::test_normal_nonzero_execution_preserves_output`. No new mechanism. |
| Guest DNS/runtime evidence | Covered / deferred | Existing process handling preserves stderr; `unit/test_continuum_runtime.py::test_cache_failure_preserves_real_stderr_without_synthetic_source_dump` protects original cache failures. A dedicated guest-DNS regression/framework is deferred; add guest-side troubleshooting guidance only. |
| Fresh-VM SSH discovery | Missing → implemented | The old `add_ssh` loop was indefinite and accepted stderr banners. `unit/test_ssh_discovery.py` now covers delayed success, unreachable/banner-only responses, subprocess timeout, shared multi-guest budget, nonzero partial output and known-host cleanup failure. |
| Current-execution selectors and immediate query errors | Covered | `unit/test_kubernetes_job_reuse.py::test_empty_selection_times_out_even_with_unrelated_running_pod`, `test_current_log_and_readiness_ignore_unrelated_failed_pod`, `test_readiness_command_error_is_not_retried_as_pending`; preserve these contracts. |
| Subscriber readiness and diagnostics | Missing → implemented | `unit/test_kubernetes_job_reuse.py` adds missing/false/boolean Ready conditions, all selected subscribers, init/container waiting changes, image-pull recovery, UID-scoped bounded events, absent UIDs and diagnostic failures. |
| Startup terminal rejection / successful completion | Covered / strengthened | Existing Job reuse lifecycle tests plus `test_readiness_rejects_terminal_fresh_subscriber` and new `test_completion_succeeds_first_poll_without_ready`. |
| Advertised observability endpoints | Covered | `unit/test_role_contracts.py::test_readiness_checks_both_replicas_and_distinct_service_addresses`, `test_http_failures_exhaust_attempt_budget_and_preserve_diagnostics`, `test_transient_health_failure_retries_then_succeeds`, `test_diagnostic_failures_do_not_replace_original_error`. Skip another fix. |
| Live healthy benchmark and bad-image helper probe | Deferred | Read-only host preflight found no prerequisite-qualified allocation; see the current handoff. No VM, pod, registry, dependency or host-trust mutation was made. |

The primary writer accepted the independent plan review's material cautions. The native execution workflow is used with the repository's required pre-implementation and complete-change read-only reviews. Ruling: retain the existing authoritative proposal as plan and record rather than generating another plan/ledger hierarchy; the user explicitly requested this bounded execution and one integration writer, so no renewed execution-method approval is required.

## Closeout result — November 3, 2026

The two fixes are implemented and independently reviewed. The final focused selection passed 76 tests and the completed-change combined suite passed 1,174 tests in 155.092 seconds; no separate unit/e2e reruns were needed. Changed-file pylint reports only six pre-existing findings reproduced against the starting commit: four long lines and two unused arguments. There are no new lint findings, and both changed test files are clean. Whitespace, documentation paths, release claims and release matrix checks pass. An initial documentation-path failure for a remote node2 file reference and an initial pylint cache-write warning are retained in the private logs alongside corrected final runs.

Independent complete-change review (`/root/complete_change_review`, fresh context, read-only) found no actionable correctness findings; its stale-status documentation notes were addressed. Review and host-preflight summaries, exact commands/environments, source/output hashes and raw final validation streams are under `/home/matthijs/continuum/logs/overnight-reliability-20261103`. The final local commit, exact binary diff/stat and file hashes are identified by `final-source-receipt.json` there. Raw RED-run output remains in the chat transcript; the retained review record explicitly distinguishes summarized negative evidence from raw logs. Expected SSH discovery failures and Kubernetes diagnostic failures appear in the passing focused/combined logs. There is no new live bad-image or healthy benchmark evidence.

Ruling: defer live validation under the objective's explicit host-prerequisite boundary, preserving node1's registry failure, node2's dependency failure and node6/node8 access failures rather than installing dependencies, changing trust or adding remote execution machinery. The cost is that the changed paths have unit/regression evidence but no new VM-backed integration evidence. Keep the local branch/worktree for human review; no merge, push, tag or publication. See the current handoff's keep/simplify/fix/defer table and host disposition.
