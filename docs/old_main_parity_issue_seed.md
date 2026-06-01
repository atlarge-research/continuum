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
| `P-QEMU-10` | `ported-unverified` | Decide exact legacy 26-core resource shape versus practical-runner support, resolve forced OpenFaaS image-prefetch access, then run full application evidence. | Full application suite is ported, but its preflight is blocked on Docker daemon access for forced OpenFaaS image prefetch. The exact 26-core legacy shape also needs external QEMU capacity or a runner host with a higher local core budget. Keep unclaimed until both prerequisites or the support claim are resolved, then certify with VM evidence and application metric artifacts. |

## 3. Cloud Provider Parity

These rows remain historical until YAML provider profiles, credential/cost
documentation, and fresh cloud-backed evidence exist.

| Row | Current Status | Issue Seed | Matrix Certification Action |
| --- | --- | --- | --- |
| `P-GCP-01` | `historical` | Keep unclaimed until a GCP cloud-only infrastructure profile exists and cloud evidence passes, or document historical/deprecated disposition. | Keep unclaimed until a GCP environment profile exists and cloud evidence passes, or document historical/deprecated disposition. |
| `P-GCP-02` | `historical` | Decide whether GCP edge-only remains in final parity scope, then port/certify or document as historical. | Port or deprecate this topology. |
| `P-GCP-03` | `historical` | Decide whether GCP endpoint-only remains in final parity scope, then port/certify or document as historical. | Port or deprecate this topology. |
| `P-GCP-04` | `historical` | Port or demote GCP cloud/edge/endpoint infrastructure topology. | Port or deprecate this topology. |
| `P-GCP-05` | `historical` | Port GCP Kubernetes image-classification path and certify with cloud-backed application evidence if kept; otherwise document historical/deprecated disposition. | Keep unclaimed until a provider profile exists and cloud-backed application evidence passes, or document historical/deprecated disposition. |
| `P-GCP-06` | `historical` | Port GCP KubeEdge image-classification path and certify with cloud-backed application evidence if kept; otherwise document historical/deprecated disposition. | Keep unclaimed until a provider profile exists and cloud-backed application evidence passes, or document historical/deprecated disposition. |
| `P-GCP-07` | `historical` | Decide whether GCP Mist remains in final parity scope, then port/certify or document as historical. | Port provider/profile path or deprecate. |
| `P-GCP-08` | `historical` | Decide whether GCP endpoint image/runtime remains in final parity scope, then port/certify or document as historical. | Port provider/profile path or deprecate. |
| `P-GCP-09` | `historical` | Port GCP Kubernetes no-benchmark path and certify with cloud-backed evidence if kept; otherwise document historical/deprecated disposition. | Keep unclaimed until a provider/profile path exists and cloud-backed evidence passes, or document historical/deprecated disposition. |
| `P-GCP-10` | `historical` | Port GCP Kubernetes plus OpenFaaS path and certify with cloud-backed evidence if kept; otherwise document historical/deprecated disposition. | Keep unclaimed until a provider/profile path exists and cloud-backed evidence passes, or document historical/deprecated disposition. |
| `P-AWS-01` | `historical` | Decide whether AWS infra-only support is in final parity scope, then port/certify or document as historical. | Decide whether AWS stays in parity scope; keep unclaimed until profile and cloud evidence exist, or deprecate. |

## 4. Conversion Notes

When converting this seed into issues:

1. keep one issue per matrix row unless multiple rows share the same concrete
   prerequisite,
2. include the row ID in the issue title,
3. copy the certification action from `docs/release_certification_matrix.md`,
4. require fresh VM-backed or cloud-backed evidence before closing a row as
   certified,
5. update the matrix, release notes, and this seed in the same change.
