/** Acquire an explicit, bounded subset of one completed capture. All remote commands are reads. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";

const [root, report, output] = process.argv.slice(2);
const diagnosticRoot =
  "/mnt/sdb/matthijs/fns-evidence/opendc-diagnostics-20261003T213920Z";
const finalRoot =
  "/mnt/sdb/matthijs/fns-evidence/opendc-final-trio-20261005T092500Z";
const completedSources = [
  {
    root:
      diagnosticRoot +
      "/evaluation/matrix-primary-reused-transport/experiments/fns-diag-primary-s62002-forecast",
    report: diagnosticRoot + "/reports/primary/metrics.json",
    destination: "evidence/preliminary",
  },
  {
    root:
      finalRoot +
      "/captures/attempt-02/experiments/fns-final-trio-b-forecast-s72001-s72001-forecast",
    report: finalRoot + "/demo-data/cases/b-s72001.json",
    destination: "evidence/accepted-final",
  },
];
const source = completedSources.find(
  (s) => s.root === root && s.report === report,
);
if (!source)
  throw new Error(
    "Acquisition requires an explicitly authorized completed capture and its exact supporting report.",
  );
const destination = resolve(output ?? source.destination);
if (existsSync(destination))
  throw new Error(
    "Use a fresh acquisition destination; existing evidence is preserved.",
  );
const cap = 80 * 1024 * 1024;
const shellQuote = (s) => "'" + s.replaceAll("'", "'\\''") + "'";
const sshArgs = [
  "-o",
  "BatchMode=yes",
  "-o",
  "ConnectTimeout=10",
  "-o",
  "StrictHostKeyChecking=yes",
  "-o",
  "UpdateHostKeys=no",
  "node3",
];
const remote = (command, input) =>
  execFileSync("ssh", [...sshArgs, command], {
    input,
    timeout: 120000,
    maxBuffer: cap + 1024 * 1024,
  });
const inCapture = (command) => `cd ${shellQuote(root)} && ${command}`;
const inventory = remote(
  inCapture('find . -maxdepth 10 -type f -printf "%P\\t%s\\n"'),
).toString();
const exact = new Set([
  "invocation.json",
  "source-hashes.json",
  "clock-preflight.json",
  "endpoint.jsonl",
  "jobs.json",
  "pods-final.json",
  "fifo-admission.log",
  "observer-drain.json",
  "cleanup.json",
  "replay-check.txt",
  "controller/identity.json",
  "controller/journal.jsonl",
  "controller/frozen-template.json",
  "source/opendt_observer.py",
  "source/events.py",
]);
const matches = (p) =>
  exact.has(p) ||
  /^observer\/(cluster-state|observer-events|workload|resource-snapshots)\.jsonl$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/(scores|collection-timing|stage-timing)\.json$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/forecast\/(forecast|boundaries|training-bins|state)\.json$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/forecast\/simulation\/(manifest|initial-state)\.json$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/suite\/manifest\.json$/.test(p) ||
  /^controller\/cycle-\d{4}\/suite\/experiments\/unchanged\/\d{4}\/case\.json$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/native\/collection\.json$/.test(p) ||
  /^controller\/cycle-\d{4}\/native\/artifacts\/results\/batch\/batch\.json$/.test(
    p,
  ) ||
  /^controller\/cycle-\d{4}\/native\/artifacts\/results\/batch\/experiments\/\d{4}\/run\/execution\.json$/.test(
    p,
  );
const files = inventory
  .trim()
  .split("\n")
  .map((line) => {
    const [path, size] = line.split("\t");
    return { path, bytes: Number(size) };
  })
  .filter((f) => matches(f.path))
  .sort((a, b) => a.path.localeCompare(b.path));
if (
  !files.some((f) => f.path === "observer/cluster-state.jsonl") ||
  files.some(
    (f) =>
      f.path.startsWith("/") ||
      f.path.split("/").includes("..") ||
      !Number.isSafeInteger(f.bytes),
  )
)
  throw new Error("Unsafe or incomplete artifact list");
const reportBytes = Number(
  remote(`stat -c %s -- ${shellQuote(report)}`)
    .toString()
    .trim(),
);
const total = files.reduce((sum, f) => sum + f.bytes, reportBytes);
if (!Number.isSafeInteger(total) || total > cap)
  throw new Error(`Transfer would exceed 80 MiB: ${total}`);
const hashesCommand = inCapture(
  "sha256sum -- " + files.map((f) => shellQuote(f.path)).join(" "),
);
const before = remote(hashesCommand).toString();
const reportBefore = remote(`sha256sum -- ${shellQuote(report)}`)
  .toString()
  .split(/\s+/)[0];
const archive = remote(
  inCapture("tar --no-recursion --verbatim-files-from -cf - -T -"),
  files.map((f) => f.path).join("\n") + "\n",
);
if (archive.length > cap + 1024 * 1024) throw new Error("Archive cap exceeded");
const reportData = remote(`cat -- ${shellQuote(report)}`);
const after = remote(hashesCommand).toString();
if (before !== after)
  throw new Error("Completed source changed during acquisition");
const reportAfter = remote(`sha256sum -- ${shellQuote(report)}`)
  .toString()
  .split(/\s+/)[0];
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
if (
  reportData.length !== reportBytes ||
  reportBefore !== reportAfter ||
  sha(reportData) !== reportBefore
)
  throw new Error("Report changed during acquisition");
const extraFiles = [];
if (source.root.startsWith(finalRoot + "/")) {
  for (const [sourcePath, path] of [
    ["demo-data/index.json", "accepted/index.json"],
    [
      "analysis/independent-monitor-audit.json",
      "accepted/independent-monitor-audit.json",
    ],
    [
      "analysis/completion-verification.json",
      "accepted/completion-verification.json",
    ],
  ]) {
    const absolutePath = finalRoot + "/" + sourcePath;
    const expectedBytes = Number(
      remote("stat -c %s -- " + shellQuote(absolutePath))
        .toString()
        .trim(),
    );
    if (
      !Number.isSafeInteger(expectedBytes) ||
      expectedBytes < 0 ||
      total +
        extraFiles.reduce((sum, file) => sum + file.bytes.length, 0) +
        expectedBytes >
        cap
    )
      throw new Error("Final audits exceed source cap");
    const hashBefore = remote("sha256sum -- " + shellQuote(absolutePath))
      .toString()
      .split(/\s+/)[0];
    const bytes = remote("cat -- " + shellQuote(absolutePath));
    const hashAfter = remote("sha256sum -- " + shellQuote(absolutePath))
      .toString()
      .split(/\s+/)[0];
    if (
      bytes.length !== expectedBytes ||
      hashBefore !== hashAfter ||
      sha(bytes) !== hashBefore
    )
      throw new Error("Final audit changed during acquisition");
    extraFiles.push({
      path,
      sourcePath: absolutePath,
      bytes,
      sha256: hashBefore,
    });
  }
}
if (total + extraFiles.reduce((sum, file) => sum + file.bytes.length, 0) > cap)
  throw new Error("Final audits exceed source cap");
mkdirSync(destination, { recursive: true });
writeFileSync(join(destination, "capture-subset.tar"), archive);
execFileSync(
  "tar",
  ["-xf", join(destination, "capture-subset.tar"), "-C", destination],
  { timeout: 30000 },
);
const hashMap = new Map(
  before
    .trim()
    .split("\n")
    .map((line) => [line.slice(66), line.slice(0, 64)]),
);
for (const file of files) {
  const data = readFileSync(join(destination, file.path));
  const hash = sha(data);
  if (data.length !== file.bytes || hash !== hashMap.get(file.path))
    throw new Error(`Checksum mismatch: ${file.path}`);
  file.sha256 = hash;
}
writeFileSync(join(destination, "supporting-metrics.json"), reportData);
for (const file of extraFiles) {
  mkdirSync(join(destination, "accepted"), { recursive: true });
  writeFileSync(join(destination, file.path), file.bytes);
  files.push({
    path: file.path,
    sourcePath: file.sourcePath,
    bytes: file.bytes.length,
    sha256: file.sha256,
  });
}
files.sort((a, b) => a.path.localeCompare(b.path));
const manifest = {
  schemaVersion: 1,
  acquiredAt: new Date().toISOString(),
  sourceHost: "node3",
  sourceRoot: root,
  reportPath: report,
  reportBytes,
  reportSha256: reportBefore,
  transferCapBytes: cap,
  totalSourceBytes:
    total + extraFiles.reduce((sum, file) => sum + file.bytes.length, 0),
  tarBytes: archive.length,
  archiveSha256: sha(archive),
  remoteReadTimeoutSeconds: 120,
  sourceUnchanged: true,
  files,
};
writeFileSync(
  join(destination, "acquisition.json"),
  JSON.stringify(manifest, null, 2) + "\n",
);
console.log(
  JSON.stringify({
    files: files.length,
    sourceBytes: total,
    tarBytes: archive.length,
    verified: true,
    destination,
  }),
);
