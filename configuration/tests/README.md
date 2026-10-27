# Legacy Test Configuration Inventory

This directory preserves historical `.cfg` inputs, not an automatically
supported runtime suite. Approved scope is
`docs/rework_milestone_release_plan.md`; factual statuses/evidence and mappings
are in `docs/release_certification_matrix.md`. Do not delete candidates before
the complete reproduction/configuration inventory and final user confirmation.

Active experiments and profiles are tracked under `configs/experiments/` and
`configs/profiles/`. Every tracked `.yaml`, including explicitly classified
templates, is shipped inventory; parser acceptance is not runtime support.
Test-only fixtures are separate. The three-document YAML model remains.

## Cloud-safe discovery and tests

```bash
python3 scripts/test/run_tests.py --list-suites
python3 scripts/test/run_tests.py --check-prereqs --suite smoke
env PYTHONPATH=. python3 -m unittest discover scripts/test
scripts/test/run_cloud_static_audit.sh
```

Listing/prerequisite checks do not provision VMs. Actually invoking a suite or
configuration can create VMs and mutate caches; do not run it from a cloud-only
sandbox. No broad all-config loop is an approved pre-main acceptance matrix.

## Authorized physical-host validation

Use the normal-user workflow and retained-root/venv exports in
`docs/smoke_runner_isolation.md`, from the live reviewed checkout:

```bash
sh scripts/test/setup_agent_host.sh verify
sh scripts/test/run_smoke_host.sh operational_regression
```

No separate smoke account, installed wrapper, privileged repository script or
dedicated-repo sync is required. Run only the exact active packet's authorized
scenario. Configured suites remain in `scripts/test/test_config.json`; the
scenario runner is `scripts/test/run_smoke_host.sh`. Lower-level overrides and
suite internals live in `scripts/test/run_tests.py`, not historical shell loops.

## Results and failures

The normal-user runner puts results under each child
`<base_path>/.continuum/test_results/`, including summary JSON and sibling
per-entry stdout, stderr and metadata artifacts. `operational_regression` has
no retained root; inspect its four real children as documented in the host
workflow. Lock/state contracts, structured benchmark/network artifacts,
readiness and cleanup assertions matter in addition to exit code and SSH hints.

Keep failed state and complete outputs before diagnosis or approved pruning.
Use `docs/vm_debugging_runbook.md` for direct artifact/state/SSH inspection.
Do not retry blindly or change ownership automatically. QEMU owns cache validation
and rebuild decisions on each physical owner/profile slot. The obsolete runner
flags `--rebuild-base-images` and `--use-cache`, and test-config keys
`base_image_rebuild_frequency`, `rebuild_base_images` and `use_cache`, are rejected.
The historical result field `base_images_rebuilt` remains empty; it is not evidence
of runtime cache reuse or rebuilding.
