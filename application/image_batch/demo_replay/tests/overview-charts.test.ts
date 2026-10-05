import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { actualChart, forecastChart } from "../src/charts.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
const size = { width: 900, height: 240 };
test("arrival counts survive membership gaps without being painted as unavailable", () => {
  const at = 1423038;
  assert.equal(viewAt(data, at).fresh, false);
  for (const chart of [actualChart, forecastChart]) {
    const html = chart(data, viewAt(data, at), size);
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
        data.jobs.filter(
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
  assert.match(actualChart(data, viewAt(data, at), size), /class="gap"/);
  assert.doesNotMatch(
    forecastChart(data, viewAt(data, at), size),
    /class="gap"/,
  );
});
test("forecast chart preserves issued history and retains forecast 8 during skipped cycle 9", () => {
  const afterSecond = data.cycles[1].available + 1000;
  const history = forecastChart(data, viewAt(data, afterSecond), size);
  assert.match(history, /class="forecast-line historical" data-cycle="1"/);
  assert.match(history, /class="forecast-line current" data-cycle="2"/);
  const fallback = data.cycles[8].available;
  const html = forecastChart(data, viewAt(data, fallback), size);
  assert.equal(viewAt(data, fallback).cycle!.tick, 9);
  assert.match(html, /class="forecast-line current" data-cycle="8"/);
  assert.match(html, /class="scenario-range current" data-cycle="8"/);
  assert.doesNotMatch(html, /No ready forecast/);
  for (const [, published] of html.matchAll(/data-available="(\d+)"/g))
    assert.ok(Number(published) <= fallback);
  forecastChart(data, viewAt(data, data.run.end), size);
  assert.equal(forecastChart(data, viewAt(data, fallback), size), html);
});
