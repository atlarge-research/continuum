import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { convertCapture } from "../tools/normalize.ts";
import { deadlineStatus } from "../src/presentation.ts";
import { viewAt } from "../src/replay.ts";
import { createHash } from "node:crypto";
const root = "evidence/accepted-final";
const available = existsSync(root + "/acceptance.json");
const json = (path: string) =>
  JSON.parse(readFileSync(root + "/" + path, "utf8"));
const convert = () =>
  convertCapture(root, "accepted-final", root + "/acceptance.json");

test(
  "accepted final capture preserves independently inspected timing, cohort and publication proof",
  { skip: !available },
  () => {
    const data = convert();
    // Inspected from the sealed capture, not calculated by the converter.
    assert.equal(
      data.run.id,
      "fns-final-trio-b-forecast-s72001-s72001-forecast",
    );
    assert.equal(data.run.evaluationStart, 1680000);
    assert.equal(data.run.arrivalEnd, 2520000);
    assert.equal(data.run.followupEnd, 2700000);
    assert.equal(data.run.periodSeconds, 840);
    assert.equal(data.run.cadenceSeconds, 90);
    assert.equal(data.run.deadlineSeconds, 120);
    assert.equal(data.jobs.length, 626);
    assert.equal(data.snapshots.length, 2598);
    assert.equal(data.resources.length, 3492);
    assert.equal(data.cycles.length, 10);
    assert.ok(
      data.cycles.every((c) => c.valid && c.forecastStatus === "ready"),
    );
    assert.equal(data.provenance.producerProof, true);
    assert.equal(data.provenance.report.evaluatedJobs, 227);
    assert.equal(data.provenance.report.timelyJobs, 227);
    assert.ok(data.snapshots[0].at < data.run.evaluationStart);
    assert.ok(data.run.start >= data.run.evaluationStart);
    assert.equal(data.run.start, data.cycles[0].available);
    assert.deepEqual(
      data.comparison!.runs.map((r) => r.seed),
      [72001, 72001, 72001],
    );
    assert.ok(
      data.bookmarks.every(
        (b) => b.at >= data.run.start && b.at <= data.run.end,
      ),
    );
    assert.ok(data.bookmarks.some((b) => b.label === "Scale-down decision"));
    assert.ok(data.bookmarks.some((b) => b.label === "Scale-up confirmed"));
    assert.ok(!data.bookmarks.some((b) => b.label === "Update skipped"));
  },
);

test(
  "final replay deadlines agree with raw terminal completion and independently audited p95",
  { skip: !available },
  () => {
    const data = convert();
    const report = json("supporting-metrics.json").runs.find(
      (r: any) => r.arm === "forecast",
    );
    const audit = json("accepted/independent-monitor-audit.json").rows.find(
      (r: any) => r.arm === "forecast",
    );
    const cohort = report.responses.cohort;
    assert.equal(cohort.length, 227);
    const responses: number[] = [];
    for (const raw of cohort) {
      const job = data.jobs.find((j) => j.uid === raw.uid)!;
      assert.ok(job.evaluated);
      assert.equal(job.creation + data.run.originMs, raw.creation_ms);
      assert.equal(job.completed! + data.run.originMs, raw.job_finish_ms);
      const at = Math.max(job.terminalAvailable!, job.completed!);
      assert.equal(deadlineStatus({ ...data, jobs: [job] }, at - 1).pending, 1);
      assert.equal(deadlineStatus({ ...data, jobs: [job] }, at).onTime, 1);
      responses.push((job.completed! - job.creation) / 1000);
    }
    responses.sort((a, b) => a - b);
    const index = (responses.length - 1) * 0.95;
    const lower = Math.floor(index),
      upper = Math.ceil(index);
    const p95 =
      responses[lower] +
      (responses[upper] - responses[lower]) * (index - lower);
    assert.ok(Math.abs(p95 - audit.p95_seconds) < 1e-9);
    assert.equal(data.jobs.filter((j) => j.evaluated).length, audit.jobs);
    assert.equal(deadlineStatus(data, data.run.end).onTime, audit.deadline_met);
    assert.ok(cohort.some((j: any) => j.job_finish_ms !== j.finish_ms));
  },
);

test(
  "final forward and backward seeking never exposes future observations",
  { skip: !available },
  () => {
    const data = convert();
    for (const cycle of data.cycles) {
      for (const at of [
        cycle.available - 1,
        cycle.available,
        cycle.available + 1000,
      ]) {
        const original = viewAt(data, at);
        assert.ok(original.knownArrivals.every((j) => j.available <= at));
        assert.ok(!original.cycle || original.cycle.available <= at);
        viewAt(data, data.run.end);
        assert.deepEqual(viewAt(data, at), original);
      }
    }
  },
);

test(
  "final physical requests, admission and measured resources agree at every source snapshot",
  { skip: !available },
  () => {
    const data = convert();
    const lines = (path: string) =>
      readFileSync(root + "/" + path, "utf8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line));
    const states = lines("observer/cluster-state.jsonl");
    for (const [i, raw] of states.entries()) {
      for (const [w, worker] of data.run.workers.entries()) {
        const held = [
          ...raw.jobs.queued,
          ...raw.jobs.active,
          ...raw.jobs.finished,
        ].filter(
          (j: any) =>
            j.node_name === worker.name &&
            !["Succeeded", "Failed"].includes(j.pod_phase) &&
            !["Complete", "Failed"].includes(j.job_terminal_status),
        );
        assert.equal(
          data.snapshots[i].workers[w].held.reduce(
            (sum, j) => sum + j.cores,
            0,
          ),
          held.reduce((sum: number, j: any) => sum + j.requested_cpu_count, 0),
          `CPU snapshot ${i}/${w}`,
        );
        assert.equal(
          data.snapshots[i].workers[w].accepting,
          raw.workers.find((j: any) => j.node_name === worker.name).schedulable,
          `admission snapshot ${i}/${w}`,
        );
      }
    }
    const resources = lines("observer/resource-snapshots.jsonl");
    data.resources.forEach((r, i) => {
      assert.equal(r.cpu, resources[i].cpu_usage_cores);
      assert.equal(r.memory, resources[i].memory_usage_mb);
      assert.equal(data.jobs[r.job].uid, resources[i].job_uid);
      assert.ok(
        r.available === null ||
          (r.available >= r.observation && r.available >= r.capture),
      );
    });
  },
);

test(
  "all final issued forecasts and selected scores remain the recorded native results",
  { skip: !available },
  () => {
    const data = convert();
    const proposals = readFileSync(root + "/controller/journal.jsonl", "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
      .filter((r) => r.event === "cycle.proposal");
    for (const cycle of data.cycles) {
      const proposal = proposals.find((r) => r.tick === cycle.tick);
      const forecast = json(
        `controller/cycle-${String(cycle.tick).padStart(4, "0")}/forecast/forecast.json`,
      );
      assert.equal(cycle.action, proposal.proposal.action);
      assert.deepEqual(
        cycle.bins,
        forecast.predictions.map((b: any) => ({
          start: b.start_ms - data.run.originMs,
          mean: b.mean_count,
        })),
      );
      cycle.futures.forEach((future, i) =>
        assert.equal(future.length, forecast.scenario_job_counts[i]),
      );
      for (const c of cycle.candidates) {
        const score = proposal.proposal.scores.find(
          (r: any) => r.candidate === c.name,
        );
        assert.equal(c.onTime, 1 - score.worst_late_fraction);
        assert.equal(c.allocationCoreSeconds, score.allocated_core_seconds);
      }
      assert.ok(cycle.tasks.length > 0);
      assert.ok(
        cycle.tasks.every((t) => ["future", "backlog"].includes(t.cohort)),
      );
    }
  },
);

test(
  "terminal deadline outcomes wait for publication of the completion timestamp",
  { skip: !available },
  () => {
    const data = convert();
    const events = readFileSync(
      root + "/observer/observer-events.jsonl",
      "utf8",
    )
      .trim()
      .split("\n")
      .map((line) =>
        JSON.parse(
          line.replace(/("timestamp_unix_ns"\s*:\s*)(\d+)/g, '$1"$2"'),
        ),
      );
    for (const event of events.filter((e) => e.event_type === "task.emitted")) {
      const job = data.jobs.find(
        (j) => j.uid === event.details.kubernetes_job_uid,
      )!;
      if (job.outcome !== "Complete" || job.completed === null) continue;
      const publication =
        Number((BigInt(event.timestamp_unix_ns) + 999999n) / 1000000n) -
        data.run.originMs;
      assert.ok(
        job.terminalAvailable! >= publication,
        `completion timestamp leaked for ${job.uid}`,
      );
      if (job.evaluated)
        assert.equal(
          deadlineStatus({ ...data, jobs: [job] }, publication - 1).onTime,
          0,
        );
    }
  },
);

test(
  "public replay provenance keeps capture identities and proofs without private machine paths",
  { skip: !available },
  () => {
    const acquisition = json("acquisition.json");
    const receipt = json("acceptance.json");
    const digest = (path: string) =>
      createHash("sha256")
        .update(readFileSync(root + "/" + path))
        .digest("hex");
    const bundled = JSON.parse(readFileSync("data/replay.json", "utf8"));
    for (const data of [convert(), bundled]) {
      const provenance = JSON.stringify(data.provenance);
      assert.ok(!provenance.includes(acquisition.sourceRoot));
      assert.ok(!provenance.includes(receipt.evidenceLocation));
      assert.equal(data.run.id, receipt.captureId);
      assert.equal(data.provenance.sourceHost, acquisition.sourceHost);
      assert.equal(data.provenance.manifestSha256, digest("acquisition.json"));
      assert.equal(data.provenance.receipt.captureId, receipt.captureId);
      assert.equal(data.provenance.receipt.sha256, digest("acceptance.json"));
    }
  },
);
