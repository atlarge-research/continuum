import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
import { actualChart, forecastChart } from "../src/charts.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
test("charts use actual viewport dimensions so text and geometry need no anisotropic scaling", () => {
  const view = viewAt(data, data.cycles[5].available);
  for (const chart of [actualChart, forecastChart]) {
    const svg = chart(data, view, { width: 900, height: 120 });
    assert.match(svg, /viewBox="0 0 900 120"/);
    assert.doesNotMatch(svg, /preserveAspectRatio="none"/);
    assert.doesNotMatch(svg, /NaN|Infinity/);
  }
});
