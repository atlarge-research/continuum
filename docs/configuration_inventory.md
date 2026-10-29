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
| Defaults | Schema validation fills run booleans with false, current registry_refresh with missing, nonzero-count VM specs with 1 core/1 GiB/quota 1, storage limits with zero, and network defaults with disabled/4g/empty overrides. Module-option validation then resolves provider/software/benchmark defaults into canonical domains. Keep raw declarations separate from normalized facts; missing legacy cfg values do not inherit these defaults. |
| Clusters | Experiments declare cluster IDs, tiers and VM counts/specs. VM IDs are derived in sorted cluster-ID order. Runtime projection aggregates by tier and rejects inconsistent specs within a tier (`input/configuration/legacy_projection.py`); this is not arbitrary heterogeneous multi-cluster runtime support. |
| Selectors | Exact-match predicates within a clause are ANDed; the allowed software any_of form unions clauses. Canonical selector IDs, sorted VM IDs and scope identities are derived/reconciled. Empty or invalid assignments fail; profiles using cloud-1/endpoint-1 are not universally composable with renamed clusters. Benchmark assignment retains the supported single match form. See `input/configuration/selector_scope.py` and `input/configuration/selector_assignment_validation.py`. |
| Run targets | Runtime order is infrastructure → software → application, independent of list order. Fresh infrastructure plus application requires software. Skipping infrastructure is QEMU-only and requires compatible retained state and SSH reachability. Infrastructure-only prepare_for_resume is explicit intent, not blanket future-phase certification. See `input/configuration/runtime_phase_targets.py` and `continuum.py`. |
| Benchmark | Application execution requires exactly one executable pipeline stage; ordered multi-stage execution is rejected by `input/configuration/benchmark_domain_validation.py`. Commented template alternatives do not prove that enabling both is supported. Several bench_* examples currently request infrastructure/software only; names do not prove application execution. |
| Host placement | All seven shipped environment profiles use QEMU and declare no external physical machines. The normal runner can supply node3 and a physical-core limit; capacity/CPU pinning determine placement. The exact OpenFaaS input requests 26 vCPUs; its distinct 20-vCPU local variant is not a substitute for the required multi-host run. |
| Cache, retention and resume | The QEMU cache is single-slot; delete_on_exit requests VM teardown, not blanket artifact deletion. A fresh same-user QEMU workflow may replace retained same-user domains across base paths. Resume v1 remains same revision/base path/topology/software; revision equality is an operator precondition, not Git-tracking machinery. Changed-parameter sweeps remain candidate-only; fresh runtime/manual acceptance is open. |

The refreshed checkpoint below records registry_refresh missing/all, default
missing, without aliases. The separate bounded cache repair covers common/active
included roles, copied inputs, consumed values and actual preload identities;
see `docs/qemu_cache_contract.md`. Neither static inventory nor cache source tests
prove fresh runtime acceptance. The previous v2/v3/v4/v5/v6/v7/v8/v9/v10/v11 inventories
remain preserved unchanged as historical evidence, not current source-hash claims.

## Frozen file coverage

Private evidence freezes input content at clean source
`b7c51977cd165820082f720624f8439a033b5f76`, containing the reviewed Kata
zero-complete-trace retry repair and regressions, endpoint metric-field parser
repair, full-body registry-manifest parser
repair, foundation observability-readiness repair, packet C's schema-envelope/documentation corrections
and packet B's unchanged Job-reuse
repair at `aa7a438ee914cc60a0902ec1908be9c57b89982f`. Each row records source SHA, historical
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
| Test/support carriers | 45 | Every non-__init__ Python file under scripts/test/unit, e2e and support, conservatively included. Literal config markers detected in 26; this heuristic neither resolves all dynamic fixtures nor claims every carrier contains configuration. |
| Test metadata | 3 | `scripts/test/test_config.json`, `scripts/test/coverage_manifest.json`, `scripts/test/test_manifest.json.example`; catalog/coverage/manifest metadata, not standalone experiments. |
| Total inventory rows | 358 | 310 inputs plus 48 fixture/support/metadata sources; no duplicate or unaccounted eligible path. |
| Explicit exclusions | 135 | Per-path hashed ledger of other tracked YAML/YML/CFG: Ansible/runtime/tool implementation assets, including `ansible.cfg`, not user experiment/profile inputs. No exclusion hash changed since v9. v9 recorded the observability-role tasks change since v8; v7 recorded the Job-role defaults/tasks changes since v6. v2's 136 paths differ only by the reviewed diagnostic-playbook deletion. |

The four templates are experiment, environment, software and legacy cfg.
Each allowed classification has exactly one current disposition:

| Classification | Rows | Current disposition |
| --- | ---: | --- |
| User example | 24 | Retain shipped input; final runtime acceptance open. Includes reusable non-template profiles, not standalone execution claims. |
| Reproduction path | 4 | Retain and validate exact R03/R04 YAML and historical cfg counterparts; no wider figure equivalence inferred. |
| Template | 4 | Retain; validate at the applicable schema/composition level. |
| Historical input | 235 | Preserve pending historical-scope confirmation. |
| Test-only fixture | 91 | Retain test input/support carrier, including shipped smoke/parity inputs and historical provider tests. Shipped status is independent of classification. |

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
configuration-inventory-v12. Manifest SHA-256:
`10dd4d8484b75c56964f870e423942ebeb46cebaa63e654fbe78e61398e7e867`.
The 2,131,065-byte inventory JSON SHA-256 is
`673d832c1e278e18eb40d59607b15cd8064a9f6ec1b070a10a3cf4d274041c18`.
The manifest binds inventory/summary; tooling/plan are alongside them. All six
copied files were verified byte-for-byte with private 0700/0600 permissions.
The unchanged extractor and its four focused checks are byte-identical to v2–v11.
All ten complete previous directories and their eight v4–v11 receipts remain unchanged:
68 files were hash-verified before/after generation and preservation, with every
historical manifest's members checked against exact bytes and sizes.
Historical v11 remains bound to clean
`3812449c0d04a3b2c9fe189e2e9b5bff11bf9409`, containing the endpoint-metric parser
repair. Its manifest SHA-256 is
`0631c0697efdba9af16332787ee7bfa0e218bf00c71369408c75605cf32449d6`;
its preserved 2,129,399-byte inventory JSON SHA-256 is
`a99fde2043bbeb1fa4826e24fe583b80b217dceebe601d8186e9bde2ba5b2278`.
That refresh verified all 61 v2–v10 snapshot/receipt files unchanged.
Historical v10 remains bound to clean
`ba5e50f05c22a5118a83ea1412aaf7141c15df60`, containing the full-body registry-manifest
parser repair. Its manifest SHA-256 is
`cb95a2daeee50b00295d2a728d150d002b56ad40d660e2a6dd2028c08f8e2304`;
its 2,128,885-byte inventory JSON SHA-256 is
`6ae68286372c3ef731bef8607116c4d756e44aa3c707ddabe24debc82ad03834`.
Historical v9 remains bound to clean
`2f969bb34de37060dc19bba7cc50d9b06e16136e`, containing the foundation
observability-readiness repair. Its manifest SHA-256 is
`0df51b8a426dee605342064b5ab26f5ed3fb1a211da74e7fefa6ee774e3bd59c`.
Its 2,128,743-byte inventory JSON SHA-256 is
`39bd030f55439dba7d549bf8d6b29164860f5885e44575852be625c30e3607c1`.
The v8 manifest is
`bdc1f2a0747ef7c4fc8c436b0693ee25b279d916786fceb301d58ba7cc42abc0`;
its preserved 2,128,231-byte inventory JSON SHA-256 is
`9559b83be067917dfa82c9a83aeb2f08fbab924aca32207ff7eb09760edd3ebd`.
The v7 manifest is
`fe066662cee2f9a5f17d542b35ff976e45bd0ad5e85a5baabf88d5b7505d2d6f`;
its preserved 2,127,869-byte inventory JSON SHA-256 is
`9c78f11c97b7b616584209b9fa0e47ec23ac7706bd0d8d055ea87dbc366dbf76`.
The v6 manifest is
`18e4faa11ab9a420f0920f1924c9be7d1c825e252e848177a8061031f932c437`;
its preserved 2,122,856-byte inventory JSON SHA-256 is
`9fa1ddf7738f8981a358defa65d024bfad02c4bea056ad2559f2754d774dbf21`.
The v5 manifest is
`b037c3c1144f84c3161a450daf214d144b9e0d526aec4988e9350f3da5ea4f20`;
its preserved 2,122,643-byte inventory JSON SHA-256 is
`0d11ea6fcda0cc9eaa8e169a7eb509b087424b3db26922e20ec0952538da88fb`.
The v4 manifest is
`ef1de711d67df03846ed8d10024fb73e947da856eb6fc5aa67e9ef1baa127bf0`;
v3's manifest SHA-256 is
`17e49b35396245be0006f5c9ad99de4bb67dc02f1b3578d12f7b7497b0503edb`, and v2's is
`be7c5ab2c5fc2904b79ef4560623f48bce68e066e66bbf1828b23a3d11972a68`.
The historical v7 refresh added `scripts/test/unit/test_kubernetes_job_reuse.py`;
the changed existing rows were `scripts/test/unit/test_application_runtime_helpers.py`
and `scripts/test/unit/test_role_contracts.py`. The two changed exclusions were
`roles/application/k8s_job_deploy/defaults/main.yml` and
`roles/application/k8s_job_deploy/tasks/main.yml`. No row or exclusion was removed.
Those changes bind the reviewed Kubernetes Job-reuse repair and its regressions.
The v8 refresh changed five existing rows: `scripts/test/e2e/test_e2e_test_utils.py`,
`scripts/test/support/e2e_utils.py`, `scripts/test/unit/test_continuum_runtime.py`,
`scripts/test/unit/test_resume_contract.py` and `scripts/test/unit/test_yaml_parser.py`.
Their AST fixture facts include the five new negative-schema regression methods;
the classifier and its heuristic limits are unchanged. That refresh added or removed
no row and changed no user-input bytes or exclusion hashes. The Docker-role hash
remains as recorded in v6. The historical v9 refresh changed one existing carrier row,
`scripts/test/unit/test_role_contracts.py`, adding seven inert observability-policy
test methods. Its current AST fixture facts and those of all 45 carriers were
verified. Only `roles/resource_manager/k8s_observability/tasks/main.yml` changed
among exclusions; no input, row or exclusion path was added or removed. This
recorded the reviewed source repair, not actual service readiness or a runtime pass.
The historical v10 refresh changed only the existing
`scripts/test/unit/test_continuum_runtime.py` carrier row. Its source hash and static
fixture facts include two new manifest regressions:
`test_qemu_preload_accepts_multiline_manifest_from_machine_output` and
`test_manifest_identity_consumes_complete_json_body`. No row/input/exclusion path
was added or removed; no input bytes, exclusion hash, classification or disposition
changed. The product parser's hash is separately bound in the generation receipt
and reviewed source commit; product Python is not an inventory carrier/exclusion.
The private configuration-inventory-v10-generation.json receipt (SHA-256
`c813e61a74f79b334fd9990eabebf29737e2031c809898073ed8dbe8c61c8e92`)
records isolated Python 3.12.7 with optimization disabled, the clean source revision
and complete verification, preserving the extractor's built-in assertions. The
historical configuration-inventory-v9-generation.json receipt remains unchanged.

The historical v11 refresh changed only the existing
`scripts/test/unit/test_application_publishers.py` carrier row: its source hash
and AST fixture facts include seven new endpoint-metric tests; two new test
helpers were also verified by AST comparison. No row/input/exclusion path, input
bytes, exclusion hash, classification or disposition changed. The product parser
is separately hash-bound in the reviewed source commit and generation receipt; it is not an inventory carrier
or exclusion. The private configuration-inventory-v11-generation.json receipt
SHA-256 is `7ba6171c48b7272017c5783982c866bdd548aa3cf17783b387ec5a5d69d81090`.
It records clean source `3812449`, isolated Python 3.12.7 with optimization disabled
and the complete verification. The v10 receipt and all older evidence are unchanged.

The v12 refresh changes only the existing
`scripts/test/unit/test_resource_manager_plans.py` carrier row: its source hash
and AST fixture facts include five new Kata retry/parser regressions and one new
test helper, `_kata_trace_config`. No row/input/exclusion path, input bytes,
exclusion hash, classification or disposition changed. The publisher carrier is
unchanged from v11. Product Kata Python is separately hash-bound in the reviewed
source commit and generation receipt, outside inventory carriers/exclusions.
The private configuration-inventory-v12-generation.json receipt SHA-256 is
`43163986e6f3509b2329b0235bb43bbdacf83791b4af9398d91e26e4fa61b685`.
It records clean source `b7c51977cd165820082f720624f8439a033b5f76`, isolated
Python 3.12.7 with optimization disabled and the complete verification. The v11
receipt and all older evidence remain unchanged.

Source hashes were checked for all 358 rows and 135 exclusions; raw-declaration
equality covered all 259 cfg and 51 YAML inputs after redaction. All 30 experiment
normalizations use registry_refresh missing/all without the retired run key.
Their normalized facts remain equal to v11; all 45 carriers' AST fixture facts were
verified. All four extractor checks passed.
Generation used the existing cloud-safe mocked-socket parser pattern, not VM,
research-script or runtime-entry-point execution. Expected successful runtime
outputs are experiment_lock.yaml, phase state.json, logs and the configured
benchmark/network artifacts; profiles alone produce none.

Refresh affected rows and the exact source/evidence binding after schema, example
or test changes. This refresh updates one existing carrier and no exclusion;
the user input set is unchanged.
The checkpoint must not be relabelled as a later final candidate
without rechecking those hashes and the exact source/evidence binding.
