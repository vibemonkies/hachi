import { useState, type Dispatch, type FormEvent } from "react";
import { cutoffs, scenarios, sleepPresets } from "./fixtures";
import { Plot } from "./components";
import type { Action, Cutoff, Scenario, Section, Workflow } from "./workflow";
export function SectionView({
  section,
  workflow,
  dispatch,
}: {
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
        <h2>A report starts with usable history.</h2>
        <p>
          Load synthetic observations, acknowledge coverage, and request a
          report at an explicit UTC cutoff.
        </p>
        <a className="button" href="#import">
          Go to import & coverage
        </a>
      </div>
    );
  const { report, history } = workflow;
  return (
    <>
      <div className="report-meta">
        <span>STATIC SYNTHETIC REPORT</span>
        <p>
          Cutoff <strong>{report.cutoff}</strong>
        </p>
        <a href="#import">Change cutoff</a>
      </div>
      {section === "overview" ? (
        <>
          <p className="lead">
            One history. Separate questions. Each output carries its own
            evidence limits.
          </p>
          <div className="reading-list">
            <a href="#forecast">
              <span>01 / Physiology forecast</span>
              <strong>
                {report.forecast.kind === "illustrative"
                  ? "Illustrative hourly heart rate"
                  : "Unavailable"}
              </strong>
              <span>Next 24 hours →</span>
            </a>
            <a href="#anomaly">
              <span>02 / Anomaly monitoring</span>
              <strong>
                {report.anomaly.kind === "illustrative"
                  ? "Deviation from a historical baseline"
                  : "Unavailable"}
              </strong>
              <span>Review changes →</span>
            </a>
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
            description={`Synthetic example medians and illustrative lower/upper intervals. Intervals are uncalibrated, with no nominal coverage claim. Horizon starts ${report.cutoff} and ends 24 hours later.`}
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
          <p className="lead">
            An unusual signal is a prompt to inspect context. It is not an
            illness probability.
          </p>
          <Plot
            panel={report.anomaly}
            title="Historical baseline deviation"
            unit="score"
            description="Synthetic standardized absolute deviation from a personal historical baseline. Zero means baseline-like; larger scores mean greater deviation. No alert threshold or measured alert burden is established."
          />
          <div className="method">
            <h3>How to read this example</h3>
            <p>
              Baseline window · {report.baseline}. Each point represents the
              completed daily window ending at its timestamp, using earlier
              observations only.
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
          </div>
        </>
      )}
    </>
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
      <p className="lead">
        Before interpreting a signal, see what was observed and what is missing.
        Start with a local, synthetic history.
      </p>
      <section className="import-panel">
        <div>
          <span className="eyebrow">01 / SOURCE</span>
          <h2>A history you can inspect.</h2>
          <p>
            No files are read or uploaded. Choose a demonstration scenario to
            explore success, missing data, and failures.
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
          <span className="eyebrow">02 / COVERAGE</span>
          <h2>What the history supports.</h2>
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
          <span className="eyebrow">03 / REPORT CUTOFF</span>
          <h2>Freeze the point in time.</h2>
          <p>
            Select a named supported fixture. Changing the cutoff removes the
            current report immediately.
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
              <a href="#overview">Open overview →</a>
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
      <h2>Questions still awaiting evidence.</h2>
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
      <p className="lead">
        Explore how an event time differs from the time an entry is made. Use
        synthetic examples only.
      </p>
      <form className="entry-form" onSubmit={submit}>
        <h2>Preview a synthetic symptom entry.</h2>
        <p>No free text or personal identifiers. Nothing is saved or sent.</p>
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
        <h2>Choose a schedule illustration.</h2>
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
          <section className="method">
            <h3>Fixed assumptions for both examples</h3>
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
          </section>
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
