import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { heldJobs, viewAt } from "../src/replay.ts";
import { resourceReservations } from "../src/presentation.ts";
import type { WorkerView } from "../src/replay.ts";
import type { Dataset } from "../src/types.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));

test("assigned memory requests retain source values independently of core requests", () => {
  const raw = {
    jobs: {
      queued: [],
      active: [
        {
          kubernetes_job_uid: "a",
          node_name: "w",
          pod_phase: "Running",
          execution_state: "running",
          requested_cpu_count: 0.5,
          requested_memory_mb: 768,
        },
      ],
      finished: [],
    },
  };
  assert.equal(heldJobs(raw)[0].memoryMiB, 768);
});

test("resource bands group fractional requests by phase and distinguish headroom from measured use", () => {
  const worker = viewAt(data, data.run.start).workers[0];
  const synthetic: WorkerView = {
    ...worker,
    occupied: 3.75,
    state: {
      ready: true,
      accepting: true,
      held: [
        { job: 0, cores: 2, memoryMiB: 2048, phase: "processing" },
        { job: 1, cores: 0.5, memoryMiB: 256, phase: "startup" },
        { job: 2, cores: 1.25, memoryMiB: 512, phase: "release" },
      ],
    },
    cpu: 0.6,
    memory: 100,
    sampled: 3,
    totalJobs: 3,
  };
  const bands = resourceReservations(synthetic);
  assert.equal(bands.outsideCpuBudget, 1);
  assert.equal(bands.cpuRequested, 3.75);
  assert.equal(bands.memoryRequested, 2816);
  assert.deepEqual(bands.segments, [
    { phase: "startup", cpu: 0.5, memory: 256 },
    { phase: "release", cpu: 1.25, memory: 512 },
    { phase: "processing", cpu: 2, memory: 2048 },
  ]);
  assert.equal(
    resourceReservations({ ...synthetic, occupied: null }).cpuRequested,
    null,
  );
  const missingMemory = structuredClone(synthetic);
  delete missingMemory.state!.held[0].memoryMiB;
  assert.equal(resourceReservations(missingMemory).memoryRequested, null);
  assert.equal(resourceReservations(missingMemory).cpuRequested, 3.75);
});

test(
  "all normalized memory requests agree with observed assigned Jobs",
  { skip: !existsSync("evidence/preliminary/observer/cluster-state.jsonl") },
  () => {
    const states = readFileSync(
      "evidence/preliminary/observer/cluster-state.jsonl",
      "utf8",
    )
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    for (const snapshot of data.snapshots) {
      const raw = states[snapshot.sourceIndex];
      const jobs = [
        ...raw.jobs.queued,
        ...raw.jobs.active,
        ...raw.jobs.finished,
      ];
      for (const worker of snapshot.workers)
        for (const held of worker.held) {
          const source = jobs.find(
            (j) => j.kubernetes_job_uid === data.jobs[held.job].uid,
          );
          assert.equal(held.memoryMiB, source.requested_memory_mb);
        }
    }
  },
);
