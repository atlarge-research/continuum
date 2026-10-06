import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  forecastEvaluation as evaluate,
  observedBins,
} from "../src/presentation.ts";
import { forecastChart } from "../src/charts.ts";
import { viewAt } from "../src/replay.ts";
import type { Cycle, Dataset } from "../src/types.ts";

const capture: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
const fixture = () => {
  const data = structuredClone(capture);
  data.run.start = 0;
  data.run.end = 50000;
  data.run.maxGapMs = 1500;
  data.gaps = [];
  data.failures = [];
  data.resources = [];
  data.capacityEvents = [];
  data.snapshots = Array.from({ length: 51 }, (_, index) => ({
    ...structuredClone(capture.snapshots[0]),
    at: index * 1000,
    started: index * 1000,
    complete: true,
    queue: [],
    processing: 0,
    assignedWaiting: 0,
    workers: data.run.workers.map(() => ({
      ready: true,
      accepting: true,
      held: [],
    })),
  }));
  data.jobs = [7000, 7100, 17000, 22000, 27000, 25000, 32000].map(
    (creation, index) => ({
      uid: String(index),
      requestId: null,
      creation,
      available: index === 5 ? 35000 : creation + 10,
      completed: null,
      terminalAvailable: null,
      outcome: null,
    }),
  );
  const cycle: Cycle = {
    ...structuredClone(capture.cycles[0]),
    cutoff: 1000,
    available: 19000,
    binMs: 5000,
    horizonMs: 40000,
    bins: [2, 0, 0, 0, 1, 0, 2, 0].map((mean, index) => ({
      start: 1000 + index * 5000,
      mean,
    })),
    futures: [
      [7000, 17000],
      [7000, 22000, 27000],
      [7100, 25000],
    ],
    forecastStatus: "ready",
    valid: true,
    tasks: [],
  };
  data.cycles = [cycle];
  return { data, cycle };
};

test("Analysis error compares aggregate predictions to arrivals in the same off-grid intervals", () => {
  const { data, cycle } = fixture();
  const result = evaluate(data, cycle, 31000);
  assert.equal(result.binMs, 15000);
  assert.deepEqual(result.bins.slice(0, 2), [
    { start: 1000, end: 16000, expected: 2, actual: 2, complete: true },
    { start: 16000, end: 31000, expected: 1, actual: 3, complete: true },
  ]);
  // Errors within the first interval cancel after aggregation; scaling native MAE would differ.
  assert.equal(result.meanAbsoluteError, 1);
  const observed = observedBins(data, 1000, 31000, 31000, 15000, 1000);
  assert.deepEqual(
    observed.map(({ start, end, count }) => ({ start, end, count })),
    [
      { start: 1000, end: 16000, count: 2 },
      { start: 16000, end: 31000, count: 3 },
    ],
  );
  assert.equal(observedBins(data, 1000, 31000, 31000)[0].end, 15000);
});

test("Analysis error waits for forecast and observation publication and rewinds exactly", () => {
  const { data, cycle } = fixture();
  assert.equal(evaluate(data, cycle, 18999).meanAbsoluteError, null);
  assert.equal(evaluate(data, cycle, 18999).bins.length, 0);
  assert.equal(evaluate(data, cycle, 19000).meanAbsoluteError, 0);
  const beforeLateObservation = evaluate(data, cycle, 31000);
  assert.equal(evaluate(data, cycle, 34999).bins[1].actual, 3);
  assert.equal(evaluate(data, cycle, 35000).bins[1].actual, 4);
  assert.equal(evaluate(data, cycle, 35000).meanAbsoluteError, 1.5);
  assert.deepEqual(evaluate(data, cycle, 31000), beforeLateObservation);
  assert.deepEqual(evaluate(data, null, 50000), {
    binMs: 15000,
    bins: [],
    meanAbsoluteError: null,
  });
});

test("Analysis error excludes observation gaps, open intervals and partial horizon groups", () => {
  const { data, cycle } = fixture();
  data.gaps = [
    { start: 20000, end: 21000, available: 21000, reason: "capture gap" },
  ];
  const result = evaluate(data, cycle, 41000);
  assert.deepEqual(
    result.bins.map(({ complete }) => complete),
    [true, false, false],
  );
  assert.equal(result.bins[1].actual, null);
  assert.equal(result.bins[2].end - result.bins[2].start, 10000);
  assert.equal(result.bins[2].actual, null);
  assert.equal(result.meanAbsoluteError, 0);
  data.gaps = [];
  assert.equal(evaluate(data, cycle, 30999).bins[1].complete, false);
  data.snapshots = data.snapshots.filter(({ at }) => at !== 8000);
  assert.equal(evaluate(data, cycle, 41000).bins[0].complete, false);
});

test("Analysis chart identifies its selected future and aligns bars without changing Overview", () => {
  const { data, cycle } = fixture();
  const view = viewAt(data, 31000);
  const detail = forecastChart(
    data,
    view,
    { width: 620, height: 280 },
    {
      cycle,
      detail: true,
      scenario: 1,
    },
  );
  assert.match(detail, /data-bin-start="1000" data-bin-end="16000"/);
  assert.match(
    detail,
    /class="future-line scenario-1 selected"[^>]*data-scenario="1"[^>]*data-selected="true"/,
  );
  assert.equal((detail.match(/data-selected="true"/g) ?? []).length, 1);
  assert.equal((detail.match(/class="future-line/g) ?? []).length, 3);
  const overview = forecastChart(data, view);
  assert.equal(forecastChart(data, view, undefined, { scenario: 1 }), overview);
  assert.equal((detail.match(/class="gridline"/g) ?? []).length, 4);
  assert.equal((overview.match(/class="gridline"/g) ?? []).length, 3);
});

test("Analysis error excludes buckets clipped by the visible operating start", () => {
  const { data, cycle } = fixture();
  data.run.start = 11000;
  const result = evaluate(data, cycle, 31000);
  assert.equal(result.bins[0].complete, false);
  assert.equal(result.bins[0].actual, null);
  assert.equal(result.bins[1].complete, true);
  assert.equal(result.meanAbsoluteError, 2);
});

test("a pinned Analysis forecast keeps its historical chart start after its horizon expires", () => {
  const { data, cycle } = fixture();
  cycle.cutoff += 240000;
  cycle.available += 240000;
  cycle.bins = cycle.bins.map((bin) => ({ ...bin, start: bin.start + 240000 }));
  cycle.futures = cycle.futures.map((future) =>
    future.map((at) => at + 240000),
  );
  const early = forecastChart(
    data,
    viewAt(data, 271000),
    { width: 620, height: 280 },
    { cycle, detail: true },
  );
  const late = forecastChart(
    data,
    viewAt(data, 500000),
    { width: 620, height: 280 },
    { cycle, detail: true },
  );
  const startLabel = '<text x="46" y="277" text-anchor="start">01:01</text>';
  assert.ok(early.includes(startLabel));
  assert.ok(late.includes(startLabel));
  assert.match(late, /Forecast horizon elapsed/);
  assert.match(late, /class="forecast-line current"/);
});
