# Major Function Test Coverage Audit

## Purpose

This is the tracked Phase-F audit for major runtime, parser, planner, infrastructure,
application, and e2e-runner functions.

The executable source of truth is `scripts/test/coverage_manifest.json`.
`scripts/test/unit/test_coverage_manifest.py` validates that:

1. every audited source file exists,
2. every listed major function still exists in that source file,
3. every referenced test file exists,
4. every audited runtime/parser/planner/infrastructure surface has unit coverage,
5. every entry records both success-path and fail-fast/error-path intent.

## Current Coverage Shape

The audit covers these active major surfaces:

1. YAML loading, profile composition, schema validation, domain validation, selector/scope handling,
   module contracts, runtime option validation, image requirements, config access, lock writing,
   and resume-contract integrity.
2. Runtime state persistence, QEMU base-image integrity, bridge/gateway discovery, Ansible
   inventory/group-vars generation, network validation artifacts, resource-manager planning,
   and application runtime helpers.
3. E2E runner suite selection, prerequisite validation, success detection, artifact validation,
   result persistence, and failure classification.

The test layout is now explicit:

1. `scripts/test/unit/` contains unit and local regression tests.
2. `scripts/test/e2e/` contains local e2e-runner and operational-evidence regression tests.
3. `scripts/test/support/` contains shared helper modules that should not be discovered as tests.

## Maintenance Rule

When a future change adds or materially changes a major parser/runtime/planner/infrastructure
function, update `scripts/test/coverage_manifest.json` in the same commit as the tests. If the
function is intentionally not unit-testable, the manifest must point to the narrowest local
regression test that exercises the behavior and explain the fail-fast/error scenario in the
`failure` field.
