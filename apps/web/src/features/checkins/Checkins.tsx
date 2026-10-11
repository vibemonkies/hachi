import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ReportJob,
  ReportResult,
  SelfReportEntry,
  SelfReportHistory,
  SymptomOnsetEntry,
} from "../../../../../contracts/typescript/index";
import { createCheckinApi, type CheckinApi } from "./client";
import { EntryForm } from "./EntryForm";
import { entryRequest, episodeRoot, label, supersededId } from "./form";
import "./checkins.css";
import { supportsCorrections } from "./schema";
import { ResultStatus } from "./ResultStatus";

type HistoryState =
  | { kind: "loading" }
  | { kind: "ready"; history: SelfReportHistory; versions: SelfReportEntry[] }
  | { kind: "error"; message: string };
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The request failed. Retry when the API is ready.";
export function Checkins(props: {
  subjectId: string;
  apiBaseUrl: string;
  asOf?: string;
}) {
  return (
    <CheckinWorkspace
      key={`${props.apiBaseUrl}|${props.subjectId}`}
      {...props}
    />
  );
}
function CheckinWorkspace({
  subjectId,
  apiBaseUrl,
  asOf,
}: {
  subjectId: string;
  apiBaseUrl: string;
  asOf?: string;
}) {
  const api = useMemo(() => createCheckinApi(apiBaseUrl), [apiBaseUrl]);
  const [state, setState] = useState<HistoryState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState<{
    kind: "save" | "delete";
    message: string;
  } | null>(null);
  const [editing, setEditing] = useState<SelfReportEntry>();
  const [formSequence, setFormSequence] = useState(0);
  const [deleting, setDeleting] = useState<SelfReportEntry>();
  const deletionTrigger = useRef<HTMLButtonElement | null>(null);
  const historyReload = useRef<HTMLButtonElement | null>(null);
  async function loadHistory() {
    const history = await api.history(subjectId);
    const versions = supportsCorrections
      ? (await api.history(subjectId, "all")).entries
      : history.entries;
    return { kind: "ready", history, versions } satisfies HistoryState;
  }
  async function deleteEntry(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!deleting) return;
    if (
      new FormData(event.currentTarget).get("confirm-entry") !==
      deleting.entry_id
    ) {
      setError({
        kind: "delete",
        message: "Type the exact entry identifier to confirm deletion.",
      });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteEntry(subjectId, deleting.entry_id);
      setDeleting(undefined);
      setFeedback(
        "This entry and every version were deleted from the backend.",
      );
      await reload();
      requestAnimationFrame(() => historyReload.current?.focus());
    } catch (error) {
      setError({ kind: "delete", message: message(error) });
    } finally {
      setBusy(false);
    }
  }

  async function reload() {
    setState({ kind: "loading" });
    try {
      setState(await loadHistory());
      return true;
    } catch (error) {
      setState({ kind: "error", message: message(error) });
      return false;
    }
  }
  useEffect(() => {
    let active = true;
    loadHistory().then(
      (state) => {
        if (active) setState(state);
      },
      (error) => {
        if (active) setState({ kind: "error", message: message(error) });
      },
    );
    return () => {
      active = false;
    };
  }, [api, subjectId]);
  const entries = state.kind === "ready" ? state.history.entries : [];
  const versions = state.kind === "ready" ? state.versions : [];
  const currentOnsets = entries.filter(
    (entry): entry is SymptomOnsetEntry => entry.kind === "symptom_onset",
  );
  const onsets = currentOnsets.flatMap((onset) => {
    try {
      return [{ ...onset, entry_id: episodeRoot(onset, versions) }];
    } catch {
      return [];
    }
  });
  async function save(entry: SelfReportEntry) {
    setBusy(true);
    setError(null);
    setFeedback("");
    try {
      await api.save(subjectId, entryRequest(entry));
      setFeedback("Check-in saved to the backend.");
      setEditing(undefined);
      setFormSequence((value) => value + 1);
      if (await reload())
        setFeedback(
          "Check-in saved to the backend. History has been read back.",
        );
      return true;
    } catch (error) {
      setError({ kind: "save", message: message(error) });
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="checkins">
      <p>
        Self-reports supply observed labels. They do not diagnose illness or
        establish a validated recovery prediction.
      </p>
      {feedback && (
        <p className="checkin-feedback" role="status">
          {feedback}
        </p>
      )}
      <>
        <div className="checkin-layout">
          <EntryForm
            key={`${editing?.entry_id ?? "new"}|${formSequence}`}
            initialEntry={editing}
            onCancel={editing ? () => setEditing(undefined) : undefined}
            onsets={onsets}
            busy={busy}
            onSave={save}
            saveError={error?.kind === "save" ? error.message : undefined}
          />
          <section aria-label="Saved check-in history">
            <h2>Saved history</h2>
            <p>
              Read from the API for the selected subject.{" "}
              {supportsCorrections
                ? "Corrections create a new version with its own entry time; earlier versions remain available for prior cutoffs."
                : "This API version supports saving and reloading; correction and per-entry deletion are not yet available."}
            </p>
            <button
              type="button"
              className="secondary"
              ref={historyReload}
              disabled={busy || state.kind === "loading"}
              onClick={() => void reload()}
            >
              Reload saved history
            </button>
            {state.kind === "loading" && (
              <p role="status">Loading saved entries…</p>
            )}
            {state.kind === "error" && (
              <p role="alert" className="error-text">
                {state.message}
              </p>
            )}
            {state.kind === "ready" && entries.length === 0 && (
              <p>
                No recorded check-ins. Missing surveys are unknown, never
                negative labels.
              </p>
            )}
            <ol className="checkin-history">
              {entries.map((entry) => (
                <li key={entry.entry_id}>
                  <h3>{label(entry.kind)}</h3>
                  <EntryDetails entry={entry} />
                  {supersededId(entry) && (
                    <p>
                      Corrected version · replaces {supersededId(entry)}.
                      Correction entry time is shown above.
                    </p>
                  )}
                  {supportsCorrections && (
                    <div className="checkin-actions">
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() => {
                          setEditing(entry);
                          setError(null);
                        }}
                      >
                        Correct this {label(entry.kind)}
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={(event) => {
                          deletionTrigger.current = event.currentTarget;
                          setError(null);
                          setDeleting(entry);
                        }}
                      >
                        Delete this {label(entry.kind)}
                      </button>
                    </div>
                  )}
                  {entry.kind === "symptom_onset" && (
                    <EpisodeRecovery
                      api={api}
                      subjectId={subjectId}
                      onset={entry}
                      entries={entries}
                      versions={versions}
                      asOf={asOf}
                    />
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
        {deleting && (
          <section
            className="checkin-delete"
            key={deleting.entry_id}
            aria-label="Confirm entry deletion"
          >
            <h2>Delete {label(deleting.kind)} and its versions?</h2>
            <p>
              All versions are removed from every cutoff. Clinical reports that
              used this entry will be recomputed. Referenced onsets require
              deleting their resolution first.
            </p>
            <form onSubmit={deleteEntry}>
              {error?.kind === "delete" && (
                <p role="alert" className="error-text">
                  {error.message}
                </p>
              )}
              <label htmlFor="confirm-entry">
                Type {deleting.entry_id} to confirm
              </label>
              <input
                id="confirm-entry"
                autoFocus
                name="confirm-entry"
                autoComplete="off"
                required
                disabled={busy}
              />
              <div className="checkin-actions">
                <button disabled={busy}>Delete entry permanently</button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    setDeleting(undefined);
                    setError(null);
                    deletionTrigger.current?.focus();
                  }}
                >
                  Cancel deletion
                </button>
              </div>
            </form>
          </section>
        )}
      </>
    </section>
  );
}
export function EntryDetails({ entry }: { entry: SelfReportEntry }) {
  const rows: [string, string][] = [["Entry time · UTC", entry.entered_at_utc]];
  switch (entry.kind) {
    case "symptom_onset":
      rows.push(
        [
          "Onset window · UTC",
          `${entry.onset_earliest_utc} to ${entry.onset_latest_utc}`,
        ],
        ["Symptoms", entry.symptoms.map(label).join(", ")],
        ["Severity", `${entry.severity} / 3`],
      );
      break;
    case "symptom_checkin":
      rows.push(
        [
          "Observed period · UTC",
          `${entry.period_start_utc} to ${entry.period_end_utc}`,
        ],
        [
          "Status",
          entry.symptoms_present
            ? `${entry.symptoms.map(label).join(", ")} · severity ${entry.severity} / 3`
            : "No symptoms observed in this period",
        ],
      );
      break;
    case "symptom_resolution":
      rows.push(
        [
          "Resolution window · UTC",
          `${entry.resolved_earliest_utc} to ${entry.resolved_latest_utc}`,
        ],
        ["Linked onset", entry.onset_entry_id],
      );
      break;
    case "test_result":
      rows.push(
        [
          "Collection window · UTC",
          `${entry.collected_earliest_utc} to ${entry.collected_latest_utc}`,
        ],
        [
          "Test",
          `${label(entry.pathogen)} · ${label(entry.method)} · ${entry.result}`,
        ],
      );
      break;
    case "alertness_rating":
      rows.push(
        ["Rating time · UTC", entry.rated_at_utc],
        ["KSS · 1–9", `${entry.value} (higher = sleepier)`],
      );
      break;
    case "pvt_result":
      rows.push(
        ["PVT start · UTC", entry.started_at_utc],
        [
          "Measured result",
          `${entry.duration_seconds} s · ${entry.trials} trials · ${entry.mean_reaction_time_ms} ms mean · ${entry.lapses} lapses`,
        ],
      );
      break;
    case "confounder":
      rows.push(
        [
          "Occurrence window · UTC",
          `${entry.occurred_earliest_utc} to ${entry.occurred_latest_utc}`,
        ],
        ["Factor", label(entry.factor)],
      );
      break;
    default: {
      const exhaustive: never = entry;
      return exhaustive;
    }
  }
  return (
    <dl>
      {rows.map(([title, value]) => (
        <div key={title} style={{ display: "contents" }}>
          <dt>{title}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function EpisodeRecovery(props: {
  api: CheckinApi;
  subjectId: string;
  onset: SymptomOnsetEntry;
  entries: SelfReportEntry[];
  versions: SelfReportEntry[];
  asOf?: string;
}) {
  try {
    const root = episodeRoot(props.onset, props.versions);
    return (
      <RecoveryPanel
        key={`${root}|${props.asOf}|${props.entries.map((entry) => entry.entry_id).join("|")}`}
        {...props}
        onset={{ ...props.onset, entry_id: root }}
      />
    );
  } catch (error) {
    return <p role="alert">{message(error)}</p>;
  }
}
function RecoveryPanel({
  api,
  subjectId,
  onset,
  entries,
  asOf,
}: {
  api: CheckinApi;
  subjectId: string;
  onset: SymptomOnsetEntry;
  entries: SelfReportEntry[];
  asOf?: string;
}) {
  const [job, setJob] = useState<ReportJob>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const resolved = entries.some(
    (entry) =>
      entry.kind === "symptom_resolution" &&
      entry.onset_entry_id === onset.entry_id,
  );
  useEffect(() => {
    if (!job || job.state === "completed") return;
    let active = true;
    const timer = setTimeout(() => {
      api.report(job.report_id).then(
        (next) => {
          if (active) setJob(next);
        },
        (error) => {
          if (active) {
            setError(message(error));
            setBusy(false);
          }
        },
      );
    }, 750);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, job]);
  async function request() {
    setJob(undefined);
    setBusy(true);
    setError("");
    try {
      setJob(
        await api.recovery({
          schema_version: "0.1",
          subject_id: subjectId,
          task: "recovery",
          as_of: asOf ?? new Date().toISOString(),
          episode_id: onset.entry_id,
        }),
      );
    } catch (error) {
      setError(message(error));
      setBusy(false);
    }
  }
  return (
    <section className="method">
      <h3>Recovery for this episode</h3>
      <p>
        {resolved
          ? "A resolution has been recorded. Recovery reports still use only entries known by the requested cutoff."
          : "No resolution follow-up has been recorded for this episode; missing follow-up does not mean recovery."}
      </p>
      <p>Report cutoff · {asOf ?? "current time when requested"}</p>
      <button
        type="button"
        className="secondary"
        disabled={busy && job?.state !== "completed"}
        onClick={() => void request()}
      >
        Request recovery report
      </button>
      {job && job.state !== "completed" && (
        <p role="status">Recovery report {job.state}…</p>
      )}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {job?.result && (
        <>
          <ResultStatus result={job.result} />
          <RecoveryResult result={job.result} episodeId={onset.entry_id} />
        </>
      )}
    </section>
  );
}
function RecoveryResult({
  result,
  episodeId,
}: {
  result: ReportResult;
  episodeId: string;
}) {
  if (result.status === "unavailable")
    return (
      <div role="status">
        <h3>Recovery unavailable · {label(result.reason_code)}</h3>
        <ul>
          {result.requirements.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
    );
  if (result.status === "error") return <p role="alert">{result.message}</p>;
  if (result.task !== "recovery" || result.recovery.episode_id !== episodeId)
    return (
      <p role="alert">
        The report did not match this episode. Reload and retry.
      </p>
    );
  return (
    <>
      <p>{result.recovery.endpoint_definition}</p>
      <p>
        Supported follow-up · {result.recovery.supported_follow_up_days} days.
        Median time after cutoff ·{" "}
        {result.recovery.median_days_after_as_of === null
          ? "not reached within supported follow-up"
          : `${result.recovery.median_days_after_as_of} days`}
        .
      </p>
      <table>
        <caption>Probability of remaining symptomatic after the cutoff</caption>
        <thead>
          <tr>
            <th>Days</th>
            <th>Probability</th>
          </tr>
        </thead>
        <tbody>
          {result.recovery.survival.map((point) => (
            <tr key={point.days_after_as_of}>
              <td>{point.days_after_as_of}</td>
              <td>{point.probability_still_symptomatic}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Mode · {result.data_mode}. Artifact ·{" "}
        {result.provenance.artifact.artifact_id}.
      </p>
    </>
  );
}
