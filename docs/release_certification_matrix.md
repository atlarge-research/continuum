# Continuum Release Certification Matrix

## 1. Purpose

This is the working matrix for turning the milestone release plan into
checkable rows. Runtime rows can be claimed in release notes only when their
status is `certified` and their evidence fields point to a fresh run for the
release being prepared. A non-runtime core row may be claimed as `core-ready`
under the policy in `docs/rework_milestone_release_plan.md`.

Certification policy and labels are defined in
`docs/rework_milestone_release_plan.md`.

## 2. How To Use This Matrix

1. Keep `docs/rework_milestone_release_plan.md` as the release strategy.
2. Keep this document as the operational checklist for release rows.
3. Update a row to `certified` only after the exact config/module set has passed
   a full VM-backed, cloud-backed, or host-backed run appropriate to the claim.
4. Leave code-present but unproven rows as `ported-unverified`.
5. Leave legacy-only rows as `historical` while they are unresolved. This is a
   non-terminal status, so every historical `P-*` row remains in
   `docs/old_main_parity_issue_seed.md`.
6. If a feature may not return, mark it `deprecated-proposed` and add rationale,
   but keep the row in the parity seed because that status is also non-terminal.

Under the current checked contract, a tracked parity row can leave the backlog
only by becoming `certified`. Closing an unsupported historical provider without
certification would require a separate atomic change that introduces an explicit
checked terminal disposition and updates the matrix checker, this document, and
the parity seed together. This documentation reset does not define that future
disposition.

Generated logs under `logs/` are local evidence and are not committed by
default. Release notes should summarize the latest committed source revision,
command, operator/runner context, and artifact location for each certified row.
The current M1 release-notes draft is `docs/release_notes_m1_draft.md`.
`scripts/test/check_release_matrix.py` verifies that matrix config paths and
suite references resolve to current repository inventories, that every
runtime-certified row names a concrete rework experiment config and runner
suite, that the local `origin/main` ref is available, that every legacy test
config under both the current worktree and the local `origin/main`
`configuration/tests/` inventory has a matrix disposition, that the M1 draft
lists every M1/old-main ready row and every M1/old-main ready-row primary
evidence document, and that M1/old-main non-ready rows stay in the nonclaim
section. It also verifies that release notes list only M1/old-main ready-row
primary evidence documents, that certified row references in the module backlog
point only at ready matrix rows, and that
`docs/old_main_parity_issue_seed.md` mirrors every non-ready `P-*` row with a
matching status and a concrete issue seed.

## 3. M1 Certified Module-Set Rows

M1 is the first intermediate rework milestone. It should prove the structured
core plus one local, VM-backed vertical slice. It is not a final replacement for
old `main`.

| ID | Claim Boundary | Configs / Suites | Required Evidence | Current Status | Next Action |
| --- | --- | --- | --- | --- | --- |
| M1-CORE | Core parser, planner, selector, registry, runtime handoff, lock/state, and runner metadata are cloud-safe. | `scripts/test/run_cloud_static_audit.sh` | Required gates pass: compile sweep, cloud audit shell syntax check, smoke wrapper shell syntax check, host setup shell syntax check, git diff whitespace check, unit unittest discovery, e2e unittest discovery, combined unittest discovery, docs path reference check, public release-claims check, release certification matrix check, configured suite catalog. | `core-ready` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if source changes before publication. |
| M1-QEMU-INFRA | `qemu` provider module can provision a minimal cloud-tier VM and persist infrastructure state. | `configs/experiments/smoke/infra_one_vm.yaml`; suite `smoke`; wrapper scenario `infra_one_vm` | VM is provisioned and reachable; lock/state exist; state reaches infrastructure; teardown/retention behavior matches config. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if runtime code changes before publication. |
| M1-QEMU-K8S | `qemu + kubernetes` module set can deploy a minimal Kubernetes software phase. | `configs/experiments/smoke/software_k8s_two_vm.yaml`; suite `smoke`; wrapper scenario `software_k8s_two_vm` | Infrastructure and software phases pass; the Continuum runtime reaches the Kubernetes software phase successfully; lock/state remain consistent. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if runtime code changes before publication. |
| M1-QEMU-NET-SMOKE | `qemu` network-emulation path can produce netperf evidence on a minimal cloud/endpoint topology. | `configs/experiments/smoke/network_netperf_two_vm.yaml`; suite `smoke`; wrapper scenario `network_netperf_two_vm` | Netperf artifact exists under the run base path; network profile tolerances pass; lock/state evidence exists. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if network runtime or verifier code changes before publication. |
| M1-QEMU-NET-SUITE | Dedicated network-validation suite can validate the 4g profile on the release candidate. | `configs/experiments/network_validation/bench_net_4g.yaml`; suite `network_validation` | Structured netperf NDJSON is validated against latency/throughput tolerances. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if network runtime or verifier code changes before publication. |
| M1-QEMU-BENCH | `qemu + kubernetes + endpoint_runtime + image_classification` can resume across infrastructure, software, and application phases and then tear down. | `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`; suite `benchmark_smoke`; wrapper scenario `benchmark_k8s_resume` | Shared resume contract stays stable; application emits stdout markers and metric artifacts; teardown evidence proves saved QEMU domains are absent when deletion is requested. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-07-08.md`; rerun if runtime code changes before publication. |

Preferred M1 host command sequence:

1. `scripts/test/run_cloud_static_audit.sh`
2. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
3. `sudo -n /usr/local/bin/continuum-hostctl verify`
4. `sh scripts/test/setup_agent_host.sh verify`
5. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression`
6. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation`
7. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity` when certifying old-main QEMU infrastructure parity rows.
8. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_image_parity` when certifying the Kubernetes image-classification parity row.
9. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity` when certifying the Kubernetes no-benchmark parity row.
10. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity` when certifying the KubeEdge software-only subset row.
11. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity` when certifying the full KubeEdge image-classification parity row.
12. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity` when certifying the Mist software-only subset row.
13. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_image_parity` when certifying the full Mist image-classification parity row.
14. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity` when certifying the endpoint-runtime software-only subset row.
15. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_image_parity` when certifying the full endpoint image/runtime parity row.
16. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity` when certifying the OpenFaaS software-only subset row.
17. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_local_parity` when certifying the OpenFaaS single-host application subset row.
18. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_image_parity` when certifying the exact OpenFaaS application parent row.
19. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_parity` when certifying the Columbo-style kubecontrol module/profile/suite integration row.
20. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubecontrol_empty_trace_parity` when certifying the strict Columbo-style kubecontrol control-plane trace row.
21. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kube_kata_empty_startup_parity` when certifying the local-QEMU Kata startup row.

The current wrapper supports `operational_regression`, which chains
`phase_smoke_matrix` and `benchmark_k8s_resume`. The dedicated
`network_validation` suite is claimed for the current M1 evidence snapshot. The
`qemu_infra_parity` suite remains separate because it certifies old-main
infrastructure parity rows rather than the first vertical M1 module set. The
pre-tag gate in `docs/release_notes_m1_draft.md` intentionally lists every
VM-backed wrapper scenario for rows claimed by the milestone.

Before publishing a release candidate from the certification host, also run:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit
python3 scripts/test/check_release_pretag.py
python3 scripts/test/check_release_claims.py
```

The artifact audit validates that the primary artifact paths named by release
evidence docs still exist, that runner summary JSON reports zero failures, that
the cloud-static audit required gates passed, and that structured
benchmark/network artifacts are parseable. The pre-tag readiness check
aggregates the documented M1 evidence, verifies that every release-evidence doc
listed in the release notes names the current git commit and clean source-tree
state, and should fail until the working tree is clean and host-helper interface
verification records `PASS`. The release-claims check validates that
public-facing docs still point support claims to this matrix. They do not claim QEMU
as Continuum core, full main replacement, uncertified cloud support, or full
application parity rows without evidence.

## 3.5 Post-M1 Research Case-Study Rows

These post-M1 rows demonstrate Continuum as a research and education platform.
Their existing `M2-*` row IDs are retained for evidence compatibility, but the
prefix does not denote the M2 Provider Parity milestone defined in
`docs/rework_milestone_release_plan.md`. They do not participate in the M1
release-notes draft until they have their own publication path, and they must
not be described as release-certified until retained runtime evidence exists.

| ID | Claim Boundary | Configs / Suites | Required Evidence | Current Status | Next Action |
| --- | --- | --- | --- | --- | --- |
| M2-QEMU-KUBECONTROL-EMPTY | Columbo-style local QEMU `kubecontrol` benchmark using the `empty` application and the per-call deployment mode from `configuration/experiment_control/microbenchmark/qemu/deployment/call_1.cfg`. | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml`; suite `qemu_kubecontrol_empty_parity`; wrapper scenario `qemu_kubecontrol_empty_parity` | Retained VM-backed evidence shows `phase_completed = application`, experiment lock/state, kubecontrol cluster readiness, deployment CSV artifacts, benchmark metric manifest for `CLOUD OUTPUT`, and documented Columbo module boundaries in `docs/columbo_on_continuum.md`. The retained image exposes kubelet/app/resource traces but not legacy `apiserver`, `controller-manager`, or `scheduler` trace points. | `certified` | Evidence: `docs/release_evidence_qemu_kubecontrol_empty_2026-07-03.md`. |
| M2-QEMU-KUBECONTROL-TRACE | Full Columbo-style local QEMU `kubecontrol` trace reproduction for the same `empty` application experiment. | `configs/experiments/parity/qemu_kubecontrol_empty/01_kubecontrol_empty_call.yaml`; suite `qemu_kubecontrol_empty_trace_parity`; wrapper scenario `qemu_kubecontrol_empty_trace_parity` | Retained VM-backed evidence shows populated `controller_read_workload (s)`, `controller_unpacked_workload (s)`, `scheduler_read_pod (s)`, `kubelet_pod_received (s)`, `kubelet_applied_sandbox (s)`, and `started_application (s)` columns in both `CLOUD OUTPUT` and benchmark metric artifacts. | `certified` | Evidence: `docs/release_evidence_qemu_kubecontrol_trace_2026-07-06.md`. |
| M2-QEMU-KUBE-KATA-EMPTY | Local QEMU `kube_kata` startup benchmark using `empty_kata`, `kata-qemu`, and `overlayfs`, mapped from `configuration/experiment_kata/1_startup_performance/strong_scalability/node_1_kata_qemu_overlayfs.cfg`. | `configs/experiments/parity/qemu_kube_kata_empty_startup/01_kube_kata_empty_pod.yaml`; suite `qemu_kube_kata_empty_startup_parity`; wrapper scenario `qemu_kube_kata_empty_startup_parity` | Retained VM-backed evidence shows cluster readiness, RuntimeClass installation, guest Kata/containerd setup, Jaeger query readiness, `empty_kata` success, runtime CSVs including `*_dataframe_kata.csv`, benchmark metric manifests for `CLOUD OUTPUT` and `KATA OUTPUT` with at least 100 rows, and cleanup. | `certified` | Evidence: `docs/release_evidence_qemu_kube_kata_empty_2026-07-09.md`. |

## 4. Old-Main Provider And Topology Parity

This table starts from the legacy test inventory under `configuration/tests/`.
Rows are not release-ready until the YAML equivalent is explicit and a fresh
VM-backed or cloud-backed run proves the claim on the rework stack.

| ID | Legacy Row | Old Public Surface | Related Rework YAML / Profile | Status | Certification Action |
| --- | --- | --- | --- | --- | --- |
| P-QEMU-01 | `configuration/tests/qemu/01_infraonly-cloud.cfg` | QEMU cloud-only infrastructure | `configs/experiments/parity/qemu/01_infraonly_cloud.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-07-08.md`. |
| P-QEMU-02 | `configuration/tests/qemu/02_infraonly-edge.cfg` | QEMU edge-only infrastructure | `configs/experiments/parity/qemu/02_infraonly_edge.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-07-08.md`. |
| P-QEMU-03 | `configuration/tests/qemu/03_infraonly-endpoint.cfg` | QEMU endpoint-only infrastructure | `configs/experiments/parity/qemu/03_infraonly_endpoint.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-07-08.md`. |
| P-QEMU-04 | `configuration/tests/qemu/04_infraonly-all.cfg` | QEMU cloud/edge/endpoint infrastructure | `configs/experiments/parity/qemu/04_infraonly_all.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-07-08.md`. |
| P-QEMU-05 | `configuration/tests/qemu/05_kuberentes-img.cfg` | QEMU Kubernetes plus image-classification application with netperf enabled | `configs/experiments/parity/qemu_k8s_image/05_kubernetes_image_classification.yaml`; suite `qemu_k8s_image_parity` | `certified` | Evidence: `docs/release_evidence_qemu_k8s_image_2026-07-08.md`. |
| P-QEMU-06-SW | Subset of `configuration/tests/qemu/06_kubeedge-img.cfg` | QEMU KubeEdge software phase on the legacy cloud/edge/endpoint topology, without image-classification application | `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml`; suite `qemu_kubeedge_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_kubeedge_software_2026-07-08.md`. This does not certify the full P-QEMU-06 application row. |
| P-QEMU-06 | `configuration/tests/qemu/06_kubeedge-img.cfg` | QEMU KubeEdge image-classification application path | `configs/experiments/parity/qemu_kubeedge_image/06_kubeedge_image_classification.yaml`; suite `qemu_kubeedge_image_parity` | `certified` | Evidence: `docs/release_evidence_qemu_kubeedge_image_2026-07-08.md`. |
| P-QEMU-07-SW | Subset of `configuration/tests/qemu/07_mist-img.cfg` | QEMU Mist software phase on the legacy edge/endpoint topology, without image-classification application | `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml`; suite `qemu_mist_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_mist_software_2026-07-08.md`. This does not certify the full P-QEMU-07 application row. |
| P-QEMU-07 | `configuration/tests/qemu/07_mist-img.cfg` | QEMU Mist image-classification application path | `configs/experiments/parity/qemu_mist_image/07_mist_image_classification.yaml`; suite `qemu_mist_image_parity` | `certified` | Evidence: `docs/release_evidence_qemu_mist_image_2026-07-08.md`. |
| P-QEMU-08-SW | Subset of `configuration/tests/qemu/08_endpoint_img.cfg` | QEMU endpoint runtime software phase on the legacy endpoint-only topology, without image-classification application | `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml`; suite `qemu_endpoint_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_endpoint_software_2026-07-08.md`. This does not certify the full P-QEMU-08 application row. |
| P-QEMU-08 | `configuration/tests/qemu/08_endpoint_img.cfg` | QEMU endpoint image/runtime path | `configs/experiments/parity/qemu_endpoint_image/08_endpoint_image_classification.yaml`; suite `qemu_endpoint_image_parity` | `certified` | Evidence: `docs/release_evidence_qemu_endpoint_image_2026-07-08.md`. |
| P-QEMU-09 | `configuration/tests/qemu/09_kubernetes-nobench.cfg` | QEMU Kubernetes plus observability without benchmark; rework profile includes endpoint runtime for endpoint resources | `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml`; suite `qemu_k8s_nobench_parity` | `certified` | Evidence: `docs/release_evidence_qemu_k8s_nobench_2026-07-08.md`. |
| P-QEMU-10-SW-LOCAL | Subset of `configuration/tests/qemu/10_kubernetes-openfaas.cfg` | QEMU Kubernetes plus OpenFaaS software phase on legacy node counts with cloud VM cores reduced from 6 to 4 for the single-host runner | `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml`; suite `qemu_openfaas_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_openfaas_software_2026-07-08.md`. This software-only subset does not certify parent row `P-QEMU-10`; use the separate parent evidence for exact application parity. |
| P-QEMU-10-APP-LOCAL | Subset of `configuration/tests/qemu/10_kubernetes-openfaas.cfg` | QEMU Kubernetes plus OpenFaaS image-classification application on legacy node counts with cloud VM cores reduced from 6 to 4 for the single-host runner | `configs/experiments/parity/qemu_openfaas_image_local/10_openfaas_image_classification_local.yaml`; suite `qemu_openfaas_image_local_parity` | `certified` | Evidence: `docs/release_evidence_qemu_openfaas_image_local_2026-07-08.md`. This remains a single-host CPU-capped subset. |
| P-QEMU-10 | `configuration/tests/qemu/10_kubernetes-openfaas.cfg` | QEMU Kubernetes plus OpenFaaS image-classification application | `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml`; suite `qemu_openfaas_image_parity` | `certified` | Evidence: `docs/release_evidence_qemu_openfaas_image_2026-07-08.md`. Exact 26 requested vCPU legacy shape passed with retained VM/application evidence on local plus `continuum-smoke@node3` external QEMU capacity. |
| P-GCP-01 | `configuration/tests/gcp/01_infraonly-cloud.cfg` | GCP cloud-only infrastructure | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| P-GCP-02 | `configuration/tests/gcp/02_infraonly-edge.cfg` | GCP edge-only infrastructure | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for edge-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| P-GCP-03 | `configuration/tests/gcp/03_infraonly-endpoint.cfg` | GCP endpoint-only infrastructure | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for endpoint-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| P-GCP-04 | `configuration/tests/gcp/04_infraonly-all.cfg` | GCP cloud/edge/endpoint infrastructure | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for cloud/edge/endpoint infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| P-GCP-05 | `configuration/tests/gcp/05_kuberentes-img.cfg` | GCP Kubernetes image/build path | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| P-GCP-06 | `configuration/tests/gcp/06_kubeedge-img.cfg` | GCP KubeEdge image/build path | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for KubeEdge image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| P-GCP-07 | `configuration/tests/gcp/07_mist-img.cfg` | GCP Mist image/build path | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Mist image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| P-GCP-08 | `configuration/tests/gcp/08_endpoint_img.cfg` | GCP endpoint image/runtime path | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for endpoint image/runtime, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| P-GCP-09 | `configuration/tests/gcp/09_kubernetes-nobench.cfg` | GCP Kubernetes without benchmark | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes without benchmark, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| P-GCP-10 | `configuration/tests/gcp/10_kubernetes-openfaas.cfg` | GCP Kubernetes plus OpenFaaS | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes plus OpenFaaS, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| P-AWS-01 | `configuration/tests/aws/01_infraonly-cloud.cfg` | AWS cloud-only infrastructure | No YAML environment profile identified | `historical` | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add an AWS environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |

## 5. Module Certification Backlog

This backlog tracks code/config surfaces that exist in the rework branch but
must not be described as release-certified until they satisfy the
provider-appropriate runtime-evidence gate defined by the applicable matrix
row. A gate may explicitly require VM-backed, cloud-backed, or host-backed
evidence; arbitrary local tests do not satisfy it.

| Module Family | Current Evidence Shape | Status | Required Before Public Claim |
| --- | --- | --- | --- |
| `qemu` provider | M1 local module-set rows, old-main infra-only parity rows, the Kubernetes image-classification row, the Kubernetes no-benchmark row, the full KubeEdge, Mist, endpoint image-classification rows, the software-only subset rows, and the exact OpenFaaS image-classification row have VM-backed evidence. | `certified` for M1 rows, `P-QEMU-01` through `P-QEMU-10`, `P-QEMU-06-SW`, `P-QEMU-07-SW`, `P-QEMU-08-SW`, `P-QEMU-10-SW-LOCAL`, and `P-QEMU-10-APP-LOCAL` only | Fresh provider-appropriate runtime evidence under the applicable matrix gate per additional topology, provider, or application claim. |
| `gcp` provider | Provider code and legacy cfg tests exist; no YAML environment profile identified in current configs. | `historical` | Keep release-unsupported and unresolved for M1, with every historical parity row retained in `docs/old_main_parity_issue_seed.md`; later certification needs YAML profiles, cloud prerequisites, credential/cost docs, and cloud-backed evidence. |
| `aws` provider | Provider code and one legacy cfg test exist; no YAML environment profile identified in current configs. | `historical` | Keep release-unsupported and unresolved for M1, with the historical parity row retained in `docs/old_main_parity_issue_seed.md`; later certification needs a scoped YAML profile, cloud prerequisites, credential/cost docs, and cloud-backed evidence. |
| `baremetal` provider | Provider code exists, but no current YAML profile, legacy test row, or host-backed release evidence was identified. The implementation is limited to one physical machine with one cloud role and endpoint roles, and explicitly rejects edge roles. | `ported-unverified` | Keep release-unsupported and unresolved for M1; later certification needs an explicit supported topology, YAML config/profile, host prerequisites, host-backed evidence, and documented limitations. |
| `kubernetes` | YAML profile, M1 smoke rows, the QEMU Kubernetes image-classification row, the QEMU no-benchmark parity row, the OpenFaaS single-host software/application variants, and the exact OpenFaaS application row have VM-backed evidence. | `certified` for M1 rows, `P-QEMU-05`, `P-QEMU-09`, `P-QEMU-10`, `P-QEMU-10-SW-LOCAL`, and `P-QEMU-10-APP-LOCAL` only | Fresh provider-appropriate runtime evidence under the applicable matrix gate per additional claimed topology. |
| `kubeedge` | YAML profiles exist; a software-only legacy-topology suite and the full QEMU image-classification application suite have VM-backed evidence on the legacy topology. | `certified` for `P-QEMU-06-SW` and `P-QEMU-06` only | Fresh provider-appropriate runtime evidence under the applicable matrix gate per additional KubeEdge topology or application claim. |
| `mist` | YAML profiles and suites exist; a software-only legacy-topology suite and the full QEMU image-classification application suite have VM-backed evidence with teardown verified. | `certified` for `P-QEMU-07-SW` and `P-QEMU-07` only | Fresh provider-appropriate runtime evidence under the applicable matrix gate per additional Mist topology or application claim; longer-term cleanup should split Mist from the shared KubeEdge base-install path. |
| `openfaas` | YAML profile, suite, single-host CPU-capped software/application variants, and the exact OpenFaaS image-classification parent row have VM-backed evidence. | `certified` for `P-QEMU-10`, `P-QEMU-10-SW-LOCAL`, and `P-QEMU-10-APP-LOCAL` only | Fresh provider-appropriate runtime evidence under the applicable matrix gate per additional OpenFaaS topology or provider claim. |
| `endpoint_runtime` | YAML profiles, the M1 benchmark row, the QEMU Kubernetes image-classification row, the QEMU no-benchmark parity row, the full endpoint image/runtime row, and the KubeEdge/Mist/endpoint-only/OpenFaaS rows have VM-backed evidence. | `certified` for M1 benchmark row, `P-QEMU-05`, `P-QEMU-06-SW`, `P-QEMU-07-SW`, `P-QEMU-08`, `P-QEMU-08-SW`, `P-QEMU-09`, `P-QEMU-10`, `P-QEMU-10-SW-LOCAL`, and `P-QEMU-10-APP-LOCAL` only | Fresh retained benchmark or software-phase evidence for additional claims. |
| `observability` | YAML module and QEMU no-benchmark parity row have VM-backed evidence. | `certified` for `P-QEMU-09` only | Fresh evidence per additional Kubernetes/KubeControl/Kata topology before broader claims. |
| `kubecontrol` | Resource-manager module, Kubernetes phase plan, control-plane image-prefetch metadata, legacy QEMU/GCP control-plane benchmark cfgs, and the M2 local-QEMU `kubecontrol` plus `empty` case-study and trace rows have evidence. | `certified` for `M2-QEMU-KUBECONTROL-EMPTY` and `M2-QEMU-KUBECONTROL-TRACE` only | Keep broader `kubecontrol` support unclaimed for M1. Future claims need fresh provider-appropriate runtime evidence under the applicable matrix gate per topology and must distinguish this minimal local-QEMU trace reproduction from broader Columbo paper sweeps. |
| `kube_kata` | Resource-manager module, Kata setup playbook, Kata runtime-class role, control-plane image-prefetch metadata, `empty_kata` application, legacy Kata experiment cfgs, YAML profile, candidate suite, host prerequisite doc, Jaeger worker setup, bounded trace retries, and artifact checks now have retained evidence for `M2-QEMU-KUBE-KATA-EMPTY`. | `certified` for `M2-QEMU-KUBE-KATA-EMPTY` only | Keep broader `kube_kata` support unclaimed for M1. The certified slice is scoped to local QEMU, `kata-qemu`, `overlayfs`, `cloud_nodes = 2`, `edge_nodes = 0`, explicit `runtime` and `runtime_filesystem`, nested virtualization/containerd/Kata prerequisites, documented `kata-fc` plus `overlayfs` exclusion, control-plane image prefetch, and retained evidence for cluster readiness, RuntimeClass installation, application success, Kata trace/artifact output, and cleanup. Future claims need fresh evidence per runtime, filesystem, topology, provider, or benchmark. |
| `image_classification` | M1 benchmark-smoke path and the full QEMU Kubernetes, KubeEdge, Mist, endpoint image/runtime, and OpenFaaS image-classification parity rows have VM-backed evidence and metric artifacts. | `certified` for M1 benchmark row, `P-QEMU-05`, `P-QEMU-06`, `P-QEMU-07`, `P-QEMU-08`, and `P-QEMU-10` only | Fresh retained benchmark evidence and metric artifact summary for additional claims. |
| `text_translation` | Application module exists, rejects `kubecontrol`, requires at least one endpoint, and uses MQTT publisher/subscriber images. No current YAML config, suite, success-detector contract, or retained release evidence was identified. | `ported-unverified` | Keep unclaimed and unresolved for M1. To certify later, add a supported-orchestrator YAML config with endpoint resources, document success/artifact checks for publisher/subscriber behavior, and capture provider-appropriate runtime evidence under the applicable matrix gate. |
| `empty` | Application module exists and is restricted to `kubecontrol`; legacy kubecontrol benchmark cfgs exist, and the M2 local-QEMU `kubecontrol` plus `empty` rows prove application success, benchmark artifacts, and strict control-plane trace evidence for the per-call deployment slice. | `certified` for `M2-QEMU-KUBECONTROL-EMPTY` and `M2-QEMU-KUBECONTROL-TRACE` only | Keep broader `empty`/`kubecontrol` benchmark support unclaimed for M1. Future claims need fresh evidence for each additional deployment mode, topology, application, or parameter sweep. |
| `empty_kata` | Application module exists and is restricted to `kube_kata`; legacy Kata startup cfgs, candidate YAML suite, host prerequisite doc, and structured `CLOUD OUTPUT`/`KATA OUTPUT` benchmark artifact contract have retained evidence for `M2-QEMU-KUBE-KATA-EMPTY`. | `certified` for `M2-QEMU-KUBE-KATA-EMPTY` only | Keep broader `empty_kata` support unclaimed for M1. Future claims need retained wrapper evidence per additional Kata runtime, filesystem, topology, application mode, or parameter sweep. |
| `stress` | Application module exists and current validation restricts it to `kubecontrol`; legacy resource-usage cfgs also reference Kata variants, so final orchestrator scope is unresolved. No current YAML suite, success-detector/resource-artifact contract, or retained release evidence was identified. | `ported-unverified` | Keep unclaimed and unresolved for M1. Decide whether `stress` is kubecontrol-only or needs a separate Kata-compatible implementation path; certification then requires a minimal YAML config, resource/success artifact checks, and provider-appropriate runtime evidence under the applicable matrix gate. |
| `mem_usage` | Application module exists and current validation restricts it to `kubecontrol`; legacy resource-usage cfgs also reference Kata variants, so final orchestrator scope is unresolved. No current YAML suite, memory-measurement artifact contract, or retained release evidence was identified. | `ported-unverified` | Keep unclaimed and unresolved for M1. Decide whether `mem_usage` is kubecontrol-only or needs a separate Kata-compatible implementation path; certification then requires a minimal YAML config, memory/success artifact checks, and provider-appropriate runtime evidence under the applicable matrix gate. |

## 6. Evidence Record Template

Use this template in release notes or a release-evidence document for every row
that moves to `certified`.

| Field | Value |
| --- | --- |
| Matrix row ID |  |
| Git commit |  |
| Tree state | clean, dirty synced to runner, or other explicit source state |
| Date | YYYY-MM-DD |
| Command |  |
| Runner context | Local shell, dedicated wrapper, or cloud runner |
| Provider / host prerequisites |  |
| Config | Use `N/A` for aggregate evidence covering multiple configs |
| Suite | Use `N/A` for aggregate evidence covering multiple suites |
| Provider profile | Use `N/A` when no single provider profile applies |
| Software profile | Use `N/A` when no single software profile applies |
| Runtime targets | infrastructure, software, application, cleanup |
| Required artifacts checked | lock, state, provider logs, software readiness, benchmark/network outputs |
| Result summary path |  |
| Artifact root |  |
| Limitations |  |

## 7. Immediate Next Steps

1. Keep the M1 cloud-safe audit fresh on the tree being tagged.
2. Rerun affected M1 VM-backed rows if runtime, runner, verifier, profile,
   playbook, or config code changes after the recorded VM-evidence source
   commit.
3. Run `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke
   release-artifact-audit` on the certification host before tagging any row as
   release-ready.
4. Run `python3 scripts/test/check_release_pretag.py` and keep M1 untagged
   until it reports zero issues.
5. Verify the installed `/usr/local/bin/continuum-hostctl` helper on the
   certification host before tagging. If the helper-interface contract changes,
   replace the root-owned helper only through a manual reviewed operator action.
6. Keep `docs/release_notes_m1_draft.md` synchronized with this matrix before
   publishing an intermediate release.
7. Refresh any certified VM-backed row if runtime, runner, verifier, profile,
   playbook, or config code changes after the recorded VM-evidence source
   commit.
8. Keep `P-QEMU-10-APP-LOCAL` scoped as a single-host CPU-capped subset; do not
   use it to claim exact parent-row parity.
9. Keep remaining GCP/AWS rows historical until a maintainer nominates exact
   scope, credentials, cost guardrails, YAML/profile targets, suites, and
   evidence requirements.
10. Convert the parity table into issues after M1, grouped by provider and
    software family, with repo docs remaining the first authoritative artifact.
11. Keep each historical row unresolved and in
    `docs/old_main_parity_issue_seed.md` until it is certified. Any future
    unsupported terminal closure requires the separate atomic checked-
    disposition change described in section 2.
