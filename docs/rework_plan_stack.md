# Continuum Rework Plan Stack (Canonical)

## Planning authority

This is the authority map, not a second policy ledger.

1. `docs/rework_milestone_release_plan.md` owns the fourteen approved pre-main policies, reproduction boundary, ordered gates and publication prohibition.
2. `docs/configuration_restructuring_design.md` owns YAML composition, parser/bootstrap validation, normalized configuration and resume semantics.
3. `docs/software_module_architecture_plan.md` owns software module graph, selector/scope, tag governance, registry and planner semantics.
4. `docs/release_certification_matrix.md` is the factual row-status and evidence authority; policy changes do not renew historical runs.
5. `docs/rework_release_handoff.md` is the concise operational checkpoint, subordinate to the above. `docs/rework_kickoff.md` is navigation only.

`docs/ansible_restructuring_design.md` and `docs/phase_c_implementation_plan.md` are historical phase records, not an active architecture queue. `docs/post_release_roadmap.md` is retired. The old overhaul dispatcher remains retired. Domain semantics must not contradict approved scope; resolve a domain conflict in its domain document and synchronize dependent operational docs atomically.

`docs/reproduction_inventory.md` is subordinate factual candidate-scope evidence, not another policy authority or certification ledger. Its final user scope confirmation and the separate configuration/fixture inventory remain open gates.

## Locked boundaries

- Core/module boundary: Continuum core owns planning, validation, selector/scope resolution, module contracts, runtime handoff, state and evidence contracts. Provider/software/application stacks are modules. `qemu` is a provider module and must not be described as core.
- Runtime claims require VM-backed or cloud-backed evidence, or host-backed evidence where the applicable matrix gate permits it. Static success alone is insufficient.
- Intermediate rework milestones may certify bounded subsets; they are not final main replacement releases.
- Final main replacement requires approved reproduction scope and zero unaccounted rows in the reproduction/config inventories, followed by final explicit user approval. The complete old-main parity inventory remains historical candidate coverage, not the replacement release scope.
- Existing hard-cut schema, cluster-first `infrastructure.clusters[]`, `software.modules[]`, exact-match AND selector clauses with software-only `any_of` unions and single-`match` benchmark selectors (module authority §6), structured scope identities, explicit-only dependencies, deterministic planning and reserved-tag collision errors remain. Benchmark tags cannot overwrite `role`; use namespaced keys such as `benchmark.role`.
- Parser/bootstrap validates and defaults once. Runtime uses canonical keys without compatibility fallbacks. Keep the parser orchestration facade, domain validators and layered semantic config-access helpers; no speculative configuration-library migration.
- The approved registry terminology hard cut is run.registry_refresh missing/all, default missing, without aliases; use the current domain schema. Frozen historical ledger entries below retain their original image_prefetch spelling.
- No new core features, speculative architecture or automatic recovery. Normal-user migration and the QEMU repair follow the ordered approved gates.
- No merge, push, tag, release or publication before final explicit approval.

## Synchronization

Before each nontrivial packet, freeze exact files and acceptance criteria, obtain independent read-only plan review, implement/test, and independently review the complete uncommitted diff. Resolve actionable findings before a local commit. Preserve unrelated edits and private/generated evidence. Keep policy detail once in the milestone authority and semantics once in the domain authorities. Historical phase completion is not candidate certification.

## Future work requiring renewed user discussion

- **Support large QEMU course demos.** Each student gets a private Kubernetes cluster running on one or more QEMU VMs, provisioned by the operator before the demo. The instructor must be able to prepare a base image once, publish it to a shared NFS location that the provisioning hosts access read-only, and copy it into the Continuum image directory for each student allocation. Continuum must reuse the copied base without rebuilding it and preserve the existing behavior of creating a separate writable QCOW2 overlay for each VM.

  Students use their own SSH keys to log in to their assigned physical hosts without sudo. From there, they use the separate Continuum guest SSH key already set up for their allocation to log in to their VMs.

  In the next planning discussion, use the [anac_setup_scripts](https://github.com/atlarge-research/anac_setup_scripts) checkout on the AL02 head node as the starting point for the test. Coordinate account and image preparation on AL02 with the matching Continuum configuration and provisioning run on node4 or whichever host holds the rework checkout. Validate with a fresh student allocation by confirming base-image reuse, independent writable overlays, Ready Kubernetes nodes, and both student SSH access paths.

- **Move guest images to Ubuntu 24.04 and restore QEMU image downloads.** Keep `ansible.builtin.get_url` for the QEMU OS image download. The current pin, `ansible-core==2.13.2`, fails when that module runs under Python 3.12 on a physical Ubuntu 24.04 worker. Upgrade the `ansible-core` pin to a maintained release that includes the HTTPS fix and supports Python 3.12 on managed hosts. Validate the upgraded Ansible runtime on the machine that launches Continuum, with Ubuntu 22.04 and 24.04 both supported as physical hosts. Plan the move from Ubuntu 20.04 to 24.04 for Continuum's guest and base images. Cover image selection and provisioning for the affected providers, workload compatibility, and how to handle previously prepared course images. [Upstream Ansible HTTPS fix](https://github.com/ansible/ansible/pull/80751)

  When scheduled, verify an actual `get_url` download with an empty image cache on an Ubuntu 24.04 physical worker and TLS certificate verification enabled. Then test mixed Ubuntu 22.04 and 24.04 physical hosts twice, with each OS taking a turn launching Continuum, and verify guest provisioning through Kubernetes readiness. Defer implementation and the choice of Ansible version to the broader rework planning discussion.

- [Small reproducibility and failure-diagnosis proposal](superpowers/plans/2026-10-30-reproducibility-failure-diagnosis.md): deferred navigation only, outside the current checkpoint. Before scheduling or executing even its initial coverage audit, discuss again with the user whether it is wanted or mostly overengineering, and obtain a renewed decision. If later approved, first check existing coverage for at most two hours; keep the total effort to one to two engineer-days including tests/docs, make at most two small fixes, and stop early with zero fixes if existing coverage is sufficient. This entry grants no audit or implementation authority and changes no current gates.

- **Read-only experiment preview.** Consider a `plan` command that reuses configuration resolution and validation to show selected phases, requested VM counts and sizes, software assignments and benchmark stages. It would report which decisions depend on live host state and leave the deployment untouched. Decide later how much of the resolved plan to expose and whether live read-only checks belong in a separate mode.

- **Run-scoped resource cleanup.** Consider a separate cleanup command for failed runs and retained deployments. The environment profile's `delete_on_exit` setting already requests VM teardown at the end of a run. A cleanup command could use a run ID or state file to preview and remove resources verified to belong to that run, preserving shared images and caches, logs and results. Decide later how to record ownership across hosts and handle failures before state is saved. Cleanup should refuse to delete resources whose ownership it cannot verify.

Both proposals need a separate decision on scope, interface and priority before implementation.

- **Agent-assisted troubleshooting.** Explore a short skill that asks what happened and which run and phase were affected, gathers the available evidence, and routes the user to focused Markdown runbooks. Each runbook would say what command to run, where to run it, how to interpret the output, and what to check next. Start with read-only diagnosis. The assistant could inspect evidence when it has access or give the same commands to the user. QEMU teardown is one possible pilot. Revisit the idea and the role of [the existing troubleshooting guide](ISSUES.md) after this branch is merged and the broader review is complete. Scope and timing remain open.

## 11. Historical Implementation Snapshot (Frozen May 22, 2026)

The complete frozen implementation ledger is preserved verbatim in Git object `b484f120f81c437f29d61b19ff5fec4e3790c58e:docs/rework_plan_stack.md`. Inspect it with `git show b484f120f81c437f29d61b19ff5fec4e3790c58e:docs/rework_plan_stack.md`. Verified private copies and SHA-256 bindings are in `docs/rework_release_handoff.md`.

This is historical provenance, not a current work queue or renewed certification. The authority map, current boundaries and closure commitments in this document remain active; use the current handoff for execution status.

## 12. End-of-Rework Test Closure Commitments

Closed May 21, 2026:

1. Major-function coverage is audited and tracked by `scripts/test/coverage_manifest.json`, with the maintenance contract documented in `docs/major_function_test_coverage.md`.
2. `scripts/test/unit/test_coverage_manifest.py` keeps the audit live by validating audited source paths, major function names, referenced tests, and success/fail-fast coverage notes.
3. Test suites are split into dedicated unit and local e2e-regression directories:
   - `scripts/test/unit/`
   - `scripts/test/e2e/`
   - shared helpers under `scripts/test/support/`
4. `scripts/test/run_cloud_static_audit.sh` now runs unit and e2e discovery as separate required gates before the combined suite.

## 13. End-of-Rework Documentation Closure Commitments

Closed for the active rework baseline:

1. Consolidated user-facing configuration docs for canonical YAML schema (`run`, `infrastructure`, `provider`, `software.modules`, `benchmark.pipeline`) are published in `docs/configuration_reference.md`.
2. Migration notes from removed legacy paths (`workload`, legacy benchmark keys, legacy config-access helpers) are published in `docs/migration_notes.md`.
3. Developer-facing architecture docs for parser/runtime decomposition boundaries, module contracts, runtime phases, and operational testing are published across the design docs.
4. Runnable examples/templates are synchronized with parser validation and covered by repository regression tests.
5. The final doc-audit gate is represented by `scripts/test/check_docs_paths.py` and `scripts/test/run_cloud_static_audit.sh`; generated reports stay under ignored `logs/cloud_static_audit/`.
6. The earlier speculative observability/package/database follow-up is retired; it is not authorized by historical documentation closure.

## 14. Deferred Outside Active Closure

The May 21, 2026 closure sweep classifies the remaining inline code-debt notes as outside the active PR-23 documentation/runtime rework:

1. QEMU-specific base-IP ownership in `infrastructure/qemu/qemu.py` should be handled as a provider-interface cleanup, not folded into the smoke/docs closure.
2. Endpoint runtime environment configurability in `resource_manager/endpoint/endpoint.py` should be handled with an explicit benchmark/runtime option design before changing user-facing behavior.
3. Splitting KubeEdge and Mist in `resource_manager/kubeedge/kubeedge.py` remains a provider/module boundary refactor and requires a separate compatibility plan.

The active rework closure therefore treats these as tracked follow-up debt, not unimplemented docs-requested overhaul items.
