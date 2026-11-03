# Continuum: a small reproducibility and failure-diagnosis pass

## Status: authorized bounded follow-up — November 3–4, 2026

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
