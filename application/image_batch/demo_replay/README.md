# Continuum offline demonstration

Explore a real six-worker service and its closed-loop digital twin through **Overview**, **Analysis** and **Policy comparison**. The included accepted B/72001 capture demonstrates physical execution and recorded decisions, with a matched comparison of static, reactive and forecast-based control. It is a selected development illustration, not held-out validation.

## Present on a laptop

Build the replay using the commands below, then copy the generated `dist/continuum-replay.html` to your MacBook Pro and open it directly in Chrome. It includes scripts, styles, logos and data: no repository, Python, internet, SSH, Kubernetes, backend or development server is needed. Prepare introductory slides separately.

Playback starts paused in operation with forecasts available. Play/pause, restart, speed, bookmarks and the timeline share one recorded-time cursor across views. Drag the timeline left or choose an earlier bookmark to seek backward; seeking pauses playback.

Overview fits a 1920×1080 presentation monitor at normal zoom. Smaller windows and larger zoom use a scrollable content area with playback controls always visible. Actual monitor readability still needs an on-site check. Follow the [walkthrough and laptop rehearsal notes](REHEARSAL.md).

## Build and verify

Build prerequisites: Node.js 24 or newer and npm. Installation requires network access; presentation does not. Run from this directory:

```sh
npm ci
npm run typecheck
npm test
npm run build
```

The build produces the standalone blue replay HTML, approximately 4 MiB, under ignored `dist/`. Generated delivery files are not committed. The committed normalized dataset makes a fresh checkout buildable without private source captures; raw-source audit tests skip when their evidence is absent.

Install the isolated verification browser once, then check direct offline opening:

```sh
PLAYWRIGHT_BROWSERS_PATH=evidence/browser npx playwright install chromium --only-shell
npm run verify:browser
npm run format:check
```

Browser verification runs with networking disabled and writes its report and screenshots to ignored `evidence/verification/`. See [validation](VALIDATION.md), [design and interpretation](DESIGN.md), and [evidence handoff](HANDOFF.md).

## Refresh recorded evidence (optional)

The included replay builds without acquisition or conversion. To replace its evidence, obtain a completed-capture handoff and run from this directory. Replace the illustrative SSH alias and archive paths below with those supplied in that handoff; no source host or archive location is configured by default.

```sh
node tools/acquire.mjs \
  --host research-archive \
  --capture /archive/completed/experiments/capture-id \
  --report /archive/completed/demo-data/cases/case-id.json \
  --audits /archive/completed \
  --output evidence/new-capture
```

- `--host`: an SSH alias or `user@host` with working key authentication and a known host key.
- `--capture`: the absolute remote directory of one completed experiment.
- `--report`: the absolute remote path to its supporting metrics JSON. For accepted-final evidence, use the selected case’s path under `demo-data/`, as recorded in the audit index.
- `--audits`: the absolute remote archive root containing `demo-data/index.json`, `analysis/independent-monitor-audit.json` and `analysis/completion-verification.json`. Optional for preliminary evidence; required for accepted-final conversion.
- `--output`: a fresh local directory, relative to this directory or absolute. Existing destinations are refused.

Acquisition checks completion and the report's capture identity, copies only the selected artifacts, enforces an 80 MiB source cap and verifies unchanged checksums. Acquisition needs local `ssh` and `tar`; the source host needs the Linux archive tools used by the script. See `node tools/acquire.mjs --help` and the [evidence handoff](HANDOFF.md#evidence-and-conversion-constraints).

Acquisition does not create the acceptance receipt. Once the evidence has been explicitly accepted, supply `evidence/new-capture/acceptance.json` with `captureId`, `accepted: true`, `acceptedBy`, `acceptedAt`, `evidenceLocation` and `comparisonCaptureIds` identifying the complete matched policy comparison. Then convert and run the checks above:

```sh
npm run convert -- --evidence evidence/new-capture \
  --status accepted-final \
  --acceptance evidence/new-capture/acceptance.json \
  --output data/replay.json
```

Conversion defaults to `evidence/accepted-final`, status `accepted-final`, its `acceptance.json` and output `data/replay.json`; the example overrides the evidence directory explicitly. Capture timing, worker capacities and controller settings come from the recorded evidence.
