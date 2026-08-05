# Old-Main Parity Issue Seed

## 1. Purpose

This document is the issue seed for work after the first M1 intermediate
release. It mirrors the non-ready rows in `docs/release_certification_matrix.md`
so they can be converted into issues or a project board without losing the
release boundary.

Rows listed here are not release-supported. Under the current checked contract,
a row leaves this document only after it becomes `certified`. `historical` is a
non-terminal, unresolved disposition and every historical `P-*` row remains in
this seed. Closing an unsupported historical provider without certification
would require a separate atomic change introducing an explicit checked terminal
disposition and updating the matrix checker, certification matrix, and this seed
together; this document does not define that future disposition.

`scripts/test/check_release_matrix.py` treats this document as checked release
planning state: every non-ready `P-*` matrix row must appear here with the same
status, a non-empty issue seed, and an exact copy of the matrix certification
action. Ready rows must be removed, and the conversion notes must preserve the
issue-creation rules needed to keep future parity work evidence-bound.

## 2. QEMU Application Parity

No non-ready QEMU application parity rows remain in this seed. `P-QEMU-10` left
this document after exact retained VM/application evidence certified it in
`docs/release_certification_matrix.md`.

## 3. Cloud Provider Parity

These rows remain historical until YAML provider profiles, credential/cost
documentation, and fresh cloud-backed evidence exist.

Issue conversion should preserve one issue per matrix row unless maintainers
choose an explicit umbrella issue for a shared prerequisite. Group the row
issues by provider and module family:

1. GCP infrastructure topology: `P-GCP-01` through `P-GCP-04`.
2. GCP Kubernetes and observability: `P-GCP-05` and `P-GCP-09`.
3. GCP edge/application module families: `P-GCP-06`, `P-GCP-07`, and
   `P-GCP-08`.
4. GCP OpenFaaS/serverless: `P-GCP-10`.
5. AWS infrastructure topology: `P-AWS-01`.

| Row | Current Status | Issue Seed | Matrix Certification Action |
| --- | --- | --- | --- |
| `P-GCP-01` | `historical` | GCP infrastructure topology issue: decide final scope for cloud-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| `P-GCP-02` | `historical` | GCP infrastructure topology issue: decide final scope for edge-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for edge-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| `P-GCP-03` | `historical` | GCP infrastructure topology issue: decide final scope for endpoint-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for endpoint-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| `P-GCP-04` | `historical` | GCP infrastructure topology issue: decide final scope for cloud/edge/endpoint infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for cloud/edge/endpoint infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| `P-GCP-05` | `historical` | GCP Kubernetes/application issue: decide final scope for Kubernetes image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| `P-GCP-06` | `historical` | GCP edge/application issue: decide final scope for KubeEdge image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for KubeEdge image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| `P-GCP-07` | `historical` | GCP edge/application issue: decide final scope for Mist image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Mist image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| `P-GCP-08` | `historical` | GCP edge/application issue: decide final scope for endpoint image/runtime; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for endpoint image/runtime, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| `P-GCP-09` | `historical` | GCP Kubernetes/observability issue: decide final scope for Kubernetes without benchmark; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes without benchmark, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |
| `P-GCP-10` | `historical` | GCP OpenFaaS/serverless issue: decide final scope for Kubernetes plus OpenFaaS; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add a GCP environment profile for Kubernetes plus OpenFaaS, credential/cost/prerequisite docs, and fresh cloud-backed application evidence. |
| `P-AWS-01` | `historical` | AWS infrastructure topology issue: decide final scope for cloud-only infrastructure; certify only after an AWS environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist. Without certification, keep the row unresolved and in this seed. | Historical and unresolved for M1; keep unclaimed and in `docs/old_main_parity_issue_seed.md`. To certify later, add an AWS environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence. |

## 4. Non-Row Module-Family Follow-Up

These backlog entries do not have `P-*` parity rows, but they should be
converted into issues beside the provider rows so unsupported surfaces do not
turn into implicit claims:

| Module Family | Current Status | Issue Seed |
| --- | --- | --- |
| `baremetal` provider | `ported-unverified` | Decide whether the one-physical-machine topology is a supported release target. Certification needs an explicit YAML config/profile, host prerequisites, host-backed evidence, and documented limitations. Without certification it remains unresolved and unclaimed. |
| `text_translation` | `ported-unverified` | Decide whether to port the MQTT publisher/subscriber application path. Certification needs a supported-orchestrator YAML config with endpoint resources, success/artifact checks, and retained provider-appropriate runtime evidence required by the applicable certification-matrix gate. That evidence may be VM-backed, cloud-backed, or host-backed only where the gate permits it; arbitrary local tests are insufficient. Without certification it remains unresolved and unclaimed. |
| `stress` | `ported-unverified` | Decide whether `stress` remains kubecontrol-only or needs a separate Kata-compatible path. Certification needs scoped YAML, resource/success artifact checks, and retained provider-appropriate runtime evidence required by the applicable certification-matrix gate. That evidence may be VM-backed, cloud-backed, or host-backed only where the gate permits it; arbitrary local tests are insufficient. Without certification it remains unresolved and unclaimed. |
| `mem_usage` | `ported-unverified` | Decide whether `mem_usage` remains kubecontrol-only or needs a separate Kata-compatible path. Certification needs scoped YAML, memory/success artifact checks, and retained provider-appropriate runtime evidence required by the applicable certification-matrix gate. That evidence may be VM-backed, cloud-backed, or host-backed only where the gate permits it; arbitrary local tests are insufficient. Without certification it remains unresolved and unclaimed. |

## 5. Conversion Notes

When converting this seed into issues:

1. keep one issue per matrix row unless multiple rows share the same concrete
   prerequisite,
2. include the row ID in the issue title,
3. copy the certification action from `docs/release_certification_matrix.md`,
4. for the current QEMU/GCP/AWS `P-*` inventory, require fresh VM-backed or
   cloud-backed evidence before closing a row as certified, as specified by the
   applicable certification-matrix gate; use the provider-appropriate gate for
   active non-row applications, which may permit host-backed evidence, and
   never treat arbitrary local tests as sufficient,
5. update the matrix, release notes, and this seed in the same change.

## 6. Nomination Rule

Until a maintainer nominates a concrete target, every row and module in this
seed stays unclaimed and docs-only. Nomination must name the exact scope,
credentials or host access, cost or capacity guardrails, YAML/profile target,
suite and success-detector work, evidence requirements, and documentation
updates.

After nomination, prefer this implementation order:

1. provider infrastructure first: `P-GCP-01`, then `P-GCP-02` through
   `P-GCP-04`, with `P-AWS-01` as a separate infrastructure-only track,
2. GCP software/application rows next: `P-GCP-09`, `P-GCP-05`,
   `P-GCP-06`, `P-GCP-07`, `P-GCP-08`, then `P-GCP-10`,
3. non-row modules after provider disposition: `baremetal`,
   `text_translation`, then `stress` and `mem_usage`.

Do not create support claims from issue conversion alone. Certification still
requires the release matrix to move the exact row or module family to
`certified` with retained provider-appropriate runtime evidence required by the
applicable matrix gate. Arbitrary local tests are insufficient.
