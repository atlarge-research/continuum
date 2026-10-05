import test from "node:test";
import assert from "node:assert/strict";
import { playbackCommand, advancePlayback } from "../src/playhead.ts";
import { packageHtml } from "../tools/package.ts";
test("a speed change advances the same authoritative cursor and paused time does not move", () => {
  let s = { cursor: 100, speed: 16, playing: false };
  s = playbackCommand(s, { type: "toggle" }, 100, 1000);
  s = advancePlayback(s, 10, 100, 1000);
  assert.equal(s.cursor, 260);
  s = playbackCommand(s, { type: "speed", speed: 4 }, 100, 1000);
  s = advancePlayback(s, 10, 100, 1000);
  assert.equal(s.cursor, 300);
  s = playbackCommand(s, { type: "pause" }, 100, 1000);
  assert.deepEqual(advancePlayback(s, 100, 100, 1000), s);
});
test("seeking pauses and clamps both ends; end-of-run play restarts deterministically", () => {
  const s = { cursor: 500, speed: 16, playing: true };
  assert.deepEqual(playbackCommand(s, { type: "seek", time: -1 }, 100, 1000), {
    cursor: 100,
    speed: 16,
    playing: false,
  });
  assert.equal(
    playbackCommand(s, { type: "seek", time: 9000 }, 100, 1000).cursor,
    1000,
  );
  assert.deepEqual(advancePlayback(s, 100, 100, 1000), {
    cursor: 1000,
    speed: 16,
    playing: false,
  });
  assert.deepEqual(
    playbackCommand(
      { cursor: 1000, speed: 16, playing: false },
      { type: "toggle" },
      100,
      1000,
    ),
    { cursor: 100, speed: 16, playing: true },
  );
});
test("rejects nonfinite/negative timing and invalid speeds rather than corrupting replay", () => {
  assert.throws(() =>
    playbackCommand(
      { cursor: 100, speed: 16, playing: false },
      { type: "speed", speed: 0 },
      100,
      1000,
    ),
  );
  assert.throws(() =>
    playbackCommand(
      { cursor: 100, speed: 16, playing: false },
      { type: "seek", time: NaN },
      100,
      1000,
    ),
  );
  assert.throws(() =>
    advancePlayback({ cursor: 100, speed: 16, playing: true }, -1, 100, 1000),
  );
});
test("packages data as inert escaped JSON and embeds scripts/styles without runtime imports", () => {
  const data = '{"label":"</script><img src=evil>"}';
  const html = packageHtml(
    '<style>__STYLE__</style><script id="replay-data" type="application/json">__DATA__</script><script>__SCRIPT__</script>',
    "body{color:white}",
    "(()=>{window.ready=true})()",
    data,
  );
  assert.ok(!html.includes("<img src=evil>"));
  assert.ok(html.includes("\\u003c/script>"));
  const embedded = html
    .split('type="application/json">')[1]
    .split("</script>")[0];
  assert.equal(JSON.parse(embedded).label, "</script><img src=evil>");
  assert.ok(html.includes("window.ready=true"));
  assert.ok(!html.includes("__DATA__"));
});
