import { latestReadyForecast } from "./forecast-history.ts";
import { decisionText } from "./decision.ts";
import type { Dataset, Cycle } from "./types.ts";
import { viewAt, forecastActuals } from "./replay.ts";
import type { ReplayView } from "./replay.ts";
import { playbackCommand, advancePlayback } from "./playhead.ts";
import type { Command, Playback } from "./playhead.ts";
import {
  actualChart,
  forecastChart,
  escapeHtml as e,
  formatTime,
} from "./charts.ts";
import {
  deadlineStatus,
  comparisonConclusion,
  resourceUsage,
  workerDisplayAt,
  resourceReservations,
  selectedForecast,
  predictedOccupancy,
} from "./presentation.ts";
const data: Dataset = JSON.parse(
  document.getElementById("replay-data")!.textContent!,
);
if (data.schemaVersion !== 1 || data.run.workers.length !== 6)
  throw new Error("Unsupported captured replay dataset");
let playback: Playback = { cursor: data.run.start, speed: 16, playing: false };
let activeView = "overview",
  forecastTick: number | null = null,
  scenario = 0;
let comparisonSeed =
  data.comparison?.runs.find((r) => r.captureId === data.run.id)?.seed ??
  data.comparison?.runs[0]?.seed ??
  0;
const element = (id: string) => document.getElementById(id)!;
const seek = element("seek") as HTMLInputElement;
seek.min = String(data.run.start);
seek.max = String(data.run.end);
seek.value = String(data.run.start);
const precise = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : value.toFixed(digits);
const time = (value: number) => formatTime(value - data.run.start);
const actionName = (action: string) =>
  action === "scale-up"
    ? "Scale up"
    : action === "scale-down"
      ? "Scale down"
      : "Do nothing";
function workerCards(display: ReturnType<typeof workerDisplayAt>): string {
  const { view, retained, observedAt, ageMs } = display;
  return view.workers
    .map((worker, index) => {
      const state = worker.state;
      const mode =
        !view.fresh || !state?.ready
          ? "unknown"
          : state.accepting
            ? "accepting"
            : worker.pending
              ? "pending"
              : (worker.occupied ?? 0) > 0
                ? "draining"
                : "reserve";
      const admission = (
        {
          unknown: "Unknown",
          accepting: "Accepting",
          pending: "Requested",
          draining: "Draining",
          reserve: "Powered reserve",
        } as Record<string, string>
      )[mode];
      const usage = resourceUsage(worker);
      const requests = resourceReservations(worker);
      const value = (n: number) => Number(n.toFixed(2)).toString();
      const resourceBar = (kind: "cpu" | "memory") => {
        const cpu = kind === "cpu";
        const capacity = cpu ? worker.config.cores : worker.config.memoryMiB;
        const amount = cpu ? requests.cpuRequested : requests.memoryRequested;
        const percent = cpu ? usage.cpuPercent : usage.memoryPercent;
        const unit = cpu ? "cores" : "GiB";
        const scale = cpu ? 1 : 1024;
        const outside = cpu ? requests.outsideCpuBudget : 0;
        const segments =
          amount === null
            ? ""
            : requests.segments
                .map((segment) => {
                  const allocation = cpu ? segment.cpu : segment.memory;
                  return allocation == null || allocation <= 0
                    ? ""
                    : `<i class="request-segment ${segment.phase}" data-phase="${segment.phase}" data-amount="${allocation}" style="width:${(allocation / capacity) * 100}%" title="${e(segment.phase)}: ${value(allocation / scale)} ${unit} requested"></i>`;
                })
                .join("");
        const requested =
          amount === null
            ? "Requests unavailable"
            : `${value(amount / scale)} / ${value(capacity / scale)} ${unit} requested`;
        const axis = [0, 0.5, 1]
          .map(
            (fraction) =>
              `<span class="capacity-tick" data-value="${capacity * fraction}" style="left:${fraction * 100}%">${value((capacity * fraction) / scale)}${!cpu && fraction === 1 ? "G" : ""}</span>`,
          )
          .join("");
        return `<div class="resource-band" data-resource="${kind}" data-requested="${amount ?? "unknown"}" data-capacity="${capacity}" title="${e(requested)}. ${cpu ? `${value(outside)} core outside application budget; this is not measured system use.` : "G denotes GiB. No system memory reservation is inferred."}"><div class="resource-label">${cpu ? "CPU" : "RAM"}</div><div class="request-track ${amount === null ? "unknown" : ""}">${outside ? `<i class="request-segment headroom" style="width:${(outside / capacity) * 100}%" title="Outside application budget"></i>` : ""}${segments}${percent === null ? "" : `<i class="usage-marker ${usage.coverage}" style="left:clamp(0px, ${Math.min(100, percent)}%, calc(100% - 5px))" title="Measured application use: ${precise(percent)}% of VM capacity"></i>`}</div><div class="resource-axis" aria-label="${cpu ? "CPU cores" : "RAM in GiB"}">${axis}</div></div>`;
      };
      const coverage =
        usage.coverage === "partial"
          ? "Partial"
          : usage.coverage === "missing"
            ? view.fresh && worker.totalJobs === 0
              ? state?.ready
                ? "Measured"
                : "Idle"
              : "Missing"
            : "Measured";
      const detail = `${retained ? `Retained worker update from ${time(observedAt!)} (${Math.ceil(ageMs! / 1000)}s old). ` : ""}Application samples: ${worker.sampled}/${worker.totalJobs} Jobs; CPU ${precise(worker.cpu, 2)} cores / ${worker.config.cores} VM cores; RAM ${precise(worker.memory, 1)} MiB / ${worker.config.memoryMiB} MiB. ${view.fresh && state?.ready && worker.totalJobs === 0 ? "Ready worker with no assigned Jobs; per-Job application samples are not applicable" : worker.sampleAge === null ? "No fresh samples" : `Oldest sample ${Math.ceil((worker.sampleAge + (retained ? ageMs! : 0)) / 1000)}s old`}. Powered VM; measured application use is separate from requested CPU.`;
      return `<article class="worker ${mode}" data-worker="${index}" data-occupied="${worker.occupied ?? "unknown"}" data-coverage="${usage.coverage}" data-retained="${retained}" data-observed-at="${observedAt ?? "unknown"}" title="${e(detail)}"><div class="worker-top"><h3>${e(worker.config.label)}</h3><span class="job-count">${view.fresh ? worker.totalJobs : "—"} Jobs</span></div><div class="worker-status"><span class="admission">${admission}</span><span class="sample-status muted">${retained ? `${Math.ceil(ageMs! / 1000)}s old` : coverage}</span></div><div class="resource-bars ${usage.coverage}" aria-label="Requested resources and measured application use">${resourceBar("cpu")}${resourceBar("memory")}</div></article>`;
    })
    .join("");
}
function alternatives(cycle: Cycle | null): string {
  if (!cycle || !cycle.valid || !cycle.candidates.length)
    return `<div class="simulation-status"><strong>Simulation update skipped</strong><span>Recorded action: ${cycle ? actionName(cycle.action) : "Waiting for publication"}</span><span>Recorded decision is shown below.</span></div>`;
  return `<table class="alternative-table"><thead><tr><th>Capacity option</th><th>Within deadline</th><th>CPU allocation</th></tr></thead><tbody>${[
    "unchanged",
    "scale-up",
    "scale-down",
  ]
    .map((name) => {
      const c = cycle.candidates.find((c) => c.name === name),
        chosen = name === cycle.action;
      const service =
        c?.valid && c.onTime !== null
          ? `${(c.onTime * 100).toFixed(1)}%`
          : c?.unavailableReason === "maximum_worker_count"
            ? "At maximum capacity"
            : "Not evaluated";
      const allocation =
        c?.allocationCoreSeconds != null
          ? `${(c.allocationCoreSeconds / 60).toFixed(1)} core-min`
          : "—";
      return `<tr class="${chosen ? "chosen" : ""}" data-candidate="${name}"><td>${actionName(name)}${chosen ? '<span class="choice-label" title="Recorded choice; application depends on safety checks">✓</span>' : ""}</td><td class="${c?.onTime != null && c.onTime < data.run.deadlineFraction ? "prediction-low" : ""}" title="Worst captured sampled future under historical controller timing rules">${service}</td><td title="Predicted requested application core-time">${allocation}</td></tr>`;
    })
    .join("")}</tbody></table>`;
}
function serviceText(cursor: number, detail = false): string {
  const s = deadlineStatus(data, cursor);
  const fraction = s.percent === null ? "—" : `${s.percent.toFixed(1)}%`;
  return detail
    ? `<h3>Observed service performance</h3><p><strong>${fraction}</strong> of confirmed evaluation outcomes met the ${data.run.deadlineSeconds}s deadline: ${s.onTime} on time, ${s.missed} missed or failed, ${s.pending} pending. Target: ≥${Math.round(data.run.deadlineFraction * 100)}%. Pending outcomes are excluded from this provisional percentage; this is not the final whole-cohort result.</p><p>The deadline measures original API Job creation to terminal Job completion. Classifier processing can finish earlier and remains separate from this service clock. Evaluation arrivals only; preceding history remains internal.</p>`
    : `<strong title="On-time fraction of confirmed evaluation outcomes; pending excluded">${fraction} on time</strong><span>${s.onTime}/${s.confirmed} confirmed</span><span class="missed">${s.missed} missed</span><span class="pending">${s.pending} pending</span><span class="service-target" title="Target applies to the full evaluation cohort, including failures and unfinished work">≤${data.run.deadlineSeconds}s · target ${Math.round(data.run.deadlineFraction * 100)}%</span>`;
}
function renderAnalysis(view: ReplayView): void {
  const available = data.cycles.filter(
    (c) => c.available >= data.run.start && c.available <= view.cursor,
  );
  if (forecastTick !== null && !available.some((c) => c.tick === forecastTick))
    forecastTick = null;
  const cycle = selectedForecast(data, view.cursor, forecastTick),
    select = element("forecast-select") as HTMLSelectElement;
  select.innerHTML =
    '<option value="latest">Latest</option>' +
    available
      .map(
        (c) =>
          `<option value="${c.tick}">Cycle ${c.tick} · ${time(c.available)}${c.valid ? "" : " · fallback"}</option>`,
      )
      .join("");
  select.value = forecastTick === null ? "latest" : String(forecastTick);
  element("analysis-forecast-input").innerHTML = cycle
    ? `<span>Cycle ${cycle.tick} · issued ${time(cycle.available)}</span><span>Input cutoff ${time(cycle.cutoff)} · age ${Math.ceil((view.cursor - cycle.available) / 1000)}s</span>`
    : "No operating forecast published";
  element("analysis-cycle").textContent = cycle
    ? `Recorded cycle ${cycle.tick}`
    : "";
  const quality = cycle ? forecastActuals(data, cycle, view.cursor) : [],
    covered = quality.filter((b) => b.complete);
  const mae = covered.length
    ? covered.reduce((s, b) => s + Math.abs(b.actual! - b.expected), 0) /
      covered.length
    : null;
  element("forecast-quality").innerHTML =
    mae === null
      ? "Forecast error waits for covered actual observations."
      : `Mean absolute error: <strong>${mae.toFixed(2)} Jobs / ${cycle!.binMs / 1000}s</strong> · ${covered.length} covered bins`;
  element("analysis-forecast-notes").innerHTML =
    `<p>Shading spans the minimum and maximum of ${cycle?.futures.length ?? 0} captured sampled futures. It is a scenario range, not a calibrated confidence interval. The expected forecast can lie outside a small set of sampled futures.</p><p>Solid bars: arrivals recorded by the cursor. Hatched bars: the current interval still filling. Counts may update as new observations arrive. Brief worker-membership gaps do not establish lost arrivals. Actual observations appear only after publication. Configured decision cadence: ${data.run.cadenceSeconds}s; actual issue intervals include computation and vary.</p>`;
  element("resource-detail").innerHTML =
    `<table class="resource-table"><thead><tr><th>Worker</th><th>App CPU</th><th>App RAM</th><th>Coverage / age</th></tr></thead><tbody>${view.workers.map((w) => `<tr><td>${e(w.config.label)}</td><td>${precise(w.cpu, 2)} cores</td><td>${precise(w.memory, 1)} MiB</td><td>${view.fresh ? `${w.sampled}/${w.totalJobs} Jobs · ${w.sampleAge === null ? "—" : `${Math.ceil(w.sampleAge / 1000)}s`}` : "State unknown"}</td></tr>`).join("")}</tbody></table><p class="analysis-notes">CPU is a ${data.run.sampleMaxAgeMs - data.run.maxGapMs}ms short-window application rate; RAM is working-set memory. Available recent per-Job samples are aggregated; partial coverage is not a complete worker total. Percentages use configured VM cores and RAM, not reserved application capacity. Samples can sum above 100% because their windows differ; they are not simultaneous whole-node measurements.</p>`;
  element("analysis-alternatives").innerHTML = alternatives(cycle);
  const status = decisionText(data, { ...view, cycle });
  element("analysis-decision").className =
    `decision${status.warning ? " warning" : ""}`;
  element("analysis-decision").innerHTML =
    `<strong><span class="badge">${e(status.stage)}</span>${e(status.title)}</strong><p>${e(status.detail)}</p>`;
  const count = cycle?.futures.length ?? 0;
  scenario = Math.min(scenario, Math.max(0, count - 1));
  const scenarios = element("scenario-select") as HTMLSelectElement;
  scenarios.innerHTML = count
    ? Array.from(
        { length: count },
        (_, i) => `<option value="${i}">${i + 1}</option>`,
      ).join("")
    : '<option value="0">—</option>';
  scenarios.value = String(scenario);
  element("predicted-processing").innerHTML =
    `<table class="allocation-table"><thead><tr><th>Worker</th><th>Predicted CPU requests</th><th>Observed CPU requests</th></tr></thead><tbody>${view.workers
      .map((w, i) => {
        const predicted = predictedOccupancy(cycle, i, view.cursor, scenario);
        const cell = (v: number | null, cls: string) =>
          `<td class="allocation-cell ${cls}"><div class="allocation-body"><span>${v ?? "—"} / ${w.config.slots}</span><div class="allocation-track"><i style="width:${v === null ? 0 : Math.min(100, (v / w.config.slots) * 100)}%"></i></div></div></td>`;
        return `<tr><td>${e(w.config.label)}</td>${cell(predicted, "predicted")}${cell(w.occupied, "observed")}</tr>`;
      })
      .join("")}</tbody></table>`;
  element("analysis-simulation-notes").innerHTML =
    `<p>${cycle && view.cursor > cycle.cutoff + cycle.horizonMs ? "The cursor is beyond this prediction horizon; predicted occupancy is unavailable." : `Predictions show the recorded selected option, sample ${scenario + 1}, at the playback cursor.`} They describe occupied requested CPU units, not measured CPU use. ${status.stage === "Guard veto" ? "The selected option was vetoed and remains hypothetical." : "A prediction is conditional on its proposed action and captured assumptions; later physical decisions may differ."}</p><p>Input: ${cycle?.inputQueue ?? "—"} queued Jobs, ${cycle?.inputAssigned ?? "—"} assigned CPU cores, ${cycle?.inputSlots ?? "—"} app CPU cores. Native scores and modeled timing are preserved from the historical run. Admission requests, acknowledgements and observed availability are distinct.</p>`;
  element("analysis-service").innerHTML = serviceText(view.cursor, true);
  element("analysis-forecast-chart").innerHTML = forecastChart(
    data,
    view,
    {
      width: element("analysis-forecast-chart").clientWidth,
      height: element("analysis-forecast-chart").clientHeight,
    },
    { cycle, detail: true },
  );
}
function renderComparison(): void {
  const comparison = data.comparison;
  if (!comparison?.runs.length) {
    element("comparison-results").innerHTML =
      '<div class="empty-chart">Matched comparison evidence is unavailable for this dataset.</div>';
    element("comparison-conclusion").textContent =
      "Policy capabilities remain visible; no measured comparison is asserted.";
    return;
  }
  const seeds = [...new Set(comparison.runs.map((r) => r.seed))];
  const select = element("comparison-seed") as HTMLSelectElement;
  select.innerHTML = seeds
    .map((seed) => `<option value="${seed}">${seed}</option>`)
    .join("");
  select.value = String(comparisonSeed);
  const rows = comparison.runs.filter((r) => r.seed === comparisonSeed),
    fixed = rows.find((r) => r.policy === "fixed")!,
    forecast = rows.find((r) => r.policy === "forecast")!,
    reactive = rows.find((r) => r.policy === "reactive")!;
  const label = (policy: string) =>
    policy === "fixed"
      ? "Static"
      : policy === "reactive"
        ? "Reactive"
        : "Digital twin";
  const maxAllocation = Math.max(...rows.map((r) => r.allocationBounds[1]));
  const service = rows
    .map(
      (r) =>
        `<div class="result-row ${r.policy}" data-policy="${r.policy}" data-timely="${r.timelyJobs}" data-jobs="${r.jobs}"><span>${label(r.policy)}</span><div class="result-track"><i class="bar" style="width:${(r.timelyJobs / r.jobs) * 100}%"></i><i class="target-marker" style="left:${r.targetFraction * 100}%" title="${r.targetFraction * 100}% service target"></i></div><span class="result-value">${((r.timelyJobs / r.jobs) * 100).toFixed(1)}% <span class="muted">(${r.timelyJobs}/${r.jobs})</span></span></div>`,
    )
    .join("");
  const allocation = rows
    .map(
      (r) =>
        `<div class="result-row ${r.policy}" data-policy="${r.policy}" data-lower="${r.allocationBounds[0]}" data-upper="${r.allocationBounds[1]}"><span>${label(r.policy)}</span><div class="result-track"><i class="bar" style="width:${(r.allocationBounds[0] / maxAllocation) * 100}%"></i><i class="bounds" style="left:${(r.allocationBounds[0] / maxAllocation) * 100}%;width:${((r.allocationBounds[1] - r.allocationBounds[0]) / maxAllocation) * 100}%" title="Observation-coverage bounds, not a confidence interval"></i></div><span class="result-value">${(r.allocationBounds[0] / 60).toFixed(1)}–${(r.allocationBounds[1] / 60).toFixed(1)}</span></div>`,
    )
    .join("");
  element("comparison-status").textContent =
    `${comparison.status === "accepted-final" ? "Accepted final" : "Preliminary"} evidence · independent of replay time`;
  element("comparison-results").innerHTML =
    `<div class="result-charts"><section class="result-chart"><h3>Jobs meeting the deadline</h3><p class="chart-subtitle">≤${fixed.deadlineSeconds}s · marker: ${fixed.targetFraction * 100}% target</p>${service}</section><section class="result-chart"><h3>Allocated application capacity</h3><p class="chart-subtitle">Core-minutes · bounds retain missing observations</p>${allocation}</section></div><div class="latency-summary"><strong>Completed-Job response p95</strong>${rows.map((r) => `<span data-policy="${r.policy}" data-p95="${r.p95CompletedSeconds ?? "unknown"}" data-completed="${r.completedJobs}">${label(r.policy)}: ${precise(r.p95CompletedSeconds, 1)}s (${r.completedJobs} completed)</span>`).join("")}</div>`;
  element("comparison-conclusion").textContent = comparisonConclusion(
    comparison,
    comparisonSeed,
  );
  element("comparison-settings").innerHTML =
    `<ul><li>Same planned workload within seed ${comparisonSeed}; ${fixed.jobs} evaluation Jobs. Common ${fixed.evaluationSeconds}s allocation window; ${fixed.followupSeconds}s completion follow-up.</li><li>Initial workers: static ${fixed.initialWorkers}; reactive ${reactive.initialWorkers}; twin ${forecast.initialWorkers}. All use the same ${fixed.workerCount}-worker physical pool; reserves stay powered.</li><li>Acquisition: delayed admission, minimum ${fixed.acquisitionSeconds}s. Recorded cadences: reactive ${reactive.cadenceSeconds}s; twin ${forecast.cadenceSeconds}s.</li><li>Recorded reactive capacity target: ${precise(reactive.reactiveTargetFraction == null ? null : reactive.reactiveTargetFraction * 100, 0)}%. Thresholds: up ${precise(reactive.reactiveUpThreshold === null ? null : reactive.reactiveUpThreshold * 100, 0)}%; down ${precise(reactive.reactiveDownThreshold === null ? null : reactive.reactiveDownThreshold * 100, 0)}%. ${reactive.reactiveStabilizationSeconds === null ? "Do not substitute settings from a later campaign." : `Downscale stabilization ${reactive.reactiveStabilizationSeconds}s.`}</li><li>Service is original API Job creation to terminal Job completion; the denominator includes failed and unfinished evaluation Jobs. Response p95 describes completed Jobs only. Allocation includes accepting, draining and pending acquired capacity.</li><li>Capture network: ${e(fixed.network)}. ${comparison.status === "accepted-final" ? `The ${fixed.initialWorkers}-worker static baseline is adequate; its minimum adequate size is not established. ` : ""}Results apply to these captured workloads; no forecast-only ablation isolates simulation's incremental benefit.</li></ul><p>Source report SHA-256: <code>${e(comparison.sourceSha256)}</code></p>`;
}
function render(): void {
  const cursor = Math.floor(playback.cursor),
    view = viewAt(data, cursor),
    cycle = view.cycle,
    status = decisionText(data, view);
  if (
    forecastTick !== null &&
    !data.cycles.some((c) => c.tick === forecastTick && c.available <= cursor)
  )
    forecastTick = null;
  element("app").dataset.cursor = String(cursor);
  element("app").dataset.view = activeView;
  const accepting = view.fresh
    ? view.workers.filter((w) => w.state?.ready && w.state.accepting).length
    : null;
  const metric = (value: number | string | null, label: string, extra = "") =>
    `<div class="metric"><strong>${value ?? "—"}</strong><span>${label}</span>${extra ? `<br><small>${extra}</small>` : ""}</div>`;
  element("physical-summary").innerHTML =
    metric(view.fresh ? view.snapshot!.queue.length : null, "Jobs waiting") +
    metric(view.fresh ? view.snapshot!.processing : null, "Jobs processing") +
    metric(view.acceptingSlots, "App CPU cores") +
    metric(view.completed, "Jobs completed") +
    metric(
      accepting === null ? null : `${accepting} / ${data.run.workers.length}`,
      "Workers accepting",
    );
  element("workers").innerHTML = workerCards(
    workerDisplayAt(data, playback.cursor),
  );
  element("service-status").innerHTML = serviceText(cursor);
  element("service-status").title =
    "Evaluation arrivals: provisional on-time fraction of confirmed outcomes. Pending outcomes are excluded; full-cohort results are in Policy comparison.";
  element("observation-age").innerHTML = view.fresh
    ? `Observed ${precise((cursor - view.snapshot!.at) / 1000)}s ago`
    : '<span class="unknown-banner">Observation gap</span>';
  const forecast = latestReadyForecast(data, cursor);
  const retained = !!forecast && cycle?.tick !== forecast.tick;
  const strip = element("twin-input");
  strip.dataset.forecastCycle = String(forecast?.tick ?? "");
  strip.dataset.issuedAt = String(forecast?.available ?? "");
  strip.dataset.inputQueue = String(forecast?.inputQueue ?? "");
  strip.dataset.inputAssigned = String(forecast?.inputAssigned ?? "");
  strip.dataset.inputCpu = String(forecast?.inputSlots ?? "");
  strip.dataset.retained = String(retained);
  element("forecast-input").innerHTML = forecast
    ? `<span>Input: <strong>${forecast.inputQueue ?? "—"} queued · ${forecast.inputAssigned ?? "—"} assigned cores</strong></span><span><strong>${forecast.inputSlots ?? "—"} app CPU cores</strong></span>`
    : "Waiting for captured forecast";
  element("forecast-time").textContent = forecast
    ? `Issued ${Math.ceil((cursor - forecast.available) / 1000)}s ago · ${forecast.horizonMs / 1000}s horizon · ${forecast.futures.length} futures`
    : "No forecast issued";
  const expired = !!forecast && cursor >= forecast.cutoff + forecast.horizonMs;
  element("forecast-status").textContent = expired
    ? "Horizon elapsed"
    : retained
      ? "Update skipped"
      : "";
  element("forecast-status").title = retained
    ? "Previous forecast retained; the latest update was skipped. Recorded reasons: " +
      (cycle?.forecastReasons?.join(", ") || cycle?.reason || "unavailable")
    : "";
  element("forecast-chart").dataset.forecastCycle = String(
    forecast?.tick ?? "",
  );
  element("alternatives").dataset.cycle = String(cycle?.tick ?? "");
  element("alternatives").innerHTML = alternatives(cycle);
  element("prediction-window").textContent =
    `Target ${Math.round(data.run.deadlineFraction * 100)}% ≤ ${data.run.deadlineSeconds}s`;
  element("decision").className = `decision${status.warning ? " warning" : ""}`;
  element("decision").innerHTML =
    `<strong><span class="badge">${e(status.stage)}</span>${e(status.title)}</strong><p>${e(status.detail)}</p>`;
  element("clock").textContent = time(cursor);
  element("duration").textContent = `/ ${time(data.run.end)}`;
  seek.value = String(cursor);
  seek.setAttribute(
    "aria-valuetext",
    `${time(cursor)} recorded operating replay`,
  );
  const play = element("play");
  play.textContent = playback.playing ? "Ⅱ Pause" : "▶ Play";
  play.setAttribute(
    "aria-label",
    playback.playing ? "Pause replay" : "Play replay",
  );
  for (const button of element("bookmarks").querySelectorAll<HTMLButtonElement>(
    "button",
  ))
    button.classList.toggle(
      "active",
      Math.abs(Number(button.dataset.time) - cursor) < 1000,
    );
  if (activeView === "overview") {
    element("actual-chart").innerHTML = actualChart(data, view, {
      width: element("actual-chart").clientWidth,
      height: element("actual-chart").clientHeight,
    });
    element("forecast-chart").innerHTML = forecastChart(data, view, {
      width: element("forecast-chart").clientWidth,
      height: element("forecast-chart").clientHeight,
    });
  } else if (activeView === "analysis") renderAnalysis(view);
  else renderComparison();
  const area = element("overview").parentElement!;
  element("view-note").textContent =
    area.scrollHeight > area.clientHeight + 2
      ? "Scroll ↓ · controls stay visible"
      : "";
}
for (const name of ["overview", "analysis", "comparison"]) {
  element(`tab-${name}`).addEventListener("click", () => {
    activeView = name;
    for (const tab of ["overview", "analysis", "comparison"]) {
      element(tab).hidden = tab !== name;
      element(`tab-${tab}`).setAttribute("aria-selected", String(tab === name));
    }
    element("overview").parentElement!.scrollTop = 0;
    render();
  });
}
element("forecast-select").addEventListener("change", (event) => {
  const value = (event.target as HTMLSelectElement).value;
  forecastTick = value === "latest" ? null : Number(value);
  render();
});
element("scenario-select").addEventListener("change", (event) => {
  scenario = Number((event.target as HTMLSelectElement).value);
  render();
});
element("comparison-seed").addEventListener("change", (event) => {
  comparisonSeed = Number((event.target as HTMLSelectElement).value);
  render();
});
function command(value: Command): void {
  playback = playbackCommand(playback, value, data.run.start, data.run.end);
  render();
}
element("bookmarks").innerHTML = data.bookmarks
  .map(
    (bookmark) =>
      `<button data-time="${bookmark.at}" title="Seek to ${time(bookmark.at)}">${e(bookmark.label)}</button>`,
  )
  .join("");
element("bookmarks").addEventListener("click", (event) => {
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
    "button",
  );
  if (button) command({ type: "seek", time: Number(button.dataset.time) });
});
element("play").addEventListener("click", () => command({ type: "toggle" }));
element("restart").addEventListener("click", () =>
  command({ type: "restart" }),
);
seek.addEventListener("input", () =>
  command({ type: "seek", time: Number(seek.value) }),
);
element("speed").addEventListener("change", (event) =>
  command({
    type: "speed",
    speed: Number((event.target as HTMLSelectElement).value),
  }),
);
document.addEventListener("keydown", (event) => {
  if (
    ["INPUT", "SELECT", "BUTTON"].includes(
      (event.target as HTMLElement)?.tagName,
    ) ||
    element("evidence-dialog").hasAttribute("open")
  )
    return;
  if (event.code === "Space") {
    event.preventDefault();
    command({ type: "toggle" });
  } else if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
    event.preventDefault();
    command({
      type: "seek",
      time: playback.cursor + (event.code === "ArrowLeft" ? -30000 : 30000),
    });
  } else if (event.code === "Home") {
    event.preventDefault();
    command({ type: "restart" });
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) command({ type: "pause" });
});
element("fullscreen").addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    element("fullscreen").textContent = "Use browser full screen";
  }
});
const dialog = element("evidence-dialog") as HTMLDialogElement;
element("evidence-button").addEventListener("click", () => dialog.showModal());
element("close-evidence").addEventListener("click", () => dialog.close());
const network =
  data.run.network === "5g_nl_kpn_mahimahi"
    ? "a KPN 5G trace captured by VU Amsterdam"
    : data.run.network;
const sourceHost =
  data.provenance.sourceHost === "node3"
    ? "node3 in the VU MCS cluster"
    : data.provenance.sourceHost;
const acquiredAt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Amsterdam",
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
}).format(new Date(data.provenance.acquiredAt));
const evidenceTimingNotes = [
  "Forecasts and simulated capacity options appear only after the controller recorded its proposed decision. Their exact publication times were not recorded.",
  "Application measurements appear only when the capture shows they were already available. The exact time each monitoring query finished was not recorded.",
  "Deadline predictions use the simulator results and timing assumptions from the captured run. This replay does not recalculate them.",
  "Each sampled future is one possible pattern of arriving jobs. Their range shows variation between scenarios, not a statistical confidence interval.",
];
element("evidence-content").innerHTML =
  `<p>This is an offline replay tool for a workload executed on a real Kubernetes cluster managed using a closed-loop digital twin. In our use case, users send images to the cluster for processing by an AI inference service. Their cellular network connection is emulated using ${e(network)}. Through this tool, we explore how a closed-loop digital twin can support the operation of AI services in 6G systems.</p>
<p>This tool presents the recorded closed-loop digital twin scenario. The <strong>Overview</strong> and <strong>Analysis</strong> tabs focus on the twin’s observations, predictions and decisions, while <strong>Policy comparison</strong> compares static, reactive and digital twin-based control.</p><ul>
<li>Scaling changes how many worker VMs accept jobs, including a delay before an additional VM starts accepting work. Reserve VMs remain powered on.</li>
<li>The CPU and RAM bars show each VM’s total capacity. Colored sections show resources requested for jobs that are starting, processing or finishing. These requests set aside capacity for a job, even when it uses less.</li>
<li>The blue marker shows CPU or RAM actually used by the AI applications. The red hatched CPU section is capacity unavailable to these jobs, rather than measured system use. Missing or older application measurements are labelled.</li>
<li>The forecast chart keeps past predictions as they were issued. New forecasts update the future part of the chart. If an update is skipped, the previous forecast remains visible until the end of its prediction window; the recorded control decision is shown separately.</li>
<li>Starting from the observed queue and worker capacity, the twin simulates options to do nothing, scale up or scale down under several possible future demand scenarios. The percentage of jobs predicted to finish within the deadline is the lowest result across those scenarios. For example, predictions of 98%, 96% and 91% would be displayed as 91%.</li>
<li>The controller compares these predictions and chooses a capacity action, aiming to meet the deadline target with less allocated capacity. It checks the current cluster state before applying the chosen action. If those checks pass, it applies the action to the real cluster. New observations of the queue and workers then inform the next prediction and decision. This feedback closes the loop. The replay shows the recorded predictions, selected actions and measured outcomes.</li>
<li>Arrival bars count the jobs recorded in each interval; striped bars mark an interval that is still filling. Forecast accuracy is shown only for completed intervals where monitoring covers the whole interval. Missing queue observations remain gaps.</li>
</ul><h3>Evidence timing</h3><ul>${evidenceTimingNotes.map((note) => `<li>${e(note)}</li>`).join("")}</ul><dl><dt>Capture identity</dt><dd><code>${e(data.run.id)}</code></dd><dt>Captured scenario</dt><dd>${data.run.workers.length} workers · ${data.run.periodSeconds}s workload cycle · decision interval set to ${data.run.cadenceSeconds}s</dd><dt>Provenance</dt><dd>Read-only subset from ${e(sourceHost)} · SHA-256 manifest ${e(data.provenance.manifestSha256)}</dd><dt>Acquired</dt><dd><time datetime="${e(data.provenance.acquiredAt)}">${e(acquiredAt)} (Amsterdam time)</time></dd></dl>`;
addEventListener("resize", () => render());
render();
let previous = performance.now(),
  lastRender = previous;
function frame(now: number): void {
  const elapsed = Math.max(0, now - previous);
  previous = now;
  if (playback.playing) {
    playback = advancePlayback(playback, elapsed, data.run.start, data.run.end);
    if (now - lastRender >= 80 || !playback.playing) {
      render();
      lastRender = now;
    }
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
