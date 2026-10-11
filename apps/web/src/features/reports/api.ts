import type {
  AnomalyRequest,
  PhysiologyForecastHourlyRequest,
  ReportJob,
  ReportResult,
  SubjectId,
} from "@hachi/contracts";
import { isRecord, requestJson, waitForPoll } from "../api";

export type TaskResult =
  | { kind: "result"; result: ReportResult }
  | { kind: "request-error"; message: string };

export type ReportPair = { forecast: TaskResult; anomaly: TaskResult };

function readReportJob(value: ReportJob): ReportJob {
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
  return value;
}

async function requestReport(
  request: PhysiologyForecastHourlyRequest | AnomalyRequest,
  signal: AbortSignal,
): Promise<ReportResult> {
  let job = readReportJob(
    await requestJson<ReportJob>("/v1/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }),
  );

  while (job.state !== "completed") {
    await waitForPoll(signal);
    job = readReportJob(
      await requestJson<ReportJob>(`/v1/reports/${encodeURIComponent(job.report_id)}`, { signal }),
    );
  }

  if (!job.result) throw new Error("The completed report did not include a result.");
  return job.result;
}

async function settleReport(
  request: PhysiologyForecastHourlyRequest | AnomalyRequest,
  signal: AbortSignal,
): Promise<TaskResult> {
  try {
    return { kind: "result", result: await requestReport(request, signal) };
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
    settleReport(forecast, signal),
    settleReport(anomaly, signal),
  ]).then(([forecastResult, anomalyResult]) => ({
    forecast: forecastResult,
    anomaly: anomalyResult,
  }));
}
