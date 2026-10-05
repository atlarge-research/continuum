/** Historical action lifecycle and current observation freshness are separate facts. */
import type { Dataset } from "./types.ts";
import type { ReplayView } from "./replay.ts";
import { formatTime } from "./charts.ts";
interface DecisionText {
  title: string;
  detail: string;
  warning: boolean;
  stage: string;
}
export function decisionText(data: Dataset, view: ReplayView): DecisionText {
  const cycle = view.cycle;
  if (!cycle)
    return {
      title: "Waiting for a recorded decision",
      detail: "",
      warning: false,
      stage: "Observe",
    };
  const time = (value: number) => formatTime(value - data.run.start);
  const actionName =
    cycle.action === "scale-up"
      ? "Scale up"
      : cycle.action === "scale-down"
        ? "Scale down"
        : "Do nothing";
  const fallback = !cycle.valid;
  const describe = (text: DecisionText): DecisionText =>
    fallback
      ? {
          ...text,
          title: `Reactive fallback · ${text.title}`,
          detail: `${cycle.forecastReasons?.includes("state_stale") ? "Forecast update skipped: input observation exceeded its freshness limit. " : ""}Recorded reactive fallback used observed demand. ${text.detail}`,
          warning: true,
        }
      : text;
  const events = view.events.filter((event) => event.tick === cycle.tick);
  const veto = events.find((event) => event.event === "cycle.error");
  if (veto) {
    const reason = (veto.error ?? "").toLowerCase();
    return describe({
      title: `${actionName} selected · safety check vetoed`,
      detail: reason.includes("empty")
        ? "A fresh observation no longer supported releasing this worker. Physical admission was kept."
        : "The recorded guard prevented this action. The cards show the observed outcome.",
      warning: true,
      stage: "Guard veto",
    });
  }
  if (cycle.action === "unchanged")
    return describe({
      title: "Keep current worker admission",
      detail: fallback
        ? "Physical admission was retained."
        : "The captured controller retained capacity after comparing its available alternatives.",
      warning: false,
      stage: fallback ? "Fallback" : "Hold",
    });
  const worker =
    cycle.worker === null ? "Worker" : data.run.workers[cycle.worker].label;
  const request = events.find((event) => event.event === "action.request");
  const confirmation =
    request && cycle.worker !== null
      ? data.snapshots.find(
          (snapshot) =>
            snapshot.at >= request.at &&
            snapshot.at <= view.cursor &&
            snapshot.complete &&
            snapshot.workers[cycle.worker!]?.accepting ===
              (cycle.action === "scale-up"),
        )
      : null;
  if (confirmation) {
    const current = view.workers[cycle.worker!].state;
    const stillObserved =
      view.fresh && current?.accepting === (cycle.action === "scale-up");
    return describe({
      title: stillObserved
        ? `${worker} ${cycle.action === "scale-up" ? "accepting Jobs" : "closed to new Jobs"} · observed`
        : `${worker}: admission change previously observed`,
      detail: `First physical confirmation at ${time(confirmation.at)}. ${!view.fresh ? "Current worker observation unavailable during this gap." : "The cards show current physical state."} Assigned work continues; the VM stays powered.`,
      warning: false,
      stage: "Physical response",
    });
  }
  const ack = events.find(
    (event) =>
      event.event === "action.result" && event.status === "acknowledged",
  );
  if (ack)
    return describe({
      title: `${worker}: API acknowledged · awaiting observation`,
      detail:
        "Acknowledgement is recorded separately from observed capacity. Cards change only on physical observation.",
      warning: false,
      stage: "Awaiting observation",
    });
  const activation = events.find(
    (event) => event.event === "activation.request",
  );
  if (activation)
    return describe({
      title: `${worker}: admission requested`,
      detail:
        "The powered reserve remains closed during the captured acquisition delay. Eligibility time is not proof of admission.",
      warning: false,
      stage: "Admission pending",
    });
  const reason =
    cycle.guardrailFeasible === false
      ? "All sampled options missed the model service target. The selected option had the least predicted violation."
      : fallback
        ? "The recorded action is shown; no valid forecast simulation was published."
        : "The historical controller selected the allocation/service tradeoff shown above.";
  return describe({
    title: `${actionName} on ${worker} · recorded selection`,
    detail: reason,
    warning: cycle.guardrailFeasible === false,
    stage: "Decision recorded",
  });
}
