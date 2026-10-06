/** Presentation selectors remain pure: display state never changes recorded evidence. */
import { coveredInterval, viewAt } from "./replay.ts";
import type {
  Cycle,
  Dataset,
  PolicyComparison,
  PolicyResult,
} from "./types.ts";
import type { WorkerView } from "./replay.ts";

/** Hold a coherent, already-published worker update through brief collection gaps only.
 * Scientific histories and decisions continue to use the strict replay view.
 */
export function workerDisplayAt(data: Dataset, cursor: number) {
  const current = viewAt(data, cursor);
  const previous = current.fresh
    ? current.snapshot
    : ([...data.snapshots]
        .reverse()
        .find((s) => s.complete && s.at <= cursor) ?? null);
  const ageMs = previous ? cursor - previous.at : null;
  const canRetain =
    !current.fresh &&
    previous &&
    ageMs! <= 3 * data.run.maxGapMs &&
    !data.failures.some((f) => f.at > previous.at && f.at <= cursor);
  const retainedView = canRetain ? viewAt(data, previous.at) : current;
  const retained = !!canRetain && retainedView.fresh;
  return {
    view: retained ? retainedView : current,
    retained,
    observedAt: (retained ? previous : current.snapshot)?.at ?? null,
    ageMs: retained
      ? ageMs
      : current.snapshot
        ? cursor - current.snapshot.at
        : null,
  };
}
/** Confirmed API creation-to-terminal-Job results; unpublished outcomes remain pending. */
export function deadlineStatus(data: Dataset, cursor: number) {
  let onTime = 0,
    missed = 0,
    pending = 0;
  for (const job of data.jobs) {
    const evaluated =
      job.evaluated ??
      (job.creation >= data.run.evaluationStart &&
        job.creation < data.run.arrivalEnd);
    if (!evaluated || job.available > cursor) continue;
    const terminal =
      job.terminalAvailable !== null && job.terminalAvailable <= cursor;
    if (terminal && job.outcome === "Failed") {
      missed++;
      continue;
    }
    if (
      terminal &&
      job.outcome === "Complete" &&
      job.completed !== null &&
      job.completed <= cursor
    ) {
      if (job.completed - job.creation <= data.run.deadlineSeconds * 1000)
        onTime++;
      else missed++;
    } else pending++;
  }
  const confirmed = onTime + missed;
  return {
    onTime,
    missed,
    pending,
    confirmed,
    percent: confirmed ? (onTime / confirmed) * 100 : null,
  };
}
/** Summarize matched whole-cohort results and only savings established by the bounds. */
export function comparisonConclusion(
  comparison: PolicyComparison,
  seed: number,
): string {
  const rows = comparison.runs.filter((r) => r.seed === seed);
  const fixed = rows.find((r) => r.policy === "fixed"),
    reactive = rows.find((r) => r.policy === "reactive"),
    forecast = rows.find((r) => r.policy === "forecast");
  if (!fixed || !reactive || !forecast)
    return "Matched policy comparison is unavailable for this workload.";
  const pass = (r: PolicyResult) => r.timelyJobs / r.jobs >= r.targetFraction;
  const allPass = rows.every(pass);
  const service = allPass
    ? `All three policies met the ${fixed.targetFraction * 100}% service target for jobs finishing within the ${fixed.deadlineSeconds}-second deadline.${rows.every((r) => r.timelyJobs === r.jobs) ? " Every evaluation job finished on time." : ""}`
    : `Against the ${fixed.targetFraction * 100}% target for jobs finishing within ${fixed.deadlineSeconds} seconds, static ${pass(fixed) ? "met" : "missed"} the target, the reactive heuristic ${pass(reactive) ? "met" : "missed"} it, and the digital twin ${pass(forecast) ? "met" : "missed"} it.`;
  const reduction = (lower: PolicyResult, higher: PolicyResult) =>
    1 - lower.allocationBounds[1] / higher.allocationBounds[0];
  const heuristicSaving = reduction(reactive, fixed),
    twinSaving = reduction(forecast, fixed),
    twinVersusHeuristic = reduction(forecast, reactive);
  const allocation: string[] = [];
  if (heuristicSaving > 0 && twinSaving > 0) {
    allocation.push(
      `Compared with static control, the reactive heuristic allocated about ${(heuristicSaving * 100).toFixed(1)}% less application capacity, and the twin about ${(twinSaving * 100).toFixed(1)}% less.`,
    );
  } else {
    for (const [run, label] of [
      [reactive, "The reactive heuristic"],
      [forecast, "The twin"],
    ] as const) {
      const saving = reduction(run, fixed);
      allocation.push(
        saving > 0
          ? `${label} allocated about ${(saving * 100).toFixed(1)}% less application capacity than static control.`
          : run.allocationBounds[0] > fixed.allocationBounds[1]
            ? `${label} allocated more application capacity than static control.`
            : `The recorded bounds do not establish an allocation reduction for ${label.toLowerCase()} compared with static control.`,
      );
    }
  }
  allocation.push(
    twinVersusHeuristic > 0
      ? `The twin also allocated about ${(twinVersusHeuristic * 100).toFixed(1)}% less than the reactive heuristic.`
      : forecast.allocationBounds[0] > reactive.allocationBounds[1]
        ? "The twin allocated more application capacity than the reactive heuristic."
        : "The twin and reactive heuristic have overlapping allocation bounds, so no reduction between them is established.",
  );
  allocation.push(
    "Allocation comparisons use the conservative ends of the recorded bounds, allowing for gaps in monitoring.",
  );
  const parts = [service, allocation.join(" ")];
  const latencies = [
    [fixed, "static"],
    [reactive, "the reactive heuristic"],
    [forecast, "the twin"],
  ] as const;
  const available = latencies
    .filter(([run]) => run.p95CompletedSeconds !== null)
    .map(
      ([run, label]) =>
        `${run.p95CompletedSeconds!.toFixed(1)}s under ${label}`,
    );
  if (available.length) {
    const values =
      available.length === 1
        ? available[0]
        : available.slice(0, -1).join(", ") + " and " + available.at(-1);
    const tradeoff =
      twinVersusHeuristic > 0 &&
      reactive.p95CompletedSeconds !== null &&
      forecast.p95CompletedSeconds !== null &&
      reactive.p95CompletedSeconds < forecast.p95CompletedSeconds
        ? "The twin's lower allocation came with slower responses. "
        : "";
    parts.push(
      `${tradeoff}Completed jobs had a response-time p95 of ${values}. This is the time within which about 95% of completed jobs finished.`,
    );
  }
  return parts.join("\n\n");
}
/** Percentages describe the available application samples, never the entire host. */
export function resourceUsage(worker: WorkerView) {
  return {
    cpuPercent:
      worker.cpu === null ? null : (worker.cpu / worker.config.cores) * 100,
    memoryPercent:
      worker.memory === null
        ? null
        : (worker.memory / worker.config.memoryMiB) * 100,
    coverage:
      worker.cpu === null || worker.memory === null
        ? "missing"
        : worker.sampled < worker.totalJobs
          ? "partial"
          : "complete",
  } as const;
}
/** Group observed requests on full VM scales; budget headroom is not measured system use. */
export function resourceReservations(worker: WorkerView) {
  const phases = ["startup", "release", "processing", "unknown"] as const;
  const known = worker.occupied !== null && worker.state !== null;
  const held = known ? worker.state!.held : [];
  const memoryKnown = known && held.every((h) => h.memoryMiB != null);
  const segments = phases
    .map((phase) => {
      const group = held.filter((h) => h.phase === phase);
      return {
        phase,
        cpu: group.reduce((sum, h) => sum + h.cores, 0),
        memory: memoryKnown
          ? group.reduce((sum, h) => sum + h.memoryMiB!, 0)
          : null,
      };
    })
    .filter((s) => s.cpu > 0);
  return {
    outsideCpuBudget: Math.max(0, worker.config.cores - worker.config.slots),
    cpuRequested: known ? held.reduce((sum, h) => sum + h.cores, 0) : null,
    memoryRequested: memoryKnown
      ? held.reduce((sum, h) => sum + h.memoryMiB!, 0)
      : null,
    segments,
  };
}

/** A pinned forecast is valid only after its publication and within the operating portion. */
export function selectedForecast(
  data: Dataset,
  cursor: number,
  tick: number | null,
): Cycle | null {
  const available = data.cycles.filter(
    (c) => c.available >= data.run.start && c.available <= cursor,
  );
  return available.find((c) => c.tick === tick) ?? available.at(-1) ?? null;
}
/** Aggregate scenario counts first; min/max describes sampled scenarios, not statistical confidence. */
export function forecastBuckets(cycle: Cycle, displayBinMs = 15000) {
  const group = Math.max(1, Math.ceil(displayBinMs / cycle.binMs));
  const result = [];
  for (let i = 0; i < cycle.bins.length; i += group) {
    const bins = cycle.bins.slice(i, i + group),
      start = bins[0].start,
      end = bins.at(-1)!.start + cycle.binMs;
    const scenarios = cycle.futures.map(
      (f) => f.filter((t) => t >= start && t < end).length,
    );
    result.push({
      start,
      end,
      mean: bins.reduce((s, b) => s + b.mean, 0),
      scenarios,
      min: scenarios.length ? Math.min(...scenarios) : 0,
      max: scenarios.length ? Math.max(...scenarios) : 0,
    });
  }
  return result;
}

/** Compare forecasts and published arrivals over the same complete display intervals. */
export function forecastEvaluation(
  data: Dataset,
  cycle: Cycle | null,
  cursor: number,
) {
  const binMs = cycle?.binMs
    ? Math.ceil(15000 / cycle.binMs) * cycle.binMs
    : 15000;
  if (!cycle || cycle.available > cursor)
    return { binMs, bins: [], meanAbsoluteError: null };
  const arrivals = data.jobs.filter((job) => job.available <= cursor);
  const horizonEnd = cycle.cutoff + cycle.horizonMs;
  const bins = forecastBuckets(cycle, binMs).map((bucket) => {
    const complete =
      bucket.end - bucket.start === binMs &&
      bucket.start >= Math.max(data.run.start, cycle.cutoff) &&
      bucket.end <= horizonEnd &&
      coveredInterval(data, bucket.start, bucket.end, cursor);
    return {
      start: bucket.start,
      end: bucket.end,
      expected: bucket.mean,
      actual: complete
        ? arrivals.filter(
            (job) => job.creation >= bucket.start && job.creation < bucket.end,
          ).length
        : null,
      complete,
    };
  });
  const covered = bins.filter((bin) => bin.complete);
  const meanAbsoluteError = covered.length
    ? covered.reduce(
        (sum, bin) => sum + Math.abs(bin.actual! - bin.expected),
        0,
      ) / covered.length
    : null;
  return { binMs, bins, meanAbsoluteError };
}

/** Origin-aligned observed intervals; the default fixed origin preserves Overview history. */
export function observedBins(
  data: Dataset,
  start: number,
  end: number,
  cursor: number,
  binMs = 15000,
  origin = 0,
) {
  const bins = [];
  const arrivals = data.jobs.filter((j) => j.available <= cursor);
  for (
    let t = origin + Math.floor((start - origin) / binMs) * binMs;
    t < Math.min(end, cursor);
    t += binMs
  ) {
    const left = Math.max(start, t),
      right = Math.min(t + binMs, end, cursor);
    if (right <= left) continue;
    const open = right < t + binMs;
    bins.push({
      start: left,
      end: right,
      count: arrivals.filter((j) => j.creation >= left && j.creation < right)
        .length,
      complete:
        !open && left === t && coveredInterval(data, left, right, cursor),
      open,
    });
  }
  return bins;
}

/** Predicted request units are conditional on the published simulation horizon. */
export function predictedOccupancy(
  cycle: Cycle | null,
  worker: number,
  cursor: number,
  scenario: number,
): number | null {
  if (
    !cycle?.valid ||
    cursor < cycle.cutoff ||
    cursor > cycle.cutoff + cycle.horizonMs
  )
    return null;
  return cycle.tasks
    .filter(
      (t) =>
        t.candidate === cycle.action &&
        t.scenario === scenario &&
        t.worker === worker &&
        t.scheduled !== null &&
        t.finished !== null &&
        t.scheduled <= cursor &&
        t.finished > cursor,
    )
    .reduce((sum, t) => sum + t.cores, 0);
}
