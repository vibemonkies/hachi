import { useEffect, useState, type CSSProperties, type Dispatch, type FormEvent } from "react";
import type { Coverage, ImportStatus } from "@hachi/contracts";
import type { Action, ImportSubmission, Workflow } from "../../workflow";

const metricLabels: Record<string, string> = {
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
  sleep_in_bed: "Time in bed",
  sleep_asleep_unspecified: "Sleep · unspecified stage",
  sleep_asleep_core: "Sleep · core",
  sleep_asleep_deep: "Sleep · deep",
  sleep_asleep_rem: "Sleep · REM",
  sleep_awake: "Awake during sleep period",
};

const unavailableReasons: Record<string, string> = {
  NO_VALIDATED_ILLNESS_ARTIFACT: "No validated illness-onset artifact is served.",
  NO_VALIDATED_RECOVERY_ARTIFACT: "No validated recovery artifact is served.",
  NO_ARTIFACT_FOR_TASK: "No compatible model artifact is served for this task.",
  INSUFFICIENT_HISTORY: "The available history does not meet this task's minimum duration.",
  NO_SUPPORTED_METRICS: "The imported history has no metrics supported by this task.",
  METRIC_NOT_OBSERVED: "The required metric was not observed in this history.",
  LOW_COVERAGE: "Coverage is below the task's required level.",
  ONGOING_EPISODE: "The episode is still ongoing, so this task cannot be evaluated yet.",
  NO_ONGOING_EPISODE: "No ongoing episode is available for this task.",
  LABELS_UNAVAILABLE: "The outcome labels required by this task are unavailable.",
  DATA_ACCESS_PENDING: "Approved access to the required data is pending.",
};

function defaultTimeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function isUtcInstant(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().replace(".000Z", "Z") === value;
}

export function ImportPanel({
  workflow,
  dispatch,
}: {
  workflow: Workflow;
  dispatch: Dispatch<Action>;
}) {
  const [subjectId, setSubjectId] = useState("");
  const [timeZone, setTimeZone] = useState(defaultTimeZone);
  const [dataMode, setDataMode] = useState<"real" | "synthetic" | "">("");
  const [asOfDraft, setAsOfDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const activeImport = workflow.kind === "uploading" || workflow.kind === "importing";
  const busy = activeImport || workflow.kind === "coverage-loading" || workflow.kind === "reporting";
  const subject = "subject" in workflow ? workflow.subject : null;
  const coverage = "coverage" in workflow ? workflow.coverage : undefined;
  const currentAsOf = "asOf" in workflow ? workflow.asOf ?? "" : "";

  useEffect(() => setAsOfDraft(currentAsOf), [currentAsOf]);
  useEffect(() => {
    if (workflow.kind === "import-error") {
      setSubjectId(workflow.submission.subjectId);
      setTimeZone(workflow.submission.timeZone);
      setDataMode(workflow.submission.dataMode);
      setFile(workflow.submission.file);
    }
  }, [workflow]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(subjectId) || !dataMode) return;
    const submission: ImportSubmission = { file, subjectId, timeZone, dataMode };
    dispatch({ type: "begin-import", operationId: crypto.randomUUID(), submission });
  }

  function refreshCoverage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isUtcInstant(asOfDraft)) return;
    dispatch({
      type: "refresh-coverage",
      operationId: crypto.randomUUID(),
      asOf: asOfDraft,
    });
  }

  function openExistingSubject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(subjectId)) return;
    dispatch({ type: "begin-subject", operationId: crypto.randomUUID(), subjectId });
  }

  return (
    <>
      <section className="import-panel api-import-panel">
        <div>
          <span className="eyebrow">Apple Health export</span>
          <h2>Import your history</h2>
          <p>The selected file is sent to the configured local Hachi API for validation and import.</p>
        </div>
        <form onSubmit={submit}>
          <label htmlFor="apple-export">Export file (.zip or .xml)</label>
          <input
            id="apple-export"
            type="file"
            accept=".zip,.xml,application/zip,application/xml,text/xml"
            disabled={busy}
            onChange={(event) => setFile(event.currentTarget.files?.[0] ?? null)}
            required
          />
          <label htmlFor="subject-id">Pseudonymous subject ID</label>
          <input
            id="subject-id"
            autoComplete="off"
            value={subjectId}
            disabled={busy}
            onChange={(event) => setSubjectId(event.target.value)}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
            title="Start with a letter or digit. Use at most 128 letters, digits, underscores, or hyphens."
            required
          />
          <label htmlFor="timezone">Time zone in the export</label>
          <input
            id="timezone"
            autoComplete="off"
            value={timeZone}
            disabled={busy}
            onChange={(event) => setTimeZone(event.target.value)}
            placeholder="America/Los_Angeles"
            required
          />
          <label htmlFor="data-mode">Data mode</label>
          <select
            id="data-mode"
            value={dataMode}
            disabled={busy}
            onChange={(event) => setDataMode(event.target.value as "real" | "synthetic")}
          >
            <option value="" disabled>Choose the source mode</option>
            <option value="synthetic">Synthetic</option>
            <option value="real">Real</option>
          </select>
          <p className="caption">The mode must match the source. Upload only data approved for use in this workspace.</p>
          <button disabled={busy || !file || !subjectId || !timeZone || !dataMode}>
            {activeImport ? "Importing…" : "Import Apple Health export"}
          </button>
          <button className="text-button" type="button" onClick={() => dispatch({ type: "reset" })}>
            {busy ? "Cancel operation" : "Clear workspace"}
          </button>
        </form>
      </section>

      <section className="import-panel existing-subject-panel">
        <div>
          <span className="eyebrow">Existing API subject</span>
          <h2>Open saved history</h2>
          <p>Enter a subject ID already available to the configured API. No upload or subject discovery is performed.</p>
        </div>
        <form onSubmit={openExistingSubject}>
          <label htmlFor="existing-subject-id">Pseudonymous subject ID</label>
          <input
            id="existing-subject-id"
            autoComplete="off"
            value={subjectId}
            disabled={busy}
            onChange={(event) => setSubjectId(event.target.value)}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
            title="Start with a letter or digit. Use at most 128 letters, digits, underscores, or hyphens."
            required
          />
          <button disabled={busy || !subjectId}>Open subject coverage</button>
        </form>
      </section>

      <section className="import-panel existing-subject-panel">
        <div>
          <span className="eyebrow">Saved API response</span>
          <h2>Offline replay</h2>
          <p>Load the replay provider’s saved report and its recorded provenance. This does not request a live report.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => dispatch({ type: "begin-replay", operationId: crypto.randomUUID() })}>
          Open saved replay
        </button>
      </section>

      {activeImport && workflow.kind === "importing" && (
        <ImportProgress status={workflow.status} />
      )}
      {workflow.kind === "uploading" && (
        <p className="phase" role="status">Sending the export to the local API…</p>
      )}
      {workflow.kind === "coverage-loading" && (
        <p className="phase" role="status">Loading coverage at the selected UTC cutoff…</p>
      )}
      {workflow.kind === "reporting" && (
        <p className="phase" role="status">Forecast and anomaly reports are running. This page polls both jobs.</p>
      )}
      {workflow.kind === "import-error" && (
        <div className="notice error" role="alert">
          <h2>Import could not be completed</h2>
          {workflow.submission.importId && <p>Import · <code>{workflow.submission.importId}</code></p>}
          {workflow.failureCode && <p>Reason · <code>{workflow.failureCode}</code></p>}
          <p>{workflow.message}</p>
          {workflow.action && <p>Next step · {workflow.action}</p>}
          <button onClick={() => submitImportAgain(workflow.submission, dispatch)}>
            Retry import
          </button>
        </div>
      )}
      {workflow.kind === "coverage-error" && (
        <div className="notice error" role="alert">
          <h2>Coverage could not be loaded</h2>
          <p>{workflow.message}</p>
          {!workflow.coverage && (
            <button onClick={() => dispatch({ type: "retry-initial-coverage", operationId: crypto.randomUUID() })}>
              Retry coverage
            </button>
          )}
        </div>
      )}

      {coverage && subject && (
        <CoveragePanel
          subject={subject}
          coverage={coverage}
          asOfDraft={asOfDraft}
          onAsOfChange={setAsOfDraft}
          onRefresh={refreshCoverage}
          onRequestReports={() =>
            dispatch({ type: "begin-reports", operationId: crypto.randomUUID() })
          }
          canRequestReports={(workflow.kind === "coverage" || workflow.kind === "report") && !!workflow.asOf}
          reporting={workflow.kind === "reporting"}
          reportReady={workflow.kind === "report"}
          onReset={() => dispatch({ type: "reset" })}
        />
      )}
    </>
  );
}

function submitImportAgain(submission: ImportSubmission, dispatch: Dispatch<Action>) {
  dispatch({ type: "begin-import", operationId: crypto.randomUUID(), submission });
}

function ImportProgress({ status }: { status: ImportStatus }) {
  const counts = status.counts;
  return (
    <section className="notice" aria-live="polite">
      <h2>Import {status.state}</h2>
      <p>Import ID · <code>{status.import_id}</code></p>
      <p>Updated · {status.updated_at_utc}</p>
      {counts && (
        <ul className="count-list">
          <li>Accepted · {counts.records_accepted}</li>
          <li>Duplicates · {counts.records_duplicate}</li>
          <li>Unsupported · {counts.records_unsupported}</li>
          <li>Rejected · {counts.records_rejected}</li>
          <li>Quarantined · {counts.records_quarantined}</li>
        </ul>
      )}
      {status.record_issues.length > 0 && (
        <details>
          <summary>Record issues</summary>
          <ul>
            {status.record_issues.map((issue) => (
              <li key={`${issue.disposition}-${issue.code}`}>
                {issue.code.replaceAll("_", " ").toLowerCase()} · {issue.count} {issue.disposition}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function CoveragePanel({
  subject,
  coverage,
  asOfDraft,
  onAsOfChange,
  onRefresh,
  onRequestReports,
  canRequestReports,
  reporting,
  reportReady,
  onReset,
}: {
  subject: { subjectId: string; imported: ImportStatus | null };
  coverage: Coverage;
  asOfDraft: string;
  onAsOfChange: (value: string) => void;
  onRefresh: (event: FormEvent<HTMLFormElement>) => void;
  onRequestReports: () => void;
  canRequestReports: boolean;
  reporting: boolean;
  reportReady: boolean;
  onReset: () => void;
}) {
  const snapshot = coverage.dataset_snapshot;
  return (
    <>
      <section className="coverage api-coverage">
        <div className="coverage-heading">
          <div>
            <span className={`mode-badge mode-${coverage.data_mode}`}>{coverage.data_mode} data</span>
            <h2>Coverage review</h2>
          </div>
          <button className="secondary" onClick={onReset}>Start a new import</button>
        </div>
        <p>
          {subject.imported ? <>Import {subject.imported.import_id} · </> : <>Subject {subject.subjectId} · </>}
          {coverage.history} history · {coverage.generated_at_utc}.
          {coverage.span_start_utc && coverage.span_end_utc && (
            <> Available from {coverage.span_start_utc} through {coverage.span_end_utc}.</>
          )}
        </p>
        {snapshot && (
          <p className="provenance-line">
            Dataset · {snapshot.dataset_id} / {snapshot.dataset_version} · SHA-256 {snapshot.snapshot_sha256}
          </p>
        )}
        {coverage.history === "empty" && (
          <div className="notice" role="status">
            <h3>No observations are available</h3>
            <p>An empty history stays empty. No missing values are treated as zero.</p>
          </div>
        )}
        {coverage.metrics.length > 0 ? (
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Signal coverage">
            <table>
              <caption>Coverage as observed at the selected UTC cutoff. Source kinds identify the contributing device class.</caption>
              <thead>
                <tr><th scope="col">Signal</th><th scope="col">Unit</th><th scope="col">Coverage</th><th scope="col">Date span · UTC</th><th scope="col">Longest gap</th><th scope="col">Sources</th></tr>
              </thead>
              <tbody>
                {coverage.metrics.map((metric) => (
                  <tr key={metric.metric}>
                    <th scope="row">{metricLabels[metric.metric] ?? metric.metric.replaceAll("_", " ")}</th>
                    <td>{metric.unit}</td>
                    <td>
                      <span className="coverage-bar" style={{ "--coverage": `${Math.max(0, Math.min(1, metric.coverage)) * 100}%` } as CSSProperties} />
                      {Math.round(metric.coverage * 100)}% · {metric.days_with_data} days
                    </td>
                    <td>{metric.first_utc} to {metric.last_utc}</td>
                    <td>{metric.longest_gap_hours} h</td>
                    <td>{metric.source_kinds.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : coverage.history !== "empty" ? (
          <p>No supported metrics are available at this cutoff.</p>
        ) : null}

        <div className="task-support" aria-label="Available task support">
          {coverage.task_support.map((task) => (
            <p key={task.task}>
              <strong>{task.task.replaceAll("_", " ")}</strong> · {task.supported ? "data requirements met" : unavailableReasons[task.reason_code ?? ""] ?? task.reason_code}
              {!task.supported && task.reason_code && <code>{task.reason_code}</code>}
            </p>
          ))}
        </div>
      </section>

      <section className="cutoff-section">
        <h2>Choose a report cutoff</h2>
        <p>Enter the UTC instant exactly, including the trailing Z. Browser local time is ignored. Coverage reloads at this cutoff before reports run.</p>
        <form onSubmit={onRefresh} className="cutoff-form">
          <label htmlFor="as-of">As of · UTC</label>
          <input
            id="as-of"
            type="text"
            inputMode="text"
            autoComplete="off"
            placeholder="2026-10-10T07:00:00Z"
            value={asOfDraft}
            onChange={(event) => onAsOfChange(event.target.value)}
            pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
            title="Enter an ISO 8601 UTC instant ending in Z, such as 2026-10-10T07:00:00Z."
            required
          />
          <button>Review coverage at this cutoff</button>
        </form>
        {canRequestReports && (
          <button disabled={reporting} onClick={onRequestReports}>
            {reporting ? "Reports running…" : reportReady ? "Run reports again" : "Run forecast and anomaly reports"}
          </button>
        )}
      </section>
    </>
  );
}
