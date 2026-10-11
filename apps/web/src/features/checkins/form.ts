import type {
  SelfReportEntry,
  SelfReportRequest,
  Symptom,
  SymptomOnsetEntry,
} from "../../../../../contracts/typescript/index";
export const symptoms = [
  "fever",
  "chills",
  "cough",
  "sore_throat",
  "runny_nose",
  "congestion",
  "headache",
  "fatigue",
  "body_aches",
  "shortness_of_breath",
  "loss_of_taste_or_smell",
  "nausea",
  "diarrhea",
  "other",
] satisfies Symptom[];
export const kinds = [
  "symptom_onset",
  "symptom_checkin",
  "symptom_resolution",
  "test_result",
  "alertness_rating",
  "pvt_result",
  "confounder",
] satisfies SelfReportEntry["kind"][];
export function label(value: string) {
  return value.replaceAll("_", " ");
}
export function choose<const T extends string>(
  value: string,
  options: readonly T[],
): T {
  const found = options.find((option) => option === value);
  if (found === undefined) throw new Error("Choose a supported value.");
  return found;
}
export function utcClock(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value))
    throw new Error("Enter a complete UTC date and time.");
  const iso = `${value.length === 16 ? `${value}:00` : value}Z`;
  const date = new Date(iso);
  if (
    !Number.isFinite(date.getTime()) ||
    date.toISOString().slice(0, 19) !== iso.slice(0, 19)
  )
    throw new Error("Enter a valid UTC calendar date and time.");
  return date.toISOString();
}
export function buildEntry(
  data: FormData,
  identity: Pick<SelfReportEntry, "entry_id" | "entered_at_utc">,
): SelfReportEntry {
  const text = (key: string) => String(data.get(key) ?? "");
  const number = (key: string, min: number, max: number, integer = true) => {
    const raw = text(key);
    const value = Number(raw);
    if (
      !raw ||
      !Number.isFinite(value) ||
      value < min ||
      value > max ||
      (integer && !Number.isInteger(value))
    )
      throw new Error(
        `${label(key)} must be ${integer ? "a whole number " : ""}between ${min} and ${max}.`,
      );
    return value;
  };
  const time = (key: string) => utcClock(text(key));
  const range = () => {
    const earliest = time("earliest");
    const latest = time("latest");
    if (earliest > latest)
      throw new Error(
        "The latest possible event time must follow the earliest.",
      );
    if (earliest > identity.entered_at_utc)
      throw new Error("The event cannot start after this entry is recorded.");
    return { earliest, latest };
  };
  const selected = () => {
    const values = data
      .getAll("symptoms")
      .map((value) => choose(String(value), symptoms));
    const [head, ...tail] = values;
    if (head === undefined) throw new Error("Select at least one symptom.");
    return [head, ...tail] satisfies [Symptom, ...Symptom[]];
  };
  const severity = () => {
    const value = number("severity", 1, 3);
    if (value === 1 || value === 2 || value === 3) return value;
    throw new Error("Choose a severity.");
  };
  const eventTime = (key: string) => {
    const value = time(key);
    if (value > identity.entered_at_utc)
      throw new Error("The event cannot be in the future.");
    return value;
  };
  const kind = choose(text("kind"), kinds);
  switch (kind) {
    case "symptom_onset": {
      const { earliest, latest } = range();
      return {
        ...identity,
        kind,
        onset_earliest_utc: earliest,
        onset_latest_utc: latest,
        symptoms: selected(),
        severity: severity(),
      };
    }
    case "symptom_checkin": {
      const { earliest, latest } = range();
      if (earliest === latest)
        throw new Error("A check-in period must have a positive duration.");
      const present = text("present") === "yes";
      return {
        ...identity,
        kind,
        period_start_utc: earliest,
        period_end_utc: latest,
        symptoms_present: present,
        symptoms: present ? selected() : [],
        severity: present ? severity() : null,
      };
    }
    case "symptom_resolution": {
      const { earliest, latest } = range();
      const onset = text("onset_entry_id");
      if (!onset)
        throw new Error("Choose the recorded onset this resolution follows.");
      return {
        ...identity,
        kind,
        onset_entry_id: onset,
        resolved_earliest_utc: earliest,
        resolved_latest_utc: latest,
      };
    }
    case "test_result": {
      const { earliest, latest } = range();
      return {
        ...identity,
        kind,
        collected_earliest_utc: earliest,
        collected_latest_utc: latest,
        pathogen: choose(text("pathogen"), [
          "sars_cov_2",
          "influenza",
          "rsv",
          "other",
          "unknown",
        ]),
        method: choose(text("method"), ["pcr", "antigen", "other", "unknown"]),
        result: choose(text("result"), [
          "positive",
          "negative",
          "inconclusive",
        ]),
      };
    }
    case "alertness_rating":
      return {
        ...identity,
        kind,
        rated_at_utc: eventTime("event"),
        scale: "kss_1_9",
        value: number("value", 1, 9),
      };
    case "pvt_result": {
      const trials = number("trials", 1, Number.MAX_SAFE_INTEGER);
      return {
        ...identity,
        kind,
        started_at_utc: eventTime("event"),
        duration_seconds: number("duration_seconds", 60, 900),
        trials,
        mean_reaction_time_ms: number(
          "mean_reaction_time_ms",
          0.001,
          10000,
          false,
        ),
        lapses: number("lapses", 0, trials),
      };
    }
    case "confounder": {
      const { earliest, latest } = range();
      return {
        ...identity,
        kind,
        occurred_earliest_utc: earliest,
        occurred_latest_utc: latest,
        factor: choose(text("factor"), [
          "alcohol",
          "vaccination",
          "travel",
          "intense_exercise",
          "sleep_loss",
          "medication",
          "other",
        ]),
      };
    }
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}
export function entryRequest(entry: SelfReportEntry): SelfReportRequest {
  return { schema_version: "0.1", entries: [entry] };
}

export function entryDefaults(
  entry: SelfReportEntry,
): Record<string, string | string[]> {
  const clock = (value: string) => value.slice(0, 19);
  switch (entry.kind) {
    case "symptom_onset":
      return {
        earliest: clock(entry.onset_earliest_utc),
        latest: clock(entry.onset_latest_utc),
        symptoms: entry.symptoms,
        severity: String(entry.severity),
      };
    case "symptom_checkin":
      return {
        earliest: clock(entry.period_start_utc),
        latest: clock(entry.period_end_utc),
        present: entry.symptoms_present ? "yes" : "no",
        symptoms: entry.symptoms,
        severity: String(entry.severity ?? 1),
      };
    case "symptom_resolution":
      return {
        earliest: clock(entry.resolved_earliest_utc),
        latest: clock(entry.resolved_latest_utc),
        onset_entry_id: entry.onset_entry_id,
      };
    case "test_result":
      return {
        earliest: clock(entry.collected_earliest_utc),
        latest: clock(entry.collected_latest_utc),
        pathogen: entry.pathogen,
        method: entry.method,
        result: entry.result,
      };
    case "alertness_rating":
      return { event: clock(entry.rated_at_utc), value: String(entry.value) };
    case "pvt_result":
      return {
        event: clock(entry.started_at_utc),
        duration_seconds: String(entry.duration_seconds),
        trials: String(entry.trials),
        mean_reaction_time_ms: String(entry.mean_reaction_time_ms),
        lapses: String(entry.lapses),
      };
    case "confounder":
      return {
        earliest: clock(entry.occurred_earliest_utc),
        latest: clock(entry.occurred_latest_utc),
        factor: entry.factor,
      };
    default: {
      const exhaustive: never = entry;
      return exhaustive;
    }
  }
}
export function supersededId(entry: SelfReportEntry): string | null {
  return "supersedes" in entry && typeof entry.supersedes === "string"
    ? entry.supersedes
    : null;
}
export function episodeRoot(
  entry: SymptomOnsetEntry,
  versions: SelfReportEntry[],
): string {
  let current: SelfReportEntry = entry;
  const visited = new Set<string>();
  while (supersededId(current)) {
    if (visited.has(current.entry_id))
      throw new Error("The API returned a cyclic correction chain.");
    visited.add(current.entry_id);
    const parent = versions.find(
      (version) => version.entry_id === supersededId(current),
    );
    if (!parent || parent.kind !== "symptom_onset")
      throw new Error(
        "The original episode onset is missing. Reload the history before requesting recovery.",
      );
    current = parent;
  }
  return current.entry_id;
}
