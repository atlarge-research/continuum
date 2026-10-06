import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { decisionText } from "../src/decision.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
test("preserves final physical confirmation across a synthetic observation gap and reverse seeking", () => {
  const cycle = data.cycles.find((c) => c.action === "scale-down")!;
  const request = data.capacityEvents.find(
    (e) => e.tick === cycle.tick && e.event === "action.request",
  )!;
  const confirmation = data.snapshots.find(
    (s) =>
      s.at >= request.at && s.complete && !s.workers[cycle.worker!].accepting,
  )!;
  const capture = structuredClone(data);
  const at = confirmation.at + 1;
  // The confirmation is real; only this later unavailable observation is synthetic.
  capture.snapshots.push({
    ...structuredClone(confirmation),
    at,
    started: at,
    complete: false,
  });
  capture.snapshots.sort((a, b) => a.at - b.at);
  capture.gaps.push({
    start: at,
    end: at + 1000,
    available: at,
    reason: "synthetic membership gap",
  });
  const confirmed = decisionText(capture, viewAt(capture, confirmation.at));
  const gap = decisionText(capture, viewAt(capture, at));
  assert.equal(confirmed.stage, "Physical response");
  assert.equal(gap.stage, "Physical response");
  assert.equal(confirmed.confirmedAt, confirmation.at);
  assert.equal(confirmed.currentConfirmed, true);
  assert.equal(gap.confirmedAt, confirmation.at);
  assert.equal(gap.currentConfirmed, false);
  assert.equal(
    decisionText(capture, viewAt(capture, cycle.available)).confirmedAt,
    undefined,
  );
  const first = confirmed.detail.match(/\d\d:\d\d/)![0];
  // Independently read final raw confirmation: 1791197314498321920 ns.
  assert.equal(first, "00:01");
  assert.equal(gap.detail.match(/\d\d:\d\d/)![0], first);
  assert.match(gap.detail, /unavailable|gap/i);
  assert.notEqual(
    decisionText(capture, viewAt(capture, cycle.available)).stage,
    "Physical response",
  );
  decisionText(capture, viewAt(capture, data.run.end));
  assert.deepEqual(
    decisionText(capture, viewAt(capture, confirmation.at)),
    confirmed,
  );
});
test("synthetic fallback identifies its action and retains physical action lifecycle", () => {
  const changed = structuredClone(data);
  const cycle = structuredClone(changed.cycles[0]);
  cycle.valid = false;
  cycle.forecastStatus = "not_ready";
  cycle.forecastReasons = ["state_stale"];
  cycle.bins = [];
  cycle.action = "unchanged";
  cycle.worker = null;
  changed.cycles = [cycle];
  changed.capacityEvents = [];
  const at = cycle.available;
  const view = viewAt(changed, at);
  const status = decisionText(changed, view);
  assert.match(status.title, /Keep.*admission/i);
  assert.match(status.detail, /fallback/i);
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
