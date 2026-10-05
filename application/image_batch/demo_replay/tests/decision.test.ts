import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { decisionText } from "../src/decision.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
test("preserves first physical confirmation across later gaps and reverse seeking", () => {
  const confirmed = decisionText(data, viewAt(data, 1403500));
  const gap = decisionText(data, viewAt(data, 1423038));
  assert.equal(confirmed.stage, "Physical response");
  assert.equal(gap.stage, "Physical response");
  const first = confirmed.detail.match(/\d\d:\d\d/)![0];
  // Independently read raw first confirmation: 1791076233972290048 ns.
  assert.equal(first, "08:34");
  assert.equal(gap.detail.match(/\d\d:\d\d/)![0], first);
  assert.match(gap.detail, /unavailable|gap/i);
  const cycle = data.cycles[5];
  assert.notEqual(
    decisionText(data, viewAt(data, cycle.available)).stage,
    "Physical response",
  );
  assert.deepEqual(decisionText(data, viewAt(data, 1403500)), confirmed);
});
test("fallback identifies its recorded action and retains lifecycle for physical fallback actions", () => {
  const at = data.bookmarks.find((b) => b.kind === "fallback")!.at;
  const view = viewAt(data, at);
  const status = decisionText(data, view);
  assert.match(status.title, /Keep.*admission/i);
  assert.match(status.detail, /fallback/i);
  const changed = structuredClone(data);
  const cycle = changed.cycles.find((c) => !c.valid)!;
  cycle.action = "scale-up";
  cycle.worker = 2;
  changed.capacityEvents.push({
    at,
    sequence: 999,
    timestampNs: "0",
    event: "activation.request",
    worker: 2,
    tick: cycle.tick,
    action: "scale-up",
    activationId: "fallback-test",
    actionId: null,
    status: null,
    due: at + 60000,
    error: null,
  });
  const pending = decisionText(changed, viewAt(changed, at));
  assert.match(pending.title, /Worker 3.*requested/);
  assert.match(pending.detail, /fallback/i);
});
