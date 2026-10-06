/** Acquire an explicit, bounded subset of one completed capture. All remote commands are reads. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    host: { type: "string" },
    capture: { type: "string" },
    report: { type: "string" },
    output: { type: "string" },
    audits: { type: "string" },
    help: { type: "boolean" },
  },
});
if (values.help) {
  console.log(
    "Usage: node tools/acquire.mjs --host HOST --capture PATH --report PATH --output PATH [--audits PATH]\n" +
      "Acquire a completed capture and its supporting report into a fresh destination.\n" +
      "Remote paths must be absolute. --audits supplies the optional archive audit root.",
  );
  process.exit(0);
}
for (const option of ["host", "capture", "report", "output"])
  if (!values[option]) throw new Error("Missing required option: --" + option);
const { host, capture: root, report, audits } = values;
if (host.startsWith("-") || /[\s\0]/.test(host))
  throw new Error("Invalid SSH host");
for (const path of [root, report, audits].filter(Boolean))
  if (!path.startsWith("/") || /[\n\r\0]/.test(path))
    throw new Error("Remote paths must be absolute and contain no line breaks");
const destination = resolve(values.output);
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
  host,
];
const remote = (command, input) =>
  execFileSync("ssh", [...sshArgs, command], {
    input,
    timeout: 120000,
    maxBuffer: cap + 1024 * 1024,
  });
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const readVerified = (path, limit = cap) => {
  const bytes = Number(
    remote("stat -c %s -- " + shellQuote(path))
      .toString()
      .trim(),
  );
  if (!Number.isSafeInteger(bytes) || bytes < 0 || bytes > limit)
    throw new Error("Source file would exceed its transfer limit: " + path);
  const before = remote("sha256sum -- " + shellQuote(path))
    .toString()
    .split(/\s+/)[0];
  const data = remote("cat -- " + shellQuote(path));
  const after = remote("sha256sum -- " + shellQuote(path))
    .toString()
    .split(/\s+/)[0];
  if (data.length !== bytes || before !== after || sha(data) !== before)
    throw new Error("Source file changed during acquisition: " + path);
  return { bytes, data, sha256: before };
};
const inCapture = (command) => `cd ${shellQuote(root)} && ${command}`;
// Check bounded completion records before inventorying potentially growing logs.
const completionFiles = new Map(
  ["invocation.json", "cleanup.json", "observer-drain.json"].map((path) => [
    path,
    readVerified(root + "/" + path, 1024 * 1024),
  ]),
);
const invocation = JSON.parse(completionFiles.get("invocation.json").data);
const cleanup = JSON.parse(completionFiles.get("cleanup.json").data);
const drain = JSON.parse(completionFiles.get("observer-drain.json").data);
if (
  typeof invocation.namespace !== "string" ||
  !invocation.namespace ||
  typeof invocation.output !== "string" ||
  !invocation.output ||
  cleanup.namespace_removed !== true ||
  !Number.isSafeInteger(drain.expected) ||
  drain.expected < 0 ||
  drain.recorded !== drain.expected ||
  !Array.isArray(drain.missing_uids) ||
  drain.missing_uids.length !== 0
)
  throw new Error(
    "Acquisition requires completed capture cleanup and observer drain.",
  );
const reportFile = readVerified(report);
const metrics = JSON.parse(reportFile.data);
const runs = [
  ...(metrics.runs ?? []),
  ...(metrics.closed_loop_reports ?? []).flatMap((entry) => entry.runs ?? []),
];
const matching = runs.filter((run) => run.run_id === invocation.namespace);
if (
  matching.length !== 1 ||
  matching[0].capture !== invocation.output ||
  matching[0].accepted_capture !== true
)
  throw new Error(
    "Acquisition requires a matching accepted report for the completed capture.",
  );
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
      !Number.isSafeInteger(f.bytes) ||
      f.bytes < 0,
  )
)
  throw new Error("Unsafe or incomplete artifact list");
const reportBytes = reportFile.bytes;
const total = files.reduce((sum, f) => sum + f.bytes, reportBytes);
if (!Number.isSafeInteger(total) || total > cap)
  throw new Error(`Transfer would exceed 80 MiB: ${total}`);
const hashesCommand = inCapture(
  "sha256sum -- " + files.map((f) => shellQuote(f.path)).join(" "),
);
const before = remote(hashesCommand).toString();
const hashMap = new Map(
  before
    .trim()
    .split("\n")
    .map((line) => [line.slice(66), line.slice(0, 64)]),
);
for (const [path, file] of completionFiles)
  if (hashMap.get(path) !== file.sha256)
    throw new Error("Completed source changed after completion validation");
const reportBefore = reportFile.sha256;
const archive = remote(
  inCapture("tar --no-recursion --verbatim-files-from -cf - -T -"),
  files.map((f) => f.path).join("\n") + "\n",
);
if (archive.length > cap + 1024 * 1024) throw new Error("Archive cap exceeded");
const reportData = reportFile.data;
const after = remote(hashesCommand).toString();
if (before !== after)
  throw new Error("Completed source changed during acquisition");
const reportAfter = remote(`sha256sum -- ${shellQuote(report)}`)
  .toString()
  .split(/\s+/)[0];
if (
  reportData.length !== reportBytes ||
  reportBefore !== reportAfter ||
  sha(reportData) !== reportBefore
)
  throw new Error("Report changed during acquisition");
const extraFiles = [];
if (audits) {
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
    const absolutePath = audits.replace(/\/$/, "") + "/" + sourcePath;
    const verified = readVerified(
      absolutePath,
      cap -
        total -
        extraFiles.reduce((sum, file) => sum + file.bytes.length, 0),
    );
    extraFiles.push({
      path,
      sourcePath: absolutePath,
      bytes: verified.data,
      sha256: verified.sha256,
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
  sourceHost: host,
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
