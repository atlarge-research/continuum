# Tests
This directory contains a wide variety of configurations that cover almost all of Continuum's features.

## Automated Testing

Continuum includes an automated end-to-end testing framework that can discover, execute, and validate test configurations. The test runner is located in `scripts/test/run_tests.py`.

### Quick Start

```bash
# Run smoke tests (fast, uses cached base images)
python3 scripts/test/run_tests.py --suite smoke

# Run full regression (all configs, periodic base image rebuild)
python3 scripts/test/run_tests.py --suite full
```

### Basic Usage

```bash
# Run smoke tests (fast, uses cached base images)
python3 scripts/test/run_tests.py --suite smoke

# Run full regression (all configs, periodic base image rebuild)
python3 scripts/test/run_tests.py --suite full

# Run specific provider tests
python3 scripts/test/run_tests.py --provider qemu

# Run single config file
python3 scripts/test/run_tests.py --config configuration/tests/qemu/01_infraonly-cloud.cfg

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
    "configuration/tests/**",
    "configuration/cellular_network/bench_cloud_4g.cfg"
  ],
  "exclude": [
    "configuration/experiment_kata/**",
    "configuration/experiment_control/microbenchmark/**"
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

### Manual Testing (Legacy)

You can still run tests manually using the old approach:

```bash
for i in configuration/tests/<qemu OR gcp>/*.cfg; do
    python3 continuum.py $i || break
done
```

A run is successful if it prints one or multiple `ssh vm_name@ip_address -i path/to/ssh/key` at the end.
You can also check the log files in `logs/` to validate the runs.

### Test Suites

The tests are currently split up per provider, with `qemu` covering local execution, and `gcp` covering execution in the cloud using Google Cloud Platform. The latter requires extra configuration, most notably, defining your GCP project name and service key location.

- **Smoke Tests**: Core test configs in `configuration/tests/` - fast validation using cached images
- **Full Regression**: All configs including experiments - comprehensive testing with periodic base image rebuilds
