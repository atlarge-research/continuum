# Tests
This directory contains a wide variety of configurations that cover almost all of Continuum's features.

## Automated Testing

Continuum includes an automated end-to-end testing framework that can discover, execute, and validate test configurations. The test runner is located in `scripts/test/run_tests.py`.

### Quick Start

```bash
# Inspect configured suites and their declared prerequisites
python3 scripts/test/run_tests.py --list-suites

# Check whether the local host can run the smoke suite
python3 scripts/test/run_tests.py --suite smoke --check-prereqs

# Run smoke tests (fast, uses cached base images)
python3 scripts/test/run_tests.py --suite smoke

# Run full regression (all configs, periodic base image rebuild)
python3 scripts/test/run_tests.py --suite full

# Run the dedicated network-emulation validation suite
python3 scripts/test/run_tests.py --suite network_validation
```

### Basic Usage

```bash
# Run smoke tests (fast, uses cached base images)
python3 scripts/test/run_tests.py --suite smoke

# Run full regression (all configs, periodic base image rebuild)
python3 scripts/test/run_tests.py --suite full

# Run network-emulation validation configs only
python3 scripts/test/run_tests.py --suite network_validation

# Run specific provider tests
python3 scripts/test/run_tests.py --provider qemu

# Run single config file
python3 scripts/test/run_tests.py --config configs/experiments/infra_only.yaml

# Stop on first failure
python3 scripts/test/run_tests.py --suite smoke --stop-on-failure
```

### Parameter Overrides

The test runner supports overriding configuration parameters, which is especially useful in cluster environments:

```bash
# Override base_path (for disk space management)
python3 scripts/test/run_tests.py --suite smoke --base-path /mnt/large_disk/continuum_tests

# Override IP ranges (for cluster environments to avoid conflicts)
python3 scripts/test/run_tests.py --suite smoke --middle-ip 150 --middle-ip-base 140

# Combine options
python3 scripts/test/run_tests.py --suite smoke --base-path /tmp/test --middle-ip 200
```

### Selective Testing with Test Manifest

For selective testing (e.g., to avoid running all experiment configs), create a test manifest file:

```bash
# Create test manifest (copy from example)
cp scripts/test/test_manifest.json.example scripts/test/test_manifest.json

# Edit test_manifest.json to include/exclude specific patterns
# Then run with manifest:
python3 scripts/test/run_tests.py --manifest scripts/test/test_manifest.json
```

The manifest supports include/exclude patterns:
```json
{
  "include": [
    "configs/experiments/**/*.yaml",
    "configs/experiments/bench_cloud_openfaas.yaml"
  ],
  "exclude": [
    "**/*template*.yaml"
  ]
}
```

### Base Image Management

The test runner intelligently manages base image caching:

```bash
# Force rebuild base images for all tests
python3 scripts/test/run_tests.py --rebuild-base-images

# Use cache only (never rebuild)
python3 scripts/test/run_tests.py --use-cache

# By default, base images are rebuilt periodically (every 10th test run)
```

### Test Results

Test results are saved to `logs/test_results/` as JSON files:
- Individual test run results: `test_results_YYYY-MM-DD_HH-MM-SS.json`
- Includes execution time, success/failure status, error messages, and base image rebuild information
- Each summary JSON now points at a sibling artifact directory `test_results_YYYY-MM-DD_HH-MM-SS/`
- Each test inside that directory gets `stdout.txt`, `stderr.txt`, and `metadata.json`
- Failed runs are also tagged with a stable `failure_class` such as `timeout`, `missing_lock`,
  `missing_state`, `wrong_state_phase`, `missing_ssh`, or `ansible_failure`

For YAML runs, the runner success contract is stricter than just `exit_code=0`.
It also expects:
- `.continuum/experiment_lock.yaml` to be written
- `.continuum/state.json` to be written
- `state.json.phase_completed` to match the executed phase target

### Manual Testing (Legacy)

Legacy `.cfg` loops are kept only for historical reproduction. For active runtime validation, use YAML experiments under `configs/experiments/`.

You can still run YAML experiments manually:

```bash
for i in configs/experiments/*.yaml; do
    python3 continuum.py $i || break
done
```

A run is successful if it prints one or multiple `ssh vm_name@ip_address -i path/to/ssh/key` at the end.
You can also check the log files in `logs/` to validate the runs.

### Test Suites

The active suites are declared in `scripts/test/test_config.json`.

- **Smoke Tests**: Dedicated lightweight YAML scenarios in `configs/experiments/smoke/`.
- **Full Regression**: All YAML experiments in `configs/experiments/` with periodic base image rebuilds.
- **Network Validation**: Only `configs/experiments/network_validation/` scenarios for TC/netperf profile validation.

The runner now performs suite preflight checks from `scripts/test/test_config.json`
before discovery/execution starts.

- **Smoke** requires host `virsh` and `ssh`.
- **Network Validation** requires host `virsh`, `ssh`, and `tc`.
- **Full** currently has no additional suite-level preflight.

The new CLI helpers are intended to make those expectations inspectable before
starting a long VM-backed run:

- `python3 scripts/test/run_tests.py --list-suites`
- `python3 scripts/test/run_tests.py --suite smoke --check-prereqs`
- `python3 scripts/test/run_tests.py --suite network_validation --check-prereqs`
- `./scripts/test/run_smoke_host.sh list-suites`
- `./scripts/test/run_smoke_host.sh check-prereqs`

When a smoke run fails, inspect the per-test artifact directory before rerunning.
That is usually faster than relying on the aggregate JSON alone.

The smoke and network-validation suites are configured to stop on first failure.
That keeps the operational path fast-fail and avoids spending time on downstream phases after an
earlier phase is already broken.

For failed smoke runs that retain VMs, use [vm_debugging_runbook.md](/home/matthijs/continuum/docs/vm_debugging_runbook.md).
For least-privilege host execution of real VM-backed smoke runs, use
[smoke_runner_isolation.md](/home/matthijs/continuum/docs/smoke_runner_isolation.md).
