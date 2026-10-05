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
const cycle = (tick: number) => data.cycles.find((c) => c.tick === tick)!;

test("ready forecasts appear only after publication in the operating replay", () => {
  const first = cycle(1);
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
  assert.equal(latestReadyForecast(capture, data.run.start)?.tick, 1);
});

test("a skipped forecast update retains cycle 8 until cycle 10 publishes", () => {
  const skipped = cycle(9),
    resumed = cycle(10);
  assert.equal(skipped.forecastStatus, "not_ready");
  for (const at of [
    skipped.available - 1,
    skipped.available,
    resumed.available - 1,
  ]) {
    assert.equal(latestReadyForecast(data, at), cycle(8));
    assert.equal(forecastHistory(data, at).at(-1)?.cycle.tick, 8);
  }
  assert.equal(latestReadyForecast(data, resumed.available), resumed);
  assert.ok(
    forecastHistory(data, resumed.available + 1).every(
      (s) => s.cycle.tick !== 9,
    ),
  );
  const capture = structuredClone(data);
  capture.cycles.push({
    ...structuredClone(resumed),
    tick: 11,
    available: resumed.available + 1,
    bins: [],
  });
  assert.equal(latestReadyForecast(capture, resumed.available + 1)?.tick, 10);
});

test("historical forecasts freeze at the next ready publication without hindsight replacement", () => {
  const at = cycle(3).available + 1000;
  const before = forecastHistory(data, at);
  assert.deepEqual(
    before.map((s) => s.cycle.tick),
    [1, 2, 3],
  );
  assert.equal(before[0].start, cycle(1).available);
  assert.equal(before[0].end, cycle(2).available);
  assert.equal(before[1].end, cycle(3).available);
  assert.equal(before[2].end, at);
  assert.deepEqual(before[0].buckets, forecastBuckets(cycle(1)));
  const after = forecastHistory(data, cycle(6).available + 1000);
  assert.deepEqual(after.slice(0, 2), before.slice(0, 2));
  assert.equal(after[2].end, cycle(4).available);
  assert.deepEqual(after[2].buckets, before[2].buckets);
  for (const segment of after) {
    assert.equal(segment.start, segment.cycle.available);
    assert.ok(segment.end <= cycle(6).available + 1000);
    assert.ok(segment.end <= segment.cycle.cutoff + segment.cycle.horizonMs);
  }
});

test("expired forecast horizons stay recorded but never receive invented extensions", () => {
  const capture = structuredClone(data);
  const ready = structuredClone(cycle(8));
  const end = ready.cutoff + ready.horizonMs;
  capture.cycles = [
    ready,
    { ...structuredClone(cycle(9)), available: end + 2000 },
  ];
  const history = forecastHistory(capture, end + 10000);
  assert.equal(latestReadyForecast(capture, end + 10000), ready);
  assert.equal(history.length, 1);
  assert.equal(history[0].end, end);
  assert.ok(history[0].buckets.every((b) => b.start < end && b.end <= end));
  assert.deepEqual(
    forecastHistory(capture, end + 10000),
    forecastHistory(capture, end + 5000),
  );
  ready.available = end + 1;
  assert.deepEqual(forecastHistory(capture, end + 10000), []);
});

test("reverse seeking reconstructs the same published forecast history through fallback", () => {
  const at = cycle(9).available + 1000;
  const original = forecastHistory(data, at);
  const source = JSON.stringify(data.cycles);
  forecastHistory(data, data.run.end);
  latestReadyForecast(data, cycle(10).available);
  assert.deepEqual(forecastHistory(data, at), original);
  assert.equal(latestReadyForecast(data, at), cycle(8));
  assert.equal(JSON.stringify(data.cycles), source);
  for (const cursor of [
    cycle(1).available - 1,
    cycle(1).available,
    cycle(2).available - 1,
    at,
  ]) {
    const prefix = structuredClone(data);
    prefix.cycles = prefix.cycles.filter((c) => c.available <= cursor);
    assert.deepEqual(
      forecastHistory(prefix, cursor),
      forecastHistory(data, cursor),
    );
    assert.deepEqual(
      latestReadyForecast(prefix, cursor),
      latestReadyForecast(data, cursor),
    );
  }
});
