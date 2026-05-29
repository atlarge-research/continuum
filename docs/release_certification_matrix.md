# Continuum Release Certification Matrix

## 1. Purpose

This is the working matrix for turning the milestone release plan into
checkable rows. A row can be claimed in release notes only when its status is
`certified` and its evidence fields point to a fresh run for the release being
prepared.

Certification policy and labels are defined in
`docs/rework_milestone_release_plan.md`.

## 2. How To Use This Matrix

1. Keep `docs/rework_milestone_release_plan.md` as the release strategy.
2. Keep this document as the operational checklist for release rows.
3. Update a row to `certified` only after the exact config/module set has passed
   a full VM-backed or cloud-backed run.
4. Leave code-present but unproven rows as `ported-unverified`.
5. Leave legacy-only rows as `historical` until a YAML equivalent and evidence
   exist.
6. If a feature will not return, mark it `deprecated-proposed` first and add
   rationale before removing user-facing claims.

Generated logs under `logs/` are local evidence and are not committed by
default. Release notes should summarize the latest committed source revision,
command, operator/runner context, and artifact location for each certified row.
The current M1 release-notes draft is `docs/release_notes_m1_draft.md`.
`scripts/test/check_release_matrix.py` verifies that matrix config paths and
suite references resolve to current repository inventories, that every
runtime-certified row names a concrete rework experiment config and runner
suite, that the local `origin/main` ref is available, that every legacy test
config under both the current worktree and the local `origin/main`
`configuration/tests/` inventory has a matrix disposition, that the draft lists
every ready row and every ready-row primary evidence document, and that
non-ready rows stay in the nonclaim section. It also verifies that release notes
list only ready-row primary evidence documents, that certified row references in
the module backlog point only at ready matrix rows, and that
`docs/old_main_parity_issue_seed.md` mirrors every non-ready `P-*` row with a
matching status and a concrete issue seed.

## 3. M1 Certified Module-Set Rows

M1 is the first intermediate rework milestone. It should prove the structured
core plus one local, VM-backed vertical slice. It is not a final replacement for
old `main`.

| ID | Claim Boundary | Configs / Suites | Required Evidence | Current Status | Next Action |
| --- | --- | --- | --- | --- | --- |
| M1-CORE | Core parser, planner, selector, registry, runtime handoff, lock/state, and runner metadata are cloud-safe. | `scripts/test/run_cloud_static_audit.sh` | Required gates pass: compile sweep, cloud audit shell syntax check, smoke wrapper shell syntax check, host setup shell syntax check, git diff whitespace check, unit unittest discovery, e2e unittest discovery, combined unittest discovery, docs path reference check, public release-claims check, release certification matrix check, configured suite catalog. | `core-ready` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if source changes before publication. |
| M1-QEMU-INFRA | `qemu` provider module can provision a minimal cloud-tier VM and persist infrastructure state. | `configs/experiments/smoke/infra_one_vm.yaml`; suite `smoke`; wrapper scenario `infra_one_vm` | VM is provisioned and reachable; lock/state exist; state reaches infrastructure; teardown/retention behavior matches config. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if runtime code changes before publication. |
| M1-QEMU-K8S | `qemu + kubernetes` module set can deploy a minimal Kubernetes software phase. | `configs/experiments/smoke/software_k8s_two_vm.yaml`; suite `smoke`; wrapper scenario `software_k8s_two_vm` | Infrastructure and software phases pass; the Continuum runtime reaches the Kubernetes software phase successfully; lock/state remain consistent. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if runtime code changes before publication. |
| M1-QEMU-NET-SMOKE | `qemu` network-emulation path can produce netperf evidence on a minimal cloud/endpoint topology. | `configs/experiments/smoke/network_netperf_two_vm.yaml`; suite `smoke`; wrapper scenario `network_netperf_two_vm` | Netperf artifact exists under the run base path; network profile tolerances pass; lock/state evidence exists. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if network runtime or verifier code changes before publication. |
| M1-QEMU-NET-SUITE | Dedicated network-validation suite can validate the 4g profile on the release candidate. | `configs/experiments/network_validation/bench_net_4g.yaml`; suite `network_validation` | Structured netperf NDJSON is validated against latency/throughput tolerances. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if network runtime or verifier code changes before publication. |
| M1-QEMU-BENCH | `qemu + kubernetes + endpoint_runtime + image_classification` can resume across infrastructure, software, and application phases and then tear down. | `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`; suite `benchmark_smoke`; wrapper scenario `benchmark_k8s_resume` | Shared resume contract stays stable; application emits stdout markers and metric artifacts; teardown evidence proves saved QEMU domains are absent when deletion is requested. | `certified` | Keep evidence in `docs/release_evidence_m1_2026-05-29.md`; rerun if runtime code changes before publication. |

Preferred M1 host command sequence:

1. `scripts/test/run_cloud_static_audit.sh`
2. `sh scripts/test/setup_agent_host.sh install-hostctl`
3. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
4. `sudo -n /usr/local/bin/continuum-hostctl verify`
5. `sh scripts/test/setup_agent_host.sh verify`
6. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression`
7. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation`
8. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity` when certifying old-main QEMU infrastructure parity rows.
9. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity` when certifying the Kubernetes no-benchmark parity row.
10. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity` when certifying the KubeEdge software-only subset row.
11. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity` when certifying the Mist software-only subset row.
12. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity` when certifying the endpoint-runtime software-only subset row.
13. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity` when certifying the OpenFaaS software-only subset row.

The current wrapper supports `operational_regression`, which chains
`phase_smoke_matrix` and `benchmark_k8s_resume`. The dedicated
`network_validation` suite is claimed for the current M1 evidence snapshot. The
`qemu_infra_parity` suite remains separate because it certifies old-main
infrastructure parity rows rather than the first vertical M1 module set. The
pre-tag gate in `docs/release_notes_m1_draft.md` intentionally lists every
VM-backed wrapper scenario for rows claimed by the milestone.

Before publishing a release candidate from the certification host, also run:

```bash
python3 scripts/test/check_release_evidence_artifacts.py
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

## 4. Old-Main Provider And Topology Parity

This table starts from the legacy test inventory under `configuration/tests/`.
Rows are not release-ready until the YAML equivalent is explicit and a fresh
VM-backed or cloud-backed run proves the claim on the rework stack.

| ID | Legacy Row | Old Public Surface | Related Rework YAML / Profile | Status | Certification Action |
| --- | --- | --- | --- | --- | --- |
| P-QEMU-01 | `configuration/tests/qemu/01_infraonly-cloud.cfg` | QEMU cloud-only infrastructure | `configs/experiments/parity/qemu/01_infraonly_cloud.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-05-29.md`. |
| P-QEMU-02 | `configuration/tests/qemu/02_infraonly-edge.cfg` | QEMU edge-only infrastructure | `configs/experiments/parity/qemu/02_infraonly_edge.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-05-29.md`. |
| P-QEMU-03 | `configuration/tests/qemu/03_infraonly-endpoint.cfg` | QEMU endpoint-only infrastructure | `configs/experiments/parity/qemu/03_infraonly_endpoint.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-05-29.md`. |
| P-QEMU-04 | `configuration/tests/qemu/04_infraonly-all.cfg` | QEMU cloud/edge/endpoint infrastructure | `configs/experiments/parity/qemu/04_infraonly_all.yaml`; suite `qemu_infra_parity` | `certified` | Evidence: `docs/release_evidence_qemu_infra_parity_2026-05-29.md`. |
| P-QEMU-05 | `configuration/tests/qemu/05_kuberentes-img.cfg` | QEMU Kubernetes plus image-classification application with netperf enabled | `configs/experiments/parity/qemu_k8s_image/05_kubernetes_image_classification.yaml`; suite `qemu_k8s_image_parity` | `ported-unverified` | VM attempt reached the forced image-prefetch path and is blocked on Docker daemon access for the smoke user. Keep unclaimed until the host prerequisite or registry design is fixed, then certify application metric artifacts plus netperf evidence. |
| P-QEMU-06-SW | Subset of `configuration/tests/qemu/06_kubeedge-img.cfg` | QEMU KubeEdge software phase on the legacy cloud/edge/endpoint topology, without image-classification application | `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml`; suite `qemu_kubeedge_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_kubeedge_software_2026-05-29.md`. This does not certify the full P-QEMU-06 application row. |
| P-QEMU-06 | `configuration/tests/qemu/06_kubeedge-img.cfg` | QEMU KubeEdge image-classification application path | `configs/experiments/parity/qemu_kubeedge_image/06_kubeedge_image_classification.yaml`; suite `qemu_kubeedge_image_parity`; software subset: `configs/experiments/parity/qemu_kubeedge_software/06_kubeedge_software.yaml` | `ported-unverified` | Full application suite is ported and the local registry cache was primed through `sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite qemu_kubeedge_image_parity`. Latest wrapper attempt reached the application phase but failed because edge-node flannel pods entered `CrashLoopBackOff`, leaving image-classification pods in `ContainerCreating`. Keep unclaimed until the edge CNI failure is fixed and a full VM suite records application metric artifacts as certification evidence. Attempt evidence: `/home/continuum-smoke/continuum_smoke/qemu_kubeedge_image_parity/.continuum/test_results/test_results_2026-05-29_21-05-38.json`. |
| P-QEMU-07-SW | Subset of `configuration/tests/qemu/07_mist-img.cfg` | QEMU Mist software phase on the legacy edge/endpoint topology, without image-classification application | `configs/experiments/parity/qemu_mist_software/07_mist_software.yaml`; suite `qemu_mist_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_mist_software_2026-05-29.md`. This does not certify the full P-QEMU-07 application row. |
| P-QEMU-07 | `configuration/tests/qemu/07_mist-img.cfg` | QEMU Mist image/build path | `configs/experiments/parity/qemu_mist_image/07_mist_image_classification.yaml`; suite `qemu_mist_image_parity` | `ported-unverified` | Full application suite is ported and now gates on a primed local registry cache instead of Docker daemon access for the smoke user. Keep unclaimed until the cache is primed and the full VM suite records application metric artifacts as certification evidence. |
| P-QEMU-08-SW | Subset of `configuration/tests/qemu/08_endpoint_img.cfg` | QEMU endpoint runtime software phase on the legacy endpoint-only topology, without image-classification application | `configs/experiments/parity/qemu_endpoint_software/08_endpoint_runtime.yaml`; suite `qemu_endpoint_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_endpoint_software_2026-05-29.md`. This does not certify the full P-QEMU-08 application row. |
| P-QEMU-08 | `configuration/tests/qemu/08_endpoint_img.cfg` | QEMU endpoint image/runtime path | `configs/experiments/parity/qemu_endpoint_image/08_endpoint_image_classification.yaml`; suite `qemu_endpoint_image_parity` | `ported-unverified` | Full application suite is ported, but its preflight is blocked on Docker daemon access for forced endpoint image prefetch. Keep unclaimed until that prerequisite or registry design is resolved, then certify with VM evidence and application metric artifacts. |
| P-QEMU-09 | `configuration/tests/qemu/09_kubernetes-nobench.cfg` | QEMU Kubernetes plus observability without benchmark; rework profile includes endpoint runtime for endpoint resources | `configs/experiments/parity/qemu_k8s_nobench/09_kubernetes_nobench.yaml`; suite `qemu_k8s_nobench_parity` | `certified` | Evidence: `docs/release_evidence_qemu_k8s_nobench_2026-05-29.md`. |
| P-QEMU-10-SW-LOCAL | Subset of `configuration/tests/qemu/10_kubernetes-openfaas.cfg` | QEMU Kubernetes plus OpenFaaS software phase on legacy node counts with cloud VM cores reduced from 6 to 4 for the single-host runner | `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml`; suite `qemu_openfaas_software_parity` | `certified` | Evidence: `docs/release_evidence_qemu_openfaas_software_2026-05-29.md`. This does not certify the exact legacy CPU shape or the full P-QEMU-10 application row. |
| P-QEMU-10 | `configuration/tests/qemu/10_kubernetes-openfaas.cfg` | QEMU Kubernetes plus OpenFaaS image-classification application | `configs/experiments/parity/qemu_openfaas_image/10_openfaas_image_classification.yaml`; suite `qemu_openfaas_image_parity`; software subset: `configs/experiments/parity/qemu_openfaas_software/10_openfaas_software.yaml` | `ported-unverified` | Full application suite is ported, but its preflight is blocked on Docker daemon access for forced OpenFaaS image prefetch. The exact 26-core legacy shape also needs external QEMU capacity or a runner host with a higher local core budget. Keep unclaimed until both prerequisites or the support claim are resolved, then certify with VM evidence and application metric artifacts. |
| P-GCP-01 | `configuration/tests/gcp/01_infraonly-cloud.cfg` | GCP cloud-only infrastructure | No YAML environment profile identified | `historical` | Keep unclaimed until a GCP environment profile exists and cloud evidence passes, or document historical/deprecated disposition. |
| P-GCP-02 | `configuration/tests/gcp/02_infraonly-edge.cfg` | GCP edge-only infrastructure | No YAML environment profile identified | `historical` | Port or deprecate this topology. |
| P-GCP-03 | `configuration/tests/gcp/03_infraonly-endpoint.cfg` | GCP endpoint-only infrastructure | No YAML environment profile identified | `historical` | Port or deprecate this topology. |
| P-GCP-04 | `configuration/tests/gcp/04_infraonly-all.cfg` | GCP cloud/edge/endpoint infrastructure | No YAML environment profile identified | `historical` | Port or deprecate this topology. |
| P-GCP-05 | `configuration/tests/gcp/05_kuberentes-img.cfg` | GCP Kubernetes image/build path | No YAML environment profile identified | `historical` | Keep unclaimed until a provider profile exists and cloud-backed application evidence passes, or document historical/deprecated disposition. |
| P-GCP-06 | `configuration/tests/gcp/06_kubeedge-img.cfg` | GCP KubeEdge image/build path | No YAML environment profile identified | `historical` | Keep unclaimed until a provider profile exists and cloud-backed application evidence passes, or document historical/deprecated disposition. |
| P-GCP-07 | `configuration/tests/gcp/07_mist-img.cfg` | GCP Mist image/build path | No YAML environment profile identified | `historical` | Port provider/profile path or deprecate. |
| P-GCP-08 | `configuration/tests/gcp/08_endpoint_img.cfg` | GCP endpoint image/runtime path | No YAML environment profile identified | `historical` | Port provider/profile path or deprecate. |
| P-GCP-09 | `configuration/tests/gcp/09_kubernetes-nobench.cfg` | GCP Kubernetes without benchmark | No YAML environment profile identified | `historical` | Keep unclaimed until a provider/profile path exists and cloud-backed evidence passes, or document historical/deprecated disposition. |
| P-GCP-10 | `configuration/tests/gcp/10_kubernetes-openfaas.cfg` | GCP Kubernetes plus OpenFaaS | No YAML environment profile identified | `historical` | Keep unclaimed until a provider/profile path exists and cloud-backed evidence passes, or document historical/deprecated disposition. |
| P-AWS-01 | `configuration/tests/aws/01_infraonly-cloud.cfg` | AWS cloud-only infrastructure | No YAML environment profile identified | `historical` | Decide whether AWS stays in parity scope; keep unclaimed until profile and cloud evidence exist, or deprecate. |

## 5. Module Certification Backlog

This backlog tracks code/config surfaces that exist in the rework branch but
must not be described as release-certified until their rows have VM/cloud
evidence.

| Module Family | Current Evidence Shape | Status | Required Before Public Claim |
| --- | --- | --- | --- |
| `qemu` provider | M1 local module-set rows, old-main infra-only parity rows, the Kubernetes no-benchmark row, the KubeEdge/Mist/endpoint-runtime software-only subset rows, and the OpenFaaS single-host software-only variant have VM-backed evidence. | `certified` for M1 rows, `P-QEMU-01` through `P-QEMU-04`, `P-QEMU-06-SW`, `P-QEMU-07-SW`, `P-QEMU-08-SW`, `P-QEMU-09`, and `P-QEMU-10-SW-LOCAL` only | Continue remaining old-main QEMU application parity rows before broadening the QEMU parity claim. `image_prefetch: "off"` rows now require a primed local registry cache; forced-prefetch rows still require Docker daemon access on the runner host. Exact P-QEMU-10 resource parity needs external QEMU capacity or a larger local runner. |
| `gcp` provider | Provider code and legacy cfg tests exist; no YAML environment profile identified in current configs. | `historical` | YAML profile, cloud prerequisites, cloud-backed evidence, cost/credential docs. |
| `aws` provider | Provider code and one legacy cfg test exist; no YAML environment profile identified in current configs. | `historical` | Scope decision, YAML profile, cloud-backed evidence, cost/credential docs. |
| `baremetal` provider | Provider code exists. | `ported-unverified` | Decide support target and add host/cluster certification path. |
| `kubernetes` | YAML profile, M1 smoke rows, the QEMU no-benchmark parity row, and the OpenFaaS single-host software-only variant have VM-backed evidence. | `certified` for M1 rows, `P-QEMU-09`, and `P-QEMU-10-SW-LOCAL` only | Fresh VM evidence per additional claimed topology. |
| `kubeedge` | YAML profiles exist; a software-only legacy-topology suite has VM-backed software-phase evidence on the legacy topology; the full application suite is ported and can use the host-primed local-registry cache. | `certified` for `P-QEMU-06-SW` only | Fix the edge-node flannel `CrashLoopBackOff` observed in the 2026-05-29 full application attempt, then rerun full application evidence with metric artifacts. |
| `mist` | YAML profiles and suites exist; a software-only legacy-topology suite has VM-backed evidence with teardown verified; the full application suite is ported and now preflights local-registry cache readiness. | `certified` for `P-QEMU-07-SW` only | Full application evidence after the required images are primed into the local registry cache; longer-term cleanup should split Mist from the shared KubeEdge base-install path. |
| `openfaas` | YAML profile, suite, and a single-host CPU-capped software-only variant have VM-backed software-phase evidence. | `certified` for `P-QEMU-10-SW-LOCAL` only | Full application evidence after Docker image-prefetch access and exact-resource-capacity decisions are resolved. |
| `endpoint_runtime` | YAML profiles, the M1 benchmark row, the QEMU no-benchmark parity row, and the KubeEdge/Mist/endpoint-only/OpenFaaS software subset rows have VM-backed evidence. | `certified` for M1 benchmark row, `P-QEMU-06-SW`, `P-QEMU-07-SW`, `P-QEMU-08-SW`, `P-QEMU-09`, and `P-QEMU-10-SW-LOCAL` only | Fresh retained benchmark or software-phase evidence for additional claims. |
| `observability` | YAML module and QEMU no-benchmark parity row have VM-backed evidence. | `certified` for `P-QEMU-09` only | Fresh evidence per additional Kubernetes/KubeControl/Kata topology before broader claims. |
| `kubecontrol` | Resource-manager module exists. | `ported-unverified` | Define supported module set, config, image-prefetch behavior, and evidence. |
| `kube_kata` | Resource-manager module and `empty_kata` application exist. | `ported-unverified` | Define supported module set, host prerequisites, runtime evidence, and limitations. |
| `image_classification` | M1 benchmark-smoke path has VM-backed evidence and metric artifacts. | `certified` for M1 benchmark row only | Fresh retained benchmark evidence and metric artifact summary for additional claims. |
| `text_translation` | Application module exists. | `ported-unverified` | Add example config, success detector, and VM-backed evidence before public claim. |
| `stress`, `mem_usage`, `empty`, `empty_kata` | Application modules exist. | `ported-unverified` | Decide whether each remains public release scope; add configs and evidence if claimed. |

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
3. Run `python3 scripts/test/check_release_evidence_artifacts.py` on the
   certification host before tagging any row as release-ready.
4. Run `python3 scripts/test/check_release_pretag.py` and keep M1 untagged
   until it reports zero issues.
5. Verify the installed `/usr/local/bin/continuum-hostctl` helper on the
   certification host before tagging. Refresh it through the root-owned wrapper
   pattern in `docs/agent_sudo_boundaries.md` if the live setup script changes
   its helper-interface contract.
6. Keep `docs/release_notes_m1_draft.md` synchronized with this matrix before
   publishing an intermediate release.
7. Investigate the full `P-QEMU-06` application attempt where edge-node flannel
   pods entered `CrashLoopBackOff` after successful host-side registry cache
   priming.
   Keep the Docker-daemon prerequisite for forced-prefetch rows `P-QEMU-05`,
   `P-QEMU-08`, and full `P-QEMU-10` until the runner host or registry design
   supports that claim.
8. Continue QEMU software/application parity rows `P-QEMU-05` through `P-QEMU-08`
   and full `P-QEMU-10`, starting with rows that can produce truthful VM
   evidence on the available runner.
9. Convert the parity table into issues after M1, grouped by provider and
   software family.
10. For each historical row, choose port, preserve-as-historical, or deprecate.
