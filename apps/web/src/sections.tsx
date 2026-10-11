import { useState, type Dispatch, type FormEvent } from "react";
import { ImportPanel } from "./features/import/ImportPanel";
import { ReportView } from "./features/reports/ReportView";
import { Plot } from "./components";
import { sleepPresets } from "./fixtures";
import type { Action, Section, Workflow } from "./workflow";
import type { Design } from "./App";

export function SectionView({
  section,
  workflow,
  dispatch,
  design,
}: {
  design: Design;
  section: Section;
  workflow: Workflow;
  dispatch: Dispatch<Action>;
}) {
  if (section === "import") return <ImportPanel workflow={workflow} dispatch={dispatch} />;
  if (section === "symptoms") return <Symptoms />;
  if (section === "sleep") return <Sleep />;
  if (workflow.kind !== "report") {
    return (
      <div className="notice">
        <h2>No report yet</h2>
        <p>Import a history, review coverage, and run the forecast and anomaly reports first.</p>
        <a className="button" href="#import">Go to import & coverage</a>
      </div>
    );
  }
  return (
    <ReportView
      section={section}
      design={design}
      imported={workflow.imported}
      coverage={workflow.coverage}
      asOf={workflow.asOf}
      reports={workflow.reports}
    />
  );
}
export function Symptoms() {
  const [preview, setPreview] = useState<{
    event: string;
    entry: string;
    symptom: string;
    severity: string;
  }>();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPreview({
      event: `${data.get("event")}:00Z`,
      entry: new Date().toISOString(),
      symptom: String(data.get("symptom")),
      severity: String(data.get("severity")),
    });
  }
  return (
    <>
      <form className="entry-form" onSubmit={submit}>
        <p>Nothing is saved or sent. Leaving this section or reloading clears the draft and preview.</p>
        <label htmlFor="event-time">Synthetic event time · UTC</label>
        <input
          id="event-time"
          name="event"
          type="datetime-local"
          defaultValue="2026-10-10T06:30"
          min="2026-10-01T00:00"
          max="2026-10-10T23:59"
          required
        />
        <label htmlFor="symptom">Synthetic symptom</label>
        <select id="symptom" name="symptom">
          <option>Example fatigue</option>
          <option>Example sore throat</option>
          <option>Example headache</option>
        </select>
        <label htmlFor="severity">Example severity</label>
        <select id="severity" name="severity">
          <option>Mild</option>
          <option>Moderate</option>
          <option>Severe</option>
        </select>
        <button>Preview synthetic entry</button>
      </form>
      {preview && (
        <section className="notice" role="status">
          <span className="badge">SYNTHETIC · UNSAVED PREVIEW</span>
          <h2>
            {preview.symptom} · {preview.severity}
          </h2>
          <p>Event time · {preview.event}</p>
          <p>Entry time · {preview.entry} (actual preview creation time)</p>
          <button className="secondary" onClick={() => setPreview(undefined)}>
            Clear preview
          </button>
        </section>
      )}
    </>
  );
}
export function Sleep() {
  const [preset, setPreset] = useState("steady");
  const selected =
    preset === "steady"
      ? sleepPresets.steady
      : preset === "late"
        ? sleepPresets.late
        : undefined;
  return (
    <>
      <section className="entry-form">
        <label htmlFor="sleep-preset">Named fixture preset</label>
        <select
          id="sleep-preset"
          value={preset}
          onChange={(event) => setPreset(event.target.value)}
        >
          <option value="steady">Steady evening · 22:30 to 06:30</option>
          <option value="late">Later night · 00:30 to 06:30</option>
          <option value="unsupported">
            Unsupported schedule · 03:00 to 07:00
          </option>
        </select>
        <p>
          Both examples use America/Los_Angeles, PDT (UTC−07:00). Steady evening
          starts October 9; later night starts October 10. Both wake October 10.
        </p>
      </section>
      {selected ? (
        <>
          <div className="report-meta">
            <span>SYNTHETIC SCHEDULE</span>
            <p>
              Bedtime <strong>{selected.bedtime}</strong> · Wake{" "}
              <strong>{selected.wake}</strong> · October 10, 2026 wake date
            </p>
          </div>
          <Plot
            panel={{
              kind: "illustrative",
              points: selected.values.map((value, index) => ({
                utc: `2026-10-${index === 4 ? "11" : "10"}T${["14", "17", "20", "23", "02"][index]}:00:00Z`,
                value,
              })),
            }}
            domain={[0, 100]}
            title={`${selected.label} · illustrative alertness`}
            unit="index"
            description="Arbitrary illustration index, 0 to 100, higher means more alert in the drawing. No measured scale, equations, calibration, or personal accuracy claim."
          />
          <details className="method">
            <summary>Fixed assumptions and source</summary>
            <p>
              Prior sleep · three illustrative nights of 8 hours. Caffeine ·
              none after 12:00 local. Light · ordinary indoor morning light and
              dim evening light. No naps, shift work, medication, or individual
              chronotype effects are represented.
            </p>
            <p>
              Manually drawn examples; no equations or measured alertness data.
            </p>
          </details>
        </>
      ) : (
        <div className="notice" role="status">
          <h2>Schedule unavailable.</h2>
          <p>
            03:00 to 07:00 has no static fixture. Choose a named supported
            preset. No curve is computed for arbitrary schedules.
          </p>
        </div>
      )}
    </>
  );
}
