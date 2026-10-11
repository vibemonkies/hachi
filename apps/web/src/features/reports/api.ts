import type {
  AnomalyRequest,
  PhysiologyForecastHourlyRequest,
  ReportJob,
  ReportResult,
  SubjectId,
} from "@hachi/contracts";
import { ApiRequestError, isRecord, requestJson, waitForPoll } from "../api";
import { parseDocument } from "../checkins/schema";

export type TaskResult =
  | { kind: "result"; result: ReportResult }
  | { kind: "request-error"; message: string };

export type ReportPair = { forecast: TaskResult; anomaly: TaskResult };

export function readReportJob(value: unknown): ReportJob {
  try {
    return parseDocument("ReportJob", value);
  } catch {
    throw new Error("The Hachi API returned an invalid report job.");
  }
}

export async function readSavedReplay(
  signal: AbortSignal,
): Promise<ReportJob> {
  let response: Response;
  try {
    response = await fetch("/replay/report", { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiRequestError("The offline replay provider could not be reached.");
  }
  if (!response.ok) {
    if (response.status === 409) {
      let error: unknown;
      try {
        error = await response.json();
      } catch {
        throw new ApiRequestError("The offline replay provider returned an unreadable error.");
      }
      if (isRecord(error) && typeof error.error_code === "string" && error.live_fallback === false) {
        throw new ApiRequestError(`No valid saved replay is available (${error.error_code}).`);
      }
      throw new ApiRequestError("The offline replay provider returned an invalid conflict response.");
    }
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
  const matchesRequest = (job: ReportJob) =>
    job.request.subject_id === request.subject_id &&
    job.request.as_of === request.as_of &&
    job.request.task === request.task;
  let job = readReportJob(
    await requestJson<ReportJob>("/v1/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }, apiBaseUrl),
  );
  if (!matchesRequest(job)) throw new Error("The Hachi API returned a report for a different request.");

  while (job.state !== "completed") {
    await waitForPoll(signal);
    job = readReportJob(
      await requestJson<ReportJob>(`/v1/reports/${encodeURIComponent(job.report_id)}`, { signal }, apiBaseUrl),
    );
    if (!matchesRequest(job)) throw new Error("The Hachi API returned a report for a different request.");
  }

  if (!job.result) throw new Error("The completed report did not include a result.");
  if (
    job.result.report_id !== job.report_id ||
    job.result.subject_id !== request.subject_id ||
    job.result.as_of !== request.as_of ||
    ((job.result.status === "ok" || job.result.status === "unavailable") && job.result.task !== request.task)
  ) {
    throw new Error("The Hachi API returned a result that does not match its report request.");
  }
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
