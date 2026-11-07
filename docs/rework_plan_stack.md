# Continuum Rework Documentation Map

## Planning authority

Use the [Continuum rework plan](rework_kickoff.md) for the work before and after merge. This map identifies where to find supporting rules, contracts and evidence.

1. `docs/rework_milestone_release_plan.md` owns safety, evidence and approval rules.
2. `docs/configuration_restructuring_design.md` owns YAML composition, parser/bootstrap validation, normalized configuration and resume semantics.
3. `docs/software_module_architecture_plan.md` owns software module graph, selector/scope, tag governance, registry and planner semantics.
4. `docs/release_certification_matrix.md` is the factual row-status and evidence authority; policy changes do not renew historical runs.
5. `docs/rework_release_handoff.md` preserves dated operational checkpoints. `docs/rework_kickoff.md` owns the agreed scope, packet dependencies and deferred work.

`docs/ansible_restructuring_design.md` and `docs/phase_c_implementation_plan.md` are historical phase records, not an active architecture queue. `docs/post_release_roadmap.md` is retired. The old overhaul dispatcher remains retired. Domain semantics must not contradict approved scope; resolve a domain conflict in its domain document and synchronize dependent operational docs atomically.

`docs/reproduction_inventory.md` records the agreed case settings and historical candidate evidence. The file-level configuration and fixture dispositions and exact removal approval remain open.

## Locked boundaries

- Core/module boundary: Continuum core owns planning, validation, selector/scope resolution, module contracts, runtime handoff, state and evidence contracts. Infrastructure, software and benchmark procedures are modules. Workload assets and study orchestration have separate homes. `qemu` is a provider module and must not be described as core.
- Runtime claims require VM-backed or cloud-backed evidence, or host-backed evidence where the applicable matrix gate permits it. Static success alone is insufficient.
- Intermediate rework milestones may certify bounded subsets; they are not final main replacement releases.
- Final main replacement requires approved reproduction scope and zero unaccounted rows in the reproduction/config inventories, followed by final explicit user approval. The complete old-main parity inventory remains historical candidate coverage, not the replacement release scope.
- Existing hard-cut schema, cluster-first `infrastructure.clusters[]`, `software.modules[]`, exact-match AND selector clauses with software-only `any_of` unions and single-`match` benchmark selectors (module authority §6), structured scope identities, explicit-only dependencies, deterministic planning and reserved-tag collision errors remain. Benchmark tags cannot overwrite `role`; use namespaced keys such as `benchmark.role`.
- Resolve, default and validate once. Use the typed resolved config and module-owned options in the target runtime. Keep one supported representation and require strong evidence before adding a configuration dependency. [Configuration cutover](configuration_restructuring_design.md#71-br23-configuration-and-module-cutover)
- The approved registry terminology hard cut is run.registry_refresh missing/all, default missing, without aliases; use the current domain schema. Frozen historical ledger entries below retain their original image_prefetch spelling.
- Limit changes to the agreed core cutover and selected module, project and development work. Apply the normal-user runtime rules.
- Obtain explicit approval for publication and merge. Separately authorized image uploads can precede final acceptance.

## Synchronization

Before each nontrivial packet, freeze exact files and acceptance criteria, obtain independent read-only plan review, implement/test, and independently review the complete uncommitted diff. Resolve actionable findings before a local commit. Preserve unrelated edits and private/generated evidence. Keep policy detail once in the milestone authority and semantics once in the domain authorities. Historical phase completion is not candidate certification.

## Platform and teaching qualifications

These details support the HOST, COURSE and MPI packets in the agreed plan. [Implementation packets](rework_kickoff.md#implementation-packets)

- **Support large QEMU course demos.** Each student with a classroom allocation gets a private Kubernetes cluster running on one or more QEMU VMs. The operator coordinates provisioning under a distinct Unix account per allocation on every shared controller or worker host. Students who pair during a tutorial can work together at one allocation. For group projects, give the group one shared account and have its members coordinate their use under the existing one-invocation-per-account rule. [QEMU ownership and resume policy](rework_milestone_release_plan.md#2-approved-consolidated-policies)

  Prepare one verified instructor base in shared NFS storage that the provisioning hosts access read-only. Define an import that stages the required OS image and base backing files in each owner-local cache and verifies the destination recipe, including guest login, before publishing its ready metadata. Check that the seed is free of instructor credentials, then create independent writable QCOW2 overlays and fresh cloud-init and guest keys. Students use their own SSH keys to log in to the physical host without sudo, then use their allocation's guest key to reach its VMs. [QEMU cache contract](qemu_cache_contract.md)

  Start from the ANAC account and demo setup scripts checkout on the AL02 head node. Confirm its path, revision, approved accounts and NFS image location during implementation preflight. Validate two allocations under different Unix accounts on the same physical host with distinct domain names, base paths and address ranges. Record cache hits on each owning host, overlay paths, Ready nodes and both SSH hops. Check the first allocation's guest UUIDs, disk bindings, readiness and access before and after provisioning the second.

  Ship the current MPI classroom demo as a project on top of the prepared two-VM Kubernetes allocation. Port the pinned lesson, application image build and MPIJob manifests. Qualify a pinned MPI Operator with the course Kubernetes profile and prepare it through the operator workflow. Run the lesson as a student, check actual worker placement for the single-VM and distributed jobs, and compare their correct result and elapsed time. Repeat the distributed run with the lesson's one-way delay and jitter through an allocation-scoped network rule. Remove the rule and the lesson's jobs afterward and verify that the other allocation remains reachable. [MPI lesson and source](https://github.com/atlarge-research/continuum/tree/db466d9ee50b771d411d18de17e3dcb720540ffa)

- **Qualify mixed Ubuntu physical hosts.** Use an isolated Python 3.12 launcher environment on both Ubuntu 22.04 and 24.04. Install Python 3.12 alongside the system Python where needed, and create the launcher environment with that interpreter. Qualify a clean install of the launcher and test dependencies, including a maintained Ansible release with the HTTPS fix and compatible collection pins. Record the actual Continuum and `ansible-playbook` executables and versions, along with the managed interpreter on each physical and guest target. The current Ubuntu 20.04 guest inventory selects the distro's Python 3.8. Qualify a supported managed interpreter on that guest image and verify guest package tasks before passing the mixed-host gate. [Side-by-side Python setup](https://documentation.ubuntu.com/ubuntu-for-developers/tutorials/python-use/#installing-a-specific-python-version) · [Host setup script](../scripts/test/setup_agent_host.sh) · [Ansible support matrix](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix) · [Upstream HTTPS fix](https://github.com/ansible/ansible/pull/80751)

  Verify an actual `ansible.builtin.get_url` download with an empty image cache on an Ubuntu 24.04 physical worker and TLS certificate verification enabled. Test both mixed-host launch directions through guest provisioning and Kubernetes readiness.

- **Qualify the existing Ubuntu 20.04 QEMU guest and base images for BR23.** Keep them for merge if the managed interpreter, package tasks, required workloads and prepared course images pass qualification. Bring any blocking failure back for a release decision with the relevant evidence. The Ubuntu 24.04 guest migration is separate post-merge work. Qualify a pinned 24.04 cloud image, cloud-init and networking, guest package roles and retained workloads. Bind cache validation to the new OS image identity and rebuild and verify the prepared course seed. [Ubuntu 24.04 release notes](https://documentation.ubuntu.com/release-notes/24.04/) · [QEMU cache contract](qemu_cache_contract.md)

## Optional post-merge ideas

These notes provide background for the optional work listed in the current plan. [After merge](rework_kickoff.md#after-merge-or-preserved-for-later-selection)

- **Further reproducibility and failure diagnosis.** The first bounded packet and November reliability follow-up are complete. Any additional work needs a concrete recurrent failure, a scoped proposal and renewed approval. Reuse the existing logs, metadata and narrow result inspection. [Completed first packet](superpowers/plans/2026-10-30-reproducibility-failure-diagnosis.md#completed-first-packet--november-3-2026) · [Reliability follow-up](rework_release_handoff.md#expanded-reliability-follow-up--november-34-2026)

- **Read-only experiment preview.** Consider a `plan` command that reuses configuration resolution and validation to show selected phases, requested VM counts and sizes, software assignments and benchmark stages. It would report which decisions depend on live host state and leave the deployment untouched. Decide later how much of the resolved plan to expose and whether live read-only checks belong in a separate mode.

- **Run-scoped resource cleanup.** Consider a separate cleanup command for failed runs and retained deployments. The environment profile's `delete_on_exit` setting already requests VM teardown at the end of a run. A cleanup command could use a run ID or state file to preview and remove resources verified to belong to that run, preserving shared images and caches, logs and results. Decide later how to record ownership across hosts and handle failures before state is saved. Cleanup should refuse to delete resources whose ownership it cannot verify.

Both proposals need a separate decision on scope, interface and priority before implementation.

- **Agent-assisted troubleshooting.** Explore a short skill that asks what happened and which run and phase were affected, gathers the available evidence, and routes the user to focused Markdown runbooks. Each runbook would say what command to run, where to run it, how to interpret the output, and what to check next. Start with read-only diagnosis. The assistant could inspect evidence when it has access or give the same commands to the user. QEMU teardown is one possible pilot. Revisit the idea and the role of [the existing troubleshooting guide](ISSUES.md) after this branch is merged and the broader review is complete. Scope and timing remain open.

- **Review local and remote command execution.** Revisit `Machine.process()` during the broader review after integration into `pr-23-curated`. The earlier handoff in `3a2353f8:docs/phase_d_handoff.md` identified recurring quoting problems when composing local shell, SSH arguments and remote shell commands. Compare a narrower OpenSSH and subprocess wrapper, a dedicated SSH library, and existing Ansible tasks where they fit. Preserve verified physical-worker access, guest bootstrap and command deadlines. Require the design to avoid replaying remote mutations whose outcome is uncertain. Tool choice, scope and timing remain open.

## BR23 branch dispositions

The 2026-11-07 GitHub branch query returned 16 names. The checkout has matching tracking refs plus one stale `origin/mahimahi` ref and six local branches. The revisions below are the observed local tips. Verify live remote tips, open work and archive reachability before taking action. Keep branches cited by publications and teaching material available at their existing addresses where practical. Use a reachable named archive for work that would otherwise be lost. Deletion is a separate maintainer decision after the source and evidence are secured.

| Branch | Observed revision and purpose | Proposed disposition |
| --- | --- | --- |
| `main` | `59c3ce0ef74777aa33941475ced4bf5f283642f3`, local and tracking tips. Current release base. | Keep as the integration destination. |
| `pr-23-curated` | `6879a42630a9f1d4ea6904c3236d93b5febb3e9f`, local and tracking tips. Rework and current review. | Merge the eventual accepted BR23 candidate. Keep the original revision reachable for archive citations. |
| `ARM` | `4085df8d7d85b08161ff6c80034ed624c8a231a7`. Raspberry Pi/ARM adaptation. | Archive as the source for a later ARM port. |
| `CCGRID2023-Artifact-Evaluation` | `269e64834c93883127afc071a21220066ed4c445`. Published smaller GCP artifact. | Keep the public artifact branch. BR23 ports the original QEMU experiments separately. |
| `columbo` | `a3fdf9ab7565fa2ae2be9da9bd863d27021e208b`. Columbo instrumented experiments. | Preserve the public research source. Port the exact `call_1` project case in BR23. Revisit wider sweeps through that project. |
| `codex/fns-2026-10-08` | `0a72e112f5b2021a24244c03f1b7aed5f744f49a`, local and tracking tips. Live closed-loop image-batch demo and later replay work. | Preserve the branch. Port the isolated guest replay fixes for BR23. Port the live digital twin as a separate project after merge. |
| `kube-opencraft` | `11198785b97fbdbea9f5bf27d3f62507423a97a8`. OpenCraft workload and install hooks. | Preserve for the post-merge OpenCraft discussion. |
| `kubeserverless` | `92d71cea5651eb28216be9fef5bdd5efd2d7c3f6`. Kubernetes Job trace replay. | Archive as a research lead. Keep it unscheduled. |
| `ml-scheduler` | `f160de1a3ebfdf3459efc3208607585e2a47cdd9`. Kubernetes and storage setup for scheduler work. | Archive as setup provenance. Tim van Kemenade's later EScheduler artifact is the separate post-merge project source. |
| `openwhisk` | `1b3a7317fd03199b94dcedf6175c417d1261ceb8`. Earlier configuration rewrite under this branch name. | Archive for provenance. Consider retiring the branch name after maintainer review. The source survey found no OpenWhisk implementation to port. |
| `tutorial-2024` | `34c1bdf72932c523e8cebfa4ced70ed261627719`. Kubernetes, Grafana and cloud offloading lesson. | Keep as teaching provenance. Reuse instructions that fit the new image-offloading lesson. |
| `tutorial-asci-a24-2022` | `5e0105a422c639fc2a6a6c5f8a176136378dc1e6`. Local, cloud and edge image-classification lesson. | Keep the original demo branch. Port those three modes and the comparison to the new core after merge. |
| `tutorial-cn-2023` | `8d70ae3625b500f3310c75b51b966632e270fca9`. Cloud image-classification and network observation lesson. | Keep as teaching provenance. Reuse relevant network exercises in the new demo. |
| `tutorial-ds-2022` | `be421ced6daf757d0faa0c102264c2e5c9591710`. Kubernetes/OpenFaaS teaching lesson. | Keep as teaching provenance. Schedule any updated lesson separately. |
| `tutorial-mpi` | Tracking tip `db466d9ee50b771d411d18de17e3dcb720540ffa`. Local tip `e5ea3758902172163377ede89143a6610190d9bd` is behind. | Keep the lesson branch and port the newer pinned MPI assets into the pre-merge classroom project. |
| `wasm` | `2e1d6ed1022b660beb5b859fb8d21e327d8e97c7`. Published WebAssembly prototype and inputs. | Keep as a research artifact. Port the full published matrix through the new benchmark contract before merge. |
| `mahimahi` | `7f1ec96334b04d522c28ea7eacf042002f5a510b`, local and stale tracking tips. Early cellular replay source. | Preserve a reachable source before pruning stale refs. Keep the guest replay capability in BR23. |
| Local `codex/overnight-qemu-20261106` | `6879a42630a9f1d4ea6904c3236d93b5febb3e9f`, same current tip as BR23. | Candidate for local cleanup after confirming the separate run receipts and historical source remain reachable. |

## 11. Historical Implementation Snapshot (Frozen May 22, 2026)

The complete frozen implementation ledger is preserved verbatim in Git object `b484f120f81c437f29d61b19ff5fec4e3790c58e:docs/rework_plan_stack.md`. Inspect it with `git show b484f120f81c437f29d61b19ff5fec4e3790c58e:docs/rework_plan_stack.md`. Verified private copies and SHA-256 bindings are in `docs/rework_release_handoff.md`.

Sections 11–14 record the May baseline and its decisions. Use the current plan for work and the certification matrix for factual status. [Current plan](rework_kickoff.md)

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

Closed for the May 2026 baseline:

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

The current plan settles the Mist scope and lists any follow-up work still eligible for later selection. [Current scope](rework_kickoff.md#agreed-merge-scope)
