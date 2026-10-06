import { latestReadyForecast } from "./forecast-history.ts";
import { decisionText } from "./decision.ts";
import { decisionChart } from "./decision-chart.ts";
import { policyDiagrams } from "./policy-diagrams.ts";
import type { Dataset, Cycle } from "./types.ts";
import { viewAt } from "./replay.ts";
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
  forecastEvaluation,
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
const detailsDialogIds: Record<string, string> = {
  overview: "evidence-dialog",
  analysis: "analysis-dialog",
  comparison: "comparison-dialog",
};
let comparisonSeed =
  data.comparison?.runs.find((r) => r.captureId === data.run.id)?.seed ??
  data.comparison?.runs[0]?.seed ??
  0;
const element = (id: string) => document.getElementById(id)!;
element("policy-diagrams").innerHTML = policyDiagrams();
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
function serviceText(cursor: number): string {
  const s = deadlineStatus(data, cursor);
  const fraction = s.percent === null ? "—" : `${s.percent.toFixed(1)}%`;
  return `<strong title="On-time fraction of confirmed evaluation outcomes; pending excluded">${fraction} on time</strong><span>${s.onTime}/${s.confirmed} confirmed</span><span class="missed">${s.missed} missed</span><span class="pending">${s.pending} pending</span><span class="service-target" title="Target applies to the full evaluation cohort, including failures and unfinished work">≤${data.run.deadlineSeconds}s · target ${Math.round(data.run.deadlineFraction * 100)}%</span>`;
}
function renderAnalysis(view: ReplayView): void {
  const available = data.cycles.filter(
    (c) => c.available >= data.run.start && c.available <= view.cursor,
  );
  if (forecastTick !== null && !available.some((c) => c.tick === forecastTick))
    forecastTick = null;
  const cycle = selectedForecast(data, view.cursor, forecastTick);
  const select = element("forecast-select") as HTMLSelectElement;
  select.innerHTML =
    '<option value="latest">Latest</option>' +
    available
      .map(
        (c) =>
          `<option value="${c.tick}">${time(c.available)}${c.valid ? "" : " · update skipped"}</option>`,
      )
      .join("");
  select.value = forecastTick === null ? "latest" : String(forecastTick);
  const horizonEnd = cycle ? cycle.cutoff + cycle.horizonMs : null;
  const expired = horizonEnd !== null && view.cursor >= horizonEnd;
  const count = cycle?.futures.length ?? 0;
  scenario = Math.min(scenario, Math.max(0, count - 1));
  const publication = element("analysis-forecast-state");
  publication.dataset.cycle = String(cycle?.tick ?? "");
  publication.dataset.pinned = String(forecastTick !== null);
  publication.dataset.available = String(cycle?.available ?? "");
  publication.innerHTML = cycle
    ? `<span><strong>${forecastTick === null ? "Latest forecast" : "Selected forecast"}</strong> · ${time(cycle.available)} · ${Math.ceil((view.cursor - cycle.available) / 1000)}s old</span><span>${expired ? "Window ended" : `Through ${time(horizonEnd!)}`} · ${count} scenarios</span>`
    : "Waiting for forecast publication";
  element("analysis-forecast-input").innerHTML = cycle
    ? `<span>Input: <strong>${cycle.inputQueue ?? "—"}</strong> queued · <strong>${cycle.inputAssigned ?? "—"}</strong> requested cores · <strong>${cycle.inputSlots ?? "—"}</strong> cores of app capacity</span>`
    : "Waiting for observed input";
  const evaluation = forecastEvaluation(data, cycle, view.cursor);
  const covered = evaluation.bins.filter((bin) => bin.complete);
  const quality = element("forecast-quality");
  quality.dataset.cycle = String(cycle?.tick ?? "");
  quality.dataset.binMs = String(evaluation.binMs);
  quality.dataset.covered = String(covered.length);
  quality.dataset.error = String(evaluation.meanAbsoluteError ?? "unknown");
  quality.innerHTML =
    evaluation.meanAbsoluteError === null
      ? "Forecast error: awaiting complete observations"
      : `Average forecast error: <strong>${evaluation.meanAbsoluteError.toFixed(2)} jobs per ${evaluation.binMs / 1000}s</strong>`;
  element("analysis-scenario-key").textContent =
    `Selected future ${scenario + 1}`;
  element("analysis-target").textContent =
    `Target: ≥${Math.round(data.run.deadlineFraction * 100)}% within ${data.run.deadlineSeconds}s`;
  element("analysis-alternatives").dataset.cycle = String(cycle?.tick ?? "");
  element("analysis-alternatives").innerHTML = decisionChart(
    data,
    cycle,
    scenario,
    {
      width: element("analysis-alternatives").clientWidth,
      height: element("analysis-alternatives").clientHeight,
    },
  );
  const status = decisionText(data, { ...view, cycle });
  const stage =
    status.stage === "Physical response"
      ? status.currentConfirmed
        ? "Confirmed on cluster"
        : "Previously confirmed"
      : ((
          {
            Observe: "Awaiting decision",
            Hold: "Capacity retained",
            Fallback: "Reactive fallback",
            "Guard veto": "Safety check blocked",
            "Awaiting observation": "Awaiting observation",
            "Admission pending": "Awaiting capacity",
            "Decision recorded": "Selected",
          } as Record<string, string>
        )[status.stage] ?? status.stage);
  const action = cycle
    ? `${actionName(cycle.action)}${cycle.worker === null ? "" : ` · ${data.run.workers[cycle.worker].label}`}`
    : "Awaiting decision";
  const decision = element("analysis-decision");
  decision.className = `decision${status.warning ? " warning" : ""}`;
  decision.dataset.cycle = String(cycle?.tick ?? "");
  decision.dataset.stage = status.stage;
  decision.dataset.action = cycle?.action ?? "";
  const scored =
    cycle?.valid && count > 0
      ? cycle.candidates.filter(
          (candidate) =>
            candidate.valid &&
            candidate.onTime !== null &&
            candidate.scenarioOnTime.length === count &&
            candidate.scenarioOnTime.every(Number.isFinite),
        )
      : [];
  const viable = scored.filter(
    (candidate) =>
      candidate.onTime! >= data.run.deadlineFraction &&
      candidate.scenarioOnTime.every(
        (value) => value >= data.run.deadlineFraction,
      ),
  );
  const completeComparison =
    cycle?.candidates.every(
      (candidate) => !candidate.valid || scored.includes(candidate),
    ) ?? false;
  const chosen = viable.find((candidate) => candidate.name === cycle?.action);
  const leastAllocation =
    completeComparison &&
    chosen?.allocationCoreSeconds !== null &&
    chosen?.allocationCoreSeconds !== undefined &&
    viable.every(
      (candidate) =>
        candidate.allocationCoreSeconds !== null &&
        chosen.allocationCoreSeconds! <= candidate.allocationCoreSeconds,
    );
  const reason =
    status.stage === "Guard veto"
      ? "Recorded choice blocked by the safety check."
      : chosen
        ? viable.length === 1 && completeComparison
          ? `Only option meeting the target in all ${count} futures.`
          : `Target met in all ${count} futures${leastAllocation ? " · Lowest allocation." : "."}`
        : cycle?.valid
          ? "Recorded controller choice."
          : "Recorded control action · Simulation unavailable.";
  decision.innerHTML = `<div class="analysis-action-summary"><strong>${e(action)}</strong><span class="analysis-action-stage">${e(stage)}</span></div><p class="analysis-action-reason">${e(reason)}</p>`;
  const scenarios = element("scenario-select") as HTMLSelectElement;
  scenarios.innerHTML = count
    ? Array.from(
        { length: count },
        (_, i) => `<option value="${i}">${i + 1}</option>`,
      ).join("")
    : '<option value="0">—</option>';
  scenarios.value = String(scenario);
  const capacities = [...new Set(view.workers.map((w) => w.config.slots))];
  element("analysis-requests-scale").textContent =
    capacities.length === 1
      ? `Cores · ${capacities[0]} per worker for applications`
      : "Cores · each bar uses its worker’s application capacity";
  element("predicted-processing").dataset.scenario = String(scenario);
  element("predicted-processing").innerHTML =
    `<table class="allocation-table"><thead><tr><th>Worker</th><th>Predicted</th><th>Observed</th></tr></thead><tbody>${view.workers
      .map((w, i) => {
        const predicted = expired
          ? null
          : predictedOccupancy(cycle, i, view.cursor, scenario);
        const observed = resourceReservations(w).cpuRequested;
        const cell = (value: number | null, kind: string) =>
          `<td class="allocation-cell ${kind}" data-cores="${value ?? "unknown"}" data-capacity="${w.config.slots}"><div class="allocation-body"><span>${value === null ? "—" : Number(value.toFixed(2))}</span><div class="allocation-track"><i style="width:${value === null ? 0 : Math.min(100, (value / w.config.slots) * 100)}%"></i></div></div></td>`;
        return `<tr data-worker="${i}"><td>${e(w.config.label)}</td>${cell(predicted, "predicted")}${cell(observed, "observed")}</tr>`;
      })
      .join("")}</tbody></table>`;
  element("analysis-forecast-notes").innerHTML =
    "<p>The chart compares observed arrivals with issued predictions. Earlier predictions stay visible as observations arrive; the range shows variation between possible futures. Forecast error uses completed intervals with available monitoring.</p>";
  element("analysis-simulation-notes").innerHTML =
    "<p>Before changing capacity, the twin simulates doing nothing, scaling up and scaling down. It checks the lowest deadline prediction across the futures and aims to meet the target with less allocated capacity. The chosen action is applied after safety checks; new cluster observations close the loop.</p>";
  element("analysis-resource-notes").innerHTML =
    "<p>Choose a future to link its forecast, deadline predictions and worker requests. Worker bars compare predicted and observed requested cores at the replay time. CPU allocation measures capacity committed over time in core-minutes; requests are separate from measured CPU use.</p>";
  element("analysis-forecast-chart").innerHTML = forecastChart(
    data,
    view,
    {
      width: element("analysis-forecast-chart").clientWidth,
      height: element("analysis-forecast-chart").clientHeight,
    },
    { cycle, detail: true, scenario, pinned: forecastTick !== null },
  );
}
function renderComparison(): void {
  const comparison = data.comparison;
  if (!comparison?.runs.length) {
    element("comparison-results").innerHTML =
      '<div class="empty-chart">Matched comparison evidence is unavailable for this dataset.</div>';
    element("comparison-interpretation").textContent =
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
        ? "Reactive heuristic"
        : "Digital twin";
  const maxAllocation = Math.max(
    3000,
    Math.ceil(Math.max(...rows.map((r) => r.allocationBounds[1])) / 3000) *
      3000,
  );
  const maxResponseSeconds =
    Math.ceil(
      Math.max(
        fixed.deadlineSeconds,
        ...rows.map((r) => r.p95CompletedSeconds ?? 0),
      ) / 30,
    ) * 30;
  const axis = (max: number, suffix = "") =>
    `<div class="result-axis" aria-hidden="true"><span>0${suffix}</span><span>${precise(max / 2, 0)}${suffix}</span><span>${precise(max, 0)}${suffix}</span></div>`;
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
  const response = rows
    .map((r) => {
      const bar =
        r.p95CompletedSeconds === null
          ? ""
          : `<i class="bar" style="width:${(r.p95CompletedSeconds / maxResponseSeconds) * 100}%"></i>`;
      return `<div class="result-row ${r.policy}" data-policy="${r.policy}" data-p95="${r.p95CompletedSeconds ?? "unknown"}" data-completed="${r.completedJobs}"><span>${label(r.policy)}</span><div class="result-track">${bar}</div><span class="result-value" title="95th percentile of API Job creation to terminal completion; ${r.completedJobs} completed evaluation Jobs only">${r.p95CompletedSeconds === null ? "—" : `${precise(r.p95CompletedSeconds, 1)}s`}</span></div>`;
    })
    .join("");
  element("comparison-results").innerHTML =
    `<div class="result-charts"><section class="result-chart" data-metric="service" data-scale-max="100"><h3>Jobs meeting deadline</h3><p class="chart-subtitle">≤${fixed.deadlineSeconds}s · ${fixed.targetFraction * 100}% target</p>${service}${axis(100, "%")}</section><section class="result-chart" data-metric="allocation" data-scale-max="${maxAllocation}"><h3>Application allocation</h3><p class="chart-subtitle">Core-minutes · recorded bounds</p>${allocation}${axis(maxAllocation / 60)}</section><section class="result-chart" data-metric="response" data-scale-max="${maxResponseSeconds}"><h3>Response time</h3><p class="chart-subtitle" title="The time within which approximately 95% of completed evaluation Jobs finished">Completed jobs · p95 (s)</p>${response}${axis(maxResponseSeconds)}</section></div>`;
  element("comparison-interpretation").innerHTML = comparisonConclusion(
    comparison,
    comparisonSeed,
  )
    .split("\n\n")
    .map((paragraph) => `<p>${e(paragraph)}</p>`)
    .join("");
  const reactiveSettings =
    (reactive.reactiveTargetFraction ?? 0) > 0
      ? `The reactive heuristic aims to keep requested CPU demand at or below ${precise(reactive.reactiveTargetFraction! * 100, 0)}% of the application capacity on workers accepting jobs. Its downscale stabilization window is ${reactive.reactiveStabilizationSeconds === null ? "unrecorded" : reactive.reactiveStabilizationSeconds + " seconds"}.`
      : `The recorded reactive thresholds are ${precise(reactive.reactiveUpThreshold === null ? null : reactive.reactiveUpThreshold * 100, 0)}% for scaling up and ${precise(reactive.reactiveDownThreshold === null ? null : reactive.reactiveDownThreshold * 100, 0)}% for scaling down.`;
  const adaptiveStart =
    reactive.initialWorkers === forecast.initialWorkers
      ? `the reactive heuristic and twin both started with ${reactive.initialWorkers}`
      : `the reactive heuristic and twin started with ${reactive.initialWorkers} and ${forecast.initialWorkers}, respectively`;
  element("comparison-settings").innerHTML =
    `<p>Each policy received the same planned workload of ${fixed.jobs} evaluation jobs. Application capacity was compared over the same ${fixed.evaluationSeconds}-second window, with another ${fixed.followupSeconds} seconds allowed for jobs to finish.</p>
    <p>Static started with ${fixed.initialWorkers} workers accepting jobs; ${adaptiveStart}. All used the same pool of ${fixed.workerCount} powered VMs. Activating a reserve introduced an admission delay of at least ${fixed.acquisitionSeconds} seconds.</p>
    <h3>Reading the graphs</h3>
    <p>The deadline graph counts every evaluation job, including failed and unfinished jobs. Response time runs from original Kubernetes Job creation to final completion; its p95 includes completed jobs only.</p>
    <p>Application allocation counts CPU capacity committed to workers accepting jobs, finishing existing jobs after stopping new admissions, or awaiting requested activation. The displayed ranges allow for gaps in monitoring.</p>
    <h3>Controller settings and source</h3>
    <p>The reactive heuristic checked demand every ${reactive.cadenceSeconds} seconds; the twin made decisions every ${forecast.cadenceSeconds} seconds. ${e(reactiveSettings)}</p>
    <p>The heuristic shown here adjusts worker admission using observed resource demand. Other autoscalers, including Kubernetes HPA, may use different rules and measurements.</p>
    <p>Workload seed: ${comparisonSeed}. Recorded network profile: <code>${e(fixed.network)}</code>. Allocation ranges describe observation coverage, not statistical confidence intervals.</p>
    <p>Source report SHA-256: <code>${e(comparison.sourceSha256)}</code></p>`;
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
  element("view-details-button").setAttribute(
    "aria-controls",
    detailsDialogIds[activeView],
  );
  element("transport").hidden = activeView === "comparison";
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
      ? activeView === "comparison"
        ? "Scroll ↓"
        : "Scroll ↓ · controls stay visible"
      : "";
}
for (const name of ["overview", "analysis", "comparison"]) {
  element(`tab-${name}`).addEventListener("click", () => {
    activeView = name;
    if (name === "comparison") playback = { ...playback, playing: false };
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
    activeView === "comparison" ||
    ["INPUT", "SELECT", "BUTTON"].includes(
      (event.target as HTMLElement)?.tagName,
    ) ||
    element("evidence-dialog").hasAttribute("open") ||
    element("comparison-dialog").hasAttribute("open") ||
    element("analysis-dialog").hasAttribute("open")
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
element("view-details-button").addEventListener("click", () => {
  command({ type: "pause" });
  (element(detailsDialogIds[activeView]) as HTMLDialogElement).showModal();
});
const analysisDialog = element("analysis-dialog") as HTMLDialogElement;
element("close-analysis-details").addEventListener("click", () =>
  analysisDialog.close(),
);
const comparisonDialog = element("comparison-dialog") as HTMLDialogElement;
element("close-comparison-settings").addEventListener("click", () =>
  comparisonDialog.close(),
);
const dialog = element("evidence-dialog") as HTMLDialogElement;
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
