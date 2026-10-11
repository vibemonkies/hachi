import type {
  Cutoff,
  History,
  ImportResult,
  Point,
  Report,
  Scenario,
} from "./workflow";
export const scenarios: { value: Scenario; label: string }[] = [
  { value: "complete", label: "Complete history" },
  { value: "empty", label: "Empty observations" },
  { value: "sparse", label: "Sparse history" },
  { value: "access-error", label: "Access failure" },
  { value: "import-error", label: "Import failure" },
  { value: "model-unavailable", label: "Models unavailable" },
  { value: "report-error", label: "Report failure" },
];
export const cutoffs: { value: Cutoff; label: string }[] = [
  {
    value: "2026-10-09T07:00:00Z",
    label: "October 9, 07:00 UTC · earlier fixture",
  },
  {
    value: "2026-10-10T07:00:00Z",
    label: "October 10, 07:00 UTC · latest fixture",
  },
];
export function importFixture(scenario: Scenario): ImportResult {
  if (scenario === "empty") return { kind: "no-observations", scenario };
  if (scenario === "access-error" || scenario === "import-error")
    return {
      kind: "import-error",
      scenario,
      message:
        scenario === "access-error"
          ? "Synthetic source access was denied. No observations were loaded."
          : "Synthetic import could not be decoded. No observations were loaded.",
    };
  return {
    kind: "coverage",
    history: {
      mode: "synthetic",
      scenario,
      start: "2026-09-25T07:00:00Z",
      end: "2026-10-10T07:00:00Z",
      coverage: [
        {
          metric: "Heart rate · hourly mean",
          unit: "bpm",
          observed: scenario === "sparse" ? 144 : 342,
          expected: 360,
        },
        {
          metric: "Daily resting heart rate",
          unit: "bpm",
          observed: scenario === "sparse" ? 5 : 14,
          expected: 15,
        },
        {
          metric: "Completed nightly sleep",
          unit: "hours",
          observed: scenario === "sparse" ? 4 : 13,
          expected: 15,
        },
      ],
    },
  };
}
const forecastValues = {
  "2026-10-09T07:00:00Z": [62, 64, 72, 70, 66, 61],
  "2026-10-10T07:00:00Z": [64, 67, 75, 73, 68, 63],
};
const anomalyValues = {
  "2026-10-09T07:00:00Z": [0.4, 0.6, 0.3, 0.8, 1.1, 0.9],
  "2026-10-10T07:00:00Z": [0.6, 0.3, 0.8, 1.1, 0.9, 1.4],
};
export function reportFixture(history: History, cutoff: Cutoff): Report {
  const date = cutoff.slice(0, 10);
  const hours = ["07", "11", "15", "19", "23", "03"];
  const nextDate = date === "2026-10-09" ? "2026-10-10" : "2026-10-11";
  const forecast: Point[] = forecastValues[cutoff].map((value, index) => ({
    utc: `${index === 5 ? nextDate : date}T${hours[index]}:00:00Z`,
    value,
    lower: value - 7,
    upper: value + 7,
  }));
  const anomaly = anomalyValues[cutoff].map((value, index) => ({
    utc: `2026-10-${String(Number(date.slice(-2)) - 5 + index).padStart(2, "0")}T07:00:00Z`,
    value: history.scenario === "sparse" && index === 2 ? null : value,
  }));
  const unavailable = history.scenario === "model-unavailable";
  return {
    mode: "synthetic",
    cutoff,
    baseline: `2026-09-25T07:00:00Z to ${cutoff} (cutoff excluded)`,
    forecast:
      unavailable || history.scenario === "sparse"
        ? {
            kind: "unavailable",
            reason: unavailable
              ? "No compatible forecast artifact. A frozen evaluated model and generated API contract are required."
              : "Sparse history does not meet this fixture’s forecast coverage requirement. More eligible hourly observations are required.",
          }
        : { kind: "illustrative", points: forecast },
    anomaly: unavailable
      ? {
          kind: "unavailable",
          reason:
            "No compatible anomaly artifact. A causal baseline and evaluated missingness policy are required.",
        }
      : { kind: "illustrative", points: anomaly },
  };
}
export const sleepPresets = {
  steady: {
    label: "Steady evening",
    bedtime: "22:30",
    wake: "06:30",
    values: [72, 83, 76, 61, 67],
  },
  late: {
    label: "Later night",
    bedtime: "00:30",
    wake: "06:30",
    values: [49, 63, 58, 43, 48],
  },
};
