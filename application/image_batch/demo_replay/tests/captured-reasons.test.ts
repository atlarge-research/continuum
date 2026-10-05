import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { convertCapture } from "../tools/normalize.ts";
import type { Dataset } from "../src/types.ts";

const root = "evidence/preliminary";
const captured = JSON.parse(
  readFileSync("data/replay.json", "utf8"),
) as Dataset;

// These reasons explain why an alternative was unavailable or a new forecast was withheld.
// They must survive packaging without changing the recorded simulation or control outcome.
test("packaged evidence retains captured capacity limits and stale-input fallback", () => {
  const unavailable = captured.cycles.flatMap((cycle) =>
    cycle.candidates
      .filter((candidate) => !candidate.valid)
      .map((candidate) => ({
        tick: cycle.tick,
        name: candidate.name,
        reason: candidate.unavailableReason,
      })),
  );
  assert.deepEqual(
    unavailable,
    [3, 4, 5, 7, 8, 10].map((tick) => ({
      tick,
      name: "scale-up",
      reason: "maximum_worker_count",
    })),
  );
  const withheld = captured.cycles.find((cycle) => cycle.tick === 9)!;
  assert.equal(withheld.forecastStatus, "not_ready");
  assert.equal(withheld.valid, false);
  assert.deepEqual(withheld.forecastReasons, ["state_stale"]);
  assert.deepEqual(withheld.bins, []);
});

test(
  "converter preserves exact source reasons without inventing candidate failures",
  { skip: !existsSync(root + "/acquisition.json") },
  () => {
    const converted = convertCapture(root);
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
