/** Browser data contract. All times are integer milliseconds relative to the recorded origin. */
export type Phase = "startup" | "processing" | "release" | "unknown";
export interface Worker {
  name: string;
  label: string;
  cores: number;
  slots: number;
  memoryMiB: number;
}
export interface Job {
  uid: string;
  requestId: string | null;
  creation: number;
  available: number;
  completed: number | null;
  terminalAvailable: number | null;
  outcome: string | null;
  /** Application execution finish, separate from Kubernetes Job completion. */
  serviceFinished?: number | null;
  serviceAvailable?: number | null;
  evaluated?: boolean;
}
export interface HeldJob {
  job: number;
  cores: number;
  memoryMiB?: number | null;
  phase: Phase;
}
export interface WorkerState {
  ready: boolean;
  accepting: boolean;
  held: HeldJob[];
}
export interface Snapshot {
  at: number;
  started: number;
  complete: boolean;
  workers: WorkerState[];
  queue: number[];
  processing: number;
  assignedWaiting: number;
  sourceIndex: number;
}
export interface ResourceSample {
  job: number;
  capture: number;
  observation: number;
  available: number | null;
  cpu: number;
  memory: number;
  basis: string;
  proofState: number | null;
}
export interface Gap {
  start: number;
  end: number;
  reason: string;
  available?: number;
}
export interface Candidate {
  name: string;
  worker: number | null;
  valid: boolean;
  /** Recorded explanation for an unavailable candidate; absent in older datasets. */
  unavailableReason?: string | null;
  onTime: number | null;
  allocationCoreSeconds: number | null;
  scenarioOnTime: number[];
  allocationWindowSeconds: number | null;
}
export interface PredictedTask {
  id: number;
  scenario: number;
  candidate: string;
  worker: number | null;
  creation: number;
  scheduled: number | null;
  finished: number | null;
  cores: number;
  cohort: string;
}
export interface Cycle {
  tick: number;
  cutoff: number;
  available: number;
  timestampNs: string;
  forecastStatus: string;
  /** Recorded forecast validation reasons; absent in older datasets. */
  forecastReasons?: string[];
  binMs: number;
  horizonMs: number;
  bins: { start: number; mean: number }[];
  futures: number[][];
  candidates: Candidate[];
  action: string;
  worker: number | null;
  reason: string;
  valid: boolean;
  guardrailFeasible: boolean | null;
  inputQueue: number | null;
  inputSlots: number | null;
  inputAssigned: number | null;
  tasks: PredictedTask[];
}
export interface CapacityEvent {
  at: number;
  sequence: number;
  timestampNs: string;
  event: string;
  worker: number | null;
  tick: number | null;
  action: string | null;
  activationId: string | null;
  actionId: string | null;
  status: string | null;
  due: number | null;
  error: string | null;
}
export interface Bookmark {
  at: number;
  label: string;
  kind: string;
}
export interface PolicyResult {
  captureId: string;
  seed: number;
  policy: "fixed" | "reactive" | "forecast";
  planSha256: string;
  jobs: number;
  timelyJobs: number;
  completedJobs: number;
  p95CompletedSeconds: number | null;
  allocationBounds: [number, number];
  deadlineSeconds: number;
  targetFraction: number;
  evaluationSeconds: number;
  followupSeconds: number;
  initialWorkers: number;
  workerCount: number;
  workerCores: number;
  acquisitionSeconds: number;
  cadenceSeconds: number;
  network: string;
  reactiveUpThreshold: number | null;
  reactiveDownThreshold: number | null;
  reactiveStabilizationSeconds: number | null;
}
export interface PolicyComparison {
  status: string;
  sourceSha256: string;
  runs: PolicyResult[];
}
export interface Dataset {
  comparison?: PolicyComparison;
  schemaVersion: 1;
  run: {
    id: string;
    title: string;
    status: string;
    originMs: number;
    start: number;
    end: number;
    evaluationStart: number;
    arrivalEnd: number;
    followupEnd: number;
    maxGapMs: number;
    sampleMaxAgeMs: number;
    deadlineSeconds: number;
    deadlineFraction: number;
    network: string;
    periodSeconds: number;
    cadenceSeconds: number;
    workers: Worker[];
  };
  jobs: Job[];
  snapshots: Snapshot[];
  resources: ResourceSample[];
  gaps: Gap[];
  failures: { at: number; reason: string }[];
  cycles: Cycle[];
  capacityEvents: CapacityEvent[];
  bookmarks: Bookmark[];
  provenance: {
    sourceHost: string;
    sourceRoot: string;
    acquiredAt: string;
    sourceBytes: number;
    manifestSha256: string;
    sourceHashes: Record<string, string>;
    availabilityNotes: string[];
    report: {
      accepted: boolean;
      evaluatedJobs: number;
      timelyJobs: number;
      allocationBounds: number[] | null;
    };
    [key: string]: unknown;
  };
}
