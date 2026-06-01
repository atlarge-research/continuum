# M1 Release Evidence Snapshot - 2026-05-31

## 1. Scope

This snapshot records the first M1 local QEMU/libvirt certification run for the
rework branch. It covers the certified module-set rows in
`docs/release_certification_matrix.md`.

This is evidence for an intermediate milestone, not for final replacement of old
`main`. Old-main provider/software parity remains open.

## 2. Source And Runner Context

| Field | Value |
| --- | --- |
| Live checkout | `/home/matthijs/continuum` |
| Git commit | `9b380abed1909aa0afad8ef32bc71a1d203941ea` |
| Tree state | Clean source tree synced to the dedicated runner |
| Dedicated repo | `/srv/continuum/repo` |
| Runner user | `continuum-smoke` |
| Runner base root | `/mnt/sdc/continuum_smoke` |
| Host wrapper | `/usr/local/bin/run-continuum-smoke` |
| Host maintenance helper | `/usr/local/bin/continuum-hostctl` |
| Provider / host prerequisites | Local QEMU/libvirt/KVM host with libvirt access, `/dev/kvm` access, SSH access, and tc/netperf support for network rows; no cloud credentials. |
| Runtime targets | `infrastructure`, `software`, `application`, cleanup across the certified M1 rows |
| Required artifacts checked | Cloud-static audit report, retained test-results summaries, experiment locks, state files, stdout/stderr/metadata artifacts, infrastructure phase evidence, software phase evidence, network NDJSON, benchmark metrics manifest, teardown evidence |
| Profile IDs | Environment profiles: `local-qemu`, `local-qemu-netperf`, `local-qemu-delete-on-exit`; software profiles: `none`, `k8s`, `k8s-endpoint-runtime` |
| Date | 2026-05-31 |

Before VM-backed execution, the dedicated repo was synced from the live checkout
and verified:

1. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
2. `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`
3. `sudo -n /usr/local/bin/continuum-hostctl verify`

The verifier confirmed libvirt access, `/dev/kvm` readability, runner repo
readability, dedicated repo sync, read-only runner access, and smoke-wrapper
prerequisites.

## 3. Cloud-Safe Baseline

Latest cloud-safe audit after the M1, QEMU infra-parity, KubeEdge software,
Mist software, endpoint-runtime software, OpenFaaS software, cache-backed
image-parity preflight inventory, forced-prefetch certification-context notice,
stricter release-matrix drift/status/evidence/config/suite/release-note sync,
release-note orphan-evidence and unknown-row checks, pre-tag wrapper-scenario,
pre-tag exact-source checks, release-evidence source-context,
prerequisite-scope, limitation-scope, and runtime-scope checks, old-main
`origin/main` ref availability and legacy-test inventory checks, parity matrix
action and issue-seed presence/status/closure-path checks, public,
release-evidence-doc, and certification-matrix release-claims checks,
configuration-reference and migration-note completeness checks,
legacy-configuration README claim checks,
global Markdown release-claim scanning under `docs/` and `configuration/`,
status-cell-specific release-evidence artifact claim checks, source-context
format checks, broad QEMU parity release-claim checks,
module-readiness overclaim checks for unsupported gateway/edge readiness wording,
cloud-audit zero-total checks for docs paths, release claims, and release
matrix drift,
clean marker debt scan, host helper interface drift checks, pre-tag command
ordering checks, wrapper-based release-evidence artifact audit and pre-tag readiness report entries,
cloud-audit artifact-audit availability checks,
ready-suite prerequisite status checks,
ready-suite prerequisite coverage in the cloud-static audit, ready-row
wrapper-scenario traceability, non-ready suite command exclusion from the
pre-tag gate, final/full-release claim wording checks, release-note
ready/nonclaim consistency checks, software-only subset runtime-scope checks,
pre-tag readiness status/issue-count consistency checks,
primary-evidence matrix reference checks, and post-release roadmap,
operational-testing-strategy, plan-stack, kickoff, host-runner, and Phase-D
handoff claim checks, plus pre-tag `git diff --check` aggregation and
dirty-worktree diagnostics, and cloud-safe prerequisite visibility for every
configured parity suite with artifact-level parity-suite prereq evidence and
latest cloud-audit report checks, plus caveated release-overclaim checks for
unsupported cloud-provider/application support wording, and final pre-tag
latest-cloud-audit report checks with required M1 evidence `Report` field
validation, named report-path existence checks, canonical
`logs/cloud_static_audit/` report-directory checks, canonical
`cloud_static_audit_YYYY-MM-DDTHHMMSSZ.md` filename checks, filename-to-heading
timestamp integrity checks, missing cloud-audit heading checks, and absolute-path
extraction that ignores relative evidence paths, plus release-note intermediate-
milestone and not-final-main-replacement wording checks, plus release-note
non-ready module backlog coverage checks, plus release-note known-limitations
checks for active host-helper,
registry-cache, Docker-prefetch, cloud-evidence,
and QEMU-capacity
blockers,
plus retained test-result runtime metadata and stdout/stderr/metadata
artifact checks with metadata-summary consistency validation, top-level
timestamp/artifacts-dir provenance, artifact containment validation, and
state-phase validation against YAML `run.targets`, plus explicit release-evidence
`Runtime targets` fields with certified-config target coverage and
cleanup/teardown claims tied to retained `teardown_verified` evidence, plus
local-QEMU provider prerequisite checks for QEMU/libvirt/KVM and no cloud
credentials, certified-config profile-ID mentions, and phase-support checks for
release-evidence runtime-target claims, plus benchmark application metric
evidence checks for certified benchmark pipeline configs, and structured
network NDJSON evidence checks for certified rows that claim netperf or network
profile evidence, plus same-run `experiment_lock.yaml` and `state.json`
existence checks with readable lock/source validation and readable state-phase
validation where runner file permissions allow it, plus retained stdout-marker
checks for evidence docs that claim Kubernetes node-ready runtime checks, plus
software-only subset evidence-scope checks for non-certified
image-classification metric artifacts, plus single-source-commit checks across
the release evidence set, plus retained VM test-result date checks against the
evidence document date, plus required structured Matrix row ID field checks for
single-result evidence docs against the release matrix, plus structured Suite
field checks against release-matrix suite references and required structured
Suite fields for single-suite evidence docs, plus structured Command field
checks for single-suite evidence docs, plus structured Config field checks for
single-config evidence docs, plus required structured Runner context field
checks for single-result evidence docs, plus required structured
Provider/Software profile field checks for single-config evidence docs against
certified config `use` profiles, plus structured Result summary path checks for
single-result evidence docs, plus required structured Artifact root field
checks against retained `.continuum` test-result roots, plus required
`Required artifacts checked` fields for single-result evidence docs with
baseline test-results, lock, state, stdout, stderr, metadata, and teardown
markers where applicable, plus aggregate artifact-kind markers for cloud-static
audit reports, network NDJSON, and benchmark metric manifests, plus runtime-
phase artifact markers for claimed infrastructure, software, and application
targets, plus artifact-kind overclaim checks that reject specialized artifact
categories absent from the evidence doc's primary artifact set, plus
release-matrix evidence-template field checks for the same structured evidence
contract, including `Required artifacts checked`, plus
required section-scoped artifact-audit Command, primary-artifact-count, and
result fields when an evidence doc records a local release-evidence artifact
audit section:

| Field | Value |
| --- | --- |
| Command | `scripts/test/run_cloud_static_audit.sh` |
| Report | `/home/matthijs/continuum/logs/cloud_static_audit/cloud_static_audit_2026-05-31T092920Z.md` |
| Required gates | PASS |
| Unit unittest discovery | 609 tests OK |
| E2E unittest discovery | 86 tests OK |
| Combined unittest discovery | 695 tests OK |
| Pytest mirror | 695 passed |
| Marker debt scan | MATCHES FOUND (2) |
| Pre-tag readiness | `TOTAL_RELEASE_PRETAG_ISSUES=0` after refreshing the VM-backed evidence from the current release candidate |
| Informational prereq findings | Every configured parity suite has cloud-safe prerequisite visibility and reports prerequisites satisfied in the current shell. Forced-prefetch and registry-cache application rows still require dedicated smoke-user wrapper VM evidence before certification. |

The two marker debt scan matches are both from documented `mktemp` examples in
the manual hostctl replacement flow.

Local release-evidence artifact audit on the certification host:

| Field | Value |
| --- | --- |
| Command | `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit` |
| Primary artifacts checked | 15 |
| Result | `TOTAL_RELEASE_EVIDENCE_ARTIFACT_ISSUES=0` |

Current pre-tag host-helper status after the sudo-hardening interface bump:

| Field | Value |
| --- | --- |
| Verify command | `sudo -n /usr/local/bin/continuum-hostctl verify` |
| Verify result | PASS |
| Current finding | None; the installed helper interface matches the repo-generated helper, the dedicated repo is synced and read-only for `continuum-smoke`, and wrapper prerequisites pass. |

Host-runner status on 2026-05-31: the dedicated repo and installed wrapper were
refreshed with `sudo -n /usr/local/bin/continuum-hostctl sync-repo` and
`sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated
/mnt/sdc/continuum_smoke`. `sudo -n /usr/local/bin/continuum-hostctl verify`
passed after syncing the clean live checkout.

The stricter pre-tag checker allows release documentation and release checker
updates after the VM evidence source commit, but any runtime, config, profile,
playbook, wrapper, or runner change after that commit requires rerunning the
affected VM-backed wrapper scenarios before tagging.

Rerun the cloud-safe audit again before cutting an M1 tag if any source changes
after this snapshot.

## 4. Operational Regression Evidence

Command:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression
```

This wrapper scenario chains `phase_smoke_matrix` and `benchmark_k8s_resume`.

| Matrix Row | Config(s) | Result | Evidence |
| --- | --- | --- | --- |
| `M1-QEMU-INFRA` | `configs/experiments/smoke/infra_one_vm.yaml` | PASS, 61.1s | `/mnt/sdc/continuum_smoke/infra_one_vm/.continuum/test_results/test_results_2026-05-31_17-53-16.json` |
| `M1-QEMU-K8S` | `configs/experiments/smoke/software_k8s_two_vm.yaml` | PASS, 725.7s | `/mnt/sdc/continuum_smoke/software_k8s_two_vm/.continuum/test_results/test_results_2026-05-31_18-05-22.json` |
| `M1-QEMU-NET-SMOKE` | `configs/experiments/smoke/network_netperf_two_vm.yaml` | PASS, 136.6s | `/mnt/sdc/continuum_smoke/network_netperf_two_vm/.continuum/test_results/test_results_2026-05-31_18-07-39.json` |
| `M1-QEMU-BENCH` | `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`; `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml` | PASS, 1242.5s total | `/mnt/sdc/continuum_smoke/benchmark_k8s_resume/.continuum/test_results/test_results_2026-05-31_18-28-22.json` |

Structured netperf artifact for `M1-QEMU-NET-SMOKE`:

```text
/mnt/sdc/continuum_smoke/network_netperf_two_vm/.continuum/logs/network_validation/netperf_results_2026-05-31_18:05:23.ndjson
```

Runner success evidence included:

1. `experiment_lock.yaml` written,
2. `state.json` written,
3. expected `state_phase` for each phase,
4. resume-contract match,
5. SSH output where required,
6. benchmark stdout/metric evidence for the application leg,
7. latest benchmark metric artifact:
   `/mnt/sdc/continuum_smoke/benchmark_k8s_resume/.continuum/logs/benchmark/2026-05-31_18_25_06_classify-images_metrics_manifest.json`,
8. teardown verified for the retained benchmark application leg.

## 5. Dedicated Network-Validation Evidence

The first `network_validation` wrapper run completed the Continuum infra/netperf
execution but failed success detection because the verifier treated a nominal
1 Gbit/s cloud-edge wired default as an exact throughput assertion and parsed
TCP_RR latency from header numbers.

The verifier was corrected to:

1. parse the final netperf TCP_RR result row,
2. compare TCP_RR latency against round-trip profile latency,
3. strictly validate throughput only for constrained links,
4. require parseable throughput evidence for high-capacity wired defaults
   without treating local QEMU host capacity as a 1 Gbit/s certification claim.

Focused verification after the fix:

1. `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_verify_network_profiles scripts.test.e2e.test_e2e_test_utils`
2. `python3 scripts/test/verify_network_profiles.py --base-path /home/continuum-smoke/continuum_smoke/network_validation`

Final wrapper rerun:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation
```

| Matrix Row | Config | Result | Evidence |
| --- | --- | --- | --- |
| `M1-QEMU-NET-SUITE` | `configs/experiments/network_validation/bench_net_4g.yaml` | PASS, 254.7s | `/mnt/sdc/continuum_smoke/network_validation/.continuum/test_results/test_results_2026-05-31_18-32-53.json` |

Structured netperf artifact:

```text
/mnt/sdc/continuum_smoke/network_validation/.continuum/logs/network_validation/netperf_results_2026-05-31_18:28:39.ndjson
```

The final success reason included `exit_code=0`, `experiment_lock_written`,
`state_file_written`, `state_phase=infrastructure`, `resume_contract_match`, and
the structured network-validation result path.

## 6. Certification Result

For the current M1 local QEMU/libvirt milestone scope:

| Row | Status |
| --- | --- |
| `M1-CORE` | `core-ready` |
| `M1-QEMU-INFRA` | `certified` |
| `M1-QEMU-K8S` | `certified` |
| `M1-QEMU-NET-SMOKE` | `certified` |
| `M1-QEMU-NET-SUITE` | `certified` |
| `M1-QEMU-BENCH` | `certified` |

Before publishing an M1 tag or release notes, rerun the cloud-safe audit on the
final source tree. If runtime, runner, or verifier code changes after this
snapshot, rerun the affected VM-backed rows.
