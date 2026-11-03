# Continuum: a small reproducibility and failure-diagnosis pass

## Status: deferred, requires renewed user discussion

This saves a future proposal outside the current checkpoint. Before scheduling or executing any part of it, including the initial coverage audit, discuss again with the user whether this work is wanted or mostly overengineering, and obtain a renewed decision. Saving this proposal authorizes no audit or implementation.

Named functions, existing-coverage claims and proposed gaps below are candidates to verify during that later audit, not findings from a current coverage review.

## Goal and effort limit

Improve how Continuum handles slow startup and explains networking/container failures, while keeping maintenance costs small.

**Limit: one to two engineer-days total, including the initial coverage audit, tests and documentation. At most two small implementation changes.** Stop early with zero fixes if existing rework coverage is sufficient. Record larger gaps for later.

This is a future backlog item for the rework thread, separate from its current checkpoint. It does not promise deterministic performance or eliminate failures caused by unavailable infrastructure.

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

Candidate gap to verify: whether `infrastructure/infrastructure.py::add_ssh` still contains an indefinite keyscan loop.

- Give each invocation one **600-second monotonic budget**, shared across its selected guest addresses.
- Give every keyscan subprocess an actual execution timeout of at most **five seconds**, capped by remaining time. Checking a deadline between attempts alone cannot bound a hung subprocess.
- Require actual host-key output; a server banner alone is insufficient.
- Preserve existing known-host handling and host-trust policy.
- On exhaustion, fail nonzero with the guest address, elapsed time, and last probe error in the existing logs.
- Keep this change local to SSH discovery. Preserve the shared execution API. Key discovery must not be described as authenticated guest readiness.

### Second priority: improve the existing Kubernetes workload wait

Candidate gap to verify: whether `application/runtime_helpers.py::_wait_kubernetes_execution` checks pod phase but misses container readiness and useful image-pull explanations.

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
