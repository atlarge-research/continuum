/** Actual disk/offline browser acceptance for all views, timing and viewport behavior. */
import assert from "node:assert/strict";
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
import { deadlineStatus, workerDisplayAt } from "../src/presentation.ts";
import type { Dataset } from "../src/types.ts";
process.env.PLAYWRIGHT_BROWSERS_PATH = resolve("evidence/browser");
const { chromium } = await import("@playwright/test");
const data: Dataset = JSON.parse(readFileSync("data/replay.json", "utf8"));
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
  assert.equal(await page.locator(".worker").count(), 6);
  assert.deepEqual(await page.locator("#bookmarks button").allTextContents(), [
    "Start",
    "Scale-down decision",
    "Demand rises",
    "Scale-up decision",
    "Scale-up confirmed",
    "Update skipped",
    "End",
  ]);
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
  await tab("comparison");
  assert.equal(await page.locator("#play").innerText(), "Ⅱ Pause");
  await page.locator("#play").click();
  const paused = await page.locator("#seek").inputValue();
  await page.waitForTimeout(140);
  assert.equal(await page.locator("#seek").inputValue(), paused);
  await page.locator("#speed").selectOption("4");
  await tab("overview");
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
      1403500,
      1423038,
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
    await seek(data.cycles[5].available);
    await page.screenshot({
      path: `${outputDir}/overview-${viewport.width}.png`,
    });
  }
  checks.push(
    `numeric agreement, grouped CPU/RAM request bands and invariant element positions across ${times.length} states at four sizes`,
  );
  await page.setViewportSize({ width: 1920, height: 1080 });
  let retainedGaps = 0;
  for (const gap of data.gaps.filter((g) => g.start >= data.run.start)) {
    const at = Math.max(gap.start, gap.available ?? gap.start);
    if (viewAt(data, at).fresh) continue;
    await seek(at);
    const held = await page.locator("#workers").innerHTML();
    assert.equal(
      await page.locator('.worker[data-retained="true"]').count(),
      6,
    );
    assert.equal(await page.locator(".worker.unknown").count(), 0);
    await seek(data.run.end);
    await seek(at);
    assert.equal(await page.locator("#workers").innerHTML(), held);
    retainedGaps++;
  }
  checks.push(
    `all ${retainedGaps} operating collection gaps retain already-published worker updates and reproduce exactly after reverse seeking`,
  );
  await seek(data.run.start);
  const before = await page.locator("#forecast-chart .actual-bar").count();
  await seek(data.run.start + 45000);
  assert.ok(
    (await page.locator("#forecast-chart .actual-bar").count()) > before,
  );
  await seek(data.cycles[1].available);
  assert.ok(
    (await page
      .locator(
        `#forecast-chart .forecast-line.historical[data-cycle="${data.cycles[0].tick}"]`,
      )
      .count()) > 0,
    "A previously issued forecast remains visible after the next publication",
  );
  assert.ok(
    (await page
      .locator(
        `#forecast-chart .forecast-line.current[data-cycle="${data.cycles[1].tick}"]`,
      )
      .count()) > 0,
  );
  const issuedHistory = await overview();
  await seek(data.run.end);
  await seek(data.cycles[1].available);
  assert.deepEqual(await overview(), issuedHistory);
  await seek(data.cycles[1].available - 1);
  assert.equal(
    await page
      .locator(
        `#forecast-chart .forecast-line[data-cycle="${data.cycles[1].tick}"]`,
      )
      .count(),
    0,
    "Future forecast publications do not leak while rewinding",
  );
  checks.push(
    `prior issued forecast segments persist with exact reverse seeking and publication ordering`,
  );
  await seek(data.cycles[5].available - 1);
  assert.equal(
    await page.locator("#alternatives").getAttribute("data-cycle"),
    "5",
  );
  await seek(data.cycles[5].available);
  assert.equal(
    await page.locator("#alternatives").getAttribute("data-cycle"),
    "6",
  );
  await tab("analysis");
  await page
    .locator("#forecast-select")
    .selectOption(String(data.cycles[0].tick));
  await seek(data.cycles[6].available);
  assert.equal(
    await page.locator("#forecast-select").inputValue(),
    String(data.cycles[0].tick),
  );
  await page.locator("#forecast-select").selectOption("latest");
  await seek(data.cycles[5].available);
  await page.locator("#forecast-select").selectOption("6");
  await seek(data.cycles[0].available);
  assert.equal(await page.locator("#forecast-select").inputValue(), "latest");
  await seek(data.cycles[5].available);
  await page.locator("#scenario-select").selectOption({ value: "2" });
  await page
    .getByText("Simulation assumptions & input", { exact: true })
    .click();
  assert.match(
    await page.locator("#analysis-simulation-notes").innerText(),
    /sample 3/,
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
  await seek(data.cycles[5].available);
  assert.deepEqual(await analysisState(), analysisInitial);
  await page.screenshot({ path: `${outputDir}/analysis-1920.png` });
  checks.push(
    `growing observed history, publication boundary, pinned forecast and causal rewind, reverse Analysis seek, sampled simulation scenarios`,
  );
  await tab("comparison");
  for (const seed of [...new Set(data.comparison!.runs.map((r) => r.seed))]) {
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
    assert.match(
      await page.locator("#comparison-conclusion").innerText(),
      /do not establish allocation savings/,
    );
  }
  await page.locator("#comparison-seed").selectOption("62002");
  await page.screenshot({
    path: `${outputDir}/comparison-1920.png`,
  });
  checks.push(
    `all six policy results, bounds, workload selection and honest preliminary conclusion`,
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
      assert.ok(await page.locator("#play").isVisible());
      await page.locator("#restart").click();
      assert.equal(
        await page.locator("#seek").inputValue(),
        String(data.run.start),
      );
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
  await seek(1403500);
  const confirmed = await page.locator("#decision p").innerText();
  await seek(1423038);
  assert.match(
    await page.locator("#decision strong").innerText(),
    /previously observed/,
  );
  const gap = await page.locator("#decision p").innerText();
  assert.equal(gap.match(/\d\d:\d\d/)![0], confirmed.match(/\d\d:\d\d/)![0]);
  const fallback = data.cycles.find((c) => !c.valid && !c.bins.length)!;
  const previousForecast = data.cycles
    .filter(
      (c) =>
        c.available < fallback.available &&
        c.forecastStatus === "ready" &&
        c.bins.length,
    )
    .at(-1)!;
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
  assert.ok(
    (await page
      .locator(
        "#forecast-chart .forecast-line.current,#forecast-chart .scenario-range",
      )
      .count()) >= 2,
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
  assert.match(
    await page.locator("#forecast-status").innerText(),
    /Update skipped/,
  );
  assert.match(
    await page.locator("#decision strong").innerText(),
    /Keep current worker admission|Keep current capacity|Do nothing/,
  );
  const fallbackState = await overview();
  await seek(data.run.end);
  await seek(fallback.available);
  assert.deepEqual(await overview(), fallbackState);
  await seek(fallback.available - 1);
  assert.equal(
    await page.locator("#alternatives").getAttribute("data-cycle"),
    String(previousForecast.tick),
  );
  assert.ok(
    !(await page.locator("#alternatives").innerText()).includes(
      "Simulation update skipped",
    ),
  );
  assert.ok(
    !(await page.locator("#forecast-status").innerText()).includes(
      "Update skipped",
    ),
  );
  await seek(
    data.cycles.find((c) =>
      c.candidates.some(
        (candidate) => candidate.name === "scale-up" && !candidate.valid,
      ),
    )!.available,
  );
  assert.match(
    await page.locator('#alternatives [data-candidate="scale-up"]').innerText(),
    /At maximum capacity/,
  );
  checks.push(
    `skipped cycle preserves its recorded fallback while retaining the earlier ready forecast and source-specific capacity reasons`,
  );
  await seek(data.cycles[5].available);
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
  await page
    .locator("#bookmarks button")
    .filter({ hasText: "Scale-up decision" })
    .click();
  assert.equal(
    await page.locator("#seek").inputValue(),
    String(data.cycles[5].available),
  );
  checks.push(
    `zoom equivalents, reachable transport, gap/fallback semantics, unscaled 18px chart labels and bookmarks`,
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
