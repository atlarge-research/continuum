---
name: continuum-cloud-static-audit
description: Use this repo-local skill when working on Continuum cloud-safe audit tasks, static checks, planning-doc drift checks, or follow-up work from scripts/test/run_cloud_static_audit.sh.
---

# Continuum Cloud Static Audit

Use this skill for Continuum audit work that must be safe in a cloud or sandboxed agent
environment where the full VM-backed framework cannot run.

## Workflow

1. Read `AGENTS.md` first.
2. For general test selection, also use `continuum-test-workflows`. For VM-backed
   host runner work, use `continuum-smoke-host-runner` instead of this skill.
3. Inspect the audit entrypoints:
   - `scripts/test/run_cloud_static_audit.sh`
   - `scripts/test/check_docs_paths.py`
   - `scripts/test/test_check_docs_paths.py`
4. Run:

   ```bash
   scripts/test/run_cloud_static_audit.sh
   ```

5. Inspect the newest report under `logs/cloud_static_audit/`.
6. Treat required gates as blockers and informational checks as evidence unless the user asks
   to burn down a specific baseline.

## How To Interpret Results

- Required gates are `py_compile`, `unittest discover`, docs path reference checking, and suite
  catalog listing.
- `pytest`, TODO/FIXME scan, `yamllint`, `ansible-lint`, and suite prerequisite checks are
  informational by default.
- TODO/FIXME matches are debt inventory, not pass/fail status.
- Generated reports belong under ignored `logs/cloud_static_audit/`, not `docs/`.
- Do not commit dated generated reports unless the user explicitly asks for an audit snapshot.

## Guardrails

- Do not run VM-backed Continuum scenarios from this skill.
- Do not treat the old `docs/cloud_audit_report_2026-04-29.md` diff as current truth.
- Keep docs-path checks low-noise: ignore schema keys, bare filenames, generated artifact names,
  and planned future paths such as `scripts/test/unit/` and `scripts/test/e2e/`.
- Before editing, check `git status --short` and avoid touching unrelated dirty files.
