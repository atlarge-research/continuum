import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { convertCapture } from "../tools/normalize.ts";
import { viewAt } from "../src/replay.ts";
const root = "evidence/preliminary";
const available = existsSync(root + "/acquisition.json");
// These literals were read independently from the captured run and supporting report.
// Changes to timing, truncation of Job cohorts or rescoring historical proposals must fail.
test(
  "converts the real capture with dataset-derived timing and full hidden history",
  { skip: !available },
  () => {
    const data = convertCapture(root);
    assert.equal(data.run.id, "fns-diag-primary-s62002-forecast");
    assert.equal(data.run.originMs, 1791074830473);
    assert.equal(data.run.evaluationStart, 840000);
    assert.equal(data.run.arrivalEnd, 1680000);
    assert.equal(data.run.start, 889465);
    assert.equal(data.run.workers.length, 6);
    assert.deepEqual(
      data.run.workers.map((w) => w.slots),
      [4, 4, 4, 4, 4, 4],
    );
    assert.equal(data.snapshots.length, 1735);
    assert.equal(data.jobs.length, 602);
    assert.equal(data.cycles.length, 10);
    assert.equal(
      data.cycles.filter((c) => c.forecastStatus === "ready").length,
      9,
    );
    assert.equal(data.provenance.report.evaluatedJobs, 296);
    assert.equal(data.provenance.report.timelyJobs, 296);
    assert.ok(data.snapshots[0].at < 0);
    assert.equal(data.cycles[5].cutoff, 1301266);
    assert.equal(data.cycles[5].available, 1338988);
    assert.equal(
      data.cycles[5].candidates.find((c) => c.name === "unchanged")?.onTime,
      0.875,
    );
    assert.equal(
      data.cycles[5].candidates.find((c) => c.name === "scale-up")
        ?.allocationCoreSeconds,
      4080,
    );
    const start = viewAt(data, data.run.start);
    const end = viewAt(data, data.run.end);
    assert.equal(start.workers.length, 6);
    assert.equal(end.knownArrivals.length, 602);
    assert.deepEqual(viewAt(data, data.run.start), start);
  },
);
test(
  "source-to-display assigned requests agree at every complete captured snapshot",
  { skip: !available },
  () => {
    const data = convertCapture(root);
    const source = readFileSync(root + "/observer/cluster-state.jsonl", "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    for (let i = 0; i < source.length; i++) {
      const raw = source[i];
      const snapshot = data.snapshots[i];
      for (let w = 0; w < data.run.workers.length; w++) {
        const requests = [
          ...raw.jobs.queued,
          ...raw.jobs.active,
          ...raw.jobs.finished,
        ].filter(
          (j: any) =>
            j.node_name === data.run.workers[w].name &&
            !["Succeeded", "Failed"].includes(j.pod_phase) &&
            !["Complete", "Failed"].includes(j.job_terminal_status),
        );
        assert.equal(
          snapshot.workers[w].held.reduce((sum, j) => sum + j.cores, 0),
          requests.reduce(
            (sum: number, j: any) => sum + j.requested_cpu_count,
            0,
          ),
          `snapshot ${i}, worker ${w}`,
        );
        const worker = raw.workers.find(
          (x: any) => x.node_name === data.run.workers[w].name,
        );
        assert.equal(snapshot.workers[w].accepting, worker.schedulable);
      }
    }
  },
);
test(
  "never labels a preliminary capture accepted-final without an explicit acceptance receipt",
  { skip: !available },
  () => {
    assert.throws(() => convertCapture(root, "accepted-final"), /acceptance/i);
  },
);

test(
  "all captured forecasts, historical candidate scores and resource values agree numerically",
  { skip: !available },
  () => {
    const data = convertCapture(root);
    const journal = readFileSync(root + "/controller/journal.jsonl", "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    for (const cycle of data.cycles) {
      const proposal = journal.find(
        (r) => r.event === "cycle.proposal" && r.tick === cycle.tick,
      );
      assert.equal(cycle.action, proposal.proposal.action);
      const forecast = JSON.parse(
        readFileSync(
          `${root}/controller/cycle-${String(cycle.tick).padStart(4, "0")}/forecast/forecast.json`,
          "utf8",
        ),
      );
      assert.deepEqual(
        cycle.bins,
        (forecast.predictions ?? []).map((b: any) => ({
          start: b.start_ms - data.run.originMs,
          mean: b.mean_count,
        })),
      );
      for (const c of cycle.candidates) {
        const raw = proposal.proposal.scores.find(
          (s: any) => s.candidate === c.name,
        );
        assert.equal(
          c.onTime,
          Number.isFinite(raw.worst_late_fraction)
            ? 1 - raw.worst_late_fraction
            : null,
        );
        assert.equal(
          c.allocationCoreSeconds,
          Number.isFinite(raw.allocated_core_seconds)
            ? raw.allocated_core_seconds
            : null,
        );
        assert.deepEqual(
          c.scenarioOnTime,
          (raw.scenario_late_fractions ?? []).map((late: number) => 1 - late),
        );
      }
    }
    const raw = readFileSync(
      root + "/observer/resource-snapshots.jsonl",
      "utf8",
    )
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    assert.equal(data.resources.length, raw.length);
    data.resources.forEach((s, i) => {
      assert.equal(s.cpu, raw[i].cpu_usage_cores);
      assert.equal(s.memory, raw[i].memory_usage_mb);
      assert.equal(data.jobs[s.job].uid, raw[i].job_uid);
    });
  },
);
