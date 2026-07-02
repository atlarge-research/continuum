# Old-Main Parity Issue Seed

## 1. Purpose

This document is the issue seed for work after the first M1 intermediate
release. It mirrors the non-ready rows in `docs/release_certification_matrix.md`
so they can be converted into issues or a project board without losing the
release boundary.

Rows listed here are not release-supported. A row leaves this document only
after it becomes `certified` or after maintainers make a final historical or
deprecation decision and the release matrix no longer tracks it as a non-ready
parity row.

`scripts/test/check_release_matrix.py` treats this document as checked release
planning state: every non-ready `P-*` matrix row must appear here with the same
status, a non-empty issue seed, and an exact copy of the matrix certification
action. Ready rows must be removed, and the conversion notes must preserve the
issue-creation rules needed to keep future parity work evidence-bound.

## 2. QEMU Application Parity

These rows are ported or partly ported on the rework stack, but they are not
full old-main parity claims yet.

| Row | Current Status | Issue Seed | Matrix Certification Action |
| --- | --- | --- | --- |
| `P-QEMU-10` | `ported-unverified` | Provide reachable capacity for the exact 26 requested VM cores, or a larger local runner, then rerun the exact OpenFaaS application suite and record retained VM/application evidence. | Full application suite is ported and uses cache-backed image preflight. On 2026-06-02 `prime-registry-cache --check-only --suite qemu_openfaas_image_parity` passed, but the exact 26-core legacy shape still selected external host `matthijs@node3`; the retained run failed before provisioning with `No route to host` in `/mnt/sdc/continuum_smoke/qemu_openfaas_image_parity/.continuum/test_results/test_results_2026-06-02_15-36-18.json`. Keep unclaimed until external QEMU capacity is available or a larger local runner can produce retained VM/application evidence for the exact shape. |

## 3. Cloud Provider Parity

These rows remain historical until YAML provider profiles, credential/cost
documentation, and fresh cloud-backed evidence exist.

| Row | Current Status | Issue Seed | Matrix Certification Action |
| --- | --- | --- | --- |
| `P-GCP-01` | `historical` | Decide final scope for GCP cloud-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |
| `P-GCP-02` | `historical` | Decide final scope for GCP edge-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for edge-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |
| `P-GCP-03` | `historical` | Decide final scope for GCP endpoint-only infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for endpoint-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |
| `P-GCP-04` | `historical` | Decide final scope for GCP cloud/edge/endpoint infrastructure; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for cloud/edge/endpoint infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |
| `P-GCP-05` | `historical` | Decide final scope for GCP Kubernetes image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for Kubernetes image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence, or record a final historical/deprecated disposition. |
| `P-GCP-06` | `historical` | Decide final scope for GCP KubeEdge image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for KubeEdge image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence, or record a final historical/deprecated disposition. |
| `P-GCP-07` | `historical` | Decide final scope for GCP Mist image-classification; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for Mist image-classification, credential/cost/prerequisite docs, and fresh cloud-backed application evidence, or record a final historical/deprecated disposition. |
| `P-GCP-08` | `historical` | Decide final scope for GCP endpoint image/runtime; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for endpoint image/runtime, credential/cost/prerequisite docs, and fresh cloud-backed application evidence, or record a final historical/deprecated disposition. |
| `P-GCP-09` | `historical` | Decide final scope for GCP Kubernetes without benchmark; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for Kubernetes without benchmark, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |
| `P-GCP-10` | `historical` | Decide final scope for GCP Kubernetes plus OpenFaaS; certify only after a GCP environment profile, credential/cost/prerequisite docs, and fresh cloud-backed application evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add a GCP environment profile for Kubernetes plus OpenFaaS, credential/cost/prerequisite docs, and fresh cloud-backed application evidence, or record a final historical/deprecated disposition. |
| `P-AWS-01` | `historical` | Decide final scope for AWS cloud-only infrastructure; certify only after an AWS environment profile, credential/cost/prerequisite docs, and fresh cloud-backed evidence exist, or record historical/deprecated disposition. | Historical for M1; keep unclaimed. To certify later, add an AWS environment profile for cloud-only infrastructure, credential/cost/prerequisite docs, and fresh cloud-backed evidence, or record a final historical/deprecated disposition. |

## 4. Conversion Notes

When converting this seed into issues:

1. keep one issue per matrix row unless multiple rows share the same concrete
   prerequisite,
2. include the row ID in the issue title,
3. copy the certification action from `docs/release_certification_matrix.md`,
4. require fresh VM-backed or cloud-backed evidence before closing a row as
   certified,
5. update the matrix, release notes, and this seed in the same change.
