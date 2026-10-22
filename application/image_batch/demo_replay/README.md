# Offline replay dashboard

Explore recorded observations, forecasts, decisions and physical outcomes through **Overview**, **Analysis** and **Policy comparison**. The dashboard replays completed evidence: it does not forecast, simulate or control a running cluster.

Start with the [live reference walkthrough](../README.md) to collect your own experiments. You can also build the included six-worker reference dataset immediately. It is a selected development illustration, not held-out validation.

## Build the included reference

On your laptop, install Node.js **24 or newer**, npm and Git. Clone a separate replay checkout so generated student data stays separate from the checkout used for live experiments:

~~~bash
git clone --branch codex/fns-2026-10-08 --single-branch \
  https://github.com/atlarge-research/continuum.git continuum-replay
cd continuum-replay/application/image_batch/demo_replay
npm ci
npm run typecheck
npm test
npm run build
~~~

Open `dist/continuum-replay.html` directly in Chrome. It embeds scripts, styles, logos and data; after building, it needs no repository, Python, Internet, SSH, Kubernetes, backend or development server. Installation requires Internet. The committed dataset is sufficient to build without private captures.

Playback starts paused with forecasts available. Play/pause, restart, speed, bookmarks and the timeline share one recorded-time cursor. Seeking pauses playback. **Policy comparison** describes completed runs and is independent of the cursor.

Switching to Policy comparison pauses playback and hides the time bar. Returning to Overview or Analysis restores the retained time, paused. If content does not fit the window, scroll inside the content area or adjust browser zoom.

## Build a replay from your own trio

First complete the [live matched trio and report](../README.md#3-capture-a-matched-policy-comparison). Conversion requires exactly six workers, one technically valid static/reactive/forecast run for the same seed, matching workload/source/image/deployment/settings identities, and an operating ready forecast in the selected forecast capture. Preliminary status does not relax those requirements.

On the laptop, use the separate replay checkout above. Cloning it and running `npm ci` are sufficient to start this path; building the included reference first is optional. Record the capture host and the **absolute** paths printed or chosen on the first physical node. Replace the example values:

~~~bash
export CAPTURE_HOST="SAME_USERNAME@FIRST_NODE"
export REMOTE_RUN_DIR="/ABSOLUTE/PATH/TO/continuum/logs/student-demo/runs/student-RUN_TAG"

ssh "$CAPTURE_HOST" 'hostname'
node tools/acquire.mjs \
  --host "$CAPTURE_HOST" \
  --capture "$REMOTE_RUN_DIR/forecast" \
  --report "$REMOTE_RUN_DIR/report/metrics.json" \
  --output evidence/student-trio
~~~

`CAPTURE_HOST` is the host where the capture and reporting commands wrote their files, not the controller VM. If your laptop needs a jump host or a particular key, configure an SSH alias and use it here. Acquisition requires local `ssh` and `tar`, Linux archive utilities on the source host, working key authentication and a verified known host key. See `node tools/acquire.mjs --help` for acquisition options.

Acquisition reads completed evidence, checks namespace cleanup and observer drain, verifies the supporting report's capture identity and unchanged checksums, and copies a bounded subset into a fresh local directory. The selected source files must total at most 80 MiB; the complete raw archive stays on the capture host. Do not move or rename the source captures before acquisition: their recorded absolute paths are part of the identity checks.

Convert and build:

~~~bash
npm run convert -- --evidence evidence/student-trio \
  --status preliminary --output data/replay.json
npm run typecheck
node --test tests/dataset.test.ts
npm run build
~~~

This replaces `data/replay.json` **in your local replay checkout** with the generated dataset. Keep that file as local experiment output rather than committing it to the reference branch. Keep the acquired evidence, raw captures, combined metrics and built HTML together with your experiment notes. Use fresh evidence directories for later trios.

Open `dist/continuum-replay.html` directly, then repeat with networking disabled:

- Check that the run identity and static/reactive/forecast summaries refer to your trio.
- Inspect Overview, Analysis and Policy comparison.
- Play, pause, restart and seek both forward and backward.
- Follow a published forecast through its decision and subsequent physical observation. Missing data or vetoed actions should remain visible.

The full `npm test` suite and `npm run verify:browser` include assertions specific to the **included reference dataset**, including final status and particular recorded events. Run them before replacing that dataset, not as generic acceptance checks for your preliminary capture. The targeted dataset test checks causal visibility and playback invariants; successful conversion/build and manual inspection remain necessary.

A technical capture accepted by the reporting checks is different from a scientifically accepted final dataset. Use `--status preliminary` for this workflow; the converter otherwise defaults to accepted-final evidence, so always specify the status explicitly. Failed matching or capture-quality checks should be investigated in the saved evidence, not bypassed by editing provenance.

## Verify the included reference in a browser

Before replacing the committed dataset, install the isolated browser and run the complete offline display checks:

~~~bash
PLAYWRIGHT_BROWSERS_PATH=evidence/browser npx playwright install chromium --only-shell
npm run verify:browser
npm run format:check
~~~

Browser verification disables networking and writes reports/screenshots to ignored `evidence/verification/`. It checks direct file opening, views, controls, seeking and display sizes. Actual laptop/monitor readability remains a manual check. See [design and interpretation](DESIGN.md).
