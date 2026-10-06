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

To acquire another completed capture, use `node tools/acquire.mjs --help` for the configurable source options and follow the [evidence handoff](HANDOFF.md). Acquisition and conversion are optional when building the included replay.

Install the isolated verification browser once, then check direct offline opening:

```sh
PLAYWRIGHT_BROWSERS_PATH=evidence/browser npx playwright install chromium --only-shell
npm run verify:browser
npm run format:check
```

Browser verification runs with networking disabled and writes its report and screenshots to ignored `evidence/verification/`. See [validation](VALIDATION.md), [design and interpretation](DESIGN.md), and [evidence handoff](HANDOFF.md).
