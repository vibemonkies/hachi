import { useMemo, useState, type FormEvent } from "react";
import type {
  AlertnessResult,
  ReportResult,
  ScenarioRequest,
} from "../../../../../contracts/typescript/index";
import { createCheckinApi } from "../checkins/client";
import { TimeField, NumberField, Choice } from "../checkins/EntryForm";
import { label } from "../checkins/form";
import { scenarioRequest } from "./request";
import "../checkins/checkins.css";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; request: ScenarioRequest; result: ReportResult };
export function ScenarioComparison(props: {
  subjectId: string;
  apiBaseUrl: string;
}) {
  return (
    <Comparison key={`${props.subjectId}|${props.apiBaseUrl}`} {...props} />
  );
}
function Comparison({
  subjectId,
  apiBaseUrl,
}: {
  subjectId: string;
  apiBaseUrl: string;
}) {
  const api = useMemo(() => createCheckinApi(apiBaseUrl), [apiBaseUrl]);
  const [state, setState] = useState<State>({ kind: "idle" });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const request = scenarioRequest(new FormData(form), subjectId);
      setState({ kind: "loading" });
      const result = await api.scenario(request);
      setState({ kind: "ready", request, result });
    } catch (error) {
      setState({
        kind: "error",
        message:
          error instanceof Error
            ? error.message
            : "Comparison failed. Check the input and retry.",
      });
    }
  }
  return (
    <section className="scenario-comparison">
      <p>
        Compare two schedules using the API’s sleep-pressure and circadian model
        when available. Simulation is distinct from measured personal alertness
        prediction.
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={state.kind === "loading"}>
          <legend>Schedules and explicit assumptions</legend>
          <label htmlFor="timezone">IANA timezone for both schedules</label>
          <input
            id="timezone"
            name="timezone"
            placeholder="America/Los_Angeles"
            required
          />
          <p>
            Enter local wall-clock dates and times in this timezone. The API
            checks daylight-saving gaps and sleep duration. Ambiguous fall-back
            clocks use the first occurrence.
          </p>
          <div className="checkin-pair">
            {["a", "b"].map((id) => (
              <fieldset key={id}>
                <legend>Schedule {id.toUpperCase()}</legend>
                <TimeField
                  name={`bed_${id}`}
                  title="Bedtime · local date and time"
                />
                <TimeField
                  name={`wake_${id}`}
                  title="Wake time · local date and time"
                />
              </fieldset>
            ))}
          </div>
          <NumberField
            name="prior_sleep"
            title="Sleep in the 24 hours before the first bedtime · hours"
            min={0}
            max={24}
            step="any"
          />
          <Choice
            name="caffeine"
            title="Caffeine assumption"
            options={[
              ["none", "No caffeine"],
              ["not_modeled", "Caffeine effects not modeled"],
            ]}
          />
          <p>
            Light exposure effects are not modeled. This schema does not support
            light intensity, caffeine dose, naps or medication inputs.
          </p>
          <button>
            {state.kind === "loading" ? "Comparing…" : "Compare schedules"}
          </button>
        </fieldset>
      </form>
      {state.kind === "error" && (
        <p role="alert" className="error-text">
          {state.message}
        </p>
      )}
      {state.kind === "loading" && (
        <p role="status">Requesting comparison from the backend…</p>
      )}
      {state.kind === "ready" && (
        <section aria-label="Schedule comparison result">
          <h2>Comparison result</h2>
          <p>
            Submitted assumptions · {state.request.tz_name}; prior sleep{" "}
            {state.request.assumptions.prior_sleep_hours} hours; caffeine{" "}
            {label(state.request.assumptions.caffeine)}; light exposure not
            modeled.
          </p>
          <ul>
            {state.request.schedules.map((schedule) => (
              <li key={schedule.schedule_id}>
                Schedule {schedule.schedule_id.toUpperCase()} · bedtime{" "}
                {schedule.bedtime_local}, wake {schedule.wake_time_local}
              </li>
            ))}
          </ul>
          <p>
            Data mode · {state.result.data_mode}. Cutoff · {state.result.as_of}.
          </p>
          {state.result.status === "unavailable" ? (
            <div role="status">
              <h3>
                Comparison unavailable · {label(state.result.reason_code)}
              </h3>
              <ul>
                {state.result.requirements.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          ) : state.result.status === "error" ? (
            <p role="alert">{state.result.message}</p>
          ) : state.result.task === "alertness" ? (
            <Curves result={state.result} />
          ) : (
            <p role="alert">
              The API returned a different task. Reload and retry.
            </p>
          )}
        </section>
      )}
    </section>
  );
}
function Curves({ result }: { result: AlertnessResult }) {
  const payload = result.alertness;
  const invalidValidation =
    payload.mode === "validated_prediction" && payload.validation === null;
  if (invalidValidation)
    return (
      <p role="alert">
        Personal prediction evidence is missing. No validated prediction can be
        displayed.
      </p>
    );
  return (
    <>
      <h3>
        {payload.mode === "simulation"
          ? "Sleep-pressure / circadian simulation"
          : "Measured alertness prediction"}
      </h3>
      {payload.mode === "simulation" && (
        <p>
          No measured personal accuracy or energy claim. Changing a schedule is
          a hypothetical comparison, not evidence of a causal personal benefit.
        </p>
      )}
      <p>{payload.model_description}</p>
      <p>
        {payload.scale.name} · {payload.scale.unit}, {payload.scale.minimum}–
        {payload.scale.maximum}. Higher means{" "}
        {payload.scale.higher_is_more_alert ? "more alert" : "less alert"}.
      </p>
      <p>
        Computed assumptions · {payload.tz_name}; prior sleep{" "}
        {payload.assumptions.prior_sleep_hours} hours; caffeine{" "}
        {label(payload.assumptions.caffeine)}; light exposure{" "}
        {label(payload.assumptions.light_exposure)}.
      </p>
      {payload.curves.map((curve) => (
        <section key={curve.schedule_id}>
          <h3>Schedule {curve.schedule_id.toUpperCase()}</h3>
          <CurvePlot result={result} scheduleId={curve.schedule_id} />
          <div
            className="table-scroll"
            role="region"
            aria-label={`Schedule ${curve.schedule_id} values`}
            tabIndex={0}
          >
            <table>
              <caption>Backend values · schedule {curve.schedule_id}</caption>
              <thead>
                <tr>
                  <th>Time · UTC</th>
                  <th>
                    {payload.scale.name} · {payload.scale.unit}
                  </th>
                </tr>
              </thead>
              <tbody>
                {curve.points.map((point) => (
                  <tr key={point.time_utc}>
                    <td>{point.time_utc}</td>
                    <td>{point.value.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      {payload.validation && (
        <p>
          Measured validation · {payload.validation.metric}:{" "}
          {payload.validation.value}, {payload.validation.n_observations}{" "}
          observations. Evidence · {payload.validation.report}.
        </p>
      )}
      {result.warnings.map((warning) => (
        <p key={warning.code}>{warning.message}</p>
      ))}
      <p>
        Artifact · {result.provenance.artifact.artifact_id}; code ·{" "}
        {result.git_sha}.
      </p>
    </>
  );
}
function CurvePlot({
  result,
  scheduleId,
}: {
  result: AlertnessResult;
  scheduleId: string;
}) {
  const curve = result.alertness.curves.find(
    (curve) => curve.schedule_id === scheduleId,
  );
  if (!curve) return null;
  const start = Date.parse(curve.points[0].time_utc);
  const end = Date.parse(curve.points[curve.points.length - 1].time_utc);
  const scale = result.alertness.scale;
  if (end <= start || scale.maximum <= scale.minimum)
    return (
      <p>The curve has no valid plotting range. See the exact values below.</p>
    );
  const points = curve.points
    .map(
      (point) =>
        `${45 + ((Date.parse(point.time_utc) - start) / (end - start)) * 640},${180 - ((point.value - scale.minimum) / (scale.maximum - scale.minimum)) * 150}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 720 225"
      role="img"
      aria-label={`Schedule ${scheduleId} ${scale.name} curve; exact times and values in the following table`}
    >
      <path
        d="M45 30V180H685"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
      />
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <text x="10" y="35" fontSize="12" fill="currentColor">
        {scale.maximum}
      </text>
      <text x="10" y="180" fontSize="12" fill="currentColor">
        {scale.minimum}
      </text>
      <text x="45" y="205" fontSize="12" fill="currentColor">
        {curve.points[0].time_utc}
      </text>
      <text x="685" y="205" textAnchor="end" fontSize="12" fill="currentColor">
        {curve.points[curve.points.length - 1].time_utc}
      </text>
    </svg>
  );
}
