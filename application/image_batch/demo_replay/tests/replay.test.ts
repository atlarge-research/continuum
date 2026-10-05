import test from "node:test";
import assert from "node:assert/strict";
import {
  parseEvidenceJson,
  nsMilliseconds,
  isoMilliseconds,
  heldJobs,
  resourceAvailability,
  forecastActuals,
  viewAt,
} from "../src/replay.ts";
import type { Dataset, Snapshot } from "../src/types.ts";
const state = (at: number, started = at - 20): Snapshot => ({
  at,
  started,
  complete: true,
  workers: [{ ready: true, accepting: true, held: [] }],
  queue: [],
  processing: 0,
  assignedWaiting: 0,
  sourceIndex: at,
});
const fixture = (): Dataset => ({
  schemaVersion: 1,
  run: {
    id: "test",
    title: "test",
    status: "preliminary",
    originMs: 0,
    start: 0,
    end: 4000,
    evaluationStart: 0,
    arrivalEnd: 4000,
    followupEnd: 4000,
    maxGapMs: 1500,
    sampleMaxAgeMs: 1500,
    deadlineSeconds: 120,
    deadlineFraction: 0.95,
    network: "test",
    periodSeconds: 420,
    cadenceSeconds: 90,
    workers: [
      { name: "w", label: "Worker 1", cores: 5, slots: 4, memoryMiB: 1024 },
    ],
  },
  jobs: [
    {
      uid: "a",
      requestId: "r",
      creation: 1400,
      available: 1900,
      completed: 2300,
      terminalAvailable: 2500,
      outcome: "Complete",
    },
  ],
  snapshots: [state(500), state(1000), state(2000), state(3000)],
  resources: [],
  gaps: [],
  failures: [],
  cycles: [
    {
      tick: 1,
      cutoff: 500,
      available: 800,
      timestampNs: "800000000",
      forecastStatus: "ready",
      binMs: 1000,
      horizonMs: 1000,
      bins: [{ start: 1000, mean: 2 }],
      futures: [[1500]],
      candidates: [],
      action: "unchanged",
      worker: null,
      reason: "test",
      valid: true,
      guardrailFeasible: true,
      inputQueue: 0,
      inputSlots: 4,
      inputAssigned: 0,
      tasks: [],
    },
  ],
  capacityEvents: [],
  bookmarks: [],
  provenance: {
    sourceHost: "test",
    sourceRoot: "test",
    acquiredAt: "test",
    sourceBytes: 0,
    manifestSha256: "test",
    sourceHashes: {},
    availabilityNotes: [],
    report: {
      accepted: false,
      evaluatedJobs: 0,
      timelyJobs: 0,
      allocationBounds: null,
    },
  },
});

test("preserves nanoseconds and rounds availability up across a millisecond boundary", () => {
  const parsed = parseEvidenceJson(
    '{"recorded_at_ns":1791075719937076241,"count":3}',
  );
  assert.equal(parsed.recorded_at_ns, "1791075719937076241");
  assert.equal(parsed.count, 3);
  assert.equal(nsMilliseconds("1791075719937999999"), 1791075719938);
  assert.equal(
    isoMilliseconds("2026-10-04T01:01:59.937001+00:00", true),
    1791075719938,
  );
  assert.equal(
    isoMilliseconds("2026-10-04T01:01:59.937001+00:00"),
    1791075719937,
  );
});
test("counts assigned startup and release occupancy while excluding terminal and unassigned Jobs", () => {
  const job = (
    uid: string,
    node: string | null,
    execution_state: string,
    pod_phase: string,
    cores = 1,
  ) => ({
    kubernetes_job_uid: uid,
    node_name: node,
    execution_state,
    pod_phase,
    requested_cpu_count: cores,
    job_terminal_status: null,
  });
  const raw = {
    jobs: {
      queued: [
        job("startup", "w", "waiting", "Pending"),
        job("queue", null, "waiting", "Pending"),
      ],
      active: [job("processing", "w", "running", "Running", 2)],
      finished: [
        job("release", "w", "terminated", "Running"),
        job("terminal", "w", "terminated", "Succeeded"),
      ],
    },
  };
  assert.deepEqual(heldJobs(raw), [
    { uid: "startup", cores: 1, phase: "startup", worker: "w" },
    { uid: "processing", cores: 2, phase: "processing", worker: "w" },
    { uid: "release", cores: 1, phase: "release", worker: "w" },
  ]);
});
test("delays resource samples to a proved later serialized collection and preserves unknown publication", () => {
  assert.deepEqual(
    resourceAvailability(50, 100, [state(180, 90), state(220, 200)], true),
    { available: 220, proofState: 220, basis: "next_serialized_collection" },
  );
  assert.equal(
    resourceAvailability(50, 100, [state(180, 90)], true).available,
    null,
  );
  assert.equal(
    resourceAvailability(50, 100, [state(220, 200)], false).available,
    null,
  );
  assert.equal(
    resourceAvailability(150, 100, [state(220, 200)], true).available,
    null,
  );
});
test("releases a forecast at its publication boundary and actual arrivals only after observation", () => {
  const data = fixture();
  assert.equal(viewAt(data, 799).cycle, null);
  assert.equal(viewAt(data, 800).cycle!.tick, 1);
  assert.equal(viewAt(data, 1800).knownArrivals.length, 0);
  assert.equal(viewAt(data, 1900).knownArrivals.length, 1);
  assert.equal(viewAt(data, 2499).completed, 0);
  assert.equal(viewAt(data, 2500).completed, 1);
});
test("forecast quality waits for closed covered bins and is unavailable across observation gaps", () => {
  const data = fixture();
  assert.equal(forecastActuals(data, data.cycles[0], 1999)[0].actual, null);
  assert.equal(forecastActuals(data, data.cycles[0], 2000)[0].actual, 1);
  data.gaps = [{ start: 1600, end: 1800, reason: "capture failed" }];
  assert.equal(forecastActuals(data, data.cycles[0], 3000)[0].actual, null);
});
test("reverse seeking restores all derived state and removes future evidence", () => {
  const data = fixture();
  const first = viewAt(data, 800);
  viewAt(data, 3000);
  viewAt(data, 1900);
  assert.deepEqual(viewAt(data, 800), first);
  assert.equal(viewAt(data, 800).completed, 0);
  assert.equal(viewAt(data, 800).knownArrivals.length, 0);
  assert.equal(viewAt(data, 800).resources.length, 0);
});
test("marks stale or incomplete physical observations unknown without replacing them with zeros", () => {
  const data = fixture();
  data.snapshots = [{ ...state(500), queue: [0] }];
  const stale = viewAt(data, 2001);
  assert.equal(stale.fresh, false);
  assert.equal(stale.snapshot!.queue.length, 1);
  data.snapshots = [{ ...state(500), complete: false }];
  assert.equal(viewAt(data, 501).fresh, false);
});
