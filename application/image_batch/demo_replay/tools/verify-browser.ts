/** Actual disk/offline browser acceptance for all views, timing and viewport behavior. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  readFileSync,
  mkdirSync,
  writeFileSync,
  mkdtempSync,
  copyFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { viewAt } from "../src/replay.ts";
import { decisionText } from "../src/decision.ts";
import { deadlineStatus, workerDisplayAt } from "../src/presentation.ts";
import type { Dataset, PolicyResult } from "../src/types.ts";
process.env.PLAYWRIGHT_BROWSERS_PATH = resolve("evidence/browser");
const { chromium } = await import("@playwright/test");
const dataBytes = readFileSync("data/replay.json");
const data: Dataset = JSON.parse(dataBytes.toString("utf8"));
const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
const operatingCycles = data.cycles.filter(
  (cycle) =>
    cycle.available >= data.run.start && cycle.available <= data.run.end,
);
const readyCycles = operatingCycles.filter(
  (cycle) => cycle.forecastStatus === "ready" && cycle.bins.length > 0,
);
assert.ok(
  readyCycles.length >= 2,
  "Captured replay has successive ready publications",
);
const firstReady = readyCycles[0],
  secondReady = readyCycles[1],
  focusCycle = readyCycles[Math.floor(readyCycles.length / 2)];
const measuredAt = data.snapshots.find(
  (snapshot) =>
    snapshot.at >= data.run.start &&
    snapshot.at <= data.run.end &&
    workerDisplayAt(data, snapshot.at).view.workers.some(
      (worker) => worker.cpu !== null && worker.memory !== null,
    ),
)?.at;
assert.ok(
  measuredAt !== undefined,
  "Captured operating replay contains application samples",
);
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
const errors: string[] = [],
  requests: string[] = [],
  checks: string[] = [];
const result: any = {
  offline: true,
  browser: browser.version(),
  capture: data.run.id,
  sourceHost: data.provenance.sourceHost,
  sourceRoot: data.provenance.sourceRoot,
  sourceBytes: data.provenance.sourceBytes,
  acquisitionManifestSha256: data.provenance.manifestSha256,
  runtimeSourceHashes: data.provenance.sourceHashes,
  dataSha256: sha256(dataBytes),
  comparisonSourceSha256: data.comparison?.sourceSha256 ?? null,
  checks,
  errors,
  requests,
  passed: false,
};
const relocated = mkdtempSync(resolve(tmpdir(), "continuum-offline-"));
const outputDir = resolve("evidence/verification");
mkdirSync(outputDir, { recursive: true });
try {
  const name = "continuum-replay.html";
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
  });
  await context.setOffline(true);
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (!/^(file:|data:|about:)/.test(r.url())) requests.push(r.url());
  });
  const htmlBytes = readFileSync(`dist/${name}`);
  result.htmlSha256 = sha256(htmlBytes);
  copyFileSync(`dist/${name}`, resolve(relocated, name));
  await page.goto(pathToFileURL(resolve(relocated, name)).href);
  await page.waitForSelector(".worker");
  const seek = async (at: number) => {
    await page.locator("#seek").evaluate((el, at) => {
      (el as HTMLInputElement).value = String(at);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }, at);
  };
  const tab = async (name: string) => {
    await page.locator(`#tab-${name}`).click();
  };
  const overview = () =>
    page.evaluate(() =>
      [
        "workers",
        "physical-summary",
        "service-status",
        "actual-chart",
        "forecast-chart",
        "twin-input",
        "forecast-time",
        "alternatives",
        "decision",
        "clock",
      ].map((id) => document.getElementById(id)!.innerHTML),
    );
  const layout = () =>
    page.evaluate(() =>
      [
        "workers",
        "actual-chart",
        "forecast-chart",
        "twin-input",
        "alternatives",
        "decision",
      ].map((id) => {
        const b = document.getElementById(id)!.getBoundingClientRect();
        return [id, b.x, b.y, b.width, b.height];
      }),
    );
  const initial = await overview();
  assert.equal(await page.locator(".worker").count(), data.run.workers.length);
  assert.deepEqual(
    await page.locator("#bookmarks button").allTextContents(),
    data.bookmarks.map((bookmark) => bookmark.label),
  );
  assert.equal(
    await page.locator("#network-context,.transport-bottom").count(),
    0,
  );
  assert.equal(
    await page.locator("#accelerated").innerText(),
    "Accelerated time",
  );
  assert.ok(
    !(await page.locator(".play-controls label").allTextContents()).some(
      (label) => label.trim() === "Speed",
    ),
    "Playback multiplier is not repeated with a Speed label",
  );
  assert.equal(
    await page.locator(".transport-top #keyboard-shortcuts").count(),
    1,
    "Keyboard hints share the top transport row",
  );
  assert.equal(await page.locator("#twin-input #forecast-time").count(), 1);
  assert.ok(
    !(await page.locator("#overview").innerText())
      .toLowerCase()
      .includes("app slots"),
    "Overview names application CPU capacity rather than app slots",
  );
  assert.equal(
    await page
      .locator("img")
      .evaluateAll(
        (imgs) =>
          imgs.filter(
            (i) =>
              !(i as HTMLImageElement).complete ||
              !(i as HTMLImageElement).naturalWidth,
          ).length,
      ),
    0,
    "Embedded branding loads offline",
  );
  await page.locator("#play").click();
  await page.waitForFunction(
    (start) =>
      Number((document.getElementById("seek") as HTMLInputElement).value) >
      start + 300,
    data.run.start,
  );
  await tab("analysis");
  assert.equal(await page.locator("#play").innerText(), "Ⅱ Pause");
  await page.locator("#speed").selectOption("4");
  const beforeComparison = Number(await page.locator("#seek").inputValue());
  await tab("comparison");
  assert.ok(!(await page.locator(".transport").isVisible()));
  assert.equal(await page.locator("#play").innerText(), "▶ Play");
  const paused = await page.locator("#seek").inputValue();
  assert.ok(
    Number(paused) >= beforeComparison,
    "Switching views retains the replay position",
  );
  await page.waitForTimeout(140);
  assert.equal(await page.locator("#seek").inputValue(), paused);
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  for (const key of ["Space", "ArrowLeft", "ArrowRight", "Home"]) {
    await page.keyboard.press(key);
    assert.equal(await page.locator("#seek").inputValue(), paused);
    assert.equal(await page.locator("#play").innerText(), "▶ Play");
  }
  await tab("analysis");
  assert.ok(await page.locator(".transport").isVisible());
  assert.equal(await page.locator("#seek").inputValue(), paused);
  assert.equal(await page.locator("#speed").inputValue(), "4");
  assert.equal(await page.locator("#play").innerText(), "▶ Play");
  await tab("overview");
  assert.ok(await page.locator(".transport").isVisible());
  assert.equal(await page.locator("#seek").inputValue(), paused);
  assert.equal(await page.locator("#speed").inputValue(), "4");
  assert.equal(
    await page.locator("#accelerated").innerText(),
    "Accelerated time",
  );
  await seek(data.run.end);
  await seek(data.run.start);
  assert.deepEqual(await overview(), initial);
  checks.push(
    `standalone relocated file, embedded logos, playback and reverse Overview seek`,
  );
  const times = [
    ...new Set([
      ...data.bookmarks.map((b) => b.at),
      ...data.cycles.flatMap((c) => [
        c.available - 1,
        c.available,
        c.available + 1000,
      ]),
      measuredAt,
      data.run.end,
      ...data.gaps.map((gap) =>
        Math.max(gap.start, gap.available ?? gap.start),
      ),
    ]),
  ].filter((t) => t >= data.run.start && t <= data.run.end);
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1600, height: 900 },
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await page.locator(".view-area").evaluate((el) => {
      el.scrollTop = 0;
    });
    await seek(data.run.start);
    const positions = await layout();
    for (const at of times) {
      await seek(at);
      const expected = viewAt(data, at);
      const display = workerDisplayAt(data, at);
      const cardView = display.view;
      assert.deepEqual(
        await page
          .locator(".worker")
          .evaluateAll((cards) =>
            cards.map((c) => c.getAttribute("data-occupied")),
          ),
        cardView.workers.map((w) => String(w.occupied ?? "unknown")),
      );
      assert.deepEqual(
        await page.locator("#physical-summary strong").allTextContents(),
        [
          expected.fresh ? String(expected.snapshot!.queue.length) : "—",
          expected.fresh ? String(expected.snapshot!.processing) : "—",
          String(expected.acceptingSlots ?? "—"),
          String(expected.completed),
          expected.fresh
            ? `${expected.workers.filter((w) => w.state?.ready && w.state.accepting).length} / ${data.run.workers.length}`
            : "—",
        ],
      );
      const requestedBands = await page
        .locator(".worker")
        .evaluateAll((cards) =>
          cards.map((card) =>
            [...card.querySelectorAll(".resource-band")].map((band) => ({
              resource: band.getAttribute("data-resource"),
              requested: band.getAttribute("data-requested"),
              capacity: band.getAttribute("data-capacity"),
              ticks: [...band.querySelectorAll(".capacity-tick")].map((t) =>
                Number(t.getAttribute("data-value")),
              ),
              phases: [...band.querySelectorAll("[data-phase]")].map(
                (segment) => ({
                  phase: segment.getAttribute("data-phase"),
                  amount: Number(segment.getAttribute("data-amount")),
                }),
              ),
            })),
          ),
        );
      const sampleStatuses = await page
        .locator(".worker .sample-status")
        .allTextContents();
      const usageMarkers = await page
        .locator(".worker")
        .evaluateAll((cards) =>
          cards.map((card) => card.querySelectorAll(".usage-marker").length),
        );
      for (const [index, bands] of requestedBands.entries()) {
        const worker = cardView.workers[index];
        if (
          !display.retained &&
          cardView.fresh &&
          worker.state?.ready &&
          worker.totalJobs === 0
        ) {
          assert.equal(
            sampleStatuses[index],
            "Measured",
            "Ready empty workers remain measured in presentation",
          );
          assert.equal(worker.cpu, null);
          assert.equal(worker.memory, null);
          assert.equal(
            usageMarkers[index],
            0,
            "The label does not invent CPU/RAM measurements",
          );
        }
        if (!display.retained && cardView.fresh && worker.totalJobs > 0) {
          assert.equal(
            sampleStatuses[index],
            worker.sampled === 0
              ? "Missing"
              : worker.sampled < worker.totalJobs
                ? "Partial"
                : "Measured",
          );
        }
        assert.equal(bands[0].requested, String(worker.occupied ?? "unknown"));
        assert.equal(bands[0].capacity, String(worker.config.cores));
        const memory =
          !cardView.fresh || worker.state?.held.some((h) => h.memoryMiB == null)
            ? "unknown"
            : String(
                worker.state!.held.reduce((sum, h) => sum + h.memoryMiB!, 0),
              );
        assert.equal(bands[1].requested, memory);
        assert.equal(bands[1].capacity, String(worker.config.memoryMiB));
        for (const band of bands) {
          assert.deepEqual(band.ticks, [
            0,
            Number(band.capacity) / 2,
            Number(band.capacity),
          ]);
          const order = ["startup", "release", "processing", "unknown"];
          assert.deepEqual(
            band.phases.map((s) => s.phase),
            [...band.phases.map((s) => s.phase)].sort(
              (a, b) => order.indexOf(a!) - order.indexOf(b!),
            ),
          );
          if (band.requested !== "unknown")
            assert.equal(
              band.phases.reduce((sum, segment) => sum + segment.amount, 0),
              Number(band.requested),
            );
        }
      }
      assert.deepEqual(
        await page
          .locator(".worker")
          .evaluateAll((cards) =>
            cards.map((c) => [
              c.getAttribute("data-retained"),
              c.getAttribute("data-observed-at"),
            ]),
          ),
        cardView.workers.map(() => [
          String(display.retained),
          String(display.observedAt ?? "unknown"),
        ]),
      );
      const service = deadlineStatus(data, at);
      assert.match(
        await page.locator("#service-status").innerText(),
        new RegExp(`${service.onTime}/${service.confirmed} confirmed`),
      );
      const decision = decisionText(data, expected);
      assert.ok(
        (await page.locator("#decision strong").innerText()).includes(
          decision.title,
        ),
      );
      assert.equal(
        await page.locator("#decision p").innerText(),
        decision.detail,
      );
      assert.deepEqual(
        await layout(),
        positions,
        `Playback changes layout at ${at}, ${viewport.width}×${viewport.height}`,
      );
      const forecast = data.cycles
        .filter(
          (c) =>
            c.available <= at && c.forecastStatus === "ready" && c.bins.length,
        )
        .at(-1)!;
      assert.equal(
        await page.locator("#twin-input").getAttribute("data-forecast-cycle"),
        String(forecast.tick),
      );
      assert.equal(
        await page.locator("#twin-input").getAttribute("data-issued-at"),
        String(forecast.available),
      );
      assert.equal(
        await page
          .locator("#forecast-chart")
          .getAttribute("data-forecast-cycle"),
        String(forecast.tick),
      );
      assert.match(
        await page.locator("#forecast-time").innerText(),
        new RegExp(
          `Issued ${Math.ceil((at - forecast.available) / 1000)}s ago`,
        ),
      );
      assert.deepEqual(
        await page
          .locator("#twin-input")
          .evaluate((input) =>
            ["data-input-queue", "data-input-assigned", "data-input-cpu"].map(
              (name) => input.getAttribute(name),
            ),
          ),
        [forecast.inputQueue, forecast.inputAssigned, forecast.inputSlots].map(
          (value) => String(value ?? ""),
        ),
        "Displayed input belongs to the forecast labeled above the graph",
      );
      assert.equal(
        await page.locator("#forecast-chart .gap").count(),
        0,
        "Worker collection gaps do not imply gaps in captured arrivals",
      );
      assert.equal(
        await page.locator("#actual-chart .gap:not([data-reason])").count(),
        0,
        "Only source-labeled queue observation gaps remain shaded",
      );
      for (const selector of [
        "#actual-chart .arrival-bar",
        "#forecast-chart .actual-bar",
      ]) {
        const bars = await page.locator(selector).evaluateAll((nodes) =>
          nodes.map((n) => ({
            start: Number(n.getAttribute("data-bin-start")),
            end: Number(n.getAttribute("data-bin-end")),
            count: Number(n.getAttribute("data-count")),
            observed:
              n.classList.contains("recorded") || n.classList.contains("open"),
          })),
        );
        for (const bar of bars) {
          assert.ok(bar.end <= at && bar.start < bar.end);
          assert.ok(
            bar.observed,
            "Arrival bars distinguish recorded and accumulating bins",
          );
          assert.equal(
            bar.count,
            data.jobs.filter(
              (j) =>
                j.available <= at &&
                j.creation >= bar.start &&
                j.creation < bar.end,
            ).length,
            `${selector}: source arrival count at ${at}`,
          );
        }
      }
      const history = await page
        .locator("#forecast-chart .forecast-line.historical")
        .evaluateAll((paths) =>
          paths.map((p) => ({
            cycle: Number(p.getAttribute("data-cycle")),
            available: Number(p.getAttribute("data-available")),
            start: Number(p.getAttribute("data-start")),
            end: Number(p.getAttribute("data-end")),
          })),
        );
      for (const segment of history) {
        const source = data.cycles.find((c) => c.tick === segment.cycle)!;
        assert.ok(source && source.forecastStatus === "ready");
        assert.equal(segment.available, source.available);
        assert.ok(segment.available <= at);
        assert.ok(segment.start < segment.end && segment.end <= at);
      }
      const overflow = await page.locator(".worker").evaluateAll(
        (cards) =>
          cards.filter((card) => {
            const b = card.getBoundingClientRect();
            return [
              ...card.querySelectorAll(
                ".worker-top,.worker-status,.resource-bars,.resource-label,.resource-axis,.capacity-tick",
              ),
            ].some((c) => {
              const x = c.getBoundingClientRect();
              return (
                x.top < b.top ||
                x.bottom > b.bottom + 1 ||
                x.right > b.right + 1
              );
            });
          }).length,
      );
      assert.equal(
        overflow,
        0,
        `Worker content containment at ${at}, ${viewport.width}`,
      );
      const overlappingStatus = await page
        .locator(".worker-status")
        .evaluateAll(
          (rows) =>
            rows.filter((row) => {
              const admission = row
                .querySelector(".admission")!
                .getBoundingClientRect();
              const sample = row
                .querySelector(".sample-status")!
                .getBoundingClientRect();
              return (
                admission.bottom > sample.top + 1 &&
                admission.right + 4 > sample.left
              );
            }).length,
        );
      assert.equal(
        overlappingStatus,
        0,
        `Worker status separation at ${at}, ${viewport.width}`,
      );
    }
    const footerOverflow = await page
      .locator(".transport-top")
      .evaluate((row) => {
        const box = row.getBoundingClientRect();
        return [
          ...row.querySelectorAll(
            "button,select,#accelerated,#keyboard-shortcuts,.clock",
          ),
        ].filter((e) => {
          const b = e.getBoundingClientRect();
          return (
            b.left < box.left - 1 ||
            b.right > box.right + 1 ||
            b.top < box.top - 1 ||
            b.bottom > box.bottom + 1
          );
        }).length;
      });
    assert.equal(
      footerOverflow,
      0,
      `Transport controls contained at ${viewport.width}`,
    );
    const horizontal = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      innerWidth,
    ]);
    assert.ok(
      horizontal[0] <= horizontal[1] + 1,
      `Horizontal page overflow ${horizontal}`,
    );
    if (viewport.width === 1920) {
      assert.equal(
        await page
          .locator(".view-area")
          .evaluate((e) => e.scrollHeight <= e.clientHeight + 1),
        true,
        "Overview fits monitor without scrolling",
      );
    }
    await seek(focusCycle.available);
    await page.screenshot({
      path: `${outputDir}/overview-${viewport.width}.png`,
    });
  }
  checks.push(
    `numeric agreement, grouped CPU/RAM request bands and invariant element positions across ${times.length} states at four sizes`,
  );
  await page.setViewportSize({ width: 1920, height: 1080 });
  let retainedGaps = 0,
    unavailableGaps = 0,
    historicalActionsDuringGaps = 0;
  for (const gap of data.gaps) {
    const at = Math.max(gap.start, gap.available ?? gap.start);
    if (at < data.run.start || at > data.run.end || viewAt(data, at).fresh)
      continue;
    const display = workerDisplayAt(data, at);
    await seek(at);
    const held = await page.locator("#workers").innerHTML();
    assert.equal(
      await page.locator('.worker[data-retained="true"]').count(),
      display.retained ? data.run.workers.length : 0,
    );
    if (display.retained)
      assert.equal(await page.locator(".worker.unknown").count(), 0);
    const expectedDecision = decisionText(data, viewAt(data, at));
    assert.equal(
      await page.locator("#decision p").innerText(),
      expectedDecision.detail,
    );
    if (expectedDecision.title.includes("previously observed"))
      historicalActionsDuringGaps++;
    await seek(data.run.end);
    await seek(at);
    assert.equal(await page.locator("#workers").innerHTML(), held);
    if (display.retained) retainedGaps++;
    else unavailableGaps++;
  }
  checks.push(
    `${retainedGaps} captured collection gaps retain published worker updates; ${unavailableGaps} expose unavailable updates; ${historicalActionsDuringGaps} preserve historical action confirmation; exact reverse seeking`,
  );
  await seek(data.run.start);
  const before = await page.locator("#forecast-chart .actual-bar").count();
  const growingHistoryAt = Math.min(
    secondReady.available - 1,
    data.run.start + firstReady.horizonMs / 4,
    data.run.end,
  );
  assert.ok(growingHistoryAt > data.run.start);
  await seek(growingHistoryAt);
  assert.ok(
    (await page.locator("#forecast-chart .actual-bar").count()) > before,
  );
  await seek(secondReady.available);
  assert.ok(
    (await page
      .locator(
        `#forecast-chart .forecast-line.historical[data-cycle="${firstReady.tick}"]`,
      )
      .count()) > 0,
    "A previously issued forecast remains visible after the next publication",
  );
  assert.ok(
    (await page
      .locator(
        `#forecast-chart .forecast-line.current[data-cycle="${secondReady.tick}"]`,
      )
      .count()) > 0,
  );
  const issuedHistory = await overview();
  await seek(data.run.end);
  await seek(secondReady.available);
  assert.deepEqual(await overview(), issuedHistory);
  await seek(secondReady.available - 1);
  assert.equal(
    await page
      .locator(
        `#forecast-chart .forecast-line[data-cycle="${secondReady.tick}"]`,
      )
      .count(),
    0,
    "Future forecast publications do not leak while rewinding",
  );
  checks.push(
    `prior issued forecast segments persist with exact reverse seeking and publication ordering`,
  );
  await seek(focusCycle.available - 1);
  assert.equal(
    await page.locator("#alternatives").getAttribute("data-cycle"),
    String(viewAt(data, focusCycle.available - 1).cycle?.tick ?? ""),
  );
  await seek(focusCycle.available);
  assert.equal(
    await page.locator("#alternatives").getAttribute("data-cycle"),
    String(focusCycle.tick),
  );
  await tab("analysis");
  await page.locator("#forecast-select").selectOption(String(firstReady.tick));
  await seek(readyCycles.at(-1)!.available);
  assert.equal(
    await page.locator("#forecast-select").inputValue(),
    String(firstReady.tick),
  );
  await page.locator("#forecast-select").selectOption("latest");
  await seek(focusCycle.available);
  await page.locator("#forecast-select").selectOption(String(focusCycle.tick));
  await seek(firstReady.available);
  assert.equal(await page.locator("#forecast-select").inputValue(), "latest");
  await seek(focusCycle.available);
  const scenario = focusCycle.futures.length - 1;
  assert.ok(
    scenario >= 0,
    "Selected captured publication contains sampled futures",
  );
  await page
    .locator("#scenario-select")
    .selectOption({ value: String(scenario) });
  await page
    .getByText("Simulation assumptions & input", { exact: true })
    .click();
  assert.match(
    await page.locator("#analysis-simulation-notes").innerText(),
    new RegExp(`sample ${scenario + 1}`),
  );
  await page.locator("#scenario-select").selectOption({ value: "0" });
  await page
    .getByText("Simulation assumptions & input", { exact: true })
    .click();
  const analysisState = () =>
    page.evaluate(() =>
      [
        "analysis-forecast-chart",
        "analysis-decision",
        "predicted-processing",
        "forecast-quality",
        "clock",
      ].map((id) => document.getElementById(id)!.innerHTML),
    );
  const analysisInitial = await analysisState();
  await seek(data.run.end);
  await seek(focusCycle.available);
  assert.deepEqual(await analysisState(), analysisInitial);
  await page.screenshot({ path: `${outputDir}/analysis-1920.png` });
  checks.push(
    `growing observed history, publication boundary, pinned forecast and causal rewind, reverse Analysis seek, sampled simulation scenarios`,
  );
  await tab("comparison");
  assert.ok(data.comparison, "Matched policy comparison is present");
  assert.equal(data.comparison.status, "accepted-final");
  assert.equal(
    data.comparison.runs.length,
    3,
    "Accepted comparison contains one matched trio",
  );
  const seeds = [...new Set(data.comparison.runs.map((run) => run.seed))];
  assert.equal(
    seeds.length,
    1,
    "Accepted comparison contains one workload seed",
  );
  assert.deepEqual(data.comparison.runs.map((run) => run.policy).sort(), [
    "fixed",
    "forecast",
    "reactive",
  ]);
  assert.equal(
    new Set(data.comparison.runs.map((run) => run.planSha256)).size,
    1,
  );
  assert.deepEqual(
    await page
      .locator("#comparison-seed option")
      .evaluateAll((options) =>
        options.map((option) => (option as HTMLOptionElement).value),
      ),
    seeds.map(String),
  );
  for (const seed of seeds) {
    await page.locator("#comparison-seed").selectOption(String(seed));
    for (const r of data.comparison!.runs.filter((r) => r.seed === seed)) {
      const service = page.locator(
        `.result-row[data-policy="${r.policy}"][data-timely]`,
      );
      assert.equal(
        await service.getAttribute("data-timely"),
        String(r.timelyJobs),
      );
      assert.equal(await service.getAttribute("data-jobs"), String(r.jobs));
      assert.equal(r.jobs, data.provenance.report.evaluatedJobs);
      assert.equal(
        r.timelyJobs,
        r.jobs,
        "Every accepted evaluation Job meets the deadline",
      );
      assert.equal(r.completedJobs, r.jobs);
      const latency = page.locator(
        `.result-row[data-policy="${r.policy}"][data-p95]`,
      );
      assert.equal(
        await latency.getAttribute("data-p95"),
        String(r.p95CompletedSeconds),
      );
      assert.equal(
        await latency.getAttribute("data-completed"),
        String(r.completedJobs),
      );
      assert.ok(
        (await latency.innerText()).includes(
          `${r.p95CompletedSeconds!.toFixed(1)}s`,
        ),
      );
      const allocation = page.locator(
        `.result-row[data-policy="${r.policy}"][data-lower]`,
      );
      assert.equal(
        await allocation.getAttribute("data-lower"),
        String(r.allocationBounds[0]),
      );
      assert.equal(
        await allocation.getAttribute("data-upper"),
        String(r.allocationBounds[1]),
      );
      assert.equal(
        await service.locator(".result-value").innerText(),
        `${((r.timelyJobs / r.jobs) * 100).toFixed(1)}% (${r.timelyJobs}/${r.jobs})`,
      );
      assert.equal(
        await allocation.locator(".result-value").innerText(),
        `${(r.allocationBounds[0] / 60).toFixed(1)}–${(r.allocationBounds[1] / 60).toFixed(1)}`,
      );
    }
    const rows: PolicyResult[] = data.comparison.runs.filter(
      (run) => run.seed === seed,
    );
    const fixed = rows.find((run) => run.policy === "fixed")!,
      reactive = rows.find((run) => run.policy === "reactive")!,
      forecast = rows.find((run) => run.policy === "forecast")!;
    const savings = [
      1 - reactive.allocationBounds[1] / fixed.allocationBounds[0],
      1 - forecast.allocationBounds[1] / fixed.allocationBounds[0],
      1 - forecast.allocationBounds[1] / reactive.allocationBounds[0],
    ];
    const conclusion = await page
      .locator("#comparison-interpretation")
      .innerText();
    for (const saving of savings) {
      assert.ok(
        saving > 0,
        "Accepted allocation bounds establish conservative savings",
      );
      assert.ok(conclusion.includes(`${(saving * 100).toFixed(1)}%`));
    }
    assert.ok(forecast.p95CompletedSeconds! > reactive.p95CompletedSeconds!);
    assert.match(conclusion, /lower allocation came with slower responses/);
    assert.ok(!conclusion.includes("This is a selected development workload."));
    assert.ok(!conclusion.includes("do not establish allocation savings"));
  }
  await page.locator("#comparison-seed").selectOption(String(seeds[0]));
  const comparisonState = () =>
    page.evaluate(() =>
      [
        "comparison-results",
        "comparison-settings",
        "comparison-interpretation",
        "policy-diagrams",
        "comparison-takeaway",
        "clock",
      ].map((id) => document.getElementById(id)!.innerHTML),
    );
  assert.deepEqual(await page.locator(".policy-cards h3").allTextContents(), [
    "Static",
    "Reactive heuristic",
    "Digital twin",
  ]);
  assert.equal(
    await page
      .locator("#comparison-conclusion,.latency-summary,#comparison-status")
      .count(),
    0,
  );
  assert.deepEqual(await page.locator(".result-chart h3").allTextContents(), [
    "Jobs meeting deadline",
    "Application allocation",
    "Response time",
  ]);
  assert.ok(!(await page.locator(".transport").isVisible()));
  assert.ok(await page.locator("#comparison-takeaway").isVisible());
  assert.deepEqual(
    await page
      .locator("#policy-diagrams .policy-flow")
      .evaluateAll((panels) =>
        panels.map((panel) => (panel as HTMLElement).dataset.policy),
      ),
    ["fixed", "reactive", "forecast"],
  );
  assert.equal(
    await page
      .locator("#policy-diagrams [data-policy=forecast] .flow-candidate")
      .count(),
    3,
  );
  assert.equal(
    await page
      .locator(
        "#policy-diagrams [data-policy=forecast] path[data-selected=true]",
      )
      .count(),
    1,
  );
  assert.equal(
    await page
      .locator(
        "#policy-diagrams [data-policy=reactive] path[data-feedback=true]",
      )
      .count(),
    1,
  );
  assert.equal(
    await page
      .locator(
        "#policy-diagrams [data-policy=forecast] path[data-feedback=true]",
      )
      .count(),
    1,
  );
  assert.deepEqual(
    await page
      .locator(".policy-flow.fixed [data-step]")
      .evaluateAll((nodes) =>
        nodes.map((node) => (node as SVGGElement).dataset.step),
      ),
    ["decide-capacity", "apply"],
  );
  assert.equal(
    await page
      .locator('#policy-diagrams [data-step="physical-outcome"]')
      .count(),
    0,
  );
  for (const policy of ["reactive", "forecast"]) {
    const flow = page.locator(`.policy-flow.${policy}`);
    assert.equal(
      await flow
        .locator(
          'path[data-from="apply"][data-to="observe"][data-feedback="true"]',
        )
        .count(),
      1,
    );
    assert.deepEqual(
      await flow.locator(".flow-feedback-label").allTextContents(),
      ["Measured feedback"],
    );
  }
  const comparisonCursor = await page.locator("#seek").inputValue();
  await page.locator("#comparison-settings-button").click();
  assert.ok(await page.locator("#comparison-dialog").isVisible());
  assert.ok(await page.locator("#comparison-settings").isVisible());
  assert.equal(await page.locator("#comparison-interpretation > p").count(), 3);
  const settings = page.locator("#comparison-settings");
  assert.equal(await settings.locator("details,summary").count(), 0);
  assert.ok(
    await settings
      .getByRole("heading", {
        name: "Controller settings and source",
        level: 3,
        exact: true,
      })
      .isVisible(),
  );
  assert.ok(
    await settings
      .getByText(data.comparison.sourceSha256, { exact: true })
      .isVisible(),
  );
  await page.locator("#comparison-dialog").focus();
  await page.keyboard.press("Home");
  assert.equal(await page.locator("#seek").inputValue(), comparisonCursor);
  await page.keyboard.press("Escape");
  assert.ok(!(await page.locator("#comparison-dialog").isVisible()));
  await page.locator("#comparison-settings-button").click();
  await page.locator("#close-comparison-settings").click();
  assert.ok(!(await page.locator("#comparison-dialog").isVisible()));
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    const geometry = await page.evaluate(() => {
      const area = document.querySelector(".view-area")!;
      const cards = [...document.querySelectorAll(".policy-cards article")];
      return {
        overflow: area.scrollHeight - area.clientHeight,
        footerHidden: (document.querySelector(".transport") as HTMLElement)
          .hidden,
        takeawayBottom: document
          .getElementById("comparison-takeaway")!
          .getBoundingClientRect().bottom,
        areaBottom: area.getBoundingClientRect().bottom,
        heights: cards.map((card) => card.getBoundingClientRect().height),
        cardBottom: Math.max(
          ...cards.map((card) => card.getBoundingClientRect().bottom),
        ),
        flows: [...document.querySelectorAll(".policy-flow")].map((flow) => {
          const box = flow.getBoundingClientRect();
          return { y: box.y, bottom: box.bottom, width: box.width };
        }),
        chartTop: document
          .getElementById("comparison-results")!
          .getBoundingClientRect().top,
        diagramLabels: [...document.querySelectorAll(".policy-flow text")].map(
          (text) => {
            const svg = text as SVGTextElement;
            const matrix = svg.getScreenCTM()!;
            return (
              parseFloat(getComputedStyle(svg).fontSize) *
              Math.hypot(matrix.a, matrix.b)
            );
          },
        ),
        charts: [...document.querySelectorAll(".result-chart")].map((chart) => {
          const box = chart.getBoundingClientRect();
          return { x: box.x, y: box.y, width: box.width, height: box.height };
        }),
        lines: [...document.querySelectorAll(".policy-cards dd")].map(
          (cell) => {
            const range = document.createRange();
            range.selectNodeContents(cell);
            return range.getClientRects().length;
          },
        ),
      };
    });
    assert.ok(
      geometry.overflow <= 1,
      `Comparison fits ${viewport.width}×${viewport.height}: ${geometry.overflow}`,
    );
    assert.ok(geometry.footerHidden);
    assert.ok(geometry.takeawayBottom <= geometry.areaBottom + 1);
    assert.ok(
      Math.max(...geometry.heights) - Math.min(...geometry.heights) <= 1,
    );
    assert.ok(geometry.lines.every((lines) => lines === 1));
    assert.equal(geometry.flows.length, 3);
    assert.ok(
      geometry.flows.every(
        (flow) =>
          flow.y >= geometry.cardBottom && flow.bottom <= geometry.chartTop,
      ),
    );
    assert.ok(
      geometry.flows.every(
        (flow) => Math.abs(flow.y - geometry.flows[0].y) <= 1,
      ),
    );
    assert.ok(geometry.diagramLabels.every((font) => font >= 18 - 0.01));
    assert.equal(geometry.charts.length, 3);
    assert.ok(
      geometry.charts.every(
        (chart) => Math.abs(chart.y - geometry.charts[0].y) <= 1,
      ),
    );
    assert.ok(
      geometry.charts[0].x < geometry.charts[1].x &&
        geometry.charts[1].x < geometry.charts[2].x,
    );
    assert.ok(
      Math.max(...geometry.charts.map((chart) => chart.width)) -
        Math.min(...geometry.charts.map((chart) => chart.width)) <=
        1,
    );
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
  checks.push(
    "comparison fits monitor and laptop viewports; hidden transport, clearer equal policy cards, three conceptual decision diagrams, three graphs, visible takeaway, grouped interpretation, visible controller settings and source, settings dialog and keyboard isolation",
  );
  const comparisonInitial = await comparisonState();
  await seek(data.run.end);
  await seek(focusCycle.available);
  assert.deepEqual(await comparisonState(), comparisonInitial);
  const finalService = deadlineStatus(data, data.run.end);
  assert.equal(finalService.onTime, data.provenance.report.timelyJobs);
  assert.equal(finalService.confirmed, data.provenance.report.evaluatedJobs);
  assert.equal(finalService.pending, 0);
  await page.screenshot({
    path: `${outputDir}/comparison-1920.png`,
  });
  checks.push(
    `all ${data.comparison.runs.length} accepted policy results for seed ${seeds[0]}, deadline cohorts, p95, conservative savings, resource/latency tradeoff and reverse Comparison seek`,
  );
  for (const zoom of [1.25, 1.5]) {
    await page.setViewportSize({
      width: Math.round(1440 / zoom),
      height: Math.round(900 / zoom),
    });
    for (const name of ["overview", "analysis", "comparison"]) {
      await tab(name);
      await page.locator(".view-area").evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });
      if (name === "comparison") {
        assert.ok(!(await page.locator(".transport").isVisible()));
        assert.ok(await page.locator("#comparison-takeaway").isVisible());
      } else {
        assert.ok(await page.locator("#play").isVisible());
        await page.locator("#restart").click();
        assert.equal(
          await page.locator("#seek").inputValue(),
          String(data.run.start),
        );
      }
      const widths = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        innerWidth,
      ]);
      assert.ok(widths[0] <= widths[1] + 1, `Zoom ${zoom}, ${name}: ${widths}`);
    }
    await page.screenshot({ path: `${outputDir}/zoom-${zoom}.png` });
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
  await tab("overview");
  assert.equal(
    await page.locator(".view-area").evaluate((el) => el.scrollTop),
    0,
    "Returning to Overview restores its top",
  );
  const skippedCycles = operatingCycles.filter(
    (cycle) => cycle.forecastStatus !== "ready" || !cycle.bins.length,
  );
  for (const fallback of skippedCycles) {
    const previousForecast = readyCycles
      .filter((cycle) => cycle.available < fallback.available)
      .at(-1);
    assert.ok(
      previousForecast,
      "Skipped captured update has an earlier ready forecast",
    );
    await seek(fallback.available);
    assert.equal(
      await page.locator("#alternatives").getAttribute("data-cycle"),
      String(fallback.tick),
    );
    assert.equal(
      await page.locator("#twin-input").getAttribute("data-forecast-cycle"),
      String(previousForecast.tick),
    );
    assert.equal(
      await page.locator("#twin-input").getAttribute("data-issued-at"),
      String(previousForecast.available),
    );
    assert.equal(
      await page.locator("#forecast-chart").getAttribute("data-forecast-cycle"),
      String(previousForecast.tick),
    );
    assert.equal(
      await page
        .getByText("No ready forecast in this cycle", { exact: true })
        .count(),
      0,
    );
    assert.match(
      await page.locator("#alternatives").innerText(),
      /Simulation update skipped/,
    );
    const fallbackState = await overview();
    await seek(data.run.end);
    await seek(fallback.available);
    assert.deepEqual(await overview(), fallbackState);
    await seek(fallback.available - 1);
    assert.equal(
      await page.locator("#alternatives").getAttribute("data-cycle"),
      String(viewAt(data, fallback.available - 1).cycle?.tick ?? ""),
    );
  }
  if (!skippedCycles.length) {
    assert.equal(readyCycles.length, operatingCycles.length);
    assert.ok(operatingCycles.every((cycle) => cycle.valid));
    assert.equal(
      data.bookmarks.filter((bookmark) => bookmark.kind === "fallback").length,
      0,
    );
    checks.push(
      `all ${readyCycles.length} captured operating forecasts are ready; no fallback recorded`,
    );
  } else
    checks.push(
      `${skippedCycles.length} captured skipped updates retain previous ready publications and rewind exactly`,
    );
  const maximum = operatingCycles.find((cycle) =>
    cycle.candidates.some(
      (candidate) =>
        candidate.name === "scale-up" &&
        candidate.unavailableReason === "maximum_worker_count",
    ),
  );
  if (maximum) {
    await seek(maximum.available);
    assert.match(
      await page
        .locator('#alternatives [data-candidate="scale-up"]')
        .innerText(),
      /At maximum capacity/,
    );
    checks.push(
      "captured maximum-capacity candidate explains its source-specific limit",
    );
  }
  await seek(focusCycle.available);
  assert.equal(
    await page.locator("#actual-chart svg .gridline").count(),
    8,
    "Four Y-axis ticks per actual-history plot",
  );
  assert.equal(
    await page
      .locator("#actual-chart svg text")
      .first()
      .evaluate((e) => getComputedStyle(e).fontSize),
    "20px",
  );
  assert.equal(await page.locator("#actual-chart .time-axis").count(), 2);
  assert.equal(await page.locator("#actual-chart .time-axis text").count(), 10);
  await seek(measuredAt);
  const markers = await page.locator(".usage-marker").evaluateAll((els) =>
    els.map((e) => ({
      color: getComputedStyle(e).backgroundColor,
      width: e.getBoundingClientRect().width,
      height: e.getBoundingClientRect().height,
    })),
  );
  assert.ok(
    markers.length > 0 && markers.every((m) => m.width === 5 && m.height >= 26),
    "Measured-use markers are wider and taller",
  );
  assert.equal(await page.locator(".usage-readout").count(), 0);
  const budgetBands = await page
    .locator('.resource-band[data-resource="cpu"] .headroom')
    .evaluateAll((els) =>
      els.map((e) => {
        const band = e.closest(".resource-band")!;
        const track = e.parentElement!;
        const box = e.getBoundingClientRect();
        const trackBox = track.getBoundingClientRect();
        const style = getComputedStyle(e);
        return {
          worker: Number(e.closest(".worker")!.getAttribute("data-worker")),
          capacity: Number(band.getAttribute("data-capacity")),
          width: box.width,
          trackWidth: track.clientWidth,
          rightOffset: trackBox.right - box.right,
          paint: `${style.backgroundColor} ${style.backgroundImage}`,
        };
      }),
    );
  assert.equal(
    budgetBands.length,
    data.run.workers.filter((w) => w.cores > w.slots).length,
  );
  for (const band of budgetBands) {
    const worker = data.run.workers[band.worker];
    assert.ok(
      Math.abs(
        band.width -
          (band.trackWidth * (worker.cores - worker.slots)) / band.capacity,
      ) <= 1,
    );
    assert.ok(band.rightOffset >= 0 && band.rightOffset <= 2);
    const colors = [...band.paint.matchAll(/rgba?\((\d+),\s*(\d+),\s*(\d+)/g)];
    assert.ok(
      colors.some(
        ([, r, g, b]) =>
          Number(r) > Number(g) + 15 && Number(r) > Number(b) + 15,
      ),
      "Outside-budget CPU band has a visible red/coral fill",
    );
  }
  const scale = await page
    .locator("#forecast-chart svg text")
    .first()
    .evaluate((e) => {
      const m = (e as SVGGraphicsElement).getScreenCTM()!;
      return { x: m.a, y: m.d, font: getComputedStyle(e).fontSize };
    });
  assert.ok(Math.abs(scale.x - 1) < 0.01 && Math.abs(scale.y - 1) < 0.01);
  assert.equal(scale.font, "18px");
  await page.locator("#evidence-button").click();
  assert.equal(
    await page
      .locator("#evidence-dialog")
      .evaluate((e) => (e as HTMLDialogElement).open),
    true,
  );
  await page.locator("#close-evidence").click();
  for (const [index, bookmark] of data.bookmarks.entries()) {
    await page.locator("#bookmarks button").nth(index).click();
    assert.equal(await page.locator("#seek").inputValue(), String(bookmark.at));
  }
  checks.push(
    `zoom equivalents, reachable transport, captured gap/forecast semantics, unscaled 18px chart labels and every dataset bookmark`,
  );
  await context.close();
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  checks.push(
    "Zero browser errors or external requests with networking disabled",
  );
  result.passed = true;
} finally {
  writeFileSync(
    resolve(outputDir, "browser.json"),
    JSON.stringify(result, null, 2) + "\n",
  );
  rmSync(relocated, { recursive: true, force: true });
  await browser.close();
}
console.log(JSON.stringify(result, null, 2));
