export const sections = [
  "import",
  "overview",
  "forecast",
  "anomaly",
  "symptoms",
  "sleep",
] as const;
export type Section = (typeof sections)[number];
export type Scenario =
  | "complete"
  | "empty"
  | "sparse"
  | "access-error"
  | "import-error"
  | "model-unavailable"
  | "report-error";
export type Cutoff = "2026-10-09T07:00:00Z" | "2026-10-10T07:00:00Z";
export type Coverage = {
  metric: string;
  unit: string;
  observed: number;
  expected: number;
};
export type History = {
  mode: "synthetic";
  scenario: Scenario;
  coverage: Coverage[];
  start: string;
  end: string;
};
export type Point = {
  utc: string;
  value: number | null;
  lower?: number;
  upper?: number;
};
export type Panel =
  | { kind: "illustrative"; points: Point[] }
  | { kind: "unavailable"; reason: string };
export type Report = {
  mode: "synthetic";
  cutoff: Cutoff;
  forecast: Panel;
  anomaly: Panel;
  baseline: string;
};
export type Workflow =
  | { kind: "empty" }
  | { kind: "importing"; scenario: Scenario }
  | { kind: "no-observations"; scenario: Scenario }
  | { kind: "import-error"; scenario: Scenario; message: string }
  | { kind: "coverage"; history: History }
  | { kind: "cutoff"; history: History; cutoff: Cutoff | "" }
  | { kind: "reporting"; history: History; cutoff: Cutoff }
  | { kind: "report-error"; history: History; cutoff: Cutoff; message: string }
  | { kind: "report"; history: History; report: Report };
export type ImportResult = Extract<
  Workflow,
  { kind: "coverage" | "no-observations" | "import-error" }
>;
export type Action =
  | { type: "load"; scenario: Scenario }
  | { type: "imported"; result: ImportResult }
  | { type: "acknowledge" }
  | { type: "cutoff"; cutoff: Cutoff | "" }
  | { type: "request" }
  | { type: "reported"; report: Report }
  | { type: "report-failed" }
  | { type: "reset" };
export function reducer(state: Workflow, action: Action): Workflow {
  switch (action.type) {
    case "reset":
      return { kind: "empty" };
    case "load":
      return { kind: "importing", scenario: action.scenario };
    case "imported":
      return state.kind === "importing" ? action.result : state;
    case "acknowledge":
      return state.kind === "coverage"
        ? { kind: "cutoff", history: state.history, cutoff: "" }
        : state;
    case "cutoff":
      return "history" in state && state.kind !== "coverage"
        ? { kind: "cutoff", history: state.history, cutoff: action.cutoff }
        : state;
    case "request":
      if (state.kind === "cutoff" && state.cutoff !== "")
        return {
          kind: "reporting",
          history: state.history,
          cutoff: state.cutoff,
        };
      if (state.kind === "report-error")
        return {
          kind: "reporting",
          history: state.history,
          cutoff: state.cutoff,
        };
      return state;
    case "reported":
      return state.kind === "reporting"
        ? { kind: "report", history: state.history, report: action.report }
        : state;
    case "report-failed":
      return state.kind === "reporting"
        ? {
            kind: "report-error",
            history: state.history,
            cutoff: state.cutoff,
            message:
              "The demonstration report failed. Retry this scenario or load a different history.",
          }
        : state;
  }
}
