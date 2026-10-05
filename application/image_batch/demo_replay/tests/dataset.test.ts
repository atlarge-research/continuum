/** Portable invariants also run when private raw evidence is absent from a clone. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Dataset } from "../src/types.ts";
import { viewAt } from "../src/replay.ts";
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
test("all actual evidence remains gated throughout forward and reverse replay", () => {
  const times = [
    data.run.start,
    data.run.end,
    ...data.bookmarks.map((b) => b.at),
    ...data.cycles.flatMap((c) => [c.available - 1, c.available]),
    ...data.gaps.flatMap((g) => [g.start + 1, g.end - 1]),
  ].filter((t) => t >= data.run.start && t <= data.run.end);
  const expected = times.map((t) => viewAt(data, t));
  for (let i = times.length - 1; i >= 0; i--) {
    const view = viewAt(data, times[i]);
    assert.deepEqual(view, expected[i]);
    assert.ok(view.knownArrivals.every((j) => j.available <= view.cursor));
    assert.ok(
      view.resources.every(
        (s) =>
          s.available !== null &&
          s.available <= view.cursor &&
          s.capture <= view.cursor,
      ),
    );
    if (view.cycle) assert.ok(view.cycle.available <= view.cursor);
    assert.ok(view.events.every((e) => e.at <= view.cursor));
    for (const bin of view.quality)
      if (bin.complete) assert.ok(bin.start + view.cycle!.binMs <= view.cursor);
  }
});
test("all bookmarks omit warm-up and every resource sample preserves provenance", () => {
  assert.ok(data.run.start >= data.run.evaluationStart);
  assert.ok(data.snapshots.some((s) => s.at < data.run.evaluationStart));
  assert.ok(
    data.bookmarks.every((b) => b.at >= data.run.start && b.at <= data.run.end),
  );
  for (const sample of data.resources) {
    assert.ok(sample.cpu >= 0 && sample.memory >= 0);
    if (sample.available !== null)
      assert.ok(
        sample.available >= sample.observation &&
          sample.available >= sample.capture,
      );
    if (sample.basis === "next_serialized_collection") {
      const proof = data.snapshots.find(
        (s) => s.sourceIndex === sample.proofState,
      )!;
      assert.ok(proof.started > sample.observation);
      assert.equal(proof.at, sample.available);
    }
  }
});
