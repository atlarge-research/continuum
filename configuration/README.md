# Configuration
This directory contains legacy `.cfg` configurations kept for historical reproduction and migration reference.

The active runtime input model is YAML-only:

- experiments: `configs/experiments/`
- environment profiles: `configs/profiles/environment/`
- software profiles: `configs/profiles/software/`

For the active schema and migration guidance, use:

- `docs/configuration_reference.md`
- `docs/migration_notes.md`

For new YAML users, start from:

- `configs/experiments/template.yaml`
- `configs/profiles/environment/template.yaml`
- `configs/profiles/software/template.yaml`

The CLI now rejects legacy `.cfg` runtime inputs directly, so files in this directory should not be used as the primary entrypoint for new runs.
