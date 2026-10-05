import { comparisonFromReport } from "./comparison.ts";
/** Normalize immutable raw evidence without importing or executing the controller/simulator. */
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import {
  parseEvidenceJson,
  nsMilliseconds,
  isoMilliseconds,
  heldJobs,
  isTerminal,
  resourceAvailability,
} from "../src/replay.ts";
import type {
  Dataset,
  Snapshot,
  Job,
  Cycle,
  CapacityEvent,
  Candidate,
  PredictedTask,
  Gap,
  ResourceSample,
} from "../src/types.ts";

const sha = (value: Buffer | string) =>
  createHash("sha256").update(value).digest("hex");
const OBSERVER_HASH =
  "0226ba9b335eb06b27357bd713dcb07e93a8b0e57c095489c49c061c22bdc967";
const WRITER_HASH =
  "f18d2600d442e55318430178fc6b09b3b3ca1ff20ecf4d78a49e3f9e64611e89";
function safeRelative(path: string): string {
  if (
    !path ||
    path.startsWith("/") ||
    path.split("/").includes("..") ||
    path.includes("\\")
  )
    throw new Error("Unsafe artifact path");
  return path;
}
/** Read each worker's recorded application capacity, separately from VM capacity. */
export function capturedWorkers(
  invocation: any,
  recorded: any[],
): Dataset["run"]["workers"] {
  return invocation.workers.map((name: string, index: number) => {
    const worker = recorded.find((w) => w.node_name === name);
    if (
      !worker ||
      worker.configured_cores !== invocation.worker_cores ||
      worker.configured_memory_mib !== invocation.worker_memory_mib ||
      !Number.isInteger(worker.modeled_cores) ||
      worker.modeled_cores <= 0 ||
      worker.modeled_cores > worker.configured_cores
    )
      throw new Error("Missing or inconsistent captured worker capacity");
    return {
      name,
      label: `Worker ${index + 1}`,
      cores: worker.configured_cores,
      slots: worker.modeled_cores,
      memoryMiB: worker.configured_memory_mib,
    };
  });
}
export function convertCapture(
  root: string,
  status = "preliminary",
  acceptance?: string,
): Dataset {
  if (!["preliminary", "accepted-final"].includes(status))
    throw new Error("Unknown dataset status");
  if (status === "accepted-final" && !acceptance)
    throw new Error("Accepted-final requires an explicit acceptance receipt");
  const json = (path: string): any =>
    parseEvidenceJson(readFileSync(join(root, safeRelative(path)), "utf8"));
  const lines = (path: string): any[] =>
    readFileSync(join(root, safeRelative(path)), "utf8")
      .trim()
      .split("\n")
      .filter(Boolean)
      .map(parseEvidenceJson);
  const acquisition = json("acquisition.json");
  if (
    acquisition.sourceUnchanged !== true ||
    acquisition.totalSourceBytes > 80 * 1024 * 1024
  )
    throw new Error("Missing bounded immutable acquisition proof");
  for (const file of acquisition.files) {
    const bytes = readFileSync(join(root, safeRelative(file.path)));
    if (bytes.length !== file.bytes || sha(bytes) !== file.sha256)
      throw new Error(`Artifact checksum changed: ${file.path}`);
  }
  if (
    sha(readFileSync(join(root, "supporting-metrics.json"))) !==
    acquisition.reportSha256
  )
    throw new Error("Supporting report checksum changed");
  const invocation = json("invocation.json");
  const sourceHashes = json("source-hashes.json");
  const producerText = readFileSync(
    join(root, "source/opendt_observer.py"),
    "utf8",
  );
  const rateWindow = producerText.match(/CPU_RATE_WINDOW = ["'](\d+)(s|m)["']/);
  if (!rateWindow)
    throw new Error("Captured application CPU rate window is not documented");
  const cpuRateWindowMs =
    Number(rateWindow[1]) * (rateWindow[2] === "m" ? 60000 : 1000);
  const endpoint = lines("endpoint.jsonl");
  const ready = endpoint.filter((r) => r.event_type === "schedule.ready");
  if (ready.length !== 1 || ready[0].run_id !== invocation.namespace)
    throw new Error("Ambiguous recorded run origin");
  const originMs = isoMilliseconds(ready[0].details.schedule_start_timestamp);
  const ms = (value: string, availability = false) =>
    isoMilliseconds(value, availability) - originMs;
  const ns = (value: string) => nsMilliseconds(value) - originMs;
  const seconds = (value: number) => Math.ceil(value * 1000) - originMs;
  const report = json("supporting-metrics.json");
  const reportedRuns = [
    ...(report.runs ?? []),
    ...(report.closed_loop_reports ?? []).flatMap((r: any) => r.runs ?? []),
  ];
  const runReport = reportedRuns.find(
    (r: any) => r.run_id === invocation.namespace,
  );
  if (!runReport)
    throw new Error("Supporting report does not contain this capture identity");
  let receipt: any = null;
  if (acceptance) {
    receipt = parseEvidenceJson(readFileSync(acceptance, "utf8"));
    if (
      receipt.captureId !== invocation.namespace ||
      receipt.accepted !== true ||
      !receipt.acceptedBy ||
      !receipt.evidenceLocation ||
      !receipt.acceptedAt
    )
      throw new Error(
        "Acceptance receipt must identify this capture and accepted evidence",
      );
  }
  if (status === "accepted-final" && runReport.accepted_capture !== true)
    throw new Error("Acceptance receipt contradicts capture validation");
  const capacityCase = acquisition.files
    .map((file: any) => file.path)
    .find((path: string) =>
      /controller\/cycle-\d+\/suite\/experiments\/unchanged\/0000\/case.json$/.test(
        path,
      ),
    );
  if (!capacityCase) throw new Error("Missing captured application capacity");
  const workers = capturedWorkers(invocation, json(capacityCase).workers);
  if (
    workers.length !== 6 ||
    workers.some((w: any) => !Number.isFinite(w.slots) || w.slots <= 0)
  )
    throw new Error(
      "This main screen requires a six-worker capture with explicit capacity",
    );
  const workerIndex = new Map<string, number>(
    workers.map((w: any, i: number) => [w.name, i]),
  );
  const rawStates = lines("observer/cluster-state.jsonl");
  const rawEvents = lines("observer/observer-events.jsonl");
  const profiles = lines("observer/workload.jsonl");
  const journal = lines("controller/journal.jsonl");
  if (journal.some((r: any, i: number) => r.sequence !== i))
    throw new Error("Journal sequence is inconsistent");
  if (
    rawStates.some(
      (s: any, i: number) =>
        s.run_id !== invocation.namespace ||
        (i > 0 &&
          BigInt(s.timestamp_unix_ns) <
            BigInt(rawStates[i - 1].timestamp_unix_ns)),
    )
  )
    throw new Error("Observer identity/clock order is inconsistent");
  const inventory = json("jobs.json").items.filter(
    (j: any) =>
      j.metadata.labels?.["app.kubernetes.io/name"] === "image-batch-worker",
  );
  const jobs: Job[] = inventory.map((j: any) => ({
    uid: j.metadata.uid,
    requestId: j.metadata.labels?.["continuum-request-id"] ?? null,
    creation: ms(j.metadata.creationTimestamp),
    available: Number.MAX_SAFE_INTEGER,
    completed: null,
    terminalAvailable: null,
    outcome: null,
    serviceFinished: null,
    serviceAvailable: null,
    evaluated: runReport.responses.cohort.some(
      (c: any) => c.uid === j.metadata.uid,
    ),
  }));
  const jobIndex = new Map<string, number>(jobs.map((j, i) => [j.uid, i]));
  const getJob = (uid: string): Job => {
    const index = jobIndex.get(uid);
    if (index === undefined)
      throw new Error(`Observed Job absent from terminal inventory: ${uid}`);
    return jobs[index];
  };
  const emitted = new Map<string, number>();
  for (const event of rawEvents) {
    const uid = event.details?.kubernetes_job_uid;
    if (event.run_id !== invocation.namespace)
      throw new Error("Observer event identity mismatch");
    if (event.event_type === "job.observed" && uid) {
      const job = getJob(uid);
      job.available = Math.min(job.available, ns(event.timestamp_unix_ns));
      if (
        event.details.creation_time &&
        ms(event.details.creation_time) !== job.creation
      )
        throw new Error("Job creation lineage mismatch");
    }
    if (event.event_type === "task.emitted" && uid)
      emitted.set(
        uid,
        Math.min(emitted.get(uid) ?? Infinity, ns(event.timestamp_unix_ns)),
      );
  }
  const snapshots: Snapshot[] = rawStates.map((raw: any, index: number) => {
    const at = ns(raw.timestamp_unix_ns);
    const held = heldJobs(raw);
    const all = [...raw.jobs.queued, ...raw.jobs.active, ...raw.jobs.finished];
    for (const record of all) {
      const job = getJob(record.kubernetes_job_uid);
      job.available = Math.min(job.available, at);
      job.requestId = record.request_id ?? job.requestId;
      if (
        record.execution_finish_time &&
        (job.serviceAvailable == null || at < job.serviceAvailable)
      ) {
        job.serviceFinished = ms(record.execution_finish_time);
        job.serviceAvailable = at;
        if (job.serviceFinished > at)
          throw new Error("Application finish evidence precedes execution");
      }
      if (isTerminal(record) && record.job_terminal_status) {
        if (job.terminalAvailable === null || at < job.terminalAvailable) {
          job.terminalAvailable = at;
          job.outcome = record.job_terminal_status;
        }
      }
    }
    let complete = (raw.collection?.missing_job_uids?.length ?? 0) === 0;
    const ws = workers.map((worker: any) => {
      const observed = raw.workers.find(
        (w: any) => w.node_name === worker.name,
      );
      if (!observed || observed.allocatable_cpu_count < worker.slots)
        complete = false;
      const entries = held
        .filter((h) => h.worker === worker.name)
        .map((h) => ({
          job: jobIndex.get(h.uid)!,
          cores: h.cores,
          memoryMiB: h.memoryMiB ?? null,
          phase: h.phase,
        }));
      if (
        entries.reduce((sum: number, h: any) => sum + h.cores, 0) > worker.slots
      )
        complete = false;
      return {
        ready: observed?.ready === true,
        accepting: observed?.schedulable === true,
        held: entries,
      };
    });
    const queue = all
      .filter((j: any) => !j.node_name && !isTerminal(j))
      .map((j: any) => jobIndex.get(j.kubernetes_job_uid)!);
    return {
      at,
      started: ms(raw.collection.started_at),
      complete,
      workers: ws,
      queue: [...new Set<number>(queue)],
      processing: held.filter((h) => h.phase === "processing").length,
      assignedWaiting: held.filter((h) => h.phase === "startup").length,
      sourceIndex: index,
    };
  });
  for (const profile of profiles) {
    const source = profile.source;
    const job = getJob(source.kubernetes_job_uid);
    const available = emitted.get(job.uid);
    if (available === undefined) continue;
    const completed = source.completion_time
      ? ms(source.completion_time)
      : null;
    if (completed !== null && completed > available)
      throw new Error("Terminal evidence precedes physical completion");
    job.completed = completed;
    if (job.terminalAvailable === null || available < job.terminalAvailable) {
      job.terminalAvailable = available;
      job.outcome = source.terminal_status;
    }
  }
  if (jobs.some((j) => j.available < j.creation))
    throw new Error("Job observation precedes its creation");
  const failures = rawEvents
    .filter((r: any) => r.event_type === "cluster_state.capture_failed")
    .map((r: any) => ({
      at: ns(r.timestamp_unix_ns),
      reason: r.details?.stage ?? "capture_failed",
    }));
  const cycles: Cycle[] = [];
  const prefixBounds: {
    bytes: number;
    completeBytes: number;
    at: number;
    tick: number;
    hash: string;
  }[] = [];
  for (const proposal of journal.filter(
    (r: any) => r.event === "cycle.proposal",
  )) {
    const directory = `controller/cycle-${String(proposal.tick).padStart(4, "0")}`;
    const forecast = json(directory + "/forecast/forecast.json");
    const timingExists = existsSync(
      join(root, directory + "/collection-timing.json"),
    );
    const boundary = json(directory + "/forecast/boundaries.json");
    const resourceBoundary = boundary["resource-snapshots.jsonl"];
    if (timingExists && resourceBoundary) {
      const timing = json(directory + "/collection-timing.json");
      prefixBounds.push({
        bytes: resourceBoundary.bytes,
        completeBytes: resourceBoundary.complete_bytes,
        at: seconds(timing.collected_at_seconds),
        tick: proposal.tick,
        hash: resourceBoundary.sha256,
      });
    }
    const p = proposal.proposal;
    const scores = existsSync(join(root, directory + "/scores.json"))
      ? json(directory + "/scores.json")
      : [];
    const futures: number[][] = [];
    const tasks: PredictedTask[] = [];
    const futureTaskInfo = new Map<number, any>();
    const forecastSettings = forecast.settings ?? {};
    if (forecast.status === "ready") {
      const nativeRoot = directory + "/native/artifacts/results/batch";
      const batch = json(nativeRoot + "/batch.json");
      if (
        batch.status !== "succeeded" ||
        batch.suite_manifest?.cutoff_ms !== isoMilliseconds(forecast.cutoff)
      )
        throw new Error("Native batch does not match forecast cutoff");
      for (
        let scenario = 0;
        scenario < forecastSettings.scenarios;
        scenario++
      ) {
        const casePath =
          directory +
          `/suite/experiments/unchanged/${String(scenario).padStart(4, "0")}/case.json`;
        const capturedCase = json(casePath);
        if (capturedCase.cutoff_ms !== isoMilliseconds(forecast.cutoff))
          throw new Error("Shared sampled-future cutoff mismatch");
        const future = capturedCase.tasks.filter(
          (t: any) => t.metadata.cohort === "future",
        );
        futures.push(
          future
            .map(
              (t: any) =>
                (t.metadata.original_creation_ms ??
                  t.metadata.original_submission_ms) - originMs,
            )
            .sort((a: number, b: number) => a - b),
        );
        if (future.length !== forecast.scenario_job_counts[scenario])
          throw new Error(
            "Sampled future count disagrees with issued forecast",
          );
        for (const task of capturedCase.tasks)
          if (["future", "backlog"].includes(task.metadata.cohort))
            futureTaskInfo.set(
              scenario * 1000000 + task.task.id,
              task.metadata,
            );
      }
      for (const member of batch.experiments) {
        if (!member.validated || member.status !== "succeeded") continue;
        const execution = json(
          nativeRoot +
            "/" +
            safeRelative(member.output_dir) +
            "/" +
            safeRelative(member.runner_dir) +
            "/execution.json",
        );
        for (const task of execution.validation?.tasks ?? []) {
          const metadata = futureTaskInfo.get(
            member.scenario * 1000000 + task.task_id,
          );
          if (!metadata) continue;
          const cutoff = isoMilliseconds(forecast.cutoff) - originMs;
          tasks.push({
            id: task.task_id,
            scenario: member.scenario,
            candidate: member.candidate,
            worker: workerIndex.get(task.host_name) ?? null,
            creation:
              (metadata.original_creation_ms ??
                metadata.original_submission_ms) - originMs,
            scheduled:
              task.schedule_time === null ? null : cutoff + task.schedule_time,
            finished:
              task.finish_time === null ? null : cutoff + task.finish_time,
            cores: task.cpu_count,
            cohort: metadata.cohort,
          });
        }
      }
    }
    const candidates: Candidate[] = (p.scores ?? []).map((score: any) => {
      const raw = scores.find((s: any) => s.candidate === score.candidate);
      return {
        name: score.candidate,
        worker: workerIndex.get(score.selected_worker) ?? null,
        valid: score.valid === true,
        unavailableReason:
          raw?.unavailable_reason ?? score.unavailable_reason ?? null,
        onTime: Number.isFinite(score.worst_late_fraction)
          ? 1 - score.worst_late_fraction
          : null,
        allocationCoreSeconds: Number.isFinite(score.allocated_core_seconds)
          ? score.allocated_core_seconds
          : null,
        scenarioOnTime: (score.scenario_late_fractions ?? []).map(
          (late: number) => 1 - late,
        ),
        allocationWindowSeconds:
          raw?.scenarios?.[0]?.allocation_window_seconds ?? null,
      };
    });
    cycles.push({
      tick: proposal.tick,
      cutoff: isoMilliseconds(forecast.cutoff) - originMs,
      available: ns(proposal.recorded_at_ns),
      timestampNs: proposal.recorded_at_ns,
      forecastStatus: forecast.status,
      forecastReasons: forecast.reasons ?? [],
      binMs: (forecastSettings.bin_seconds ?? 0) * 1000,
      horizonMs: (forecastSettings.horizon_seconds ?? 0) * 1000,
      bins: (forecast.predictions ?? []).map((b: any) => ({
        start: b.start_ms - originMs,
        mean: b.mean_count,
      })),
      futures,
      candidates,
      action: p.action,
      worker: workerIndex.get(p.selected_worker) ?? null,
      reason: p.reason,
      valid: proposal.forecast_valid === true,
      guardrailFeasible: p.guardrail_feasible ?? null,
      inputQueue: proposal.before.queue?.length ?? null,
      inputSlots: proposal.before.application_slots ?? null,
      inputAssigned: Object.keys(proposal.before.assignments ?? {}).length,
      tasks,
    });
  }
  if (!cycles.length) throw new Error("No recorded forecast/control cycles");
  const evaluationStart =
    invocation.warmup_cycles * invocation.period_seconds * 1000;
  const firstReady = cycles.find(
    (c) =>
      c.forecastStatus === "ready" && c.valid && c.cutoff >= evaluationStart,
  );
  if (!firstReady) throw new Error("No operating ready forecast");
  const forecastSettings = json(
    `controller/cycle-${String(firstReady.tick).padStart(4, "0")}/forecast/forecast.json`,
  ).settings;
  if (forecastSettings.origin_ms !== originMs)
    throw new Error("Forecast and sender origins disagree");
  const maxGapMs = forecastSettings.max_gap_seconds * 1000;
  const gaps: Gap[] = [];
  for (let i = 0; i < snapshots.length; i++) {
    const s = snapshots[i],
      next = snapshots[i + 1];
    if (next && next.at - s.at > maxGapMs)
      gaps.push({
        start: s.at + maxGapMs,
        end: next.at,
        reason: "observation_gap",
      });
    if (!s.complete)
      gaps.push({
        start: s.started,
        end: next?.at ?? s.at + maxGapMs,
        reason: "incomplete_membership",
        available: s.at,
      });
  }
  for (const failure of failures) {
    const next = snapshots.find((s) => s.at >= failure.at && s.complete);
    gaps.push({
      start: failure.at,
      end: next?.at ?? snapshots.at(-1)!.at,
      reason: failure.reason,
      available: failure.at,
    });
  }
  gaps.sort((a, b) => a.start - b.start);
  const clock = json("clock-preflight.json");
  const producerProof =
    sourceHashes["opendt_observer.py"] === OBSERVER_HASH &&
    sourceHashes["events.py"] === WRITER_HASH &&
    sha(readFileSync(join(root, "source/opendt_observer.py"))) ===
      OBSERVER_HASH &&
    sha(readFileSync(join(root, "source/events.py"))) === WRITER_HASH &&
    runReport.restarts?.["opendt-observer"] === 0 &&
    clock.guests?.every((g: any) =>
      g.offset_seconds_bounds.every((b: number) => Math.abs(b) <= 1),
    );
  const resourceBytes = readFileSync(
    join(root, "observer/resource-snapshots.jsonl"),
  );
  prefixBounds.sort((a, b) => a.at - b.at);
  for (const bound of prefixBounds) {
    if (
      bound.completeBytes > bound.bytes ||
      bound.bytes > resourceBytes.length ||
      sha(resourceBytes.subarray(0, bound.bytes)) !== bound.hash
    )
      throw new Error("Frozen resource prefix checksum mismatch");
  }
  let lineEnd = 0;
  const resources: ResourceSample[] = resourceBytes
    .toString("utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      lineEnd += Buffer.byteLength(line) + 1;
      const raw = parseEvidenceJson(line);
      const capture = ms(raw.capture_time),
        observation = raw.observation_time
          ? ms(raw.observation_time, true)
          : Number.MAX_SAFE_INTEGER;
      let availability = resourceAvailability(
        capture,
        observation,
        snapshots,
        producerProof,
      );
      if (availability.available === null) {
        const bound = prefixBounds.find(
          (b) => lineEnd <= b.completeBytes && b.at >= observation,
        );
        if (bound)
          availability = {
            available: bound.at,
            proofState: null,
            basis: `frozen_prefix_cycle_${bound.tick}`,
          };
      }
      if (
        !Number.isFinite(raw.cpu_usage_cores) ||
        raw.cpu_usage_cores < 0 ||
        !Number.isFinite(raw.memory_usage_mb) ||
        raw.memory_usage_mb < 0
      )
        throw new Error("Invalid measured application resource sample");
      const index = jobIndex.get(raw.job_uid);
      if (index === undefined)
        throw new Error("Resource sample lacks Job lineage");
      return {
        job: index,
        capture,
        observation,
        available: availability.available,
        cpu: raw.cpu_usage_cores,
        memory: raw.memory_usage_mb,
        basis: availability.basis,
        proofState: availability.proofState,
      };
    });
  const activationTicks = new Map<string, number>();
  const actionTicks = new Map<string, number>();
  let currentTick: number | null = null;
  const capacityEvents: CapacityEvent[] = journal
    .filter((r: any) => r.event !== "controller.start")
    .map((r: any) => {
      if (r.event === "cycle.begin") currentTick = r.tick;
      const tick =
        r.tick ??
        (r.activation_id ? activationTicks.get(r.activation_id) : undefined) ??
        (r.action_id ? actionTicks.get(r.action_id) : undefined) ??
        currentTick;
      if (r.event === "activation.request" && r.activation_id && tick !== null)
        activationTicks.set(r.activation_id, tick);
      if (r.event === "action.request" && r.action_id && tick !== null)
        actionTicks.set(r.action_id, tick);
      const proposal = cycles.find((c) => c.tick === tick);
      return {
        at: ns(r.recorded_at_ns),
        sequence: r.sequence,
        timestampNs: r.recorded_at_ns,
        event: r.event,
        worker: workerIndex.get(r.selected_worker) ?? proposal?.worker ?? null,
        tick,
        action: r.action ?? proposal?.action ?? null,
        activationId: r.activation_id ?? null,
        actionId: r.action_id ?? null,
        status: r.status ?? r.outcome ?? null,
        due: r.ready_at_seconds ? seconds(r.ready_at_seconds) : null,
        error: r.error ?? r.reason ?? null,
      };
    });
  const arrivalEnd = invocation.cycles * invocation.period_seconds * 1000;
  const start = Math.max(evaluationStart, firstReady.available);
  const end = Math.min(
    snapshots.at(-1)!.at,
    arrivalEnd + invocation.followup_seconds * 1000,
  );
  const bookmarks = [{ at: start, label: "Start", kind: "start" }];
  const secondRise = cycles.find(
    (c) => c.tick > 2 && c.action === "scale-up" && c.valid,
  );
  if (secondRise)
    bookmarks.push(
      {
        at: Math.max(start, secondRise.cutoff - 15000),
        label: "Demand rises",
        kind: "demand",
      },
      {
        at: secondRise.available,
        label: "Scale-up decision",
        kind: "decision",
      },
    );
  const observed = capacityEvents.find(
    (e) =>
      e.event === "activation.result" &&
      e.status === "observed" &&
      e.tick === secondRise?.tick,
  );
  if (observed) {
    const confirmation = snapshots.find(
      (s) => s.at >= observed.at && s.complete,
    );
    bookmarks.push({
      at: confirmation?.at ?? observed.at,
      label: "Scale-up confirmed",
      kind: "observed",
    });
  }
  const released = cycles.find(
    (c) =>
      c.tick > 2 &&
      c.action === "scale-down" &&
      capacityEvents.some(
        (e) =>
          e.tick === c.tick &&
          e.event === "action.result" &&
          e.status === "acknowledged",
      ),
  );
  if (released)
    bookmarks.push({
      at: released.available,
      label: "Scale-down decision",
      kind: "decision",
    });
  const fallback = cycles.find((c) => !c.valid);
  if (fallback)
    bookmarks.push({
      at: fallback.available,
      label: "Update skipped",
      kind: "fallback",
    });
  bookmarks.push({ at: end, label: "End", kind: "end" });
  bookmarks.sort((a, b) => a.at - b.at);
  const dataset: Dataset = {
    schemaVersion: 1,
    comparison: comparisonFromReport(
      report,
      invocation.namespace,
      status,
      sha(readFileSync(join(root, "supporting-metrics.json"))),
      receipt?.comparisonCaptureIds,
    ),
    run: {
      id: invocation.namespace,
      title: "Digital twin control for cellular-connected services",
      status,
      originMs,
      start,
      end,
      evaluationStart,
      arrivalEnd,
      followupEnd: arrivalEnd + invocation.followup_seconds * 1000,
      maxGapMs,
      sampleMaxAgeMs: cpuRateWindowMs + maxGapMs,
      deadlineSeconds: invocation.deadline_seconds,
      deadlineFraction: invocation.deadline_fraction,
      network: invocation.network_preset,
      periodSeconds: invocation.period_seconds,
      cadenceSeconds: invocation.cadence_seconds,
      workers,
    },
    jobs,
    snapshots,
    resources,
    gaps,
    failures,
    cycles,
    capacityEvents,
    bookmarks,
    provenance: {
      sourceHost: acquisition.sourceHost,
      sourceRoot: acquisition.sourceRoot,
      acquiredAt: acquisition.acquiredAt,
      sourceBytes: acquisition.totalSourceBytes,
      manifestSha256: sha(readFileSync(join(root, "acquisition.json"))),
      sourceHashes,
      producerProof,
      receipt: receipt
        ? { ...receipt, sha256: sha(readFileSync(acceptance!)) }
        : null,
      availabilityNotes: [
        "Forecasts and candidates are released at the controller proposal, a conservative recorded boundary rather than an exact issue time.",
        "Application samples are available by a proved next serialized collection or a verified immutable prefix; exact query response/write time is unrecorded.",
        "Historical controller service scores include its recorded timing assumptions; they are not rescored by current controller code.",
        "Sampled futures reflect conditional arrival randomness, not confidence intervals.",
      ],
      report: {
        accepted: runReport.accepted_capture === true,
        evaluatedJobs: runReport.responses.jobs,
        timelyJobs: runReport.responses.deadline_met,
        allocationBounds:
          runReport.allocation.allocated_core_seconds_bounds ?? null,
      },
    },
  };
  return dataset;
}
