---
name: continuum-test-workflows
description: Use when choosing, running or updating Continuum tests, scripts/test commands, suite discovery, documentation checks, unittest/pytest or YAML/Ansible lint, or distinguishing cloud-safe and VM-backed validation.
---

# Continuum Test Workflows

Read `AGENTS.md`, `scripts/test/test_config.json` and
`scripts/test/run_tests.py`. For broad static checks also inspect
`scripts/test/run_cloud_static_audit.sh`; its current required flags are
authoritative. Use continuum-cloud-static-audit for audit work.

## Cloud-safe commands

```bash
scripts/test/run_cloud_static_audit.sh
env PYTHONPATH=. python3 -m unittest discover scripts/test/unit
env PYTHONPATH=. python3 -m unittest discover scripts/test/e2e
env PYTHONPATH=. python3 -m unittest discover scripts/test
python3 scripts/test/run_tests.py --list-suites
python3 scripts/test/run_tests.py --check-prereqs --suite smoke
```

Required audit gates include compile, all three shell syntax checks,
whitespace, unit/e2e/combined unittest, docs paths, release claims/matrix and
suite catalog. Pytest, artifact/pre-tag audits, lint baselines, debt scan and
prerequisite checks are informational in the canonical audit, not silently
required or runtime evidence. Run applicable changed-file lint explicitly.
Use a Python version supported by the static checker/test code; the historical
physical-runner venv may be older and must not be silently upgraded.

## VM-backed work

Actually running `run_tests.py --suite` or `--config` can create VMs and
modify retained state. Do not do this from cloud-only/sandbox contexts.
For explicitly authorized physical-host work use continuum-smoke-host-runner:

```bash
sh scripts/test/setup_agent_host.sh verify
sh scripts/test/run_smoke_host.sh operational_regression
```

This is normal-user execution from the live checkout, not the retired
separate smoke account or installed hostctl/wrapper. No sudo repo scripts,
account creation, dedicated-repo sync or automated ownership repair.
Preserve failed artifacts and respect the approved scenario/gates.
Suite listing and parser acceptance do not certify runtime support.

Tests live in `scripts/test/unit/`, `scripts/test/e2e/` and shared
`scripts/test/support/`. Expected negative-path ERROR logs are not failures;
read the final summary. Mahimahi is fetched into the run's
`<base_path>/.continuum/mahimahi`, never a repo-root vendored checkout.

Before a reviewed local commit, report exact files/commands, pass/fail,
deliberately skipped VM validation, remaining dirty files and limitations.
Keep generated logs, images, private evidence and credentials out of Git.
