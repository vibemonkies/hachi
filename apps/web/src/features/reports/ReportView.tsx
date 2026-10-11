import type {
  AnomalyResult,
  Coverage,
  ForecastSeries,
  ImportStatus,
  ReportResult,
} from "@hachi/contracts";
import type { Design } from "../../App";
import type { ReportPair, TaskResult } from "./api";
import type { Section } from "../../workflow";

const labels: Record<string, string> = {
  heart_rate: "Heart rate",
  resting_heart_rate_vendor: "Resting heart rate (vendor)",
  hrv_sdnn: "HRV · SDNN",
  hrv_rmssd: "HRV · RMSSD",
  respiratory_rate: "Respiratory rate",
  oxygen_saturation: "Oxygen saturation",
  wrist_temperature_deviation: "Wrist temperature deviation",
  body_temperature: "Body temperature",
  steps: "Steps",
  active_energy: "Active energy",
  walking_running_distance: "Walking and running distance",
};

export function ReportView({
  section,
  design,
  subject,
  coverage,
  asOf,
  reports,
}: {
  section: Section;
  design: Design;
  subject: { subjectId: string; imported: ImportStatus | null };
  coverage: Coverage;
  asOf: string;
  reports: ReportPair;
}) {
  const taskResults = section === "anomaly"
    ? [{ title: "Baseline deviation", task: reports.anomaly, kind: "anomaly" as const, expectedTask: "anomaly" as const }]
    : section === "forecast"
      ? [{ title: "Forecast", task: reports.forecast, kind: "forecast" as const, expectedTask: "physiology_forecast" as const }]
      : [
          { title: "Forecast", task: reports.forecast, kind: "forecast" as const, expectedTask: "physiology_forecast" as const },
          { title: "Baseline deviation", task: reports.anomaly, kind: "anomaly" as const, expectedTask: "anomaly" as const },
        ];

  return (
    <>
      <div className="report-meta">
        <p>As of <strong>{asOf}</strong></p>
        <span className={`mode-badge mode-${coverage.data_mode}`}>{coverage.data_mode} data</span>
        <span>{subject.imported ? `Import · ${subject.imported.import_id}` : `Subject · ${subject.subjectId}`}</span>
        <a href="#import">Review coverage or change cutoff</a>
      </div>
      {section === "overview" && (
        <div className="reading-list">
          <a href="#forecast"><span>Forecast report</span><strong>{resultTitle(reports.forecast, "physiology_forecast")}</strong><span>Open forecast values and provenance</span></a>
          <a href="#anomaly"><span>Baseline deviation</span><strong>{resultTitle(reports.anomaly, "anomaly")}</strong><span>Open anomaly timeline and alert state</span></a>
        </div>
      )}
      {taskResults.map(({ title, task, kind, expectedTask }) => (
        <TaskResultPanel key={kind} title={title} task={task} expectedTask={expectedTask} expanded={design === "analysis"} />
      ))}
      {(section === "overview" || section === "anomaly") && (
        <UnavailableTasks coverage={coverage} />
      )}
    </>
  );
}

function resultTitle(task: TaskResult, expectedTask: "physiology_forecast" | "anomaly") {
  if (task.kind === "request-error") return "Request failed";
  const result = task.result;
  if (result.status === "unavailable") return "Unavailable";
  if (result.status === "error") return "Report error";
  if (result.task !== expectedTask) return "Unexpected result";
  return result.task === "anomaly" ? result.anomaly.alert_state.replaceAll("_", " ") : `${result.forecast.series.length} signal series`;
}

export function TaskResultPanel({
  title,
  task,
  expectedTask,
  expanded,
}: {
  title: string;
  task: TaskResult;
  expectedTask: "physiology_forecast" | "anomaly";
  expanded: boolean;
}) {
  if (task.kind === "request-error") {
    return <div className="notice error" role="alert"><h2>{title} request failed</h2><p>{task.message}</p></div>;
  }
  const result = task.result;
  if (result.status === "unavailable") {
    const explanation = result.reason_code === "NO_ARTIFACT_FOR_TASK"
      ? "No forecast model is set up for this data source yet."
      : result.reason_code === "INSUFFICIENT_HISTORY"
        ? "The available history is too sparse for this forecast."
        : null;
    return (
      <div className="notice">
        <h2>{title} unavailable</h2>
        {explanation && <p>{explanation}</p>}
        <p>Reason · <code>{result.reason_code}</code></p>
        <div className="result-identity">
          <span className={`mode-badge mode-${result.data_mode}`}>{result.data_mode} data</span>
          {result.replay && <span>REPLAY · {result.replay.recorded_at_utc}</span>}
          <span>Report · {result.report_id}</span>
          {result.provenance?.artifact && <span>Model · {result.provenance.artifact.artifact_id} · {result.provenance.artifact.artifact_sha256}</span>}
          {result.provenance?.dataset_snapshot && <span>Dataset · {result.provenance.dataset_snapshot.dataset_id} / {result.provenance.dataset_snapshot.dataset_version}</span>}
          <span>Code · {result.git_sha}</span>
        </div>
        <ul>{result.requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>
      </div>
    );
  }
  if (result.status === "error") {
    return <div className="notice error" role="alert"><h2>{title} error · {result.error_code}</h2><p>{result.message}</p><ResultIdentity result={result} /></div>;
  }
  if (result.task !== expectedTask) {
    return <div className="notice error" role="alert"><h2>{title} response mismatch</h2><p>The API returned a {result.task.replaceAll("_", " ")} result for a {expectedTask.replaceAll("_", " ")} request. It was not rendered as the requested chart.</p></div>;
  }

  if (expectedTask === "physiology_forecast" && result.task === "physiology_forecast") {
    const forecastSeries = result.forecast.series;
    const pointOnly = forecastSeries.length > 0 && forecastSeries.every(isPointOnly);
    return (
      <section className="result-card">
        <ResultIdentity result={result} />
        {result.warnings.filter((warning) => !(pointOnly && warning.code === "UNCALIBRATED_INTERVALS")).map((warning) => <p key={warning.code} className={`warning-line${warning.code === "DEVICE_SHIFT" ? " device-shift-warning" : ""}`}>
          {warning.code === "DEVICE_SHIFT" && <strong className="device-shift-label">Unvalidated device transfer</strong>}
          <strong>{warning.code.replaceAll("_", " ")}</strong> · {warning.message}
        </p>)}
        {forecastSeries.map((series) => <ForecastChart key={series.metric} series={series} expanded={expanded} asOf={result.as_of} />)}
        {result.forecast.unavailable_metrics.length > 0 && (
          <div className="notice">
            <h3>Requested signals unavailable</h3>
            <ul>{result.forecast.unavailable_metrics.map((item) => <li key={item.metric}>{labels[item.metric] ?? item.metric} · {item.reason_code}</li>)}</ul>
          </div>
        )}
      </section>
    );
  }

  if (result.task !== "anomaly") {
    return <div className="notice error" role="alert"><h2>{title} response mismatch</h2><p>The API returned an unsupported result type.</p></div>;
  }

  return (
    <section className="result-card">
      <ResultIdentity result={result} />
      {result.warnings.map((warning) => <p key={warning.code} className={`warning-line${warning.code === "DEVICE_SHIFT" ? " device-shift-warning" : ""}`}>
        {warning.code === "DEVICE_SHIFT" && <strong className="device-shift-label">Unvalidated device transfer</strong>}
        <strong>{warning.code.replaceAll("_", " ")}</strong> · {warning.message}
      </p>)}
      <AnomalyChart result={result} expanded={expanded} />
    </section>
  );
}

function ResultIdentity({ result }: { result: Extract<ReportResult, { status: "ok" | "error" }> }) {
  const artifact = result.status === "ok" ? result.provenance.artifact : null;
  const snapshot = result.status === "ok" ? result.provenance.dataset_snapshot : null;
  return (
    <div className="result-identity">
      <span className={`mode-badge mode-${result.data_mode}`}>{result.data_mode} data</span>
      {result.replay && <span className="mode-badge">REPLAY · {result.replay.recorded_at_utc}</span>}
      <span>Report · {result.report_id}</span>
      <span>Model · {artifact ? `${artifact.artifact_id} · ${artifact.artifact_sha256}` : "not available"}</span>
      {snapshot && <span>Dataset · {snapshot.dataset_id} / {snapshot.dataset_version}</span>}
      <span>Code · {result.git_sha}</span>
      {result.status === "ok" && result.provenance.feature_coverage.length > 0 && (
        <span>Input coverage · {result.provenance.feature_coverage.map((feature) => `${labels[feature.metric] ?? feature.metric} ${Math.round(feature.coverage * 100)}%`).join(" · ")}</span>
      )}
    </div>
  );
}

function isPointOnly(series: ForecastSeries) {
  return series.interval_calibration === "none" && series.nominal_coverage === null &&
    series.points.every((point) => point.lower === null && point.upper === null);
}

function ForecastChart({ series, expanded, asOf }: { series: ForecastSeries; expanded: boolean; asOf: string }) {
  const pointOnly = isPointOnly(series);
  const showBounds = series.interval_calibration !== "none" &&
    series.points.every((point) => point.lower !== null && point.upper !== null);
  const values = series.points.flatMap((point) => showBounds
    ? [point.lower as number, point.upper as number]
    : [point.median]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max === min ? Math.max(1, Math.abs(max) * 0.05) : (max - min) * 0.12;
  const low = min - range;
  const high = max + range;
  const start = Date.parse(asOf);
  const end = start + 24 * 60 * 60 * 1000;
  const x = (timestamp: string) => 58 + (Date.parse(timestamp) - start) * 560 / (end - start);
  const y = (value: number) => 220 - (value - low) / (high - low) * 170;
  const path = series.points.map((point, index) => `${index ? "L" : "M"}${x(point.interval_start_utc)},${y(point.median)}`).join(" ");
  const metricName = labels[series.metric] ?? series.metric.replaceAll("_", " ");
  return (
    <figure className="plot api-plot">
      <figcaption>
        <h2>{metricName} forecast · {series.unit}</h2>
        <p>Values and timestamps come directly from the hourly report response. Missing or unsupported signals remain unavailable instead of receiving a fabricated series.</p>
      </figcaption>
      {pointOnly ? (
        <p className="warning-line"><strong>Point estimates only.</strong> No interval bounds or coverage claim are supplied.</p>
      ) : series.interval_calibration === "none" ? (
        <p className="warning-line"><strong>No interval bounds.</strong> Median points are shown without an interval band or coverage claim.</p>
      ) : series.interval_calibration === "uncalibrated" ? (
        <p className="warning-line"><strong>Uncalibrated intervals.</strong> Bounds are displayed without a coverage claim.</p>
      ) : (
        <p className="caption">Nominal interval coverage · {series.nominal_coverage === null ? "not provided" : `${Math.round(series.nominal_coverage * 100)}%`}.</p>
      )}
      <div className="chart-scroll" tabIndex={0} role="region" aria-label={`${metricName} forecast chart in ${series.unit}`}>
        <svg viewBox="0 0 680 270" role="img" aria-label={`${metricName} median forecast${pointOnly ? " points without intervals" : " with interval bounds"}`}>
          {[low, (low + high) / 2, high].map((value) => <g key={value}><line x1="58" x2="640" y1={y(value)} y2={y(value)} className="grid-line" /><text x="8" y={y(value) + 4}>{value.toFixed(1)}</text></g>)}
          <text x="8" y="18">{series.unit}</text>
          {series.points.map((point) => <g key={point.interval_start_utc}>
            {showBounds && point.lower !== null && point.upper !== null && <line x1={x(point.interval_start_utc)} x2={x(point.interval_start_utc)} y1={y(point.lower)} y2={y(point.upper)} className="interval" />}
            <text x={x(point.interval_start_utc)} y="254" textAnchor="middle">{point.interval_start_utc.slice(5, 10)} {point.interval_start_utc.slice(11, 16)}</text>
          </g>)}
          <path d={path} className="series" />
          {series.points.map((point) => <circle key={point.interval_start_utc} cx={x(point.interval_start_utc)} cy={y(point.median)} r="4" className="dot" />)}
        </svg>
      </div>
      <details open={expanded}>
        <summary>View exact forecast values</summary>
        <div className="table-scroll" tabIndex={0} role="region" aria-label={`${metricName} forecast values`}>
          <table>
            <caption>{metricName} forecast in {series.unit}. Intervals: {pointOnly ? "not present" : series.interval_calibration === "validated" && series.nominal_coverage !== null ? `${Math.round(series.nominal_coverage * 100)}% nominal coverage` : "uncalibrated or unavailable; no coverage claim"}.</caption>
            <thead><tr><th scope="col">Interval start · UTC</th><th scope="col">Interval end · UTC</th>{series.points.some((point) => point.local_date) && <th scope="col">Local date</th>}<th scope="col">Median · {series.unit}</th><th scope="col">Lower · {series.unit}</th><th scope="col">Upper · {series.unit}</th></tr></thead>
            <tbody>{series.points.map((point) => <tr key={point.interval_start_utc}><td>{point.interval_start_utc}</td><td>{point.interval_end_utc}</td>{series.points.some((item) => item.local_date) && <td>{point.local_date ?? "Not applicable"}</td>}<td>{point.median}</td><td>{point.lower ?? "Not available"}</td><td>{point.upper ?? "Not available"}</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

function AnomalyChart({ result, expanded }: { result: AnomalyResult; expanded: boolean }) {
  const { anomaly } = result;
  const values = anomaly.timeline.flatMap((point) => point.score === null ? [] : [point.score]);
  if (values.length === 0) {
    return <div className="notice"><ResultIdentity result={result} /><h2>Detector abstained</h2><p>{anomaly.score_definition}</p><p>No timeline scores were available at this cutoff. An abstention is not a zero score or evidence of no risk.</p></div>;
  }
  const min = Math.min(0, ...values);
  const max = Math.max(anomaly.alert_threshold, ...values);
  const range = max === min ? 1 : max - min;
  const y = (value: number) => 220 - (value - min) / range * 170;
  const start = Date.parse(anomaly.baseline_window_start_utc);
  const end = Date.parse(anomaly.baseline_window_end_utc);
  const x = (timestamp: string) => 58 + (Date.parse(timestamp) - start) * 560 / Math.max(1, end - start);
  const path = anomaly.timeline.map((point, index) => {
    if (point.score === null) return "";
    const previous = anomaly.timeline[index - 1];
    const contiguous = previous !== undefined && previous.score !== null &&
      Date.parse(previous.interval_end_utc) === Date.parse(point.interval_start_utc);
    return `${contiguous ? "L" : "M"}${x(point.interval_start_utc)},${y(point.score)}`;
  }).join(" ");
  return (
    <figure className="plot api-plot">
      <figcaption><h2>Baseline deviation timeline · score</h2><p>{anomaly.score_definition}</p></figcaption>
      <p className="alert-state">Alert state · <strong>{anomaly.alert_state.replaceAll("_", " ")}</strong>{anomaly.score !== null && <> · Latest score {anomaly.score} · Threshold {anomaly.alert_threshold}</>}</p>
      <div className="chart-scroll" tabIndex={0} role="region" aria-label="Baseline deviation chart">
        <svg viewBox="0 0 680 270" role="img" aria-label={`Anomaly timeline, alert state ${anomaly.alert_state.replaceAll("_", " ")}`}>
          {[min, (min + max) / 2, max].map((value) => <g key={value}><line x1="58" x2="640" y1={y(value)} y2={y(value)} className="grid-line" /><text x="8" y={y(value) + 4}>{value.toFixed(2)}</text></g>)}
          <line x1="58" x2="640" y1={y(anomaly.alert_threshold)} y2={y(anomaly.alert_threshold)} className="threshold" />
          <text x="8" y="18">score</text>
          {anomaly.timeline.map((point) => <text key={point.interval_start_utc} x={x(point.interval_start_utc)} y="254" textAnchor="middle">{point.interval_start_utc.slice(5, 10)} {point.interval_start_utc.slice(11, 16)}</text>)}
          <path d={path} className="series" />
          {anomaly.timeline.map((point) => point.score === null ? <text key={point.interval_start_utc} x={x(point.interval_start_utc)} y="238" textAnchor="middle">abstained</text> : <circle key={point.interval_start_utc} cx={x(point.interval_start_utc)} cy={y(point.score)} r="4" className={point.alert ? "alert-dot" : "dot"} />)}
        </svg>
      </div>
      {anomaly.observed_alert_burden ? <p>Observed burden · {anomaly.observed_alert_burden.false_alert_episodes_per_30_healthy_days} false-alert episodes per 30 healthy days · {anomaly.observed_alert_burden.evaluation_report}</p> : <p className="caption">Observed alert burden has not been measured. This is deviation from a personal baseline, not an illness probability.</p>}
      <details open={expanded}>
        <summary>View exact timeline and changed features</summary>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Anomaly timeline values">
          <table><caption>Timeline from the report response. Missing scores indicate detector abstention.</caption><thead><tr><th scope="col">Interval start · UTC</th><th scope="col">Interval end · UTC</th><th scope="col">Score</th><th scope="col">Alert</th></tr></thead><tbody>{anomaly.timeline.map((point) => <tr key={point.interval_start_utc}><td>{point.interval_start_utc}</td><td>{point.interval_end_utc}</td><td>{point.score ?? "Abstained"}</td><td>{point.alert ? "Alert" : "No alert"}</td></tr>)}</tbody></table>
        </div>
        {anomaly.changed_features.length > 0 && <div className="table-scroll" tabIndex={0} role="region" aria-label="Changed features"><table><caption>Features contributing to the baseline deviation.</caption><thead><tr><th scope="col">Signal</th><th scope="col">Observed</th><th scope="col">Baseline median</th><th scope="col">Robust z</th><th scope="col">Unit</th></tr></thead><tbody>{anomaly.changed_features.map((feature) => <tr key={feature.metric}><th scope="row">{labels[feature.metric] ?? feature.metric}</th><td>{feature.observed}</td><td>{feature.baseline_median}</td><td>{feature.robust_z}</td><td>{feature.unit}</td></tr>)}</tbody></table></div>}
      </details>
      <p className="provenance-line">Baseline window · {anomaly.baseline_window_start_utc} to {anomaly.baseline_window_end_utc}</p>
    </figure>
  );
}

function UnavailableTasks({ coverage }: { coverage: Coverage }) {
  const tasks = coverage.task_support.filter((task) => task.task === "illness_onset" || task.task === "recovery");
  return (
    <section className="method unavailable-tasks">
      <h2>Illness and recovery</h2>
      {tasks.map((task) => (
        <div key={task.task}>
          <h3>{task.task === "illness_onset" ? "Illness onset" : "Recovery"}</h3>
          <p>{task.supported ? "Coverage indicates this task is supported. No illness or recovery report was requested in this workflow." : `Unavailable · ${task.reason_code ?? "UNSPECIFIED"}.`}</p>
        </div>
      ))}
    </section>
  );
}
