import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  truncateSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const script = resolve("tools/acquire.mjs");
const host = "fixture-archive";

function fixture(t: test.TestContext) {
  const base = mkdtempSync(join(tmpdir(), "replay-acquire-"));
  t.after(() => rmSync(base, { recursive: true, force: true }));
  const capture = join(base, "capture's completed run");
  const report = join(base, "report.json");
  const output = join(base, "acquired");
  const audits = join(base, "audits");
  const log = join(base, "reads.log");
  const bin = join(base, "bin");
  mkdirSync(join(capture, "observer"), { recursive: true });
  mkdirSync(bin);
  const json = (path: string, value: unknown) =>
    writeFileSync(path, JSON.stringify(value) + "\n");
  const historicalCapture = "/archive/original/completed-fixture";
  json(join(capture, "invocation.json"), {
    namespace: "completed-fixture",
    output: historicalCapture,
  });
  json(join(capture, "cleanup.json"), { namespace_removed: true });
  json(join(capture, "observer-drain.json"), {
    expected: 1,
    recorded: 1,
    missing_uids: [],
  });
  const cluster = join(capture, "observer/cluster-state.jsonl");
  writeFileSync(cluster, '{"timestamp":1}\n');
  writeFileSync(join(capture, "unselected.txt"), "excluded\n");
  const run = {
    run_id: "completed-fixture",
    capture: historicalCapture,
    accepted_capture: true,
  };
  json(report, { runs: [run] });
  mkdirSync(join(audits, "demo-data"), { recursive: true });
  mkdirSync(join(audits, "analysis"));
  json(join(audits, "demo-data/index.json"), { ready: true });
  json(join(audits, "analysis/independent-monitor-audit.json"), { rows: [] });
  json(join(audits, "analysis/completion-verification.json"), {
    campaign_process_exit_code: 0,
  });
  // Replace only the network boundary. Every archive command runs on local files.
  writeFileSync(
    join(bin, "ssh"),
    `#!/bin/sh
while [ "$#" -gt 2 ]; do shift; done
[ "$1" = "$ACQUIRE_TEST_HOST" ] || exit 90
printf '%s\\n' "$2" >> "$ACQUIRE_TEST_LOG"
/bin/sh -c "$2" || exit "$?"
case "$2" in
  *"tar --no-recursion"*)
    if [ -n "$ACQUIRE_TEST_MUTATE" ]; then
      printf '%s\\n' '{"timestamp":2}' >> "$ACQUIRE_TEST_MUTATE"
    fi
    ;;
esac
`,
    { mode: 0o755 },
  );
  const acquire = (extra: string[] = [], mutate?: string) =>
    spawnSync(
      process.execPath,
      [
        script,
        "--host",
        host,
        "--capture",
        capture,
        "--report",
        report,
        "--output",
        output,
        ...extra,
      ],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          PATH: bin + ":" + process.env.PATH,
          ACQUIRE_TEST_HOST: host,
          ACQUIRE_TEST_LOG: log,
          ACQUIRE_TEST_MUTATE: mutate ?? "",
        },
      },
    );
  const reads = () => (existsSync(log) ? readFileSync(log, "utf8") : "");
  return {
    capture,
    report,
    output,
    audits,
    cluster,
    json,
    run,
    acquire,
    reads,
  };
}

test("acquires relocated completed artifacts and audits with verified machine provenance", (t) => {
  const f = fixture(t);
  const result = f.acquire(["--audits", f.audits]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(
    readFileSync(join(f.output, "observer/cluster-state.jsonl"), "utf8"),
    '{"timestamp":1}\n',
  );
  assert.ok(!existsSync(join(f.output, "unselected.txt")));
  assert.deepEqual(
    JSON.parse(readFileSync(join(f.output, "accepted/index.json"), "utf8")),
    { ready: true },
  );
  const manifest = JSON.parse(
    readFileSync(join(f.output, "acquisition.json"), "utf8"),
  );
  assert.equal(manifest.sourceHost, host);
  assert.equal(manifest.sourceRoot, f.capture);
  assert.equal(manifest.reportPath, f.report);
  assert.equal(manifest.sourceUnchanged, true);
  assert.equal(manifest.files.length, 7);
  assert.equal(
    manifest.files.find(
      (file: { path: string }) => file.path === "accepted/index.json",
    ).sourcePath,
    join(f.audits, "demo-data/index.json"),
  );
  assert.equal(manifest.reportSha256.length, 64);
  assert.ok(
    manifest.files.every(
      (file: { sha256: string }) => file.sha256.length === 64,
    ),
  );
});

test("accepts a completed preliminary report without archive audits", (t) => {
  const f = fixture(t);
  f.json(f.report, { closed_loop_reports: [{ runs: [f.run] }] });
  const result = f.acquire();
  assert.equal(result.status, 0, result.stderr);
  assert.ok(!existsSync(join(f.output, "accepted")));
});

for (const reason of [
  "mismatched run",
  "mismatched capture",
  "unaccepted run",
  "unfinished cleanup",
  "undrained observer",
]) {
  test(`refuses ${reason} before inventorying capture files`, (t) => {
    const f = fixture(t);
    if (reason === "mismatched run") f.run.run_id = "another-run";
    if (reason === "mismatched capture") f.run.capture += "/another";
    if (reason === "unaccepted run") f.run.accepted_capture = false;
    f.json(f.report, { runs: [f.run] });
    if (reason === "unfinished cleanup")
      f.json(join(f.capture, "cleanup.json"), { namespace_removed: false });
    if (reason === "undrained observer")
      f.json(join(f.capture, "observer-drain.json"), {
        expected: 2,
        recorded: 1,
        missing_uids: ["pending"],
      });
    const result = f.acquire();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /completed capture/i);
    assert.ok(!f.reads().includes("find ."));
    if (reason === "unfinished cleanup" || reason === "undrained observer")
      assert.ok(!f.reads().includes(f.report));
    assert.ok(!existsSync(f.output));
  });
}

test("refuses an oversized completed capture before transferring its archive", (t) => {
  const f = fixture(t);
  truncateSync(f.cluster, 80 * 1024 * 1024 + 1);
  const result = f.acquire();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /exceed 80 MiB/i);
  assert.ok(!f.reads().includes("tar --no-recursion"));
  assert.ok(!existsSync(f.output));
});

test("preserves an existing destination without reading the source", (t) => {
  const f = fixture(t);
  mkdirSync(f.output);
  writeFileSync(join(f.output, "keep.txt"), "preserved\n");
  const result = f.acquire();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /fresh acquisition destination/i);
  assert.equal(readFileSync(join(f.output, "keep.txt"), "utf8"), "preserved\n");
  assert.equal(f.reads(), "");
});

test("refuses capture mutation during the local transfer", (t) => {
  const f = fixture(t);
  const result = f.acquire([], f.cluster);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /source changed/i);
  assert.ok(!existsSync(f.output));
});
