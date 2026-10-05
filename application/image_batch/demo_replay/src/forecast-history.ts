import type { Cycle, Dataset } from "./types.ts";
import { forecastBuckets } from "./presentation.ts";

export interface ForecastHistorySegment {
  cycle: Cycle;
  /** Publication time, rather than the earlier computation cutoff. */
  start: number;
  /** Exclusive display boundary: next ready publication, cursor or forecast horizon. */
  end: number;
  /** Original counts remain intact; the renderer clips their paths to start/end. */
  buckets: ReturnType<typeof forecastBuckets>;
}

function publishedReadyForecasts(data: Dataset, cursor: number): Cycle[] {
  return data.cycles
    .filter(
      (cycle) =>
        cycle.available >= data.run.start &&
        cycle.available <= cursor &&
        cycle.forecastStatus === "ready" &&
        cycle.bins.length > 0,
    )
    .sort((a, b) => a.available - b.available || a.tick - b.tick);
}

/** Return the latest ready publication, including an expired record for provenance.
 * An invalid subsequent update does not erase a previously issued forecast.
 * Callers must stop predictions at the recorded cutoff plus horizon.
 */
export function latestReadyForecast(
  data: Dataset,
  cursor: number,
): Cycle | null {
  return publishedReadyForecasts(data, cursor).at(-1) ?? null;
}

/** Preserve the forecast that was visible at each historical instant.
 * Each segment begins at publication and ends at the next ready publication,
 * playback cursor or actual forecast horizon. A skipped update does not replace
 * history. The original bucket series includes points outside these clipping
 * boundaries so paths can interpolate up to the edges without changing counts.
 */
export function forecastHistory(
  data: Dataset,
  cursor: number,
  displayBinMs = 15000,
): ForecastHistorySegment[] {
  const ready = publishedReadyForecasts(data, cursor);
  return ready.flatMap((cycle, index) => {
    const start = cycle.available;
    const horizonEnd = cycle.cutoff + cycle.horizonMs;
    const end = Math.min(
      ready[index + 1]?.available ?? cursor,
      cursor,
      horizonEnd,
    );
    if (end <= start) return [];
    return [
      {
        cycle,
        start,
        end,
        buckets: forecastBuckets(cycle, displayBinMs).filter(
          (bucket) => bucket.start < horizonEnd && bucket.end <= horizonEnd,
        ),
      },
    ];
  });
}
