# Replay delivery handoff

## Current state and next steps

The reviewed accepted-data replay is integrated into `codex/fns-2026-10-08`. Overview, Analysis, Policy comparison and their explanatory dialogs are approved. The shared **View details** header button opens the active tab's dialog. The remaining work is colleague feedback and presentation rehearsal.

The packaged dataset is the accepted B/72001 forecast capture with its matched static/reactive/forecast comparison. Keep the captured 120-second deadline and issued prediction scores authoritative. Retrospective scoring under another deadline requires a separate analysis. The committed compact dataset builds the standalone offline HTML without private captures; use [README.md](../demo_replay/README.md) for build and presentation instructions.

Current-build laptop rehearsal and actual venue-monitor readability remain pending in [REHEARSAL.md](REPLAY_REHEARSAL.md). Earlier HTML opened in Chrome on the presenter's MacBook Pro, but that does not accept this delivery. Automated checks and their limits are described in [VALIDATION.md](REPLAY_VALIDATION.md); generated reports and screenshots belong under ignored `evidence/verification/`.

## Evidence and conversion constraints

The [authoritative experiment handoff](OPENDT_HANDOFF.md#final-data-location-and-replay-handoff) locates the completed archive, findings and reproduction evidence. The ignored local [raw capture](../demo_replay/evidence/accepted-final) and [portable export](../demo_replay/evidence/final-export) retain acquisition manifests, checksums and independent metric/completion audits. Evidence replacement must use a completed-artifact handoff and renewed validation; do not poll growing campaign artifacts.

Raw conversion to accepted-final status requires an explicit acceptance receipt, such as the preserved [receipt](../demo_replay/evidence/accepted-final/acceptance.json). Acquisition does **not** create that receipt: it must separately document the user's acceptance and identify the selected capture and matched comparison. It contains `captureId`, `accepted: true`, `acceptedBy`, `acceptedAt`, `evidenceLocation` and `comparisonCaptureIds` for the complete matched comparison. Merely creating a receipt does not supply the independent audits. Conversion verifies the accepted export and audits as well. The canonical case's legacy `ready=false` is superseded by that accepted export and audit, as explained in the experiment handoff; preserve the sealed case.

For independently reviewed evidence replacement, run acquisition from `application/image_batch/demo_replay` with `--audits` pointing to the remote archive root containing `demo-data/index.json`, `analysis/independent-monitor-audit.json` and `analysis/completion-verification.json`. Its `--report` must be the selected case under `demo-data/` as identified by that index. See `node tools/acquire.mjs --help` for acquisition options. Capture timing, worker capacities and controller settings come from the evidence.

After review and acquisition, convert from that same directory with an explicit accepted-final status and receipt:

~~~bash
npm run convert -- --evidence evidence/reviewed-trio \
  --status accepted-final --acceptance evidence/reviewed-trio/acceptance.json \
  --output data/replay.json
~~~

Publication timing depends on reviewed archived producers: application samples require the next completed serialized collection or a verified frozen-prefix boundary. Changed producer code needs another proof review. Without either proof, samples remain unavailable. Timed terminal outcomes also wait for the workload writer's `task.emitted` boundary, because a cluster snapshot can expose terminal status before publishing its exact completion timestamp. See [DESIGN.md](../demo_replay/DESIGN.md) for interpretation contracts.

Optional earlier slides and reference material remain in ignored `evidence/preserved-deliverables/pre-cleanup-c5394b2/`. Private UI history remains on local `codex/demo-replay-reviewed-history`; keep it private when publishing the delivery branch.
