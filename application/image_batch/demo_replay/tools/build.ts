import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { packageHtml } from "./package.ts";
const data = readFileSync("data/replay.json", "utf8");
const normalized = JSON.parse(data);
if (normalized.schemaVersion !== 1)
  throw new Error("Unsupported replay dataset");
const result = await build({
  entryPoints: ["src/app.ts"],
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "es2022",
  minify: true,
  write: false,
  metafile: true,
  legalComments: "inline",
});
if (
  Object.values(result.metafile!.outputs).some(
    (output) => output.imports.length,
  )
)
  throw new Error("Runtime imports are forbidden");
const template = readFileSync("index.html", "utf8")
  .replace(
    "__VU_LOGO__",
    () =>
      `data:image/svg+xml;base64,${readFileSync("assets/vu-amsterdam.svg").toString("base64")}`,
  )
  .replace(
    "__FNS_LOGO__",
    () =>
      `data:image/png;base64,${readFileSync("assets/fns.png").toString("base64")}`,
  );
const html = packageHtml(
  template,
  readFileSync("src/style.css", "utf8"),
  result.outputFiles[0].text,
  data,
);
const artifact = "dist/continuum-replay.html";
mkdirSync("dist", { recursive: true });
writeFileSync(artifact, html);
mkdirSync("evidence/verification", { recursive: true });
writeFileSync(
  "evidence/verification/build.json",
  JSON.stringify(
    {
      artifact,
      bytes: Buffer.byteLength(html),
      sha256: createHash("sha256").update(html).digest("hex"),
      captureId: normalized.run.id,
      datasetStatus: normalized.run.status,
      embeddedDataSha256: createHash("sha256").update(data).digest("hex"),
      runtimeImports: 0,
      format: "iife",
      target: "es2022",
    },
    null,
    2,
  ) + "\n",
);
console.log(`Built ${artifact} (${Buffer.byteLength(html)} bytes)`);
