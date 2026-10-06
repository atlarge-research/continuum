# Replay delivery handoff

## Current state

Accepted-data adaptation and visual iteration live on `codex/demo-replay-final-data` in the existing managed replay worktree, following the shared replay/FNS checkpoint `ee023e7`. The retired `codex/demo-replay` branch has been removed. Keep changes confined to this deliverable and integrate back into `codex/fns-2026-10-08` only when the presenter requests it.

The packaged dataset is the accepted B/72001 forecast capture, with its matched static/reactive/forecast comparison. See the [authoritative experiment handoff](../OPENDT_HANDOFF.md) for acceptance, interpretation and evidence. All ten captured forecast cycles are ready; this run has no recorded forecast fallback. The earlier preliminary evidence is retained privately for regression audits, not mixed into the current comparison. Start with [README.md](README.md).

The presenter has approved Overview, Evidence and Policy comparison. The agreed Analysis polish is applied for presenter review: its forecast, alternatives, action and six-worker CPU-request table share one screen, and longer explanations and measurements live in Analysis details. The selected scenario connects the chart and worker predictions. Its chart and forecast error use matching aggregate intervals; publication, coverage and reverse-seeking rules remain in force. Review Analysis before the final rehearsal.

The presenter confirmed that an earlier HTML opens on a MacBook Pro in Chrome. The accepted-data delivery needs its own laptop rehearsal and the venue monitor check in [REHEARSAL.md](REHEARSAL.md). Node6 browser verification cannot establish those external acceptance gates.

## Evidence and replacement

The completed read-only archive is node3's `/mnt/sdb/matthijs/fns-evidence/opendc-final-trio-20261005T092500Z/`. The selected forecast capture is `captures/attempt-02/experiments/fns-final-trio-b-forecast-s72001-s72001-forecast`; the complete trio report is `demo-data/cases/b-s72001.json`. The portable export and independent metric/completion audits are retained under ignored `evidence/final-export/`. Export checksums were verified before use.

The ignored raw capture is `evidence/accepted-final/`. Its acquisition manifest records paths, sizes and SHA-256 hashes for the 259 raw artifacts, three acceptance audits and supporting report, totalling 55,785,262 source bytes. It excludes duplicate observer prefixes, container images, Parquet and the rest of the archive. Acquisition verifies unchanged remote and local hashes, bounds each read, refuses an existing destination and retains an 80 MiB source cap. Only the exact completed diagnostic and final sources are allowed; never generalize this into a growing-campaign watcher.

```sh
node tools/acquire.mjs /mnt/sdb/matthijs/fns-evidence/opendc-final-trio-20261005T092500Z/captures/attempt-02/experiments/fns-final-trio-b-forecast-s72001-s72001-forecast /mnt/sdb/matthijs/fns-evidence/opendc-final-trio-20261005T092500Z/demo-data/cases/b-s72001.json
npm run convert
```

Conversion defaults to this final capture and its explicit `acceptance.json` receipt. The receipt records `captureId`, `accepted: true`, `acceptedBy`, `acceptedAt`, `evidenceLocation` and all three `comparisonCaptureIds`. It documents the presenter's acceptance; it does not rewrite sealed reports. Final conversion additionally verifies the accepted export index and independent metric/completion audits against the captured cohort, p95 and allocation bounds. Legacy `ready=false` in the canonical case is superseded by the accepted export and independent audit, as explained in the experiment handoff. Do not change the sealed case to hide that distinction.

## Causal timing and service

Controller proposal timestamps conservatively bound publication of forecasts and candidates, which lack independent issue timestamps. The normalizer preserves integer nanoseconds and rounds availability upward. It retains preceding history and starts at the first ready operating forecast, deriving period, cadence, horizon, deadline and application capacity from captured metadata.

Application resource observations begin before Prometheus queries complete. Reviewed archived producer identities establish availability by the next completed serialized collection; verified frozen-prefix boundaries provide a fallback. If neither proof exists, samples remain unavailable. The final observer hash is `ec29267e0f2d5c74b3fcb99388088a910aedac0b1d38ee2636ac297eea1eb9f4`; its overrun/watch-resync changes preserve the publication proof. Changed producer code needs another proof review.

Worker cards retain a coherent already-published update through brief collection gaps, bounded by `3 * run.maxGapMs` and stopped by explicit failures. Scientific counters, histories, forecast quality and decisions retain strict coverage. Arrival counts do not inherit non-atomic Job/Pod membership gaps. Historical forecast segments retain their issued values; skipped-update retention never substitutes old simulations for the actual current decision. See [DESIGN.md](DESIGN.md).

Service is API Job creation to terminal Job completion. Classifier finish is preserved separately. The provisional indicator waits for published terminal evidence, counts failures as missed and excludes pending outcomes from its confirmed percentage. Timed outcomes also wait for the workload writer’s `task.emitted` boundary: an earlier cluster snapshot can expose terminal status without publishing the exact completion timestamp. The completed comparison retains the full evaluated denominator, including failed and unfinished Jobs. Historical simulator scores retain their original model/timing assumptions and are not rescored as terminal physical outcomes.

## Delivery and validation

The committed compact dataset makes a fresh checkout buildable without private captures. The single delivery is generated as `dist/continuum-replay.html`; all `dist/`, raw evidence, receipts, browser reports and screenshots are ignored. No presentation depends on local untracked code or earlier generated files. Tests and verification tools remain tracked. [VALIDATION.md](VALIDATION.md) describes automated checks; generated results live under `evidence/verification/`.

The earlier slides, neutral variant and prior verification material remain optional private references in `evidence/preserved-deliverables/pre-cleanup-c5394b2/`. Unpublished UI development history is preserved locally on `codex/demo-replay-reviewed-history`; do not publish it with `git push --all`. Keep further visualization iteration on the accepted-data branch until the presenter requests integration back into FNS.
