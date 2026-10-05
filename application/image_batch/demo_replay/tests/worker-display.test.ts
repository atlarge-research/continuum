import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { workerDisplayAt } from "../src/presentation.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
const displayAt = (cursor: number, capture = data) => {
  return workerDisplayAt(capture, cursor);
};
test("worker cards retain only the last complete published update during short collection gaps", () => {
  for (const gap of data.gaps.filter((g) => g.start >= data.run.start)) {
    const at = Math.max(gap.start, gap.available ?? gap.start);
    const strict = viewAt(data, at);
    if (strict.fresh) continue;
    const display = displayAt(at);
    const previous = data.snapshots
      .filter((s) => s.complete && s.at <= at)
      .at(-1)!;
    assert.equal(display.retained, true);
    assert.equal(display.observedAt, previous.at);
    assert.deepEqual(display.view.workers, viewAt(data, previous.at).workers);
    assert.ok(display.observedAt! <= at);
    assert.equal(
      viewAt(data, at).fresh,
      false,
      "scientific state remains unknown",
    );
  }
});
test("fresh worker updates resume immediately and reverse seeking reproduces retained state", () => {
  const at = 1423038;
  const held = displayAt(at);
  assert.equal(held.retained, true);
  const next = data.snapshots.find((s) => s.complete && s.at > at)!;
  const fresh = displayAt(next.at);
  assert.equal(fresh.retained, false);
  assert.deepEqual(fresh.view, viewAt(data, next.at));
  displayAt(data.run.end);
  assert.deepEqual(displayAt(at), held);
});
test("retention expires and does not replace absent measurements or explicit observer failures", () => {
  const capture = structuredClone(data);
  const source = capture.snapshots.find(
    (s) => s.complete && s.at >= capture.run.start,
  )!;
  capture.snapshots = [source];
  capture.resources = [];
  capture.failures = [];
  const within = displayAt(source.at + capture.run.maxGapMs + 1, capture);
  assert.equal(within.retained, true);
  assert.ok(
    within.view.workers.every((w) => w.cpu === null && w.memory === null),
  );
  const expired = displayAt(source.at + 3 * capture.run.maxGapMs + 1, capture);
  assert.equal(expired.retained, false);
  assert.equal(expired.view.fresh, false);
  capture.failures = [{ at: source.at + 1, reason: "observer failure" }];
  assert.equal(displayAt(source.at + 2, capture).view.fresh, false);
  assert.equal(displayAt(source.at + 2, capture).retained, false);
});
