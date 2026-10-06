# Replay delivery handoff

## Current state and next steps

The accepted-data replay is on `codex/demo-replay-final-data`, awaiting the user's code review and explicit merge request into `codex/fns-2026-10-08`. Overview, Analysis, Policy comparison and their explanatory dialogs are approved. The shared **View details** header button opens the active tab's dialog; visual iteration is complete for review.

The packaged dataset is the accepted B/72001 forecast capture with its matched static/reactive/forecast comparison. Keep the captured 120-second deadline and issued prediction scores authoritative. Retrospective scoring under another deadline requires a separate analysis. The committed compact dataset builds the standalone offline HTML without private captures; use [README.md](README.md) for build and presentation instructions.

Current-build laptop rehearsal and actual venue-monitor readability remain pending in [REHEARSAL.md](REHEARSAL.md). Earlier HTML opened in Chrome on the presenter's MacBook Pro, but that does not accept this delivery. Automated checks and their limits are described in [VALIDATION.md](VALIDATION.md); generated reports and screenshots belong under ignored `evidence/verification/`.

## Evidence and conversion constraints

The [authoritative experiment handoff](../OPENDT_HANDOFF.md#final-data-location-and-replay-handoff) locates the completed archive, findings and reproduction evidence. The ignored local [raw capture](evidence/accepted-final/) and [portable export](evidence/final-export/) retain acquisition manifests, checksums and independent metric/completion audits. Evidence replacement must use a completed-artifact handoff and renewed validation; do not poll growing campaign artifacts.

Raw conversion requires the explicit [acceptance receipt](evidence/accepted-final/acceptance.json). Acquisition does **not** create that receipt: it must separately document the user's acceptance and identify the selected capture and matched comparison. Conversion also verifies the accepted export and independent audits. The canonical case's legacy `ready=false` is superseded by that accepted export and audit, as explained in the experiment handoff; preserve the sealed case.

Publication timing depends on reviewed archived producers: application samples require the next completed serialized collection or a verified frozen-prefix boundary. Changed producer code needs another proof review. Without either proof, samples remain unavailable. Timed terminal outcomes also wait for the workload writer's `task.emitted` boundary, because a cluster snapshot can expose terminal status before publishing its exact completion timestamp. See [DESIGN.md](DESIGN.md) for interpretation contracts.

Optional earlier slides and reference material remain in ignored `evidence/preserved-deliverables/pre-cleanup-c5394b2/`. Private UI history remains on local `codex/demo-replay-reviewed-history`; keep it private when publishing the delivery branch.
