---
name: continuum-cloud-static-audit
description: Use when working on Continuum cloud-safe audit tasks, planning-doc drift checks, or follow-up from scripts/test/run_cloud_static_audit.sh.
---

# Continuum Cloud Static Audit

Read `AGENTS.md` and use continuum-test-workflows for test selection.
The current `scripts/test/run_cloud_static_audit.sh` is the gate authority;
inspect it when changing gates. Run it from the repository root:

```bash
scripts/test/run_cloud_static_audit.sh
```

Required blockers: compile sweep; shell syntax for audit, smoke runner and host
setup; git diff whitespace; unit, local-e2e and combined unittest discovery;
documentation paths; public release claims; certification matrix; suite catalog.

Informational by default: artifact audit, pre-tag readiness, pytest mirrors,
TODO/FIXME inventory, YAML/Ansible lint baselines and suite prerequisites.
Assess findings against changed scope; applicable changed-file lint still
needs explicit validation. Historical evidence may be stale for pre-tagging
without failing required cloud-safe gates. Never weaken freshness checks to
make old evidence certify a new candidate.
The required matrix gate owns release-command policy; informational pre-tag
readiness owns source/tree/report checks without historical wrapper/Kata runtime
waivers. See docs/branch_slimming_audit.md for retained checker responsibilities.

Read the newest report under ignored `logs/cloud_static_audit/`; do not commit
generated reports. Negative-path tests may intentionally log errors: inspect
the final test summary. Static/parser success is not runtime certification.

Do not start VMs through this skill. For approved physical-host work use
continuum-smoke-host-runner and `docs/smoke_runner_isolation.md`.
