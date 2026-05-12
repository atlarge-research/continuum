---
name: continuum-research-scripts
description: Use when invoking or modifying Continuum scripts outside scripts/test, including migrate_cfg_to_yaml.py, kube_analyzer.py, replicate_kubecontrol*.py, replicate_model.py, replicate_paper.py, fig1.py, or scripts/kata batch runners.
---

# Continuum Research Scripts

Use this skill for the legacy/research helper scripts under `scripts/` that are
not part of the main test runner. Many of these scripts run long experiments,
consume historical logs, generate plots, or assume they are launched from a
particular working directory.

## Script Map

- `scripts/migrate_cfg_to_yaml.py`: conservative legacy `.cfg` to YAML triplet
  converter. This is the safest non-test script; inspect outputs before
  committing generated configs.
- `scripts/kube_analyzer.py`: analysis layer over kubecontrol replication logs.
  It assumes existing benchmark CSV/log artifacts.
- `scripts/replicate_kubecontrol.py` and
  `scripts/replicate_kubecontrol_combine.py`: legacy Kubernetes control-plane
  benchmark reproduction and result aggregation.
- `scripts/replicate_model.py` and `scripts/replicate_paper.py`: legacy paper
  reproduction/model scripts that may run Continuum configurations repeatedly.
- `scripts/fig1.py`: plotting/figure helper over existing data.
- `scripts/kata/run_all_kata_*.sh`: batch runners for Kata experiments; these
  are VM-backed and should not be run casually from an agent.

## Guardrails

1. Read the script before running it; do not infer behavior from the name.
2. Check for `os.chdir`, hard-coded config paths, log assumptions, and calls to
   `continuum.py`.
3. Prefer analysis/resume modes over rerunning experiments when available.
4. Do not run VM-backed reproduction scripts unless the user explicitly asks and
   the host setup is ready.
5. Do not commit generated plots, CSVs, logs, or large artifacts unless asked.

## Validation

For code-only edits, use focused static checks:

```bash
python3 -m py_compile scripts/<name>.py
env PYTHONPATH=. python3 -m unittest discover scripts/test
```

For migration work, run the converter on a small known `.cfg` and inspect the
generated YAML diff manually. For plot or reproduction scripts, prefer checking
parsers and helper functions with unit tests rather than running full
experiments.
