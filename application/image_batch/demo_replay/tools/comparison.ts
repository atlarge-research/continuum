/** Extract compact completed-run summaries from the acquired report, without executing a policy. */
import type { PolicyComparison } from "../src/types.ts";
/** Ignore sealed artifact locations while preserving all deployment content identities. */
function deploymentContent(deployment: any) {
  if (!deployment) return deployment;
  const {
    config: _configPath,
    inventory: _inventoryPath,
    ...identities
  } = deployment;
  return identities;
}
/** Canonicalize mapping order without changing scientific values or list order. */
function canonical(value: any): any {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonical(value[key])]),
    );
  return value;
}
export function comparisonFromReport(
  report: any,
  captureId: string,
  status: string,
  sourceSha256: string,
  acceptedCaptureIds?: string[],
): PolicyComparison {
  const all =
    report.runs ??
    report.closed_loop_reports?.flatMap((r: any) => r.runs ?? []) ??
    [];
  if (!all.some((r: any) => r.run_id === captureId))
    throw new Error("Comparison report does not contain replay capture");
  const seeds = [...new Set<number>(all.map((r: any) => r.seed))].sort(
    (a, b) => a - b,
  );
  const runs: PolicyComparison["runs"] = [];
  for (const seed of seeds) {
    const arms = ["fixed", "reactive", "forecast"].map((arm) =>
      all.filter((r: any) => r.seed === seed && r.arm === arm),
    );
    if (arms.some((a) => a.length !== 1))
      throw new Error(
        "Comparison requires three matched policy runs per workload",
      );
    const group = arms.map((a) => a[0]);
    const reference = group[0];
    const signature = (r: any) =>
      JSON.stringify(
        canonical({
          plan: r.arrival_plan_sha256,
          source: r.source_hashes,
          images: {
            endpoint: r.invocation.endpoint_image,
            native: r.invocation.native_image,
          },
          deployment: deploymentContent(r.invocation.deployment_sources),
          settings: {
            ...r.comparison_settings,
            deployment_sources: deploymentContent(
              r.comparison_settings.deployment_sources,
            ),
          },
          config: r.config,
          window: r.arrival_end_seconds - r.evaluation_start_seconds,
          deadline: r.invocation.deadline_seconds,
          target: r.invocation.deadline_fraction,
          cohort: r.responses.jobs,
        }),
      );
    if (group.some((r) => signature(r) !== signature(reference)))
      throw new Error(
        "Comparison workload or accounting settings are not matched",
      );
    for (const r of group) {
      if (
        status === "accepted-final" &&
        (!Object.keys(r.source_hashes ?? {}).length ||
          !r.invocation.endpoint_image ||
          !r.invocation.native_image ||
          !r.comparison_settings.deployment_sources?.config_sha256 ||
          !r.comparison_settings.deployment_sources?.inventory_sha256)
      )
        throw new Error(
          "Final comparison requires matched source, image and deployment identities",
        );
      const b = r.allocation?.allocated_core_seconds_bounds;
      if (
        r.accepted_capture !== true ||
        !Array.isArray(r.acceptance_issues) ||
        r.acceptance_issues.length ||
        r.sender_evaluated_window?.fidelity_passed !== true
      )
        throw new Error("Comparison contains an unaccepted capture");
      if (
        !Array.isArray(b) ||
        b.length !== 2 ||
        b.some((v) => !Number.isFinite(v) || v < 0) ||
        b[0] > b[1]
      )
        throw new Error("Comparison allocation bounds are unavailable");
      const count = r.responses.jobs,
        timely = r.responses.deadline_met;
      if (
        !Number.isInteger(count) ||
        count <= 0 ||
        !Number.isInteger(timely) ||
        timely < 0 ||
        timely > count ||
        !Number.isInteger(r.responses.completed) ||
        r.responses.completed < timely ||
        r.responses.completed > count
      )
        throw new Error("Invalid comparison service denominator");
      const p95 = r.responses.completed_response_p95_seconds;
      if (r.responses.completed > 0 && (!Number.isFinite(p95) || p95 < 0))
        throw new Error("Invalid completed-response p95 duration");
      const cohort = r.responses.cohort;
      if (
        cohort !== undefined &&
        (!Array.isArray(cohort) ||
          cohort.length !== count ||
          cohort.some((job: any) => typeof job.uid !== "string" || !job.uid) ||
          new Set(cohort.map((job: any) => job.uid)).size !== count)
      )
        throw new Error(
          "Comparison response cohort does not preserve the service denominator and unique Jobs",
        );
      runs.push({
        captureId: r.run_id,
        seed,
        policy: r.arm,
        planSha256: r.arrival_plan_sha256,
        jobs: count,
        timelyJobs: timely,
        completedJobs: r.responses.completed,
        p95CompletedSeconds: r.responses.completed_response_p95_seconds,
        allocationBounds: [b[0], b[1]],
        deadlineSeconds: r.invocation.deadline_seconds,
        targetFraction: r.invocation.deadline_fraction,
        evaluationSeconds: r.arrival_end_seconds - r.evaluation_start_seconds,
        followupSeconds: r.comparison_settings.followup_seconds,
        initialWorkers: r.comparison_settings.active_workers[r.arm],
        workerCount: r.config.workers.length,
        workerCores: r.config.workers[0].configured_cores,
        acquisitionSeconds: r.comparison_settings.acquisition_seconds,
        cadenceSeconds: r.controller.cadence_seconds,
        network: r.comparison_settings.network_preset,
        reactiveTargetFraction: r.invocation.reactive_target_fraction ?? null,
        reactiveUpThreshold: r.invocation.reactive_up_threshold ?? null,
        reactiveDownThreshold: r.invocation.reactive_down_threshold ?? null,
        reactiveStabilizationSeconds:
          r.invocation.reactive_downscale_stabilization_seconds ?? null,
      });
    }
  }
  if (
    status === "accepted-final" &&
    !(
      acceptedCaptureIds &&
      runs.every((r) => acceptedCaptureIds.includes(r.captureId))
    )
  )
    throw new Error(
      "Final comparison requires explicit acceptance of all matched captures",
    );
  return { status, sourceSha256, runs };
}
