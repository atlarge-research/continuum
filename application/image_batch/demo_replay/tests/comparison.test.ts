import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { comparisonConclusion } from "../src/presentation.ts";
import { comparisonFromReport } from "../tools/comparison.ts";

// Independent, hand-checked contract fixture: one workload, three policies,
// equal source/deployment content despite separate sealed configuration paths.
function finalReport() {
  const policy = ["fixed", "reactive", "forecast"];
  return {
    runs: policy.map((arm, i) => ({
      run_id: "final-" + arm,
      seed: 72001,
      arm,
      arrival_plan_sha256: "same-plan",
      source_hashes: { "observer.py": "same-source" },
      accepted_capture: true,
      acceptance_issues: [],
      sender_evaluated_window: { fidelity_passed: true },
      evaluation_start_seconds: 1000 + i * 2000,
      arrival_end_seconds: 1840 + i * 2000,
      comparison_settings: {
        followup_seconds: 180,
        acquisition_seconds: 60,
        active_workers: { fixed: 5, reactive: 4, forecast: 4 },
        network_preset: "5g_nl_kpn_mahimahi",
        deployment_sources: {
          config: "/sealed/" + arm + "/continuum.cfg",
          inventory: "/sealed/" + arm + "/inventory.ini",
          config_sha256: "same-config",
          inventory_sha256: "same-inventory",
        },
      },
      config: {
        minimum_workers: 2,
        maximum_workers: 6,
        workers: Array.from({ length: 6 }, (_, n) => ({
          node_name: "worker" + n,
          configured_cores: 5,
          memory_mib: 16384,
        })),
      },
      invocation: {
        deadline_seconds: 120,
        deadline_fraction: 0.95,
        endpoint_image: "same-endpoint",
        native_image: "same-native",
        reactive_up_threshold: 0.9,
        reactive_down_threshold: 0.7,
        reactive_target_fraction: 0.8,
        reactive_downscale_stabilization_seconds: 120,
      },
      controller: { cadence_seconds: arm === "reactive" ? 30 : 90 },
      responses: {
        jobs: 227,
        deadline_met: 227,
        completed: 227,
        completed_response_p95_seconds: [50, 81, 91][i],
      },
      allocation: {
        allocated_core_seconds_bounds: [
          [1000, 1020],
          [800, 820],
          [600, 620],
        ][i],
      },
    })),
  };
}
const accepted = ["final-fixed", "final-reactive", "final-forecast"];
test("canonical final report preserves the whole cohort and recorded reactive target", () => {
  const result = comparisonFromReport(
    finalReport(),
    "final-forecast",
    "accepted-final",
    "hash",
    accepted,
  );
  assert.deepEqual(
    result.runs.map((r) => [
      r.policy,
      r.jobs,
      r.timelyJobs,
      r.p95CompletedSeconds,
    ]),
    [
      ["fixed", 227, 227, 50],
      ["reactive", 227, 227, 81],
      ["forecast", 227, 227, 91],
    ],
  );
  assert.equal(
    result.runs.find((r) => r.policy === "reactive")?.reactiveTargetFraction,
    0.8,
  );
  assert.deepEqual(
    result.runs.find((r) => r.policy === "forecast")?.allocationBounds,
    [600, 620],
  );
});
test("canonical comparison rejects mixed sources, images, deployment content and worker capacity", () => {
  const changes = [
    (r: any) => {
      r.source_hashes["observer.py"] = "other-source";
    },
    (r: any) => {
      delete r.source_hashes["observer.py"];
    },
    (r: any) => {
      r.invocation.native_image = "other-native";
    },
    (r: any) => {
      r.invocation.endpoint_image = "other-endpoint";
    },
    (r: any) => {
      r.comparison_settings.deployment_sources.config_sha256 = "other-config";
    },
    (r: any) => {
      r.config.workers[0].configured_cores = 6;
    },
    (r: any) => {
      r.arrival_plan_sha256 = "other-plan";
    },
  ];
  for (const change of changes) {
    const report = finalReport();
    change(report.runs[1]);
    assert.throws(
      () =>
        comparisonFromReport(
          report,
          "final-forecast",
          "accepted-final",
          "hash",
          accepted,
        ),
      /matched/,
    );
  }
});
test("canonical comparison refuses missing arms, duplicate arms, failed acceptance and reduced denominator", () => {
  const missing = finalReport();
  missing.runs.pop();
  assert.throws(
    () =>
      comparisonFromReport(
        missing,
        "final-fixed",
        "accepted-final",
        "hash",
        accepted,
      ),
    /three matched/,
  );
  const duplicate = finalReport();
  duplicate.runs.push(duplicate.runs[0]);
  assert.throws(
    () =>
      comparisonFromReport(
        duplicate,
        "final-fixed",
        "accepted-final",
        "hash",
        accepted,
      ),
    /three matched/,
  );
  const unaccepted = finalReport();
  unaccepted.runs[1].accepted_capture = false;
  assert.throws(
    () =>
      comparisonFromReport(
        unaccepted,
        "final-fixed",
        "accepted-final",
        "hash",
        accepted,
      ),
    /unaccepted/,
  );
  const reduced = finalReport();
  reduced.runs[1].responses.jobs = 226;
  assert.throws(
    () =>
      comparisonFromReport(
        reduced,
        "final-fixed",
        "accepted-final",
        "hash",
        accepted,
      ),
    /matched/,
  );
  assert.throws(
    () =>
      comparisonFromReport(
        finalReport(),
        "final-forecast",
        "accepted-final",
        "hash",
        accepted.slice(0, 2),
      ),
    /acceptance/,
  );
});

const finalCase = "evidence/final-export/demo-data/cases/b-s72001.json";
const auditPath =
  "evidence/final-export/analysis/independent-monitor-audit.json";
test(
  "accepted B/72001 export agrees with the independent monitor audit",
  { skip: !existsSync(finalCase) || !existsSync(auditPath) },
  () => {
    const report = JSON.parse(readFileSync(finalCase, "utf8"));
    const audit = JSON.parse(readFileSync(auditPath, "utf8"));
    const ids = report.runs.map((r: any) => r.run_id);
    const result = comparisonFromReport(
      report,
      ids.find((id: string) => id.endsWith("forecast")),
      "accepted-final",
      "verified-separately",
      ids,
    );
    assert.equal(result.runs.length, 3);
    for (const r of result.runs) {
      const independent = audit.rows.find((a: any) => a.arm === r.policy);
      assert.equal(r.jobs, 227);
      assert.equal(r.timelyJobs, 227);
      assert.equal(r.jobs, independent.jobs);
      assert.equal(r.timelyJobs, independent.deadline_met);
      assert.equal(r.p95CompletedSeconds, independent.p95_seconds);
      assert.deepEqual(
        r.allocationBounds.map((v) => v / 3600),
        independent.allocated_core_hours_bounds,
      );
    }
    assert.equal(
      result.runs.find((r) => r.policy === "reactive")?.reactiveTargetFraction,
      0.8,
    );
    const conclusion = comparisonConclusion(result, 72001);
    assert.match(
      conclusion,
      /reactive heuristic allocated about 12.4% less application capacity/,
    );
    assert.match(conclusion, /twin about 27.7% less/);
    assert.match(
      conclusion,
      /twin also allocated about 17.1% less than the reactive heuristic/,
    );
    assert.match(
      conclusion,
      /81.0s under the reactive heuristic.*90.7s under the twin/,
    );
  },
);

test("comparison conclusion retains service, conservative savings and the latency tradeoff", () => {
  const result = comparisonFromReport(
    finalReport(),
    "final-forecast",
    "accepted-final",
    "hash",
    accepted,
  );
  const text = comparisonConclusion(result, 72001);
  assert.match(text, /All three policies met the 95% service target/);
  assert.match(
    text,
    /reactive heuristic allocated about 18.0% less application capacity/,
  );
  assert.match(text, /twin about 38.0% less/);
  assert.match(
    text,
    /twin also allocated about 22.5% less than the reactive heuristic/,
  );
  assert.match(
    text,
    /81.0s under the reactive heuristic.*91.0s under the twin/,
  );
  const reactive = result.runs.find((r) => r.policy === "reactive")!;
  reactive.timelyJobs = 200;
  const forecast = result.runs.find((r) => r.policy === "forecast")!;
  forecast.allocationBounds = [810, 830];
  const changed = comparisonConclusion(result, 72001);
  assert.match(changed, /reactive heuristic missed/);
  assert.doesNotMatch(changed, /All three policies met/);
  assert.match(
    changed,
    /overlapping allocation bounds.*no reduction between them is established/,
  );
  assert.doesNotMatch(changed, /twin also allocated about/);
  forecast.p95CompletedSeconds = null;
  const missingLatency = comparisonConclusion(result, 72001);
  assert.doesNotMatch(missingLatency, /91.0s under the twin/);
  assert.doesNotMatch(
    missingLatency,
    /lower allocation came with slower responses/,
  );
  assert.match(missingLatency, /81.0s under the reactive heuristic/);
});

test("completed response p95 must be a finite nonnegative duration", () => {
  for (const invalid of [null, undefined, "81", NaN, Infinity, -1]) {
    const report = finalReport();
    (report.runs[1].responses as any).completed_response_p95_seconds = invalid;
    assert.throws(
      () =>
        comparisonFromReport(
          report,
          "final-forecast",
          "accepted-final",
          "hash",
          accepted,
        ),
      /p95/,
    );
  }
  const report = finalReport();
  report.runs[1].responses.completed = 0;
  report.runs[1].responses.deadline_met = 0;
  (report.runs[1].responses as any).completed_response_p95_seconds = null;
  const result = comparisonFromReport(
    report,
    "final-forecast",
    "accepted-final",
    "hash",
    accepted,
  );
  assert.equal(result.runs[1].jobs, 227);
  assert.equal(result.runs[1].completedJobs, 0);
  assert.equal(result.runs[1].p95CompletedSeconds, null);
});
test("supplied response cohorts preserve the denominator and unique Job lineage", () => {
  const cohort = Array.from({ length: 227 }, (_, i) => ({ uid: "job-" + i }));
  const valid = finalReport();
  (valid.runs[1].responses as any).cohort = cohort;
  assert.equal(
    comparisonFromReport(
      valid,
      "final-forecast",
      "accepted-final",
      "hash",
      accepted,
    ).runs[1].jobs,
    227,
  );
  const invalidCohorts = [
    cohort.slice(1),
    [...cohort.slice(1), cohort[1]],
    null,
  ];
  for (const invalid of invalidCohorts) {
    const report = finalReport();
    (report.runs[1].responses as any).cohort = invalid;
    assert.throws(
      () =>
        comparisonFromReport(
          report,
          "final-forecast",
          "accepted-final",
          "hash",
          accepted,
        ),
      /cohort|denominator/,
    );
  }
});
