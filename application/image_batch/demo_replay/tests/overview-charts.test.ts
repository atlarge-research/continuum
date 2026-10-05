import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { actualChart, forecastChart } from "../src/charts.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
const size = { width: 900, height: 240 };
test("arrival counts survive a synthetic membership gap without being painted as unavailable", () => {
  const capture = structuredClone(data);
  const source = capture.snapshots.find(
    (s) => s.complete && s.at >= (capture.run.start + capture.run.end) / 2,
  )!;
  const at = source.at + 1;
  capture.snapshots.push({
    ...structuredClone(source),
    at,
    started: at,
    complete: false,
  });
  capture.snapshots.sort((a, b) => a.at - b.at);
  capture.gaps.push({
    start: at,
    end: at + 1000,
    available: at,
    reason: "synthetic membership gap",
  });
  assert.equal(viewAt(capture, at).fresh, false);
  for (const chart of [actualChart, forecastChart]) {
    const html = chart(capture, viewAt(capture, at), size);
    const bars = [
      ...html.matchAll(
        /<rect class="(?:arrival-bar|actual-bar) ([^"]+)" data-count="(\d+)" data-bin-start="(\d+)" data-bin-end="(\d+)"[^>]*>/g,
      ),
    ];
    assert.ok(bars.length > 0);
    for (const [, classes, count, left, right] of bars) {
      assert.match(classes, /recorded|open/);
      assert.equal(
        Number(count),
        capture.jobs.filter(
          (j) =>
            j.available <= at &&
            j.creation >= Number(left) &&
            j.creation < Number(right),
        ).length,
      );
      assert.ok(Number(right) <= at);
    }
    assert.doesNotMatch(
      html,
      /coverage incomplete|covered observations|partial coverage/,
    );
  }
  assert.match(actualChart(capture, viewAt(capture, at), size), /class="gap"/);
  assert.doesNotMatch(
    forecastChart(capture, viewAt(capture, at), size),
    /class="gap"/,
  );
});
test("forecast chart preserves real issue history and retains a forecast through a synthetic skipped update", () => {
  const ready = data.cycles.filter(
    (c) => c.forecastStatus === "ready" && c.bins.length,
  );
  const [first, second] = ready;
  const afterSecond = second.available + 1000;
  const history = forecastChart(data, viewAt(data, afterSecond), size);
  assert.match(
    history,
    new RegExp(`class="forecast-line historical" data-cycle="${first.tick}"`),
  );
  assert.match(
    history,
    new RegExp(`class="forecast-line current" data-cycle="${second.tick}"`),
  );
  const capture = structuredClone(data);
  const skipped = {
    ...structuredClone(second),
    tick: second.tick + 1,
    available: second.available + 1000,
    forecastStatus: "not_ready",
    forecastReasons: ["state_stale"],
    valid: false,
    bins: [],
  };
  capture.cycles = [first, second, skipped];
  const fallback = skipped.available;
  const html = forecastChart(capture, viewAt(capture, fallback), size);
  assert.equal(viewAt(capture, fallback).cycle!.tick, skipped.tick);
  assert.match(
    html,
    new RegExp(`class="forecast-line current" data-cycle="${second.tick}"`),
  );
  assert.match(
    html,
    new RegExp(`class="scenario-range current" data-cycle="${second.tick}"`),
  );
  assert.doesNotMatch(html, /No ready forecast/);
  for (const [, published] of html.matchAll(/data-available="(\d+)"/g))
    assert.ok(Number(published) <= fallback);
  forecastChart(capture, viewAt(capture, data.run.end), size);
  assert.equal(forecastChart(capture, viewAt(capture, fallback), size), html);
});
