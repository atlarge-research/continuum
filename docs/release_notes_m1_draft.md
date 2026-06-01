# Continuum M1 Milestone Release Notes Draft

## 1. Release Type

This is a draft for an intermediate rework milestone release. It is not a final
replacement for the old `main` branch.

The purpose of this milestone is to publish the structured planning-engine
rework with a small, evidence-backed local module set and the first certified
old-main QEMU parity rows. Any support claim in these notes is limited to rows
marked `certified` or `core-ready` in
`docs/release_certification_matrix.md`.

## 2. Primary Evidence

Use these documents as the release evidence set:

1. `docs/release_certification_matrix.md`
2. `docs/release_evidence_m1_2026-06-01.md`
3. `docs/release_evidence_qemu_infra_parity_2026-06-01.md`
4. `docs/release_evidence_qemu_k8s_image_2026-06-01.md`
5. `docs/release_evidence_qemu_k8s_nobench_2026-06-01.md`
6. `docs/release_evidence_qemu_kubeedge_software_2026-06-01.md`
7. `docs/release_evidence_qemu_kubeedge_image_2026-06-01.md`
8. `docs/release_evidence_qemu_mist_software_2026-06-01.md`
9. `docs/release_evidence_qemu_mist_image_2026-06-01.md`
10. `docs/release_evidence_qemu_endpoint_software_2026-06-01.md`
11. `docs/release_evidence_qemu_endpoint_image_2026-06-01.md`
12. `docs/release_evidence_qemu_openfaas_software_2026-06-01.md`

Before tagging, rerun the commands in section 7. VM-backed evidence may name a
clean runtime source commit that precedes final release-documentation commits,
but no runtime, config, profile, playbook, wrapper, or runner path may change
after that evidence source commit without rerunning the affected wrapper
scenario.

Current checkpoint note: the VM-backed evidence set has been refreshed on one
runtime source line. Keep it tag-ready by rerunning any affected wrapper
scenario if runtime, runner, verifier, profile, playbook, or config code changes
after the recorded VM-evidence source commit.

## 3. What This Milestone Certifies

This milestone certifies matrix row `M1-CORE`, the structured Continuum core,
as `core-ready` for:

1. YAML/profile composition and schema validation,
2. normalized infrastructure, software, and benchmark domains,
3. selector and scope resolution,
4. module registry and dependency/capability validation,
5. planner snapshots and runtime handoff metadata,
6. runtime lock/state/resume contracts,
7. test-runner metadata, success detection, and artifact contracts.

This milestone certifies the following local QEMU/libvirt rows:

| Row | Claim |
| --- | --- |
| `M1-QEMU-INFRA` | Minimal local QEMU cloud-tier VM infrastructure path |
| `M1-QEMU-K8S` | Minimal local QEMU plus Kubernetes software phase |
| `M1-QEMU-NET-SMOKE` | Minimal local QEMU netperf smoke path |
| `M1-QEMU-NET-SUITE` | Dedicated 4g network-validation suite |
| `M1-QEMU-BENCH` | Resumed `qemu + kubernetes + endpoint_runtime + image_classification` benchmark path with teardown evidence |
| `P-QEMU-01` through `P-QEMU-04` | Old-main QEMU infrastructure-only parity rows |
| `P-QEMU-05` | Old-main QEMU Kubernetes image-classification application parity row |
| `P-QEMU-09` | Old-main QEMU Kubernetes no-benchmark parity row |
| `P-QEMU-06-SW` | KubeEdge software-only subset of old-main P-QEMU-06 |
| `P-QEMU-06` | Full KubeEdge image-classification application parity row |
| `P-QEMU-07-SW` | Mist software-only subset of old-main P-QEMU-07 |
| `P-QEMU-07` | Full Mist image-classification application parity row |
| `P-QEMU-08-SW` | Endpoint-runtime software-only subset of old-main P-QEMU-08 |
| `P-QEMU-08` | Full endpoint image/runtime application parity row |
| `P-QEMU-10-SW-LOCAL` | Single-host CPU-capped OpenFaaS software-only subset of old-main P-QEMU-10 |

These rows are certified only for the exact configs, profiles, host context,
runtime targets, and limitations recorded in the evidence documents.

## 4. What This Milestone Does Not Certify

Do not describe this milestone as full old-main parity.

The following rows remain unclaimed:

1. full QEMU OpenFaaS application parity row `P-QEMU-10`,
2. exact legacy P-QEMU-10 resource shape with three 6-core cloud VMs,
3. GCP rows `P-GCP-01` through `P-GCP-10`,
4. AWS row `P-AWS-01`,
5. bare-metal provider support,
6. broader `kubecontrol`, `kube_kata`, `text_translation`, `stress`,
   `mem_usage`, `empty`, and `empty_kata` runtime support,
7. a visual frontend,
8. structured experiment database support,
9. a reproducibility-package catalog.

These may be ported, certified, preserved as historical, or deprecated in later
milestones.

## 5. Known Limitations

1. QEMU is a provider module, not Continuum core.
2. Full Kubernetes image-classification parity is certified for `P-QEMU-05`;
   the exact evidence is `docs/release_evidence_qemu_k8s_image_2026-06-01.md`.
   Full endpoint image/runtime parity is certified for `P-QEMU-08`; the exact
   evidence is `docs/release_evidence_qemu_endpoint_image_2026-06-01.md`.
3. Full KubeEdge application parity is certified only for `P-QEMU-06`; the
   exact evidence is `docs/release_evidence_qemu_kubeedge_image_2026-06-01.md`.
   Full Mist application parity is certified only for `P-QEMU-07`; the exact
   evidence is `docs/release_evidence_qemu_mist_image_2026-06-01.md`.
4. Full OpenFaaS application parity still requires a manually refreshed
   `continuum-hostctl` helper with root-owned registry-cache priming, a primed
   local registry cache, and retained VM/application evidence.
5. Full OpenFaaS application parity also needs a decision on exact legacy
   resource-shape certification or a larger/external QEMU runner.
6. Cloud-provider rows need YAML profiles, credential/cost documentation, and
   cloud-backed evidence before they can be release-supported.
7. Cache-backed full application parity rows require an explicitly primed local
   registry cache for certification. Host-side cache priming is exposed through
   the allowlisted `continuum-hostctl prime-registry-cache` helper.

## 6. User-Facing Wording

Use wording like:

> Continuum M1 is an intermediate rework milestone. It certifies the structured
> planning core plus a local QEMU/KVM module set and selected old-main QEMU
> parity rows. See the release certification matrix for exact supported
> combinations.

Avoid wording like:

1. "Continuum rework fully replaces main",
2. "Continuum supports GCP/AWS on this release",
3. "QEMU core",
4. "OpenFaaS application parity is certified",
5. "Full QEMU parity is certified",
6. "M1 is the final/full release",
7. "All shipped YAML examples are release-supported".

## 7. Pre-Tag Gate

Run these checks before tagging:

```bash
scripts/test/run_cloud_static_audit.sh
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke release-artifact-audit
python3 scripts/test/check_release_pretag.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_docs_paths.py
git diff --check
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sh scripts/test/setup_agent_host.sh verify
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_image_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity
```

Keep this order. Updating `/usr/local/bin/continuum-hostctl` is a manual
reviewed operator action and is not part of the agent pre-tag command block.
The live `setup_agent_host.sh verify` check must run after the installed
`continuum-hostctl verify` check because older installed helpers can pass their
own verification while missing the current helper-interface contract.

The wrapper scenarios above are the VM-backed evidence gate for the rows claimed
in section 3. If runtime, runner, verifier, profile, or playbook code changed
after the latest VM-backed evidence snapshot, rerun the affected scenario and
refresh the evidence document before tagging. The pre-tag checker also requires
the current worktree to be clean and every listed release-evidence document to
name a clean VM-evidence source commit. Final release-documentation and release
checker commits may follow that source commit; runtime-affecting changes may
not.

## 8. Suggested Next Milestones

1. Refresh the root-owned helper, prime the local registry cache, and run full
   `P-QEMU-10` OpenFaaS application evidence.
2. Decide exact-resource versus practical-runner claims for full `P-QEMU-10`.
3. Port or explicitly demote GCP/AWS historical rows.
4. Convert the remaining parity matrix into issues grouped by provider and
   module family.
