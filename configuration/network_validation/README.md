## Network Validation Scenarios

This directory contains small configuration files that exercise Continuum's
network emulation paths (TC + optional Mahimahi), without deploying any
resource manager or applications.

Mahimahi is fetched only when a `_mahimahi` wireless preset is active. The
Ansible role clones the Continuum-modified Mahimahi repository into
`<base_path>/.continuum/mahimahi/repo`, exports a clean source tree under
`<base_path>/.continuum/mahimahi/source`, and builds it on the base VMs. The
Continuum repository should not vendor a repo-root `mahimahi/` directory.

All configs:
- set `run.targets: [infrastructure]` so only infrastructure is created;
- set `infrastructure.network.emulation: true` so TC rules are applied;
- set `provider.config.netperf: true` so the built-in netperf benchmark runs;
- use a minimal QEMU topology (2 cloud nodes + 1 endpoint).

### Scenarios

- `bench_net_4g.yaml`: 4G profile via `infrastructure.network.wireless_preset: 4g`.

### How netperf results are collected

When `provider.config.netperf: true`, `infrastructure.network.benchmark()`:

- Starts a `netserver` on the relevant VMs.
- Runs a small set of `netperf` latency and throughput tests.
- Logs human–readable output to the main Continuum log as before.
- Additionally writes **NDJSON** entries to:
  - `<base_path>/.continuum/logs/network_validation/netperf_results_<timestamp>.ndjson`

The schema-v1 NDJSON artifact is self-describing:

- The first line is one `ContinuumNetperfRun` header. Its `planned_pairs` list records
  every directed source/target pair, SSH source, target IP, and expected profile value.
- Every remaining line is a `ContinuumNetperfInvocation` record for exactly one
  `latency` or `throughput` command. It binds the run timestamp and planned pair to
  the exact command plus raw `output` and `error` strings.

The validator requires exactly one invocation in each direction for every header pair.
Legacy invocation-only artifacts are intentionally rejected; generate fresh evidence
with the current producer before validating a run.

### Running the network validation suite

1. From the project root, run the dedicated test suite:

   ```bash
   python3 scripts/test/run_tests.py --suite network_validation \
     --stop-on-failure --provider qemu \
     --base-path /mnt/sdc/matthijs --middle-ip 80 --middle-ip-base 81
   ```

   Adjust `--provider` / `--base-path` / IP options as needed for your setup.
   This will:

   - Provision the minimal VMs described above.
   - Apply TC (and Mahimahi, where configured).
   - Execute the netperf micro–benchmarks.
   - Save both the normal Continuum log and the NDJSON netperf results under
     the selected `base_path`.

2. After the suite completes, run the profile validator:

   ```bash
   python3 scripts/test/verify_network_profiles.py --base-path /mnt/sdc/matthijs
   ```

   This script:

   - Finds the latest
     `<base_path>/.continuum/logs/network_validation/netperf_results_*.ndjson`.
   - Groups entries by scenario (e.g. `cloud->endpoint`).
   - Compares observed latency and throughput against the expected profile values
     carried in the structured result records.
   - Uses the agreed smoke tolerance:
     - within 25% of the expected value, or
     - within 10 ms for latency / 10 mbit for throughput,
       whichever tolerance band is larger.
   - Exits with code `0` when checks pass, or `1` when they fail.

3. You can also point the validator at a specific run:

   ```bash
   python3 scripts/test/verify_network_profiles.py \
     --results-file /mnt/sdc/matthijs/.continuum/logs/network_validation/netperf_results_YYYY-MM-DD_HHMMSS.ndjson
   ```

### What this validates

These scenarios and the validator together provide a lightweight regression
suite for:

- **Profile–based networking**:
  - `infrastructure.network.wireless_preset` profiles such as `4g`.
- **Manual throughput / latency overrides**:
  - YAML `infrastructure.network.overrides` values layered on top of presets.
- **Mahimahi–based networking**:
  - Mahimahi presets and their interaction with the TC core-network model when
    those YAML scenarios are added to the active suite.
