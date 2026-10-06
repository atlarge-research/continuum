/** Compare the captured deadline scores of each capacity action across all futures. */
import { escapeHtml } from "./charts.ts";
import type { ChartSize } from "./charts.ts";
import type { Candidate, Cycle, Dataset } from "./types.ts";

const actions = [
  ["unchanged", "Do nothing"],
  ["scale-up", "Scale up"],
  ["scale-down", "Scale down"],
] as const;
const percent = (value: number) => `${Number((value * 100).toFixed(1))}%`;

/** Use distinct shapes and separate tracks so coincident scores remain visible. */
function futureDot(
  value: number,
  scenario: number,
  selected: boolean,
  width: number,
): string {
  const x = 10 + value * (width - 20),
    y = 8 + scenario * 9;
  const attrs = `class="decision-dot scenario-${scenario}${selected ? " selected" : ""}" data-scenario="${scenario}" data-value="${value}" data-selected="${selected}"`;
  const title = `<title>Future ${scenario + 1}: ${percent(value)} within the deadline${selected ? " · selected future" : ""}</title>`;
  if (scenario % 3 === 1)
    return `<polygon ${attrs} points="${x},${y - 4.5} ${x + 4.5},${y} ${x},${y + 4.5} ${x - 4.5},${y}">${title}</polygon>`;
  if (scenario % 3 === 2)
    return `<rect ${attrs} x="${x - 4}" y="${y - 4}" width="8" height="8">${title}</rect>`;
  return `<circle ${attrs} cx="${x}" cy="${y}" r="4">${title}</circle>`;
}

/** Draw recorded scores only; unavailable alternatives do not receive zero scores. */
function actionRow(
  candidate: Candidate | undefined,
  name: string,
  label: string,
  cycle: Cycle,
  scenario: number,
  target: number,
  width: number,
): string {
  const chosen = cycle.action === name;
  const scores = candidate?.valid ? candidate.scenarioOnTime : [];
  const available = scores.length > 0;
  const lowest = available ? Math.min(...scores) : null;
  const allocation = candidate?.valid ? candidate.allocationCoreSeconds : null;
  const labelHtml = `<span class="decision-action" role="cell"><span class="decision-choice" aria-label="${chosen ? "Recorded selection" : ""}">${chosen ? "✓" : ""}</span>${label}</span>`;
  const recordedReason = candidate?.unavailableReason;
  const reason =
    recordedReason === "maximum_worker_count"
      ? "At maximum capacity"
      : recordedReason
        ? recordedReason
            .replaceAll("_", " ")
            .replace(/^./, (value) => value.toUpperCase())
        : "No recorded simulation";
  let plot = `<span class="decision-unavailable" role="cell" title="${escapeHtml(reason)}">${escapeHtml(reason)}</span>`;
  if (available) {
    const tracks = scores
      .map(
        (_, index) =>
          `<line class="decision-track" x1="10" x2="${width - 10}" y1="${8 + index * 9}" y2="${8 + index * 9}"/>`,
      )
      .join("");
    const targetX = 10 + target * (width - 20);
    const targetLine = `<line class="decision-target" x1="${targetX}" x2="${targetX}" y1="1" y2="33"><title>${percent(target)} deadline target</title></line>`;
    const dots = scores
      .map((value, index) => futureDot(value, index, scenario === index, width))
      .join("");
    plot = `<svg class="decision-scores" viewBox="0 0 ${width} 34" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(scores.map((value, index) => `Future ${index + 1}: ${percent(value)}`).join("; "))}">${tracks}${targetLine}${dots}</svg>`;
  }
  return `<div class="decision-row${chosen ? " chosen" : ""}" role="row" data-candidate="${name}" data-selected-action="${chosen}">${labelHtml}${plot}<strong class="decision-lowest${lowest !== null && lowest < target ? " below-target" : ""}" role="cell" data-value="${lowest ?? "unknown"}" title="Lowest deadline score across the captured futures">${lowest === null ? "—" : percent(lowest)}</strong><span class="decision-allocation" role="cell" data-value="${allocation ?? "unknown"}" title="Recorded application CPU allocation across the candidate’s allocation window">${allocation === null || allocation === undefined ? "—" : (allocation / 60).toFixed(1)}</span></div>`;
}

/** Render the publication selected by the replay, using one aggregate allocation per action. */
export function decisionChart(
  data: Dataset,
  cycle: Cycle | null,
  scenario: number,
  size: ChartSize,
): string {
  if (!cycle)
    return '<div class="simulation-status"><strong>Awaiting a published simulation</strong></div>';
  if (!cycle.valid || !cycle.candidates.length)
    return '<div class="simulation-status"><strong>Simulation update skipped</strong><span>The recorded control action is shown below.</span></div>';
  const width = Math.max(160, size.width - 348);
  const header =
    '<div class="decision-chart-heading" role="row"><span role="columnheader">Action</span><span class="decision-score-axis" role="columnheader" aria-label="Jobs within the deadline, 0 to 100 percent"><span>0%</span><span>50%</span><span>100%</span></span><span role="columnheader">Lowest</span><span class="decision-allocation" role="columnheader">CPU (core-min)</span></div>';
  const rows = actions
    .map(([name, label]) =>
      actionRow(
        cycle.candidates.find((candidate) => candidate.name === name),
        name,
        label,
        cycle,
        scenario,
        data.run.deadlineFraction,
        width,
      ),
    )
    .join("");
  return `<div class="decision-chart" data-target="${data.run.deadlineFraction}" role="table" aria-label="Predicted deadline outcomes for three capacity actions">${header}${rows}</div>`;
}
