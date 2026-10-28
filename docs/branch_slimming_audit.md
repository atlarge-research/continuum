# Branch slimming audit

This applies Section8 of `docs/rework_milestone_release_plan.md`; it is factual
scope accounting, not another policy or certification ledger. At clean
`d93f8903ff28904aeee071ff4cbbbcd2e14c198f`, a fresh `git diff main...HEAD --shortstat`
reported 470 changed files, 74,773 insertions and 5,463 deletions. That is the
pre-checker-packet checkpoint, not a final-candidate count; recalculate at final
acceptance. No arbitrary line-count target is used.

## Major additions: one category each

Categories are: 1 reproduction/runtime behavior; 2 correctness/safety;
3 regression coverage; 4 test-host boundary; 5 active provenance/evidence;
6 obsolete/superseded material; 7 duplicate/unnecessary machinery.

| Major addition | Category | Concrete disposition and justification |
| --- | ---: | --- |
| Structured experiment/environment/software schema, composition and selector/planner handoffs | 1 | Retain the requested structured workflow and deterministic module placement; no additional configuration framework. |
| Provider provisioning/scheduling/generation and software role/playbook refactors | 1 | Retain the execution paths needed by the nominated workflows; source presence does not establish additional provider claims. |
| Application launch paths, instrumented Columbo/Kata traces and text-translation implementation | 1 | Retain execution/artifact behavior. R03/R04 remain required; other associations remain bounded by `docs/reproduction_inventory.md`, not inferred paper equivalence. |
| Shared application completion/output handling | 2 | Retain fixes that distinguish finished publishers/pods and real benchmark output from a successful launcher return. |
| Machine process transport, physical-owner execution and SSH preflight | 2 | Retain nonzero/error/stream handling and fail-before-dispatch checks; shell presentation is not a success protocol. |
| State, lock and narrow resume contracts | 2 | Retain basic shape/phase/topology/software/SSH checks and preserved failure state, not arbitrary recovery or cross-commit resume. |
| QEMU single-slot cache validation and ready publication | 2 | Retain exact owner-local mutation, valid-peer preservation, baked-input checks and publication only after confirmed stop; no generations or permission repair. |
| Registry requirement/identity and network-evidence validation | 2 | Retain the distinction between required image identity and a tag name, and between actual network measurements and configured intent. |
| Unit, local-e2e, shared test support, fixture catalogs and coverage metadata | 3 | Retain proportional negative/behavior coverage. Removed tests exercise removed debug/exception behavior or demonstrably duplicated command-policy checks; not deletion for size. |
| Normal-user host setup/runner, explicit paths and retained-result/storage/pruning interface | 4 | Retain explicit normal-user execution and bounded evidence handling. The separate-account/installed-helper boundary is retired; this is high-trust execution, not sandbox isolation. |
| Dependency/lint/ignore settings and repository agent workflow guards | 2 | Retain reproducible validation, generated/credential exclusion and scoped review discipline; these do not confer runtime privileges. |
| Current semantic/user/operator documentation and approved authority map | 5 | Retain the actual configuration, runtime, support and publication boundaries in one owner per concern. |
| Release claims/matrix/artifact/source-readiness checks and their active integration | 5 | Retain distinct demonstrated false-claim protection below; static success never renews runtime evidence. |
| Dated release evidence and model/data/image provenance | 5 | Preserve exact historical runs and attribution needed to understand retained claims; no date, source or status renewal. |
| Legacy cfg/DSL/role archives and research-script associations | 5 | Preserve historical workflow evidence pending the single final scope answer. Do not execute obsolete scripts or delete candidate functionality by assumption. |
| Completed dispatcher, Phase-C/Phase-D execution ledgers and frozen implementation ledger | 6 | Consolidated into immutable b484f120f81c437f29d61b19ff5fec4e3790c58e Git references plus verified full private copies and the four-row binding in `docs/rework_release_handoff.md`. Current authority/closure boundaries remain unchanged. |
| Old account/installed helpers and temporary diagnostic replay surface | 6 | Account/helpers are privately quarantined after verified migration. The debug command/playbook and four exclusive tests were removed in d93f890; Git preserves the source. Narrow result interfaces remain. |
| Historical wrapper-literal and Kata runtime-source freshness exemptions | 7 | Remove: real temporary-Git regressions showed changed runtime code could remain compatible with old evidence. No runtime path gets a special waiver. |
| Repeated pre-tag command-list policy pass | 7 | Remove from informational pretag readiness; the unchanged required matrix gate already owns identical presence/order/duplicate policy and its negative tests. |

## Checker retention and consolidation

| Checker | Demonstrated false claim prevented; retained responsibility |
| --- | --- |
| `scripts/test/check_docs_paths.py` | A current operating reference points to a deleted file. The debug removal actually exposed the historical playbook reference; it now resolves to an immutable Git object, without weakening this check. |
| `scripts/test/check_release_claims.py` | Parser/shipped-example coverage or code-present cloud modules are described as supported runtime. Existing negative tests reject these statements and require matrix scope. |
| `scripts/test/check_release_matrix.py` | A subset masquerades as its parent, a certified row lacks exact config/suite/evidence, a historical row disappears, or release command policy is missing/misordered/duplicated. These remain required checks with dedicated negative tests. |
| `scripts/test/check_release_evidence_artifacts.py` | A launcher/state marker is substituted for metric/network/trace/teardown artifacts or the named artifact is missing/stale. Actual audits still find missing historical benchmark/state evidence; negative tests reject incomplete full control-plane traces and cleanup without teardown. |
| `scripts/test/check_release_pretag.py` | A dirty tree, changed runtime source, stale audit or failed host verification is presented as release-ready. Retain these checks; remove the two historical source waivers and the duplicate matrix-owned command-policy pass. Real-Git negatives cover both former waivers. |
| `scripts/test/verify_network_profiles.py` | Declared network settings are mistaken for measured latency/throughput success. Retain measured-artifact/tolerance validation and its negative regressions. |
| `scripts/test/check_kata_host_prereqs.py` and registry-cache prerequisite checks | Claimed runtime capability/cache readiness lacks the required host capability or image identity. Retain prerequisite checks, explicitly not reproduction/application certification. |

The audit compile list retains all four release checkers. Its twelve required
gates are unchanged; artifact/pre-tag readiness, pytest mirrors, lint baselines,
debt scan and suite prerequisites remain informational there. Applicable changed
file validation still applies. Matrix command-policy checks have one required
owner; source freshness is stricter, not bypassed to make old evidence pass.

## Open boundaries

Completed-ledger consolidation preserves full Git objects and independent private
copies at the exact b484f12 source checkpoint; current files retain navigation.
The historical reproduction-scope answer, final legacy dispositions, refreshed
configuration hashes and fresh exact-candidate runtime/manual acceptance remain
open. Same-application parameter sweeps remain candidate-only until collision-free
cleanup/idempotence is demonstrated separately. Nothing here authorizes cloud
spending, broad deletion, privilege changes, merge, push, tagging or publication.
