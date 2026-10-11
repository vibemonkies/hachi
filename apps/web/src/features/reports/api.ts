import type {
  AnomalyRequest,
  PhysiologyForecastHourlyRequest,
  ReportJob,
  ReportResult,
  SubjectId,
} from "@hachi/contracts";
import { ApiRequestError, apiUrl, isRecord, requestJson, waitForPoll } from "../api";

export type TaskResult =
  | { kind: "result"; result: ReportResult }
  | { kind: "request-error"; message: string };

export type ReportPair = { forecast: TaskResult; anomaly: TaskResult };

export function readReportJob(value: unknown): ReportJob {
  if (
    !isRecord(value) ||
    value.schema_version !== "0.1" ||
    typeof value.report_id !== "string" ||
    !["queued", "running", "completed"].includes(String(value.state)) ||
    !isRecord(value.request) ||
    (value.state === "completed" && !isRecord(value.result))
  ) {
    throw new Error("The Hachi API returned an invalid report job.");
  }
  return value as unknown as ReportJob;
}

export async function readSavedReplay(
  apiBaseUrl: string,
  signal: AbortSignal,
): Promise<ReportJob> {
  let response: Response;
  try {
    response = await fetch(apiUrl("/replay/report", apiBaseUrl), { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiRequestError("The offline replay provider could not be reached.");
  }
  if (!response.ok) {
    throw new ApiRequestError(`No valid saved replay is available (${response.status}).`);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiRequestError("The offline replay provider returned unreadable data.");
  }
  const job = readReportJob(body);
  if (job.state !== "completed" || !job.result?.replay) {
    throw new ApiRequestError("The saved report is incomplete or lacks replay provenance.");
  }
  return job;
}

async function requestReport(
  request: PhysiologyForecastHourlyRequest | AnomalyRequest,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<ReportResult> {
  let job = readReportJob(
    await requestJson<ReportJob>("/v1/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }, apiBaseUrl),
  );

  while (job.state !== "completed") {
    await waitForPoll(signal);
    job = readReportJob(
      await requestJson<ReportJob>(`/v1/reports/${encodeURIComponent(job.report_id)}`, { signal }, apiBaseUrl),
    );
  }

  if (!job.result) throw new Error("The completed report did not include a result.");
  return job.result;
}

async function settleReport(
  request: PhysiologyForecastHourlyRequest | AnomalyRequest,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<TaskResult> {
  try {
    return { kind: "result", result: await requestReport(request, signal, apiBaseUrl) };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return {
      kind: "request-error",
      message: error instanceof Error ? error.message : "The report request failed.",
    };
  }
}

export function requestForecastAndAnomaly(
  subjectId: SubjectId,
  asOf: string,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<ReportPair> {
  const forecast: PhysiologyForecastHourlyRequest = {
    schema_version: "0.1",
    subject_id: subjectId,
    as_of: asOf,
    task: "physiology_forecast",
    resolution: "hour",
    horizon_hours: 24,
    metrics: ["heart_rate"],
  };
  const anomaly: AnomalyRequest = {
    schema_version: "0.1",
    subject_id: subjectId,
    as_of: asOf,
    task: "anomaly",
  };

  return Promise.all([
    settleReport(forecast, signal, apiBaseUrl),
    settleReport(anomaly, signal, apiBaseUrl),
  ]).then(([forecastResult, anomalyResult]) => ({
    forecast: forecastResult,
    anomaly: anomalyResult,
  }));
}
