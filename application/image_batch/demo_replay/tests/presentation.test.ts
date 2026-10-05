import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import {
  deadlineStatus,
  resourceUsage,
  forecastBuckets,
  selectedForecast,
} from "../src/presentation.ts";
import { comparisonFromReport } from "../tools/comparison.ts";
const privateEvidence = existsSync(
  "evidence/preliminary/supporting-metrics.json",
);
const capture: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
test("service outcomes use application finish and wait for both success and published finish evidence", () => {
  const data = structuredClone(capture);
  data.run.evaluationStart = 0;
  data.run.arrivalEnd = 10000;
  data.run.deadlineSeconds = 2;
  data.jobs = [
    {
      uid: "early",
      requestId: null,
      creation: 1000,
      available: 1100,
      completed: 4000,
      terminalAvailable: 4500,
      outcome: "Complete",
      serviceFinished: 2900,
      serviceAvailable: 3200,
      evaluated: true,
    },
    {
      uid: "late",
      requestId: null,
      creation: 1000,
      available: 1100,
      completed: 4000,
      terminalAvailable: 4100,
      outcome: "Complete",
      serviceFinished: 3100,
      serviceAvailable: 3300,
      evaluated: true,
    },
    {
      uid: "unknown",
      requestId: null,
      creation: 2000,
      available: 2100,
      completed: null,
      terminalAvailable: null,
      outcome: null,
      evaluated: true,
    },
    {
      uid: "future",
      requestId: null,
      creation: 6000,
      available: 6100,
      completed: 7000,
      terminalAvailable: 7100,
      outcome: "Complete",
      serviceFinished: 6900,
      serviceAvailable: 7000,
      evaluated: true,
    },
    {
      uid: "warmup",
      requestId: null,
      creation: -1000,
      available: 0,
      completed: 1,
      terminalAvailable: 2,
      outcome: "Complete",
      serviceFinished: 1,
      serviceAvailable: 2,
      evaluated: false,
    },
  ];
  assert.deepEqual(deadlineStatus(data, 4000), {
    onTime: 0,
    missed: 0,
    pending: 3,
    confirmed: 0,
    percent: null,
  });
  assert.deepEqual(deadlineStatus(data, 4500), {
    onTime: 1,
    missed: 1,
    pending: 1,
    confirmed: 2,
    percent: 50,
  });
  assert.deepEqual(deadlineStatus(data, 4000), {
    onTime: 0,
    missed: 0,
    pending: 3,
    confirmed: 0,
    percent: null,
  });
});
test("worker percentages preserve partial samples and values above capacity", () => {
  const worker = viewAt(capture, capture.run.start).workers[0];
  const full = { ...worker, cpu: 6, memory: 8192, sampled: 2, totalJobs: 2 };
  assert.deepEqual(resourceUsage(full), {
    cpuPercent: 120,
    memoryPercent: 50,
    coverage: "complete",
  });
  assert.equal(resourceUsage({ ...full, sampled: 1 }).coverage, "partial");
  assert.equal(
    resourceUsage({ ...full, cpu: null, memory: null, sampled: 0 }).coverage,
    "missing",
  );
});
test("forecast selection never reveals future publications and excludes warm-up", () => {
  const first = capture.cycles.find((c) => c.available >= capture.run.start)!;
  const future = capture.cycles[5];
  assert.equal(
    selectedForecast(capture, first.available, future.tick)?.tick,
    first.tick,
  );
  assert.equal(
    selectedForecast(capture, future.available, first.tick)?.tick,
    first.tick,
  );
  assert.equal(
    selectedForecast(capture, future.available, null)?.tick,
    future.tick,
  );
});
test("forecast range sums each scenario within display bins rather than adding per-bin extrema", () => {
  const cycle = {
    ...capture.cycles[0],
    cutoff: 0,
    available: 0,
    binMs: 5000,
    horizonMs: 15000,
    bins: [
      { start: 0, mean: 1 },
      { start: 5000, mean: 2 },
      { start: 10000, mean: 3 },
    ],
    futures: [[1, 5001], [10001, 10002, 10003], []],
  };
  const buckets = forecastBuckets(cycle, 15000);
  assert.deepEqual(buckets, [
    { start: 0, end: 15000, mean: 6, scenarios: [2, 3, 0], min: 0, max: 3 },
  ]);
});
test(
  "comparison extracts all matched report runs and retains uncertainty, settings and preliminary status",
  { skip: !privateEvidence },
  () => {
    const report = JSON.parse(
      readFileSync("evidence/preliminary/supporting-metrics.json", "utf8"),
    );
    const comparison = comparisonFromReport(
      report,
      capture.run.id,
      "preliminary",
      "report-hash",
    );
    assert.equal(comparison.status, "preliminary");
    assert.equal(comparison.sourceSha256, "report-hash");
    assert.equal(comparison.runs.length, 6);
    for (const raw of report.closed_loop_reports.flatMap((r: any) => r.runs)) {
      const result = comparison.runs.find((r) => r.captureId === raw.run_id)!;
      assert.equal(result.timelyJobs, raw.responses.deadline_met);
      assert.equal(result.jobs, raw.responses.jobs);
      assert.deepEqual(
        result.allocationBounds,
        raw.allocation.allocated_core_seconds_bounds,
      );
      assert.equal(
        result.p95CompletedSeconds,
        raw.responses.completed_response_p95_seconds,
      );
    }
    const altered = structuredClone(report);
    altered.closed_loop_reports[0].runs[0].arrival_plan_sha256 = "different";
    assert.throws(
      () => comparisonFromReport(altered, capture.run.id, "preliminary", "h"),
      /matched|workload/i,
    );
    assert.throws(
      () => comparisonFromReport(report, capture.run.id, "accepted-final", "h"),
      /accept/i,
    );
  },
);

import { convertCapture } from "../tools/normalize.ts";
test(
  "application completion and deadline counts agree with the report cohort",
  { skip: !privateEvidence },
  () => {
    const data = convertCapture("evidence/preliminary");
    const report = JSON.parse(
      readFileSync("evidence/preliminary/supporting-metrics.json", "utf8"),
    );
    const raw = report.closed_loop_reports
      .flatMap((r: any) => r.runs)
      .find((r: any) => r.run_id === data.run.id);
    for (const c of raw.responses.cohort) {
      const j = data.jobs.find((j) => j.uid === c.uid)!;
      assert.equal(j.evaluated, true);
      assert.equal(j.serviceFinished! + data.run.originMs, c.finish_ms);
      assert.ok(
        j.serviceAvailable !== null &&
          j.serviceAvailable! >= j.serviceFinished!,
      );
    }
    const last = Math.max(
      data.run.end,
      ...data.jobs.map((j) => j.terminalAvailable ?? 0),
    );
    const status = deadlineStatus(data, last);
    assert.equal(status.onTime, raw.responses.deadline_met);
    assert.equal(status.confirmed + status.pending, raw.responses.jobs);
  },
);
import { observedBins } from "../src/presentation.ts";
test("arrival history counts only published observations and marks open or uncovered bins", () => {
  const data = structuredClone(capture);
  data.run.start = 0;
  data.run.maxGapMs = 20000;
  data.snapshots = [
    {
      at: 0,
      started: 0,
      complete: true,
      workers: [],
      queue: [],
      processing: 0,
      assignedWaiting: 0,
      sourceIndex: 0,
    },
    {
      at: 15000,
      started: 15000,
      complete: true,
      workers: [],
      queue: [],
      processing: 0,
      assignedWaiting: 0,
      sourceIndex: 1,
    },
  ];
  data.gaps = [];
  data.jobs = [
    {
      uid: "known",
      requestId: null,
      creation: 1000,
      available: 2000,
      completed: null,
      terminalAvailable: null,
      outcome: null,
    },
    {
      uid: "unpublished",
      requestId: null,
      creation: 3000,
      available: 16000,
      completed: null,
      terminalAvailable: null,
      outcome: null,
    },
  ];
  assert.deepEqual(observedBins(data, 0, 15000, 15000), [
    { start: 0, end: 15000, count: 1, complete: true, open: false },
  ]);
  assert.equal(observedBins(data, 0, 15000, 10000)[0].open, true);
  data.gaps = [{ start: 4000, end: 5000, reason: "missing" }];
  assert.equal(observedBins(data, 0, 15000, 15000)[0].complete, false);
});
import { predictedOccupancy } from "../src/presentation.ts";
test("predicted worker reservations are unavailable outside the recorded prediction horizon", () => {
  const cycle = {
    ...capture.cycles[0],
    cutoff: 100,
    action: "unchanged",
    available: 150,
    horizonMs: 1000,
    tasks: [
      {
        id: 1,
        scenario: 0,
        candidate: "unchanged",
        worker: 0,
        creation: 100,
        scheduled: 200,
        finished: 900,
        cores: 2,
        cohort: "future",
      },
    ],
  };
  assert.equal(predictedOccupancy(cycle, 0, 250, 0), 2);
  assert.equal(predictedOccupancy(cycle, 0, 1000, 0), 0);
  assert.equal(predictedOccupancy(cycle, 0, 1200, 0), null);
  assert.equal(predictedOccupancy(cycle, 0, 99, 0), null);
});
