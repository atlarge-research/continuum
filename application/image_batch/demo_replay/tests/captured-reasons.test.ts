import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { convertCapture } from "../tools/normalize.ts";
import type { Dataset } from "../src/types.ts";

const root = "evidence/accepted-final";
const captured = JSON.parse(
  readFileSync("data/replay.json", "utf8"),
) as Dataset;

// These reasons explain why an alternative was unavailable or a new forecast was withheld.
// They must survive packaging without changing the recorded simulation or control outcome.
test("accepted capture retains ready forecasts without inventing unavailable alternatives", () => {
  const unavailable = captured.cycles.flatMap((cycle) =>
    cycle.candidates
      .filter((candidate) => !candidate.valid)
      .map((candidate) => ({
        tick: cycle.tick,
        name: candidate.name,
        reason: candidate.unavailableReason,
      })),
  );
  // Independently inspected all ten final forecasts and proposal score records.
  assert.equal(captured.cycles.length, 10);
  assert.deepEqual(unavailable, []);
  for (const cycle of captured.cycles) {
    assert.equal(cycle.forecastStatus, "ready");
    assert.equal(cycle.valid, true);
    assert.deepEqual(cycle.forecastReasons, []);
    assert.ok(cycle.bins.length > 0);
    assert.ok(
      cycle.candidates.every(
        (candidate) => candidate.unavailableReason == null,
      ),
    );
  }
});

test(
  "converter preserves exact source reasons without inventing candidate failures",
  { skip: !existsSync(root + "/acquisition.json") },
  () => {
    const converted = convertCapture(
      root,
      "accepted-final",
      root + "/acceptance.json",
    );
    const journal = readFileSync(root + "/controller/journal.jsonl", "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    for (const cycle of converted.cycles) {
      const directory = `${root}/controller/cycle-${String(cycle.tick).padStart(4, "0")}`;
      const forecast = JSON.parse(
        readFileSync(directory + "/forecast/forecast.json", "utf8"),
      );
      assert.deepEqual(
        cycle.forecastReasons,
        forecast.reasons ?? [],
        `cycle ${cycle.tick}`,
      );
      const scorePath = directory + "/scores.json";
      const rawScores = existsSync(scorePath)
        ? JSON.parse(readFileSync(scorePath, "utf8"))
        : [];
      const proposal = journal.find(
        (entry) =>
          entry.event === "cycle.proposal" && entry.tick === cycle.tick,
      ).proposal;
      for (const candidate of cycle.candidates) {
        const raw = rawScores.find(
          (score: any) => score.candidate === candidate.name,
        );
        const proposed = proposal.scores.find(
          (score: any) => score.candidate === candidate.name,
        );
        assert.equal(
          candidate.unavailableReason,
          raw?.unavailable_reason ?? proposed?.unavailable_reason ?? null,
          `cycle ${cycle.tick}, ${candidate.name}`,
        );
      }
    }
  },
);
