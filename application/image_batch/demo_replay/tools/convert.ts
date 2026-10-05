import { parseArgs } from "node:util";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";
import { convertCapture } from "./normalize.ts";
const { values } = parseArgs({
  options: {
    evidence: { type: "string", default: "evidence/accepted-final" },
    status: { type: "string", default: "accepted-final" },
    acceptance: { type: "string" },
    output: { type: "string", default: "data/replay.json" },
  },
});
const acceptance =
  values.acceptance ??
  (values.status === "accepted-final"
    ? join(values.evidence!, "acceptance.json")
    : undefined);
const data = convertCapture(values.evidence!, values.status, acceptance);
const text = JSON.stringify(data) + "\n";
mkdirSync(dirname(values.output!), { recursive: true });
writeFileSync(values.output!, text);
mkdirSync("evidence/verification", { recursive: true });
const audit = {
  schemaVersion: 1,
  captureId: data.run.id,
  datasetStatus: data.run.status,
  datasetSha256: createHash("sha256").update(text).digest("hex"),
  datasetBytes: Buffer.byteLength(text),
  jobs: data.jobs.length,
  snapshots: data.snapshots.length,
  resources: data.resources.length,
  availableResources: data.resources.filter((s) => s.available !== null).length,
  cycles: data.cycles.length,
  readyCycles: data.cycles.filter((c) => c.forecastStatus === "ready").length,
  hiddenPrecedingSnapshots: data.snapshots.filter((s) => s.at < data.run.start)
    .length,
  gaps: data.gaps.length,
  visibleStartMs: data.run.start,
  visibleEndMs: data.run.end,
  provenance: data.provenance,
};
writeFileSync(
  "evidence/verification/conversion.json",
  JSON.stringify(audit, null, 2) + "\n",
);
console.log(
  JSON.stringify({
    capture: data.run.id,
    bytes: Buffer.byteLength(text),
    jobs: data.jobs.length,
    snapshots: data.snapshots.length,
    cycles: data.cycles.length,
    availableResources: audit.availableResources,
  }),
);
