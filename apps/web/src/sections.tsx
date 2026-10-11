import { useState, type Dispatch, type FormEvent } from "react";
import { cutoffs, scenarios, sleepPresets } from "./fixtures";
import type { Design } from "./App";
import { Plot } from "./components";
import type { Action, Cutoff, Scenario, Section, Workflow } from "./workflow";
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
  if (section === "import")
    return <ImportSection workflow={workflow} dispatch={dispatch} />;
  if (section === "symptoms") return <Symptoms />;
  if (section === "sleep") return <Sleep />;
  if (workflow.kind !== "report")
    return (
      <div className="notice">
        <h2>No report yet</h2>
        <p>Load a history and review coverage first.</p>
        <a className="button" href="#import">
          Go to import & coverage
        </a>
      </div>
    );
  const { report, history } = workflow;
  return (
    <>
      <div className="report-meta">
        <span>HAND-AUTHORED FIXTURE</span>
        <p>
          Cutoff <strong>{report.cutoff}</strong>
        </p>
        <a href="#import">Change cutoff</a>
      </div>
      <div
        className={design === "analysis" && section !== "overview" ? "analysis-detail" : undefined}
      >
        <div className="report-content">
          {section === "overview" ? (
            <>
              <div className="overview-layout">
                <div className="overview-results">
                  <div className="reading-list">
                    <a href="#forecast">
                      <span>Forecast</span>
                      <strong>{report.forecast.kind === "illustrative" ? "Illustrative heart rate" : "Unavailable"}</strong>
                      <span>{report.forecast.kind === "illustrative" ? "Six selected hourly bins within 24 hours · Open forecast →" : report.forecast.reason}</span>
                    </a>
                    <a href="#anomaly">
                      <span>Baseline deviation</span>
                      <strong>{report.anomaly.kind === "illustrative" ? "Illustrative baseline deviation" : "Unavailable"}</strong>
                      <span>{report.anomaly.kind === "illustrative" ? "Historical fixture scores · View deviation →" : report.anomaly.reason}</span>
                    </a>
                  </div>
                  {design === "analysis" && (
                    <div className="overview-plots">
                      <Plot
                        panel={report.forecast}
                        title="Heart rate · hourly mean"
                        unit="bpm"
                        expanded
                        description="Six selected hourly bins within 24 hours, not a full forecast. Bounds are illustrative and uncalibrated; no forecast model ran."
                      />
                      <Plot
                        panel={report.anomaly}
                        title="Historical baseline deviation"
                        unit="score"
                        expanded
                        description="Hand-authored scores: zero means baseline-like; larger means greater deviation. Not illness probability. No validated alert threshold."
                      />
                    </div>
                  )}
                </div>
                {design === "analysis" && <EvidenceRegister workflow={workflow} />}
              </div>
              <UnavailableTasks />
            </>
          ) : section === "forecast" ? (
            <>
              <p className="lead">
                Hourly heart-rate examples after the cutoff. Six selected hourly
                bins illustrate a 24-hour horizon, not a complete modeled forecast.
              </p>
              <Plot
                panel={report.forecast}
                title="Heart rate · hourly mean"
                unit="bpm"
                expanded={design === "analysis"}
                description={`Hand-authored medians; no forecast model ran. Bounds are illustrative and uncalibrated, not a likely range. Horizon starts ${report.cutoff} and ends 24 hours later.`}
              />
              <p className="method">
                Coverage at import · {history.coverage[0].observed}/
                {history.coverage[0].expected} hourly bins across the synthetic
                import period. Report examples contain no input from after the
                cutoff. Source · hand-authored fixture, no model artifact.
              </p>
            </>
          ) : (
            <>
              <Plot
                panel={report.anomaly}
                expanded={design === "analysis"}
                title="Historical baseline deviation"
                unit="score"
                description="Synthetic standardized absolute deviation from a personal historical baseline. Zero means baseline-like; larger scores mean greater deviation. Not illness probability. No validated alert threshold or measured alert burden."
              />
              <details className="method">
                <summary>Baseline method and coverage</summary>
                <p>
                  Baseline window · {report.baseline} labels the final illustrative
                  point. Earlier points use windows ending at their own timestamps.
                  Scores and windows are static fixture metadata; no baseline
                  calculation runs.
                </p>
                <p>
                  Changed features · hourly heart-rate mean and resting heart rate.
                  No infection inference is made. Coverage ·{" "}
                  {history.coverage[1].observed}/{history.coverage[1].expected}{" "}
                  daily resting-HR values. Missing points are gaps, never zero.
                </p>
                <p>
                  Provenance · hand-authored synthetic baseline and scores. No
                  trained model, calibrated alert rule, or confounder adjustment.
                </p>
              </details>
            </>
          )}
        </div>
        {design === "analysis" && section !== "overview" && (
          <EvidenceRegister workflow={workflow} />
        )}
      </div>
    </>
  );
}
function EvidenceRegister({
  workflow,
}: {
  workflow: Extract<Workflow, { kind: "report" }>;
}) {
  const { history, report } = workflow;
  return (
    <aside className="evidence-register" aria-label="Source and coverage">
      <h2>Source & coverage</h2>
      <p>Hand-authored synthetic history. No model artifact.</p>
      <dl>
        <dt>Import period · UTC</dt>
        <dd>{history.start}<br />to {history.end}<br />(end excluded)</dd>
        {history.coverage.map((row) => (
          <div key={row.metric}>
            <dt>{row.metric}</dt>
            <dd>
              {row.observed} / {row.expected}
              <span>observations / expected · signal unit: {row.unit}</span>
            </dd>
          </div>
        ))}
        <dt>Baseline window · final illustrative point</dt>
        <dd>{report.baseline}</dd>
      </dl>
      <p>
        Import-wide counts. Reports use the eligible prefix at the selected
        cutoff. Missing values are gaps, never zero.
      </p>
    </aside>
  );
}
function ImportSection({
  workflow,
  dispatch,
}: {
  workflow: Workflow;
  dispatch: Dispatch<Action>;
}) {
  const [scenario, setScenario] = useState<Scenario>("complete");
  const busy = workflow.kind === "importing" || workflow.kind === "reporting";
  const history = "history" in workflow ? workflow.history : undefined;
  const cutoff =
    workflow.kind === "report"
      ? workflow.report.cutoff
      : "cutoff" in workflow
        ? workflow.cutoff
        : "";
  return (
    <>
      <section className="import-panel">
        <div>
          <h2>Synthetic history</h2>
          <p>
            No files are read or uploaded.
          </p>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            dispatch({ type: "load", scenario });
          }}
        >
          <label htmlFor="scenario">Demonstration scenario</label>
          <select
            id="scenario"
            value={scenario}
            disabled={busy}
            onChange={(event) => setScenario(event.target.value as Scenario)}
          >
            {scenarios.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <button disabled={busy}>
            {workflow.kind === "importing"
              ? "Loading history…"
              : "Load synthetic history"}
          </button>
          <button
            className="text-button"
            type="button"
            onClick={() => dispatch({ type: "reset" })}
          >
            {busy ? "Cancel operation" : "Reset workspace"}
          </button>
        </form>
      </section>
      {workflow.kind === "import-error" && (
        <div className="notice error" role="alert">
          <h2>History could not be loaded.</h2>
          <p>{workflow.message}</p>
          <button
            onClick={() =>
              dispatch({ type: "load", scenario: workflow.scenario })
            }
          >
            Retry import
          </button>
        </div>
      )}
      {workflow.kind === "no-observations" && (
        <div className="notice">
          <h2>No observations in this fixture.</h2>
          <p>
            Missing observations are not zero values. Select Complete history to
            explore coverage and reports.
          </p>
          <button
            onClick={() =>
              dispatch({ type: "load", scenario: workflow.scenario })
            }
          >
            Retry empty import
          </button>
        </div>
      )}
      {history && (
        <section className="coverage">
          <h2>Coverage</h2>
          <p>
            Synthetic device fixture · {history.start} to {history.end} (end
            excluded).
          </p>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Coverage table"
          >
            <table>
              <caption>
                Import coverage. Expected counts use hourly bins or completed
                daily windows.
              </caption>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Unit</th>
                  <th>Observed / expected</th>
                  <th>Missing</th>
                  <th>Coverage</th>
                </tr>
              </thead>
              <tbody>
                {history.coverage.map((row) => (
                  <tr key={row.metric}>
                    <th scope="row">{row.metric}</th>
                    <td>{row.unit}</td>
                    <td>
                      {row.observed} / {row.expected}
                    </td>
                    <td>{row.expected - row.observed}</td>
                    <td>
                      <span
                        className="coverage-bar"
                        style={
                          {
                            "--coverage": `${(row.observed / row.expected) * 100}%`,
                          } as React.CSSProperties
                        }
                      />
                      {Math.round((row.observed / row.expected) * 100)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="caption">
            These are import-wide counts, not evidence available at every
            cutoff. Static report bundles use only the selected cutoff’s
            eligible prefix. Sleep duration and resting heart rate are distinct
            daily signals.
          </p>
          {workflow.kind === "coverage" && (
            <button onClick={() => dispatch({ type: "acknowledge" })}>
              I have reviewed the coverage
            </button>
          )}
        </section>
      )}
      {history && workflow.kind !== "coverage" && (
        <section className="cutoff-section">
          <h2>Report cutoff</h2>
          <p>
            Changing the cutoff clears the current report.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              dispatch({ type: "request" });
            }}
          >
            <label htmlFor="cutoff">Explicit UTC cutoff</label>
            <select
              id="cutoff"
              value={cutoff}
              disabled={busy}
              onChange={(event) =>
                dispatch({
                  type: "cutoff",
                  cutoff: event.target.value as Cutoff | "",
                })
              }
            >
              <option value="">Select a supported UTC example</option>
              {cutoffs.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <button disabled={!cutoff || busy || workflow.kind === "report"}>
              {workflow.kind === "reporting"
                ? "Preparing report…"
                : workflow.kind === "report-error"
                  ? "Retry synthetic report"
                  : "Request synthetic report"}
            </button>
          </form>
          {workflow.kind === "report-error" && (
            <p className="error-text" role="alert">
              {workflow.message}
            </p>
          )}
          {workflow.kind === "report" && (
            <p className="success">
              Report ready at {workflow.report.cutoff}.{" "}
              <a className="button" href="#forecast">Open forecast →</a>{" "}<a href="#overview">Overview</a>
            </p>
          )}
        </section>
      )}
    </>
  );
}
function UnavailableTasks() {
  return (
    <section className="method">
      <h2>Unavailable outputs</h2>
      <h3>Illness onset · unavailable</h3>
      <p>
        Requires validated onset labels, participant holdout, and a calibrated
        artifact. Wearable deviations do not establish infection.
      </p>
      <h3>Recovery · unavailable</h3>
      <p>
        Requires an ongoing episode, a prespecified resolution endpoint, and
        censoring-aware follow-up evaluation. No time-to-recovery estimate is
        generated.
      </p>
    </section>
  );
}
function Symptoms() {
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
        <h2>Symptom entry</h2>
        <p>Synthetic examples only. Nothing is saved or sent. Leaving this section or reloading clears the draft and preview.</p>
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
          <p>
            Local memory only. Reload clears this preview. Leaving this section
            also clears the draft.
          </p>
          <button className="secondary" onClick={() => setPreview(undefined)}>
            Clear preview
          </button>
        </section>
      )}
      <UnavailableTasks />
    </>
  );
}
function Sleep() {
  const [preset, setPreset] = useState("steady");
  const selected =
    preset === "steady"
      ? sleepPresets.steady
      : preset === "late"
        ? sleepPresets.late
        : undefined;
  return (
    <>
      <p className="lead">
        Compare two named schedules through static illustrations. These are not
        personal alertness predictions or equation-based simulations.
      </p>
      <section className="entry-form">
        <h2>Schedule illustration</h2>
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
              Provenance · manually drawn synthetic examples. A supported
              scientific simulation would require documented equations and
              validated personal prediction would require measured alertness
              labels and held-out evaluation.
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
