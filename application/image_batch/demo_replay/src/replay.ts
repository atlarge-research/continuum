import type {
  Dataset,
  Snapshot,
  ResourceSample,
  Cycle,
  WorkerState,
  CapacityEvent,
} from "./types.ts";

/** Preserve integer nanoseconds before JSON parsing can round them. Node 24 supplies source text. */
export function parseEvidenceJson(text: string): any {
  return (JSON.parse as any)(
    text,
    (key: string, value: unknown, context?: { source: string }) => {
      if (key.endsWith("_ns") && typeof value === "number") {
        if (!context?.source || !/^\d+$/.test(context.source))
          throw new Error(`Invalid integer timestamp: ${key}`);
        return context.source;
      }
      return value;
    },
  );
}
/** Availability rounds upward: evidence must never be introduced into an earlier millisecond. */
export function nsMilliseconds(value: string): number {
  if (!/^\d+$/.test(value))
    throw new Error("Expected nonnegative integer nanoseconds");
  const ms = Number((BigInt(value) + 999999n) / 1000000n);
  if (!Number.isSafeInteger(ms))
    throw new Error("Timestamp exceeds safe millisecond range");
  return ms;
}
export function isoMilliseconds(value: string, availability = false): number {
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value))
    throw new Error("Timestamp must include timezone");
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) throw new Error(`Invalid timestamp: ${value}`);
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] ?? "";
  return ms + Number(availability && /[1-9]/.test(fraction.slice(3)));
}
export function isTerminal(job: any): boolean {
  return (
    ["Succeeded", "Failed"].includes(job.pod_phase) ||
    ["Complete", "Failed"].includes(job.job_terminal_status)
  );
}
/** Assigned requests persist through classifier termination until terminal Pod/Job evidence. */
export function heldJobs(raw: any): {
  uid: string;
  cores: number;
  memoryMiB?: number | null;
  phase: "startup" | "processing" | "release" | "unknown";
  worker: string;
}[] {
  const result: ReturnType<typeof heldJobs> = [];
  const seen = new Set<string>();
  for (const group of ["queued", "active", "finished"])
    for (const job of raw.jobs[group] ?? []) {
      if (!job.node_name || isTerminal(job) || seen.has(job.kubernetes_job_uid))
        continue;
      const cores = job.requested_cpu_count;
      if (!Number.isFinite(cores) || cores <= 0)
        throw new Error("Invalid assigned resource request");
      seen.add(job.kubernetes_job_uid);
      const phase: "startup" | "processing" | "release" | "unknown" =
        job.execution_state === "running"
          ? "processing"
          : job.execution_state === "waiting"
            ? "startup"
            : job.execution_state === "terminated"
              ? "release"
              : "unknown";
      result.push({
        uid: job.kubernetes_job_uid,
        cores,
        ...(Object.hasOwn(job, "requested_memory_mb")
          ? {
              memoryMiB:
                Number.isFinite(job.requested_memory_mb) &&
                job.requested_memory_mb >= 0
                  ? job.requested_memory_mb
                  : null,
            }
          : {}),
        phase,
        worker: job.node_name,
      });
    }
  return result;
}
/** A later serialized collection proves that the preceding resource write already completed. */
export function resourceAvailability(
  capture: number,
  observation: number,
  states: Snapshot[],
  proof: boolean,
): { available: number | null; proofState: number | null; basis: string } {
  if (proof && capture <= observation) {
    const state = states.find(
      (s) => s.started > observation && s.at >= s.started,
    );
    if (state)
      return {
        available: state.at,
        proofState: state.sourceIndex,
        basis: "next_serialized_collection",
      };
  }
  return { available: null, proofState: null, basis: "unavailable" };
}
export function latestAt<T extends { at: number }>(
  values: T[],
  cursor: number,
): T | null {
  let left = 0,
    right = values.length;
  while (left < right) {
    const middle = (left + right) >>> 1;
    if (values[middle].at <= cursor) left = middle + 1;
    else right = middle;
  }
  return left ? values[left - 1] : null;
}
export function coveredInterval(
  data: Dataset,
  start: number,
  end: number,
  cursor: number,
): boolean {
  if (
    end > cursor ||
    data.gaps.some(
      (g) =>
        (g.available ?? g.start) <= cursor && g.start < end && g.end > start,
    )
  )
    return false;
  const before = latestAt(data.snapshots, start);
  if (!before || !before.complete || start - before.at > data.run.maxGapMs)
    return false;
  const after = data.snapshots.find((s) => s.at >= end && s.at <= cursor);
  if (!after) return false;
  let previous = before;
  for (const snapshot of data.snapshots) {
    if (snapshot.at <= before.at) continue;
    if (snapshot.at > after.at) break;
    if (!snapshot.complete || snapshot.at - previous.at > data.run.maxGapMs)
      return false;
    previous = snapshot;
  }
  return true;
}
export function forecastActuals(
  data: Dataset,
  cycle: Cycle,
  cursor: number,
): {
  start: number;
  expected: number;
  actual: number | null;
  complete: boolean;
}[] {
  const arrivals = data.jobs.filter((j) => j.available <= cursor);
  return cycle.bins.map((bin) => {
    const end = bin.start + cycle.binMs;
    const complete =
      cycle.available <= cursor &&
      coveredInterval(data, bin.start, end, cursor);
    return {
      start: bin.start,
      expected: bin.mean,
      actual: complete
        ? arrivals.filter((j) => j.creation >= bin.start && j.creation < end)
            .length
        : null,
      complete,
    };
  });
}
export interface WorkerView {
  config: Dataset["run"]["workers"][number];
  state: WorkerState | null;
  pending: CapacityEvent | null;
  occupied: number | null;
  cpu: number | null;
  memory: number | null;
  sampled: number;
  totalJobs: number;
  sampleAge: number | null;
}
export interface ReplayView {
  cursor: number;
  snapshot: Snapshot | null;
  fresh: boolean;
  cycle: Cycle | null;
  knownArrivals: Dataset["jobs"];
  completed: number;
  failed: number;
  resources: ResourceSample[];
  workers: WorkerView[];
  acceptingSlots: number | null;
  pendingSlots: number;
  events: CapacityEvent[];
  quality: ReturnType<typeof forecastActuals>;
}
/** Derive all panels from immutable evidence. No prior calls or playback direction affect this result. */
export function viewAt(data: Dataset, cursor: number): ReplayView {
  const snapshot = latestAt(data.snapshots, cursor);
  const fresh =
    !!snapshot &&
    snapshot.complete &&
    cursor - snapshot.at <= data.run.maxGapMs &&
    !data.failures.some((f) => f.at > snapshot.at && f.at <= cursor);
  const cycle =
    [...data.cycles].reverse().find((c) => c.available <= cursor) ?? null;
  const events = data.capacityEvents.filter((e) => e.at <= cursor);
  const pending = new Map<string, CapacityEvent>();
  for (const event of events) {
    if (event.event === "activation.request" && event.activationId)
      pending.set(event.activationId, event);
    if (
      event.event === "activation.result" &&
      event.activationId &&
      ["observed", "cancelled", "canceled", "failed"].includes(
        event.status ?? "",
      )
    )
      pending.delete(event.activationId);
  }
  const latestSamples = new Map<number, ResourceSample>();
  for (const sample of data.resources) {
    if (
      sample.available === null ||
      sample.available > cursor ||
      sample.capture > cursor ||
      cursor - sample.capture > data.run.sampleMaxAgeMs
    )
      continue;
    const earlier = latestSamples.get(sample.job);
    if (!earlier || sample.capture > earlier.capture)
      latestSamples.set(sample.job, sample);
  }
  const resources = [...latestSamples.values()].sort((a, b) => a.job - b.job);
  const workers = data.run.workers.map((config, index): WorkerView => {
    const state = snapshot?.workers[index] ?? null;
    const held = state?.held ?? [];
    const sampled = held
      .map((h) => latestSamples.get(h.job))
      .filter((s): s is ResourceSample => !!s);
    const acquisition =
      [...pending.values()].find((e) => e.worker === index) ?? null;
    return {
      config,
      state,
      pending: state?.accepting ? null : acquisition,
      occupied:
        fresh && state ? held.reduce((sum, h) => sum + h.cores, 0) : null,
      cpu:
        fresh && sampled.length
          ? sampled.reduce((sum, s) => sum + s.cpu, 0)
          : null,
      memory:
        fresh && sampled.length
          ? sampled.reduce((sum, s) => sum + s.memory, 0)
          : null,
      sampled: sampled.length,
      totalJobs: held.length,
      sampleAge: sampled.length
        ? Math.max(...sampled.map((s) => cursor - s.capture))
        : null,
    };
  });
  const knownArrivals = data.jobs.filter((j) => j.available <= cursor);
  const completed = data.jobs.filter(
    (j) =>
      j.outcome === "Complete" &&
      j.completed !== null &&
      j.completed >= data.run.start &&
      j.terminalAvailable !== null &&
      j.terminalAvailable <= cursor,
  ).length;
  const failed = data.jobs.filter(
    (j) =>
      j.outcome === "Failed" &&
      j.terminalAvailable !== null &&
      j.terminalAvailable >= data.run.start &&
      j.terminalAvailable <= cursor,
  ).length;
  return {
    cursor,
    snapshot,
    fresh,
    cycle,
    knownArrivals,
    completed,
    failed,
    resources,
    workers,
    acceptingSlots: fresh
      ? workers.reduce(
          (sum, w) =>
            sum + (w.state?.ready && w.state.accepting ? w.config.slots : 0),
          0,
        )
      : null,
    pendingSlots: workers.reduce(
      (sum, w) => sum + (w.pending ? w.config.slots : 0),
      0,
    ),
    events,
    quality:
      cycle && cycle.forecastStatus === "ready"
        ? forecastActuals(data, cycle, cursor)
        : [],
  };
}
