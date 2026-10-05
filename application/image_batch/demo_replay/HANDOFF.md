# Replay delivery handoff

## Current state

The demo is isolated on `codex/demo-replay`, forked from `codex/fns-2026-10-08` at `a99ab54ae538373f79d00018d2059bdeb6f030b6`. All task-owned files are in this directory; controller, simulator, deployment, infrastructure and the experiment checkout are untouched. The deliverable has Overview, Analysis and Policy comparison in one self-contained blue replay HTML. Introductory slides are prepared separately by the presenter. A causal service indicator distinguishes confirmed application deadline outcomes from pending Jobs. Start with [README.md](README.md).

The preliminary run is `fns-diag-primary-s62002-forecast`. The presenter reports that acceptable final experiments are available, but no final capture has been imported. Campaign files have not been read or polled. The presenter confirmed that the earlier HTML runs locally on a MacBook Pro in Chrome, including its main controls. Rehearsal of the revised artifacts and replacement with accepted final evidence remain external acceptance gates. Node6 browser checks do not establish either gate.

## Evidence and acquisition

The read-only source is node3's `/mnt/sdb/matthijs/fns-evidence/opendc-diagnostics-20261003T213920Z/evaluation/matrix-primary-reused-transport/experiments/fns-diag-primary-s62002-forecast`; the supporting report is `reports/primary/metrics.json` under that diagnostics archive. The local capture manifest, `evidence/preliminary/acquisition.json`, records exact paths, byte sizes and SHA-256 hashes; the normalized dataset embeds its provenance. The 222-file subset totals 58,664,068 source bytes. It excludes container images, duplicate observer archives, Parquet and the remaining archive.

The private raw subset is locally under `evidence/preliminary/` and is ignored by Git. `tools/acquire.mjs` permits only this explicitly authorized completed diagnostics archive, caps uncompressed source size at 80 MiB, bounds each remote read, and verifies unchanged remote and local hashes. It refuses to overwrite an existing acquisition. Do not relax its completed-evidence constraint to poll the active final campaign.

```sh
node tools/acquire.mjs /mnt/sdb/matthijs/fns-evidence/opendc-diagnostics-20261003T213920Z/evaluation/matrix-primary-reused-transport/experiments/fns-diag-primary-s62002-forecast /mnt/sdb/matthijs/fns-evidence/opendc-diagnostics-20261003T213920Z/reports/primary/metrics.json
npm run convert
```

## Causal timing

Ruling: use controller proposal timestamps as conservative publication bounds for forecasts and candidates because these artifacts lack independent issue timestamps. Application resource observations start before Prometheus queries complete; a source-hash-verified serialized producer establishes availability by its next completed collection, with verified frozen-prefix collection boundaries as fallback. If neither proof exists, the sample remains unavailable. This may delay a display slightly; treating those earlier timestamps as publication would expose future measurements.

The converter preserves integer nanoseconds before parsing and rounds availability upward. It retains historical journal scores instead of rerunning current controller scoring. It retains preceding history internally, begins at the first ready operating forecast, and derives timing, deadlines, acquisition events and worker application capacity from captured metadata. The producer proof is pinned to the archived source hashes; changed producer code needs a new proof review, rather than silently inheriting the old one.

Worker cards use a separate bounded last-complete-update presentation selector; strict `viewAt` still drives counters, histories and decision interpretation. The bound derives from `3 * run.maxGapMs`, and explicit failures stop retention. See [DESIGN.md](DESIGN.md#resources-and-service) before changing this behavior.

The Overview forecast uses the latest published ready forecast independently of the latest recorded decision, retaining historical issue segments with clipping at publication, the next ready issue and horizon. Skipped-update reasons and unavailable-alternative reasons now survive conversion; do not replace actual fallback decisions with the retained forecast's old simulations. Arrival bars use recorded counts independently of membership gaps; forecast quality retains conservative full-collection coverage. See [DESIGN.md](DESIGN.md#prediction-and-comparison).

## Service and comparison evidence

Application `execution_finish_time` is separate from terminal Kubernetes completion. Each Job retains the earliest observed finish availability and membership in the report's evaluated cohort. Deadline confirmations require both finish evidence and a successful terminal status; failures count as missed, unknown outcomes remain pending. The existing Job-completion counter retains its original meaning.

The already acquired report contains six matched diagnostic policy captures over two seeds; compact summaries are embedded in the dataset. Numerical comparison includes the report's allocation bounds and completed-only latency. All three arms remain visible even when a result does not establish the intended advantage. The preliminary twin meets service but costs more application allocation than adequate static; this is not final savings evidence.

Ruling: larger type takes precedence over squeezing all content onto smaller laptop viewports. The content area scrolls; playback controls remain visible. Overview fits 1920×1080 without scrolling. Analysis explanations expand, and selection of an issued forecast is local presentation state, causally gated on rewind.

## Replacing the dataset

Wait for an explicit handoff naming one completed accepted six-worker capture and its supporting report. Obtain the same bounded subset with before/after checksum verification in a new local evidence directory. The current acquisition tool intentionally cannot read the pending final archive: adapting its exact archive boundary is part of that completed handoff, not an automated campaign watcher.

Create an acceptance receipt containing `captureId`, `accepted: true`, `acceptedBy`, `acceptedAt` and `evidenceLocation`. It must match the capture identity and its supporting report's `accepted_capture: true`. Supply that receipt explicitly:

```sh
npm run convert -- --evidence evidence/accepted-final --status accepted-final --acceptance evidence/accepted-final/acceptance.json
npm run typecheck
npm test
npm run build
npm run verify:browser
```

The receipt also needs `comparisonCaptureIds`, listing every accepted matched policy capture included in the completed report. This is separate from the immutable report: do not add acceptance fields to sealed evidence. The converter requires fixed/reactive/forecast arms matched within each seed, consistent settings and accounting, accepted captures and sender fidelity; never combine preliminary and final arms.

Review the acquisition, conversion and build records, all causal boundaries, new bookmarks, numerical source agreement, all three views and the supported screen sizes/zoom equivalents. Inform the presenter of any changed capture/network statement for their slides and repeat laptop rehearsal. Raw-source golden tests currently identify the preliminary acquisition; add the accepted capture's independently read expectations instead of changing those literals blindly.

Keep this branch and its managed worktree available for code review. Do not push or merge before the presenter approves the code. Their intended later sequence is to push the replay branch, merge updated `codex/fns-2026-10-08` into it, import completed accepted evidence, refine/rehearse the visualization, then merge back after approval.

The delivery is generated as `dist/continuum-replay.html`; all of `dist/` is ignored. A fresh checkout needs `npm ci` and `npm run build` before the HTML can be copied to the presentation laptop. Generated build/conversion receipts, screenshots and the browser report are written under ignored `evidence/verification/`; the acquisition manifest stays beside its private capture. Tests and verification scripts remain tracked. [REHEARSAL.md](REHEARSAL.md) and [VALIDATION.md](VALIDATION.md) describe presentation acceptance and automated checks. The earlier slides (source HTML, generated HTML/PDF and build script), neutral replay and prior verification files are preserved in ignored `evidence/preserved-deliverables/pre-cleanup-c5394b2/`, with a checksum manifest. This archive is optional reference material and no build or presentation depends on it.
