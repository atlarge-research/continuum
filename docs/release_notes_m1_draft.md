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
2. `docs/release_evidence_m1_2026-05-29.md`
3. `docs/release_evidence_qemu_infra_parity_2026-05-29.md`
4. `docs/release_evidence_qemu_k8s_nobench_2026-05-29.md`
5. `docs/release_evidence_qemu_kubeedge_software_2026-05-29.md`
6. `docs/release_evidence_qemu_mist_software_2026-05-29.md`
7. `docs/release_evidence_qemu_endpoint_software_2026-05-29.md`
8. `docs/release_evidence_qemu_openfaas_software_2026-05-29.md`

Before tagging, rerun the commands in section 7. VM-backed evidence may name a
clean runtime source commit that precedes final release-documentation commits,
but no runtime, config, profile, playbook, wrapper, or runner path may change
after that evidence source commit without rerunning the affected wrapper
scenario.

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
| `P-QEMU-09` | Old-main QEMU Kubernetes no-benchmark parity row |
| `P-QEMU-06-SW` | KubeEdge software-only subset of old-main P-QEMU-06 |
| `P-QEMU-07-SW` | Mist software-only subset of old-main P-QEMU-07 |
| `P-QEMU-08-SW` | Endpoint-runtime software-only subset of old-main P-QEMU-08 |
| `P-QEMU-10-SW-LOCAL` | Single-host CPU-capped OpenFaaS software-only subset of old-main P-QEMU-10 |

These rows are certified only for the exact configs, profiles, host context,
runtime targets, and limitations recorded in the evidence documents.

## 4. What This Milestone Does Not Certify

Do not describe this milestone as full old-main parity.

The following rows remain unclaimed:

1. full QEMU application parity rows `P-QEMU-05`, `P-QEMU-06`, `P-QEMU-07`,
   `P-QEMU-08`, and full `P-QEMU-10`,
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
2. Full KubeEdge and Mist application parity rows require a primed local
   registry cache before VM-backed certification can proceed.
3. Forced image-prefetch rows still require Docker daemon access on the
   certification host.
4. Full OpenFaaS application parity also needs a decision on exact legacy
   resource-shape certification or a larger/external QEMU runner.
5. Cloud-provider rows need YAML profiles, credential/cost documentation, and
   cloud-backed evidence before they can be release-supported.
6. The installed host maintenance helper must declare the current
   `HOSTCTL_INTERFACE_VERSION` and expose `prime-registry-cache` before
   cache-backed full application parity rows can be certified through the
   allowlisted host workflow.

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
4. "KubeEdge/Mist/OpenFaaS application parity is certified",
5. "Full QEMU parity is certified",
6. "M1 is the final/full release",
7. "All shipped YAML examples are release-supported".

## 7. Pre-Tag Gate

Run these checks before tagging:

```bash
scripts/test/run_cloud_static_audit.sh
python3 scripts/test/check_release_evidence_artifacts.py
python3 scripts/test/check_release_pretag.py
python3 scripts/test/check_release_claims.py
python3 scripts/test/check_release_matrix.py
python3 scripts/test/check_docs_paths.py
git diff --check
sh scripts/test/setup_agent_host.sh install-hostctl
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl verify
sh scripts/test/setup_agent_host.sh verify
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke operational_regression
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke network_validation
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_infra_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_k8s_nobench_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_kubeedge_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_mist_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_endpoint_software_parity
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke qemu_openfaas_software_parity
```

Keep this order. Refresh the installed helper from the exact source tree before
syncing the dedicated repository. The live `setup_agent_host.sh verify` check
must run after the installed `continuum-hostctl verify` check because older
installed helpers can pass their own verification while missing the current
helper-interface contract.

The wrapper scenarios above are the VM-backed evidence gate for the rows claimed
in section 3. If runtime, runner, verifier, profile, or playbook code changed
after the latest VM-backed evidence snapshot, rerun the affected scenario and
refresh the evidence document before tagging. The pre-tag checker also requires
the current worktree to be clean and every listed release-evidence document to
name a clean VM-evidence source commit. Final release-documentation and release
checker commits may follow that source commit; runtime-affecting changes may
not.

## 8. Suggested Next Milestones

1. Refresh the installed host maintenance helper and prime the local registry
   cache.
2. Certify full `P-QEMU-06` and `P-QEMU-07` application rows after cache
   readiness.
3. Resolve Docker-daemon or registry design for forced-prefetch application rows.
4. Decide exact-resource versus practical-runner claims for full `P-QEMU-10`.
5. Port or explicitly demote GCP/AWS historical rows.
6. Convert the remaining parity matrix into issues grouped by provider and
   module family.
