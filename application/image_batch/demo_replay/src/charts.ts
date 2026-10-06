import { forecastBuckets, observedBins } from "./presentation.ts";
import { latestReadyForecast, forecastHistory } from "./forecast-history.ts";
import type { Cycle } from "./types.ts";
import type { Dataset } from "./types.ts";
import type { ReplayView } from "./replay.ts";
import { latestAt } from "./replay.ts";
export const escapeHtml = (value: unknown) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const n = (value: number) => Number(value.toFixed(2));
export interface ChartSize {
  width: number;
  height: number;
}
const svg = (label: string, body: string, size: ChartSize, font: number) =>
  `<svg viewBox="0 0 ${size.width} ${size.height}" style="font-size:${font}px" role="img" aria-label="${escapeHtml(label)}">${body}</svg>`;
const text = (x: number, y: number, value: string, anchor = "start") =>
  `<text x="${n(x)}" y="${n(y)}" text-anchor="${anchor}">${escapeHtml(value)}</text>`;
export function formatTime(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
/** Two measured histories share the replay cursor; future observations are never drawn. */
export function actualChart(
  data: Dataset,
  view: ReplayView,
  size: ChartSize = { width: 620, height: 200 },
): string {
  const font = 20,
    left = 190,
    right = size.width - 8;
  const arrivalTop = 10,
    arrivalBottom = size.height / 2 - font - 12,
    queueTop = size.height / 2 + 10,
    queueBottom = size.height - font - 8;
  const end = view.cursor,
    start = Math.max(data.run.start, end - 180000);
  if (end - start < 1000)
    return '<div class="empty-chart">Measured history develops as the replay advances.<br>Current worker state is shown above.</div>';
  const x = (time: number) =>
    left + ((time - start) / (end - start)) * (right - left);
  const binMs = 15000;
  const arrivalBins = observedBins(data, start, end, view.cursor, binMs);
  const maximum = (value: number) => {
    const estimate = Math.max(2, value / 3);
    const power = 10 ** Math.floor(Math.log10(estimate));
    const step = [1, 2, 5, 10].find((v) => v * power >= estimate)! * power;
    return step * 3;
  };
  const maxArrivals = maximum(Math.max(...arrivalBins.map((b) => b.count)));
  const points = data.snapshots.filter((s) => s.at >= start && s.at <= end);
  const preceding = latestAt(data.snapshots, start);
  if (preceding && preceding.at < start) points.unshift(preceding);
  const maxQueue = maximum(Math.max(0, ...points.map((p) => p.queue.length)));
  let body =
    '<defs><pattern id="physical-arrival-open" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="var(--physical)" stroke-width="2"/></pattern></defs>' +
    text(
      0,
      (arrivalTop + arrivalBottom) / 2 + font * 0.35,
      `Jobs / ${binMs / 1000}s`,
    ) +
    text(0, (queueTop + queueBottom) / 2 + font * 0.35, "Queue");
  for (const [top, bottom, max] of [
    [arrivalTop, arrivalBottom, maxArrivals],
    [queueTop, queueBottom, maxQueue],
  ]) {
    for (let i = 0; i <= 3; i++) {
      const value = (max * i) / 3;
      const y = bottom - (i / 3) * (bottom - top);
      body +=
        `<line class="gridline" x1="${left}" y1="${n(y)}" x2="${right}" y2="${n(y)}"/>` +
        text(left - 10, y + 5, String(n(value)), "end");
    }
  }
  for (const b of arrivalBins) {
    const left = x(b.start),
      width = Math.max(1, x(b.end) - left - 2);
    const height = (b.count / maxArrivals) * (arrivalBottom - arrivalTop);
    body += `<rect class="arrival-bar ${b.open ? "open" : "recorded"}" data-count="${b.count}" data-bin-start="${b.start}" data-bin-end="${b.end}" x="${n(left)}" y="${n(arrivalBottom - height)}" width="${n(width)}" height="${n(height)}" fill="${b.open ? "url(#physical-arrival-open)" : "var(--physical)"}"><title>${b.count} arrivals recorded by the cursor${b.open ? " · current interval still filling" : ""}</title></rect>`;
  }
  let path = "",
    previous: (typeof points)[number] | null = null;
  for (const point of points) {
    if (!point.complete) {
      previous = null;
      continue;
    }
    const time = Math.max(start, point.at),
      px = x(time),
      py =
        queueBottom -
        (point.queue.length / maxQueue) * (queueBottom - queueTop);
    if (previous && point.at - previous.at <= data.run.maxGapMs)
      path += `H${n(px)}V${n(py)}`;
    else path += `M${n(px)},${n(py)}`;
    previous = point;
  }
  if (previous && end - previous.at <= data.run.maxGapMs)
    path += `H${n(x(end))}`;
  body += `<path class="measured-line" d="${path}"/>`;
  for (const gap of data.gaps) {
    if (
      (gap.available ?? gap.start) > end ||
      gap.end <= start ||
      gap.start >= end
    )
      continue;
    body += `<rect class="gap" data-reason="${escapeHtml(gap.reason)}" x="${n(x(Math.max(start, gap.start)))}" y="${n(queueTop)}" width="${n(x(Math.min(end, gap.end)) - x(Math.max(start, gap.start)))}" height="${n(queueBottom - queueTop)}"><title>Observation gap: ${escapeHtml(gap.reason)}</title></rect>`;
  }
  for (const [plot, bottom] of [
    ["arrivals", arrivalBottom],
    ["queue", queueBottom],
  ] as const) {
    body += `<g class="time-axis" data-plot="${plot}">`;
    for (let i = 0; i <= 4; i++) {
      const t = start + ((end - start) * i) / 4;
      body +=
        `<line class="axis-tick" x1="${n(x(t))}" x2="${n(x(t))}" y1="${n(bottom)}" y2="${n(bottom + 4)}" stroke="var(--muted)"/>` +
        text(
          x(t),
          bottom + font + 3,
          formatTime(t - data.run.start),
          i === 0 ? "start" : i === 4 ? "end" : "middle",
        );
    }
    body += "</g>";
  }
  return svg(
    "Recorded arrivals and unassigned queue. Hatched arrivals are in the filling interval; amber queue intervals have incomplete queue observations.",
    body,
    size,
    font,
  );
}
/** Preserve issued forecast history; sampled ranges are not confidence intervals. */
export function forecastChart(
  data: Dataset,
  view: ReplayView,
  size: ChartSize = { width: 620, height: 240 },
  options: { cycle?: Cycle | null; detail?: boolean; scenario?: number } = {},
): string {
  const font = 18,
    left = 46,
    right = size.width - 16,
    top = 38,
    bottom = Math.max(top + 35, size.height - 32);
  const detail = options.detail === true;
  const cycle =
    options.cycle === undefined
      ? latestReadyForecast(data, view.cursor)
      : options.cycle;
  const ready =
    !!cycle &&
    cycle.available <= view.cursor &&
    cycle.forecastStatus === "ready" &&
    cycle.bins.length > 0;
  const start =
    detail && ready
      ? Math.max(data.run.start, cycle!.cutoff - 180000)
      : Math.max(data.run.start, view.cursor - 180000);
  const horizonEnd = cycle ? cycle.cutoff + cycle.horizonMs : view.cursor;
  const end = Math.max(view.cursor + 15000, horizonEnd);
  const x = (t: number) =>
    left + ((t - start) / Math.max(1, end - start)) * (right - left);
  const displayBinMs = cycle?.binMs
    ? Math.ceil(15000 / cycle.binMs) * cycle.binMs
    : 15000;
  const observed = observedBins(
    data,
    start,
    view.cursor,
    view.cursor,
    displayBinMs,
    detail && ready ? cycle!.bins[0].start : 0,
  );
  const history = detail
    ? []
    : forecastHistory(data, view.cursor, displayBinMs);
  const current = ready
    ? [
        {
          cycle: cycle!,
          start: detail ? cycle!.cutoff : view.cursor,
          end: horizonEnd,
          buckets: forecastBuckets(cycle!, displayBinMs),
        },
      ]
    : [];
  const segments = [
    ...history.map((s) => ({ ...s, kind: "historical" })),
    ...current.map((s) => ({ ...s, kind: "current" })),
  ].filter((s) => s.end > Math.max(s.start, start) && s.start < end);
  const visibleBuckets = segments.flatMap((s) =>
    s.buckets.filter(
      (b) => b.end > Math.max(start, s.start) && b.start < Math.min(end, s.end),
    ),
  );
  const peak = Math.max(
    0,
    ...observed.map((b) => b.count),
    ...visibleBuckets.flatMap((b) => [b.mean, b.max]),
  );
  const estimate = Math.max(2, peak / 3),
    power = 10 ** Math.floor(Math.log10(estimate)),
    step = [1, 2, 5, 10].find((value) => value * power >= estimate)! * power;
  const ymax = detail ? step * 3 : Math.max(5, Math.ceil(peak / 5) * 5);
  const y = (v: number) => bottom - (v / ymax) * (bottom - top);
  const prefix = detail ? "analysis" : "overview";
  let body = `<defs><pattern id="${prefix}-arrival-open" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="var(--physical)" stroke-width="2"/></pattern>`;
  for (const s of segments) {
    const clipLeft = x(Math.max(start, s.start)),
      clipRight = x(Math.min(end, s.end));
    body += `<clipPath id="${prefix}-forecast-${s.cycle.tick}-${s.kind}"><rect x="${n(clipLeft)}" y="${top}" width="${n(Math.max(0, clipRight - clipLeft))}" height="${bottom - top}"/></clipPath>`;
  }
  body += `</defs><rect x="${n(x(view.cursor))}" y="${top}" width="${n(Math.max(0, right - x(view.cursor)))}" height="${bottom - top}" fill="var(--twin)" opacity=".05"/>`;
  for (const v of detail
    ? [0, ymax / 3, (2 * ymax) / 3, ymax]
    : [0, ymax / 2, ymax])
    body +=
      `<line class="gridline" x1="${left}" x2="${right}" y1="${n(y(v))}" y2="${n(y(v))}"/>` +
      text(left - 8, y(v) + 6, String(v), "end");
  body += text(0, 20, `Jobs / ${displayBinMs / 1000}s`);
  const lineBodies: string[] = [];
  for (const s of segments) {
    const path = (values: number[]) =>
      s.buckets
        .map(
          (b, i) =>
            `${i ? "L" : "M"}${n(x((b.start + b.end) / 2))},${n(y(values[i]))}`,
        )
        .join("");
    const clip = `clip-path="url(#${prefix}-forecast-${s.cycle.tick}-${s.kind})"`;
    const attrs = `data-cycle="${s.cycle.tick}" data-available="${s.cycle.available}" data-start="${s.start}" data-end="${s.end}"`;
    const upper = path(s.buckets.map((b) => b.max));
    const lower = [...s.buckets]
      .reverse()
      .map((b) => `L${n(x((b.start + b.end) / 2))},${n(y(b.min))}`)
      .join("");
    body += `<path class="scenario-range ${s.kind}" ${attrs} ${clip} d="${upper}${lower}Z" fill="var(--twin)" opacity=".18"><title>Forecast range: minimum to maximum of ${s.cycle.futures.length} sampled futures; issued ${formatTime(s.cycle.available - data.run.start)}. Not a confidence interval.</title></path>`;
    if (detail)
      for (let i = 0; i < s.cycle.futures.length; i++)
        lineBodies.push(
          `<path class="future-line scenario-${i}${i === options.scenario ? " selected" : ""}" data-scenario="${i}" data-selected="${i === options.scenario}" ${clip} d="${path(s.buckets.map((b) => b.scenarios[i]))}"><title>Simulation scenario ${i + 1}</title></path>`,
        );
    lineBodies.push(
      `<path class="forecast-line ${s.kind}" ${attrs} ${clip} d="${path(s.buckets.map((b) => b.mean))}"><title>Expected arrivals from forecast issued ${formatTime(s.cycle.available - data.run.start)}</title></path>`,
    );
  }
  for (const b of observed) {
    const width = Math.max(1, x(b.end) - x(b.start) - 2),
      height = bottom - y(b.count);
    body += `<rect class="actual-bar ${b.open ? "open" : "recorded"}" data-count="${b.count}" data-bin-start="${b.start}" data-bin-end="${b.end}" x="${n(x(b.start) + 1)}" y="${n(y(b.count))}" width="${n(width)}" height="${n(height)}" fill="${b.open ? `url(#${prefix}-arrival-open)` : "var(--physical)"}"><title>${b.count} arrivals recorded by the cursor${b.open ? " · current interval still filling" : ""}</title></rect>`;
  }
  body += lineBodies.join("");
  body +=
    `<line class="cursor-line" x1="${n(x(view.cursor))}" x2="${n(x(view.cursor))}" y1="${top}" y2="${bottom}"/>` +
    text(
      Math.max(left + 22, Math.min(right - 22, x(view.cursor))),
      20,
      "now",
      "middle",
    );
  const xDivisions = detail ? 4 : 3;
  for (let i = 0; i <= xDivisions; i++) {
    const t = start + ((end - start) * i) / xDivisions;
    body += text(
      x(t),
      size.height - 3,
      formatTime(t - data.run.start),
      i === 0 ? "start" : i === xDivisions ? "end" : "middle",
    );
  }
  if (!ready)
    body += text(
      (left + right) / 2,
      top + 27,
      "No forecast issued for this update",
      "middle",
    );
  else if (view.cursor >= horizonEnd)
    body += text(
      (left + right) / 2,
      top + 27,
      "Forecast horizon elapsed",
      "middle",
    );
  return svg(
    "Observed arrivals and future demand. Hatched bars are in the filling interval. The purple line preserves predictions as issued; shading is the forecast range of sampled futures.",
    body,
    size,
    font,
  );
}
