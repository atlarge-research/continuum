import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { forecastBuckets } from "../src/presentation.ts";
import {
  forecastHistory,
  latestReadyForecast,
} from "../src/forecast-history.ts";

const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
const ready = data.cycles.filter(
  (c) => c.forecastStatus === "ready" && c.bins.length,
);

/** A synthetic skipped update between two real forecast templates, never packaged evidence. */
function skippedUpdate() {
  const capture = structuredClone(data);
  const first = structuredClone(ready[0]);
  const resumed = structuredClone(ready[1]);
  const skipped = {
    ...structuredClone(first),
    tick: first.tick + 1,
    available: first.available + 1000,
    forecastStatus: "not_ready",
    forecastReasons: ["state_stale"],
    valid: false,
    bins: [],
  };
  resumed.tick = first.tick + 2;
  capture.cycles = [first, skipped, resumed];
  return { capture, first, skipped, resumed };
}

test("ready forecasts appear only after publication in the operating replay", () => {
  const first = ready[0];
  assert.equal(latestReadyForecast(data, first.available - 1), null);
  assert.equal(latestReadyForecast(data, first.available), first);
  assert.deepEqual(forecastHistory(data, first.available), []);
  const capture = structuredClone(data);
  capture.cycles.unshift({
    ...structuredClone(first),
    tick: 0,
    available: data.run.start - 1,
  });
  assert.equal(latestReadyForecast(capture, data.run.start - 1), null);
  assert.equal(latestReadyForecast(capture, data.run.start)?.tick, first.tick);
});

test("a synthetic skipped update retains the preceding forecast until a ready publication", () => {
  const { capture, first, skipped, resumed } = skippedUpdate();
  assert.equal(skipped.forecastStatus, "not_ready");
  assert.ok(first.cutoff + first.horizonMs > resumed.available);
  for (const at of [
    skipped.available - 1,
    skipped.available,
    resumed.available - 1,
  ]) {
    assert.equal(latestReadyForecast(capture, at), first);
    assert.equal(forecastHistory(capture, at).at(-1)?.cycle.tick, first.tick);
  }
  assert.equal(latestReadyForecast(capture, resumed.available), resumed);
  assert.ok(
    forecastHistory(capture, resumed.available + 1).every(
      (s) => s.cycle.tick !== skipped.tick,
    ),
  );
  capture.cycles.push({
    ...structuredClone(resumed),
    tick: resumed.tick + 1,
    available: resumed.available + 1,
    bins: [],
  });
  assert.equal(
    latestReadyForecast(capture, resumed.available + 1)?.tick,
    resumed.tick,
  );
});

test("historical forecasts freeze at the next ready publication without hindsight replacement", () => {
  const at = ready[2].available + 1000;
  const before = forecastHistory(data, at);
  assert.deepEqual(
    before.map((s) => s.cycle.tick),
    ready.slice(0, 3).map((c) => c.tick),
  );
  assert.equal(before[0].start, ready[0].available);
  assert.equal(before[0].end, ready[1].available);
  assert.equal(before[1].end, ready[2].available);
  assert.equal(before[2].end, at);
  assert.deepEqual(before[0].buckets, forecastBuckets(ready[0]));
  const after = forecastHistory(data, ready[5].available + 1000);
  assert.deepEqual(after.slice(0, 2), before.slice(0, 2));
  assert.equal(after[2].end, ready[3].available);
  assert.deepEqual(after[2].buckets, before[2].buckets);
  for (const segment of after) {
    assert.equal(segment.start, segment.cycle.available);
    assert.ok(segment.end <= ready[5].available + 1000);
    assert.ok(segment.end <= segment.cycle.cutoff + segment.cycle.horizonMs);
  }
});

test("expired forecast horizons stay recorded but never receive invented extensions", () => {
  const { capture, first, skipped } = skippedUpdate();
  const end = first.cutoff + first.horizonMs;
  capture.cycles = [first, { ...skipped, available: end + 2000 }];
  const history = forecastHistory(capture, end + 10000);
  assert.equal(latestReadyForecast(capture, end + 10000), first);
  assert.equal(history.length, 1);
  assert.equal(history[0].end, end);
  assert.ok(history[0].buckets.every((b) => b.start < end && b.end <= end));
  assert.deepEqual(
    forecastHistory(capture, end + 10000),
    forecastHistory(capture, end + 5000),
  );
  first.available = end + 1;
  assert.deepEqual(forecastHistory(capture, end + 10000), []);
});

test("reverse seeking reconstructs published history through a synthetic fallback", () => {
  const { capture, first, skipped, resumed } = skippedUpdate();
  const at = skipped.available + 1000;
  const original = forecastHistory(capture, at);
  const source = JSON.stringify(capture.cycles);
  forecastHistory(capture, data.run.end);
  latestReadyForecast(capture, resumed.available);
  assert.deepEqual(forecastHistory(capture, at), original);
  assert.equal(latestReadyForecast(capture, at), first);
  assert.equal(JSON.stringify(capture.cycles), source);
  for (const cursor of [
    first.available - 1,
    first.available,
    skipped.available - 1,
    at,
  ]) {
    const prefix = structuredClone(capture);
    prefix.cycles = prefix.cycles.filter((c) => c.available <= cursor);
    assert.deepEqual(
      forecastHistory(prefix, cursor),
      forecastHistory(capture, cursor),
    );
    assert.deepEqual(
      latestReadyForecast(prefix, cursor),
      latestReadyForecast(capture, cursor),
    );
  }
});
