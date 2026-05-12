# Repository Guidelines

## Project Overview

Continuum automates infrastructure deployment, software installation, and application benchmarking across cloud, edge, and endpoint tiers. The framework is being reworked, so expect file changes and keep new edits scoped.

## Project Structure & Module Organization

The main entry point is `continuum.py`. Core Python modules live in `infrastructure/`, `resource_manager/`, `application/`, `execution_model/`, and `input/configuration/`. Ansible automation is in `playbooks/` and `roles/`, with root-level `ansible.cfg` and `.ansible-lint`. New YAML profiles and experiments live in `configs/`; legacy `.cfg` examples remain under `configuration/`. Tests are in `scripts/test/`. Docs and diagrams are under `docs/`. Avoid broad refactors in `mahimahi/` unless the task targets the bundled network emulator.

## Dev Environment Tips

- `pip3 install -r requirements.txt`: install Python, Ansible, linting, and test dependencies.
- `python3 continuum.py --help`: inspect runtime options.
- `python3 continuum.py configuration/bench_cloud.cfg`: run a legacy example configuration.
- Keep generated logs, VM artifacts, and local temp data out of commits.

## Testing Instructions

- `PYTHONPATH=. python3 -m unittest discover scripts/test`: run the Python test suite.
- `python3 scripts/test/run_tests.py --suite smoke`: run the configured smoke suite from `configs/experiments/`.
- `python3 scripts/test/run_tests.py --config configuration/tests/qemu/01_infraonly-cloud.cfg`: run one end-to-end config.
- `pylint --rcfile=sysconfig/pylintrc <path>` and `yamllint -c sysconfig/yamllint.yml <path>`: run lint checks.

Tests use `unittest` with files named `scripts/test/test_*.py` and classes ending in `Tests`. Add focused tests near the changed code path, especially for configuration parsing, schema validation, selector resolution, and runtime planning. End-to-end tests can create VMs or use cached base images; prefer `--suite smoke` or one `--config`.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and keep lines at or below 100 characters where practical, matching `sysconfig/pylintrc`. Prefer snake_case for Python names and Ansible variables; `.ansible-lint` enforces lowercase variable names without requiring role prefixes. Keep YAML readable and deterministic; `sysconfig/yamllint.yml` allows lines up to 160 characters. Follow existing module boundaries when adding infrastructure providers, resource managers, applications, or benchmark stages.

## PR Instructions

Recent commits use short descriptive subjects such as `fix linting bugs`, `cleanup network emu configs`, and `Update README.md`. Keep subjects concise and focused on one change. Pull requests should explain the behavior change, list commands run, call out affected configs or providers, and link related issues or docs.

## Security Considerations

Do not commit generated logs, local `.tmp` files, credentials, service keys, VM images, or machine-specific IP overrides. Treat cloud and cluster config changes as high impact: document defaults, required secrets, and provider assumptions.
