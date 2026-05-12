---
name: continuum-test-workflows
description: Use when choosing, running, or updating Continuum tests, static checks, test scripts under scripts/test, run_tests.py suites, docs path checks, unittest/pytest/yamllint/ansible-lint commands, or deciding whether a test is cloud-safe versus VM-backed.
---

# Continuum Test Workflows

Use this skill before running or changing Continuum's test machinery. Continuum
has both cloud-safe checks and VM-backed suites; choosing the wrong one can
start QEMU/libvirt work or mutate retained test state.

## First Read

1. `AGENTS.md`
2. `scripts/test/test_config.json`
3. `scripts/test/run_tests.py`
4. `scripts/test/run_cloud_static_audit.sh` when doing cloud-safe verification
5. `scripts/test/run_smoke_host.sh` and `scripts/test/setup_agent_host.sh` only
   when the task is explicitly about host-backed smoke execution

## Default Safe Verification

For broad cloud-safe verification, prefer:

```bash
scripts/test/run_cloud_static_audit.sh
```

It runs required gates for compile, unittest discovery, docs-path references,
and suite catalog listing. It also records informational checks such as pytest,
TODO/FIXME inventory, yamllint, ansible-lint, and suite prerequisite checks.
Reports are generated under `logs/cloud_static_audit/`; do not commit generated
reports unless explicitly asked.

For focused checks, use the smallest command that covers the touched surface:

```bash
env PYTHONPATH=. python3 -m unittest discover scripts/test
env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers
python3 -m py_compile path/to/file.py
yamllint -c sysconfig/yamllint.yml path/to/file.yml
env XDG_CACHE_HOME=/tmp/continuum-xdg-cache \
  ANSIBLE_LOCAL_TEMP=/tmp/continuum-ansible-local \
  ANSIBLE_REMOTE_TEMP=/tmp/continuum-ansible-remote \
  ansible-lint -c .ansible-lint path/to/playbook.yml
```

`pytest -q scripts/test` is useful as an informational mirror of unittest
coverage. Unittest discovery is the required Python test gate unless the user
asks for something narrower.

## run_tests.py

`scripts/test/run_tests.py` is the VM-backed suite runner. Safe discovery and
preflight commands are:

```bash
python3 scripts/test/run_tests.py --list-suites
python3 scripts/test/run_tests.py --check-prereqs --suite smoke
python3 scripts/test/run_tests.py --check-prereqs --suite benchmark_smoke
python3 scripts/test/run_tests.py --check-prereqs --suite network_validation
```

Running a suite or config can create VMs and mutate cached base images:

```bash
python3 scripts/test/run_tests.py --suite smoke
python3 scripts/test/run_tests.py --config configs/experiments/smoke/infra_one_vm.yaml
```

Configs with `_mahimahi` wireless presets also fetch the external
`continuum-modded-mahimahi` repository through the Mahimahi Ansible role and
cache it under `<base_path>/.continuum/mahimahi`. Do not rely on or create a
repo-root `mahimahi/` checkout for tests.

Do not run those directly from a cloud/sandboxed agent. For the dedicated local
host path, use the `continuum-smoke-host-runner` skill and the installed wrapper.

## Test Script Map

- `scripts/test/check_docs_paths.py`: cloud-safe docs reference check.
- `scripts/test/run_cloud_static_audit.sh`: canonical cloud-safe audit.
- `scripts/test/run_tests.py`: suite/config runner; VM-backed except for
  `--list-suites` and `--check-prereqs`.
- `scripts/test/setup_agent_host.sh`: host bootstrap and maintenance wrapper
  generator; use the host-runner skill.
- `scripts/test/run_smoke_host.sh`: installed-wrapper target for retained smoke
  scenarios; use the host-runner skill.
- `scripts/test/verify_network_profiles.py`: validates generated netperf
  results under `logs/network_validation/`; it does not create VMs itself.
- `scripts/test/test_*.py`: unit/regression tests; run through unittest with
  `PYTHONPATH=.`.

## Interpreting Results

Negative-path unit tests intentionally log `ERROR:root:` lines. Trust the test
runner summary (`OK`, `FAILED`, or pytest counts) over those expected logs.

The cloud static audit's required gates are blockers. Informational yamllint or
ansible-lint findings should be fixed when they are caused by the current
change, but old baseline findings are not automatically blockers.

## Commit Hygiene

Before proposing a commit, report:

1. exact files in the proposed group,
2. exact commands run,
3. whether any VM-backed checks were skipped,
4. remaining dirty files that are outside the proposed group.
