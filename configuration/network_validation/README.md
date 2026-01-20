## Network Validation Scenarios

This directory contains small configuration files that exercise Continuum's
network emulation paths (TC + optional Mahimahi), without deploying any
resource manager or applications.

All configs:
- set `infra_only = True` so only infrastructure is created;
- enable `network_emulation = True` so TC rules are applied;
- enable `netperf = True` so the built–in netperf benchmark runs;
- use a minimal QEMU topology (2 cloud nodes + 1 endpoint).

### Scenarios

- `bench_net_4g.cfg`: 4G profile via `wireless_network_preset = 4g`.
- `bench_net_5g.cfg`: 5G profile via `wireless_network_preset = 5g`.
- `bench_net_manual_low.cfg`: 4G preset, but with low manual throughput caps:
  - `cloud_endpoint_throughput = 5`, `edge_endpoint_throughput = 5`.
- `bench_net_manual_high.cfg`: 4G preset, but with higher throughput caps:
  - `cloud_endpoint_throughput = 100`, `edge_endpoint_throughput = 100`.
- `bench_net_mahimahi_4g.cfg`: Mahimahi–based 4G networking via
  `wireless_network_preset = 4g_us_verizon_mahimahi`.
- `bench_net_manual_override_only.cfg`: No `wireless_network_preset` at all;
  only manual latency/throughput overrides are used:
  - `cloud_endpoint_latency_*`, `cloud_endpoint_throughput`,
  - `edge_endpoint_latency_*`, `edge_endpoint_throughput`.

### How netperf results are collected

When `netperf = True`, `infrastructure.network.benchmark()`:

- Starts a `netserver` on the relevant VMs.
- Runs a small set of `netperf` latency and throughput tests.
- Logs human–readable output to the main Continuum log as before.
- Additionally writes **NDJSON** entries to:
  - `logs/network_validation/netperf_results_<timestamp>.ndjson`

Each NDJSON line contains:

- `timestamp`: benchmark timestamp taken from the main config.
- `source` / `target`: logical node types (e.g. `cloud`, `endpoint`).
- `source_ssh` / `target_ip`: where the command ran and which IP was targeted.
- `direction`: `"latency"` or `"throughput"`.
- `command`: the exact netperf command that was executed.
- `output` / `error`: raw netperf stdout / stderr (as a single string).

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
   - Save both the normal Continuum log and the NDJSON netperf results.

2. After the suite completes, run the profile validator:

   ```bash
   python3 scripts/test/verify_network_profiles.py
   ```

   This script:

   - Finds the latest `logs/network_validation/netperf_results_*.ndjson`.
   - Groups entries by scenario (e.g. `cloud->endpoint`).
   - Computes basic average throughput per scenario.
   - Performs conservative, **relative** checks such as:
     - High–throughput scenarios should achieve clearly higher throughput
       than low–throughput scenarios.
   - Exits with code `0` when checks pass, or `1` when they fail.

3. You can also point the validator at a specific run:

   ```bash
   python3 scripts/test/verify_network_profiles.py \
     --results-file logs/network_validation/netperf_results_YYYY-MM-DD_HH:MM:SS.ndjson
   ```

### What this validates

These scenarios and the validator together provide a lightweight regression
suite for:

- **Profile–based networking**:
  - `wireless_network_preset = 4g` vs `5g`.
- **Manual throughput / latency overrides**:
  - Both in combination with presets, and in a pure "manual only" mode
    without any `wireless_network_preset` set.
- **Mahimahi–based networking**:
  - `*_mahimahi` presets and their interaction with the TC core–network model.

