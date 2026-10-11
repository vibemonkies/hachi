import type { Coverage, DataMode, ImportStatus } from "@hachi/contracts";
import { isRecord, requestJson, waitForPoll } from "../api";

function readImportStatus(value: ImportStatus): ImportStatus {
  if (
    !isRecord(value) ||
    value.schema_version !== "0.1" ||
    typeof value.import_id !== "string" ||
    typeof value.subject_id !== "string" ||
    !["pending", "running", "succeeded", "failed"].includes(String(value.state)) ||
    !Array.isArray(value.record_issues)
  ) {
    throw new Error("The Hachi API returned an invalid import status.");
  }
  return value;
}

function readCoverage(value: Coverage): Coverage {
  if (
    !isRecord(value) ||
    value.schema_version !== "0.1" ||
    typeof value.subject_id !== "string" ||
    !["empty", "insufficient", "sufficient"].includes(String(value.history)) ||
    !Array.isArray(value.metrics) ||
    !Array.isArray(value.task_support)
  ) {
    throw new Error("The Hachi API returned invalid coverage data.");
  }
  return value;
}

export async function submitImport(
  file: File,
  subjectId: string,
  timeZone: string,
  dataMode: DataMode,
  signal: AbortSignal,
): Promise<ImportStatus> {
  const sourceFormat = file.name.toLowerCase().endsWith(".zip")
    ? "apple_health_export_zip"
    : "apple_health_export_xml";
  const query = new URLSearchParams({
    subject_id: subjectId,
    tz_name: timeZone,
    source_format: sourceFormat,
    data_mode: dataMode,
  });
  const status = await requestJson<ImportStatus>(`/v1/imports?${query}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
    signal,
  });
  return readImportStatus(status);
}

export async function pollImport(
  importId: string,
  signal: AbortSignal,
  onProgress: (status: ImportStatus) => void,
): Promise<ImportStatus> {
  for (;;) {
    const status = readImportStatus(
      await requestJson<ImportStatus>(`/v1/imports/${encodeURIComponent(importId)}`, { signal }),
    );
    onProgress(status);
    if (status.state === "succeeded" || status.state === "failed") return status;
    await waitForPoll(signal);
  }
}

export async function getCoverage(
  subjectId: string,
  asOf: string | null,
  signal: AbortSignal,
): Promise<Coverage> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return readCoverage(
    await requestJson<Coverage>(
      `/v1/subjects/${encodeURIComponent(subjectId)}/coverage${query}`,
      { signal },
    ),
  );
}

export async function getInitialCoverage(
  subjectId: string,
  signal: AbortSignal,
): Promise<{ coverage: Coverage; asOf: string }> {
  const initial = await getCoverage(subjectId, null, signal);
  const asOf = latestHour(initial.span_end_utc);
  return {
    coverage: asOf ? await getCoverage(subjectId, asOf, signal) : initial,
    asOf,
  };
}

function latestHour(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  date.setUTCMinutes(0, 0, 0);
  return date.toISOString().replace(".000Z", "Z");
}
