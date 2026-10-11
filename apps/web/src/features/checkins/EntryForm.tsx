import { useRef, useState, type FormEvent } from "react";
import type {
  SelfReportEntry,
  SymptomOnsetEntry,
} from "../../../../../contracts/typescript/index";
import {
  buildEntry,
  choose,
  entryDefaults,
  kinds,
  label,
  symptoms,
} from "./form";

export function EntryForm({
  onsets,
  busy,
  onSave,
  initialEntry,
  onCancel,
  saveError,
}: {
  onsets: SymptomOnsetEntry[];
  busy: boolean;
  initialEntry?: SelfReportEntry;
  onCancel?: () => void;
  saveError?: string;
  onSave: (entry: SelfReportEntry) => Promise<boolean>;
}) {
  const [kind, setKind] = useState<SelfReportEntry["kind"]>(
    initialEntry?.kind ?? "symptom_onset",
  );
  const [present, setPresent] = useState(
    initialEntry?.kind === "symptom_checkin" && !initialEntry.symptoms_present
      ? "no"
      : "yes",
  );
  const [error, setError] = useState("");
  const defaults = initialEntry ? entryDefaults(initialEntry) : {};
  const defaultText = (name: string) =>
    typeof defaults[name] === "string" ? defaults[name] : undefined;
  const attempt = useRef<
    { fingerprint: string; entry: SelfReportEntry } | undefined
  >(undefined);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setError("");
    try {
      const data = new FormData(form);
      const fingerprint = JSON.stringify([...data.entries()]);
      if (attempt.current?.fingerprint !== fingerprint)
        attempt.current = {
          fingerprint,
          entry: buildEntry(data, {
            entry_id: `entry-${crypto.randomUUID()}`,
            entered_at_utc: new Date().toISOString(),
          }),
        };
      const entry = initialEntry
        ? { ...attempt.current.entry, supersedes: initialEntry.entry_id }
        : attempt.current.entry;
      if (await onSave(entry)) {
        attempt.current = undefined;
        form.reset();
      }
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "This entry could not be saved. Check the fields and retry.",
      );
    }
  }
  const range = kind !== "alertness_rating" && kind !== "pvt_result";
  const hasSymptoms =
    kind === "symptom_onset" ||
    (kind === "symptom_checkin" && present === "yes");
  return (
    <form className="checkin-form" onSubmit={submit}>
      <h2>{initialEntry ? "Correct a saved check-in" : "Record a check-in"}</h2>
      {initialEntry && (
        <p>
          The original version stays in the audit history. This correction
          records a new entry time when saved.
        </p>
      )}
      <p>
        Event time describes what happened. Entry time is recorded separately
        when you save. Enter event clocks in UTC; saved history displays the
        exact UTC values.
      </p>
      <fieldset disabled={busy}>
        <legend>Entry details</legend>
        <label htmlFor="entry-kind">What are you recording?</label>
        <select
          id="entry-kind"
          name="kind"
          value={kind}
          onChange={(event) => {
            if (!initialEntry) setKind(choose(event.target.value, kinds));
            setError("");
          }}
        >
          {(initialEntry ? [initialEntry.kind] : kinds).map((kind) => (
            <option key={kind} value={kind}>
              {label(kind)}
            </option>
          ))}
        </select>
        {range ? (
          <div className="checkin-pair">
            <TimeField
              name="earliest"
              defaultValue={defaultText("earliest")}
              title={
                kind === "symptom_checkin"
                  ? "Period start · UTC"
                  : "Earliest possible event time · UTC"
              }
            />
            <TimeField
              name="latest"
              defaultValue={defaultText("latest")}
              title={
                kind === "symptom_checkin"
                  ? "Period end · UTC"
                  : "Latest possible event time · UTC"
              }
            />
          </div>
        ) : (
          <TimeField
            name="event"
            defaultValue={defaultText("event")}
            title={
              kind === "pvt_result" ? "PVT start · UTC" : "Rating time · UTC"
            }
          />
        )}
        {range && kind !== "symptom_checkin" && (
          <p className="caption">
            If the time is exact, use the same time twice. Otherwise record the
            uncertainty window.
          </p>
        )}
        {kind === "symptom_checkin" && (
          <>
            <label htmlFor="present">Symptoms during this period?</label>
            <select
              id="present"
              name="present"
              value={present}
              onChange={(event) => setPresent(event.target.value)}
            >
              <option value="yes">Present</option>
              <option value="no">No symptoms observed</option>
            </select>
            <p className="caption">
              No check-in means unknown. Explicit absence applies only to this
              recorded period.
            </p>
          </>
        )}
        {hasSymptoms && (
          <>
            <fieldset className="symptom-options">
              <legend>Observed symptoms</legend>
              {symptoms.map((symptom) => (
                <label key={symptom}>
                  <input
                    name="symptoms"
                    type="checkbox"
                    value={symptom}
                    defaultChecked={
                      Array.isArray(defaults.symptoms) &&
                      defaults.symptoms.includes(symptom)
                    }
                  />
                  {label(symptom)}
                </label>
              ))}
            </fieldset>
            <Choice
              defaultValue={defaultText("severity")}
              name="severity"
              title="Severity"
              options={[
                ["1", "Mild"],
                ["2", "Moderate"],
                ["3", "Severe"],
              ]}
            />
          </>
        )}
        {kind === "symptom_resolution" && (
          <>
            <label htmlFor="onset_entry_id">Recorded onset</label>
            <select
              id="onset_entry_id"
              name="onset_entry_id"
              defaultValue={defaultText("onset_entry_id")}
              required
            >
              <option value="">Choose an onset</option>
              {onsets.map((onset) => (
                <option key={onset.entry_id} value={onset.entry_id}>
                  {onset.symptoms.map(label).join(", ")} ·{" "}
                  {onset.onset_earliest_utc}
                </option>
              ))}
            </select>
            {onsets.length === 0 && (
              <p>Save a symptom onset before recording its resolution.</p>
            )}
          </>
        )}
        {kind === "test_result" && (
          <>
            <Choice
              defaultValue={defaultText("pathogen")}
              name="pathogen"
              title="Tested pathogen"
              options={[
                ["unknown", "Unknown"],
                ["sars_cov_2", "SARS-CoV-2"],
                ["influenza", "Influenza"],
                ["rsv", "RSV"],
                ["other", "Other"],
              ]}
            />
            <Choice
              defaultValue={defaultText("method")}
              name="method"
              title="Test method"
              options={[
                ["unknown", "Unknown"],
                ["pcr", "PCR"],
                ["antigen", "Antigen"],
                ["other", "Other"],
              ]}
            />
            <Choice
              defaultValue={defaultText("result")}
              name="result"
              title="Test result"
              options={[
                ["inconclusive", "Inconclusive"],
                ["negative", "Negative"],
                ["positive", "Positive"],
              ]}
            />
            <p className="caption">
              Collection time is not symptom onset. A negative test is not a
              symptom-free label.
            </p>
          </>
        )}
        {kind === "alertness_rating" && (
          <>
            <NumberField
              defaultValue={defaultText("value")}
              name="value"
              title="Karolinska Sleepiness Scale · 1–9"
              min={1}
              max={9}
            />
            <p>
              1 = extremely alert; 9 = very sleepy, fighting sleep. Use the same
              scale each time.
            </p>
          </>
        )}
        {kind === "pvt_result" && (
          <>
            <p>
              Enter a measured PVT result. This form does not administer a PVT
              or generate reaction times.
            </p>
            <NumberField
              defaultValue={defaultText("duration_seconds")}
              name="duration_seconds"
              title="Test duration · seconds"
              min={60}
              max={900}
            />
            <NumberField
              defaultValue={defaultText("trials")}
              name="trials"
              title="Number of trials"
              min={1}
            />
            <NumberField
              defaultValue={defaultText("mean_reaction_time_ms")}
              name="mean_reaction_time_ms"
              title="Mean reaction time · milliseconds"
              min={0.001}
              max={10000}
              step="any"
            />
            <NumberField
              defaultValue={defaultText("lapses")}
              name="lapses"
              title="Lapses · responses slower than 500 ms"
              min={0}
            />
          </>
        )}
        {kind === "confounder" && (
          <Choice
            defaultValue={defaultText("factor")}
            name="factor"
            title="Optional confounding factor"
            options={[
              ["alcohol", "Alcohol"],
              ["vaccination", "Vaccination"],
              ["travel", "Travel"],
              ["intense_exercise", "Intense exercise"],
              ["sleep_loss", "Sleep loss"],
              ["medication", "Medication"],
              ["other", "Other"],
            ]}
          />
        )}
        <button disabled={busy}>
          {busy
            ? "Saving…"
            : initialEntry
              ? "Save correction"
              : "Save check-in"}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel correction
          </button>
        )}
      </fieldset>
      {(error || saveError) && (
        <p className="error-text" role="alert">
          {error || saveError}
        </p>
      )}
    </form>
  );
}
export function TimeField({
  name,
  title,
  defaultValue,
}: {
  name: string;
  title: string;
  defaultValue?: string;
}) {
  return (
    <div>
      <label htmlFor={name}>{title}</label>
      <input
        id={name}
        name={name}
        type="datetime-local"
        step="1"
        defaultValue={defaultValue}
        required
      />
    </div>
  );
}
export function Choice({
  name,
  title,
  options,
  defaultValue,
}: {
  name: string;
  title: string;
  options: [string, string][];
  defaultValue?: string;
}) {
  return (
    <>
      <label htmlFor={name}>{title}</label>
      <select id={name} name={name} defaultValue={defaultValue}>
        {options.map(([value, title]) => (
          <option key={value} value={value}>
            {title}
          </option>
        ))}
      </select>
    </>
  );
}
export function NumberField({
  name,
  title,
  min,
  max,
  step = "1",
  defaultValue,
}: {
  name: string;
  title: string;
  min: number;
  max?: number;
  step?: string;
  defaultValue?: string;
}) {
  return (
    <div>
      <label htmlFor={name}>{title}</label>
      <input
        id={name}
        name={name}
        type="number"
        defaultValue={defaultValue}
        min={min}
        max={max}
        step={step}
        required
      />
    </div>
  );
}
