import type { ScenarioRequest } from "../../../../../contracts/typescript/index";
import { choose } from "../checkins/form.ts";
export function scenarioRequest(
  data: FormData,
  subjectId: string,
): ScenarioRequest {
  const text = (key: string) => String(data.get(key) ?? "");
  const prior = Number(text("prior_sleep"));
  if (
    !text("prior_sleep") ||
    !Number.isFinite(prior) ||
    prior < 0 ||
    prior > 24
  )
    throw new Error("Prior sleep must be between 0 and 24 hours.");
  const timezone = text("timezone");
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone });
  } catch {
    throw new Error("Enter an IANA timezone, such as America/Los_Angeles.");
  }
  const schedule = (id: "a" | "b") => {
    const bed = text(`bed_${id}`);
    const wake = text(`wake_${id}`);
    if (
      !bed ||
      !wake ||
      !Number.isFinite(Date.parse(bed)) ||
      !Number.isFinite(Date.parse(wake))
    )
      throw new Error("Enter both dates and times for each schedule.");
    // Wall-clock ordering is a quick check; the backend resolves timezone/DST and the 16h limit.
    if (wake <= bed)
      throw new Error(
        "Wake time must follow bedtime; include the next day's date.",
      );
    return {
      schedule_id: id,
      bedtime_local: bed.length === 16 ? `${bed}:00` : bed,
      wake_time_local: wake.length === 16 ? `${wake}:00` : wake,
    };
  };
  return {
    schema_version: "0.1",
    subject_id: subjectId,
    tz_name: timezone,
    schedules: [schedule("a"), schedule("b")],
    assumptions: {
      prior_sleep_hours: prior,
      caffeine: choose(text("caffeine"), ["none", "not_modeled"]),
      light_exposure: "not_modeled",
    },
  };
}
