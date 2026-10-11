import { test } from "node:test";
import assert from "node:assert/strict";
import { buildEntry, utcClock } from "../src/features/checkins/form.ts";
import { scenarioRequest } from "../src/features/scenarios/request.ts";
const identity = {
  entry_id: "synthetic-entry",
  entered_at_utc: "2026-10-11T12:00:00.000Z",
};
function form(values) {
  const data = new FormData();
  for (const [key, value] of Object.entries(values))
    for (const item of Array.isArray(value) ? value : [value])
      data.append(key, String(item));
  return data;
}
const range = { earliest: "2026-10-10T06:00", latest: "2026-10-10T08:00" };
test("UTC clocks preserve event time independently of save time and reject impossible dates", () => {
  assert.equal(utcClock(range.earliest), "2026-10-10T06:00:00.000Z");
  assert.throws(() => utcClock("2026-02-30T06:00"));
  assert.throws(() => utcClock("2026-10-10T06:00-07:00"));
  const entry = buildEntry(
    form({
      ...range,
      kind: "symptom_onset",
      symptoms: ["cough", "fatigue"],
      severity: 2,
    }),
    identity,
  );
  assert.equal(entry.onset_earliest_utc, "2026-10-10T06:00:00.000Z");
  assert.equal(entry.entered_at_utc, identity.entered_at_utc);
  assert.throws(() =>
    buildEntry(
      form({ ...range, kind: "symptom_onset", symptoms: [], severity: 2 }),
      identity,
    ),
  );
  assert.throws(() =>
    buildEntry(
      form({
        ...range,
        kind: "symptom_onset",
        earliest: "2026-10-12T06:00",
        latest: "2026-10-12T08:00",
        symptoms: "cough",
        severity: 2,
      }),
      identity,
    ),
  );
});
test("symptom absence is explicit and resolution references a recorded onset", () => {
  const entry = buildEntry(
    form({ ...range, kind: "symptom_checkin", present: "no" }),
    identity,
  );
  assert.deepEqual(entry.symptoms, []);
  assert.equal(entry.severity, null);
  assert.equal(entry.symptoms_present, false);
  assert.throws(() =>
    buildEntry(
      form({
        ...range,
        kind: "symptom_checkin",
        present: "no",
        latest: range.earliest,
      }),
      identity,
    ),
  );
  assert.throws(() =>
    buildEntry(form({ ...range, kind: "symptom_resolution" }), identity),
  );
  assert.equal(
    buildEntry(
      form({ ...range, kind: "symptom_resolution", onset_entry_id: "onset" }),
      identity,
    ).onset_entry_id,
    "onset",
  );
});
test("test uncertainty, KSS direction, PVT measurements and confounders use supported fields", () => {
  const entry = buildEntry(
    form({
      ...range,
      kind: "test_result",
      pathogen: "unknown",
      method: "unknown",
      result: "inconclusive",
    }),
    identity,
  );
  assert.equal(entry.result, "inconclusive");
  assert.equal(entry.collected_latest_utc, "2026-10-10T08:00:00.000Z");
  const rating = buildEntry(
    form({ kind: "alertness_rating", event: range.earliest, value: 9 }),
    identity,
  );
  assert.equal(rating.scale, "kss_1_9");
  assert.equal(rating.value, 9);
  const pvt = {
    kind: "pvt_result",
    event: range.earliest,
    duration_seconds: 180,
    trials: 31,
    mean_reaction_time_ms: 312.5,
    lapses: 2,
  };
  assert.equal(buildEntry(form(pvt), identity).mean_reaction_time_ms, 312.5);
  assert.throws(() => buildEntry(form({ ...pvt, lapses: 32 }), identity));
  assert.throws(() => buildEntry(form({ ...pvt, trials: 1.5 }), identity));
  assert.equal(
    buildEntry(
      form({ ...range, kind: "confounder", factor: "travel" }),
      identity,
    ).factor,
    "travel",
  );
});
test("schedule dates and explicit simulation assumptions are preserved; unsupported input is refused", () => {
  const values = {
    timezone: "America/Los_Angeles",
    bed_a: "2026-10-10T22:30",
    wake_a: "2026-10-11T06:30",
    bed_b: "2026-10-11T00:30",
    wake_b: "2026-10-11T06:30",
    prior_sleep: 7,
    caffeine: "not_modeled",
  };
  const request = scenarioRequest(form(values), "synthetic-001");
  assert.equal(request.schedules.length, 2);
  assert.equal(request.schedules[1].bedtime_local, "2026-10-11T00:30:00");
  assert.deepEqual(request.assumptions, {
    prior_sleep_hours: 7,
    caffeine: "not_modeled",
    light_exposure: "not_modeled",
  });
  assert.throws(() =>
    scenarioRequest(form({ ...values, wake_a: values.bed_a }), "synthetic-001"),
  );
  assert.throws(() =>
    scenarioRequest(
      form({ ...values, timezone: "somewhere" }),
      "synthetic-001",
    ),
  );
});

test("correction defaults round-trip event fields and retain the original episode root", async () => {
  const { entryDefaults, episodeRoot } =
    await import("../src/features/checkins/form.ts");
  const original = buildEntry(
    form({ ...range, kind: "symptom_onset", symptoms: ["cough"], severity: 1 }),
    identity,
  );
  const corrected = {
    ...buildEntry(
      form({ kind: original.kind, ...entryDefaults(original), severity: 2 }),
      { entry_id: "correction", entered_at_utc: "2026-10-11T13:00:00.000Z" },
    ),
    supersedes: original.entry_id,
  };
  assert.equal(corrected.onset_earliest_utc, original.onset_earliest_utc);
  assert.equal(
    episodeRoot(corrected, [original, corrected]),
    original.entry_id,
  );
  assert.throws(() => episodeRoot(corrected, [corrected]));
  const cycle = { ...original, supersedes: corrected.entry_id };
  assert.throws(() => episodeRoot(corrected, [cycle, corrected]));
});
