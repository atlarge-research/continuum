/** Conceptual policy diagrams, independent of recorded replay or comparison metrics. */
import { escapeHtml } from "./charts.ts";

type Policy = "fixed" | "reactive" | "forecast";
type Kind = "control" | "model";

type Node = {
  step: string;
  order: number;
  lines: string[];
  x: number;
  y: number;
  width: number;
  height: number;
  description: string;
  kind?: Kind;
  candidate?: string;
};

type Edge = {
  policy: Policy;
  from: string;
  to: string;
  path: string;
  description: string;
  kind?: Kind;
  feedback?: boolean;
  selected?: boolean;
  candidate?: string;
};

const color = (kind: Kind) =>
  kind === "model" ? "var(--twin)" : "var(--physical)";

/** Render one labeled conceptual step or alternative with inspectable geometry. */
function node(spec: Node): string {
  const kind = spec.kind ?? "control";
  const center = spec.x + spec.width / 2;
  const baseline =
    spec.y + spec.height / 2 + 6 - ((spec.lines.length - 1) * 20) / 2;
  const identity = spec.candidate
    ? `data-candidate="${spec.candidate}"`
    : `data-step="${spec.step}" data-order="${spec.order}"`;
  return `<g class="flow-node ${kind}${spec.candidate ? " flow-candidate" : ""}" ${identity} role="img" aria-label="${escapeHtml(spec.description)}"><title>${escapeHtml(spec.description)}</title><rect x="${spec.x}" y="${spec.y}" width="${spec.width}" height="${spec.height}" rx="5" fill="${kind === "model" ? "var(--soft-twin)" : "#e9f4f4"}" stroke="${color(kind)}" stroke-width="1.5"/><text class="flow-label" x="${center}" y="${baseline}" text-anchor="middle" font-size="18" fill="${color(kind)}">${spec.lines.map((line, index) => `<tspan x="${center}" y="${baseline + index * 20}">${escapeHtml(line)}</tspan>`).join(" ")}</text></g>`;
}

/** Render a directed connection; feedback is explicit rather than implied by proximity. */
function edge(spec: Edge): string {
  const kind = spec.kind ?? "control";
  return `<path class="flow-edge ${kind}${spec.feedback ? " flow-feedback" : ""}${spec.selected ? " flow-selected" : ""}" data-from="${spec.from}" data-to="${spec.to}" data-feedback="${Boolean(spec.feedback)}"${spec.selected ? ' data-selected="true"' : ""}${spec.candidate ? ` data-candidate="${spec.candidate}"` : ""} d="${spec.path}" fill="none" stroke="${color(kind)}" stroke-width="${spec.selected ? 3 : 2}" marker-end="url(#policy-${spec.policy}-${kind}-arrow)" role="img" aria-label="${escapeHtml(spec.description)}"><title>${escapeHtml(spec.description)}</title></path>`;
}

/** Wrap a policy drawing with unique accessible labels and local arrowheads. */
function panel(
  policy: Policy,
  label: string,
  description: string,
  sequence: string,
  body: string,
): string {
  const markers = (["control", "model"] as const)
    .map(
      (kind) =>
        `<marker id="policy-${policy}-${kind}-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="${color(kind)}"/></marker>`,
    )
    .join("");
  return `<section class="policy-flow ${policy}" data-policy="${policy}" data-conceptual="true" aria-label="${label}: conceptual decision process"><svg class="policy-flow-svg" width="400" height="120" viewBox="0 0 400 120" data-policy="${policy}" data-sequence="${sequence}" role="img" aria-labelledby="policy-${policy}-title policy-${policy}-description"><title id="policy-${policy}-title">${label}: conceptual decision process</title><desc id="policy-${policy}-description">${escapeHtml(description)}</desc><defs>${markers}</defs>${body}</svg></section>`;
}

/** Render the fixed capacity decision and its application. */
function fixedDiagram(): string {
  return panel(
    "fixed",
    "Static",
    "Decide a fixed processing capacity, then apply it. This is a conceptual explanation, not captured metrics.",
    "decide-capacity apply",
    [
      edge({
        policy: "fixed",
        from: "decide-capacity",
        to: "apply",
        path: "M202,60 H270",
        description: "The decided fixed capacity is applied.",
      }),
      node({
        step: "decide-capacity",
        order: 0,
        lines: ["Decide capacity"],
        x: 28,
        y: 44,
        width: 174,
        height: 32,
        description: "Decide a fixed processing capacity.",
      }),
      node({
        step: "apply",
        order: 1,
        lines: ["Apply"],
        x: 270,
        y: 44,
        width: 102,
        height: 32,
        description: "Apply the decided fixed capacity.",
      }),
    ].join(""),
  );
}

/** Render reactive rules and their closed physical observation loop. */
function reactiveDiagram(): string {
  return panel(
    "reactive",
    "Reactive heuristic",
    "Observe current physical conditions, evaluate reactive rules, and apply a capacity action. Measured feedback from physical execution informs the next observation, closing the control loop. This is a conceptual explanation, not captured metrics.",
    "observe rules apply observe",
    [
      edge({
        policy: "reactive",
        from: "observe",
        to: "rules",
        path: "M104,24 H156",
        description:
          "Observed current conditions are evaluated by reactive rules.",
      }),
      edge({
        policy: "reactive",
        from: "rules",
        to: "apply",
        path: "M244,24 H306",
        description: "The reactive rules select an action to apply.",
      }),
      edge({
        policy: "reactive",
        from: "apply",
        to: "observe",
        path: "M349,40 V96 H56 V40",
        description:
          "Measured feedback from physical execution informs the next reactive observation.",
        feedback: true,
      }),
      node({
        step: "observe",
        order: 0,
        lines: ["Observe"],
        x: 8,
        y: 8,
        width: 96,
        height: 32,
        description: "Observe current workload and worker state.",
      }),
      node({
        step: "rules",
        order: 1,
        lines: ["Rules"],
        x: 156,
        y: 8,
        width: 88,
        height: 32,
        description: "Evaluate reactive threshold rules.",
      }),
      node({
        step: "apply",
        order: 2,
        lines: ["Apply"],
        x: 306,
        y: 8,
        width: 86,
        height: 32,
        description: "Apply the rule-selected capacity action.",
      }),
      `<text class="flow-label flow-feedback-label control" data-from="apply" data-to="observe" x="200" y="84" text-anchor="middle" font-size="18" fill="var(--physical)">Measured feedback</text>`,
    ].join(""),
  );
}

/** Render model-based alternatives, their convergence, and physical feedback. */
function forecastDiagram(): string {
  const candidates = [
    { name: "scale-up", label: "Scale up", x: 114, width: 88 },
    { name: "hold", label: "Hold", x: 214, width: 54 },
    { name: "scale-down", label: "Scale down", x: 282, width: 110 },
  ];
  const branches = candidates
    .map((candidate) => {
      const center = candidate.x + candidate.width / 2;
      return [
        edge({
          policy: "forecast",
          from: "simulate",
          to: candidate.name,
          path: `M320,46 V50 H${center} V58`,
          description: `Simulate the ${candidate.label.toLowerCase()} alternative.`,
          kind: "model",
          candidate: candidate.name,
        }),
        edge({
          policy: "forecast",
          from: candidate.name,
          to: "choose",
          path: `M${center},82 V89 H308 V95`,
          description: `Compare the simulated ${candidate.label.toLowerCase()} alternative when choosing an action.`,
          kind: "model",
          candidate: candidate.name,
        }),
        node({
          step: candidate.name,
          order: 2,
          lines: [candidate.label],
          x: candidate.x,
          y: 58,
          width: candidate.width,
          height: 24,
          description: `Simulated ${candidate.label.toLowerCase()} alternative, not a captured metric.`,
          kind: "model",
          candidate: candidate.name,
        }),
      ].join("");
    })
    .join("");
  return panel(
    "forecast",
    "Digital twin",
    "Observe physical conditions, forecast future demand, and simulate scale up, hold, and scale down alternatives. The alternatives reconverge at Choose. Apply the selected action to physical execution. Measured feedback from physical execution informs the next observation, closing the control loop. Purple represents forecasting and simulation; teal represents physical observation and control. This is a conceptual explanation, not captured metrics.",
    "observe forecast simulate choose apply observe",
    [
      edge({
        policy: "forecast",
        from: "observe",
        to: "forecast",
        path: "M94,24 H121",
        description: "Physical observations inform the demand forecast.",
        kind: "model",
      }),
      edge({
        policy: "forecast",
        from: "forecast",
        to: "simulate",
        path: "M217,24 H249",
        description:
          "The forecast is an input to simulated capacity alternatives.",
        kind: "model",
      }),
      branches,
      edge({
        policy: "forecast",
        from: "choose",
        to: "apply",
        path: "M263,107 H211",
        description:
          "Apply the action selected after comparing simulated alternatives.",
        selected: true,
      }),
      edge({
        policy: "forecast",
        from: "apply",
        to: "observe",
        path: "M133,107 H4 V24 H8",
        description:
          "Measured feedback from physical execution informs the next digital twin observation.",
        feedback: true,
      }),
      node({
        step: "observe",
        order: 0,
        lines: ["Observe"],
        x: 8,
        y: 2,
        width: 86,
        height: 44,
        description: "Observe physical workload and worker state.",
      }),
      node({
        step: "forecast",
        order: 1,
        lines: ["Forecast"],
        x: 121,
        y: 2,
        width: 96,
        height: 44,
        description: "Forecast future demand from current observations.",
        kind: "model",
      }),
      node({
        step: "simulate",
        order: 2,
        lines: ["Simulate", "alternatives"],
        x: 249,
        y: 2,
        width: 143,
        height: 44,
        description: "Simulate the effects of alternative capacity actions.",
        kind: "model",
      }),
      node({
        step: "choose",
        order: 3,
        lines: ["Choose"],
        x: 263,
        y: 95,
        width: 90,
        height: 24,
        description:
          "Choose an action after comparing the simulated alternatives.",
        kind: "model",
      }),
      node({
        step: "apply",
        order: 4,
        lines: ["Apply"],
        x: 133,
        y: 95,
        width: 78,
        height: 24,
        description: "Apply the chosen action to physical execution.",
      }),
      `<text class="flow-label flow-feedback-label control" data-from="apply" data-to="observe" x="8" y="74" font-size="18" fill="var(--physical)"><tspan x="8" y="74">Measured</tspan> <tspan x="8" y="95">feedback</tspan></text>`,
    ].join(""),
  );
}

/** Return the three conceptual policy drawings in their card and result order. */
export function policyDiagrams(): string {
  return fixedDiagram() + reactiveDiagram() + forecastDiagram();
}
