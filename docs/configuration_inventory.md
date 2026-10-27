# Configuration inventory and structure review

This factual review applies the approved policy in
`docs/rework_milestone_release_plan.md`. It does not change the schema, nominate
additional paper experiments or certify runtime support. Candidate research scope
is separate in `docs/reproduction_inventory.md`; factual certification remains in
`docs/release_certification_matrix.md`.

## Three-document review

Retain experiment/environment/software composition. Experiments own topology,
run intent and benchmark; environment profiles own provider/host settings; software
profiles own module instances and assignments. No inspected runtime evidence
requires merging or adding documents.

| Concern | Current behavior and bounded conclusion |
| --- | --- |
| Composition and resolution | `input/configuration/profile_composition.py` loads exactly one environment and one software profile. `input/configuration/yaml_io.py` tries an existing absolute reference, experiment-relative references (literal, .yaml, .yml), repository-relative references (same suffix order), the named repository profile and finally the named home-directory profile. First existing file wins. This is file resolution, not layered override/deep-merge semantics; record the selected source paths/lock. |
| Defaults | Schema validation fills run booleans with false, current image_prefetch with off, nonzero-count VM specs with 1 core/1 GiB/quota 1, storage limits with zero, and network defaults with disabled/4g/empty overrides. Module-option validation then resolves provider/software/benchmark defaults into canonical domains. Keep raw declarations separate from normalized facts; missing legacy cfg values do not inherit these defaults. |
| Clusters | Experiments declare cluster IDs, tiers and VM counts/specs. VM IDs are derived in sorted cluster-ID order. Runtime projection aggregates by tier and rejects inconsistent specs within a tier (`input/configuration/legacy_projection.py`); this is not arbitrary heterogeneous multi-cluster runtime support. |
| Selectors | Exact-match predicates within a clause are ANDed; the allowed software any_of form unions clauses. Canonical selector IDs, sorted VM IDs and scope identities are derived/reconciled. Empty or invalid assignments fail; profiles using cloud-1/endpoint-1 are not universally composable with renamed clusters. Benchmark assignment retains the supported single match form. See `input/configuration/selector_scope.py` and `input/configuration/selector_assignment_validation.py`. |
| Run targets | Runtime order is infrastructure → software → application, independent of list order. Fresh infrastructure plus application requires software. Skipping infrastructure is QEMU-only and requires compatible retained state and SSH reachability. Infrastructure-only prepare_for_resume is explicit intent, not blanket future-phase certification. See `input/configuration/runtime_phase_targets.py` and `continuum.py`. |
| Benchmark | Application execution requires exactly one executable pipeline stage; ordered multi-stage execution is rejected by `input/configuration/benchmark_domain_validation.py`. Commented template alternatives do not prove that enabling both is supported. Several bench_* examples currently request infrastructure/software only; names do not prove application execution. |
| Host placement | All seven shipped environment profiles use QEMU and declare no external physical machines. The normal runner can supply node3 and a physical-core limit; capacity/CPU pinning determine placement. The exact OpenFaaS input requests 26 vCPUs; its distinct 20-vCPU local variant is not a substitute for the required multi-host run. |
| Cache, retention and resume | The QEMU cache is single-slot; delete_on_exit requests VM teardown, not blanket artifact deletion. A fresh same-user QEMU workflow may replace retained same-user domains across base paths. Resume v1 remains same revision/base path/topology/software; revision equality is an operator precondition, not Git-tracking machinery. Changed-parameter sweeps remain candidate-only; fresh runtime/manual acceptance is open. |

The approved registry_refresh missing/all hard cut is a separate atomic packet.
At this checkpoint the schema still uses image_prefetch off/on. The common
base-install fingerprint gap found during cache review is also separate;
inventory completion does not repair it.

## Frozen file coverage

Private evidence freezes input content at clean source
`b22cadc072d14ff24111189cc31cdc19890baf9b`. Each row records source SHA, historical
workflow, provider/hosts, resources, multi-host triggers, phases, software,
benchmark, cache/cleanup/retention/resume, outputs, support, one classification
and one current disposition. Credential-sensitive derived values are redacted;
key presence and raw-text empty/nonempty status remain, not credential validity.

| Coverage set | Files | Interpretation |
| --- | ---: | --- |
| Structured experiments | 30 | Official parser/module-option/planner construction passes with host IP mocked; no VM execution. |
| Environment profiles | 7 | Standalone schema validation passes; topology/workflow require an experiment. |
| Software profiles | 14 | Standalone schema validation passes; assignment/resource/module-option compatibility requires composition. |
| Legacy cfg inputs | 259 | INI declarations inventoried; active entry point rejects cfg. The old converter emits a retired schema, not current clusters/modules/pipeline. |
| Test/support carriers | 44 | Every non-__init__ Python file under scripts/test/unit, e2e and support, conservatively included. Literal config markers detected in 25; this heuristic neither resolves all dynamic fixtures nor claims every carrier contains configuration. |
| Test metadata | 3 | `scripts/test/test_config.json`, `scripts/test/coverage_manifest.json`, `scripts/test/test_manifest.json.example`; catalog/coverage/manifest metadata, not standalone experiments. |
| Total inventory rows | 357 | 310 inputs plus 47 fixture/support/metadata sources; no duplicate or unaccounted eligible path. |
| Explicit exclusions | 136 | Per-path hashed ledger of other tracked YAML/YML/CFG: Ansible/runtime/tool implementation assets, including `ansible.cfg`, not user experiment/profile inputs. |

The four templates are experiment, environment, software and legacy cfg.
Each allowed classification has exactly one current disposition:

| Classification | Rows | Current disposition |
| --- | ---: | --- |
| User example | 24 | Retain shipped input; final runtime acceptance open. Includes reusable non-template profiles, not standalone execution claims. |
| Reproduction path | 4 | Retain and validate exact R03/R04 YAML and historical cfg counterparts; no wider figure equivalence inferred. |
| Template | 4 | Retain; validate at the applicable schema/composition level. |
| Historical input | 235 | Preserve pending historical-scope confirmation. |
| Test-only fixture | 90 | Retain test input/support carrier, including shipped smoke/parity inputs and historical provider tests. Shipped status is independent of classification. |

All 257 legacy inputs other than the two nominated exact cfg counterparts retain
final_disposition_pending=true, including historical templates and provider tests.
One preservation/current disposition per file is not an approved final
disposition. The configuration gate remains open for historical scope, required
structured equivalents and fresh runtime acceptance. No file was removed and no
cloud execution/spending was authorized.

## Preserved evidence and refresh requirement

The generated inventory, summary, extractor, four focused extractor checks and
reviewed plan are private, outside Git, under the existing migration evidence root
`/mnt/sdc/continuum_migration_evidence/20261027T173000Z-node4`, in
configuration-inventory-v2. Manifest SHA-256:
`be7c5ab2c5fc2904b79ef4560623f48bce68e066e66bbf1828b23a3d11972a68`.
The 2,118,803-byte inventory JSON SHA-256 is
`fe369d27d108433ba6b05b82a6bb57bf03bbe1828aa218c28d38b2f09de9b631`.
The manifest binds inventory/summary; tooling/plan are alongside them. All six
copied files were verified byte-for-byte with private 0700/0600 permissions.

Source hashes were checked for all 357 rows; raw-declaration equality covered all
259 cfg and 51 YAML inputs after redaction. All four extractor checks passed.
Generation used the existing cloud-safe mocked-socket parser pattern, not VM,
research-script or runtime-entry-point execution. Expected successful runtime
outputs are experiment_lock.yaml, phase state.json, logs and the configured
benchmark/network artifacts; profiles alone produce none.

Refresh affected rows and the exact source/evidence binding after schema, example
or test changes, including registry terminology. This checkpoint must not be
relabelled as an inventory of a later final candidate.
